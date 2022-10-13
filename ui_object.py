from typing import Union, cast, Optional
from bpy.types import UIList, Context, UILayout, Panel, SpaceProperties, Operator, Object, Mesh, PropertyGroup, Menu
from bpy.props import EnumProperty

from .registration import register_module_classes_factory
from .extensions import (
    ArmatureSettings,
    MaterialSettings,
    MeshSettings,
    ModifierSettings,
    ObjectBuildSettings,
    ObjectPropertyGroup,
    ScenePropertyGroup,
    ShapeKeyOp,
    ShapeKeySettings,
    UVSettings,
    VertexGroupSettings,
)
from .integration import check_gret_shape_key_apply_modifiers
from .context_collection_ops import (
    CollectionAddBase,
    CollectionMoveBase,
    CollectionRemoveBase,
    ContextCollectionOperatorBase,
    PropCollectionType,
)


class ShapeKeyOpsUIList(UIList):
    bl_idname = "shapekey_ops_list"

    def draw_item(self, context: Context, layout: UILayout, data, item: ShapeKeyOp, icon: int, active_data: ShapeKeyOp,
                  active_property: str, index: int = 0, flt_flag: int = 0):
        self.use_filter_show = False

        row = layout.row(align=True)

        op_type = item.type
        shape_keys = item.id_data.data.shape_keys

        if op_type in ShapeKeyOp.DELETE_OPS_DICT:
            op = ShapeKeyOp.DELETE_OPS_DICT[op_type]
            row.label(text=op.list_label, icon="TRASH")
            op.draw_props(row, shape_keys, item, "")
        elif op_type in ShapeKeyOp.MERGE_OPS_DICT:
            op = ShapeKeyOp.MERGE_OPS_DICT[op_type]

            if item.merge_grouping == 'CONSECUTIVE':
                mode_icon = ShapeKeyOp.GROUPING_CONSECUTIVE_ICON
            elif item.merge_grouping == 'ALL':
                mode_icon = ShapeKeyOp.GROUPING_ALL_ICON
            else:
                mode_icon = "NONE"

            row.label(text=op.list_label, icon="FULLSCREEN_EXIT")
            op.draw_props(row, shape_keys, item, "")
            options = row.operator('wm.context_cycle_enum', text="", icon=mode_icon)
            options.wrap = True
            options.data_path = 'object.' + item.path_from_id('merge_grouping')
        else:
            # This shouldn't happen normally
            row.label(text="ERROR: Unknown Op Type", icon="QUESTION")

    def draw_filter(self, context: Context, layout: UILayout):
        # No filter
        pass

    def filter_items(self, context: Context, data, property: str):
        # We always want to show every op in order because they are applied in series. No filtering or sorting is ever
        # enabled
        return [], []


class ShapeKeyOpsListBase(ContextCollectionOperatorBase):
    @staticmethod
    def get_shape_key_settings(context: Context) -> Optional[ObjectBuildSettings]:
        obj = context.object
        group = ObjectPropertyGroup.get_group(obj)
        return group.get_displayed_settings(context.scene)

    @classmethod
    def get_collection(cls, context: Context) -> Optional[PropCollectionType]:
        settings = cls.get_shape_key_settings(context)
        if settings is not None:
            return settings.mesh_settings.shape_key_settings.shape_key_ops.data
        else:
            return None

    @classmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        settings = cls.get_shape_key_settings(context)
        if settings is not None:
            return settings.mesh_settings.shape_key_settings.shape_key_ops.active_index
        else:
            return None

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        settings = cls.get_shape_key_settings(context)
        if settings is not None:
            settings.mesh_settings.shape_key_settings.shape_key_ops.active_index = value


class ShapeKeyOpsListAdd(ShapeKeyOpsListBase, CollectionAddBase[ShapeKeyOp]):
    """Add a new shape key op"""
    bl_idname = 'shape_key_ops_list_add'

    type: EnumProperty(
        items=ShapeKeyOp.TYPE_ITEMS,
        name="Type",
        description="Type of the added shape key op"
    )

    def modify_newly_created(self, data: PropCollectionType, added: ShapeKeyOp):
        super().modify_newly_created(data, added)
        added.type = self.type


class ShapeKeyOpsListAddDeleteSubMenu(Menu):
    """Add an op that deletes shape keys"""
    bl_idname = 'shape_key_ops_list_add_delete_submenu'
    bl_label = "Delete"

    def draw(self, context: Context):
        layout = self.layout
        for op in ShapeKeyOp.DELETE_OPS_DICT.values():
            layout.operator(ShapeKeyOpsListAdd.bl_idname, text=op.menu_label).type = op.id


