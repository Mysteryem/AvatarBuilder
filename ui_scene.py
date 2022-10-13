import bpy
from bpy.types import UIList, Context, UILayout, Menu, Panel, Operator, Object, Mesh, Armature
from typing import cast
from bpy.props import EnumProperty

from .registration import register_module_classes_factory
from .extensions import ScenePropertyGroup, ObjectPropertyGroup
from .op_build_avatar import BuildAvatarOp
from .ui_object import ObjectBuildSettingsAdd
from .context_collection_ops import (
    PropCollectionType,
    ContextCollectionOperatorBase,
    CollectionAddBase,
    CollectionRemoveBase,
    CollectionMoveBase,
)


class SceneBuildSettingsUIList(UIList):
    bl_idname = "scene_build_settings"

    def draw_item(self, context: Context, layout: UILayout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        #layout.label(text="", icon_value=icon)
        layout.prop(item, 'name_prop', text="", emboss=False, icon="SETTINGS")


class SceneBuildSettingsMenu(Menu):
    bl_idname = "scene_build_menu"
    bl_label = "Build Settings Specials"

    def draw(self, context):
        pass


class ScenePanel(Panel):
    bl_idname = "scene_panel"
    bl_label = "Avatar Builder"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Avatar Builder"

    def draw(self, context: Context):
        layout = self.layout
        group = ScenePropertyGroup.get_group(context.scene)
        col = layout.column()
        if group.is_export_scene:
            col.label(text=f"{context.scene.name} Export Scene")
            col.operator(DeleteExportScene.bl_idname, icon='TRASH')
        else:
            col.label(text="Scene Settings Groups")
            row = col.row()
            row.template_list(SceneBuildSettingsUIList.bl_idname, "", group, 'build_settings', group, 'build_settings_active_index')
            vertical_buttons_col = row.column(align=True)
            vertical_buttons_col.operator(SceneBuildSettingsAdd.bl_idname, text="", icon="ADD")
            vertical_buttons_col.operator(SceneBuildSettingsRemove.bl_idname, text="", icon="REMOVE")
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(SceneBuildSettingsMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
            vertical_buttons_col.operator(SceneBuildSettingsMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'

            buttons_col = col.column(align=True)
            # TODO: Sync is only useful if forced sync is turned off, so only display it in those cases
            row = buttons_col.row(align=True)
            row.operator(SceneBuildSettingsSync.bl_idname, text="Sync")
            row.operator(SceneBuildSettingsPurge.bl_idname, text="Purge")
            row = buttons_col.row(align=True)
            row.operator(SelectObjectsInSceneSettings.bl_idname)
            row.operator(UnhideFromSceneSettings.bl_idname)
            row.operator(DisableHiddenFromSceneSettings.bl_idname)
            row = buttons_col.row(align=True)
            row.operator(AddSelectedToSceneSettings.bl_idname)
            row.operator(EnableSelectedFromSceneSettings.bl_idname)
            row.operator(DisableSelectedFromSceneSettings.bl_idname)

            col = layout.column()
            scene_settings = group.get_active()
            if scene_settings:
                box = col.box()
                sub = box.column()
                sub.alignment = 'RIGHT'
                sub.prop(scene_settings, 'reduce_to_two_meshes')
                if scene_settings.reduce_to_two_meshes:
                    sub = box.column()
                    sub.enabled = scene_settings.reduce_to_two_meshes
                    sub.use_property_split = True
                    sub.alert = not scene_settings.shape_keys_mesh_name
                    sub.prop(scene_settings, 'shape_keys_mesh_name', icon="MESH_DATA", text="Shape keys")
                    sub.alert = not scene_settings.no_shape_keys_mesh_name
                    sub.prop(scene_settings, 'no_shape_keys_mesh_name', icon="MESH_DATA", text="No shape keys")
                    sub.alert = False
                sub.use_property_split = False
                sub.prop(scene_settings, 'ignore_hidden_objects')
                sub.operator(BuildAvatarOp.bl_idname)


class SceneBuildSettingsBase(ContextCollectionOperatorBase):
    @classmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        return ScenePropertyGroup.get_group(context.scene).build_settings

    @classmethod
    def get_active_index(cls, context: Context) -> int:
        return ScenePropertyGroup.get_group(context.scene).build_settings_active_index

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        ScenePropertyGroup.get_group(context.scene).build_settings_active_index = value


class SceneBuildSettingsAdd(CollectionAddBase, SceneBuildSettingsBase):
    """Add new scene build settings"""
    bl_idname = "scene_build_settings_add"

    def set_new_item_name(self, data, added):
        if self.name:
            added.name_prop = self.name
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


# TODO: Also remove from objects in the scene! (maybe optionally)
class SceneBuildSettingsRemove(CollectionRemoveBase, SceneBuildSettingsBase):
    """Remove the active build settings"""
    bl_idname = "scene_build_settings_remove"


class SceneBuildSettingsMove(CollectionMoveBase, SceneBuildSettingsBase):
    """Move the active scene build settings up or down the list"""
    bl_idname = "scene_build_settings_move"

    type: EnumProperty(
        items=(
            ('UP', "Up", "Move settings up, wrapping around if already at the top"),
            ('DOWN', "Down", "Move settings down, wrapping around if already at the bottom"),
            ('TOP', "Top", "Move settings to the top"),
            ('BOTTOM', "Bottom", "Move settings to the bottom"),
        ),
        name="Type",
    )


class SceneBuildSettingsPurge(Operator):
    """Clear all orphaned Build Settings from all objects in the scene
    (Not yet implemented)"""
    bl_idname = "scene_build_settings_purge"
    bl_label = "Purge"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return False

    def execute(self, context: bpy.types.Context) -> set[str]:
        return {'FINISHED'}


# TODO: Implement and add a 'Fake User' BoolProperty to Object Settings that prevents purging
# TODO: By default we only show the object settings matching the scene settings, so is this necessary?
class SceneBuildSettingsSync(Operator):
    """Set the currently displayed settings of all objects in the scene to the currently active Build Settings
    (Not yet implemented)"""
    bl_idname = "scene_build_settings_sync"
    bl_label = "Purge"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return False

    def execute(self, context: bpy.types.Context) -> set[str]:
        return {'FINISHED'}


class SceneBuildSettingsDuplicate(Operator):
    """Duplicate the active build settings, additionally duplicating them on all objects in the current scene if they
    exist
    (Not yet implemented)"""
    bl_idname = "scene_build_settings_duplicate"
    bl_label = "Duplicate"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return False

    def execute(self, context: bpy.types.Context) -> set[str]:
        return {'FINISHED'}


class DeleteExportScene(Operator):
    bl_idname = "delete_export_scene"
    bl_label = "Delete Export Scene"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context) -> bool:
        return bpy.ops.scene.delete.poll() and ScenePropertyGroup.get_group(context.scene).is_export_scene

    def execute(self, context: Context) -> set[str]:
        export_scene = context.scene
        obj: Object
        for obj in export_scene.objects:
            # Deleting data also deletes any objects using that data when do_unlink=True (default value)
            data = obj.data
            if obj.type == 'MESH':
                data = cast(Mesh, data)
                shape_keys = data.shape_keys
                if shape_keys:
                    obj.shape_key_clear()
                bpy.data.meshes.remove(data)
            elif obj.type == 'ARMATURE':
                bpy.data.armatures.remove(cast(Armature, data))
            else:
                bpy.data.objects.remove(obj)
        group = ScenePropertyGroup.get_group(export_scene)
        original_scene_name = group.export_scene_source_scene

        # Switching the scene to the original scene before deleting seems to crash blender sometimes????
        # Another workaround seems to be to  delete the objects after the scene has been deleted instead of before

        # If this is somehow the only scene, deleting isn't possible
        if bpy.ops.scene.delete.poll():
            bpy.ops.scene.delete()

        if original_scene_name:
            original_scene = bpy.data.scenes.get(original_scene_name)
            if original_scene:
                context.window.scene = original_scene
        return {'FINISHED'}


class SelectObjectsInSceneSettings(Operator):
    """Select objects in the active scene settings"""
    bl_idname = "select_objects_in_scene_settings"
    bl_label = "Select Active"
    bl_options = {'REGISTER', 'UNDO'}

    # TODO: extend property
    include_disabled: bpy.props.BoolProperty(
        name="Include Disabled",
        description="Include objects where the active scene settings are currently disabled",
        default=False,
    )

    def execute(self, context: Context) -> set[str]:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active:
            active_group_name = active.name
            vl = context.view_layer
            for obj in context.visible_objects:
                if not obj.select_get(view_layer=vl):
                    object_settings = ObjectPropertyGroup.get_group(obj).object_settings
                    if active_group_name in object_settings:
                        if self.include_disabled or object_settings[active_group_name].include_in_build:
                            obj.select_set(state=True, view_layer=vl)
        return {'FINISHED'}


class AddSelectedToSceneSettings(Operator):
    """Add selected objects to the active scene settings if they do not already exist"""
    bl_idname = "add_selected_to_scene_settings"
    bl_label = "Add Selected"
    bl_options = {'REGISTER', 'UNDO'}

    # TODO: name property so that the group to add to can be overwritten

    def execute(self, context: Context) -> set[str]:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active:
            active_group_name = active.name
            for obj in context.selected_objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.object_settings
                if active_group_name not in object_settings:
                    added = object_settings.add()
                    ObjectBuildSettingsAdd.set_new_item_name_static(object_settings, added, active_group_name)
        return {'FINISHED'}


class DisableSelectedFromSceneSettings(Operator):
    """Disable the active scene settings on the selected objects if the settings exist"""
    bl_idname = "disable_selected_from_scene_settings"
    bl_label = "Disable Selected"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: Context) -> set[str]:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active:
            active_group_name = active.name
            for obj in context.selected_objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.object_settings
                if active_group_name in object_settings:
                    object_settings[active_group_name].include_in_build = False
        return {'FINISHED'}


class EnableSelectedFromSceneSettings(Operator):
    """Enable the active scene settings on the selected objects if the settings exist"""
    bl_idname = "enable_selected_from_scene_settings"
    bl_label = "Enable Selected"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: Context) -> set[str]:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active:
            active_group_name = active.name
            for obj in context.selected_objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.object_settings
                if active_group_name in object_settings:
                    object_settings[active_group_name].include_in_build = True
        return {'FINISHED'}


