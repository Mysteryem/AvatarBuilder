from typing import Type, Any, Union, TypeVar, Callable
from dataclasses import dataclass
from collections import defaultdict
import numpy as np
import bpy
from bpy.props import StringProperty, BoolProperty, CollectionProperty, IntProperty, EnumProperty, PointerProperty
from bpy.types import (Armature, PropertyGroup, Operator, Panel, UIList, Object, ShapeKey, Mesh, ID, Bone, PoseBone,
                       Context, Menu, UILayout, Scene, MeshUVLoopLayer, Modifier, ArmatureModifier)
# Conflict with the bpy.props function of the same name
from bpy.types import CollectionProperty as CollectionPropertyType


# bpy_prop_collection_idprop isn't currently exposed in bpy.types, so it can't actually be imported. It's presence here
# is purely to assist with development.
# noinspection PyUnreachableCode
if hasattr(bpy.types, 'bpy_prop_collection_idprop'):
    from bpy.types import bpy_prop_collection_idprop
else:
    bpy_prop_collection_idprop = bpy.types.bpy_prop_collection

bl_info = {
    "name": "Avatar Builder",
    "author": "Mysteryem",
    "version": (0, 0, 1),
    "blender": (2, 93, 7),
    "location": "3D View and Object Properties",
    "tracker_url": "https://github.com/Mysteryem/Miscellaneous/issues",
    "category": "3D View",
}


# want to have the settings for objects defined on objects
# BUT
# want to have different sets of settings, e.g. one for VRC, one for VRM
# BUT might want to put some settings on MESH or ARMATURE directly, instead of OBJECT
#
# Settings for MESH (or MESH object)
# Remap materials or reduce to single specified material
# Apply current shape key mix and remove all shape keys
# Apply non-armature modifiers (data transfer won't work, TODO: Try data transfer with the existing object as the target instead of the copy object which we know doesn't work

# Each object would have a collection, but only show the active collection in the UI (active collection is specified on the scene)

# Care would need to be taken to make sure that every objects' collections match up with the collections defined on the scene (if we can get collection elements by name, this would be simpler)

# Type hint for any Blender type that can have custom properties assigned to it
PropHolderType = Union[ID, Bone, PoseBone]

# Prefix
_BL_ID_PREFIX = "mysteryem_avatar_builder"
_PROP_PREFIX = _BL_ID_PREFIX

# Mapping from space type to panel prefix
_PANEL_SPACE_TYPE_PREFIX = {
    'CLIP_EDITOR': 'CLIP',
    'CONSOLE': 'CONSOLE',  # not used by Blender
    'DOPESHEET_EDITOR': 'DOPESHEET',
    'EMPTY': 'EMPTY',  # not used by Blender
    'FILE_BROWSER': 'FILEBROWSER',
    'GRAPH_EDITOR': 'GRAPH',
    'IMAGE_EDITOR': 'IMAGE',
    'INFO': 'INFO',  # not used by Blender
    'NLA_EDITOR': 'NLA',
    # NODE_EDITOR uses the defaultdict below for more specific prefixes
    # 'NODE_EDITOR': 'NODE',
    'OUTLINER': 'OUTLINER',
    'PREFERENCES': 'USERPREF',
    'PROPERTIES': 'PROPERTIES',
    'SEQUENCE_EDITOR': 'SEQUENCER',
    'SPREADSHEET': 'SPREADSHEET',  # not used by Blender
    'STATUSBAR': 'STATUSBAR',  # not used by Blender
    'TEXT_EDITOR': 'TEXT',
    'TOPBAR': 'TOPBAR',
    'VIEW_3D': 'VIEW3D',
}

_NODE_EDITOR_PANEL_SPACE_TYPE_PREFIX = defaultdict(
    lambda: defaultdict(lambda: 'NODE'),
    {
        'LIGHT': defaultdict(lambda: 'NODE', {'CYCLES': 'NODE_CYCLES_LIGHT'}),
        'WORLD': defaultdict(lambda: 'NODE_WORLD', {'CYCLES': 'NODE_CYCLES_WORLD'}),
        'MATERIAL': defaultdict(
            lambda: 'NODE_MATERIAL', {'CYCLES': 'NODE_CYCLES_MATERIAL', 'EEVEE': 'NODE_EEVEE_MATERIAL'}
        ),
        'DATA': defaultdict(lambda: 'NODE_DATA'),
    }
)


def get_panel_prefix(panel_cls: Type[Panel], node_type=None, node_engine_type=None):
    space_type = panel_cls.bl_space_type
    if space_type == 'NODE_EDITOR':
        return _NODE_EDITOR_PANEL_SPACE_TYPE_PREFIX[node_type][node_engine_type]
    else:
        return _PANEL_SPACE_TYPE_PREFIX[space_type]


def update_name_ensure_unique(element_updating: PropertyGroup, collection_prop: bpy_prop_collection_idprop,
                              name_prop_name: str):
    """Helper function for ensuring name uniqueness with collection properties"""
    # Ensure name uniqueness by renaming the other found element with the same name, if it exists

    # Note that care is needed when renaming another element, since that will call this function too, but for that
    # element

    # The internal name should always be the old name, since it's only this function that updates it after initial
    # creation
    old_name = element_updating.name
    new_name = getattr(element_updating, name_prop_name)

    if new_name == old_name:
        # Nothing to do
        return
    try:
        # Get all existing internal names, excluding our new one
        existing_names = {bs.name for bs in collection_prop} - {old_name}
        print(f"Updating name of '{element_updating}' from '{old_name}' to '{new_name}'")
        if new_name in collection_prop:
            # print("New name already exists!")
            existing_element = collection_prop[new_name]

            existing_element_new_name = new_name

            # Make sure we can't possibly set the existing element's name to the new name of self or any other elements
            disallowed_names = existing_names.union({new_name})

            # Since we just got this element by name, this must be its current name
            existing_element_name = new_name

            # Strip ".[0-9]+" from the end of the name to get the original name
            last_period_idx = existing_element_name.rfind(".")
            if last_period_idx != -1:
                # Everything after the last period
                suffix = existing_element_name[last_period_idx + 1:]
                if suffix.isdigit():
                    # Original name is everything before the last period
                    existing_element_orig_name = existing_element_name[:last_period_idx]
                else:
                    # The name has "." in it, but either there is nothing after it or there are characters that aren't
                    # digits
                    existing_element_orig_name = existing_element_name
            else:
                # The name doesn't have "." in it, so use it as is
                existing_element_orig_name = existing_element_name

            # TODO: Could check if existing_element_orig_name in disallowed_names first

            suffix_number = 0
            while existing_element_new_name in disallowed_names:
                suffix_number += 1
                # my_name -> my_name.001 -> my_name.002 -> my_name.003 etc.
                existing_element_new_name = f"{existing_element_orig_name}.{suffix_number:03d}"
                # print(f"Trying new name '{existing_element_new_name}'")

            # Update the name of the existing element, so it won't conflict with the new name of self and won't conflict
            # with the names of any other elements either

            # print(f"Renaming already existing element with the same name as the new name '{new_name}' to '{existing_element_new_name}'")

            # Need to update the name of self first, otherwise when we change the name_prop of the existing element,
            # it will see the old name of self
            element_updating.name = new_name
            setattr(existing_element, name_prop_name, existing_element_new_name)
            # print(f"Renamed already existing element with the same name as the new name '{new_name}'")
    finally:
        # Always update internal name to match, this name is used when subscripting the collection to get a specific element
        element_updating.name = new_name
    # Return name change so that it can be propagated to objects when updating a SceneBuildSettings
    return old_name, new_name


def scene_build_settings_update_name(self: 'SceneBuildSettings', context: Context):
    scene = context.scene
    scene_group = ScenePropertyGroup.get_group(scene)
    build_settings = scene_group.build_settings

    old_name, new_name = update_name_ensure_unique(self, build_settings, 'name_prop')

    if old_name != new_name:
        # Propagate name change to object settings of objects in the corresponding scene
        for obj in scene.objects:
            object_group = ObjectPropertyGroup.get_group(obj)
            object_settings = object_group.object_settings
            if old_name in object_settings:
                object_settings[old_name].name_prop = new_name


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


