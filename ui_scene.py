import bpy
from bpy.types import (
    Context,
    UILayout,
    Menu,
    Panel,
    Operator,
    Object,
    Mesh,
    Armature,
    SpaceProperties,
    SpaceView3D,
)
from typing import cast
from collections import defaultdict

from .registration import register_module_classes_factory
from .extensions import ScenePropertyGroup, ObjectPropertyGroup, MmdShapeKeySettings
from .op_build_avatar import BuildAvatarOp
from .ui_object import ObjectBuildSettingsAdd, ObjectPanelInScene
from .context_collection_ops import (
    PropCollectionType,
    ContextCollectionOperatorBase,
    CollectionAddBase,
    CollectionRemoveBase,
)
from . import utils


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
    # Before MMD Shape Mapping Panel by default
    bl_order = 0

    @staticmethod
    def draw_mmd(layout: UILayout, mmd_settings: MmdShapeKeySettings):
        layout.prop(mmd_settings, 'do_remap')
        if mmd_settings.do_remap:
            col = layout.column()
            col.use_property_split = True
            col.prop(mmd_settings, 'limit_to_body')
            col.prop(mmd_settings, 'remap_to')
            col.prop(mmd_settings, 'avoid_double_activation')

    def draw(self, context: Context):
        layout = self.layout
        layout.use_property_decorate = False
        group = ScenePropertyGroup.get_group(context.scene)
        col = layout.column()
        if group.is_export_scene:
            col.label(text=f"{context.scene.name} Export Scene")
            col.operator(DeleteExportScene.bl_idname, icon='TRASH')
        else:
            col.label(text="Scene Settings Groups")
            # TODO: Replace the 'new' Operator with an Operator that shows a menu of different 'new' options:
            #  blank (same as the current add), duplicate (same as simple, buildable Duplicate Operator), deep-copy
            #  (duplicate, but also duplicates ObjectBuildSettings on each Object)
            group.draw_search(col,
                              new=SceneBuildSettingsAdd.bl_idname,
                              unlink=SceneBuildSettingsRemove.bl_idname,
                              name_prop='name_prop')
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
                box_col = box.column()
                box_col.prop(scene_settings, 'ignore_hidden_objects')
                box_col.prop(scene_settings, 'reduce_to_two_meshes')
                if scene_settings.reduce_to_two_meshes:
                    sub = box_col.column()
                    sub.use_property_split = True
                    sub.alert = not scene_settings.shape_keys_mesh_name
                    sub.prop(scene_settings, 'shape_keys_mesh_name', icon="MESH_DATA", text="Shape keys")
                    sub.alert = not scene_settings.no_shape_keys_mesh_name
                    sub.prop(scene_settings, 'no_shape_keys_mesh_name', icon="MESH_DATA", text="No shape keys")
                    sub.alert = False
                self.draw_mmd(box_col, scene_settings.mmd_settings)

                box_col.prop(scene_settings, 'do_limit_total')
                if scene_settings.do_limit_total:
                    sub = box_col.column()
                    sub.use_property_split = True
                    sub.prop(scene_settings, 'limit_num_groups')


                # And finally the button for actually running Build Avatar
                box_col.operator(BuildAvatarOp.bl_idname, icon='SHADERFX')


class SceneBuildSettingsBase(ContextCollectionOperatorBase):
    @classmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        return ScenePropertyGroup.get_group(context.scene).collection

    @classmethod
    def get_active_index(cls, context: Context) -> int:
        return ScenePropertyGroup.get_group(context.scene).active_index

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        ScenePropertyGroup.get_group(context.scene).active_index = value


def _redraw_object_properties_panels(context: Context):
    view3d_panel_drawn = ObjectPanelInScene.poll(context)
    # Iterate through all areas in the current screen
    for area in context.screen.areas:
        if area.type == 'PROPERTIES':
            # If it's a Properties area, get its SpaceProperties (this is probably an unnecessarily safe way
            # to do so since I suspect there is only ever one Space and that it is always a SpaceProperties)
            space_properties = next((s for s in area.spaces if isinstance(s, SpaceProperties)), None)
            # We only care if the currently displayed properties are Object Properties, since that's where the
            # Object Panel is shown.
            if space_properties is not None and space_properties.context == 'OBJECT':
                # SpaceProperties can pin an ID (should always be an Object if .context == 'OBJECT')
                # Note that space_properties.use_pin_id doesn't actually determine if the pin is used, all it seems
                # to do is change the pin icon in the UI.
                pin_id = space_properties.pin_id
                if isinstance(pin_id, Object):
                    displayed_object = pin_id
                elif pin_id is not None:
                    # Pinned id can be a Mesh, Armature or many other types of Object data (though
                    # shouldn't be since .context == 'OBJECT')
                    displayed_object = None
                else:
                    # If there's no pin, then context.object is used.
                    # Note that if there are no Objects in the current scene, context.object can be None
                    displayed_object = context.object
                if (
                        displayed_object is not None
                        and displayed_object.type in ObjectPropertyGroup.ALLOWED_TYPES
                ):
                    for region in area.regions:
                        # The region in which the Panel is shown is the WINDOW
                        if region.type == 'WINDOW':
                            # Tell the WINDOW region to redraw
                            region.tag_redraw()
                            # If we found the WINDOW region before the end, we can skip the other regions
                            # (HEADER and NAVIGATION_BAR)
                            break
        elif view3d_panel_drawn and area.type == 'VIEW_3D':
            ui_region_shown = False
            # I think there's only ever a single space in the 3D View, but we'll loop to be sure
            for space in area.spaces:
                # SpaceView3D.show_region_ui indicates whether the right shelf (the 'UI' region) is displayed
                if isinstance(space, SpaceView3D) and space.show_region_ui:
                    ui_region_shown = True
                    break

            if ui_region_shown:
                # Find the 'UI' region
                for region in area.regions:
                    if region.type == 'UI':
                        # There doesn't appear to be a way to tell which tab of the UI region is active, nor does there
                        # appear to be a way to tell if a specific Panel is expanded or collapsed, so we will have to
                        # assume that the Panel's tab is active and that the Panel is expanded.
                        # Tell the UI region to redraw
                        region.tag_redraw()
                        # There should only be one UI region, so any remaining regions can be skipped
                        break


