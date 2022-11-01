from typing import Union, cast, Optional
from bpy.types import UIList, Context, UILayout, Panel, SpaceProperties, Operator, Object, Mesh, PropertyGroup, Menu
from bpy.props import StringProperty, EnumProperty, BoolProperty

from itertools import chain
import operator
from functools import reduce

from . import shape_key_ops, ui_material_remap, utils, ui_uv_maps
from .registration import register_module_classes_factory
from .extensions import (
    ArmatureSettings,
    MaterialSettings,
    MeshSettings,
    ModifierSettings,
    ObjectBuildSettings,
    ObjectPropertyGroup,
    ScenePropertyGroup,
    ShapeKeySettings,
    UVSettings,
    VertexGroupSettings,
    WindowManagerPropertyGroup,
    WmObjectToggles,
    WmArmatureToggles,
    WmMeshToggles,
)
from .integration import check_gret_shape_key_apply_modifiers
from .context_collection_ops import (
    CollectionAddBase,
    CollectionMoveBase,
    CollectionRemoveBase,
    ContextCollectionOperatorBase,
    PropCollectionType,
)
from .utils import id_property_group_copy


# Constants used as item ids for properties to copy
_GENERAL = 'GENERAL'
_ARMATURE_POSE = 'POSE'
_MESH_VERTEX_GROUPS = 'VERTEX_GROUPS'
_MESH_SHAPE_KEYS = 'SHAPE_KEYS'
_MESH_MODIFIERS = 'MODIFIERS'
_MESH_UV_LAYERS = 'UV_LAYERS'
_MESH_MATERIALS = 'MATERIALS'
_MESH_VERTEX_COLORS = 'VERTEX_COLORS'
_ALL = 'ALL'
_ALL_MESH = 'ALL_MESH'
_ALL_ARMATURE = 'ALL_ARMATURE'
_ALL_COPY_PROP_IDENTIFIERS = (
    _GENERAL, _ARMATURE_POSE, _MESH_VERTEX_GROUPS, _MESH_SHAPE_KEYS, _MESH_MODIFIERS, _MESH_UV_LAYERS, _MESH_MATERIALS,
    _MESH_VERTEX_COLORS, _ALL, _ALL_MESH, _ALL_ARMATURE
)


