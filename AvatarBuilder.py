from typing import Type, Any, Union, TypeVar, Callable, Annotated
from collections import defaultdict
import numpy as np
import bpy
from bpy.props import StringProperty, BoolProperty, CollectionProperty, IntProperty, EnumProperty, PointerProperty
from bpy.types import (Armature, PropertyGroup, Operator, Panel, UIList, Object, ShapeKey, Mesh, ID, Bone, PoseBone,
                       Context, Menu, UILayout, Scene, MeshUVLoopLayer)
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


class SceneBuildSettingsControl(Operator):
    bl_idname = 'scene_build_settings_control'
    bl_label = "Build Settings Control"

    command: EnumProperty(
        items=[
            ('ADD', "Add", "Add a new set of Build Settings"),
            ('REMOVE', "Remove", "Remove the currently active Build Settings"),
            # TODO: By default we only show the object settings matching the scene settings, so is this necessary?
            ('SYNC', "Sync", "Set the currently displayed settings of all objects in the scene to the currently active Build Settings"),
            ('UP', "Move Up", "Move active Build Settings up"),
            ('DOWN', "Move Down", "Move active Build Settings down"),
            ('TOP', "Move to top", "Move active Build Settings to top"),
            ('BOTTOM', "Move to bottom", "Move active Build Settings to bottom"),
            # TODO: Implement and add a 'Fake User' BoolProperty to Object Settings that prevents purging
            ('PURGE', "Purge", "Clear all orphaned Build Settings from all objects in the scene"),
        ],
        default='ADD',
    )

    # @classmethod
    # def description(cls, context, properties):
    #     command = properties.command
    #     # see if we can get the description from the enum property

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
            scene_group.build_settings_active_index = active_index - 1
        elif command == 'SYNC':
            self.report({'INFO'}, "Sync is not implemented yet")
        elif command == 'UP':
            # TODO: Wrap around when at top already
            new_index = max(0, active_index - 1)
            build_settings.move(active_index, new_index)
            scene_group.build_settings_active_index = new_index
        elif command == 'DOWN':
            # TODO: Wrap around when at bottom already
            new_index = min(len(build_settings) - 1, active_index + 1)
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