class DisableHiddenFromSceneSettings(Operator):
    """Disable the active scene settings on the hidden objects if the settings exist"""
    bl_idname = "disable_hidden_from_scene_settings"
    bl_label = "Disable Hidden"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: Context) -> set[str]:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active:
            vl = context.view_layer
            active_group_name = active.name
            for obj in vl.objects:
                if obj.hide_get(view_layer=vl):
                    object_group = ObjectPropertyGroup.get_group(obj)
                    object_settings = object_group.object_settings
                    if active_group_name in object_settings:
                        object_settings[active_group_name].include_in_build = False
        return {'FINISHED'}


class UnhideFromSceneSettings(Operator):
    """Unhide objects which are in the active scene settings"""
    bl_idname = "unhide_selected_from_scene_settings"
    bl_label = "Reveal Hidden"
    bl_options = {'REGISTER', 'UNDO'}

    select: bpy.props.BoolProperty(name="Select", description="Select the objects", default=True)

    def execute(self, context: Context) -> set[str]:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active:
            vl = context.view_layer
            active_group_name = active.name
            for obj in vl.objects:
                if obj.hide_get(view_layer=vl):
                    object_group = ObjectPropertyGroup.get_group(obj)
                    object_settings = object_group.object_settings
                    if active_group_name in object_settings:
                        obj.hide_set(state=False, view_layer=vl)
                        if self.select:
                            obj.select_set(state=True, view_layer=vl)
        return {'FINISHED'}


register, unregister = register_module_classes_factory(__name__, globals())