class CopyObjectProperties(Operator):
    """Copy Object properties from the active object to other selected objects or a different group on the active
    object"""
    bl_idname = 'copy_object_props'
    bl_label = "Copy Properties"
    bl_options = {'REGISTER', 'UNDO'}

    # Icons match UI boxes in ui_object.py
    # Since we're using the 'ENUM_FLAG' option, the unique values for the items must represent a bit field
    _general_items = ((_GENERAL, "General", "General Object settings", 'OBJECT_DATA', 1 << 0),)
    _armature_items = ((_ARMATURE_POSE, "Pose", "Pose settings", 'ARMATURE_DATA', 1 << 1),)
    _mesh_items = (
        (_MESH_VERTEX_GROUPS, "Vertex Groups", "Vertex Group settings", 'GROUP_VERTEX', 1 << 2),
        (_MESH_SHAPE_KEYS, "Shape Keys", "Shape Key settings", 'SHAPEKEY_DATA', 1 << 3),
        (_MESH_MODIFIERS, "Modifiers", "Modifier settings", 'MODIFIER_DATA', 1 << 4),
        (_MESH_UV_LAYERS, "UV Layers", "UV Layer settings", 'GROUP_UVS', 1 << 5),
        (_MESH_MATERIALS, "Materials", "Material settings", 'MATERIAL_DATA', 1 << 6),
        (_MESH_VERTEX_COLORS, "Vertex Colors", "Vertex Color settings", 'GROUP_VCOL', 1 << 7),
    )

    # Shortcuts for groups of items at a time
    # Bitwise ORs of groups of the items. Note that if we call with operator with {_MESH_MODIFIERS} as the
    # props_to_copy, for example, the received set will actually be {_ALL, _MESH_MODIFIERS, _ALL_MESH}. I guess Blender
    # does a bitwise AND and checks for non-zero result, so both of the options will be present in the set. Therefore,
    # _ALL and the other grouped items should only be used as an input to the Operator and should not be used within the
    # Operator itself
    _grouped_items = (
        (
            _ALL,
            "All",
            "All settings",
            'DUPLICATE',
            # Compute bitwise OR via a reduce operation
            reduce(operator.or_, (item[4] for item in chain(_general_items, _armature_items, _mesh_items)), 0)
        ),
        (
            _ALL_ARMATURE,
            "All Armature",
            "All settings for Armature Objects",
            'ARMATURE_DATA',
            reduce(operator.or_, (item[4] for item in chain(_general_items, _armature_items)), 0)
        ),
        (
            _ALL_MESH,
            "All Mesh",
            "All settings for Mesh Objects",
            'MESH_DATA',
            reduce(operator.or_, (item[4] for item in chain(_general_items, _mesh_items)), 0)
        )
    )

    _props_to_copy_items = _general_items + _armature_items + _mesh_items + _grouped_items

    paste_to_name: StringProperty(
        name="Paste To",
        description="Name of the settings to paste to. When empty, will default to the currently displayed settings of"
                    " the active Object"
    )
    props_to_copy: EnumProperty(
        items=_props_to_copy_items,
        options={'ENUM_FLAG'},
        default={_ALL},
    )
    mode: EnumProperty(
        items=(
            ('OTHER_SELECTED', "Other Selected", "Other selected objects"),
            ('SELF', "Self", "Self"),
        ),
        default='OTHER_SELECTED',
        description="Mode to specify which objects to paste to",
    )
    create: BoolProperty(
        name="Create",
        description="Create new settings when the pasted to settings don't already exist",
        default=True
    )

    def draw(self, context: Context):
        layout = self.layout
        layout.prop(self, 'mode')
        layout.prop(self, 'paste_to_name')
        layout.prop(self, 'create')

    def execute(self, context: Context) -> set[str]:
        props_to_copy: set[str] = self.props_to_copy
        # Remove the grouped items from the set
        props_to_copy = props_to_copy.difference(item[0] for item in self._grouped_items)
        if not props_to_copy:
            # No properties to copy, so nothing to do. The user can change the properties, so we still need to push an
            # undo
            return {'FINISHED'}
        mode = self.mode
        copy_object = context.object
        copy_from_settings = ObjectPropertyGroup.get_group(copy_object).get_displayed_settings(context.scene)
        paste_settings_name = self.paste_to_name
        if copy_from_settings is None:
            self.report({'ERROR'}, "Currently displayed Object settings not found")
            # Nothing the user can change will cause the Operator to do anything, so don't push an undo
            return {'CANCELLED'}

        # When the settings to paste to is the empty string, default to the currently visible settings (which we are
        # copying from)
        if not paste_settings_name:
            paste_settings_name = copy_from_settings.name

        # Get the objects we're  pasting to
        paste_objects = set()
        if mode == 'OTHER_SELECTED':
            allowed_types = ObjectPropertyGroup.ALLOWED_TYPES
            paste_objects = set(o for o in context.selected_objects if o.type in allowed_types)
            # Exclude self
            paste_objects.discard(copy_object)
        elif mode == 'SELF':
            paste_objects = {copy_object}

            # If we're pasting to the same Object and settings we're copying from, there's nothing to do, so we can skip
            if copy_from_settings.name == paste_settings_name:
                return {'FINISHED'}

        create = self.create
        for paste_to_obj in paste_objects:
            settings_col = ObjectPropertyGroup.get_group(paste_to_obj).object_settings
            if paste_settings_name in settings_col:
                paste_to_settings = settings_col[paste_settings_name]
            elif create:
                paste_to_settings = settings_col.add()
                paste_to_settings.name_prop = paste_settings_name
            else:
                continue

            paste_to_mesh_settings = paste_to_settings.mesh_settings
            copy_from_mesh_settings = copy_from_settings.mesh_settings

            if _GENERAL in props_to_copy:
                paste_to_settings.join_order = copy_from_settings.join_order
                paste_to_settings.target_object_name = copy_from_settings.target_object_name
                paste_to_mesh_settings.ignore_reduce_to_two_meshes = copy_from_mesh_settings.ignore_reduce_to_two_meshes

            if _ARMATURE_POSE in props_to_copy:
                id_property_group_copy(copy_from_settings, paste_to_settings, 'armature_settings')

            def copy_mesh_group(paste_prop):
                id_property_group_copy(copy_from_mesh_settings, paste_to_mesh_settings, paste_prop)

            if _MESH_MATERIALS in props_to_copy:
                copy_mesh_group('material_settings')

            if _MESH_MODIFIERS in props_to_copy:
                copy_mesh_group('modifier_settings')

            if _MESH_UV_LAYERS in props_to_copy:
                copy_mesh_group('uv_settings')

            if _MESH_VERTEX_GROUPS in props_to_copy:
                copy_mesh_group('vertex_group_settings')

            if _MESH_SHAPE_KEYS in props_to_copy:
                copy_mesh_group('shape_key_settings')

            if _MESH_VERTEX_COLORS in props_to_copy:
                copy_mesh_group('vertex_color_settings')

        return {'FINISHED'}