# TODO: Split into different operators so that we can use different poll functions, e.g. disable move ops and remove op
#  when there aren't any settings in the array
class ObjectBuildSettingsControl(Operator):
    bl_idname = 'object_build_settings_control'
    bl_label = "Object Build Settings Control"

    command_items = (
        ('ADD', "Add", "Add a new set of build settings, defaults to the active build settings if they don't exist on this Object"),
        ('REMOVE', "Remove", "Remove the currently active build settings"),
        # Disabled if doesn't exist on the object
        ('UP', "Move Up", "Move active build settings up"),
        ('DOWN', "Move Down", "Move active build settings down"),
        ('SYNC', "Sync", "Set the currently displayed settings of to the currently active build settings"),
        ('TOP', "Move to top", "Move active build settings to top"),
        ('BOTTOM', "Move to bottom", "Move active build settings to bottom"),
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
        obj = context.object
        object_group = ObjectPropertyGroup.get_group(obj)
        # With sync enabled, we often ignore the active index, instead preferring to use the settings that match the
        # active build settings
        sync_enabled = object_group.sync_active_with_scene

        object_build_settings = object_group.object_settings
        active_index = object_group.object_settings_active_index

        command = self.command

        if sync_enabled:
            if command == 'ADD':
                active_build_settings = ScenePropertyGroup.get_group(context.scene).get_active()
                if active_build_settings and active_build_settings.name not in object_build_settings:
                    added = object_build_settings.add()
                    added.name_prop = active_build_settings.name
                    object_group.object_settings_active_index = len(object_build_settings) - 1
                    return {'FINISHED'}
                else:
                    return {'CANCELLED'}
            elif command == 'REMOVE':
                active_build_settings = ScenePropertyGroup.get_group(context.scene).get_active()
                if active_build_settings:
                    index = object_build_settings.find(active_build_settings.name)
                    if index != -1:
                        object_build_settings.remove(index)
                        was_last_index = active_index >= len(object_build_settings)
                        if was_last_index:
                            object_group.object_settings_active_index = max(0, active_index - 1)
                        return {'FINISHED'}
                    else:
                        return {'CANCELLED'}
            elif command in {'SYNC', 'UP', 'DOWN', 'TOP', 'BOTTOM'}:
                # Sync is enabled, this doesn't make sense
                return {'CANCELLED'}
        else:
            if command == 'ADD':
                added = object_build_settings.add()

                # Rename if not unique and ensure that the internal name is also set
                added_name = added.name_prop
                orig_name = added_name
                unique_number = 0
                # Its internal name of the newly added build_settings will currently be "" since it hasn't been set
                # We could do `while added_name in build_settings:` but I'm guessing Blender has to iterate through each
                # element until `added_name` is found since duplicate names are allowed. Checking against a set should be
                # faster if there are lots
                existing_names = {bs.name for bs in object_build_settings}
                while added_name in existing_names:
                    unique_number += 1
                    added_name = orig_name + " " + str(unique_number)
                if added_name != orig_name:
                    # Assigning the prop will also update the internal name
                    added.name_prop = added_name
                else:
                    added.name = added_name
                # Set active to the new element
                object_group.object_settings_active_index = len(object_build_settings) - 1
            elif command == 'REMOVE':
                object_build_settings.remove(active_index)
                object_group.object_settings_active_index = active_index - 1
            elif command == 'SYNC':
                scene_active = ScenePropertyGroup.get_group(context.scene).get_active()
                if scene_active:
                    index = object_build_settings.find(scene_active.name)
                    if index != -1:
                        object_group.object_settings_active_index = index
                        return {'FINISHED'}
                return {'CANCELLED'}
            elif command == 'UP':
                # Previous index, with wrap around to the bottom
                new_index = (active_index - 1) % len(object_build_settings)
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'DOWN':
                # Next index, with wrap around to the top
                new_index = (active_index + 1) % len(object_build_settings)
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'TOP':
                new_index = 0
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'BOTTOM':
                new_index = len(object_build_settings) - 1
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            return {'FINISHED'}


class SceneBuildSettings(PropertyGroup):
    # Shown in UI
    # Create export scene as f"Export {build_settings.name} scene"
    name_prop: StringProperty(default="BuildSettings", update=scene_build_settings_update_name)

    reduce_to_two_meshes: BoolProperty(
        name="Reduce to two meshes",
        description="Reduce to two meshes as a final step, one mesh that has shape keys and a second mesh that doesn't have shape keys",
        default=True
    )
    shape_keys_mesh_name: StringProperty(default="Body")
    no_shape_keys_mesh_name: StringProperty(default="MainBody")
    ignore_hidden_objects: BoolProperty(name="Ignore hidden objects", default=True)
    # TODO: Needs UI and needs to actually be used
    remove_settings_from_built_avatar: BoolProperty(name="Remove settings from built avatar", default=True)
    # TODO: Add the option below to join mesh UVMaps by index instead of name
    # uv_map_joining: EnumProperty(
    #     items=[
    #         (
    #             'NAME',
    #             "By name",
    #             "Join UV Maps by name, this is the default Blender behaviour when joining meshes"
    #         ),
    #         (
    #             'INDEX',
    #             "By index",
    #             "Join UV Maps by index. This will results in all UV Maps being renamed according to their index"
    #         ),
    #         # TODO: Add a 'FIRST_BY_INDEX_OTHERS_BY_NAME' option, basically, just rename the first UVMap of every mesh to
    #         #  "UVMap" before any joining happens
    #     ],
    #     name="Join UV Maps",
    #     default='INDEX',
    #     description="Specify how UV Maps of meshes should be combined when meshes are joined together",
    # )


def object_build_settings_update_name(self: 'ObjectBuildSettings', context: Context):
    scene = context.scene
    scene_group = ScenePropertyGroup.get_group(scene)
    build_settings = scene_group.build_settings

    # id_data is the ID that owns this which should be the object
    obj = self.id_data
    object_group = ObjectPropertyGroup.get_group(obj)

    update_name_ensure_unique(self, object_group.object_settings, 'name_prop')


class ObjectBuildSettings(PropertyGroup):
    name_prop: StringProperty(default="BuildSettings", update=object_build_settings_update_name)

    # Could use a string type and match by name instead, TODO: in both cases, consider what happens or needs to happen if the BuildSettings are deleted or renamed
    #build_settings: bpy.props.PointerProperty(type=SceneBuildSettings)
    # General properties
    target_object_name: StringProperty(
        name="Built name",
        description="The name of the object once building is complete.\n"
                    "All objects with the same name will be joined together (if they're the same type)\n"
                    "Leave blank to keep the current name"
    )
    include_in_build: BoolProperty(name="Include in build", default=True, description="Include these build settings. This lets you disable the export without deleting settings")

    # Armature object properties
    armature_export_pose: EnumProperty(
        name="Export pose",
        description="Pose to set when exporting",
        items=[
            ('REST', "Rest Position", ""),
            ('POSE', "Pose Position", ""),
            ('CUSTOM_ASSET_LIBRARY', "Custom", ""),
            ('CUSTOM_POSE_LIBRARY', "Pose Library Marker (deprecated)", ""),
        ],
        default="POSE"
    )
    armature_export_pose_library_marker: StringProperty(name="Pose", description="Pose Library Marker (deprecated)")

    # TODO: Find out how asset viewer stuff works as the replacement for Pose Libraries
    #armature_export_pose_asset_library: PointerProperty()

    # TODO: Access via obj.pose_markers[name] when used
    armature_export_pose_pose_library_marker_name: StringProperty()

    # Change all the armature modifiers on meshes using this armature to the following setting for Preserve volume
    # modifier-controlled/yes/no
    armature_export_pose_preserve_volume: EnumProperty(
        name="Preserve volume",
        items=[
            ('MODIFIER', "Modifier controlled", ""),
            ('YES', "Enabled", ""),
            ('NO', "Disabled", ""),
        ],
        description="Intended for use to override modifier settings when exporting for VRM, which requires a T-pose."
                    "\n\nWhen a model has been exported in an A-pose, put into a T-pose in Unity and exported as a VRM,"
                    " putting that VRM back into the original A-pose can result in a different appearance to how the"
                    " model was original exported."
                    "\n\nEnabling Preserve Volume and changing the pose to a T-pose before exporting may produce better"
                    " results than when exporting in an A-pose."
    )

    ignore_reduce_to_two_meshes: BoolProperty(default=False)

    # TODO: If the shape key operations were put into a PropertyGroup, we could then have a CollectionProperty where we
    #  can add as many operations as we want.
    #  e.g.
    #  - Add an operation to delete all shape keys before/after <shape key name>
    #  - Add an operation to delete all shape keys between <shape key 1> <shape key 2>
    #  - Add an operation to apply one of the different merge operations
    #  And maybe in the future:
    #  - Add a special mmd convert, translate and rename conflicts operation
    # Mesh props
    # Keep/Merge(see below)/Apply Mix/Delete-All
    shape_keys_op: EnumProperty(
        name="EXtra Operation",
        items=[
            ('KEEP', "Keep", "Keep all the shape keys"),
            ('MERGE', "Merge", "Merge shape keys together, according to the rules below"),
            ('APPLY_MIX', "Apply Mix", "Set the mesh to the current mix of all the shape keys and then delete all the shape keys"),
            ('DELETE_ALL', "Delete All", "Delete all the shape keys"),
        ],
        default='KEEP'
    )

    # TODO: prop to remove empty shapes (with a tolerance setting?)

    delete_shape_keys_after: StringProperty(
        name="Delete after",
        description="Delete shape keys after the specified shape key."
                    " Can be used with Delete shape keys before to delete all shape keys between the two.")
    delete_shape_keys_before: StringProperty(
        name="Delete before",
        description="Delete shape keys before the specified shape key."
                    " Can be used with Delete shape keys after to delete all shape keys between the two."
                    " Will not delete the 'Basis' shape key")

    # Merge by prefix/suffix/common-before-last-delimiter/common-after-first-delimiter none/all/consecutive-only
    # TODO: Could make this into a multiple-choice enum, merge_shape_keys_prefix_suffix would then have to be split
    #  into one property for each option
    # TODO: Rename property
    merge_shape_keys: EnumProperty(
        name="Merge pattern",
        items=[
            ('PREFIX', "Prefix",
                "Shape keys with the specified prefix will be merged together"
            ),
            ('SUFFIX', "Suffix",
                "Shape keys with the specified suffix will be merged together"
             ),
            # TODO: Could also have modes that ignore shape keys that don't have the delimiter
            ('COMMON_BEFORE_LAST', "Common before last delimiter",
                "Shape keys that have the same characters before the last found delimiter in their name will be merged"
                " together.\n"
                'e.g. "Smile", "Smile_part1" and "Smile_part2" when the delimiter is "_"\n'
                "The delimiter and common part will be removed from the merged shape key"
            ),
            ('COMMON_AFTER_FIRST', "Common after first delimiter",
                "Shape keys that have the same characters after the first found delimiter in their name will be merged"
                " together.\n"
                'e.g. "frown", "part1.frown" and "part2.frown" when the delimiter is "."\n'
            ),
        ],
        default='COMMON_BEFORE_LAST'
    )

    # TODO: Rename property
    merge_shape_keys_pattern: EnumProperty(
        name="Merge grouping",
        items=[
            ('ALL', "All", "All shape keys matching the same pattern will be merged together"),
            ('CONSECUTIVE', "Consecutive", "Only consecutive shape keys matching the same pattern will be merged together"),
        ],
        default='CONSECUTIVE',
    )
    merge_shape_keys_prefix_suffix: StringProperty()

    #merge_shape_keys_delimiter: StringProperty(default=".")
    merge_shape_keys_ignore_prefix: StringProperty(
        name="Ignore prefix",
        default="vrc.",
        description="Ignore this prefix when comparing shape key names."
                    " This is generally used to prevent merging all 'vrc.' shape keys when you want to merge all"
                    " shape keys that are the same before the first '.'")

    # TODO: If we were to instead put properties on Meshes and Armatures and not their objects, this is how they should be split up
    # Mesh object properties
    # TODO: Might be better if this actually applied all Armature modifiers excluding the first one
    apply_non_armature_modifiers: EnumProperty(
        name="Apply modifiers",
        items=[
            ('APPLY_IF_NO_SHAPES', "Apply if no shape keys", "Apply non-armature modifiers if there are no shape keys on the mesh (other than the Basis)"),
            ('NONE', "None", ""),
            ('APPLY_IF_POSSIBLE', "Apply if possible", "Apply all modifiers if possible, some modifiers can be applied even when a mesh has shape keys"),
            ('APPLY_FORCED', "Apply (forced)", "Apply modifiers, deleting all shape keys if necessary"),
            ('APPLY_KEEP_SHAPES_GRET', "Apply with shapes (gret addon)", "Apply modifiers. Using the gret addon when the mesh has shape keys"),
        ],
        default='APPLY_IF_POSSIBLE',
    )

    # TODO: Extend this to a collection property so that multiple can be kept
    # UV Layer to keep
    keep_only_uv_map: StringProperty(name="UV Map to keep", description="Name of the only UV map to keep on this mesh")

    # Clean up vertex groups that aren't used by the armature
    remove_non_deform_vertex_groups: BoolProperty(
        name="Remove non-deform",
        default=True,
        description="Remove vertex groups that don't have an associated deform bone"
    )

    remove_vertex_colors: BoolProperty(
        name="Remove vertex colors",
        default=True,
        description="Remove all vertex colors"
    )

    # TODO: Extend to being able to re-map materials from one to another
    keep_only_material: StringProperty(
        name="Material to keep",
        description="Name of the only Material to keep on the mesh"
    )

    # materials_remap
    remap_materials: BoolProperty(default=False)
    # materials_remap: CollectionProperty(type=<custom type needed?>)


#############

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



class ObjectBuildSettingsUIList(UIList):
    bl_idname = "object_build_settings"

    def draw_item(self, context: Context, layout: UILayout, data, item, icon, active_data, active_property, index=0,
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
        # Display the prop of the scene settings if it exists, this simplifies renaming
        row.prop(item if is_orphaned else scene_settings[index_in_scene_settings], 'name_prop', text="", emboss=False, icon=row_icon)
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
        # noinspection PyTypeChecker
        space_data: bpy.types.SpaceProperties = context.space_data
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

    def draw(self, context: Context):
        # noinspection PyTypeChecker
        space_data: bpy.types.SpaceProperties = context.space_data
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
                row.operator(ObjectBuildSettingsControl.bl_idname, text="Add to Avatar Builder", icon="ADD").command = 'ADD'
        else:
            list_row = row.row(align=False)
            list_row.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'object_settings', group,'object_settings_active_index', rows=3)
            vertical_buttons_col = row.column(align=True)
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="ADD").command = 'ADD'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="REMOVE").command = 'REMOVE'
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_UP").command = 'UP'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN").command = 'DOWN'

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

            ################
            # General Object
            ################
            object_box = properties_col.box()
            object_box_col = object_box.column()
            object_box_col.label(text="Object", icon="OBJECT_DATA")
            object_box_col.prop(active_object_settings, 'target_object_name')

            if obj.type == 'ARMATURE':
                armature_box = properties_col.box()
                armature_box_col = armature_box.column()
                armature_box_col.label(text="Pose", icon="ARMATURE_DATA")

                export_pose = active_object_settings.armature_export_pose

                armature_box_col.prop(active_object_settings, 'armature_export_pose')

                armature_preserve_volume_col = armature_box_col.column()
                armature_preserve_volume_col.enabled = export_pose != 'REST'
                armature_preserve_volume_col.prop(active_object_settings, 'armature_export_pose_preserve_volume')

                armature_pose_custom_col = armature_box_col.column()
                armature_pose_custom_col.enabled = export_pose.startswith("CUSTOM")
                if export_pose == 'CUSTOM_POSE_LIBRARY' and obj.pose_library:
                    pose_library = obj.pose_library

                    if pose_library:
                        armature_pose_custom_col.prop_search(
                            active_object_settings,
                            'armature_export_pose_library_marker',
                            pose_library,
                            'pose_markers', icon="DOT")
                else:
                    # TODO: elif for `export_pose == 'CUSTOM_ASSET_LIBRARY':`
                    armature_pose_custom_col.enabled = False
                    armature_pose_custom_col.prop(
                        active_object_settings,
                        'armature_export_pose_library_marker', icon="DOT")

            elif obj.type == 'MESH':
                ###############
                # Vertex Groups
                ###############
                if obj.vertex_groups:
                    vertex_groups_box = properties_col.box()

                    vertex_groups_box_col = vertex_groups_box.column()
                    vertex_groups_box_col.label(text="Vertex Groups", icon="GROUP_VERTEX")
                    vertex_groups_box_col.prop(active_object_settings, 'remove_non_deform_vertex_groups')
                    # TODO: Remove empty vertex groups? Probably not very important, since it won't result in much
                    #  extra data, assuming they even get exported at all

                ############
                # Shape keys
                ############
                if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1:
                    shape_keys_box = properties_col.box()
                    shape_keys_box_col = shape_keys_box.column()
                    shape_keys_box_col.label(text="Shape keys", icon="SHAPEKEY_DATA")
                    # ------------------------
                    # delete_col
                    delete_col = shape_keys_box_col.column(align=True)
                    delete_col.prop_search(active_object_settings, 'delete_shape_keys_after', obj.data.shape_keys, 'key_blocks')
                    delete_col.prop_search(active_object_settings, 'delete_shape_keys_before', obj.data.shape_keys, 'key_blocks')

                    shape_keys_box_col.prop(active_object_settings, 'shape_keys_op')

                    # Shape key merge
                    merge_col = shape_keys_box_col.column(align=True)
                    merge_col.enabled = active_object_settings.shape_keys_op == 'MERGE'
                    merge_col.prop(active_object_settings, 'merge_shape_keys')
                    merge_setting = active_object_settings.merge_shape_keys

                    if merge_setting == 'PREFIX':
                        text_label = "Merge Prefix"
                    elif merge_setting == 'SUFFIX':
                        text_label = "Merge Suffix"
                    else:  # merge_setting == 'COMMON_BEFORE_LAST' or merge_setting == 'COMMON_AFTER_FIRST':
                        text_label = "Merge Delimiter"

                    merge_col.alert = merge_col.enabled and not active_object_settings.merge_shape_keys_prefix_suffix
                    merge_col.prop(active_object_settings, 'merge_shape_keys_prefix_suffix', text=text_label)
                    merge_col.alert = False
                    merge_col.prop(active_object_settings, 'merge_shape_keys_pattern')
                    merge_col.prop(active_object_settings, 'merge_shape_keys_ignore_prefix')
                    # ------------------------

                ################
                # Mesh Modifiers
                ################
                mesh_modifiers_box = properties_col.box()
                mesh_modifiers_box_col = mesh_modifiers_box.column(align=True)
                mesh_modifiers_box_col.label(text="Modifiers", icon="MODIFIER_DATA")
                if active_object_settings.apply_non_armature_modifiers == 'APPLY_KEEP_SHAPES_GRET':
                    gret_available = check_gret_shape_key_apply_modifiers()
                    mesh_modifiers_box_col.alert = not gret_available
                    mesh_modifiers_box_col.prop(active_object_settings, 'apply_non_armature_modifiers')

                    if not gret_available:
                        if gret_available is None:
                            mesh_modifiers_box_col.label("Gret addon operator not found")
                        else:
                            mesh_modifiers_box_col.label("Unsupported version of Gret")
                    mesh_modifiers_box_col.alert = False
                else:
                    mesh_modifiers_box_col.prop(active_object_settings, 'apply_non_armature_modifiers')

                ################
                # Mesh UV Layers
                ################
                if obj.data.uv_layers:
                    uv_layers_box = properties_col.box()
                    uv_layers_box_col = uv_layers_box.column()
                    uv_layers_box_col.label(text="UV Layers", icon="GROUP_UVS")
                    uv_layers_box_col.prop_search(active_object_settings, 'keep_only_uv_map', obj.data, 'uv_layers', icon="GROUP_UVS")

                ################
                # Mesh Materials
                ################
                if obj.data.materials:
                    materials_box = properties_col.box()
                    materials_box_col = materials_box.column()
                    materials_box_col.label(text="Materials", icon="MATERIAL_DATA")
                    materials_box_col.prop_search(active_object_settings, 'keep_only_material', obj.data, 'materials')

            # all_icons = ['NONE', 'QUESTION', 'ERROR', 'CANCEL', 'TRIA_RIGHT', 'TRIA_DOWN', 'TRIA_LEFT', 'TRIA_UP', 'ARROW_LEFTRIGHT', 'PLUS', 'DISCLOSURE_TRI_RIGHT', 'DISCLOSURE_TRI_DOWN', 'RADIOBUT_OFF', 'RADIOBUT_ON', 'MENU_PANEL', 'BLENDER', 'GRIP', 'DOT', 'COLLAPSEMENU', 'X', 'DUPLICATE', 'TRASH', 'COLLECTION_NEW', 'OPTIONS', 'NODE', 'NODE_SEL', 'WINDOW', 'WORKSPACE', 'RIGHTARROW_THIN', 'BORDERMOVE', 'VIEWZOOM', 'ADD', 'REMOVE', 'PANEL_CLOSE', 'COPY_ID', 'EYEDROPPER', 'CHECKMARK', 'AUTO', 'CHECKBOX_DEHLT', 'CHECKBOX_HLT', 'UNLOCKED', 'LOCKED', 'UNPINNED', 'PINNED', 'SCREEN_BACK', 'RIGHTARROW', 'DOWNARROW_HLT', 'FCURVE_SNAPSHOT', 'OBJECT_HIDDEN', 'TOPBAR', 'STATUSBAR', 'PLUGIN', 'HELP', 'GHOST_ENABLED', 'COLOR', 'UNLINKED', 'LINKED', 'HAND', 'ZOOM_ALL', 'ZOOM_SELECTED', 'ZOOM_PREVIOUS', 'ZOOM_IN', 'ZOOM_OUT', 'DRIVER_DISTANCE', 'DRIVER_ROTATIONAL_DIFFERENCE', 'DRIVER_TRANSFORM', 'FREEZE', 'STYLUS_PRESSURE', 'GHOST_DISABLED', 'FILE_NEW', 'FILE_TICK', 'QUIT', 'URL', 'RECOVER_LAST', 'THREE_DOTS', 'FULLSCREEN_ENTER', 'FULLSCREEN_EXIT', 'BRUSHES_ALL', 'LIGHT', 'MATERIAL', 'TEXTURE', 'ANIM', 'WORLD', 'SCENE', 'OUTPUT', 'SCRIPT', 'PARTICLES', 'PHYSICS', 'SPEAKER', 'TOOL_SETTINGS', 'SHADERFX', 'MODIFIER', 'BLANK1', 'FAKE_USER_OFF', 'FAKE_USER_ON', 'VIEW3D', 'GRAPH', 'OUTLINER', 'PROPERTIES', 'FILEBROWSER', 'IMAGE', 'INFO', 'SEQUENCE', 'TEXT', 'SPREADSHEET', 'SOUND', 'ACTION', 'NLA', 'PREFERENCES', 'TIME', 'NODETREE', 'CONSOLE', 'TRACKER', 'ASSET_MANAGER', 'NODE_COMPOSITING', 'NODE_TEXTURE', 'NODE_MATERIAL', 'UV', 'OBJECT_DATAMODE', 'EDITMODE_HLT', 'UV_DATA', 'VPAINT_HLT', 'TPAINT_HLT', 'WPAINT_HLT', 'SCULPTMODE_HLT', 'POSE_HLT', 'PARTICLEMODE', 'TRACKING', 'TRACKING_BACKWARDS', 'TRACKING_FORWARDS', 'TRACKING_BACKWARDS_SINGLE', 'TRACKING_FORWARDS_SINGLE', 'TRACKING_CLEAR_BACKWARDS', 'TRACKING_CLEAR_FORWARDS', 'TRACKING_REFINE_BACKWARDS', 'TRACKING_REFINE_FORWARDS', 'SCENE_DATA', 'RENDERLAYERS', 'WORLD_DATA', 'OBJECT_DATA', 'MESH_DATA', 'CURVE_DATA', 'META_DATA', 'LATTICE_DATA', 'LIGHT_DATA', 'MATERIAL_DATA', 'TEXTURE_DATA', 'ANIM_DATA', 'CAMERA_DATA', 'PARTICLE_DATA', 'LIBRARY_DATA_DIRECT', 'GROUP', 'ARMATURE_DATA', 'COMMUNITY', 'BONE_DATA', 'CONSTRAINT', 'SHAPEKEY_DATA', 'CONSTRAINT_BONE', 'CAMERA_STEREO', 'PACKAGE', 'UGLYPACKAGE', 'EXPERIMENTAL', 'BRUSH_DATA', 'IMAGE_DATA', 'FILE', 'FCURVE', 'FONT_DATA', 'RENDER_RESULT', 'SURFACE_DATA', 'EMPTY_DATA', 'PRESET', 'RENDER_ANIMATION', 'RENDER_STILL', 'LIBRARY_DATA_BROKEN', 'BOIDS', 'STRANDS', 'GREASEPENCIL', 'LINE_DATA', 'LIBRARY_DATA_OVERRIDE', 'GROUP_BONE', 'GROUP_VERTEX', 'GROUP_VCOL', 'GROUP_UVS', 'FACE_MAPS', 'RNA', 'RNA_ADD', 'MOUSE_LMB', 'MOUSE_MMB', 'MOUSE_RMB', 'MOUSE_MOVE', 'MOUSE_LMB_DRAG', 'MOUSE_MMB_DRAG', 'MOUSE_RMB_DRAG', 'MEMORY', 'PRESET_NEW', 'DECORATE', 'DECORATE_KEYFRAME', 'DECORATE_ANIMATE', 'DECORATE_DRIVER', 'DECORATE_LINKED', 'DECORATE_LIBRARY_OVERRIDE', 'DECORATE_UNLOCKED', 'DECORATE_LOCKED', 'DECORATE_OVERRIDE', 'FUND', 'TRACKER_DATA', 'HEART', 'ORPHAN_DATA', 'USER', 'SYSTEM', 'SETTINGS', 'OUTLINER_OB_EMPTY', 'OUTLINER_OB_MESH', 'OUTLINER_OB_CURVE', 'OUTLINER_OB_LATTICE', 'OUTLINER_OB_META', 'OUTLINER_OB_LIGHT', 'OUTLINER_OB_CAMERA', 'OUTLINER_OB_ARMATURE', 'OUTLINER_OB_FONT', 'OUTLINER_OB_SURFACE', 'OUTLINER_OB_SPEAKER', 'OUTLINER_OB_FORCE_FIELD', 'OUTLINER_OB_GROUP_INSTANCE', 'OUTLINER_OB_GREASEPENCIL', 'OUTLINER_OB_LIGHTPROBE', 'OUTLINER_OB_IMAGE', 'OUTLINER_COLLECTION', 'RESTRICT_COLOR_OFF', 'RESTRICT_COLOR_ON', 'HIDE_ON', 'HIDE_OFF', 'RESTRICT_SELECT_ON', 'RESTRICT_SELECT_OFF', 'RESTRICT_RENDER_ON', 'RESTRICT_RENDER_OFF', 'RESTRICT_INSTANCED_OFF', 'OUTLINER_DATA_EMPTY', 'OUTLINER_DATA_MESH', 'OUTLINER_DATA_CURVE', 'OUTLINER_DATA_LATTICE', 'OUTLINER_DATA_META', 'OUTLINER_DATA_LIGHT', 'OUTLINER_DATA_CAMERA', 'OUTLINER_DATA_ARMATURE', 'OUTLINER_DATA_FONT', 'OUTLINER_DATA_SURFACE', 'OUTLINER_DATA_SPEAKER', 'OUTLINER_DATA_LIGHTPROBE', 'OUTLINER_DATA_GP_LAYER', 'OUTLINER_DATA_GREASEPENCIL', 'GP_SELECT_POINTS', 'GP_SELECT_STROKES', 'GP_MULTIFRAME_EDITING', 'GP_ONLY_SELECTED', 'GP_SELECT_BETWEEN_STROKES', 'MODIFIER_OFF', 'MODIFIER_ON', 'ONIONSKIN_OFF', 'ONIONSKIN_ON', 'RESTRICT_VIEW_ON', 'RESTRICT_VIEW_OFF', 'RESTRICT_INSTANCED_ON', 'MESH_PLANE', 'MESH_CUBE', 'MESH_CIRCLE', 'MESH_UVSPHERE', 'MESH_ICOSPHERE', 'MESH_GRID', 'MESH_MONKEY', 'MESH_CYLINDER', 'MESH_TORUS', 'MESH_CONE', 'MESH_CAPSULE', 'EMPTY_SINGLE_ARROW', 'LIGHT_POINT', 'LIGHT_SUN', 'LIGHT_SPOT', 'LIGHT_HEMI', 'LIGHT_AREA', 'CUBE', 'SPHERE', 'CONE', 'META_PLANE', 'META_CUBE', 'META_BALL', 'META_ELLIPSOID', 'META_CAPSULE', 'SURFACE_NCURVE', 'SURFACE_NCIRCLE', 'SURFACE_NSURFACE', 'SURFACE_NCYLINDER', 'SURFACE_NSPHERE', 'SURFACE_NTORUS', 'EMPTY_AXIS', 'STROKE', 'EMPTY_ARROWS', 'CURVE_BEZCURVE', 'CURVE_BEZCIRCLE', 'CURVE_NCURVE', 'CURVE_NCIRCLE', 'CURVE_PATH', 'LIGHTPROBE_CUBEMAP', 'LIGHTPROBE_PLANAR', 'LIGHTPROBE_GRID', 'COLOR_RED', 'COLOR_GREEN', 'COLOR_BLUE', 'TRIA_RIGHT_BAR', 'TRIA_DOWN_BAR', 'TRIA_LEFT_BAR', 'TRIA_UP_BAR', 'FORCE_FORCE', 'FORCE_WIND', 'FORCE_VORTEX', 'FORCE_MAGNETIC', 'FORCE_HARMONIC', 'FORCE_CHARGE', 'FORCE_LENNARDJONES', 'FORCE_TEXTURE', 'FORCE_CURVE', 'FORCE_BOID', 'FORCE_TURBULENCE', 'FORCE_DRAG', 'FORCE_FLUIDFLOW', 'RIGID_BODY', 'RIGID_BODY_CONSTRAINT', 'IMAGE_PLANE', 'IMAGE_BACKGROUND', 'IMAGE_REFERENCE', 'NODE_INSERT_ON', 'NODE_INSERT_OFF', 'NODE_TOP', 'NODE_SIDE', 'NODE_CORNER', 'ANCHOR_TOP', 'ANCHOR_BOTTOM', 'ANCHOR_LEFT', 'ANCHOR_RIGHT', 'ANCHOR_CENTER', 'SELECT_SET', 'SELECT_EXTEND', 'SELECT_SUBTRACT', 'SELECT_INTERSECT', 'SELECT_DIFFERENCE', 'ALIGN_LEFT', 'ALIGN_CENTER', 'ALIGN_RIGHT', 'ALIGN_JUSTIFY', 'ALIGN_FLUSH', 'ALIGN_TOP', 'ALIGN_MIDDLE', 'ALIGN_BOTTOM', 'BOLD', 'ITALIC', 'UNDERLINE', 'SMALL_CAPS', 'CON_ACTION', 'MOD_LENGTH', 'MOD_DASH', 'MOD_LINEART', 'HOLDOUT_OFF', 'HOLDOUT_ON', 'INDIRECT_ONLY_OFF', 'INDIRECT_ONLY_ON', 'CON_CAMERASOLVER', 'CON_FOLLOWTRACK', 'CON_OBJECTSOLVER', 'CON_LOCLIKE', 'CON_ROTLIKE', 'CON_SIZELIKE', 'CON_TRANSLIKE', 'CON_DISTLIMIT', 'CON_LOCLIMIT', 'CON_ROTLIMIT', 'CON_SIZELIMIT', 'CON_SAMEVOL', 'CON_TRANSFORM', 'CON_TRANSFORM_CACHE', 'CON_CLAMPTO', 'CON_KINEMATIC', 'CON_LOCKTRACK', 'CON_SPLINEIK', 'CON_STRETCHTO', 'CON_TRACKTO', 'CON_ARMATURE', 'CON_CHILDOF', 'CON_FLOOR', 'CON_FOLLOWPATH', 'CON_PIVOT', 'CON_SHRINKWRAP', 'MODIFIER_DATA', 'MOD_WAVE', 'MOD_BUILD', 'MOD_DECIM', 'MOD_MIRROR', 'MOD_SOFT', 'MOD_SUBSURF', 'HOOK', 'MOD_PHYSICS', 'MOD_PARTICLES', 'MOD_BOOLEAN', 'MOD_EDGESPLIT', 'MOD_ARRAY', 'MOD_UVPROJECT', 'MOD_DISPLACE', 'MOD_CURVE', 'MOD_LATTICE', 'MOD_TINT', 'MOD_ARMATURE', 'MOD_SHRINKWRAP', 'MOD_CAST', 'MOD_MESHDEFORM', 'MOD_BEVEL', 'MOD_SMOOTH', 'MOD_SIMPLEDEFORM', 'MOD_MASK', 'MOD_CLOTH', 'MOD_EXPLODE', 'MOD_FLUIDSIM', 'MOD_MULTIRES', 'MOD_FLUID', 'MOD_SOLIDIFY', 'MOD_SCREW', 'MOD_VERTEX_WEIGHT', 'MOD_DYNAMICPAINT', 'MOD_REMESH', 'MOD_OCEAN', 'MOD_WARP', 'MOD_SKIN', 'MOD_TRIANGULATE', 'MOD_WIREFRAME', 'MOD_DATA_TRANSFER', 'MOD_NORMALEDIT', 'MOD_PARTICLE_INSTANCE', 'MOD_HUE_SATURATION', 'MOD_NOISE', 'MOD_OFFSET', 'MOD_SIMPLIFY', 'MOD_THICKNESS', 'MOD_INSTANCE', 'MOD_TIME', 'MOD_OPACITY', 'REC', 'PLAY', 'FF', 'REW', 'PAUSE', 'PREV_KEYFRAME', 'NEXT_KEYFRAME', 'PLAY_SOUND', 'PLAY_REVERSE', 'PREVIEW_RANGE', 'ACTION_TWEAK', 'PMARKER_ACT', 'PMARKER_SEL', 'PMARKER', 'MARKER_HLT', 'MARKER', 'KEYFRAME_HLT', 'KEYFRAME', 'KEYINGSET', 'KEY_DEHLT', 'KEY_HLT', 'MUTE_IPO_OFF', 'MUTE_IPO_ON', 'DRIVER', 'SOLO_OFF', 'SOLO_ON', 'FRAME_PREV', 'FRAME_NEXT', 'NLA_PUSHDOWN', 'IPO_CONSTANT', 'IPO_LINEAR', 'IPO_BEZIER', 'IPO_SINE', 'IPO_QUAD', 'IPO_CUBIC', 'IPO_QUART', 'IPO_QUINT', 'IPO_EXPO', 'IPO_CIRC', 'IPO_BOUNCE', 'IPO_ELASTIC', 'IPO_BACK', 'IPO_EASE_IN', 'IPO_EASE_OUT', 'IPO_EASE_IN_OUT', 'NORMALIZE_FCURVES', 'VERTEXSEL', 'EDGESEL', 'FACESEL', 'CURSOR', 'PIVOT_BOUNDBOX', 'PIVOT_CURSOR', 'PIVOT_INDIVIDUAL', 'PIVOT_MEDIAN', 'PIVOT_ACTIVE', 'CENTER_ONLY', 'ROOTCURVE', 'SMOOTHCURVE', 'SPHERECURVE', 'INVERSESQUARECURVE', 'SHARPCURVE', 'LINCURVE', 'NOCURVE', 'RNDCURVE', 'PROP_OFF', 'PROP_ON', 'PROP_CON', 'PROP_PROJECTED', 'PARTICLE_POINT', 'PARTICLE_TIP', 'PARTICLE_PATH', 'SNAP_FACE_CENTER', 'SNAP_PERPENDICULAR', 'SNAP_MIDPOINT', 'SNAP_OFF', 'SNAP_ON', 'SNAP_NORMAL', 'SNAP_GRID', 'SNAP_VERTEX', 'SNAP_EDGE', 'SNAP_FACE', 'SNAP_VOLUME', 'SNAP_INCREMENT', 'STICKY_UVS_LOC', 'STICKY_UVS_DISABLE', 'STICKY_UVS_VERT', 'CLIPUV_DEHLT', 'CLIPUV_HLT', 'SNAP_PEEL_OBJECT', 'GRID', 'OBJECT_ORIGIN', 'ORIENTATION_GLOBAL', 'ORIENTATION_GIMBAL', 'ORIENTATION_LOCAL', 'ORIENTATION_NORMAL', 'ORIENTATION_VIEW', 'COPYDOWN', 'PASTEDOWN', 'PASTEFLIPUP', 'PASTEFLIPDOWN', 'VIS_SEL_11', 'VIS_SEL_10', 'VIS_SEL_01', 'VIS_SEL_00', 'AUTOMERGE_OFF', 'AUTOMERGE_ON', 'UV_VERTEXSEL', 'UV_EDGESEL', 'UV_FACESEL', 'UV_ISLANDSEL', 'UV_SYNC_SELECT', 'GP_CAPS_FLAT', 'GP_CAPS_ROUND', 'FIXED_SIZE', 'TRANSFORM_ORIGINS', 'GIZMO', 'ORIENTATION_CURSOR', 'NORMALS_VERTEX', 'NORMALS_FACE', 'NORMALS_VERTEX_FACE', 'SHADING_BBOX', 'SHADING_WIRE', 'SHADING_SOLID', 'SHADING_RENDERED', 'SHADING_TEXTURE', 'OVERLAY', 'XRAY', 'LOCKVIEW_OFF', 'LOCKVIEW_ON', 'AXIS_SIDE', 'AXIS_FRONT', 'AXIS_TOP', 'LAYER_USED', 'LAYER_ACTIVE', 'OUTLINER_OB_CURVES', 'OUTLINER_DATA_CURVES', 'CURVES_DATA', 'OUTLINER_OB_POINTCLOUD', 'OUTLINER_DATA_POINTCLOUD', 'POINTCLOUD_DATA', 'OUTLINER_OB_VOLUME', 'OUTLINER_DATA_VOLUME', 'VOLUME_DATA', 'CURRENT_FILE', 'HOME', 'DOCUMENTS', 'TEMP', 'SORTALPHA', 'SORTBYEXT', 'SORTTIME', 'SORTSIZE', 'SHORTDISPLAY', 'LONGDISPLAY', 'IMGDISPLAY', 'BOOKMARKS', 'FONTPREVIEW', 'FILTER', 'NEWFOLDER', 'FOLDER_REDIRECT', 'FILE_PARENT', 'FILE_REFRESH', 'FILE_FOLDER', 'FILE_BLANK', 'FILE_BLEND', 'FILE_IMAGE', 'FILE_MOVIE', 'FILE_SCRIPT', 'FILE_SOUND', 'FILE_FONT', 'FILE_TEXT', 'SORT_DESC', 'SORT_ASC', 'LINK_BLEND', 'APPEND_BLEND', 'IMPORT', 'EXPORT', 'LOOP_BACK', 'LOOP_FORWARDS', 'BACK', 'FORWARD', 'FILE_ARCHIVE', 'FILE_CACHE', 'FILE_VOLUME', 'FILE_3D', 'FILE_HIDDEN', 'FILE_BACKUP', 'DISK_DRIVE', 'MATPLANE', 'MATSPHERE', 'MATCUBE', 'MONKEY', 'CURVES', 'ALIASED', 'ANTIALIASED', 'MAT_SPHERE_SKY', 'MATSHADERBALL', 'MATCLOTH', 'MATFLUID', 'WORDWRAP_OFF', 'WORDWRAP_ON', 'SYNTAX_OFF', 'SYNTAX_ON', 'LINENUMBERS_OFF', 'LINENUMBERS_ON', 'SCRIPTPLUGINS', 'DISC', 'DESKTOP', 'EXTERNAL_DRIVE', 'NETWORK_DRIVE', 'SEQ_SEQUENCER', 'SEQ_PREVIEW', 'SEQ_LUMA_WAVEFORM', 'SEQ_CHROMA_SCOPE', 'SEQ_HISTOGRAM', 'SEQ_SPLITVIEW', 'SEQ_STRIP_META', 'SEQ_STRIP_DUPLICATE', 'IMAGE_RGB', 'IMAGE_RGB_ALPHA', 'IMAGE_ALPHA', 'IMAGE_ZDEPTH', 'HANDLE_AUTOCLAMPED', 'HANDLE_AUTO', 'HANDLE_ALIGNED', 'HANDLE_VECTOR', 'HANDLE_FREE', 'VIEW_PERSPECTIVE', 'VIEW_ORTHO', 'VIEW_CAMERA', 'VIEW_PAN', 'VIEW_ZOOM', 'BRUSH_BLOB', 'BRUSH_BLUR', 'BRUSH_CLAY', 'BRUSH_CLAY_STRIPS', 'BRUSH_CLONE', 'BRUSH_CREASE', 'BRUSH_FILL', 'BRUSH_FLATTEN', 'BRUSH_GRAB', 'BRUSH_INFLATE', 'BRUSH_LAYER', 'BRUSH_MASK', 'BRUSH_MIX', 'BRUSH_NUDGE', 'BRUSH_PINCH', 'BRUSH_SCRAPE', 'BRUSH_SCULPT_DRAW', 'BRUSH_SMEAR', 'BRUSH_SMOOTH', 'BRUSH_SNAKE_HOOK', 'BRUSH_SOFTEN', 'BRUSH_TEXDRAW', 'BRUSH_TEXFILL', 'BRUSH_TEXMASK', 'BRUSH_THUMB', 'BRUSH_ROTATE', 'GPBRUSH_SMOOTH', 'GPBRUSH_THICKNESS', 'GPBRUSH_STRENGTH', 'GPBRUSH_GRAB', 'GPBRUSH_PUSH', 'GPBRUSH_TWIST', 'GPBRUSH_PINCH', 'GPBRUSH_RANDOMIZE', 'GPBRUSH_CLONE', 'GPBRUSH_WEIGHT', 'GPBRUSH_PENCIL', 'GPBRUSH_PEN', 'GPBRUSH_INK', 'GPBRUSH_INKNOISE', 'GPBRUSH_BLOCK', 'GPBRUSH_MARKER', 'GPBRUSH_FILL', 'GPBRUSH_AIRBRUSH', 'GPBRUSH_CHISEL', 'GPBRUSH_ERASE_SOFT', 'GPBRUSH_ERASE_HARD', 'GPBRUSH_ERASE_STROKE', 'KEYTYPE_KEYFRAME_VEC', 'KEYTYPE_BREAKDOWN_VEC', 'KEYTYPE_EXTREME_VEC', 'KEYTYPE_JITTER_VEC', 'KEYTYPE_MOVING_HOLD_VEC', 'HANDLETYPE_FREE_VEC', 'HANDLETYPE_ALIGNED_VEC', 'HANDLETYPE_VECTOR_VEC', 'HANDLETYPE_AUTO_VEC', 'HANDLETYPE_AUTO_CLAMP_VEC', 'COLORSET_01_VEC', 'COLORSET_02_VEC', 'COLORSET_03_VEC', 'COLORSET_04_VEC', 'COLORSET_05_VEC', 'COLORSET_06_VEC', 'COLORSET_07_VEC', 'COLORSET_08_VEC', 'COLORSET_09_VEC', 'COLORSET_10_VEC', 'COLORSET_11_VEC', 'COLORSET_12_VEC', 'COLORSET_13_VEC', 'COLORSET_14_VEC', 'COLORSET_15_VEC', 'COLORSET_16_VEC', 'COLORSET_17_VEC', 'COLORSET_18_VEC', 'COLORSET_19_VEC', 'COLORSET_20_VEC', 'COLLECTION_COLOR_01', 'COLLECTION_COLOR_02', 'COLLECTION_COLOR_03', 'COLLECTION_COLOR_04', 'COLLECTION_COLOR_05', 'COLLECTION_COLOR_06', 'COLLECTION_COLOR_07', 'COLLECTION_COLOR_08', 'SEQUENCE_COLOR_01', 'SEQUENCE_COLOR_02', 'SEQUENCE_COLOR_03', 'SEQUENCE_COLOR_04', 'SEQUENCE_COLOR_05', 'SEQUENCE_COLOR_06', 'SEQUENCE_COLOR_07', 'SEQUENCE_COLOR_08', 'SEQUENCE_COLOR_09', 'LIBRARY_DATA_INDIRECT', 'LIBRARY_DATA_OVERRIDE_NONEDITABLE', 'EVENT_A', 'EVENT_B', 'EVENT_C', 'EVENT_D', 'EVENT_E', 'EVENT_F', 'EVENT_G', 'EVENT_H', 'EVENT_I', 'EVENT_J', 'EVENT_K', 'EVENT_L', 'EVENT_M', 'EVENT_N', 'EVENT_O', 'EVENT_P', 'EVENT_Q', 'EVENT_R', 'EVENT_S', 'EVENT_T', 'EVENT_U', 'EVENT_V', 'EVENT_W', 'EVENT_X', 'EVENT_Y', 'EVENT_Z', 'EVENT_SHIFT', 'EVENT_CTRL', 'EVENT_ALT', 'EVENT_OS', 'EVENT_F1', 'EVENT_F2', 'EVENT_F3', 'EVENT_F4', 'EVENT_F5', 'EVENT_F6', 'EVENT_F7', 'EVENT_F8', 'EVENT_F9', 'EVENT_F10', 'EVENT_F11', 'EVENT_F12', 'EVENT_ESC', 'EVENT_TAB', 'EVENT_PAGEUP', 'EVENT_PAGEDOWN', 'EVENT_RETURN', 'EVENT_SPACEKEY']
            # for icon in all_icons:
            #     try:
            #         properties_col.label(text=icon, icon=icon)
            #     except:
            #         pass

            if is_synced:
                #final_col = layout.column()
                #properties_col.enabled = True
                final_col = main_column.column(align=True)
                final_col.operator(ObjectBuildSettingsControl.bl_idname, text="Remove from Avatar Builder", icon="TRASH").command = 'REMOVE'


