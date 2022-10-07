import numpy as np
from typing import Union
from collections import defaultdict
from dataclasses import dataclass
import bpy
from bpy.types import Object, ShapeKey, Mesh, Operator, Modifier, MeshUVLoopLayer, Scene, Armature, ArmatureModifier
from .extensions import ObjectBuildSettings, ObjectPropertyGroup, ScenePropertyGroup
from .integration import check_gret_shape_key_apply_modifiers
from .registration import register_module_classes_factory


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
    me = mesh_obj.data
    if isinstance(me, Mesh):
        mesh_uv_layers = me.uv_layers
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


def run_gret_shape_key_apply_modifiers(obj: Object, modifier_names_to_apply: set[str]):
    gret_check = check_gret_shape_key_apply_modifiers()
    if gret_check == 'keep_modifiers':
        # Older version, applies all non-disabled modifiers and modifiers not in our list
        # Temporarily disable all other modifiers, run the operator and then restore the modifiers that were temporarily
        # disabled
        mods_to_enable = []
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
            # noinspection PyUnresolvedReferences
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

    # Optionally remove disabled modifiers
    if settings.remove_disabled_modifiers:
        modifiers = obj.modifiers
        mod: Modifier
        for mod in obj.modifiers:
            if not mod.show_viewport:
                modifiers.remove(mod)

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
            if isinstance(mod, ArmatureModifier) and mod.use_vertex_groups:
                if mod.object and isinstance(mod.object.data, Armature):
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
            copy_data = obj.data.copy()
            copy_obj.data = copy_data

            # Remove drivers from copy
            copy_obj.animation_data_clear()
            copy_data.animation_data_clear()
            if isinstance(copy_data, Mesh):
                shape_keys = copy_data.shape_keys
                if shape_keys:
                    shape_keys.animation_data_clear()


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


register, unregister = register_module_classes_factory(__name__, globals())