def _generate_menu_classes() -> dict[str, type[Menu]]:
    """Since we can't provide arguments to menus, we need to create a menu for each different option.
    We can then make a lookup to get the correct menu .bl_idname based on the option.
    Additionally, the generated classes are added to the module's globals() so that registration will pick them up."""
    lookup: dict[str, type[Menu]] = {}

    # Base class for a menu for copying properties from one object settings to another on the same object
    class CopyObjectPropsSelfMenuBase(Menu):
        bl_label = "Copy To..."

        props = {_ALL}

        def draw(self, context: Context):
            layout = self.layout
            scene = context.scene

            object_group = ObjectPropertyGroup.get_group(context.object)
            displayed_settings = object_group.get_displayed_settings(scene)
            # We exclude the currently displayed settings as there's no point in pasting to the same settings that we're
            # copying from
            if displayed_settings:
                all_build_settings_names = {displayed_settings.name}
            else:
                # Generally there will always be some displayed settings
                all_build_settings_names = set()

            at_least_one_drawn = False

            for build_settings in chain(ScenePropertyGroup.get_group(scene).build_settings, object_group.object_settings):
                name = build_settings.name
                if name not in all_build_settings_names:
                    all_build_settings_names.add(name)
                    options = layout.operator(CopyObjectProperties.bl_idname, text=name)
                    options.mode = 'SELF'
                    options.paste_to_name = name
                    options.props_to_copy = self.props
                    at_least_one_drawn = True

            if not at_least_one_drawn:
                layout.label(text="No Other Scene Settings Found")

    # Base class for a menu for copying properties from the active object to other selected objects and for displaying
    # the menu for copying properties from one object settings to another on the same object
    class CopyObjectPropsMenuBase(Menu):
        bl_label = "Copy Properties"
        props = {_ALL}
        sub_menu: type[Menu]

        def draw(self, context: Context):
            layout = self.layout
            options = layout.operator(CopyObjectProperties.bl_idname, text="Copy To Other Selected Objects")
            options.mode = 'OTHER_SELECTED'
            options.paste_to_name = ''
            options.props_to_copy = self.props

            layout.separator()

            layout.menu(self.sub_menu.bl_idname)

    for prop_id in _ALL_COPY_PROP_IDENTIFIERS:
        props_set = {prop_id}
        # Lowercase name will be appended to the bl_idnames
        lower_name = prop_id.lower()
        # PascalCase name will be appended to the name of the attribute added to the module's globals() and the
        # subclass' name
        pascal_case_name = prop_id.replace('_', ' ').title().replace(" ", "")

        # (sub)Menu subclass for copying properties to other settings on the same object
        self_menu_name = f'CopyObjectPropsSelfMenu{pascal_case_name}'
        self_menu_class_attributes = dict(
            bl_idname='object_build_settings_copy_self_' + lower_name,
            props=props_set,
        )
        self_menu_class = cast(
            type[CopyObjectPropsSelfMenuBase],
            type(self_menu_name, (CopyObjectPropsSelfMenuBase,), self_menu_class_attributes)
        )

        # Menu subclass for copying properties to other selected objects or showing the submenu for copying properties
        # to other settings on the same object
        copy_menu_name = f'CopyObjectPropsMenu{pascal_case_name}'
        copy_menu_class_attributes = dict(
            bl_idname='object_build_settings_copy_' + lower_name,
            props=props_set,
            sub_menu=self_menu_class
        )
        copy_menu_class = cast(
            type[CopyObjectPropsMenuBase],
            type(copy_menu_name, (CopyObjectPropsMenuBase,), copy_menu_class_attributes)
        )

        # Add classes to module globals so that they will be picked up for registration
        g = globals()
        g[self_menu_name] = self_menu_class
        g[copy_menu_name] = copy_menu_class
        # While we only need the .bl_idname of the class, the lookup has to have class values because registration
        # modifies the .bl_idname of registered classes to include prefixes
        lookup[prop_id] = copy_menu_class

    return lookup


_COPY_MENU_LOOKUP: dict[str, type[Menu]] = _generate_menu_classes()