##################


T = TypeVar('T', bound='PropertyGroupSuper')


# Base class used to provide typed access (and checks) to getting groups from ID types
# Ideally we'd make this an abstract baseclass, but Blender doesn't like that for metaclasses
class PropertyGroupBase:

    # Technically, obj can also be a Bone or PoseBone, but we're not using
    @classmethod
    def get_group(cls: Type[T], obj: PropHolderType) -> T:
        group = get_property_group(obj, strict=True)
        if isinstance(group, cls):
            return group
        else:
            raise ValueError(f"Tried to get a {cls} from {obj}, but got a {type(group)}.")


class ScenePropertyGroup(PropertyGroupBase, PropertyGroup):
    attribute_name = 'scene_settings_collection'

    # The main collection and its active index
    build_settings: CollectionProperty(type=SceneBuildSettings)
    build_settings_active_index: IntProperty()

    # Tag export scenes as such so that they and they can be detected more easily for deletion
    is_export_scene: BoolProperty(
        name="Is an export scene",
        description="True only for export scenes created by running the Avatar Builder"
    )
    export_scene_source_scene: StringProperty(
        name="Source Scene name",
        description="Name of the scene this export scene was created from and should swap back to when deleted",
    )

    def get_active(self) -> Union[SceneBuildSettings, None]:
        settings = self.build_settings
        active_index = self.build_settings_active_index
        if settings:
            if 0 <= active_index < len(settings):
                return settings[active_index]
        else:
            return None