class ShapeKeyOpsListAddMergeSubMenu(Menu):
    """Add an op that merges shape keys"""
    bl_idname = 'shape_key_ops_list_add_merge_submenu'
    bl_label = "Merge"

    def draw(self, context: Context):
        layout = self.layout
        for op in ShapeKeyOp.MERGE_OPS_DICT.values():
            layout.operator(ShapeKeyOpsListAdd.bl_idname, text=op.menu_label).type = op.id


class ShapeKeyOpsListAddMenu(Menu):
    """Add a new shape key op to the list"""
    bl_idname = 'shape_key_ops_list_add_menu'
    bl_label = "Add"

    def draw(self, context: Context):
        layout = self.layout
        layout.menu(ShapeKeyOpsListAddDeleteSubMenu.bl_idname, icon='TRASH')
        layout.menu(ShapeKeyOpsListAddMergeSubMenu.bl_idname, icon='FULLSCREEN_EXIT')


class ShapeKeyOpsListRemove(ShapeKeyOpsListBase, CollectionRemoveBase):
    """Remove the active shape key op"""
    bl_idname = 'shape_key_ops_list_remove'


class ShapeKeyOpsListMove(ShapeKeyOpsListBase, CollectionMoveBase):
    """Move the active shape key op"""
    bl_idname = 'shape_key_ops_list_move'


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
        if not obj or obj.type not in {'MESH', 'ARMATURE'}:
            return False
        scene = context.scene
        # Build settings must be non-empty
        # TODO: Should add a 'clean' or 'purge' button to Scene panel that purges non-existent build settings from all
        #       objects in the current scene. This is because we otherwise have no way to remove the object settings
        #       if we hide the panel when there's no build settings
        return ScenePropertyGroup.get_group(scene).build_settings

    @staticmethod
    def draw_general_object_box(properties_col: UILayout, settings: ObjectBuildSettings):
        object_box = properties_col.box()
        object_box_col = object_box.column()
        object_box_col.label(text="Object", icon="OBJECT_DATA")
        object_box_col.prop(settings, 'target_object_name')

    @staticmethod
    def draw_armature_box(properties_col: UILayout, settings: ArmatureSettings, obj: Object):
        armature_box = properties_col.box()
        armature_box_col = armature_box.column()
        armature_box_col.label(text="Pose", icon="ARMATURE_DATA")

        export_pose = settings.armature_export_pose

        armature_box_col.prop(settings, 'armature_export_pose')

        armature_preserve_volume_col = armature_box_col.column()
        armature_preserve_volume_col.enabled = export_pose != 'REST'
        armature_preserve_volume_col.prop(settings, 'armature_export_pose_preserve_volume')

        armature_pose_custom_col = armature_box_col.column()
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
            armature_pose_custom_col.prop(
                settings,
                'armature_export_pose_library_marker', icon="DOT")

    @staticmethod
    def draw_vertex_groups_box(properties_col: UILayout, settings: VertexGroupSettings):
        vertex_groups_box = properties_col.box()

        vertex_groups_box_col = vertex_groups_box.column()
        vertex_groups_box_col.label(text="Vertex Groups", icon="GROUP_VERTEX")
        vertex_groups_box_col.prop(settings, 'remove_non_deform_vertex_groups')
        # TODO: Remove empty vertex groups? Probably not very important, since it won't result in much
        #  extra data, assuming they even get exported at all

    @staticmethod
    def draw_shape_keys_box(properties_col: UILayout, settings: ShapeKeySettings, me: Mesh):
        shape_keys_box = properties_col.box()
        shape_keys_box_col = shape_keys_box.column()
        shape_keys_box_col.label(text="Shape keys", icon="SHAPEKEY_DATA")

        main_op_col = shape_keys_box_col.column()
        main_op_col.prop(settings, 'shape_keys_main_op')

        main_op = settings.shape_keys_main_op
        if main_op == 'CUSTOM':
            shape_key_ops = settings.shape_key_ops

            operations_title_row = shape_keys_box_col.row()
            operations_title_row.label(text="Operations")
            vertical_buttons_col = operations_title_row.row(align=True)
            vertical_buttons_col.menu(ShapeKeyOpsListAddMenu.bl_idname, text="", icon="ADD")
            vertical_buttons_col.operator(ShapeKeyOpsListRemove.bl_idname, text="", icon="REMOVE")
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(ShapeKeyOpsListMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
            vertical_buttons_col.operator(ShapeKeyOpsListMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'
            shape_keys_box_col.template_list(
                ShapeKeyOpsUIList.bl_idname, "",
                shape_key_ops, 'data',
                shape_key_ops, 'active_index',
                # With the buttons down the side, 4 rows is the minimum we can have, so we put the buttons on top
                sort_lock=True, rows=1)

            active_op_col = shape_keys_box_col.column(align=True)
            active_op = shape_key_ops.active
            if active_op:
                op_type = active_op.type
                if op_type in ShapeKeyOp.DELETE_OPS_DICT:
                    if op_type == ShapeKeyOp.DELETE_AFTER:
                        active_op_col.prop_search(active_op, 'delete_after_name', me.shape_keys, 'key_blocks')
                    elif op_type == ShapeKeyOp.DELETE_BEFORE:
                        active_op_col.prop_search(active_op, 'delete_before_name', me.shape_keys, 'key_blocks')
                    elif op_type == ShapeKeyOp.DELETE_BETWEEN:
                        active_op_col.prop_search(active_op, 'delete_after_name', me.shape_keys, 'key_blocks', text="Key 1")
                        active_op_col.prop_search(active_op, 'delete_before_name', me.shape_keys, 'key_blocks', text="Key 2")
                    elif op_type == ShapeKeyOp.DELETE_SINGLE:
                        active_op_col.prop_search(active_op, 'pattern', me.shape_keys, 'key_blocks', text="Name")
                    elif op_type == ShapeKeyOp.DELETE_REGEX:
                        active_op_col.prop(active_op, 'pattern')
                elif op_type in ShapeKeyOp.MERGE_OPS_DICT:
                    if op_type == ShapeKeyOp.MERGE_PREFIX:
                        active_op_col.prop(active_op, 'pattern', text="Prefix")
                    elif op_type == ShapeKeyOp.MERGE_SUFFIX:
                        active_op_col.prop(active_op, 'pattern', text="Suffix")
                    elif op_type == ShapeKeyOp.MERGE_COMMON_BEFORE_DELIMITER or op_type == ShapeKeyOp.MERGE_COMMON_AFTER_DELIMITER:
                        active_op_col.prop(active_op, 'pattern', text="Delimiter")
                    elif op_type == ShapeKeyOp.MERGE_REGEX:
                        active_op_col.prop(active_op, 'pattern')

                    # Common for all merge ops
                    active_op_col.prop(active_op, 'merge_grouping')

                # Common for all ops
                active_op_col.prop(active_op, 'ignore_regex')

    @staticmethod
    def draw_mesh_modifiers_box(properties_col: UILayout, settings: ModifierSettings):
        mesh_modifiers_box = properties_col.box()
        mesh_modifiers_box_col = mesh_modifiers_box.column(align=True)
        mesh_modifiers_box_col.label(text="Modifiers", icon="MODIFIER_DATA")
        if settings.apply_non_armature_modifiers == 'APPLY_KEEP_SHAPES_GRET':
            gret_available = check_gret_shape_key_apply_modifiers()
            mesh_modifiers_box_col.alert = not gret_available
            mesh_modifiers_box_col.prop(settings, 'apply_non_armature_modifiers')

            if not gret_available:
                if gret_available is None:
                    mesh_modifiers_box_col.label("Gret addon operator not found")
                else:
                    mesh_modifiers_box_col.label("Unsupported version of Gret")
            mesh_modifiers_box_col.alert = False
        else:
            mesh_modifiers_box_col.prop(settings, 'apply_non_armature_modifiers')

    @staticmethod
    def draw_uv_layers_box(properties_col: UILayout, settings: UVSettings, me: Mesh):
        uv_layers_box = properties_col.box()
        uv_layers_box_col = uv_layers_box.column()
        uv_layers_box_col.label(text="UV Layers", icon="GROUP_UVS")
        uv_layers_box_col.prop_search(settings, 'keep_only_uv_map', me, 'uv_layers', icon="GROUP_UVS")

    @staticmethod
    def draw_materials_box(properties_col: UILayout, settings: MaterialSettings, me: Mesh):
        materials_box = properties_col.box()
        materials_box_col = materials_box.column()
        materials_box_col.label(text="Materials", icon="MATERIAL_DATA")
        materials_box_col.prop_search(settings, 'keep_only_material', me, 'materials')

    def draw_mesh_boxes(self, properties_col: UILayout, settings: MeshSettings, obj: Object):
        me = cast(Mesh, obj.data)
        if obj.vertex_groups:
            self.draw_vertex_groups_box(properties_col, settings.vertex_group_settings)
        # Only draw the shape keys box if there is more than one shape key. When there's one shape key, it will be the
        # reference key, the 'Basis'.
        # Note that non-relative shape keys are not supported at this time
        # TODO: Find out if (and if so, how) Blender's FBX exporter supports non-relative shape keys
        if me.shape_keys and len(me.shape_keys.key_blocks) > 1:
            self.draw_shape_keys_box(properties_col, settings.shape_key_settings, me)
        # We don't touch armature modifiers, so only include the modifiers box when there's at least one non-armature
        # modifier
        # Additionally, modifiers which are disabled in the viewport get removed, so only count modifiers that are
        # enabled
        if any(mod.type != 'ARMATURE' and mod.show_viewport for mod in obj.modifiers):
            self.draw_mesh_modifiers_box(properties_col, settings.modifier_settings)
        if me.uv_layers:
            self.draw_uv_layers_box(properties_col, settings.uv_settings, me)
        if me.materials:
            self.draw_materials_box(properties_col, settings.material_settings, me)

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

        row = header_col.row(align=True)
        row.use_property_decorate = False
        row.prop(group, 'sync_active_with_scene', icon="SCENE_DATA", text="")
        row.prop(group, 'sync_active_with_scene', icon="OBJECT_DATA", text="", invert_checkbox=True)

        is_synced = group.sync_active_with_scene
        if group.sync_active_with_scene:
            # Get active_object_settings by name of active_build_settings
            scene_group = ScenePropertyGroup.get_group(context.scene)
            active_build_settings = scene_group.get_active()

            active_object_settings: Union[ObjectBuildSettings, None]
            if active_build_settings:
                active_object_settings = object_settings.get(active_build_settings.name)
            else:
                active_object_settings = None
                if scene_group.build_settings:
                    # Only happens if the active index is out of bounds for some reason, since we hide the panel
                    # when there are no Build Settings
                    header_col.label(text="Active build settings is out of bounds, this shouldn't normally happen,"
                                          " select one in the list in the 3D View and the active build settings index"
                                          " will update automatically")
                    # TODO: Draw button to 'fix' out of bounds index
            if active_object_settings:
                if active_build_settings:
                    row.separator()
                    row.label(text="", icon="SETTINGS")
                    row.prop(active_build_settings, "name_prop", icon="SCENE_DATA", emboss=False, text="")
                    row.use_property_split = True
                    row.prop(active_object_settings, "include_in_build", text="")
            else:
                row.operator(ObjectBuildSettingsAdd.bl_idname, text="Add to Avatar Builder", icon="ADD")
        else:
            list_row = row.row(align=False)
            list_row.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'object_settings', group, 'object_settings_active_index', rows=3)
            vertical_buttons_col = row.column(align=True)
            vertical_buttons_col.operator(ObjectBuildSettingsAdd.bl_idname, text="", icon="ADD")
            vertical_buttons_col.operator(ObjectBuildSettingsRemove.bl_idname, text="", icon="REMOVE")
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(ObjectBuildSettingsMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
            vertical_buttons_col.operator(ObjectBuildSettingsMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'

            object_settings_active_index = group.object_settings_active_index
            num_object_settings = len(object_settings)
            if num_object_settings > 0 and 0 <= object_settings_active_index < num_object_settings:
                active_object_settings = object_settings[object_settings_active_index]
            else:
                active_object_settings = None

        if active_object_settings:
            # Extra col for label when disabled
            if not active_object_settings.include_in_build:
                disabled_label_col = main_col.column()
                disabled_label_col.alignment = 'RIGHT'
                disabled_label_col.use_property_split = True
                disabled_label_col.use_property_decorate = True
                disabled_label_col.label(text="Disabled. Won't be included in build")

            # Display the properties for the active settings
            settings_enabled = active_object_settings.include_in_build
            properties_col = main_column.column(align=True)
            properties_col.use_property_split = True
            properties_col.use_property_decorate = False
            properties_col.enabled = settings_enabled

            # Display the box for general object settings
            self.draw_general_object_box(properties_col, active_object_settings)

            # Display the box for armature settings if the object is an armature
            if obj.type == 'ARMATURE':
                self.draw_armature_box(properties_col, active_object_settings.armature_settings, obj)
            # Display the boxes for mesh settings if the object is a mesh
            elif obj.type == 'MESH':
                mesh_settings = active_object_settings.mesh_settings
                self.draw_mesh_boxes(properties_col, mesh_settings, obj)

            # Display a button to remove the settings from Avatar Builder when scene sync is enabled
            if is_synced:
                #final_col = layout.column()
                #properties_col.enabled = True
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