class ObjectBuildSettingsUIList(UIList):
    bl_idname = "object_build_settings"

    def draw_item(self, context: Context, layout: UILayout, data, item: ObjectBuildSettings, icon, active_data, active_property, index=0,
                  flt_flag=0):
        scene_group = ScenePropertyGroup.get_group(context.scene)
        scene_settings = scene_group.build_settings

        scene_active_name = scene_group.get_active().name
        is_scene_active = item.name == scene_active_name

        index_in_scene_settings = scene_settings.find(item.name)
        is_orphaned = index_in_scene_settings == -1

        row = layout.row(align=True)
        #row.label(text="", icon="SETTINGS")
        if is_scene_active:
            row_icon = "SCENE_DATA"
        elif is_orphaned:
            #row_icon = "ORPHAN_DATA"
            #row_icon = "LIBRARY_DATA_BROKEN"
            #row_icon = "UNLINKED"
            row_icon = "GHOST_DISABLED"
            row.alert = True
        else:
            row_icon = "BLANK1"
        # We could instead display the prop of the scene settings if it exists, which would make changing the name of
        # ObjectBuildSettings also change the name of the connected SceneBuildSettings
        # row.prop(item if is_orphaned else scene_settings[index_in_scene_settings], 'name_prop', text="", emboss=False, icon=row_icon)
        row.prop(item, 'name_prop', text="", emboss=False, icon=row_icon)
        row.alert = False
        row.prop(item, "include_in_build", text="")
        #row.alert = True
        #row.enabled = not is_scene_active


