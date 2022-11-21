from typing import Union, cast, Optional
from bpy.types import (
    UIList,
    Context,
    UILayout,
    Panel,
    SpaceProperties,
    Operator,
    Object,
    Mesh,
    PropertyGroup,
    Menu,
    Scene,
)

from . import shape_key_ops, ui_material_remap, utils, ui_uv_maps, ui_vertex_group_swaps
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
from .integration_gret import check_gret_shape_key_apply_modifiers
from .context_collection_ops import (
    CollectionAddBase,
    CollectionDuplicateBase,
    ContextCollectionOperatorBase,
    PropCollectionType,
)
from .object_props_copy import (
    CopyPropsItem,
    COPY_GENERAL_OBJECT_SETTINGS,
    COPY_ARMATURE_POSE_SETTINGS,
    COPY_MESH_VERTEX_GROUPS_SETTINGS,
    COPY_MESH_SHAPE_KEYS_SETTINGS,
    COPY_MESH_MODIFIERS_SETTINGS,
    COPY_MESH_UV_LAYERS_SETTINGS,
    COPY_MESH_MATERIALS_SETTINGS,
    COPY_ALL_MESH_SETTINGS,
    COPY_ALL_ARMATURE_SETTINGS,
)
from .preferences import object_ui_sync_enabled


class ObjectBuildSettingsUIList(UIList):
    bl_idname = "object_build_settings"

    def draw_item(self, context: Context, layout: UILayout, data, item: ObjectBuildSettings, icon, active_data, active_property, index=0,
                  flt_flag=0):
        scene_group = ScenePropertyGroup.get_group(context.scene)
        scene_settings = scene_group.collection

        scene_active_name = scene_group.active.name
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