_op_builder = SceneBuildSettingsBase.op_builder(
    class_name_prefix='SceneBuildSettings',
    bl_idname_prefix='scene_build_settings',
    element_label="scene build settings",
)


@_op_builder.add.decorate
class SceneBuildSettingsAdd(CollectionAddBase, SceneBuildSettingsBase):
    def set_new_item_name(self, data, added):
        if self.name:
            added.name_prop = self.name
        else:
            # Rename if not unique and ensure that the internal name is also set
            orig_name = added.name_prop
            added_name = utils.get_unique_name(orig_name, data, number_separator=' ', min_number_digits=1)
            if added_name != orig_name:
                # Assigning the prop will also update the internal name
                added.name_prop = added_name
            else:
                added.name = added_name

    def execute(self, context: Context) -> set[str]:
        no_elements_to_start_with = not self.get_collection(context)
        result = super().execute(context)
        # If there weren't any settings to start with, and we just added new settings, we want to cause a UI redraw for
        # currently displayed Properties areas that are showing Object Properties of an Object with a type that can be
        # built. This is so that the .poll of the Object Panel gets called again, making the Panel appear due to the
        # fact that there are now some settings that exist.
        if no_elements_to_start_with and 'FINISHED' in result:
            _redraw_object_properties_panels(context)
        return result


# TODO: Also remove from objects in the scene! (maybe optionally)
@_op_builder.remove.decorate
class SceneBuildSettingsRemove(CollectionRemoveBase, SceneBuildSettingsBase):
    def execute(self, context: Context) -> set[str]:
        result = super().execute(context)
        if not self.get_collection(context):
            # If we've just removed the last settings, tell any Object Properties regions to redraw so that they update
            # for the fact that there are no longer any settings, meaning the Panel in Object Properties shouldn't be
            # drawn anymore
            _redraw_object_properties_panels(context)
        return result


class SceneBuildSettingsPurge(Operator):
    """Remove orphaned Build Settings from all Objects in every Scene."""
    bl_idname = "scene_build_settings_purge"
    bl_label = "Purge"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context: bpy.types.Context) -> set[str]:
        total_num_settings_removed = 0
        num_objects_removed_from = 0

        # Objects could be in multiple Scenes, so we need to find the possible SceneBuildSettings for each Object in
        # each Scene
        non_orphan_settings_per_object: dict[Object, set[str]] = defaultdict(set)
        for scene in bpy.data.scenes:
            scene_property_group = ScenePropertyGroup.get_group(scene)
            # Get the names of all SceneBuildSettings in this Scene
            settings_in_scene = {spg.name for spg in scene_property_group.collection}
            # Only need to look through the Objects in the Scene if there is at least one SceneBuildSettings
            if settings_in_scene:
                # Iterate through every Object in this Scene
                for obj in scene.objects:
                    # Only need to check Objects of the allowed types
                    if obj.type in ObjectPropertyGroup.ALLOWED_TYPES:
                        # Add the set of names of settings in this Scene to set of all names for this Object
                        non_orphan_settings_per_object[obj].update(settings_in_scene)

        # Iterate through all found Objects, removing any ObjectBuildSettings that are not in the set of names for the
        # Object being iterated
        for obj, non_orphan_groups in non_orphan_settings_per_object.items():
            object_group = ObjectPropertyGroup.get_group(obj)
            # Get the collection of ObjectBuildSettings
            settings_col = object_group.collection
            # Iterate in reverse so that we can remove settings without affecting the indices of settings we are yet to
            # iterate.
            num_settings_removed = 0
            for idx, settings in utils.enumerate_reversed(settings_col):
                # If the name of the ObjectBuildSettings doesn't match any of the SceneBuildSettings for this Object,
                # remove the ObjectBuildSettings
                settings_name = settings.name
                if settings_name not in non_orphan_groups:
                    settings_col.remove(idx)
                    num_settings_removed += 1
            num_remaining_settings = len(settings_col)
            if object_group.active_index >= num_remaining_settings:
                object_group.active_index = max(0, num_remaining_settings - 1)
            if num_settings_removed != 0:
                total_num_settings_removed += num_settings_removed
                num_objects_removed_from += 1

        self.report({'INFO'}, f"Removed {total_num_settings_removed} settings from {num_objects_removed_from} Objects.")
        if total_num_settings_removed != 0:
            # Cause a UI redraw
            _redraw_object_properties_panels(context)
        return {'FINISHED'}


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
                    object_settings = ObjectPropertyGroup.get_group(obj).collection
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
                object_settings = object_group.collection
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
                object_settings = object_group.collection
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
                object_settings = object_group.collection
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
                    object_settings = object_group.collection
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
                    object_settings = object_group.collection
                    if active_group_name in object_settings:
                        obj.hide_set(state=False, view_layer=vl)
                        if self.select:
                            obj.select_set(state=True, view_layer=vl)
        return {'FINISHED'}


del _op_builder
register, unregister = register_module_classes_factory(__name__, globals())