class ObjectPropertyGroup(PropertyGroupBase, PropertyGroup):
    attribute_name = 'object_settings_collection'

    object_settings: CollectionProperty(type=ObjectBuildSettings)
    object_settings_active_index: IntProperty()
    sync_active_with_scene: BoolProperty(name="Toggle scene sync", default=True)

    def get_active_settings(self) -> Union[ObjectBuildSettings, None]:
        settings = self.object_settings
        active_index = self.object_settings_active_index
        if settings:
            if 0 <= active_index < len(settings):
                return settings[active_index]
        else:
            return None

    def get_synced_settings(self, scene: Scene) -> Union[ObjectBuildSettings, None]:
        active_build_settings = ScenePropertyGroup.get_group(scene).get_active()
        if active_build_settings and active_build_settings.name in self.object_settings:
            return self.object_settings[active_build_settings.name]
        else:
            return None


def merge_shapes_into_first(mesh_obj: Object, shapes_to_merge: list[tuple[ShapeKey, list[ShapeKey]]]):
    # We only update/remove shapes at the end, to avoid issues when some shapes are relative to other shapes being
    # merged or merged into

    shape_cos_dict = {}

    def get_shape_cos(shape):
        cos = shape_cos_dict.get(shape.name)
        if cos is None:
            cos = np.empty(3 * len(shape.data), dtype=np.single)
            shape.data.foreach_get('co', cos)
            shape_cos_dict[shape.name] = cos
        return cos

    shape_updates = {}
    main_shapes = set()
    shapes_to_delete = set()
    # Check the input
    for main_shape, shape_list in shapes_to_merge:
        # Check that we're not merging any shapes into more than one main shape, as this indicates something has gone
        # wrong
        already_merging = shapes_to_delete.intersection(shape_list)
        if already_merging:
            raise ValueError(f"Shapes are already being merged into another main shape:\n{already_merging}")

        # Check that a main shape isn't included more than once
        if main_shape in main_shapes:
            raise ValueError(f"{main_shape} is already having shapes merged into it. Each main shape must not appear"
                             f" more than once")

        main_shapes.add(main_shape)
        shapes_to_delete.update(shape_list)

    # Check that we're not merging any of the main shapes into another main shape as this indicates something has gone
    # wrong
    # This check could be disabled if there becomes a need for this, but currently there is not
    shapes_both_main_and_merged = shapes_to_delete.intersection(main_shapes)
    if shapes_both_main_and_merged:
        raise ValueError(f"Some shapes are both being merged and having shapes merged into them, this shouldn't be"
                         f" done:\n{shapes_both_main_and_merged}")

    for main_shape, shapes in shapes_to_merge:

        # When all shapes have the same vertex group, we can ignore the vertex group and leave it on the combined shape,
        # otherwise, we must apply the vertex group on each shape and remove the vertex group from the combined shape
        all_shapes_have_same_vertex_group = len({shape.vertex_group for shape in shapes}) == 1
        if not all_shapes_have_same_vertex_group:
            raise ValueError("Not Yet Implemented. Currently, all shape keys must have the same vertex group to be merged.")

        main_shape_cos = get_shape_cos(main_shape)
        for shape in shapes:
            # If the shape is relative to itself, the shape is 'basis-like', meaning it does nothing when activated
            if shape != shape.relative_key:
                main_shape_cos += get_shape_cos(shape) - get_shape_cos(shape.relative_key)
            print(f'merged {shape.name} into {main_shape.name}')

        # Prepare the updated cos for the main shape, to be applied once all updated main shape cos have been
        # calculated
        shape_updates[main_shape] = main_shape_cos

    for shape, shape_cos in shape_updates.items():
        shape.data.foreach_set('co', shape_cos)

    for shape in shapes_to_delete:
        mesh_obj.shape_key_remove(shape)