class ObjectPanelBase(Panel):
    @staticmethod
    def _poll_object(obj: Object):
        # TODO: Currently, we're only building these types, should we be including any others?
        # TODO: Make the set a global variable and uses it elsewhere too
        return obj and obj.type in ObjectPropertyGroup.ALLOWED_TYPES

    @staticmethod
    def _poll_scene(scene: Scene):
        # Build settings must be non-empty
        # TODO: Should add a 'clean' or 'purge' button to Scene panel that purges non-existent build settings from all
        #       objects in the current scene. This is because we otherwise have no way to remove the object settings
        #       if we hide the panel when there's no build settings
        return scene and ScenePropertyGroup.get_group(scene).collection

    @staticmethod
    def _get_object(context: Context):
        return context.object

    @classmethod
    def poll(cls, context: Context):
        return cls._poll_object(cls._get_object(context)) and cls._poll_scene(context.scene)

    @staticmethod
    def draw_expandable_header(properties_col: UILayout, ui_toggle_data: PropertyGroup, ui_toggle_prop: str,
                               enabled: bool, copy_type: CopyPropsItem, **header_args):
        """Draw an expandable header
        :return: a box UILayout when expanded, otherwise None"""
        header_row = properties_col.row(align=True)
        header_row.use_property_split = False
        header_row.alert = not enabled
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
        if copy_type:
            # Sub row without align so that the button appears disconnected from the third element
            menu_row = header_row.row(align=False)
            menu_row.menu(copy_type.copy_menu.bl_idname, text="", icon="PASTEDOWN")

        if is_expanded:
            # Create a box that the properties will be drawn in
            box = properties_col.box()
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
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'general', enabled,
                                                 COPY_GENERAL_OBJECT_SETTINGS, text="Object", icon='OBJECT_DATA')
        if box:
            box.prop(settings, 'target_object_name')
            box.prop(settings, 'join_order')

    @staticmethod
    def draw_armature_box(properties_col: UILayout, settings: ArmatureSettings, obj: Object,
                          ui_toggle_data: WmArmatureToggles, enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'pose', enabled,
                                                 COPY_ARMATURE_POSE_SETTINGS, text="Pose", icon='ARMATURE_DATA')
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
                                                 COPY_MESH_VERTEX_GROUPS_SETTINGS, text="Vertex Groups",
                                                 icon='GROUP_VERTEX')
        if box:
            ui_vertex_group_swaps.draw_vertex_group_swaps(box, settings.vertex_group_swaps)
            box.prop(settings, 'remove_non_deform_vertex_groups')
            # TODO: Remove empty vertex groups? Probably not very important, since it won't result in much
            #  extra data, assuming they even get exported at all

    @staticmethod
    def draw_shape_keys_box(properties_col: UILayout, settings: ShapeKeySettings, me: Mesh,
                            ui_toggle_data: WmMeshToggles, enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'shape_keys', enabled,
                                                 COPY_MESH_SHAPE_KEYS_SETTINGS, text="Shape keys", icon='SHAPEKEY_DATA')
        if box:
            main_op_col = box.column()
            main_op_col.prop(settings, 'shape_keys_main_op')

            main_op = settings.shape_keys_main_op
            if main_op == 'CUSTOM':
                shape_key_ops.draw_shape_key_ops(box, settings, me.shape_keys)

    @staticmethod
    def draw_mesh_modifiers_box(properties_col: UILayout, settings: ModifierSettings, ui_toggle_data: WmMeshToggles,
                                enabled: bool):
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'modifiers', enabled,
                                                 COPY_MESH_MODIFIERS_SETTINGS, text="Modifiers", icon='MODIFIER_DATA')
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
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'uv_layers', enabled,
                                                 COPY_MESH_UV_LAYERS_SETTINGS, text="UV Layers", icon='GROUP_UVS')
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
        box = ObjectPanel.draw_expandable_header(properties_col, ui_toggle_data, 'materials', enabled,
                                                 COPY_MESH_MATERIALS_SETTINGS, text="Materials", icon='MATERIAL_DATA')
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
        obj = self._get_object(context)
        group = ObjectPropertyGroup.get_group(obj)
        object_settings = group.collection

        layout = self.layout
        main_column = layout.column(align=True)
        main_col = main_column.column()
        # Sync setting and anything else that should be before things

        header_col = main_col.column()
        header_col.use_property_decorate = True

        header_top_row = header_col.row(align=True)
        header_top_row.use_property_decorate = False

        copy_menu = None
        if obj.type == 'MESH':
            copy_menu = COPY_ALL_MESH_SETTINGS.copy_menu
        elif obj.type == 'ARMATURE':
            copy_menu = COPY_ALL_ARMATURE_SETTINGS.copy_menu

        is_synced = object_ui_sync_enabled(context)
        if is_synced:
            # Get active_object_settings by name of active_build_settings
            scene_group = ScenePropertyGroup.get_group(context.scene)
            active_build_settings = scene_group.active

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
                    options = header_top_row.operator(ObjectBuildSettingsAdd.bl_idname,
                                                      text=f"Add to '{active_build_settings.name}'",
                                                      icon="ADD")
                    options.name = active_build_settings.name
            else:
                active_object_settings = None
                # If there are any SceneBuildSettings:
                if scene_group.collection:
                    # Only happens if the active index is out of bounds for some reason, since we hide the panel
                    # when there are no Build Settings
                    header_col.label(text="Active build settings is out of bounds, this shouldn't normally happen.")
                    header_col.label(text="Select one in the list in the 3D View or Auto Fix")
                    # Button to set the active index to 0
                    options = header_col.operator('wm.context_set_int', text="Auto Fix", icon='SHADERFX')
                    options.data_path = 'scene.' + scene_group.path_from_id('active_index')
                    options.value = 0
                    options.relative = False
        else:
            object_settings_active_index = group.active_index
            num_object_settings = len(object_settings)
            if num_object_settings > 0 and 0 <= object_settings_active_index < num_object_settings:
                active_object_settings = object_settings[object_settings_active_index]
            else:
                active_object_settings = None

            if active_object_settings and copy_menu:
                header_top_row.menu(copy_menu.bl_idname, text="", icon='PASTEDOWN')

            list_row = header_top_row.row(align=False)
            list_row.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'collection', group, 'active_index', rows=3)
            vertical_buttons_col = header_top_row.column(align=True)
            vertical_buttons_col.menu(ObjectBuildSettingsAddMenu.bl_idname, text="", icon="ADD")
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
                disabled_label_col.alert = True
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
                final_col.operator(ObjectBuildSettingsRemove.bl_idname,
                                   text=f"Remove from '{active_object_settings.name}'",
                                   icon="TRASH")


class ObjectPanel(ObjectPanelBase):
    bl_idname = "object_panel"
    bl_label = "Avatar Builder"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @staticmethod
    def _get_object(context: Context):
        # guaranteed to be SpaceProperties by the bl_space_type
        space_data = cast(SpaceProperties, context.space_data)
        pin_id = space_data.pin_id
        if pin_id:
            # poll function has already checked that there's either no pin or that it's an object
            return pin_id
        else:
            return context.object


class ObjectPanelView3D(ObjectPanelBase):
    """3D View version of the Object Settings Panel"""
    # Using the same bl_idname as the PROPERTIES version of the Panel is ok, because Panel subclasses are prefixed
    # differently based on their bl_space_type during registration
    bl_idname = 'object_panel'
    bl_label = "Object Settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Avatar Builder"
    # After MMD Shape Mapping Panel by default (since this Panel is not always present)
    bl_order = 3