# TODO: Duplicate and Delete ops that take an index argument so we can have a button displayed for each element in the
#  list
class ObjectBuildSettingsControl(Operator):
    bl_idname = 'object_build_settings_control'
    bl_label = "Object Build Settings Control"

    command: EnumProperty(
        items=[
            ('ADD', "Add", "Add a new set of build settings, defaults to the active build settings if they don't exist on this Object"),
            ('REMOVE', "Remove", "Remove the currently active build settings"),
            # Disabled if doesn't exist on the object
            ('SYNC', "Sync", "Set the currently displayed settings of to the currently active build settings"),
            ('UP', "Move Up", "Move active build settings up"),
            ('DOWN', "Move Down", "Move active build settings down"),
            ('TOP', "Move to top", "Move active build settings to top"),
            ('BOTTOM', "Move to bottom", "Move active build settings to bottom"),
        ],
        default='ADD',
    )

    # @classmethod
    # def description(cls, context, properties):
    #     command = properties.command
    #     # see if we can get the description from the enum property

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
                        if active_index >= len(object_build_settings):
                            object_group.object_settings_active_index = active_index - 1
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
                # TODO: Wrap around when at top already
                new_index = max(0, active_index - 1)
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'DOWN':
                # TODO: Wrap around when at bottom already
                new_index = min(len(object_build_settings) - 1, active_index + 1)
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
    target_mesh_name: StringProperty(
        name="Built mesh name",
        description="The name of the mesh once building is complete.\n"
                    "All meshes with the same name will be joined together\n"
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
        description="Intended for use to override modifier settings when exporting for VRM which requires a T-Pose when"
                    " a model has been created in an A-pose. Enabling Preserve Volume and changing the export pose to a"
                    " T-Pose may produce better results exporting directly as T-Pose compared to setting T-Pose in"
                    " Unity when normalizing for VRM."
    )

    # Mesh props
    # Keep/Merge(see below)/Apply Mix/Delete-All
    shape_keys_op: EnumProperty(
        name="Operation",
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
            ('APPLY_KEEP_SHAPES_ADDON', "(NYI)Apply with shapes", "Apply modifiers. Use an addon when the mesh has shape keys"),
        ],
        default='APPLY_IF_POSSIBLE',
    )

    # TODO: Extend this to a collection property so that multiple can be kept
    # UV Layer to keep
    keep_only_uv_map: StringProperty(name="UV Map to keep", description="Name of the only UV map to keep on this mesh")

    # Clean up vertex groups that aren't used by the armature
    remove_non_deform_vertex_groups: BoolProperty(name="Remove non-deform vg", description="Remove vertex groups that don't have an associated bone in the armature")

    remove_vertex_colors: BoolProperty(name="Remove vertex colors", description="Remove all vertex colors")

    # TODO: Extend to being able to re-map materials from one to another
    keep_only_material: StringProperty(name="Material to keep", description="Name of the only Material to keep on the mesh")

    # materials_remap
    remap_materials: BoolProperty(default=False)
    # materials_remap: CollectionProperty(type=<custom type needed?>)

    ignore_reduce_to_two_meshes: BoolProperty(default=False)


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
        col = layout.column()
        col.label(text="Scene Settings Groups")
        group = ScenePropertyGroup.get_group(context.scene)
        row = col.row()
        row.template_list(SceneBuildSettingsUIList.bl_idname, "", group, 'build_settings', group, 'build_settings_active_index')
        vertical_buttons_col = row.column(align=True)
        vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="ADD").command = 'ADD'
        vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="REMOVE").command = 'REMOVE'
        vertical_buttons_col.separator()
        # vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="TRIA_UP_BAR").command = 'TOP'
        vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="TRIA_UP").command = 'UP'
        vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN").command = 'DOWN'
        # vertical_buttons_col.operator(SceneBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN_BAR").command = 'BOTTOM'
        # vertical_buttons_col.direction = 'VERTICAL'

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
                sub.prop(scene_settings, 'shape_keys_mesh_name', icon="MESH_DATA", text="Shape keys")
                sub.prop(scene_settings, 'no_shape_keys_mesh_name', icon="MESH_DATA", text="No shape keys")
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
        if is_scene_active:
            row_icon = "SCENE_DATA"
        elif is_orphaned:
            #row_icon = "ORPHAN_DATA"
            # row_icon = "LIBRARY_DATA_BROKEN"
            # row_icon = "UNLINKED"
            row_icon = "GHOST_DISABLED"
        else:
            row_icon = "BLANK1"
        row.label(text="", icon="SETTINGS")
        # Display the prop of the scene settings if it exists, this simplifies renaming
        row.prop(item if is_orphaned else scene_settings[index_in_scene_settings], 'name_prop', text="", emboss=False, icon=row_icon)
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
        scene = context.scene
        # Build settings must be non-empty
        # TODO: Should add a 'clean' or 'purge' button to Scene panel that purges non-existent build settings from all
        #       objects in the current scene. This is because we otherwise have no way to remove the object settings
        #       if we hide the panel when there's no build settings
        return ScenePropertyGroup.get_group(scene).build_settings

    def draw(self, context: Context):
        obj = context.object
        group = ObjectPropertyGroup.get_group(obj)
        object_settings = group.object_settings

        layout = self.layout
        main_col = layout.column()
        # Sync setting and anything else that should be before things

        col = main_col.column()
        # col.use_property_split = True
        col.use_property_decorate = True

        row = col.row(align=True)
        row.use_property_decorate = False
        row.prop(group, 'sync_active_with_scene', icon="SCENE_DATA", text="")
        row.prop(group, 'sync_active_with_scene', icon="OBJECT_DATA", text="", invert_checkbox=True)

        is_synced = group.sync_active_with_scene
        if group.sync_active_with_scene:
            # Get active_object_settings by name of active_build_settings
            scene_group = ScenePropertyGroup.get_group(context.scene)
            active_build_settings = scene_group.get_active()

            if active_build_settings:
                active_object_settings = object_settings.get(active_build_settings.name)
            else:
                active_object_settings = None
                if scene_group.build_settings:
                    # Only happens if the active index is out of bounds for some reason, since we hide the panel
                    # when there are no Build Settings
                    col.label(text="Active build settings is out of bounds, this shouldn't normally happen, select one in"
                                   " the list in the 3D View and the active build settings index will update automatically")
                    # TODO: Draw button to 'fix' out of bounds index
            if active_object_settings:
                if active_build_settings:
                    row.separator()
                    row.label(text="", icon="SETTINGS")
                    row.prop(active_build_settings, "name_prop", icon="SCENE_DATA", emboss=False, text="")
                    row.prop(active_object_settings, "include_in_build", text="")
            else:
                row.operator(ObjectBuildSettingsControl.bl_idname, text="Add to Avatar Builder", icon="ADD").command = 'ADD'
        else:
            list_row = row.row(align=False)
            list_row.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'object_settings', group, 'object_settings_active_index', rows=3)
            vertical_buttons_col = row.column(align=True)
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="ADD").command = 'ADD'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="REMOVE").command = 'REMOVE'
            vertical_buttons_col.separator()
            # vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="UV_SYNC_SELECT").command = 'SYNC'
            # vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_UP_BAR").command = 'TOP'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_UP").command = 'UP'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN").command = 'DOWN'
            # vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN_BAR").command = 'BOTTOM'
            # sub_col_no_decorate = col.column(align=True)
            # sub_col_no_decorate.use_property_split = False
            #
            # # TODO: Needs its own UIList class that highlights the currently active build settings, if it exists in the
            # #  list
            # sub_col_no_decorate.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'object_settings', group, 'object_settings_active_index', rows=3)
            # buttons_col = col.column(align=True)
            # row = buttons_col.row(align=True)
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Add").command = 'ADD'
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Remove").command = 'REMOVE'
            # row = buttons_col.row(align=True)
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Up").command = 'UP'
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Down").command = 'DOWN'
            # row = buttons_col.row(align=True)
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Top").command = 'TOP'
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Bottom").command = 'BOTTOM'
            # TODO: Sync is only useful if forced sync is turned off, so only display it in those cases
            # row = buttons_col.row(align=True)
            # row.operator(ObjectBuildSettingsControl.bl_idname, text="Sync").command = 'SYNC'

            object_settings_active_index = group.object_settings_active_index
            num_object_settings = len(object_settings)
            if num_object_settings > 0 and 0 <= object_settings_active_index < num_object_settings:
                active_object_settings = object_settings[object_settings_active_index]
            else:
                active_object_settings = None

        # TODO: Now display props for active_object_settings
        if active_object_settings:
            enabled = active_object_settings.include_in_build
            properties_col = layout.column(align=True)
            properties_col.use_property_split = True
            properties_col.use_property_decorate = False
            if obj.type == 'ARMATURE':
                armature_box = properties_col.box()
                armature_box.enabled = enabled
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
                mesh_general_box = properties_col.box()
                mesh_general_box.enabled = enabled

                mesh_general_box_col = mesh_general_box.column()
                mesh_general_box_col.label(text="Mesh", icon="OBJECT_DATA")
                mesh_general_box_col.prop(active_object_settings, 'target_mesh_name')
                non_deform_vertex_group_clear_row = mesh_general_box_col.row()
                non_deform_vertex_group_clear_row.prop(active_object_settings, 'remove_non_deform_vertex_groups')
                non_deform_vertex_group_clear_row.label(icon="GROUP_VERTEX")

                if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1:
                    shape_keys_box = properties_col.box()
                    shape_keys_box.enabled = enabled
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

                    merge_col.prop(active_object_settings, 'merge_shape_keys_prefix_suffix', text=text_label)
                    merge_col.prop(active_object_settings, 'merge_shape_keys_pattern')
                    merge_col.prop(active_object_settings, 'merge_shape_keys_ignore_prefix')
                    # ------------------------

                if obj.data.uv_layers:
                    uv_layers_box = properties_col.box()
                    uv_layers_box_col = uv_layers_box.column()
                    uv_layers_box_col.label(text="UV Layers", icon="GROUP_UVS")
                    uv_layers_box_col.prop_search(active_object_settings, 'keep_only_uv_map', obj.data, 'uv_layers', icon="GROUP_UVS")

                if obj.data.materials:
                    materials_box = properties_col.box()
                    materials_box_col = materials_box.column()
                    materials_box_col.label(text="Materials", icon="MATERIAL_DATA")
                    materials_box_col.prop_search(active_object_settings, 'keep_only_material', obj.data, 'materials')

                ################
                # Mesh Modifiers
                ################
                mesh_modifiers_box = properties_col.box()
                mesh_modifiers_box.enabled = enabled
                mesh_modifiers_box_col = mesh_modifiers_box.column(align=True)
                mesh_modifiers_box_col.label(text="Modifiers", icon="MODIFIER_DATA")
                mesh_modifiers_box_col.prop(active_object_settings, 'apply_non_armature_modifiers')

            # all_icons = ['NONE', 'QUESTION', 'ERROR', 'CANCEL', 'TRIA_RIGHT', 'TRIA_DOWN', 'TRIA_LEFT', 'TRIA_UP', 'ARROW_LEFTRIGHT', 'PLUS', 'DISCLOSURE_TRI_RIGHT', 'DISCLOSURE_TRI_DOWN', 'RADIOBUT_OFF', 'RADIOBUT_ON', 'MENU_PANEL', 'BLENDER', 'GRIP', 'DOT', 'COLLAPSEMENU', 'X', 'DUPLICATE', 'TRASH', 'COLLECTION_NEW', 'OPTIONS', 'NODE', 'NODE_SEL', 'WINDOW', 'WORKSPACE', 'RIGHTARROW_THIN', 'BORDERMOVE', 'VIEWZOOM', 'ADD', 'REMOVE', 'PANEL_CLOSE', 'COPY_ID', 'EYEDROPPER', 'CHECKMARK', 'AUTO', 'CHECKBOX_DEHLT', 'CHECKBOX_HLT', 'UNLOCKED', 'LOCKED', 'UNPINNED', 'PINNED', 'SCREEN_BACK', 'RIGHTARROW', 'DOWNARROW_HLT', 'FCURVE_SNAPSHOT', 'OBJECT_HIDDEN', 'TOPBAR', 'STATUSBAR', 'PLUGIN', 'HELP', 'GHOST_ENABLED', 'COLOR', 'UNLINKED', 'LINKED', 'HAND', 'ZOOM_ALL', 'ZOOM_SELECTED', 'ZOOM_PREVIOUS', 'ZOOM_IN', 'ZOOM_OUT', 'DRIVER_DISTANCE', 'DRIVER_ROTATIONAL_DIFFERENCE', 'DRIVER_TRANSFORM', 'FREEZE', 'STYLUS_PRESSURE', 'GHOST_DISABLED', 'FILE_NEW', 'FILE_TICK', 'QUIT', 'URL', 'RECOVER_LAST', 'THREE_DOTS', 'FULLSCREEN_ENTER', 'FULLSCREEN_EXIT', 'BRUSHES_ALL', 'LIGHT', 'MATERIAL', 'TEXTURE', 'ANIM', 'WORLD', 'SCENE', 'OUTPUT', 'SCRIPT', 'PARTICLES', 'PHYSICS', 'SPEAKER', 'TOOL_SETTINGS', 'SHADERFX', 'MODIFIER', 'BLANK1', 'FAKE_USER_OFF', 'FAKE_USER_ON', 'VIEW3D', 'GRAPH', 'OUTLINER', 'PROPERTIES', 'FILEBROWSER', 'IMAGE', 'INFO', 'SEQUENCE', 'TEXT', 'SPREADSHEET', 'SOUND', 'ACTION', 'NLA', 'PREFERENCES', 'TIME', 'NODETREE', 'CONSOLE', 'TRACKER', 'ASSET_MANAGER', 'NODE_COMPOSITING', 'NODE_TEXTURE', 'NODE_MATERIAL', 'UV', 'OBJECT_DATAMODE', 'EDITMODE_HLT', 'UV_DATA', 'VPAINT_HLT', 'TPAINT_HLT', 'WPAINT_HLT', 'SCULPTMODE_HLT', 'POSE_HLT', 'PARTICLEMODE', 'TRACKING', 'TRACKING_BACKWARDS', 'TRACKING_FORWARDS', 'TRACKING_BACKWARDS_SINGLE', 'TRACKING_FORWARDS_SINGLE', 'TRACKING_CLEAR_BACKWARDS', 'TRACKING_CLEAR_FORWARDS', 'TRACKING_REFINE_BACKWARDS', 'TRACKING_REFINE_FORWARDS', 'SCENE_DATA', 'RENDERLAYERS', 'WORLD_DATA', 'OBJECT_DATA', 'MESH_DATA', 'CURVE_DATA', 'META_DATA', 'LATTICE_DATA', 'LIGHT_DATA', 'MATERIAL_DATA', 'TEXTURE_DATA', 'ANIM_DATA', 'CAMERA_DATA', 'PARTICLE_DATA', 'LIBRARY_DATA_DIRECT', 'GROUP', 'ARMATURE_DATA', 'COMMUNITY', 'BONE_DATA', 'CONSTRAINT', 'SHAPEKEY_DATA', 'CONSTRAINT_BONE', 'CAMERA_STEREO', 'PACKAGE', 'UGLYPACKAGE', 'EXPERIMENTAL', 'BRUSH_DATA', 'IMAGE_DATA', 'FILE', 'FCURVE', 'FONT_DATA', 'RENDER_RESULT', 'SURFACE_DATA', 'EMPTY_DATA', 'PRESET', 'RENDER_ANIMATION', 'RENDER_STILL', 'LIBRARY_DATA_BROKEN', 'BOIDS', 'STRANDS', 'GREASEPENCIL', 'LINE_DATA', 'LIBRARY_DATA_OVERRIDE', 'GROUP_BONE', 'GROUP_VERTEX', 'GROUP_VCOL', 'GROUP_UVS', 'FACE_MAPS', 'RNA', 'RNA_ADD', 'MOUSE_LMB', 'MOUSE_MMB', 'MOUSE_RMB', 'MOUSE_MOVE', 'MOUSE_LMB_DRAG', 'MOUSE_MMB_DRAG', 'MOUSE_RMB_DRAG', 'MEMORY', 'PRESET_NEW', 'DECORATE', 'DECORATE_KEYFRAME', 'DECORATE_ANIMATE', 'DECORATE_DRIVER', 'DECORATE_LINKED', 'DECORATE_LIBRARY_OVERRIDE', 'DECORATE_UNLOCKED', 'DECORATE_LOCKED', 'DECORATE_OVERRIDE', 'FUND', 'TRACKER_DATA', 'HEART', 'ORPHAN_DATA', 'USER', 'SYSTEM', 'SETTINGS', 'OUTLINER_OB_EMPTY', 'OUTLINER_OB_MESH', 'OUTLINER_OB_CURVE', 'OUTLINER_OB_LATTICE', 'OUTLINER_OB_META', 'OUTLINER_OB_LIGHT', 'OUTLINER_OB_CAMERA', 'OUTLINER_OB_ARMATURE', 'OUTLINER_OB_FONT', 'OUTLINER_OB_SURFACE', 'OUTLINER_OB_SPEAKER', 'OUTLINER_OB_FORCE_FIELD', 'OUTLINER_OB_GROUP_INSTANCE', 'OUTLINER_OB_GREASEPENCIL', 'OUTLINER_OB_LIGHTPROBE', 'OUTLINER_OB_IMAGE', 'OUTLINER_COLLECTION', 'RESTRICT_COLOR_OFF', 'RESTRICT_COLOR_ON', 'HIDE_ON', 'HIDE_OFF', 'RESTRICT_SELECT_ON', 'RESTRICT_SELECT_OFF', 'RESTRICT_RENDER_ON', 'RESTRICT_RENDER_OFF', 'RESTRICT_INSTANCED_OFF', 'OUTLINER_DATA_EMPTY', 'OUTLINER_DATA_MESH', 'OUTLINER_DATA_CURVE', 'OUTLINER_DATA_LATTICE', 'OUTLINER_DATA_META', 'OUTLINER_DATA_LIGHT', 'OUTLINER_DATA_CAMERA', 'OUTLINER_DATA_ARMATURE', 'OUTLINER_DATA_FONT', 'OUTLINER_DATA_SURFACE', 'OUTLINER_DATA_SPEAKER', 'OUTLINER_DATA_LIGHTPROBE', 'OUTLINER_DATA_GP_LAYER', 'OUTLINER_DATA_GREASEPENCIL', 'GP_SELECT_POINTS', 'GP_SELECT_STROKES', 'GP_MULTIFRAME_EDITING', 'GP_ONLY_SELECTED', 'GP_SELECT_BETWEEN_STROKES', 'MODIFIER_OFF', 'MODIFIER_ON', 'ONIONSKIN_OFF', 'ONIONSKIN_ON', 'RESTRICT_VIEW_ON', 'RESTRICT_VIEW_OFF', 'RESTRICT_INSTANCED_ON', 'MESH_PLANE', 'MESH_CUBE', 'MESH_CIRCLE', 'MESH_UVSPHERE', 'MESH_ICOSPHERE', 'MESH_GRID', 'MESH_MONKEY', 'MESH_CYLINDER', 'MESH_TORUS', 'MESH_CONE', 'MESH_CAPSULE', 'EMPTY_SINGLE_ARROW', 'LIGHT_POINT', 'LIGHT_SUN', 'LIGHT_SPOT', 'LIGHT_HEMI', 'LIGHT_AREA', 'CUBE', 'SPHERE', 'CONE', 'META_PLANE', 'META_CUBE', 'META_BALL', 'META_ELLIPSOID', 'META_CAPSULE', 'SURFACE_NCURVE', 'SURFACE_NCIRCLE', 'SURFACE_NSURFACE', 'SURFACE_NCYLINDER', 'SURFACE_NSPHERE', 'SURFACE_NTORUS', 'EMPTY_AXIS', 'STROKE', 'EMPTY_ARROWS', 'CURVE_BEZCURVE', 'CURVE_BEZCIRCLE', 'CURVE_NCURVE', 'CURVE_NCIRCLE', 'CURVE_PATH', 'LIGHTPROBE_CUBEMAP', 'LIGHTPROBE_PLANAR', 'LIGHTPROBE_GRID', 'COLOR_RED', 'COLOR_GREEN', 'COLOR_BLUE', 'TRIA_RIGHT_BAR', 'TRIA_DOWN_BAR', 'TRIA_LEFT_BAR', 'TRIA_UP_BAR', 'FORCE_FORCE', 'FORCE_WIND', 'FORCE_VORTEX', 'FORCE_MAGNETIC', 'FORCE_HARMONIC', 'FORCE_CHARGE', 'FORCE_LENNARDJONES', 'FORCE_TEXTURE', 'FORCE_CURVE', 'FORCE_BOID', 'FORCE_TURBULENCE', 'FORCE_DRAG', 'FORCE_FLUIDFLOW', 'RIGID_BODY', 'RIGID_BODY_CONSTRAINT', 'IMAGE_PLANE', 'IMAGE_BACKGROUND', 'IMAGE_REFERENCE', 'NODE_INSERT_ON', 'NODE_INSERT_OFF', 'NODE_TOP', 'NODE_SIDE', 'NODE_CORNER', 'ANCHOR_TOP', 'ANCHOR_BOTTOM', 'ANCHOR_LEFT', 'ANCHOR_RIGHT', 'ANCHOR_CENTER', 'SELECT_SET', 'SELECT_EXTEND', 'SELECT_SUBTRACT', 'SELECT_INTERSECT', 'SELECT_DIFFERENCE', 'ALIGN_LEFT', 'ALIGN_CENTER', 'ALIGN_RIGHT', 'ALIGN_JUSTIFY', 'ALIGN_FLUSH', 'ALIGN_TOP', 'ALIGN_MIDDLE', 'ALIGN_BOTTOM', 'BOLD', 'ITALIC', 'UNDERLINE', 'SMALL_CAPS', 'CON_ACTION', 'MOD_LENGTH', 'MOD_DASH', 'MOD_LINEART', 'HOLDOUT_OFF', 'HOLDOUT_ON', 'INDIRECT_ONLY_OFF', 'INDIRECT_ONLY_ON', 'CON_CAMERASOLVER', 'CON_FOLLOWTRACK', 'CON_OBJECTSOLVER', 'CON_LOCLIKE', 'CON_ROTLIKE', 'CON_SIZELIKE', 'CON_TRANSLIKE', 'CON_DISTLIMIT', 'CON_LOCLIMIT', 'CON_ROTLIMIT', 'CON_SIZELIMIT', 'CON_SAMEVOL', 'CON_TRANSFORM', 'CON_TRANSFORM_CACHE', 'CON_CLAMPTO', 'CON_KINEMATIC', 'CON_LOCKTRACK', 'CON_SPLINEIK', 'CON_STRETCHTO', 'CON_TRACKTO', 'CON_ARMATURE', 'CON_CHILDOF', 'CON_FLOOR', 'CON_FOLLOWPATH', 'CON_PIVOT', 'CON_SHRINKWRAP', 'MODIFIER_DATA', 'MOD_WAVE', 'MOD_BUILD', 'MOD_DECIM', 'MOD_MIRROR', 'MOD_SOFT', 'MOD_SUBSURF', 'HOOK', 'MOD_PHYSICS', 'MOD_PARTICLES', 'MOD_BOOLEAN', 'MOD_EDGESPLIT', 'MOD_ARRAY', 'MOD_UVPROJECT', 'MOD_DISPLACE', 'MOD_CURVE', 'MOD_LATTICE', 'MOD_TINT', 'MOD_ARMATURE', 'MOD_SHRINKWRAP', 'MOD_CAST', 'MOD_MESHDEFORM', 'MOD_BEVEL', 'MOD_SMOOTH', 'MOD_SIMPLEDEFORM', 'MOD_MASK', 'MOD_CLOTH', 'MOD_EXPLODE', 'MOD_FLUIDSIM', 'MOD_MULTIRES', 'MOD_FLUID', 'MOD_SOLIDIFY', 'MOD_SCREW', 'MOD_VERTEX_WEIGHT', 'MOD_DYNAMICPAINT', 'MOD_REMESH', 'MOD_OCEAN', 'MOD_WARP', 'MOD_SKIN', 'MOD_TRIANGULATE', 'MOD_WIREFRAME', 'MOD_DATA_TRANSFER', 'MOD_NORMALEDIT', 'MOD_PARTICLE_INSTANCE', 'MOD_HUE_SATURATION', 'MOD_NOISE', 'MOD_OFFSET', 'MOD_SIMPLIFY', 'MOD_THICKNESS', 'MOD_INSTANCE', 'MOD_TIME', 'MOD_OPACITY', 'REC', 'PLAY', 'FF', 'REW', 'PAUSE', 'PREV_KEYFRAME', 'NEXT_KEYFRAME', 'PLAY_SOUND', 'PLAY_REVERSE', 'PREVIEW_RANGE', 'ACTION_TWEAK', 'PMARKER_ACT', 'PMARKER_SEL', 'PMARKER', 'MARKER_HLT', 'MARKER', 'KEYFRAME_HLT', 'KEYFRAME', 'KEYINGSET', 'KEY_DEHLT', 'KEY_HLT', 'MUTE_IPO_OFF', 'MUTE_IPO_ON', 'DRIVER', 'SOLO_OFF', 'SOLO_ON', 'FRAME_PREV', 'FRAME_NEXT', 'NLA_PUSHDOWN', 'IPO_CONSTANT', 'IPO_LINEAR', 'IPO_BEZIER', 'IPO_SINE', 'IPO_QUAD', 'IPO_CUBIC', 'IPO_QUART', 'IPO_QUINT', 'IPO_EXPO', 'IPO_CIRC', 'IPO_BOUNCE', 'IPO_ELASTIC', 'IPO_BACK', 'IPO_EASE_IN', 'IPO_EASE_OUT', 'IPO_EASE_IN_OUT', 'NORMALIZE_FCURVES', 'VERTEXSEL', 'EDGESEL', 'FACESEL', 'CURSOR', 'PIVOT_BOUNDBOX', 'PIVOT_CURSOR', 'PIVOT_INDIVIDUAL', 'PIVOT_MEDIAN', 'PIVOT_ACTIVE', 'CENTER_ONLY', 'ROOTCURVE', 'SMOOTHCURVE', 'SPHERECURVE', 'INVERSESQUARECURVE', 'SHARPCURVE', 'LINCURVE', 'NOCURVE', 'RNDCURVE', 'PROP_OFF', 'PROP_ON', 'PROP_CON', 'PROP_PROJECTED', 'PARTICLE_POINT', 'PARTICLE_TIP', 'PARTICLE_PATH', 'SNAP_FACE_CENTER', 'SNAP_PERPENDICULAR', 'SNAP_MIDPOINT', 'SNAP_OFF', 'SNAP_ON', 'SNAP_NORMAL', 'SNAP_GRID', 'SNAP_VERTEX', 'SNAP_EDGE', 'SNAP_FACE', 'SNAP_VOLUME', 'SNAP_INCREMENT', 'STICKY_UVS_LOC', 'STICKY_UVS_DISABLE', 'STICKY_UVS_VERT', 'CLIPUV_DEHLT', 'CLIPUV_HLT', 'SNAP_PEEL_OBJECT', 'GRID', 'OBJECT_ORIGIN', 'ORIENTATION_GLOBAL', 'ORIENTATION_GIMBAL', 'ORIENTATION_LOCAL', 'ORIENTATION_NORMAL', 'ORIENTATION_VIEW', 'COPYDOWN', 'PASTEDOWN', 'PASTEFLIPUP', 'PASTEFLIPDOWN', 'VIS_SEL_11', 'VIS_SEL_10', 'VIS_SEL_01', 'VIS_SEL_00', 'AUTOMERGE_OFF', 'AUTOMERGE_ON', 'UV_VERTEXSEL', 'UV_EDGESEL', 'UV_FACESEL', 'UV_ISLANDSEL', 'UV_SYNC_SELECT', 'GP_CAPS_FLAT', 'GP_CAPS_ROUND', 'FIXED_SIZE', 'TRANSFORM_ORIGINS', 'GIZMO', 'ORIENTATION_CURSOR', 'NORMALS_VERTEX', 'NORMALS_FACE', 'NORMALS_VERTEX_FACE', 'SHADING_BBOX', 'SHADING_WIRE', 'SHADING_SOLID', 'SHADING_RENDERED', 'SHADING_TEXTURE', 'OVERLAY', 'XRAY', 'LOCKVIEW_OFF', 'LOCKVIEW_ON', 'AXIS_SIDE', 'AXIS_FRONT', 'AXIS_TOP', 'LAYER_USED', 'LAYER_ACTIVE', 'OUTLINER_OB_CURVES', 'OUTLINER_DATA_CURVES', 'CURVES_DATA', 'OUTLINER_OB_POINTCLOUD', 'OUTLINER_DATA_POINTCLOUD', 'POINTCLOUD_DATA', 'OUTLINER_OB_VOLUME', 'OUTLINER_DATA_VOLUME', 'VOLUME_DATA', 'CURRENT_FILE', 'HOME', 'DOCUMENTS', 'TEMP', 'SORTALPHA', 'SORTBYEXT', 'SORTTIME', 'SORTSIZE', 'SHORTDISPLAY', 'LONGDISPLAY', 'IMGDISPLAY', 'BOOKMARKS', 'FONTPREVIEW', 'FILTER', 'NEWFOLDER', 'FOLDER_REDIRECT', 'FILE_PARENT', 'FILE_REFRESH', 'FILE_FOLDER', 'FILE_BLANK', 'FILE_BLEND', 'FILE_IMAGE', 'FILE_MOVIE', 'FILE_SCRIPT', 'FILE_SOUND', 'FILE_FONT', 'FILE_TEXT', 'SORT_DESC', 'SORT_ASC', 'LINK_BLEND', 'APPEND_BLEND', 'IMPORT', 'EXPORT', 'LOOP_BACK', 'LOOP_FORWARDS', 'BACK', 'FORWARD', 'FILE_ARCHIVE', 'FILE_CACHE', 'FILE_VOLUME', 'FILE_3D', 'FILE_HIDDEN', 'FILE_BACKUP', 'DISK_DRIVE', 'MATPLANE', 'MATSPHERE', 'MATCUBE', 'MONKEY', 'CURVES', 'ALIASED', 'ANTIALIASED', 'MAT_SPHERE_SKY', 'MATSHADERBALL', 'MATCLOTH', 'MATFLUID', 'WORDWRAP_OFF', 'WORDWRAP_ON', 'SYNTAX_OFF', 'SYNTAX_ON', 'LINENUMBERS_OFF', 'LINENUMBERS_ON', 'SCRIPTPLUGINS', 'DISC', 'DESKTOP', 'EXTERNAL_DRIVE', 'NETWORK_DRIVE', 'SEQ_SEQUENCER', 'SEQ_PREVIEW', 'SEQ_LUMA_WAVEFORM', 'SEQ_CHROMA_SCOPE', 'SEQ_HISTOGRAM', 'SEQ_SPLITVIEW', 'SEQ_STRIP_META', 'SEQ_STRIP_DUPLICATE', 'IMAGE_RGB', 'IMAGE_RGB_ALPHA', 'IMAGE_ALPHA', 'IMAGE_ZDEPTH', 'HANDLE_AUTOCLAMPED', 'HANDLE_AUTO', 'HANDLE_ALIGNED', 'HANDLE_VECTOR', 'HANDLE_FREE', 'VIEW_PERSPECTIVE', 'VIEW_ORTHO', 'VIEW_CAMERA', 'VIEW_PAN', 'VIEW_ZOOM', 'BRUSH_BLOB', 'BRUSH_BLUR', 'BRUSH_CLAY', 'BRUSH_CLAY_STRIPS', 'BRUSH_CLONE', 'BRUSH_CREASE', 'BRUSH_FILL', 'BRUSH_FLATTEN', 'BRUSH_GRAB', 'BRUSH_INFLATE', 'BRUSH_LAYER', 'BRUSH_MASK', 'BRUSH_MIX', 'BRUSH_NUDGE', 'BRUSH_PINCH', 'BRUSH_SCRAPE', 'BRUSH_SCULPT_DRAW', 'BRUSH_SMEAR', 'BRUSH_SMOOTH', 'BRUSH_SNAKE_HOOK', 'BRUSH_SOFTEN', 'BRUSH_TEXDRAW', 'BRUSH_TEXFILL', 'BRUSH_TEXMASK', 'BRUSH_THUMB', 'BRUSH_ROTATE', 'GPBRUSH_SMOOTH', 'GPBRUSH_THICKNESS', 'GPBRUSH_STRENGTH', 'GPBRUSH_GRAB', 'GPBRUSH_PUSH', 'GPBRUSH_TWIST', 'GPBRUSH_PINCH', 'GPBRUSH_RANDOMIZE', 'GPBRUSH_CLONE', 'GPBRUSH_WEIGHT', 'GPBRUSH_PENCIL', 'GPBRUSH_PEN', 'GPBRUSH_INK', 'GPBRUSH_INKNOISE', 'GPBRUSH_BLOCK', 'GPBRUSH_MARKER', 'GPBRUSH_FILL', 'GPBRUSH_AIRBRUSH', 'GPBRUSH_CHISEL', 'GPBRUSH_ERASE_SOFT', 'GPBRUSH_ERASE_HARD', 'GPBRUSH_ERASE_STROKE', 'KEYTYPE_KEYFRAME_VEC', 'KEYTYPE_BREAKDOWN_VEC', 'KEYTYPE_EXTREME_VEC', 'KEYTYPE_JITTER_VEC', 'KEYTYPE_MOVING_HOLD_VEC', 'HANDLETYPE_FREE_VEC', 'HANDLETYPE_ALIGNED_VEC', 'HANDLETYPE_VECTOR_VEC', 'HANDLETYPE_AUTO_VEC', 'HANDLETYPE_AUTO_CLAMP_VEC', 'COLORSET_01_VEC', 'COLORSET_02_VEC', 'COLORSET_03_VEC', 'COLORSET_04_VEC', 'COLORSET_05_VEC', 'COLORSET_06_VEC', 'COLORSET_07_VEC', 'COLORSET_08_VEC', 'COLORSET_09_VEC', 'COLORSET_10_VEC', 'COLORSET_11_VEC', 'COLORSET_12_VEC', 'COLORSET_13_VEC', 'COLORSET_14_VEC', 'COLORSET_15_VEC', 'COLORSET_16_VEC', 'COLORSET_17_VEC', 'COLORSET_18_VEC', 'COLORSET_19_VEC', 'COLORSET_20_VEC', 'COLLECTION_COLOR_01', 'COLLECTION_COLOR_02', 'COLLECTION_COLOR_03', 'COLLECTION_COLOR_04', 'COLLECTION_COLOR_05', 'COLLECTION_COLOR_06', 'COLLECTION_COLOR_07', 'COLLECTION_COLOR_08', 'SEQUENCE_COLOR_01', 'SEQUENCE_COLOR_02', 'SEQUENCE_COLOR_03', 'SEQUENCE_COLOR_04', 'SEQUENCE_COLOR_05', 'SEQUENCE_COLOR_06', 'SEQUENCE_COLOR_07', 'SEQUENCE_COLOR_08', 'SEQUENCE_COLOR_09', 'LIBRARY_DATA_INDIRECT', 'LIBRARY_DATA_OVERRIDE_NONEDITABLE', 'EVENT_A', 'EVENT_B', 'EVENT_C', 'EVENT_D', 'EVENT_E', 'EVENT_F', 'EVENT_G', 'EVENT_H', 'EVENT_I', 'EVENT_J', 'EVENT_K', 'EVENT_L', 'EVENT_M', 'EVENT_N', 'EVENT_O', 'EVENT_P', 'EVENT_Q', 'EVENT_R', 'EVENT_S', 'EVENT_T', 'EVENT_U', 'EVENT_V', 'EVENT_W', 'EVENT_X', 'EVENT_Y', 'EVENT_Z', 'EVENT_SHIFT', 'EVENT_CTRL', 'EVENT_ALT', 'EVENT_OS', 'EVENT_F1', 'EVENT_F2', 'EVENT_F3', 'EVENT_F4', 'EVENT_F5', 'EVENT_F6', 'EVENT_F7', 'EVENT_F8', 'EVENT_F9', 'EVENT_F10', 'EVENT_F11', 'EVENT_F12', 'EVENT_ESC', 'EVENT_TAB', 'EVENT_PAGEUP', 'EVENT_PAGEDOWN', 'EVENT_RETURN', 'EVENT_SPACEKEY']
            # for icon in all_icons:
            #     try:
            #         properties_col.label(text=icon, icon=icon)
            #     except:
            #         pass

            if is_synced:
                #final_col = layout.column()
                properties_col.operator(ObjectBuildSettingsControl.bl_idname, text="Remove from Avatar Builder", icon="TRASH").command = 'REMOVE'


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
    sync_active_with_scene: BoolProperty(name="Sync with scene", default=True)

    def get_active(self) -> Union[ObjectBuildSettings, None]:
        settings = self.object_settings
        active_index = self.object_settings_active_index
        if settings:
            if 0 <= active_index < len(settings):
                return settings[active_index]
        else:
            return None

    def get_synced(self, scene: Scene) -> Union[ObjectBuildSettings, None]:
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
        shape_cos = shape_cos_dict.get(shape.name)
        if shape_cos is None:
            shape_cos = np.empty(len(shape.data), dtype=np.single)
            shape.data.foreach_get('co', shape_cos)
            shape_cos_dict[shape.name] = shape_cos
        return shape_cos

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
                obj.shape_key_remove(key_blocks[key_name])

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
                print(f"{mod.type} can be applied with shapes?: {can_apply_with_shapes}")
                can_apply_all_with_shapes &= can_apply_with_shapes
                mod_name_and_applicable_with_shapes.append((mod.name, can_apply_with_shapes))

        if shape_keys and not can_apply_all_with_shapes:
            if apply_modifiers == 'APPLY_FORCED':
                # Sync vertices to reference key
                reference_key_co = np.empty(3 * len(obj.data.vertices), dtype=np.single)
                obj.data.shape_keys.reference_key.data.foreach_get('co', reference_key_co)
                obj.data.vertices.foreach_set('co', reference_key_co)
                # Delete all shape keys
                obj.shape_key_clear()
            elif apply_modifiers == 'APPLY_KEEP_SHAPES_ADDON':
                raise RuntimeError("Apply with shapes is not yet implemented")
            elif apply_modifiers == 'APPLY_IF_POSSIBLE':
                print("filtering")
                # Create a filter to remove all those which can't be applied
                mod_name_and_applicable_with_shapes = filter(lambda t: t[1], mod_name_and_applicable_with_shapes)

        # For data transfer modifiers to work (and possibly some other modifiers), we must temporarily add the copied
        # object to the original (and active) scene
        original_scene.collection.objects.link(obj)
        try:
            for mod_name, _ in mod_name_and_applicable_with_shapes:
                print(f"Applying modifier {mod_name} to {repr(obj)}")
                bpy.ops.object.modifier_apply(context_override, modifier=mod_name)
        finally:
            # Unlink from the collection again
            original_scene.collection.objects.unlink(obj)

    # Remove other uv maps
    if settings.keep_only_uv_map:
        remove_all_uv_layers_except(obj, settings.keep_only_uv_map)

    # Remove non-deform vertex groups
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
        for vc in obj.data.vertex_colors:
            obj.data.vertex_colors.remove(vc)

    # Remove all but one material
    if settings.keep_only_material:
        only_material_name = settings.keep_only_material
        materials = obj.data.materials
        if only_material_name not in materials:
            raise ValueError(f"Could not find '{only_material_name}' in {repr(materials)}")
        # Iterate in reverse so that indices remain the same for materials we're yet to check
        for idx in reversed(range(len(materials))):
            material = materials[idx]
            if material.name != only_material_name:
                materials.pop(idx)

    # TODO: Remap materials
    pass