# def verify_mesh(obj: Object, me: Mesh, settings: ObjectBuildSettings) -> (bool, str):
#     """Verify that a mesh's settings are valid for building"""
#     shape_keys = me.shape_keys
#     if shape_keys:
#         key_blocks = shape_keys.key_blocks
#
#         delete_after_name = settings.delete_shape_keys_after
#         if delete_after_name and not delete_after_name in key_blocks:
#             return False, f"Shape key to delete after '{delete_after_name}' could not be found"
#
#         delete_before_name = settings.delete_shape_keys_before
#         if delete_before_name and not delete_before_name in key_blocks:
#             return False, f"Shape key to delete before '{delete_before_name}' could not be found"

# Want to use Object[Mesh], but will fail in Blender
# Perhaps we can:
# In blender:
# T = TypeVar('T')
# Object = Annotated[Object, T]

def remove_all_uv_layers_except(mesh_obj: Object, *uv_layers: Union[str, MeshUVLoopLayer]):
    mesh_uv_layers = mesh_obj.data.uv_layers
    uv_layer_idx_to_keep = set()
    # print(mesh_obj)
    for uv_layer in uv_layers:
        if isinstance(uv_layer, MeshUVLoopLayer):
            uv_layer = uv_layer.name
        # print(uv_layer)
        uv_layer_index = mesh_uv_layers.find(uv_layer)
        uv_layer_idx_to_keep.add(uv_layer_index)
    uv_layers_to_remove = [mesh_uv_layers[i].name for i in range(len(mesh_uv_layers)) if i not in uv_layer_idx_to_keep]
    # print(uv_layers_to_remove)
    for uv_layer in uv_layers_to_remove:
        # print(f'Removing {uv_layer}')
        mesh_uv_layers.remove(mesh_uv_layers[uv_layer])


# All modifier types that are eModifierTypeType_NonGeometrical
# Only these can be applied to meshes with shape keys
# We should also be able to easily apply any modifiers which are BKE_modifier_is_same_topology too
# Modifiers that are geometrical, but same topology are the ones that can be applied as shape keys
_modifiers_eModifierTypeType_NonGeometrical = {
    'DATA_TRANSFER',
    'UV_PROJECT',
    'UV_WARP',
    'VOLUME_DISPLACE',  # Isn't available for meshes
    'VERTEX_WEIGHT_EDIT',
    'VERTEX_WEIGHT_MIX',
    'VERTEX_WEIGHT_PROXIMITY',
}