class ObjectBuildSettingsBase(ContextCollectionOperatorBase):
    @classmethod
    def get_object_group(cls, context: Context) -> ObjectPropertyGroup:
        return ObjectPropertyGroup.get_group(context.object)

    @classmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        return cls.get_object_group(context).collection

    @classmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        object_group = cls.get_object_group(context)
        # With sync enabled, we often ignore the active index, instead preferring to use the settings that match the
        # active build settings
        sync_enabled = object_ui_sync_enabled(context)
        if sync_enabled:
            active_scene_settings = ScenePropertyGroup.get_group(context.scene).active
            if active_scene_settings and active_scene_settings.name:
                return object_group.collection.find(active_scene_settings.name)
            else:
                return None
        else:
            return object_group.active_index

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        object_group = cls.get_object_group(context)
        sync_enabled = object_ui_sync_enabled(context)
        if sync_enabled:
            # The active index is effectively read-only when sync is enabled
            return
        else:
            object_group.active_index = value


_op_builder = ObjectBuildSettingsBase.op_builder(
    class_name_prefix='ObjectBuildSettings',
    bl_idname_prefix='object_build_settings',
    element_label="settings",
)
ObjectBuildSettingsRemove = _op_builder.remove.build()
ObjectBuildSettingsMove = _op_builder.move.build()


@_op_builder.add.decorate
class ObjectBuildSettingsAdd(ObjectBuildSettingsBase, CollectionAddBase[ObjectBuildSettings]):
    """Add new settings, defaults to the active build settings if they don't exist on this Object"""

    @staticmethod
    def set_new_item_name_static(data: PropCollectionType, added: ObjectBuildSettings, name=None):
        if name:
            added.name_prop = name
        # Auto name
        else:
            # Rename if not unique and ensure that the internal name is also set
            orig_name = added.name_prop
            added_name = utils.get_unique_name(orig_name, data, number_separator=' ', min_number_digits=1)
            if added_name != orig_name:
                # Assigning the prop will also update the internal name
                added.name_prop = added_name
            else:
                added.name = added_name

    def set_new_item_name(self, data: PropCollectionType, added: ObjectBuildSettings):
        self.set_new_item_name_static(data, added, self.name)

    def execute(self, context: Context) -> set[str]:
        obj = context.object
        object_group = ObjectPropertyGroup.get_group(obj)
        sync_enabled = object_ui_sync_enabled(context)
        if sync_enabled:
            synced_active_index = self.get_active_index(context)
            if synced_active_index == -1:
                # ObjectSettings for the currently active SceneSettings don't exist
                active_build_settings = ScenePropertyGroup.get_group(context.scene).active
                self.name = active_build_settings.name
            else:
                # There is no currently active Scene settings
                return {'CANCELLED'}
        return super().execute(context)


@_op_builder.duplicate.decorate
class ObjectBuildSettingsDuplicate(ObjectBuildSettingsBase, CollectionDuplicateBase[ObjectBuildSettings]):

    def set_new_item_name(self, data: PropCollectionType, added: ObjectBuildSettings):
        desired_name = self.name
        if desired_name:
            # Since we're duplicating some existing settings, it's probably best that we don't force the name of the
            # duplicated settings to the desired name and instead pick a unique name using the desired name as the base
            duplicate_name = utils.get_unique_name(desired_name, data)
        else:
            source = data[self.index_being_duplicated]
            source_name = source.name

            # Get the first unique name using source_name as the base name
            duplicate_name = utils.get_unique_name(source_name, data)

        # Set the name for the duplicated element (we've guaranteed that it's unique, so no need to propagate to other
        # settings to ensure uniqueness)
        added.set_name_no_propagate(duplicate_name)


class ObjectBuildSettingsAddMenu(Menu):
    """Add new settings, either blank or a duplicate of the active settings"""
    bl_label = "Duplicate"
    bl_idname = 'object_build_settings_duplicate'

    def draw(self, context: Context):
        layout = self.layout
        layout.operator(ObjectBuildSettingsAdd.bl_idname, text="New").name = ''
        layout.operator(ObjectBuildSettingsDuplicate.bl_idname, text="Copy Active Settings").name = ''


class ObjectBuildSettingsSync(ObjectBuildSettingsBase, Operator):
    """Set the currently displayed settings to the currently active build settings"""
    bl_idname = 'object_build_settings_sync'
    bl_label = "Sync"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return not object_ui_sync_enabled(context)

    def execute(self, context: Context) -> set[str]:
        scene_active = ScenePropertyGroup.get_group(context.scene).active
        object_build_settings = self.get_collection(context)
        if scene_active:
            index = object_build_settings.find(scene_active.name)
            if index != -1:
                self.set_active_index(context, index)
                return {'FINISHED'}
        return {'CANCELLED'}


del _op_builder
register_module_classes_factory(__name__, globals())
