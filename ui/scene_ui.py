import bpy
from bpy.types import UIList, Context, UILayout, Menu, Panel, Operator, Object, Mesh
from bpy.props import EnumProperty

from ..registration import register_module_classes_factory
from ..extensions import ScenePropertyGroup
from ..ops.build_avatar import BuildAvatarOp


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
            vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="ADD").command = 'ADD'
            vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="REMOVE").command = 'REMOVE'
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="TRIA_UP").command = 'UP'
            vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN").command = 'DOWN'

            buttons_col = col.column(align=True)
            # TODO: Sync is only useful if forced sync is turned off, so only display it in those cases
            row = buttons_col.row(align=True)
            row.operator(SceneBuildSettingsControl.bl_idname, text="Sync").command = 'SYNC'
            row.operator(SceneBuildSettingsControl.bl_idname, text="Purge").command = 'PURGE'

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


# TODO: Split into different operators so that we can use different poll functions, e.g. disable move ops and remove op
#  when there aren't any settings in the array
class SceneBuildSettingsControl(Operator):
    bl_idname = 'scene_build_settings_control'
    bl_label = "Build Settings Control"

    # TODO: Add a DUPLICATE command that duplicates the current SceneBuildSettings and also duplicates the
    #  ObjectBuildSettings for all Objects in the scene if that Object has ObjectBuildSettings that correspond to the
    #  SceneBuildSettings being duplicated
    command_items = (
        ('ADD', "Add", "Add a new set of Build Settings"),
        ('REMOVE', "Remove", "Remove the currently active Scene Settings"),
        ('UP', "Move Up", "Move active Scene Settings up"),
        ('DOWN', "Move Down", "Move active Scene Settings down"),
        ('PURGE', "Purge", "Clear all orphaned Build Settings from all objects in the scene"),
        ('TOP', "Move to top", "Move active Scene Settings to top"),
        ('BOTTOM', "Move to bottom", "Move active Build Settings to bottom"),
        # TODO: Implement and add a 'Fake User' BoolProperty to Object Settings that prevents purging
        # TODO: By default we only show the object settings matching the scene settings, so is this necessary?
        ('SYNC', "Sync", "Set the currently displayed settings of all objects in the scene to the currently active Build Settings"),
    )

    command: EnumProperty(
        items=command_items,
        default='ADD',
    )

    @classmethod
    def description(cls, context, properties):
        command = properties.command
        for identifier, _, description in cls.command_items:
            if identifier == command:
                return description
        return f"Error: enum value '{command}' not found"

    def execute(self, context: Context):
        scene_group = ScenePropertyGroup.get_group(context.scene)
        active_index = scene_group.build_settings_active_index
        build_settings = scene_group.build_settings
        command = self.command
        if command == 'ADD':
            added = build_settings.add()
            # Rename if not unique and ensure that the internal name is also set
            added_name = added.name_prop
            orig_name = added_name
            unique_number = 0
            # Its internal name of the newly added build_settings will currently be "" since it hasn't been set
            # We could do `while added_name in build_settings:` but I'm guessing Blender has to iterate through each
            # element until `added_name` is found since duplicate names are allowed. Checking against a set should be
            # faster if there are lots
            existing_names = {bs.name for bs in build_settings}
            while added_name in existing_names:
                unique_number += 1
                added_name = orig_name + " " + str(unique_number)
            if added_name != orig_name:
                # Assigning the prop will also update the internal name
                added.name_prop = added_name
            else:
                added.name = added_name
            # Set active to the new element
            scene_group.build_settings_active_index = len(scene_group.build_settings) - 1
        elif command == 'REMOVE':
            # TODO: Also remove from objects in the scene! (maybe optionally)
            build_settings.remove(active_index)
            was_last_index = active_index >= len(build_settings)
            if was_last_index:
                scene_group.build_settings_active_index = max(0, active_index - 1)
        elif command == 'SYNC':
            self.report({'INFO'}, "Sync is not implemented yet")
        elif command == 'UP':
            # Previous index, with wrap around to the bottom
            new_index = (active_index - 1) % len(build_settings)
            build_settings.move(active_index, new_index)
            scene_group.build_settings_active_index = new_index
        elif command == 'DOWN':
            # Next index, with wrap around to the top
            new_index = (active_index + 1) % len(build_settings)
            build_settings.move(active_index, new_index)
            scene_group.build_settings_active_index = new_index
        elif command == 'TOP':
            new_index = 0
            build_settings.move(active_index, new_index)
            scene_group.build_settings_active_index = new_index
        elif command == 'BOTTOM':
            new_index = len(build_settings) - 1
            build_settings.move(active_index, new_index)
            scene_group.build_settings_active_index = new_index
        return {'FINISHED'}


class DeleteExportScene(Operator):
    bl_idname = "delete_export_scene"
    bl_label = "Delete Export Scene"

    @classmethod
    def poll(cls, context) -> bool:
        return bpy.ops.scene.delete.poll() and ScenePropertyGroup.get_group(context.scene).is_export_scene

    def execute(self, context: Context) -> str:
        export_scene = context.scene
        obj: Object
        for obj in export_scene.objects:
            # Deleting data also deletes any objects using that data when do_unlink=True (default value)
            data = obj.data
            if isinstance(data, Mesh):
                shape_keys = data.shape_keys
                if shape_keys:
                    obj.shape_key_clear()
                bpy.data.meshes.remove(obj.data)
            elif obj.type == 'ARMATURE':
                bpy.data.armatures.remove(obj.data)
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


register, unregister = register_module_classes_factory(__name__, globals())