# TODO: Break up the larger parts of this function into separate functions
# Needs to be down here for the type hints to work
def build_mesh(original_scene: Scene, obj: Object, me: Mesh, settings: ObjectBuildSettings):
    # Shape keys first, then modifiers
    shape_keys = me.shape_keys
    if shape_keys:
        key_blocks = shape_keys.key_blocks
        shape_keys_op = settings.shape_keys_op

        if shape_keys_op == 'DELETE_ALL':
            # Avoid reference key and vertices desync by setting vertices co to reference key co
            reference_key_co = np.empty(3 * len(me.vertices), dtype=np.single)
            shape_keys.reference_key.data.foreach_get('co', reference_key_co)
            me.vertices.foreach_set('co', reference_key_co)
            # Remove all shape keys
            obj.shape_key_clear()
            del reference_key_co
        else:
            # Delete shape keys before/after the specified keys (excluding the reference key)
            keys_to_delete = set()
            delete_after_name = settings.delete_shape_keys_after
            if delete_after_name:
                delete_after_index = key_blocks.find(delete_after_name)
                if delete_after_index != -1:
                    keys_to_delete = set(key_blocks[delete_after_index + 1:])
                else:
                    raise KeyError(f"Shape key to delete after '{delete_after_name}' could not be found on Object"
                                   f" '{obj.name}'")

            delete_before_name = settings.delete_shape_keys_before
            if delete_before_name:
                delete_before_index = key_blocks.find(delete_before_name)
                if delete_before_index != -1:
                    # Start from 1 to avoid including the reference key
                    found_keys = set(key_blocks[1:delete_before_index])
                    if delete_after_name:
                        # Only shape keys that satisfy both conditions
                        keys_to_delete.intersection_update(found_keys)
                    else:
                        keys_to_delete = found_keys
                else:
                    raise KeyError(f"Shape key to delete before '{delete_before_name}' could not be found on Object"
                                   f" '{obj.name}'")

            for key_name in keys_to_delete:
                obj.shape_key_remove(key_name)

            if shape_keys_op == 'APPLY_MIX':
                # Delete all remaining shape keys, setting the mesh vertices to the current mix of all shape keys
                # Add a shape key that is the mix of all shapes at their current values
                mix_shape = obj.shape_key_add(from_mix=True)
                mix_shape_co = np.empty(3 * len(me.vertices), dtype=np.single)
                # Get the co for the mixed shape
                mix_shape.data.foreach_get('co', mix_shape_co)
                # Remove all the shapes
                obj.shape_key_clear()
                # Set the vertices to the mixed shape co
                me.vertices.foreach_set('co', mix_shape_co)
                del mix_shape_co
            elif shape_keys_op == 'MERGE':
                merge_pattern = settings.merge_shape_keys
                merge_grouping = settings.merge_shape_keys_pattern
                merge_prefix_suffix_delim = settings.merge_shape_keys_prefix_suffix
                merge_ignore_prefix = settings.merge_shape_keys_ignore_prefix

                # Merge shape keys based on their names
                # Only one of these structures will be used based on which options were picked
                # A list of shapes, all elements will be merged into one shape
                matched = []
                # A dictionary of 'common prefix/suffix' to list of shapes with that prefix/suffix
                # Each list will be merged into one shape
                matched_grouped = defaultdict(list)
                # A list of lists of shapes
                # Each list will be merged into one shape
                matched_consecutive = []

                # Skip the reference shape
                key_blocks_to_search = key_blocks[1:]
                if merge_ignore_prefix:
                    # Skip any that begin with the specific prefix we're ignoring
                    key_blocks_to_search = (shape for shape in key_blocks_to_search if not shape.name.startswith(merge_ignore_prefix))

                if merge_grouping == 'ALL':
                    if merge_pattern == 'PREFIX':
                        matched = [shape for shape in key_blocks_to_search if shape.name.startswith(merge_prefix_suffix_delim)]
                    elif merge_pattern == 'SUFFIX':
                        matched = [shape for shape in key_blocks_to_search if shape.name.endswith(merge_prefix_suffix_delim)]
                    elif merge_pattern == 'COMMON_BEFORE_LAST':
                        for shape in key_blocks_to_search:
                            name = shape.name
                            index = name.rfind(merge_prefix_suffix_delim)
                            if index != -1:
                                common_part_before_delimiter = name[:index]
                            else:
                                # If the delimiter isn't found we use the entire name, this allows for "MyShape" to
                                # combine with "MyShape_adjustments" when the delimiter is "_", for example.
                                common_part_before_delimiter = name
                            matched_grouped[common_part_before_delimiter].append(shape)
                    elif merge_pattern == 'COMMON_AFTER_FIRST':
                        # TODO: Reduce duplicate code shared with COMMON_BEFORE_LAST
                        for shape in key_blocks_to_search:
                            name = shape.name
                            index = name.find(merge_prefix_suffix_delim)
                            if index != -1:
                                common_part_after_delimiter = name[index+1:]
                            else:
                                # If the delimiter isn't found we use the entire name, this allows for "MyShape" to
                                # combine with "adjust.MyShape" when the delimiter is "_", for example.
                                common_part_after_delimiter = name
                            matched_grouped[common_part_after_delimiter].append(shape)
                elif merge_grouping == 'CONSECUTIVE':
                    # similar to 'ALL', but check against the previous
                    if merge_pattern == 'PREFIX':
                        previous_shape_matched = False
                        current_merge_list = None
                        for shape in key_blocks_to_search:
                            current_shape_matches = shape.name.startswith(merge_prefix_suffix_delim)
                            if current_shape_matches:
                                if not previous_shape_matched:
                                    # Create a new merge list
                                    current_merge_list = []
                                    matched_consecutive.append(current_merge_list)
                                # Add to the current merge list
                                current_merge_list.append(shape)
                            # Update for the next shape in the list
                            previous_shape_matched = current_shape_matches
                    elif merge_pattern == 'SUFFIX':
                        # TODO: Remove the duplicate code shared with PREFIX
                        previous_shape_matched = False
                        current_merge_list = None
                        for shape in key_blocks_to_search:
                            current_shape_matches = shape.name.endswith(merge_prefix_suffix_delim)
                            if current_shape_matches:
                                if not previous_shape_matched:
                                    # Create a new merge list
                                    current_merge_list = []
                                    matched_consecutive.append(current_merge_list)
                                # Add to the current merge list
                                current_merge_list.append(shape)
                            # Update for the next shape in the list
                            previous_shape_matched = current_shape_matches
                    elif merge_pattern == 'COMMON_BEFORE_LAST':
                        previous_common_part = None
                        current_merge_list = None
                        for shape in key_blocks_to_search:
                            name = shape.name
                            index = name.rfind(merge_prefix_suffix_delim)
                            if index != -1:
                                common_part_before_delimiter = name[:index]
                            else:
                                # If the delimiter isn't found we use the entire name, this allows for "MyShape" to
                                # combine with "MyShape_adjustments" when the delimiter is "_", for example.
                                common_part_before_delimiter = name
                            if common_part_before_delimiter != previous_common_part:
                                # Create a new merge list
                                current_merge_list = []
                                matched_consecutive.append(current_merge_list)
                            # Add to the current merge list
                            current_merge_list.append(shape)
                    elif merge_pattern == 'COMMON_AFTER_FIRST':
                        # TODO: Reduce common code shared with COMMON_BEFORE_LAST
                        previous_common_part = None
                        current_merge_list = None
                        for shape in key_blocks_to_search:
                            name = shape.name
                            index = name.find(merge_prefix_suffix_delim)
                            if index != -1:
                                common_part_after_delimiter = name[index+1:]
                            else:
                                # If the delimiter isn't found we use the entire name, this allows for "MyShape" to
                                # combine with "MyShape_adjustments" when the delimiter is "_", for example.
                                common_part_after_delimiter = name
                            if common_part_after_delimiter != previous_common_part:
                                # Create a new merge list
                                current_merge_list = []
                                matched_consecutive.append(current_merge_list)
                            # Add to the current merge list
                            current_merge_list.append(shape)
                # Collect all the shapes to be merged into a common dictionary format that the merge function uses
                # The first shape in each list will be picked as the shape that the other shapes in the list should be
                # merged into
                # We will skip any lists that don't have more than one element since merging only happens with two or
                # more shapes
                merge_lists = []

                # Only one of the 3 different data structures we declared will actually be used, but we'll check all
                # three for simplicity
                if len(matched) > 1:
                    merge_lists.append((matched[0], matched[1:]))
                for shapes_to_merge in matched_grouped.values():
                    if len(shapes_to_merge) > 1:
                        merge_lists.append((shapes_to_merge[0], shapes_to_merge[1:]))
                for shapes_to_merge in matched_consecutive:
                    if len(shapes_to_merge) > 1:
                        merge_lists.append((shapes_to_merge[0], shapes_to_merge[1:]))

                # Merge all the specified shapes
                merge_shapes_into_first(obj, merge_lists)

            # If there is only the reference shape key left, remove it
            # This will allow for most modifiers to be applied, compared to when there is just the reference key
            if len(key_blocks) == 1:
                # Copy reference key co to the vertices to avoid desync between the vertices and reference key
                reference_key_co = np.empty(3 * len(me.vertices), dtype=np.single)
                shape_keys.reference_key.data.foreach_get('co', reference_key_co)
                me.vertices.foreach_set('co', reference_key_co)
                # Remove all shape keys
                obj.shape_key_clear()
                del reference_key_co

    # Update shape keys reference in-case it has changed (happens when removing all shape keys)
    shape_keys = me.shape_keys

    # Apply modifiers
    apply_modifiers = settings.apply_non_armature_modifiers
    if apply_modifiers != 'NONE' and not (apply_modifiers == 'APPLY_IF_NO_SHAPES' and shape_keys):
        # Note: deprecated in newer blender
        context_override = {'object': obj}

        # All
        mod_name_and_applicable_with_shapes = []
        # Track whether all the modifiers can be applied with shape keys
        can_apply_all_with_shapes = True
        # Look through all the modifiers
        for mod in obj.modifiers:
            if mod.type != 'ARMATURE' and mod.show_viewport:
                can_apply_with_shapes = mod.type in _modifiers_eModifierTypeType_NonGeometrical
                can_apply_all_with_shapes &= can_apply_with_shapes
                mod_name_and_applicable_with_shapes.append((mod.name, can_apply_with_shapes))

        if shape_keys and not can_apply_all_with_shapes:
            if apply_modifiers == 'APPLY_FORCED':
                # Sync vertices to reference key
                reference_key_co = np.empty(3 * len(me.vertices), dtype=np.single)
                me.shape_keys.reference_key.data.foreach_get('co', reference_key_co)
                me.vertices.foreach_set('co', reference_key_co)
                # Delete all shape keys
                obj.shape_key_clear()
            elif apply_modifiers == 'APPLY_IF_POSSIBLE':
                # Create a filter to remove all those which can't be applied
                mod_name_and_applicable_with_shapes = filter(lambda t: t[1], mod_name_and_applicable_with_shapes)

        # For data transfer modifiers to work (and possibly some other modifiers), we must temporarily add the copied
        # object to the original (and active) scene
        original_scene.collection.objects.link(obj)
        # Again for data transfer modifiers to work, the active shape key has to be set to the reference key because,
        # for some reason. This isn't normal behaviour of applying th modifier gets applied almost as if the active shape key has a value of 1.0, despite the
        # fact this is not the normal behaviour in any way. I honestly don't know why this happens
        orig_active_shape_key_index = obj.active_shape_key_index
        obj.active_shape_key_index = 0
        # gret might also be turning this off, we'll follow suit
        orig_show_only_shape_key = obj.show_only_shape_key
        obj.show_only_shape_key = False
        try:
            if apply_modifiers == 'APPLY_KEEP_SHAPES_GRET':
                print("Applying modifiers with Gret")
                result = run_gret_shape_key_apply_modifiers(obj, {mod_name for mod_name, _ in mod_name_and_applicable_with_shapes})
                if 'FINISHED' not in result:
                    raise RuntimeError(f"Applying modifiers with gret failed for"
                                       f" {[mod_name for mod_name, _ in mod_name_and_applicable_with_shapes]} on"
                                       f" {repr(obj)}")
                print("Applied modifiers with Gret")
            else:
                for mod_name, _ in mod_name_and_applicable_with_shapes:
                    print(f"Applying modifier {mod_name} to {repr(obj)}")
                    if 'FINISHED' not in bpy.ops.object.modifier_apply(context_override, modifier=mod_name):
                        raise RuntimeError(f"bpy.ops.object.modifier_apply failed for {mod_name} on {repr(obj)}")
        finally:
            obj.show_only_shape_key = orig_show_only_shape_key
            obj.active_shape_key_index = orig_active_shape_key_index
            # Unlink from the collection again
            original_scene.collection.objects.unlink(obj)

    # Remove other uv maps
    if settings.keep_only_uv_map:
        remove_all_uv_layers_except(obj, settings.keep_only_uv_map)

    # Remove non-deform vertex groups
    # Must be done after applying modifiers, as modifiers may use vertex groups to affect their behaviour
    if settings.remove_non_deform_vertex_groups:
        # TODO: Not sure how FBX and unity handle multiple armatures
        deform_bones_names = set()
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.use_vertex_groups:
                if mod.object:
                    armature = mod.object.data
                    for bone in armature.bones:
                        if bone.use_deform:
                            deform_bones_names.add(bone.name)
        for vg in obj.vertex_groups:
            if vg.name not in deform_bones_names:
                obj.vertex_groups.remove(vg)

    # Remove vertex colors
    if settings.remove_vertex_colors:
        # TODO: Support for newer vertex colors via mesh attributes or whatever they're called
        for vc in me.vertex_colors:
            me.vertex_colors.remove(vc)

    # Remove all but one material
    if settings.keep_only_material:
        only_material_name = settings.keep_only_material
        materials = me.materials
        if only_material_name not in materials:
            raise ValueError(f"Could not find '{only_material_name}' in {repr(materials)}")
        # Iterate in reverse so that indices remain the same for materials we're yet to check
        for idx in reversed(range(len(materials))):
            material = materials[idx]
            if material.name != only_material_name:
                materials.pop(index=idx)

    # TODO: Remap materials
    pass

    # This could be done just prior to joining meshes together, but I think it's ok to do here
    # There probably shouldn't be an option to turn this off
    # Set custom split normals (so that the current normals are kept when joining other meshes)
    # TODO: We might need to do something when use_auto_smooth is False
    bpy.ops.mesh.customdata_custom_splitnormals_add({'mesh': me})

    # TODO: Add option to apply all transforms
    # bpy.ops.object.transform_apply({'selected_editable_objects': [obj]}, location=True, rotation=True, scale=True)
    pass