def build_armature(obj: Object, armature: Armature, settings: ObjectBuildSettings, copy_objects: list[Object]):
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
            for mod in copy_object.modifiers:
                if mod.type == 'ARMATURE' and mod.object == obj:
                    mod.use_deform_preserve_volume = True


class BuildAvatarOp(Operator):
    bl_idname = "build_avatar"
    bl_label = "Build Avatar"
    bl_description = "Build an avatar based on the meshes in the current scene, creating a new scene with the created avatar"

    @classmethod
    def poll(cls, context) -> bool:
        return ScenePropertyGroup.get_group(context.scene).get_active() is not None

    def execute(self, context) -> str:
        scene = context.scene
        active_scene_settings = ScenePropertyGroup.get_group(context.scene).get_active()

        export_scene_name = active_scene_settings.name
        export_scene = bpy.data.scenes.new(export_scene_name)
        export_scene_group = ScenePropertyGroup.get_group(export_scene)
        export_scene_group.is_export_scene = True
        export_scene_group.export_scene_source_scene = scene.name

        orig_object_to_copy = {}
        #old_object_to_copy_names = {}
        copy_objects = []
        if active_scene_settings.ignore_hidden_objects:
            objects_gen = scene.objects
        else:
            objects_gen = (o for o in scene.objects if not o.hide and not o.hide_viewport)

        for obj in objects_gen:
            object_settings = ObjectPropertyGroup.get_group(obj).get_synced(scene)
            if object_settings and object_settings.include_in_build:
                # Copy object
                copy_obj = obj.copy()
                copy_objects.append(copy_obj)

                # Store mapping from old to copy for easier access
                orig_object_to_copy[obj] = (copy_obj, object_settings)

                # Copy data (also will make single user any linked data)
                copy_obj.data = obj.data.copy()
                # Note that multiple objects can share the same data so there isn't guaranteed to be a 1-1 mapping from
                # old data to copy data

                # Add the object to the export scene (needed in order to join meshes)
                export_scene.collection.objects.link(copy_obj)

                # Currently, we don't copy Materials or any other data
                # We don't do anything else yet to ensure that we fully populate the dictionary before continuing

        # Operations within this loop must not cause Object ID blocks to be recreated
        for copy_obj, object_settings in orig_object_to_copy.values():
            # Set armature modifier objects to the copies
            for mod in copy_obj.modifiers:
                if mod.type == 'ARMATURE':
                    mod_object = mod.object
                    if mod_object and mod_object in orig_object_to_copy:
                        mod.object = orig_object_to_copy[mod_object][0]

            # Swap parents to copy objects
            orig_parent = copy_obj.parent
            if orig_parent:
                if orig_parent in orig_object_to_copy:
                    copy_obj.parent = orig_object_to_copy[orig_parent]
                else:
                    # Not actually sure what the FBX exporter does when the parent object isn't in the current scene
                    # If we can't just leave it alone, we could unparent (if we can use the operator, unparent with
                    # keep_transforms=True), otherwise we can raise an error
                    # TODO: If we need to do this, check the parents before creating any copy objects
                    raise ValueError(f"{copy_obj} is parented to {orig_parent} which isn't included in the avatar build")

            # Run build based on Object type
            if copy_obj.type == 'ARMATURE':
                build_armature(copy_obj, copy_obj.data, object_settings, copy_objects)
            elif copy_obj.type == 'MESH':
                build_mesh(scene, copy_obj, copy_obj.data, object_settings)

        # TODO: Join meshes by desired name and rename the combined mesh
        join_meshes = defaultdict(list)
        # Find the meshes for each name
        for orig_object, (copy_obj, object_settings) in orig_object_to_copy.items():
            if object_settings.target_mesh_name:
                name = object_settings.target_mesh_name
            else:
                # Otherwise, set to the original name
                name = orig_object.name
            join_meshes[name].append((copy_obj, object_settings))

        meshes_after_joining = []
        for name, objects_and_settings in join_meshes.items():
            objects = [o for o, s in objects_and_settings]
            if len(objects_and_settings) > 1:
                # Join the objects together
                # If any of the objects being joined were set to ignore
                joined_mesh_ignores_reduce_to_two = any(s.ignore_reduce_to_two_meshes for o, s in objects_and_settings)
                # TODO: Clean up all these comprehensions
                # TODO: Are there other things that we should ensure are set a specific way on the combined mesh?
                joined_mesh_autosmooth = any(o.data.use_auto_smooth for o in objects)
                combined_object = objects[0]
                bpy.ops.object.join({'selected_editable_objects': objects, 'active_object': combined_object,
                                     'scene': export_scene})
                combined_object.data.use_auto_smooth = joined_mesh_autosmooth
                meshes_after_joining.append((combined_object, joined_mesh_ignores_reduce_to_two))
            else:
                # There's only one object, so just get it
                combined_object = objects[0]
                meshes_after_joining.append((combined_object, objects_and_settings[0][1].ignore_reduce_to_two_meshes))

            # Since we're going to rename the joined copy objects, if an object with the corresponding name already exists,
            # and it doesn't have a target_mesh_name set, we need to set it to its current name because its name is about to
            # change
            existing_object: Object
            existing_object = bpy.data.objects.get(name)

            # Rename the combined mesh
            combined_object.name = name

            if existing_object:
                existing_object_group = ObjectPropertyGroup.get_group(existing_object)
                existing_object_settings = existing_object_group.object_settings
                # Get the object settings for the settings we're building with or create them if they don't exist
                existing_object_settings_for_scene: ObjectBuildSettings
                if active_scene_settings.name in existing_object_settings:
                    existing_object_settings_for_scene = existing_object_settings[active_scene_settings.name]
                else:
                    # Add the settings to the existing object
                    existing_object_settings_for_scene = existing_object_settings.add()
                    existing_object_settings_for_scene.name = active_scene_settings.name

                # Set the target mesh name to its original name
                if not existing_object_settings_for_scene.target_mesh_name:
                    existing_object_settings_for_scene.target_mesh_name = name

        # Join meshes based on whether they have shape keys
        # The ignore_reduce_to_two_meshes setting will need to only be True if it was True for all the joined meshes
        if active_scene_settings.reduce_to_two_meshes:
            shape_key_meshes = []
            # TODO: autosmooth settings
            shape_key_meshes_autosmooth = False
            non_shape_key_meshes = []
            non_shape_key_meshes_autosmooth = False

            for mesh_obj, ignore_reduce_to_two in meshes_after_joining:
                # Individual meshes can exclude themselves from this operation
                if not ignore_reduce_to_two:
                    if mesh_obj.data.shape_keys:
                        shape_key_meshes.append(mesh_obj)
                    else:
                        non_shape_key_meshes.append(mesh_obj)

            # TODO: Join the meshes and rename the resulting mesh according to the scene settings.
            #  If an object already exists with the target name, set that object's
            #  existing_object_settings_for_scene.target_mesh_name to the target name if it hasn't been set to something

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
    ObjectBuildSettingsControl,
    ObjectBuildSettingsUIList,
    ObjectBuildSettings,
    ObjectPropertyGroup,
    ObjectPanel,
    BuildAvatarOp,
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
            except Exception:
                print("unregistering previous version failed, continuing")
        # Set unregister function on WindowManager
        # TODO: Make sure this isn't saved in blend files or otherwise persisted
        bpy.types.WindowManager.mysteryem_test_unregister = unregister
    # Register everything here
    _register_classes()
    _register_props()


def unregister(is_test=True):
    if is_test:
        # noinspection PyUnresolvedReferences
        del bpy.types.WindowManager.mysteryem_test_unregister
    # Unregister everything here
    _unregister_props()
    _unregister_classes()


# Test from the editor
if __name__ == '__main__':
    register(is_test=True)