class ObjectPanel(Panel):
    bl_idname = "object_panel"
    bl_label = "Avatar Builder"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    #bl_category = "AvatarBuilder"
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: Context):
        # guaranteed to be SpaceProperties by the bl_space_type
        space_data = cast(SpaceProperties, context.space_data)
        pin_id = space_data.pin_id
        if pin_id is not None:
            # pin object is guaranteed to be an Object because of the bl_context = "object" which says this Panel is
            # only displayed in the Object Properties tab. The Object Properties tab is not available if Object Data is
            # pinned
            obj = pin_id
        else:
            obj = context.object

        # TODO: Currently, we're only building these types, should we be including any others?
        # TODO: Make the set a global variable and uses it elsewhere too
        if not obj or obj.type not in ObjectPropertyGroup.ALLOWED_TYPES:
            return False
        scene = context.scene
        # Build settings must be non-empty
        # TODO: Should add a 'clean' or 'purge' button to Scene panel that purges non-existent build settings from all
        #       objects in the current scene. This is because we otherwise have no way to remove the object settings
        #       if we hide the panel when there's no build settings
        return ScenePropertyGroup.get_group(scene).build_settings

    @staticmethod
    def draw_expandable_header(properties_col: UILayout, ui_toggle_data: PropertyGroup, ui_toggle_prop: str,
                               enabled: bool, copy_type: Union[tuple[str, ...], str], **header_args):
        """Draw an expandable header
        :return: a box UILayout when expanded, otherwise None"""
        header_row = properties_col.row(align=True)
        header_row.use_property_split = False
        is_expanded = getattr(ui_toggle_data, ui_toggle_prop)
        expand_icon = 'DISCLOSURE_TRI_DOWN' if is_expanded else 'DISCLOSURE_TRI_RIGHT'
        # We draw everything in the header as the toggle property so that any of it can be clicked on to expand the
        # contents.
        # To debug the clickable regions of the header, set emboss to True in each .prop call.
        header_row.prop(ui_toggle_data, ui_toggle_prop, text="", icon=expand_icon, emboss=False)

        # If we left align the entire header row, it won't expand to fill the entire width, meaning the user
        # can't click on anywhere in the header to expand it, so we create a sub_row that is left aligned and draw
        # the header text there
        sub_row = header_row.row(align=True)
        sub_row.alignment = 'LEFT'
        # Force emboss to be disabled
        header_args['emboss'] = False
        sub_row.prop(ui_toggle_data, ui_toggle_prop, **header_args)

        # We then need a third element to expand and fill the rest of the header, ensuring that the entire header can be
        # clicked on.
        # Text needs to be non-empty to actually expand, this does cut the header text off slightly when the Panel is
        # made very narrow, but this will have to do.
        # toggle=1 will hide the tick box
        header_row.prop(ui_toggle_data, ui_toggle_prop, text=" ", toggle=1, emboss=False)

        # Draw menu button for copying properties to other groups or other selected objects
        menu = _COPY_MENU_LOOKUP.get(copy_type)
        if menu:
            # Sub row without align so that the button appears disconnected from the third element
            menu_row = header_row.row(align=False)
            menu_row.menu(menu.bl_idname, text="", icon="PASTEDOWN")

        if is_expanded:
            # Create a box that the properties will be drawn in
            box = properties_col.box()
            # If the settings are disabled, disable the box to make it extra visible that the settings are disabled
            box.enabled = enabled
            # Add a small gap after the box to help separate it from the next header
            properties_col.separator()
            # Create a column within the box for the properties to go in and return it
            return box.column()
        else:
            # The header isn't expanded, so don't return anything for properties to go in
            return None

    @staticmethod
    def draw_general_object_box(properties_col: UILayout, settings: ObjectBuildSettings,
                                ui_toggle_data: WmObjectToggles, enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'general', enabled, _GENERAL,
                                                 text="Object", icon='OBJECT_DATA')
        if box:
            box.prop(settings, 'target_object_name')
            box.prop(settings, 'join_order')

    @staticmethod
    def draw_armature_box(properties_col: UILayout, settings: ArmatureSettings, obj: Object,
                          ui_toggle_data: WmArmatureToggles, enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'pose', enabled, _ARMATURE_POSE,
                                                 text="Pose", icon='ARMATURE_DATA')
        if box:
            export_pose = settings.armature_export_pose

            box.prop(settings, 'armature_export_pose')

            armature_preserve_volume_col = box.column()
            armature_preserve_volume_col.enabled = export_pose != 'REST'
            armature_preserve_volume_col.prop(settings, 'armature_export_pose_preserve_volume')

            armature_pose_custom_col = box.column()
            armature_pose_custom_col.enabled = export_pose.startswith("CUSTOM")
            if export_pose == 'CUSTOM_POSE_LIBRARY' and obj.pose_library:
                pose_library = obj.pose_library

                if pose_library:
                    armature_pose_custom_col.prop_search(
                        settings,
                        'armature_export_pose_library_marker',
                        pose_library,
                        'pose_markers', icon="DOT")
            else:
                # TODO: elif for `export_pose == 'CUSTOM_ASSET_LIBRARY':`
                armature_pose_custom_col.enabled = False
                armature_pose_custom_col.prop(settings, 'armature_export_pose_library_marker', icon="DOT")

    @staticmethod
    def draw_vertex_groups_box(properties_col: UILayout, settings: VertexGroupSettings, ui_toggle_data: WmMeshToggles,
                               enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'vertex_groups', enabled,
                                                 _MESH_VERTEX_GROUPS, text="Vertex Groups", icon='GROUP_VERTEX')
        if box:
            box.prop(settings, 'remove_non_deform_vertex_groups')
            # TODO: Remove empty vertex groups? Probably not very important, since it won't result in much
            #  extra data, assuming they even get exported at all

    @staticmethod
    def draw_shape_keys_box(properties_col: UILayout, settings: ShapeKeySettings, me: Mesh,
                            ui_toggle_data: WmMeshToggles, enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'shape_keys', enabled,
                                                 _MESH_SHAPE_KEYS, text="Shape keys", icon='SHAPEKEY_DATA')
        if box:
            main_op_col = box.column()
            main_op_col.prop(settings, 'shape_keys_main_op')

            main_op = settings.shape_keys_main_op
            if main_op == 'CUSTOM':
                shape_key_ops.draw_shape_key_ops(box, settings, me.shape_keys)

    @staticmethod
    def draw_mesh_modifiers_box(properties_col: UILayout, settings: ModifierSettings, ui_toggle_data: WmMeshToggles,
                                enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'modifiers', enabled, _MESH_MODIFIERS,
                                                 text="Modifiers", icon='MODIFIER_DATA')
        if box:
            if settings.apply_non_armature_modifiers == 'APPLY_KEEP_SHAPES_GRET':
                gret_available = check_gret_shape_key_apply_modifiers()
                box.alert = not gret_available
                box.prop(settings, 'apply_non_armature_modifiers')

                if not gret_available:
                    if gret_available is None:
                        box.label("Gret addon operator not found")
                    else:
                        box.label("Unsupported version of Gret")
                box.alert = False
            else:
                box.prop(settings, 'apply_non_armature_modifiers')

    @staticmethod
    def draw_uv_layers_box(properties_col: UILayout, settings: UVSettings, me: Mesh, ui_toggle_data: WmMeshToggles,
                           enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'uv_layers', enabled, _MESH_UV_LAYERS,
                                                 text="UV Layers", icon='GROUP_UVS')
        if box:
            box.prop(settings, 'uv_maps_to_keep')
            # Guaranteed to not be empty because we only call this function when it's non-empty
            uv_layers = me.uv_layers
            uv_maps_to_keep = settings.uv_maps_to_keep
            if uv_maps_to_keep == 'FIRST':
                box.prop(uv_layers[0], 'name', emboss=False)
            elif uv_maps_to_keep == 'SINGLE':
                box.prop_search(settings, 'keep_only_uv_map', me, 'uv_layers', icon="GROUP_UVS")
            elif uv_maps_to_keep == 'LIST':
                ui_uv_maps.draw_uv_map_list(box, settings.keep_uv_map_list)

    @staticmethod
    def draw_materials_box(properties_col: UILayout, settings: MaterialSettings, obj: Object,
                           ui_toggle_data: WmMeshToggles, enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'materials', enabled, _MESH_MATERIALS,
                                                 text="Materials", icon='MATERIAL_DATA')
        if box:
            box.prop(settings, 'materials_main_op')

            main_op = settings.materials_main_op
            if main_op == 'KEEP_SINGLE':
                slot_index = settings.keep_only_mat_slot
                mat_slots = obj.material_slots
                num_slots = len(mat_slots)
                # 0.4 split with a label in the first part of the split and an operator in the second part of the split
                # seems to match properties with non-empty text displayed with UILayout.use_property_split
                split = box.split(factor=0.4, align=True)
                # Only applies to the label, not sure if there's a way to align the text within a .operator
                split.alignment = 'RIGHT'
                split.label(text="Material")
                # For some reason .alert causes .alignment to be ignored, so we have to put the operator in a
                # sub-layout, so we can set .alert on that instead
                sub = split.row()
                if num_slots != 0:
                    if 0 <= slot_index < num_slots:
                        mat = mat_slots[slot_index].material
                        if mat:
                            sub.operator(ui_material_remap.KeepOnlyMaterialSlotSearch.bl_idname, text=mat.name,
                                         icon_value=utils.get_preview(mat).icon_id)
                        else:
                            sub.operator(ui_material_remap.KeepOnlyMaterialSlotSearch.bl_idname, text="(empty slot)",
                                         icon='MATERIAL_DATA')
                    else:
                        sub.alert = True
                        sub.operator(ui_material_remap.KeepOnlyMaterialSlotSearch.bl_idname, text="(invalid slot)",
                                     icon='ERROR')
                else:
                    # Generally this will never be displayed because the Materials box is only drawn if the mesh's materials
                    # list isn't empty
                    sub.alert = True
                    sub.operator(ui_material_remap.KeepOnlyMaterialSlotSearch.bl_idname, text="(no material slots)",
                                 icon='ERROR')
            elif main_op == 'REMAP_SINGLE':
                mat = settings.remap_single_material
                if mat:
                    box.prop(settings, 'remap_single_material', icon_value=utils.get_preview(mat).icon_id)
                else:
                    box.prop(settings, 'remap_single_material')
            elif main_op == 'REMAP':
                ui_material_remap.draw_material_remap_list(box, obj, settings.materials_remap)

    def draw_mesh_boxes(self, properties_col: UILayout, settings: MeshSettings, obj: Object,
                        ui_toggle_data: WmMeshToggles, enabled: bool):
        me = cast(Mesh, obj.data)
        if obj.vertex_groups:
            self.draw_vertex_groups_box(properties_col, settings.vertex_group_settings, ui_toggle_data, enabled)
        # Only draw the shape keys box if there is more than one shape key. When there's one shape key, it will be the
        # reference key, the 'Basis'.
        # Note that non-relative shape keys are not supported at this time
        # TODO: Find out if (and if so, how) Blender's FBX exporter supports non-relative shape keys
        if me.shape_keys and len(me.shape_keys.key_blocks) > 1:
            self.draw_shape_keys_box(properties_col, settings.shape_key_settings, me, ui_toggle_data, enabled)
        # We don't touch armature modifiers, so only include the modifiers box when there's at least one non-armature
        # modifier
        # Additionally, modifiers which are disabled in the viewport get removed, so only count modifiers that are
        # enabled
        if any(mod.type != 'ARMATURE' and mod.show_viewport for mod in obj.modifiers):
            self.draw_mesh_modifiers_box(properties_col, settings.modifier_settings, ui_toggle_data, enabled)
        if me.uv_layers:
            self.draw_uv_layers_box(properties_col, settings.uv_settings, me, ui_toggle_data, enabled)
        if me.materials:
            self.draw_materials_box(properties_col, settings.material_settings, obj, ui_toggle_data, enabled)

    def draw(self, context: Context):
        # guaranteed to be SpaceProperties by the bl_space_type
        space_data = cast(SpaceProperties, context.space_data)
        pin_id = space_data.pin_id
        if pin_id:
            # poll function has already checked that there's either no pin or that it's an object
            obj = pin_id
        else:
            obj = context.object
        group = ObjectPropertyGroup.get_group(obj)
        object_settings = group.object_settings

        layout = self.layout
        main_column = layout.column(align=True)
        main_col = main_column.column()
        # Sync setting and anything else that should be before things

        header_col = main_col.column()
        header_col.use_property_decorate = True

        header_top_row = header_col.row(align=True)
        header_top_row.use_property_decorate = False
        header_top_row_left_buttons_col = header_top_row.column(align=True)
        header_top_row_left_buttons_row1 = header_top_row_left_buttons_col.row(align=True)
        header_top_row_left_buttons_row1.prop(group, 'sync_active_with_scene', icon="SCENE_DATA", text="")
        header_top_row_left_buttons_row1.prop(group, 'sync_active_with_scene', icon="OBJECT_DATA", text="", invert_checkbox=True)

        copy_menu = None
        if obj.type == 'MESH':
            copy_menu = _COPY_MENU_LOOKUP.get(_ALL_MESH)
        elif obj.type == 'ARMATURE':
            copy_menu = _COPY_MENU_LOOKUP.get(_ALL_ARMATURE)

        is_synced = group.sync_active_with_scene
        if is_synced:
            # Get active_object_settings by name of active_build_settings
            scene_group = ScenePropertyGroup.get_group(context.scene)
            active_build_settings = scene_group.get_active()

            active_object_settings: Union[ObjectBuildSettings, None]
            if active_build_settings:
                active_object_settings = object_settings.get(active_build_settings.name)
                if active_object_settings:
                    if copy_menu:
                        header_top_row.menu(copy_menu.bl_idname, text="", icon='PASTEDOWN')
                    header_top_row.separator()
                    header_top_row.prop(active_build_settings, "name_prop", icon="SCENE_DATA", emboss=False, text="")
                    header_top_row.use_property_split = True
                    header_top_row.prop(active_object_settings, "include_in_build", text="")
                else:
                    options = header_top_row.operator(ObjectBuildSettingsAdd.bl_idname, text="Add to Avatar Builder", icon="ADD")
                    options.name = active_build_settings.name
            else:
                active_object_settings = None
                # If there are any SceneBuildSettings:
                if scene_group.build_settings:
                    # Only happens if the active index is out of bounds for some reason, since we hide the panel
                    # when there are no Build Settings
                    header_col.label(text="Active build settings is out of bounds, this shouldn't normally happen.")
                    header_col.label(text="Select one in the list in the 3D View or Auto Fix")
                    # Button to set the active index to 0
                    options = header_col.operator('wm.context_set_int', text="Auto Fix", icon='SHADERFX')
                    options.data_path = 'scene.' + scene_group.path_from_id('build_settings_active_index')
                    options.value = 0
                    options.relative = False
        else:
            object_settings_active_index = group.object_settings_active_index
            num_object_settings = len(object_settings)
            if num_object_settings > 0 and 0 <= object_settings_active_index < num_object_settings:
                active_object_settings = object_settings[object_settings_active_index]
            else:
                active_object_settings = None

            if active_object_settings and copy_menu:
                header_top_row_left_buttons_row2 = header_top_row_left_buttons_col.row()
                # Change back to EXPAND or LEFT if we add more buttons/menus
                header_top_row_left_buttons_row2.alignment = 'CENTER'
                header_top_row_left_buttons_row2.menu(copy_menu.bl_idname, text="", icon='PASTEDOWN')

            list_row = header_top_row.row(align=False)
            list_row.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'object_settings', group, 'object_settings_active_index', rows=3)
            vertical_buttons_col = header_top_row.column(align=True)
            vertical_buttons_col.operator(ObjectBuildSettingsAdd.bl_idname, text="", icon="ADD").name = ''
            vertical_buttons_col.operator(ObjectBuildSettingsRemove.bl_idname, text="", icon="REMOVE")
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(ObjectBuildSettingsMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
            vertical_buttons_col.operator(ObjectBuildSettingsMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'

        if active_object_settings:
            # Extra col for label when disabled
            if not active_object_settings.include_in_build:
                disabled_label_col = main_col.column()
                disabled_label_col.alignment = 'RIGHT'
                disabled_label_col.use_property_split = True
                disabled_label_col.use_property_decorate = True
                disabled_label_col.label(text="Disabled. Won't be included in build")
            elif is_synced:
                # Add a separator to move the first properties header away from the main header. This isn't needed when
                # sync is disabled because the UIList adds extra space, similarly with when the settings are disabled
                main_col.separator()

            # Display the properties for the active settings
            settings_enabled = active_object_settings.include_in_build
            properties_col = main_column.column()
            properties_col.use_property_split = True
            properties_col.use_property_decorate = False

            toggles = WindowManagerPropertyGroup.get_group(context.window_manager).ui_toggles.object

            # Display the box for general object settings
            self.draw_general_object_box(properties_col, active_object_settings, toggles, settings_enabled)

            # Display the box for armature settings if the object is an armature
            if obj.type == 'ARMATURE':
                self.draw_armature_box(properties_col, active_object_settings.armature_settings, obj, toggles.armature, settings_enabled)
            # Display the boxes for mesh settings if the object is a mesh
            elif obj.type == 'MESH':
                mesh_settings = active_object_settings.mesh_settings
                self.draw_mesh_boxes(properties_col, mesh_settings, obj, toggles.mesh, settings_enabled)

            # Display a button to remove the settings from Avatar Builder when scene sync is enabled
            if is_synced:
                # Separator to move the Remove button slightly away from the properties headers
                main_column.separator()
                final_col = main_column.column(align=True)
                final_col.operator(ObjectBuildSettingsRemove.bl_idname, text="Remove from Avatar Builder", icon="TRASH")


class ObjectBuildSettingsBase(ContextCollectionOperatorBase):
    @classmethod
    def get_object_group(cls, context: Context) -> ObjectPropertyGroup:
        return ObjectPropertyGroup.get_group(context.object)

    @classmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        return cls.get_object_group(context).object_settings

    @classmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        object_group = cls.get_object_group(context)
        # With sync enabled, we often ignore the active index, instead preferring to use the settings that match the
        # active build settings
        sync_enabled = object_group.sync_active_with_scene
        if sync_enabled:
            active_scene_settings = ScenePropertyGroup.get_group(context.scene).get_active()
            if active_scene_settings and active_scene_settings.name:
                return object_group.object_settings.find(active_scene_settings.name)
            else:
                return None
        else:
            return object_group.object_settings_active_index

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        object_group = cls.get_object_group(context)
        sync_enabled = object_group.sync_active_with_scene
        if sync_enabled:
            # The active index is effectively read-only when sync is enabled
            return
        else:
            object_group.object_settings_active_index = value


class ObjectBuildSettingsAdd(ObjectBuildSettingsBase, CollectionAddBase):
    """Add a new set of build settings, defaults to the active build settings if they don't exist on this Object"""
    bl_idname = 'object_build_settings_add'

    @staticmethod
    def set_new_item_name_static(data: PropCollectionType, added: PropertyGroup, name=None):
        if name:
            added.name_prop = name
        # Auto name
        else:
            # Rename if not unique and ensure that the internal name is also set
            added_name = added.name_prop
            orig_name = added_name
            unique_number = 0
            # Its internal name of the newly added build_settings will currently be "" since it hasn't been set
            # We could do `while added_name in build_settings:` but I'm guessing Blender has to iterate through each
            # element until `added_name` is found since duplicate names are allowed. Checking against a set should be
            # faster if there are lots
            existing_names = {bs.name for bs in data}
            while added_name in existing_names:
                unique_number += 1
                added_name = orig_name + " " + str(unique_number)
            if added_name != orig_name:
                # Assigning the prop will also update the internal name
                added.name_prop = added_name
            else:
                added.name = added_name

    def set_new_item_name(self, data: PropCollectionType, added: PropertyGroup):
        self.set_new_item_name_static(data, added, self.name)

    def execute(self, context: Context) -> set[str]:
        obj = context.object
        object_group = ObjectPropertyGroup.get_group(obj)
        sync_enabled = object_group.sync_active_with_scene
        if sync_enabled:
            synced_active_index = self.get_active_index(context)
            if synced_active_index == -1:
                # ObjectSettings for the currently active SceneSettings don't exist
                active_build_settings = ScenePropertyGroup.get_group(context.scene).get_active()
                self.name = active_build_settings.name
            else:
                # There is no currently active Scene settings
                return {'CANCELLED'}
        return super().execute(context)


class ObjectBuildSettingsRemove(ObjectBuildSettingsBase, CollectionRemoveBase):
    bl_idname = 'object_build_settings_remove'


class ObjectBuildSettingsMove(ObjectBuildSettingsBase, CollectionMoveBase):
    bl_idname = 'object_build_settings_move'


class ObjectBuildSettingsSync(ObjectBuildSettingsBase, Operator):
    """Set the currently displayed settings to the currently active build settings"""
    bl_idname = 'object_build_settings_sync'
    bl_label = "Sync"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        object_group = cls.get_object_group(context)
        return not object_group.sync_active_with_scene

    def execute(self, context: Context) -> set[str]:
        scene_active = ScenePropertyGroup.get_group(context.scene).get_active()
        object_build_settings = self.get_collection(context)
        if scene_active:
            index = object_build_settings.find(scene_active.name)
            if index != -1:
                self.set_active_index(context, index)
                return {'FINISHED'}
        return {'CANCELLED'}


register, unregister = register_module_classes_factory(__name__, globals())