def build_armature(obj: Object, armature: Armature, settings: ObjectBuildSettings, copy_objects: set[Object]):
    export_pose = settings.armature_export_pose
    if export_pose == "REST":
        armature.pose_position = 'REST'
    else:
        armature.pose_position = 'POSE'
        if export_pose == 'POSE':
            pass
        elif export_pose == 'CUSTOM_ASSET_LIBRARY':
            raise NotImplementedError()
        elif export_pose == ' CUSTOM_POSE_LIBRARY':
            raise NotImplementedError()

    preserve_volume_setting = settings.armature_export_pose_preserve_volume

    preserve_volume = None
    if preserve_volume_setting == 'YES':
        preserve_volume = True
    elif preserve_volume_setting == 'NO':
        preserve_volume = False

    if preserve_volume is not None:
        # Iterate through all the copy objects, setting preserve_volume on all armature modifiers that use this
        # armature
        for copy_object in copy_objects:
            mod: Modifier
            for mod in copy_object.modifiers:
                if isinstance(mod, ArmatureModifier) and mod.object == obj:
                    mod.use_deform_preserve_volume = True

    # TODO: Add option to apply all transforms
    # bpy.ops.object.transform_apply({'selected_editable_objects': [obj]}, location=True, rotation=True, scale=True)


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
            if obj.type == 'MESH':
                shape_keys = obj.data.shape_keys
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


def check_gret_shape_key_apply_modifiers():
    """Returns a truthy value when valid.
     Returns None when not detected.
     Returns False when detected, but the version could not be determined."""
    if hasattr(bpy.ops, 'gret') and hasattr(bpy.ops.gret, 'shape_key_apply_modifiers'):
        operator = bpy.ops.gret.shape_key_apply_modifiers
        for prop in operator.get_rna_type().properties:
            identifier = prop.identifier
            if identifier == 'modifier_mask':
                # Not yet implemented
                # return identifier
                return False
            elif identifier == 'keep_modifiers':
                return identifier
        return False
    return None


def run_gret_shape_key_apply_modifiers(obj: Object, modifier_names_to_apply: set[str]):
    gret_check = check_gret_shape_key_apply_modifiers()
    if gret_check == 'keep_modifiers':
        # Older version, applies all non-disabled modifiers and modifiers not in our list
        # Temporarily disable all other modifiers, run the operator and then restore the modifiers that were temporarily
        # disabled
        mods_to_enable = []
        mod: Modifier
        try:
            for mod in obj.modifiers:
                if mod.name in modifier_names_to_apply:
                    # Normally we're only applying enabled modifiers, but this should make the code more robust
                    mod.show_viewport = True
                elif mod.show_viewport:
                    # Record that this modifier needs to be re-enabled
                    mods_to_enable.append(mod.name)
                    # Disable the modifier so that it doesn't get applied
                    mod.show_viewport = False
            # Apply all non-disabled modifiers
            return bpy.ops.gret.shape_key_apply_modifiers({'object': obj})
        finally:
            # Restore modifiers that were temporarily disabled
            modifiers = obj.modifiers
            # The operator isn't our code, so don't assume that all the modifiers we expect to still exist actually do
            expected_modifier_not_found = []
            for mod_name in mods_to_enable:
                mod = modifiers.get(mod_name)
                if mod:
                    mod.show_viewport = True
                else:
                    expected_modifier_not_found.append(mod_name)
    elif gret_check == 'modifier_mask':
        # Newer version, only supports up to 32 modifiers, uses a mask to decide which modifiers to apply
        raise RuntimeError("Noy yet implemented")
    else:
        raise RuntimeError("Gret addon not found or version incompatible")


# TODO: Rename this function to be shorter
def set_build_name_for_existing_object_about_to_be_renamed(name: str):
    existing_object: Object = bpy.data.objects.get(name)
    if existing_object:
        existing_object_group = ObjectPropertyGroup.get_group(existing_object)
        existing_object_settings = existing_object_group.object_settings
        # Iterate through all the build settings on this object, if they don't have a target object name set, then they
        # would have been using the object's name instead. Since the object's name is about to be changed, the target
        # object name must be set in order for build behaviour to remain the same.
        object_build_settings: ObjectBuildSettings
        for object_build_settings in existing_object_settings:
            if not object_build_settings.target_object_name:
                object_build_settings.target_object_name = name


class BuildAvatarOp(Operator):
    bl_idname = "build_avatar"
    bl_label = "Build Avatar"
    bl_description = "Build an avatar based on the meshes in the current scene, creating a new scene with the created avatar"

    @classmethod
    def poll(cls, context) -> bool:
        active = ScenePropertyGroup.get_group(context.scene).get_active()
        if active is None:
            return False
        if active.reduce_to_two_meshes and (not active.shape_keys_mesh_name or not active.no_shape_keys_mesh_name):
            return False
        return True

    def execute(self, context) -> str:
        scene = context.scene
        active_scene_settings = ScenePropertyGroup.get_group(context.scene).get_active()

        export_scene_name = active_scene_settings.name
        if not export_scene_name:
            raise ValueError("Active build settings' name must not be empty")

        if active_scene_settings.ignore_hidden_objects:
            scene_objects_gen = [o for o in scene.objects if not o.hide and not o.hide_viewport]
        else:
            scene_objects_gen = scene.objects

        # Annotated variables to assist with typing Object.data
        mesh_data: Mesh
        armature_data: Armature

        # Helper class
        @dataclass
        class ObjectHelper:
            orig_object: Object
            settings: ObjectBuildSettings
            desired_name: str
            copy_object: Union[Object, None] = None
            joined_settings_ignore_reduce_to_two_meshes: Union[bool, None] = None

        objects_for_build: list[ObjectHelper] = []

        allowed_object_types = {'MESH', 'ARMATURE'}
        for obj in scene_objects_gen:
            if obj.type in allowed_object_types:
                group = ObjectPropertyGroup.get_group(obj)
                object_settings = group.get_synced_settings(scene)
                if object_settings and object_settings.include_in_build:
                    desired_name = object_settings.target_object_name
                    if not desired_name:
                        desired_name = obj.name
                    helper_tuple = ObjectHelper(obj, object_settings, desired_name)
                    objects_for_build.append(helper_tuple)

        # Get desired object names and validate that there won't be any attempt to join Objects of different types
        desired_name_meshes: dict[str, list[ObjectHelper]] = defaultdict(list)
        desired_name_armatures: dict[str, list[ObjectHelper]] = defaultdict(list)
        for helper in objects_for_build:
            obj = helper.orig_object
            data = obj.data
            if isinstance(data, Mesh):
                name_dict = desired_name_meshes
            elif isinstance(data, Armature):
                name_dict = desired_name_armatures
            else:
                raise RuntimeError(f"Unexpected data type '{type(data)}' for object '{repr(obj)}' with type"
                                   f" '{obj.type}'")

            name_dict[helper.desired_name].append(helper)

        name_conflicts = set(desired_name_meshes.keys())
        name_conflicts.intersection_update(desired_name_armatures.keys())
        if name_conflicts:
            conflict_lines: list[str] = []
            for name in name_conflicts:
                meshes = [helper.orig_object for helper in desired_name_meshes[name]]
                armatures = [helper.orig_object for helper in desired_name_armatures[name]]
                conflict_lines.append(f"Name conflict '{name}':\n\tMeshes: {meshes}\n\tArmatures: {armatures}")
            conflicts_str = "\n".join(conflict_lines)
            raise RuntimeError(f"Some meshes and armatures have the same build name, but only objects of the same type"
                               f" can be combined together. Please change the build name for all objects in one"
                               f" of the lists for each name conflict:\n{conflicts_str}")

        shape_keys_mesh_name = active_scene_settings.shape_keys_mesh_name
        no_shape_keys_mesh_name = active_scene_settings.no_shape_keys_mesh_name
        if active_scene_settings.reduce_to_two_meshes:
            if not shape_keys_mesh_name:
                raise ValueError("When reduce to two meshes is enabled, the shape keys mesh name must not be empty")
            if not no_shape_keys_mesh_name:
                raise ValueError("When reduce to two meshes is enabled, the no shape keys mesh must not be empty")

            # There may be no name conflicts with the objects being joined, but if we're reducing to two meshes, it's
            # possible that a mesh that ignores reduce_to_two_meshes has the same name as either the shapekey mesh
            # or the non-shapekey mesh, which would be another conflict.
            disallowed_names = {shape_keys_mesh_name, no_shape_keys_mesh_name}

            for disallowed_name in disallowed_names:
                # Since armatures are unaffected by reduce_to_two_meshes, if there are any with the same name, we have
                # a conflict
                if disallowed_name in desired_name_armatures:
                    armature_helpers = desired_name_armatures[disallowed_name]
                    armature_object_names = ", ".join(h.orig_object.name for h in armature_helpers)
                    raise RuntimeError(f"Naming conflict. The armatures [{armature_object_names}] have the build name"
                                       f" '{disallowed_name}', but it is reserved by one of the meshes used in the"
                                       f" 'Reduce to two meshes' option."
                                       f"\nEither change the build name of the armatures or change the mesh name used"
                                       f" by the 'Reduce to two meshes' option.")
                # Meshes will be joined into one of the two meshes, unless they have the option enabled that makes them
                # ignore the reduce operation. We only need to check meshes that ignore that reduce operation.
                # Note that when meshes are joined by name, if any of them ignore the reduce operation, the joined mesh
                # will also ignore the reduce operation
                if disallowed_name in desired_name_meshes:
                    mesh_helpers = desired_name_meshes[disallowed_name]
                    # We only need to check meshes which ignore the reduce_to_two option, since other meshes will be
                    # joined together into one of the reduced meshes
                    ignoring_mesh_helpers = [h.orig_object.name for h in mesh_helpers if h.settings.ignore_reduce_to_two_meshes]
                    if ignoring_mesh_helpers:
                        ignoring_mesh_object_names = ", ".join(ignoring_mesh_helpers)
                        raise RuntimeError(f"Naming conflict. The meshes [{ignoring_mesh_object_names}] are ignoring"
                                           f" the 'Reduce to two meshes' option, but have the build name"
                                           f" '{disallowed_name}'. '{disallowed_name}' is reserved by one of the"
                                           f" meshes used in the 'Reduce to two meshes' option."
                                           f"\nEither change the build name of the meshes or change the mesh name used"
                                           f" by the 'Reduce to two meshes' option.")

        # Creation and modification can now commence as all checks have passed
        export_scene = bpy.data.scenes.new(export_scene_name + " Export Scene")
        export_scene_group = ScenePropertyGroup.get_group(export_scene)
        export_scene_group.is_export_scene = True
        export_scene_group.export_scene_source_scene = scene.name

        orig_object_to_helper: dict[Object, ObjectHelper] = {}
        # TODO: Change to store helpers?
        copy_objects: set[Object] = set()
        for helper in objects_for_build:
            obj = helper.orig_object
            # Copy object
            copy_obj = obj.copy()
            helper.copy_object = copy_obj
            copy_objects.add(copy_obj)

            # Store mapping from original object to helper for easier access
            orig_object_to_helper[obj] = helper

            # Copy data (also will make single user any linked data)
            copy_obj.data = obj.data.copy()

            # Add the copy object to the export scene (needed in order to join meshes)
            export_scene.collection.objects.link(copy_obj)

            # Currently, we don't copy Materials or any other data
            # We don't do anything else to each copy object yet to ensure that we fully populate the dictionary before
            # continuing as some operations will need to get the copy obj of an original object that they are related to

        # Operations within this loop must not cause Object ID blocks to be recreated
        for helper in orig_object_to_helper.values():
            copy_obj = helper.copy_object
            object_settings = helper.settings
            # TODO: Add a setting for whether to parent all meshes to the armature or not OR a setting for parenting
            #  objects without a parent (either because their parent isn't in the build or because they didn't have one
            #  to start with) to the first found armature for that object
            first_armature_copy = None

            # Set armature modifier objects to the copies
            for mod in copy_obj.modifiers:
                if mod.type == 'ARMATURE':
                    mod_object = mod.object
                    if mod_object and mod_object in orig_object_to_helper:
                        armature_copy = orig_object_to_helper[mod_object].copy_object
                        mod.object = armature_copy
                        if first_armature_copy is None:
                            first_armature_copy = armature_copy

            # TODO: Maybe we should give an option to re-parent to first armature?
            # Swap parents to copy object parent
            orig_parent = copy_obj.parent
            if orig_parent:
                if orig_parent in orig_object_to_helper:
                    parent_copy = orig_object_to_helper[orig_parent].copy_object
                    # TODO: Why doesn't this work?
                    # copy_obj.parent = parent_copy
                    override = {
                        'object': parent_copy,
                        # Not sure if the list needs to contain the new parent too, but it would usually be selected
                        # when re-parenting through the UI
                        'selected_editable_objects': [parent_copy, copy_obj],
                        # TODO: Not sure if scene is required, we'll include it anyway
                        'scene': export_scene,
                    }
                    bpy.ops.object.parent_set(override, type='OBJECT', keep_transform=True)
                    print(f"Swapped parent of copy of {helper.orig_object.name} to copy of {orig_parent.name}")
                else:
                    # Look for a recursive parent that does have a copy object and reparent to that
                    recursive_parent = orig_parent.parent
                    while recursive_parent and recursive_parent not in orig_object_to_helper:
                        orig_parent = orig_parent.parent
                    if recursive_parent:
                        # Re-parent to the found recursive parent
                        orig_recursive_parent_copy = orig_object_to_helper[recursive_parent].copy_object
                        # Transform must change to remain in the same place, run the operator to reparent and keep
                        # transforms
                        # Context override to act on the objects we want and not the current context
                        override = {
                            'object': orig_recursive_parent_copy,
                            # Not sure if the list needs to contain the new parent too, but it would usually be selected
                            # when re-parenting through the UI
                            'selected_editable_objects': [orig_recursive_parent_copy, copy_obj],
                            # TODO: Not sure if scene is required, we'll include it anyway
                            'scene': export_scene,
                        }
                        bpy.ops.object.parent_set(override, type='OBJECT', keep_transform=True)
                        print(f"Swapped parent of copy of {helper.orig_object.name} to copy of its recursive parent {recursive_parent.name}")
                    else:
                        # No recursive parent has a copy object, so clear parent, but keep transforms
                        # Context override to act on only the copy object
                        override = {
                            'selected_editable_objects': [copy_obj],
                            # Scene isn't required, but it could be good to include in-case it does become one
                            'scene': export_scene,
                        }
                        bpy.ops.object.parent_clear(override, type='CLEAR_KEEP_TRANSFORM')
                        print(f"Remove parent of copy of {helper.orig_object.name}, none of its recursive parents have copy objects")
            else:
                # No parent to start with, so the copy will remain with no parent
                pass

            # TODO: Should we run build first (and apply all transforms) before re-parenting?
            # Run build based on Object data type
            data = copy_obj.data
            if isinstance(data, Armature):
                build_armature(copy_obj, data, object_settings, copy_objects)
            elif isinstance(data, Mesh):
                build_mesh(scene, copy_obj, data, object_settings)

        # Join meshes and armatures by desired names and rename the combined objects to those desired names

        # Mesh and armature objects will only ever be attempted to join objects of the same type due to our initial
        # checks
        meshes_after_joining: list[ObjectHelper] = []
        armatures_after_joining: list[ObjectHelper] = []

        # meshes_tuple: tuple[str, defa]
        meshes_tuple = (
            'MESH',
            desired_name_meshes,
            meshes_after_joining,
            bpy.data.meshes.get,
            bpy.data.meshes.remove,
        )
        armatures_tuple = (
            'ARMATURE',
            desired_name_armatures,
            armatures_after_joining,
            bpy.data.armatures.get,
            bpy.data.armatures.remove,
        )

        for object_type, join_dict, after_joining_list, get_func, remove_func in (meshes_tuple, armatures_tuple):
            names_to_remove: list[str] = []
            for name, object_helpers in join_dict.items():
                objects = [helper.copy_object for helper in object_helpers]
                combined_object_helper = object_helpers[0]
                combined_object = combined_object_helper.copy_object
                context_override = {
                    'selected_editable_objects': objects,
                    'active_object': combined_object,
                    'scene': export_scene
                }
                if len(object_helpers) > 1:
                    # The data of the objects that join the combined object get left behind, we'll delete them and do so
                    # safely in-case Blender decides to delete them in the future
                    names_to_remove.extend(o.data.name for o in objects[1:])

                    if object_type == 'MESH':
                        # If any of the objects being joined were set to ignore, the combined mesh will be too
                        ignore_reduce_to_two = any(h.settings.ignore_reduce_to_two_meshes for h in object_helpers)
                        combined_object_helper.joined_settings_ignore_reduce_to_two_meshes = ignore_reduce_to_two

                        # TODO: Clean up all these comprehensions
                        # TODO: Are there other things that we should ensure are set a specific way on the combined mesh?
                        # noinspection PyUnresolvedReferences
                        joined_mesh_autosmooth = any(o.data.use_auto_smooth for o in objects)

                        # Set mesh autosmooth if any of the joined meshes used it
                        combined_object.data.use_auto_smooth = joined_mesh_autosmooth

                    # Join the objects
                    bpy.ops.object.join(context_override)

                else:
                    # There's only one object, there's nothing to join
                    pass

                # Append the ObjectHelper for the Object that remains after joining
                after_joining_list.append(combined_object_helper)

                # Since we're going to rename the joined copy objects, if an object with the corresponding name already
                # exists, and it doesn't have a target_object_name set, we need to set it to its current name because
                # its name is about to change
                set_build_name_for_existing_object_about_to_be_renamed(name)

                # Rename the combined mesh
                combined_object.name = name

            # Delete data of objects that have been joined into combined objects
            for name in names_to_remove:
                data_by_name = get_func(name)
                if data_by_name:
                    remove_func(data_by_name)

        # After performing deletions, these structures are no good anymore because some objects may be deleted
        del orig_object_to_helper, copy_objects

        # Join meshes based on whether they have shape keys
        # The ignore_reduce_to_two_meshes setting will need to only be True if it was True for all the joined meshes
        if active_scene_settings.reduce_to_two_meshes:
            shape_key_meshes = []
            # TODO: autosmooth settings
            shape_key_meshes_auto_smooth = False
            no_shape_key_meshes = []
            no_shape_key_meshes_auto_smooth = False

            for helper in meshes_after_joining:
                mesh_obj = helper.copy_object
                # Individual mesh objects can exclude themselves from this operation
                # If mesh objects have been combined, whether the combined mesh object should ignore is stored in
                # a separate attribute of the helper
                ignore_reduce_to_two = helper.joined_settings_ignore_reduce_to_two_meshes
                # If the separate attribute of the helper hasn't been set, it will be None
                if ignore_reduce_to_two is None:
                    # If no mesh objects were combined into this one, get whether to ignore from its own settings
                    ignore_reduce_to_two = helper.settings.ignore_reduce_to_two_meshes
                if not ignore_reduce_to_two:
                    # noinspection PyTypeChecker
                    mesh_data = mesh_obj.data
                    if mesh_data.shape_keys:
                        shape_key_meshes.append(mesh_obj)
                        shape_key_meshes_auto_smooth |= mesh_data.use_auto_smooth
                    else:
                        no_shape_key_meshes.append(mesh_obj)
                        no_shape_key_meshes_auto_smooth |= mesh_data.use_auto_smooth

            shape_keys_tuple = (shape_keys_mesh_name, shape_key_meshes, shape_key_meshes_auto_smooth)
            no_shape_keys_tuple = (no_shape_keys_mesh_name, no_shape_key_meshes, no_shape_key_meshes_auto_smooth)

            for name, mesh_objects, auto_smooth in (shape_keys_tuple, no_shape_keys_tuple):
                if mesh_objects:
                    mesh_names_to_remove = [m.data.name for m in mesh_objects[1:]]

                    combined_object = mesh_objects[0]
                    # noinspection PyTypeChecker
                    mesh_data = combined_object.data
                    # Set mesh autosmooth if any of the joined meshes used it
                    mesh_data.use_auto_smooth = auto_smooth

                    context_override = {
                        'selected_editable_objects': mesh_objects,
                        'active_object': combined_object,
                        'scene': export_scene
                    }

                    # Join the objects
                    bpy.ops.object.join(context_override)

                    # Since we're about to rename the combined object, if there is an existing object with that name, the
                    # existing object will have its name changed. If that object were to not have
                    set_build_name_for_existing_object_about_to_be_renamed(name)

                    # Rename the combined object
                    combined_object.name = name

                    for to_remove_name in mesh_names_to_remove:
                        to_remove = bpy.data.meshes.get(to_remove_name)
                        if to_remove:
                            bpy.data.meshes.remove(to_remove)

            # TODO: Join the meshes and rename the resulting mesh according to the scene settings.
            #  If an object already exists with the target name, set that object's
            #  existing_object_settings_for_scene.target_object_name to the target name if it hasn't been set to something

        # Swap to the export scene
        context.window.scene = export_scene

        return {'FINISHED'}


def prefix_classes(classes):
    for cls in classes:
        if hasattr(cls, 'bl_idname'):
            if issubclass(cls, Panel):
                cls.bl_idname = get_panel_prefix(cls) + "_PT_" + _BL_ID_PREFIX + "_" + cls.bl_idname
            elif issubclass(cls, Operator):
                cls.bl_idname = _BL_ID_PREFIX + "." + cls.bl_idname
            elif issubclass(cls, UIList):
                cls.bl_idname = "AVATAR_BUILDER_UL_" + cls.bl_idname
            elif issubclass(cls, Menu):
                cls.bl_idname = "AVATAR_BUILDER_MT_" + cls.bl_idname
            else:
                cls.bl_idname = _BL_ID_PREFIX + "_" + cls.bl_idname
        # if prefix_id:
        #     cls.bl_idname = _BL_ID_PREFIX + cls.bl_idname
        # elif hasattr(cls, 'bl_idname'):
        #     raise ValueError(f"{cls} has bl_idname, but it was not set to be prefixed!")


# TODO: maybe replace this with a method that looks through the current variables for classes that have
#  bl_idname
bl_classes = [
    SceneBuildSettingsControl,
    SceneBuildSettingsUIList,
    SceneBuildSettingsMenu,
    SceneBuildSettings,
    ScenePropertyGroup,
    ScenePanel,
    BuildAvatarOp,
    DeleteExportScene,
    ObjectBuildSettingsControl,
    ObjectBuildSettingsUIList,
    ObjectBuildSettings,
    ObjectPropertyGroup,
    ObjectPanel,
]

prefix_classes(bl_classes)

_register_classes, _unregister_classes = bpy.utils.register_classes_factory(bl_classes)


def register_props_factory(**registrations: (Type[PropHolderType], Type[PropertyGroupBase], Any)) -> (Callable, Callable, Callable):

    prefixed_registrations = {_PROP_PREFIX + '_' + k: v for k, v in registrations.items()}

    def register_props():
        for attribute_name, (bl_type, prop) in prefixed_registrations.items():
            setattr(bl_type, attribute_name, prop)

    def unregister_props():
        for attribute_name, (bl_type, _prop) in prefixed_registrations.items():
            delattr(bl_type, attribute_name)

    # Lookup to find property group by type
    property_group_lookup = {}
    for attribute_name, (bl_type, _prop) in prefixed_registrations.items():
        if bl_type not in property_group_lookup:
            property_group_lookup[bl_type] = attribute_name
        else:
            raise ValueError(f"Only one property should be registered per Blender ID/Bone/PoseBone, but got two for {bl_type}")

    def get_property_group(id_instance, strict=True) -> Union[CollectionPropertyType, None]:
        instance_type = type(id_instance)
        if instance_type in property_group_lookup:
            return getattr(id_instance, property_group_lookup[instance_type])
        elif strict:
            print(f"Available types:\n{property_group_lookup}")
            raise ValueError(f"{id_instance} (a {instance_type}) does not have an Avatar Builder property group")
        else:
            return None

    return register_props, unregister_props, get_property_group


_register_props, _unregister_props, get_property_group = register_props_factory(
    scene_settings_group=(Scene, PointerProperty(type=ScenePropertyGroup)),
    object_settings_group=(Object, PointerProperty(type=ObjectPropertyGroup)),
)


def register(is_test=False):
    if is_test:
        # Get unregister function of previous test from WindowManager type and call it
        if hasattr(bpy.types.WindowManager, 'mysteryem_test_unregister'):
            # noinspection PyBroadException
            try:
                bpy.types.WindowManager.mysteryem_test_unregister(is_test=True)
            except Exception as e:
                print("unregistering previous version failed, continuing")
                print(e)
        # Set unregister function on WindowManager
        # TODO: Make sure this isn't saved in blend files or otherwise persisted
        bpy.types.WindowManager.mysteryem_test_unregister = unregister
    # Register everything here
    _register_classes()
    _register_props()


def unregister(is_test=False):
    if is_test:
        # noinspection PyUnresolvedReferences
        del bpy.types.WindowManager.mysteryem_test_unregister
    # Unregister everything here
    _unregister_props()
    _unregister_classes()


# Test from the editor
if __name__ == '__main__':
    register(is_test=True)