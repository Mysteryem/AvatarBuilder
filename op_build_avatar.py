import numpy as np
import re
from typing import Union, Optional, AnyStr, Callable, Literal, cast, Iterable
from collections import defaultdict
from dataclasses import dataclass
import itertools
import functools

import bpy
from bpy.types import (
    Armature,
    ArmatureModifier,
    Context,
    Key,
    Material,
    Mesh,
    MeshUVLoopLayer,
    Modifier,
    Object,
    Scene,
    ShapeKey,
    ViewLayer,
    BlendData,
    PoseBone,
    Operator,
)

from .extensions import (
    ArmatureSettings,
    MaterialSettings,
    MeshSettings,
    ModifierSettings,
    ObjectBuildSettings,
    ObjectPropertyGroup,
    SceneBuildSettings,
    ScenePropertyGroup,
    ShapeKeyOp,
    ShapeKeySettings,
    UVSettings,
    VertexColorSettings,
    VertexGroupSettings,
    SceneFixSettings,
)
from .integration_gret import run_gret_shape_key_apply_modifiers
from .integration_pose_library import apply_legacy_pose_marker, apply_pose_from_pose_action
from .registration import register_module_classes_factory, OperatorBase
from . import utils
from .util_generic_bpy_typing import PropCollection
from .version_compatibility import LEGACY_POSE_LIBRARY_AVAILABLE, ASSET_BROWSER_AVAILABLE, get_vertex_colors
from .tools.apply_mmd_mappings import mmd_remap


def merge_shapes_into_first(mesh_obj: Object, shapes_to_merge: list[tuple[ShapeKey, list[ShapeKey]]]):
    # We only update/remove shapes at the end, to avoid issues when some shapes are relative to other shapes being
    # merged or merged into

    @functools.cache
    def get_shape_cos(shape):
        cos = np.empty(3 * len(shape.data), dtype=np.single)
        shape.data.foreach_get('co', cos)
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
        shape_iter = iter(shapes)
        first_vg = next(shape_iter).vertex_group
        all_shapes_have_same_vertex_group = all(shape.vertex_group == first_vg for shape in shape_iter)
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


def remove_all_uv_layers_except(me: Mesh, *uv_layers: Union[str, MeshUVLoopLayer]):
    mesh_uv_layers = me.uv_layers
    # Indices are iterated in reverse, so that when a uv layer is removed, the remaining indices remain unchanged
    indices_to_remove = reversed(range(len(mesh_uv_layers)))
    if uv_layers:
        # Find the indices of the layers we want to keep
        uv_layer_idx_to_keep = set()
        for uv_layer in uv_layers:
            if isinstance(uv_layer, MeshUVLoopLayer):
                uv_layer = uv_layer.name
            uv_layer_index = mesh_uv_layers.find(uv_layer)
            uv_layer_idx_to_keep.add(uv_layer_index)
        # Filter out the indices of layers we want to keep
        indices_to_remove = (i for i in indices_to_remove if i not in uv_layer_idx_to_keep)
    for i in indices_to_remove:
        mesh_uv_layers.remove(mesh_uv_layers[i])


def smart_delete_shape_keys(obj: Object, shape_keys: Key, to_delete: set[ShapeKey]):
    """Delete shape keys and adjust any shape keys relative to or recursively relative to the deleted shape keys"""
    reference_key = shape_keys.reference_key
    if reference_key in to_delete:
        raise ValueError("Reference key cannot be deleted safely using Shape Key ops")

    # Any shapes not being deleted that are relative to a shape that is being deleted need to have their relative key
    # changed to a shape that isn't being deleted. In order to make this change, the relative movement of the shape key
    # needs to be retargeted for the new relative key (automatically set to the reference key if we don't set it
    # ourselves).
    reverse_relative_shapes = utils.ReverseRelativeShapeKeyMap(shape_keys)
    # Avoid creating the arrays unless we actually need them, in-case the mesh being operated on is very large
    reference_co = None
    shape_co = None
    to_delete_co = None
    co_length = len(reference_key.data) * 3
    co_dtype = np.single
    for shape_to_delete in to_delete:
        # Get all shapes keys relative to or recursively relative to the shape being deleted
        shapes_relative_to = reverse_relative_shapes.get_relative_recursive_keys(shape_to_delete)
        # Exclude any shapes that we're also going to be deleting to minimise the amount of work we need to do
        shapes_needing_modification = shapes_relative_to - to_delete

        if shapes_needing_modification:
            # Movement of a shape, s = s - s.relative_key
            #   m(s) = s - s.r
            # When we delete s.r, the new relative_to shape will become the reference key
            #   m(s') = s - ref
            # To keep the movement the same, we need to add some amount, x, to the shape, s
            #   s - s.r = s + x - ref
            # Rearranging
            #   -s.r = x - ref
            #   x = ref - s.r
            # Note that s.r is shape_to_delete, so the amount to add to s is
            #   ref - shape_to_delete

            # Get the co (vertex coordinates) for the reference shape key
            # Since it doesn't change, we only need to get it once
            if reference_co is None:
                reference_co = np.empty(co_length, dtype=co_dtype)
                reference_key.data.foreach_get('co', reference_co)

            # Create the array for storing the difference between the shape's relative key and its new relative key
            # (the reference key). This array will be re-used for each shape key to delete.
            if to_delete_co is None:
                to_delete_co = np.empty(co_length, dtype=co_dtype)

            # Create the array for storing the co of the shape key being modified. This array will be re-used for each
            # shape key relative to the shape key to delete.
            if shape_co is None:
                shape_co = np.empty(co_length, dtype=co_dtype)

            # Get the co of the shape to delete
            shape_to_delete.data.foreach_get('co', to_delete_co)

            # Get the difference between the reference key and the shape to delete (and store it into to_delete_co,
            # since we won't need its value again)
            difference_co = np.subtract(reference_co, to_delete_co, out=to_delete_co)
            for shape_to_modify in shapes_needing_modification:
                # Get the co of the shape
                shape_to_modify.data.foreach_get('co', shape_co)
                # Add the difference between the reference key and the shape's relative key (or recursively relative
                # key)
                shape_co += difference_co
                # Set the shape key to the updated co
                shape_to_modify.data.foreach_set('co', shape_co)

    # Delete the shape keys now that we're done using them, to avoid any issues where we might try to use a shape key
    # that we've already deleted
    for shape in to_delete:
        # Removing the shape will automatically set shape keys that were relative to it, to be relative to the reference
        # key instead
        obj.shape_key_remove(shape)


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


# TODO: Rename this function to be shorter
def set_build_name_for_existing_object_about_to_be_renamed(name: str):
    existing_object: Object = bpy.data.objects.get(name)
    if existing_object:
        existing_object_group = ObjectPropertyGroup.get_group(existing_object)
        existing_object_settings = existing_object_group.collection
        # Iterate through all the build settings on this object, if they don't have a target object name set, then they
        # would have been using the object's name instead. Since the object's name is about to be changed, the target
        # object name must be set in order for build behaviour to remain the same.
        object_build_settings: ObjectBuildSettings
        for object_build_settings in existing_object_settings:
            if not object_build_settings.general_settings.target_object_name:
                object_build_settings.general_settings.target_object_name = name


_ZERO_ROTATION_QUATERNION = np.array([1, 0, 0, 0], dtype=np.single)


def reset_pose_bones(bones: PropCollection[PoseBone], update_tag=True):
    num_bones = len(bones)
    # 3 components: X, Y, Z, set each bone to (0,0,0)
    bones.foreach_set('location', np.zeros(num_bones * 3, dtype=np.single))
    # 3 components: X, Y, Z, set each bone to (1,1,1)
    bones.foreach_set('scale', np.ones(num_bones * 3, dtype=np.single))
    # 4 components: W, X, Y, Z, set each bone to (1, 0, 0, 0)
    bones.foreach_set('rotation_quaternion', np.tile(_ZERO_ROTATION_QUATERNION, num_bones))
    if update_tag:
        # Mark that the owning ID of the PoseBones bpy_prop_collection (should always be an Object), needs to update its
        # display data following our changes to the pose bones
        bones.id_data.update_tag()


def do_build_modifiers(obj: Object):
    do_remove_disabled = False
    for mod in obj.modifiers:
        if mod.type != 'ARMATURE':
            if mod.show_viewport:
                return True, True
            else:
                do_remove_disabled = True
    return do_remove_disabled, False


@dataclass
class ObjectHelper:
    """Helper class"""
    orig_object: Object
    orig_object_name: str
    settings: ObjectBuildSettings
    desired_name: str
    copy_object: Optional[Object] = None
    joined_settings_ignore_reduce_to_two_meshes: Optional[bool] = None

    def to_join_sort_key(self) -> Union[tuple[int, int, str], tuple[int, str]]:
        """Ordering for joining objects together"""
        # settings.join_order is likely to be the same for most objects being sorted, so we have to provide additional
        # deterministic ordering for when .join_order is the same
        #
        # orig_object_name should be unique per helper and have been set directly from an Object's .name, which is
        # guaranteed to be unique, so the by including it in the sort key tuple, the entire tuple should therefore be unique
        orig_data = self.orig_object.data
        if isinstance(orig_data, Mesh):
            # By including the number of shape keys in the sort key, the user can prepare one mesh with all shape keys in
            # the desired order, then, when being joined with other meshes, they will all be joined into that one mesh with
            # all the shape keys, maintaining the user's desired shape key order.
            shape_keys = orig_data.shape_keys
            if shape_keys:
                # We negate the number of shape keys because we want the meshes with the most shape keys to be sorted first
                shape_key_ordering = -len(shape_keys.key_blocks)
            else:
                shape_key_ordering = 0
            return self.settings.general_settings.join_order, shape_key_ordering, self.orig_object_name
        else:
            # Not a Mesh, which currently means it must be an Armature, which doesn't have shape keys.
            # Attempting to join Objects of different types is an error, so we won't include a dummy value for shape key
            # ordering.
            return self.settings.general_settings.join_order, self.orig_object_name

    def init_copy(self, export_scene: Scene):
        """Create and initialise the copy object"""
        obj = self.orig_object
        # Copy object
        copy_obj = obj.copy()
        self.copy_object = copy_obj

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

        # TODO: Do we need to make the copy objects visible at all, or will they automatically not be hidden in the
        #  export scene's view_layer?
        # Add the copy object to the export scene (needed in order to join meshes)
        export_scene.collection.objects.link(copy_obj)

        # Currently, we don't copy Materials or any other data
        # We don't do anything else to each copy object yet to ensure that we fully populate the dictionary before
        # continuing as some operations will need to get the copy obj of an original object that they are related to
        return copy_obj


@dataclass
class ValidatedBuild:
    """Helper class"""
    export_scene_name: str
    orig_object_to_helper: dict[Object, ObjectHelper]
    desired_name_meshes: dict[str, list[ObjectHelper]]
    desired_name_armatures: dict[str, list[ObjectHelper]]
    shape_keys_mesh_name: str
    no_shape_keys_mesh_name: str

    @property
    def objects_for_build(self):
        return self.orig_object_to_helper.values()


_DATA_LOOKUP: dict[type, Callable[[], PropCollection]] = {
    # References to the collections in bpy.data can become invalidated when doing certain operations, such as undo/redo,
    # so we don't store them directly and instead store lambdas to get them
    Mesh: (lambda: bpy.data.meshes),
    Armature: (lambda: bpy.data.armatures),
}


def _prepare_custom_normals_for_joining(combined_obj: Object, joining_obj: Object,
                                        calling_op: Optional[Operator] = None):
    if combined_obj.type != 'MESH' or joining_obj.type != 'MESH':
        # This shouldn't happen because we're checking that we're joining meshes before calling this function
        raise ValueError("combined_obj and joining_obj must both be mesh Objects (Object.type == 'MESH'")
    joining_mesh = cast(Mesh, joining_obj.data)
    if not joining_mesh.has_custom_normals:
        # Nothing to do because the joining_mesh does not have custom normals
        return
    # Joining object will become the scale of combined_scale when it joins
    combined_scale = combined_obj.scale
    joining_scale = joining_obj.scale
    if combined_scale == joining_scale:
        # Nothing to do because the scale of both objects is the same
        return

    # TODO: Loses precision when the combined mesh has one axis very small (this might just be a limitation of single
    #  precision floats being used to store normals)
    scale_multiplier = np.array(combined_scale, dtype=np.single) / np.array(joining_scale, dtype=np.single)
    if not np.all(np.isfinite(scale_multiplier)):
        # Can't proceed, division by zero has occurred
        # Technically, we could probably adjust only the axes that do not have a scale of zero
        # For now, we won't raise
        message = (
            f"Can't join {joining_obj!r} into {combined_obj!r} and maintain custom normals due to {joining_obj!r}"
            f" having a scale of 0 on at least one axis (scale is {joining_obj.scale})!"
        )
        if calling_op is not None:
            calling_op.report({'WARNING'}, message)
        else:
            print(message)
        return
    # While we actually divided the components of combined_scale by the components of joining_scale, since division is
    # just multiplication by the reciprocal, the sign of the result from multiplying the components instead will be the
    # same as dividing.
    # There is a special case when one of the components of combined_scale is zero, since the product will then be zero.
    # Currently, this is allowed, though is unlikely to happen due to how little use there is for mesh objects that have
    # been scaled to zero on at least one axis. Additionally, the normals of such an object are likely to be a mess
    # anyway.
    negative_scale_product = np.prod(scale_multiplier) < 0
    if negative_scale_product:
        # FIXME: Doesn't work when the product of the components of the combined and joining object scales is negative.
        #  Not sure what to do here.
        #  Note that faces will need to be flipped somewhere along this process to counteract them being flipped due to
        #   the join operator.
        #  It might be that because the flipping reverses polygon vertex order (does it?), we would also have to reverse
        #   the order of the split normals for each polygon too?
        #  Or maybe flipping polygons results in some other changes to loops?
        #  Note: See how flipping individual polygons flips the split normals for that polygon, do we therefore have to
        #   flip our custom normals about the plane of the normal of the polygon? It looks like it's just a negation
        #   though?
        message = (
            f"Can't join {joining_obj!r} into {combined_obj!r} and maintain custom normals due to product of their"
            f" components being negative!"
        )
        if calling_op is not None:
            calling_op.report({'WARNING'}, message)
        else:
            print(message)
        return
    #
    # Calculate split normals so we can read them from loops
    joining_mesh.calc_normals_split()
    #
    num_loops = len(joining_mesh.loops)
    current_split_normals = np.empty(num_loops * 3, dtype=np.single)
    joining_mesh.loops.foreach_get('normal', current_split_normals)
    # Change viewed shape so each index corresponds to a vector
    current_split_normals.shape = (num_loops, 3)

    # Multiply
    current_split_normals *= np.abs(scale_multiplier)

    # Now normalize the resulting vectors:
    # When the divisor is zero, it means the vector was (0,0,0), in which case, we do nothing,
    # otherwise, we divide the original vector
    # normalized(v) = v/|v| = v/magnitude(v)
    # 2-norm gets us euclidean distance, a.k.a. magnitude
    magnitude_per_v = np.linalg.norm(current_split_normals, axis=1, keepdims=True)
    # np.where tends to be faster than indexing to get only the subset that is normalizable and then updating that
    # subset
    #  normalizable = magnitude_per_v != 0
    #  current_split_normals[normalizable] = current_split_normals[normalizable] / magnitude_per_v
    normalized = np.where(magnitude_per_v == 0, current_split_normals, current_split_normals / magnitude_per_v)
    joining_mesh.normals_split_custom_set(normalized)


def join_objects(object_type: Literal[Mesh, Armature], sorted_object_helpers: list[ObjectHelper], export_scene: Scene,
                 calling_op: Optional[Operator] = None) -> ObjectHelper:
    if not sorted_object_helpers:
        raise ValueError("At least one ObjectHelper must be provided")
    collection = _DATA_LOOKUP[object_type]()

    objects = [helper.copy_object for helper in sorted_object_helpers]
    combined_object_helper = sorted_object_helpers[0]

    if len(objects) > 1:
        combined_object = combined_object_helper.copy_object

        # The data of the objects that join the combined object get left behind, we'll delete them and do so
        # safely in-case Blender decides to delete them in the future
        data_names_to_remove = [o.data.name for o in objects[1:]]

        if object_type == Mesh:
            # If any of the objects being joined were set to ignore, the combined mesh will be too
            ignore_reduce_to_two = any(
                h.settings.mesh_settings.ignore_reduce_to_two_meshes for h in sorted_object_helpers)
            combined_object_helper.joined_settings_ignore_reduce_to_two_meshes = ignore_reduce_to_two

            # TODO: Clean up all these comprehensions
            # TODO: Are there other things that we should ensure are set a specific way on the combined mesh?
            joined_mesh_autosmooth = any(cast(Mesh, o.data).use_auto_smooth for o in objects)

            # Set mesh autosmooth if any of the joined meshes used it
            combined_object.data.use_auto_smooth = joined_mesh_autosmooth

            # TODO: Add an option in an 'advanced settings' section of the SceneBuildSettings that allows this feature
            #  to be turned off, since it's technically different behaviour to Blender by default.
            # If the scale differs between an object being joined and the combined object, if the object being joined
            # has custom normals, Blender won't adjust them for the new scale. Fortunately, in most cases, we can adjust
            # them ourselves.
            for obj in objects[1:]:
                _prepare_custom_normals_for_joining(combined_object, obj, calling_op)

        # Join the objects
        context_override = {
            'selected_editable_objects': objects,
            'active_object': combined_object,
            'scene': export_scene
        }
        utils.op_override(bpy.ops.object.join, context_override)

        # Delete the data of the objects other than the final combined object
        for name in data_names_to_remove:
            data_by_name = collection.get(name)
            if data_by_name:
                collection.remove(data_by_name)

    return combined_object_helper


def join_objects_with_rename(combined_name: str, object_type: Literal[Mesh, Armature],
                             sorted_object_helpers: list[ObjectHelper], export_scene: Scene,
                             calling_op: Optional[Operator] = None) -> ObjectHelper:
    combined_object_helper = join_objects(object_type, sorted_object_helpers, export_scene, calling_op)

    # Since we're going to rename the joined copy objects, if an object with the corresponding name already
    # exists, and it doesn't have a target_object_name set, we need to set it to its current name because
    # its name is about to change
    set_build_name_for_existing_object_about_to_be_renamed(combined_name)

    # Rename the combined mesh
    combined_object_helper.copy_object.name = combined_name

    return combined_object_helper


def join_objects_with_renames(join_dict: dict[str, list[ObjectHelper]], object_type: Literal[Mesh, Armature],
                              export_scene: Scene, calling_op: Optional[Operator] = None) -> list[ObjectHelper]:
    return [
        join_objects_with_rename(name, object_type, object_helpers, export_scene, calling_op)
        for name, object_helpers in join_dict.items()
    ]


_SHAPE_MERGE_LIST = list[tuple[ShapeKey, list[ShapeKey]]]


class BuildAvatarOp(OperatorBase):
    bl_idname = "build_avatar"
    bl_label = "Build Avatar"
    bl_description = "Build an avatar based on the meshes in the current scene, creating a new scene with the created avatar"
    bl_options = {'REGISTER', 'UNDO'}

    def _shape_key_op_delete(self, obj: Object, op: ShapeKeyOp, op_type: str, shape_keys: Key,
                             available_key_blocks: set[ShapeKey]):
        key_blocks = shape_keys.key_blocks
        keys_to_delete = set()
        if op_type == ShapeKeyOp.DELETE_SINGLE:
            key_name = op.pattern
            if key_name in key_blocks:
                keys_to_delete = {key_blocks[key_name]}
        elif op_type == ShapeKeyOp.DELETE_AFTER:
            delete_after_index = key_blocks.find(op.delete_after_name)
            if delete_after_index != -1:
                keys_to_delete = set(key_blocks[delete_after_index + 1:])
        elif op_type == ShapeKeyOp.DELETE_BEFORE:
            delete_before_index = key_blocks.find(op.delete_before_name)
            if delete_before_index != -1:
                # Start from 1 to avoid including the reference key
                keys_to_delete = set(key_blocks[1:delete_before_index])
        elif op_type == ShapeKeyOp.DELETE_BETWEEN:
            delete_after_index = key_blocks.find(op.delete_after_name)
            delete_before_index = key_blocks.find(op.delete_before_name)
            if delete_after_index != -1 and delete_before_index != -1:
                keys_to_delete = set(key_blocks[delete_after_index + 1:delete_before_index])
        elif op_type == ShapeKeyOp.DELETE_REGEX:
            pattern_str = op.pattern
            if pattern_str:
                try:
                    pattern = re.compile(pattern_str)
                    keys_to_delete = {k for k in key_blocks if pattern.fullmatch(k.name) is not None}
                except re.error as err:
                    self.report({'WARNING'}, f"Regex error for '{pattern_str}' on {obj!r} for"
                                             f" {ShapeKeyOp.DELETE_REGEX}:\n"
                                             f"\t{err}")

        # Limit the deleted keys to those available
        keys_to_delete.intersection_update(available_key_blocks)

        # Remove all the shape keys being deleted, automatically adjusting any shape keys relative to or recursively
        # relative the shape keys being deleted
        smart_delete_shape_keys(obj, shape_keys, keys_to_delete)

    @staticmethod
    def _common_before_delimiter(name: str, delimiter: str) -> str:
        """Get the common part before a delimiter. If the delimiter is not found, returns the input string"""
        before, _found_delimiter, _after = name.partition(delimiter)
        # Note that if the delimiter is not found, before will contain the original string. We
        # include this so that "MyShape" can combine with "MyShape_adjustments" when the
        # delimiter is "_"
        return before

    @staticmethod
    def _common_after_delimiter(name: str, delimiter: str) -> str:
        """Get the common part after a delimiter. If the delimiter is not found, returns the input string"""
        _before, found_delimiter, after = name.partition(delimiter)
        if found_delimiter:
            return after
        else:
            # When the delimiter is not found, we will consider the common part to be the original
            # string, so that "MyShape" can be merged with "adjust.MyShape" when the delimiter is
            # "."
            return name

    def _shape_key_op_merge_all(self, op: ShapeKeyOp, op_type: str, key_blocks_to_search: Iterable[ShapeKey]
                                ) -> _SHAPE_MERGE_LIST:
        merge_lists: _SHAPE_MERGE_LIST = []
        matched: list[ShapeKey] = []
        matched_grouped: dict[Union[str, tuple[AnyStr, ...]], list[ShapeKey]] = defaultdict(list)
        if op_type == ShapeKeyOp.MERGE_PREFIX:
            prefix = op.pattern
            if prefix:
                matched = [shape for shape in key_blocks_to_search if shape.name.startswith(prefix)]
        elif op_type == ShapeKeyOp.MERGE_SUFFIX:
            suffix = op.pattern
            if suffix:
                matched = [shape for shape in key_blocks_to_search if shape.name.endswith(suffix)]
        elif op_type == ShapeKeyOp.MERGE_REGEX:
            pattern_str = op.pattern
            if pattern_str:
                try:
                    pattern = re.compile(pattern_str)
                    if pattern.groups:
                        # If the pattern contains groups, they need to match too
                        for key in key_blocks_to_search:
                            name = key.name
                            match = pattern.fullmatch(name)
                            if match:
                                # Create key from all capture groups, so that if capture groups are used, they
                                # must match
                                matched_grouped[match.groups()].append(key)
                    else:
                        matched = [k for k in key_blocks_to_search if pattern.fullmatch(k.name)]
                except re.error as err:
                    self.report({'WARNING'}, f"Regex error for '{pattern_str}' for {ShapeKeyOp.MERGE_REGEX}:\n"
                                             f"\t{err}")
        elif op_type == ShapeKeyOp.MERGE_COMMON_BEFORE_DELIMITER:
            delimiter = op.pattern
            if delimiter:
                for key in key_blocks_to_search:
                    matched_grouped[self._common_before_delimiter(key.name, delimiter)].append(key)
        elif op_type == ShapeKeyOp.MERGE_COMMON_AFTER_DELIMITER:
            delimiter = op.pattern
            if delimiter:
                for key in key_blocks_to_search:
                    matched_grouped[self._common_after_delimiter(key.name, delimiter)].append(key)

        # Only one of the data structures we declared will actually be used, but we'll check them both for
        # simplicity
        for shapes_to_merge in itertools.chain([matched], matched_grouped.values()):
            if len(shapes_to_merge) > 1:
                # The shapes in each list are going to be merged into the first shape of the list
                merge_lists.append((shapes_to_merge[0], shapes_to_merge[1:]))

        return merge_lists

    @staticmethod
    def _shape_key_op_merge_consecutive_compare(compare_func: Callable[[str, str], bool], op: ShapeKeyOp,
                                                matched_consecutive: list, key_blocks_to_search: Iterable[ShapeKey]):
        compare_against = op.pattern
        if compare_against:
            previous_shape_matched = False
            current_merge_list = None
            for shape in key_blocks_to_search:
                current_shape_matches = compare_func(shape.name, compare_against)
                if current_shape_matches:
                    if not previous_shape_matched:
                        # Create a new merge list
                        current_merge_list = []
                        matched_consecutive.append(current_merge_list)
                    # Add to the current merge list
                    current_merge_list.append(shape)
                # Update for the next shape in the list
                previous_shape_matched = current_shape_matches

    @staticmethod
    def _delimiter_match_consecutive(common_part_func: Callable[[str, str], str], op: ShapeKeyOp,
                                     matched_consecutive: list, key_blocks_to_search: Iterable[ShapeKey]):
        delimiter = op.pattern
        if delimiter:
            previous_common_part = None
            current_merge_list = None
            for key in key_blocks_to_search:
                name = key.name
                common_part = common_part_func(name, delimiter)
                if common_part != previous_common_part:
                    # Create a new merge list
                    current_merge_list = []
                    matched_consecutive.append(current_merge_list)
                    # Set the previous_common_part to the new, different common_part, for the next iteration
                    previous_common_part = common_part
                # Add to the current merge list
                current_merge_list.append(key)

    def _shape_key_op_merge_consecutive(self, op: ShapeKeyOp, op_type: str, key_blocks_to_search: Iterable[ShapeKey]
                                        ) -> _SHAPE_MERGE_LIST:
        # Similar to 'ALL', but check against the previous and create a new sub-list each time the previous
        # didn't match
        merge_lists: _SHAPE_MERGE_LIST = []
        matched_consecutive = []
        if op_type == ShapeKeyOp.MERGE_PREFIX:
            # PyCharm bug. It thinks str.startswith doesn't match Callable[[str,str], bool]
            # noinspection PyTypeChecker
            self._shape_key_op_merge_consecutive_compare(str.startswith,
                                                         op, matched_consecutive, key_blocks_to_search)
        elif op_type == ShapeKeyOp.MERGE_SUFFIX:
            # PyCharm bug. It thinks str.endswith doesn't match Callable[[str,str], bool]
            # noinspection PyTypeChecker
            self._shape_key_op_merge_consecutive_compare(str.endswith,
                                                         op, matched_consecutive, key_blocks_to_search)
        elif op_type == ShapeKeyOp.MERGE_REGEX:
            pattern_str = op.pattern
            if pattern_str:
                try:
                    pattern = re.compile(pattern_str)
                except re.error as err:
                    self.report({'WARNING'}, f"Regex error for '{pattern_str}' for {ShapeKeyOp.MERGE_REGEX}:\n"
                                             f"\t{err}")
                    return []

                previous_shape_match: Optional[re.Match] = None
                current_merge_list = None
                for key in key_blocks_to_search:
                    name = key.name
                    match = pattern.fullmatch(name)
                    if match:
                        if not previous_shape_match or previous_shape_match.groups() != match.groups():
                            # If the previous shape key didn't match, or it did, but the groups of the
                            # match are different to the current match, create a new merge list.
                            # If the pattern has no capture groups, then .groups() will be an empty tuple
                            current_merge_list = []
                            matched_consecutive.append(current_merge_list)
                        # Add to the current merge list
                        current_merge_list.append(key)
                    # Update for the next shape in the list
                    previous_shape_match = match
        elif op_type == ShapeKeyOp.MERGE_COMMON_BEFORE_DELIMITER:
            self._delimiter_match_consecutive(self._common_before_delimiter,
                                              op, matched_consecutive, key_blocks_to_search)
        elif op_type == ShapeKeyOp.MERGE_COMMON_AFTER_DELIMITER:
            self._delimiter_match_consecutive(self._common_after_delimiter,
                                              op, matched_consecutive, key_blocks_to_search)

        # Collect all lists of shapes to merge that have more than one element into merge_lists
        for shapes_to_merge in matched_consecutive:
            if len(shapes_to_merge) > 1:
                merge_lists.append((shapes_to_merge[0], shapes_to_merge[1:]))

        return merge_lists

    def _shape_key_op_merge(self, obj: Object, op: ShapeKeyOp, op_type: str, key_blocks: PropCollection[ShapeKey],
                            available_key_blocks: set[ShapeKey]):
        grouping = op.merge_grouping

        # Collect all the shapes to be merged into a common dictionary format that the merge function uses
        # The first shape in each list will be picked as the shape that the other shapes in the list should be
        # merged into
        # We will skip any lists that don't have more than one element since merging only happens with two or
        # more shapes
        merge_lists: list[tuple[ShapeKey, list[ShapeKey]]] = []

        # Skip the reference shape and any other ignored shape keys
        key_blocks_to_search = (k for k in key_blocks[1:] if k in available_key_blocks)

        if grouping == 'ALL':
            merge_lists = self._shape_key_op_merge_all(op, op_type, key_blocks_to_search)
        elif grouping == 'CONSECUTIVE':
            merge_lists = self._shape_key_op_merge_consecutive(op, op_type, key_blocks_to_search)

        # Merge all the specified shapes
        merge_shapes_into_first(obj, merge_lists)

    def build_mesh_shape_key_op(self, obj: Object, shape_keys: Key, op: ShapeKeyOp):
        # TODO: Replace ignore_regex with 'IGNORE_' ops. See ShapeKeyOp comments for details. Note that key_blocks would
        #  need to be passed between subsequent calls to this function in that case.
        key_blocks = shape_keys.key_blocks

        ignore_regex = op.ignore_regex
        if ignore_regex:
            try:
                ignore_pattern = re.compile(ignore_regex)
                available_key_blocks = {k for k in key_blocks if ignore_pattern.fullmatch(k.name) is None}
            except re.error as err:
                # TODO: Check patterns in advance for validity, see ShapeKeyOp comments for details
                self.report({'WARNING'}, f"Regex error occurred for ignore_regex '{ignore_regex}' on {obj!r}:\n"
                                         f"\t{err}")
                available_key_blocks = set(key_blocks)
        else:
            available_key_blocks = set(key_blocks)

        if key_blocks:
            op_type = op.type
            if op_type in ShapeKeyOp.DELETE_OPS_DICT:
                self._shape_key_op_delete(obj, op, op_type, shape_keys, available_key_blocks)
            elif op_type in ShapeKeyOp.MERGE_OPS_DICT:
                self._shape_key_op_merge(obj, op, op_type, key_blocks, available_key_blocks)

    def build_mesh_shape_keys(self, obj: Object, me: Mesh, settings: ShapeKeySettings, fixes: SceneFixSettings):
        """Note that this function may invalidate old references to Mesh.shape_keys as it may delete them entirely"""
        shape_keys = me.shape_keys
        if shape_keys:
            key_blocks = shape_keys.key_blocks
            main_op = settings.shape_keys_main_op
            if main_op == 'APPLY_MIX':
                # Delete shape keys, setting the mesh vertices to the current mix of all shape keys
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
                return
            elif main_op == 'CUSTOM':
                for op in settings.shape_key_ops.collection:
                    self.build_mesh_shape_key_op(obj, shape_keys, op)
            elif main_op == 'KEEP':
                # Nothing to do
                pass

            if fixes.sync_mesh_vertices_to_reference_key:
                # Copy reference key co to the vertices to avoid desync between the vertices and reference key, this is
                # especially important when exporting an FBX (it uses mesh vertices positions and not reference key
                # positions) or when deleting all shape keys (the mesh will go back to the shape specified by the vertex
                # positions).
                # This can be a lot of data to copy for huge meshes, but it is reasonably fast since no iteration is
                # required in either Python (due to the use of foreach_get/set) or C (due to the use of a buffer object
                # with the same C type as the 'co' data).
                reference_key_co = np.empty(3 * len(me.vertices), dtype=np.single)
                shape_keys.reference_key.data.foreach_get('co', reference_key_co)
                me.vertices.foreach_set('co', reference_key_co)

            # If there is only the reference shape key left, remove it
            # This will allow for most modifiers to be applied, compared to when there is just the reference key
            if main_op == 'DELETE_ALL' or len(key_blocks) == 1:
                # Remove all shape keys
                # Note that this will invalidate any existing references to me.shape_keys
                obj.shape_key_clear()

    def build_mesh_uvs(self, obj: Object, me: Mesh, settings: UVSettings, fixes: SceneFixSettings):
        uv_layers = me.uv_layers
        # Remove all but the specified uv maps
        if uv_layers:
            # warning = None
            uv_maps_to_keep = settings.uv_maps_to_keep
            if uv_maps_to_keep == 'FIRST':
                # Keep only the first uv map
                remove_all_uv_layers_except(me, uv_layers[0].name)
            elif uv_maps_to_keep == 'SINGLE':
                # Keep only the single specified uv map
                single_uv_map = settings.keep_only_uv_map
                if single_uv_map:
                    if single_uv_map not in uv_layers:
                        self.report({'WARNING'}, f"Could not find {single_uv_map} in uv maps of {obj!r}")
                else:
                    self.report({'WARNING'}, f"The single UV Map to keep for {obj!r} is empty. All UV"
                                             f" Maps have been removed.")
                remove_all_uv_layers_except(me, single_uv_map)
            elif uv_maps_to_keep == 'LIST':
                # Keep only the uv maps that have been specified in the list
                keep_uv_map_list = settings.keep_uv_map_list
                if keep_uv_map_list:
                    not_found = []
                    found = []
                    for element in settings.keep_uv_map_list:
                        uv_map = element.name
                        if uv_map in uv_layers:
                            found.append(uv_map)
                        else:
                            not_found.append(uv_map)
                    if found:
                        if not_found:
                            self.report({'WARNING'}, f"Could not find the UV maps {', '.join(not_found)} in {obj!r}")
                    else:
                        self.report({'WARNING'}, f"Could not find any of the UV maps to keep for {obj!r}, all the UV"
                                                 f" maps of the built object {obj!r} have been removed")
                else:
                    self.report({'WARNING'}, f"The list of UV maps to keep for {obj!r} is empty, all of its UV maps have"
                                             f" been removed")
                remove_all_uv_layers_except(me, *(e.name for e in keep_uv_map_list))
            elif uv_maps_to_keep == 'NONE':
                # Remove all uv maps. Not sure if this would ever be needed, but it's here in-case the user were to try to
                # use the LIST mode to remove all uv maps. Since LIST mode doesn't allow removing all uv maps, this NONE
                # option is provided separately
                remove_all_uv_layers_except(me)

            # NaN uvs cause Blender's FBX exporter to raise errors
            if fixes.remove_nan_uvs:
                # Twice the number of loops, since 'uv' is a 2 element Vector that gets flattened
                uvs = np.empty(len(me.loops) * 2, dtype=np.single)
                for uv_layer in me.uv_layers:
                    data = uv_layer.data
                    data.foreach_get('uv', uvs)
                    # Replace NaN with 0.0
                    uvs[np.isnan(uvs)] = 0.0
                    data.foreach_set('uv', uvs)

    def build_mesh_modifiers(self, original_scene: Scene, obj: Object, me: Mesh, settings: ModifierSettings):
        # TODO: This setting is not currently shown in the UI, it should probably be replaced with a setting on the
        #  scene, or the UI in ui_object.py would need to be changed to display the Modifiers Box when there are any
        #  non-armature modifiers
        # Optionally remove disabled modifiers
        if settings.remove_disabled_modifiers:
            modifiers = obj.modifiers
            mod: Modifier
            # While it seems to work when iterating normally, iterating in reverse is generally safer, since removing
            # elements from the end is less likely to affect the pointers of elements that have yet to be iterated.
            # To be really safe, we would have to iterate each index in reverse.
            for mod in reversed(obj.modifiers):
                if not mod.show_viewport:
                    modifiers.remove(mod)

        if not utils.has_any_enabled_non_armature_modifiers(obj):
            return

        # Apply modifiers
        shape_keys = me.shape_keys
        apply_modifiers = settings.apply_non_armature_modifiers
        if apply_modifiers != 'NONE' and not (apply_modifiers == 'APPLY_IF_NO_SHAPES' and shape_keys):
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
            # Again for data transfer modifiers to work, the active shape key has to be set to the reference key because it
            # applies to the active shape key
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
                        op_result = utils.op_override(bpy.ops.object.modifier_apply, context_override, modifier=mod_name)
                        if 'FINISHED' not in op_result:
                            raise RuntimeError(f"bpy.ops.object.modifier_apply failed for {mod_name} on {repr(obj)}")
            finally:
                obj.show_only_shape_key = orig_show_only_shape_key
                obj.active_shape_key_index = orig_active_shape_key_index
                # Unlink from the collection again
                original_scene.collection.objects.unlink(obj)

    def build_mesh_vertex_groups(self, obj: Object, settings: VertexGroupSettings):
        swaps = settings.vertex_group_swaps
        if swaps.enabled:
            vertex_groups = obj.vertex_groups
            temp_name = utils.get_unique_name('temp', vertex_groups)

            for swap in swaps.collection:
                first = swap.name
                second = swap.swap_with

                if first == second:
                    # Same name, don't need to do anything
                    continue

                first_vg = vertex_groups.get(first)
                if not first_vg:
                    self.report({'WARNING'}, f"Could not find '{first}' in the vertex groups of {obj!r}")
                    continue

                second_vg = vertex_groups.get(second)
                if not second_vg:
                    self.report({'WARNING'}, f"Could not find '{second}' in the vertex groups of {obj!r}")
                    continue

                # Currently, if a vertex group called Group already exists, attempting to rename another vertex group to
                # Group will result in it actually being renamed to Group.001 or similar. This behaviour is unlike some
                # other types when renamed, which will rename the already existing Group instead. Due to this inconsistent
                # behaviour when renaming different types, we're avoiding the behaviour entirely by first changing one
                # vertex group to a name which we've guaranteed isn't already in use.
                first_vg.name = temp_name
                second_vg.name = first
                first_vg.name = second

        if settings.remove_non_deform_vertex_groups:
            # TODO: Not sure how FBX and unity handle multiple armatures, should we only check the first armature modifier
            #  when exporting as FBX or exporting for Unity?
            deform_bone_names = utils.get_deform_bone_names(obj)
            for vg in obj.vertex_groups:
                if vg.name not in deform_bone_names:
                    obj.vertex_groups.remove(vg)

    def build_mesh_vertex_colors(self, me: Mesh, settings: VertexColorSettings):
        if settings.remove_vertex_colors:
            # Version compatible removal of all vertex colors.
            # On Blender 3.2 and newer, removes all Mesh.color_attributes.
            # On older versions, removes all Mesh.vertex_colors, which on Blender 3.0 and newer is the same as removing
            # Byte Color + Face Corner attributes. On older versions of Blender, vertex colors are their own separate
            # thing, since the Attribute system doesn't exist.
            #
            # Currently, the FBX exporter only exports via the deprecate Mesh.vertex_colors, which gives access to
            # attributes that store Byte Color data on Face Corners, in the future, other color attributes are likely to
            # be supported.
            # https://developer.blender.org/D15942 is looking promising, so we'll remove all color attributes.
            #
            # Removing a color attribute shuffles around the references to other color attributes (and probably all
            # attributes in general). Removing the attributes in reverse order seems to avoid issues, but I'm not keen
            # on relying on it, so we'll get the color_attributes in reverse index order instead, since it's much safer.
            #
            # The same issues with removing color attributes applies to the legacy vertex colors (at least on 2.93 and
            # newer)
            collection = get_vertex_colors(me)
            if collection is not None:
                for idx in reversed(range(len(collection))):
                    collection.remove(collection[idx])

    def build_mesh_materials(self, obj: Object, me: Mesh, settings: MaterialSettings):
        assert obj.data == me
        # Force all slots to DATA to simplify things
        # As each copy object will have its own unique data, this should be fine to do
        material_slots = obj.material_slots
        for slot in material_slots:
            if slot.link != 'DATA':
                # Get the material of the slot
                mat = slot.material
                # Change to the slot to DATA
                slot.link = 'DATA'
                # Set the material (updating the material in the DATA (mesh))
                slot.material = mat

        materials = me.materials

        # Remove all but one material
        main_op = settings.materials_main_op
        if main_op == 'KEEP_SINGLE':
            slot_index = settings.keep_only_mat_slot
            if 0 <= slot_index < len(materials):
                material = materials[slot_index]
                if material:
                    materials.clear()
                    materials.append(material)
            else:
                self.report({'WARNING'}, f"Invalid material slot index '{slot_index}' for {repr(obj)}")
        elif main_op == 'REMAP_SINGLE':
            material = settings.remap_single_material
            if material:
                materials.clear()
                materials.append(material)
        elif main_op == 'REMAP':
            # Using zip to stop iteration as soon as either iterator runs out of elements
            for idx, remap in zip(range(len(materials)), settings.materials_remap.collection):
                materials[idx] = remap.to_mat

        # TODO: We might want to clean up any polygon material indices that are out of bounds of the number of materials

        if len(materials) > 1:
            # Combine any duplicate materials into the first slot for that material, we do this because joining meshes does
            # this automatically and if this mesh doesn't get joined, we want the behaviour to be the same as if it did get
            # joined
            duplicates: dict[Material, list[int]] = {}
            for idx, mat in enumerate(materials):
                if mat in duplicates:
                    duplicates[mat].append(idx)
                else:
                    duplicates[mat] = [idx]
            duplicate_lists = []
            for mat, idx_list in duplicates.items():
                if len(idx_list) > 1:
                    first_duplicate_idx = idx_list[0]
                    other_duplicate_idx = idx_list[1:]
                    pair = (first_duplicate_idx, other_duplicate_idx)
                    duplicate_lists.append(pair)
            if duplicate_lists:
                # Note: material_index is refactored into an int Attribute in Blender 3.4, access may be faster via the
                # attribute in that version
                material_indices = np.empty(len(me.polygons), dtype=np.short)
                me.polygons.foreach_get('material_index', material_indices)
                # Map the materials indices to the first duplicate material
                # Get the unique material indices so that we only need to operate on a very small array when mapping instead
                # of the full array of material indices
                unique_mat_indices, inverse = np.unique(material_indices, return_inverse=True)
                for to_idx, from_indices in duplicate_lists:
                    for idx in from_indices:
                        unique_mat_indices[unique_mat_indices == idx] = to_idx
                material_indices = unique_mat_indices[inverse]
                me.polygons.foreach_set('material_index', material_indices)

    def build_mesh(self, original_scene: Scene, obj: Object, me: Mesh, settings: MeshSettings, fixes: SceneFixSettings):
        # Shape keys before modifiers because this may result in all shape keys being removed, in which case, more types of
        # modifier can be applied
        self.build_mesh_shape_keys(obj, me, settings.shape_key_settings, fixes)

        self.build_mesh_modifiers(original_scene, obj, me, settings.modifier_settings)

        self.build_mesh_uvs(obj, me, settings.uv_settings, fixes)

        # Must be done after applying modifiers, as modifiers may use vertex groups to affect their behaviour
        self.build_mesh_vertex_groups(obj, settings.vertex_group_settings)

        self.build_mesh_vertex_colors(me, settings.vertex_color_settings)

        self.build_mesh_materials(obj, me, settings.material_settings)

        # TODO: Do this when joining meshes iff the meshes don't have the same normals settings
        #  use_auto_smooth, auto_smooth_angle, has_custom_normals (if use_auto_smooth is True, since custom normals are
        #  ignored when use_auto_smooth is False)
        # This could be done just prior to joining meshes together, but I think it's ok to do here
        # There probably shouldn't be an option to turn this off
        # Set custom split normals (so that the current normals are kept when joining other meshes)
        # When use_auto_smooth is off, we need to clear sharp edges, because they will be included when calculating the
        # split normals
        if not me.use_auto_smooth:
            # Clear all sharp edges
            edges = me.edges
            edges.foreach_set('use_edge_sharp', np.zeros(len(edges), dtype=bool))
        utils.op_override(bpy.ops.mesh.customdata_custom_splitnormals_add, {'mesh': me})

        # TODO: Add option to apply all transforms
        # utils.op_override(bpy.ops.object.transform_apply, {'selected_editable_objects': [obj]},
        #                   location=True, rotation=True, scale=True)

    def build_armature(self, obj: Object, armature: Armature, settings: ArmatureSettings, copy_objects: Iterable[Object]):
        if settings.reset_before_applying_enabled() and settings.reset_pose_before_applying:
            reset_pose_bones(obj.pose.bones)
        export_pose = settings.armature_export_pose
        if export_pose == "REST":
            armature.pose_position = 'REST'
        else:
            armature.pose_position = 'POSE'
            if export_pose == 'POSE':
                pass
            elif export_pose == 'CUSTOM_ASSET_LIBRARY':
                if ASSET_BROWSER_AVAILABLE:
                    asset_settings = settings.export_pose_asset_settings
                    if asset_settings.asset_is_local_action:
                        action = asset_settings.local_action
                        if action:
                            # Poses from the Pose Library addon use frame 1 only
                            apply_pose_from_pose_action(obj, action)
                    else:
                        library_path = asset_settings.external_action_filepath
                        asset_name = asset_settings.external_action_name
                        if library_path and asset_name:
                            # Load Action from library into temp data and then apply pose from the loaded Action
                            with BlendData.temp_data() as temp_data:
                                with temp_data.libraries.load(library_path) as (data_from, data_to):
                                    data_to.actions = [asset_name]

                                action = data_to.actions[0]
                                if action:
                                    apply_pose_from_pose_action(obj, action)
                                else:
                                    self.report({'WARNING'}, f"Tried to apply Asset pose '{asset_name}' from"
                                                             f" '{library_path}' to {obj!r}, but the Asset could not be"
                                                             f" found in the library")
                else:
                    self.report({'WARNING'}, f"Tried to apply Asset pose to {obj!r}, but the Asset Browser does not"
                                             f" exist in your version of Blender")
            elif export_pose == 'CUSTOM_POSE_LIBRARY':
                if not LEGACY_POSE_LIBRARY_AVAILABLE:
                    self.report({'WARNING'}, f"Legacy Pose Library has been removed. The pose for {obj!r} could not be"
                                             f" applied")
                else:
                    marker_name = settings.armature_export_pose_library_marker
                    apply_legacy_pose_marker(self, obj, marker_name)

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
        # utils.op_override(bpy.ops.object.transform_apply, {'selected_editable_objects': [obj]},
        #                   location=True, rotation=True, scale=True)

    def validate_build(self, context: Context, active_scene_settings: SceneBuildSettings) -> Optional[ValidatedBuild]:
        view_layer = context.view_layer

        export_scene_name = active_scene_settings.name
        if not export_scene_name:
            self.report({'ERROR'}, "Active build settings' name must not be empty")
            return None
        else:
            export_scene_name += " Export Scene"

        object_to_helper: dict[Object, ObjectHelper] = {}
        for obj, object_settings in active_scene_settings.objects_gen(view_layer, yield_settings=True):
            # Ensure all objects (and their copies) will be in object mode. Since the operator's .poll fails if
            # context.mode != 'OBJECT', this will generally only happen if some script has changed the active object
            # without leaving the current sculpt/weight-paint or other mode that only allows one object at a time.
            if obj.mode != 'OBJECT':
                override = {'active_object': obj}
                utils.op_override(bpy.ops.object.mode_set, override, context, mode='OBJECT')
            desired_name = object_settings.general_settings.target_object_name
            if not desired_name:
                desired_name = obj.name
            helper = ObjectHelper(
                orig_object=obj,
                orig_object_name=obj.name,
                settings=object_settings,
                desired_name=desired_name,
            )
            object_to_helper[obj] = helper

        # Get desired object names and validate that there won't be any attempt to join Objects of different types
        desired_name_meshes: dict[str, list[ObjectHelper]] = defaultdict(list)
        desired_name_armatures: dict[str, list[ObjectHelper]] = defaultdict(list)
        for helper in object_to_helper.values():
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

        # Sort, in-place, each list of ObjectHelpers
        for helper_list in itertools.chain(desired_name_meshes.values(), desired_name_armatures.values()):
            helper_list.sort(key=ObjectHelper.to_join_sort_key)

        name_conflicts = set(desired_name_meshes.keys())
        name_conflicts.intersection_update(desired_name_armatures.keys())
        if name_conflicts:
            conflict_lines: list[str] = []
            for name in name_conflicts:
                meshes = [helper.orig_object for helper in desired_name_meshes[name]]
                armatures = [helper.orig_object for helper in desired_name_armatures[name]]
                conflict_lines.append(f"Name conflict '{name}':\n\tMeshes: {meshes}\n\tArmatures: {armatures}")
            conflicts_str = "\n".join(conflict_lines)
            self.report({'ERROR'}, f"Some meshes and armatures have the same build name, but only objects of the same"
                                   f" type can be combined together. Please change the build name for all objects in"
                                   f" one of the lists for each name conflict:\n{conflicts_str}")
            return None

        shape_keys_mesh_name = active_scene_settings.shape_keys_mesh_name
        no_shape_keys_mesh_name = active_scene_settings.no_shape_keys_mesh_name
        if active_scene_settings.reduce_to_two_meshes:
            if not shape_keys_mesh_name:
                self.report({'ERROR'}, "When reduce to two meshes is enabled, the shape keys mesh name must not be"
                                       " empty")
                return None
            if not no_shape_keys_mesh_name:
                self.report({'ERROR'}, "When reduce to two meshes is enabled, the no shape keys mesh must not be empty")
                return None

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
                    self.report({'ERROR'}, f"Naming conflict. The armatures [{armature_object_names}] have the build"
                                           f" name '{disallowed_name}', but it is reserved by one of the meshes used in"
                                           f" the 'Reduce to two meshes' option."
                                           f"\nEither change the build name of the armatures or change the mesh name"
                                           f" used by the 'Reduce to two meshes' option.")
                    return None
                # Meshes will be joined into one of the two meshes, unless they have the option enabled that makes them
                # ignore the reduce operation. We only need to check meshes that ignore that reduce operation.
                # Note that when meshes are joined by name, if any of them ignore the reduce operation, the joined mesh
                # will also ignore the reduce operation
                if disallowed_name in desired_name_meshes:
                    mesh_helpers = desired_name_meshes[disallowed_name]
                    # We only need to check meshes which ignore the reduce_to_two option, since other meshes will be
                    # joined together into one of the reduced meshes
                    ignoring_mesh_helpers = [h.orig_object.name for h in mesh_helpers if h.settings.mesh_settings.ignore_reduce_to_two_meshes]
                    if ignoring_mesh_helpers:
                        ignoring_mesh_object_names = ", ".join(ignoring_mesh_helpers)
                        self.report({'ERROR'}, f"Naming conflict. The meshes [{ignoring_mesh_object_names}] are"
                                               f" ignoring the 'Reduce to two meshes' option, but have the build name"
                                               f" '{disallowed_name}'. '{disallowed_name}' is reserved by one of the"
                                               f" meshes used in the 'Reduce to two meshes' option."
                                               f"\nEither change the build name of the meshes or change the mesh name"
                                               f" used by the 'Reduce to two meshes' option.")
                        return None

        return ValidatedBuild(
            export_scene_name=export_scene_name,
            orig_object_to_helper=object_to_helper,
            desired_name_meshes=desired_name_meshes,
            desired_name_armatures=desired_name_armatures,
            shape_keys_mesh_name=shape_keys_mesh_name,
            no_shape_keys_mesh_name=no_shape_keys_mesh_name,
        )

    @staticmethod
    def create_export_scene(scene: Scene, export_scene_name: str) -> Scene:
        export_scene = bpy.data.scenes.new(name=export_scene_name)
        export_scene_group = ScenePropertyGroup.get_group(export_scene)
        export_scene_group.is_export_scene = True
        export_scene_group.export_scene_source_scene = scene.name

        # Copy Color Management from original scene to export scene
        # Copy Display Device
        export_scene.display_settings.display_device = scene.display_settings.display_device
        # Copy View Settings
        orig_view_settings = scene.view_settings
        export_view_settings = export_scene.view_settings
        export_view_settings.view_transform = orig_view_settings.view_transform
        export_view_settings.look = orig_view_settings.look
        export_view_settings.exposure = orig_view_settings.exposure
        export_view_settings.gamma = orig_view_settings.gamma
        # TODO: Copy .curve_mapping too
        export_view_settings.use_curve_mapping = orig_view_settings.use_curve_mapping
        # Copy Sequencer
        export_scene.sequencer_colorspace_settings.name = scene.sequencer_colorspace_settings.name
        return export_scene

    @staticmethod
    def set_armature_modifiers_to_copies(helper: ObjectHelper, orig_object_to_helper: dict[Object, ObjectHelper]):
        """Set the Objects used """
        copy_obj = helper.copy_object

        # Set armature modifier objects to the copies
        for mod in copy_obj.modifiers:
            if mod.type == 'ARMATURE':
                mod_object = mod.object
                if mod_object and mod_object in orig_object_to_helper:
                    armature_copy = orig_object_to_helper[mod_object].copy_object
                    mod.object = armature_copy

    @staticmethod
    def set_parenting(helper: ObjectHelper, orig_object_to_helper: dict[Object, ObjectHelper], export_scene: Scene):
        """Set parenting such that copy Objects become parented to the copy Object equivalent of their original parent.
        If no such parent exists, search recursively for a 'grandparent' etc. that does have a copy Object equivalent
        and parent to that instead.
        If no recursive parent exists, remove the parent.
        In each case, modify the parent, but in such a way that the transform of the copy Object doesn't change."""
        copy_obj = helper.copy_object

        # Maybe add a setting for whether to parent all meshes to the armature or not OR a setting for parenting
        #  objects without a parent (either because their parent isn't in the build or because they didn't have one
        #  to start with) to the first found armature for that object.
        # Note that having the meshes parented to the armature results in the same hierarchy in Unity as not having
        #  the meshes parented.

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
                utils.op_override(bpy.ops.object.parent_set, override, type='OBJECT', keep_transform=True)
                print(f"Swapped parent of copy of {helper.orig_object.name} to copy of {orig_parent.name}")
            else:
                # Look for a recursive parent that does have a copy object and reparent to that
                recursive_parent = orig_parent.parent
                while recursive_parent and recursive_parent not in orig_object_to_helper:
                    recursive_parent = recursive_parent.parent
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
                    utils.op_override(bpy.ops.object.parent_set, override, type='OBJECT', keep_transform=True)
                    print(f"Swapped parent of copy of {helper.orig_object.name} to copy of its recursive parent"
                          f" {recursive_parent.name}")
                else:
                    # No recursive parent has a copy object, so clear parent, but keep transforms
                    # Context override to act on only the copy object
                    override = {
                        'selected_editable_objects': [copy_obj],
                        # Scene isn't required, but it could be good to include in-case it does become one
                        'scene': export_scene,
                    }
                    utils.op_override(bpy.ops.object.parent_clear, override, type='CLEAR_KEEP_TRANSFORM')
                    print(f"Remove parent of copy of {helper.orig_object.name}, none of its recursive parents have copy"
                          f" objects")
        else:
            # No parent to start with, so the copy will remain with no parent
            pass

    def build_object(self, helper: ObjectHelper, validated_build: ValidatedBuild, export_scene: Scene,
                     original_scene: Scene, fix_settings: SceneFixSettings):
        copy_obj = helper.copy_object

        orig_object_to_helper = validated_build.orig_object_to_helper

        # TODO: Should this be done after build_mesh/build_armature and are there any other modifiers we would want to
        #  change to use copy Objects rather than the originals?
        # Set modifiers (currently only Armature Modifiers) to use the equivalent copy Objects.
        self.set_armature_modifiers_to_copies(helper, orig_object_to_helper)

        # Set parenting such that copy Objects become parented to the copy Object equivalent of their original parent.
        # If no such parent exists, search recursively for a 'grandparent' etc. that does have a copy Object equivalent
        # and parent to that instead.
        # If no recursive parent exists, remove the parent.
        # In each case, modify the parent, but in such a way that the transform of the copy Object doesn't change.
        self.set_parenting(helper, orig_object_to_helper, export_scene)

        # TODO: Should we run build first (and apply all transforms) before re-parenting?
        # Run build based on Object data type
        object_settings = helper.settings
        data = copy_obj.data
        if isinstance(data, Armature):
            self.build_armature(copy_obj, data, object_settings.armature_settings, (h.copy_object for h in orig_object_to_helper.values()))
        elif isinstance(data, Mesh):
            self.build_mesh(original_scene, copy_obj, data, object_settings.mesh_settings, fix_settings)

    @classmethod
    def poll(cls, context) -> bool:
        if context.mode != 'OBJECT':
            return cls.poll_fail("Must be in Object mode")
        active = ScenePropertyGroup.get_group(context.scene).active
        if active is None:
            return cls.poll_fail("No active Scene Settings")
        if active.reduce_to_two_meshes and (not active.shape_keys_mesh_name or not active.no_shape_keys_mesh_name):
            return cls.poll_fail("Names for the 'Shape keys' Mesh and 'No shape keys' Mesh must be set when 'Reduce to"
                                 " two meshes' is enabled")
        return True

    def execute(self, context) -> set[str]:
        scene = context.scene
        scene_property_group = ScenePropertyGroup.get_group(context.scene)
        active_scene_settings = scene_property_group.active

        validated_build = self.validate_build(context, active_scene_settings)
        if validated_build is None:
            # errors should have already been reported
            return {'FINISHED'}

        # Creation and modification can now commence as all initial checks have passed

        # Create the export scene
        export_scene = self.create_export_scene(scene, validated_build.export_scene_name)

        # Initialise the copy Object (Object that will be built, since we don't modify existing Objects) for each Helper
        orig_object_to_helper = validated_build.orig_object_to_helper
        for helper in orig_object_to_helper.values():
            helper.init_copy(export_scene)

        # Operations within this loop must not cause Object ID blocks to be recreated (otherwise the references we're
        # keeping to Objects will become invalid)
        for helper in orig_object_to_helper.values():
            self.build_object(helper, validated_build, export_scene, scene, active_scene_settings.fix_settings)

        # Join meshes and armatures by desired names and rename the combined objects to those desired names
        meshes_after_joining = join_objects_with_renames(validated_build.desired_name_meshes, Mesh, export_scene, self)
        join_objects_with_renames(validated_build.desired_name_armatures, Armature, export_scene, self)

        # After performing deletions, these structures are no good anymore because some objects may be deleted
        del orig_object_to_helper

        # Join meshes based on whether they have shape keys
        # The ignore_reduce_to_two_meshes setting will need to only be True if it was True for all the joined meshes
        if active_scene_settings.reduce_to_two_meshes:
            shape_key_helpers = []
            no_shape_key_helpers = []

            mesh_objs_after_joining = []

            # Pre-sort all the ObjectHelpers, this way, when we create lists of shapekey and no-shapekey ObjectHelpers,
            # they will already be sorted
            meshes_after_joining.sort(key=ObjectHelper.to_join_sort_key)
            for helper in meshes_after_joining:
                mesh_obj = helper.copy_object
                # Individual mesh objects can exclude themselves from this operation
                # If mesh objects have been combined, whether the combined mesh object should ignore is stored in
                # a separate attribute of the helper
                ignore_reduce_to_two = helper.joined_settings_ignore_reduce_to_two_meshes
                # If the separate attribute of the helper hasn't been set, it will be None
                if ignore_reduce_to_two is None:
                    # If no mesh objects were combined into this one, get whether to ignore from its own settings
                    ignore_reduce_to_two = helper.settings.mesh_settings.ignore_reduce_to_two_meshes
                if not ignore_reduce_to_two:
                    mesh_data = cast(Mesh, mesh_obj.data)
                    if mesh_data.shape_keys:
                        shape_key_helpers.append(helper)
                    else:
                        no_shape_key_helpers.append(helper)
                else:
                    # The mesh in question ignores the 'reduce to two' option
                    mesh_objs_after_joining.append(mesh_obj)

            if shape_key_helpers:
                shape_keys_combined = join_objects_with_rename(validated_build.shape_keys_mesh_name, Mesh,
                                                               shape_key_helpers, export_scene, self)
                mesh_objs_after_joining.append(shape_keys_combined.copy_object)
            if no_shape_key_helpers:
                no_shape_keys_combined = join_objects_with_rename(validated_build.no_shape_keys_mesh_name, Mesh,
                                                                  no_shape_key_helpers, export_scene, self)
                mesh_objs_after_joining.append(no_shape_keys_combined.copy_object)
        else:
            mesh_objs_after_joining = [helper.copy_object for helper in meshes_after_joining]

        # Remap shape keys to MMD shape key names if enabled
        mmd_remap(self, scene_property_group, active_scene_settings.mmd_settings, mesh_objs_after_joining)

        if active_scene_settings.do_limit_total:
            # Annoyingly, bpy.ops.object.vertex_group_limit_total doesn't work with any useful context overrides when in
            # OBJECT mode, since it gets all selected objects in the view layer.
            # Our other options are:
            # • Setting each object into a Paint mode or sculpt mode and then overriding context.active_object
            # • Overriding the space_data to a space_properties and overriding context.object
            # A second issue, is that we want to use the BONE_DEFORM group_select_mode, but the operator will
            # only let us use it if context.active_object could have deform weights (has an armature modifier), so, even
            # though there's no useful context override, we still need to supply one with .object set to an Object that
            # can use the BONE_DEFORM group_select_mode.
            # A third issue, is that the operator's poll method checks context.object for whether it supports vertex
            # groups

            # Find all mesh Objects that could have deform weights
            # Create a function to filter meshes that don't have an armature modifier
            def any_armature_mod_filter(mesh_obj):
                return any(mod.type == 'ARMATURE' for mod in mesh_obj.modifiers)

            deform_meshes: list[Object] = list(filter(any_armature_mod_filter, mesh_objs_after_joining))

            if deform_meshes:
                with utils.temp_view_layer(export_scene) as vl:
                    # Override .object so that bpy.ops.object.vertex_group_limit_total.poll succeeds
                    # Override .active_object so that 'BONE_DEFORM' is an available group_select_mode
                    # Override .view_layer so that the Objects operated on are only the ones we selected in our temporary
                    # view_layer
                    # Passing in .scene override too in case something tries to get the scene
                    first_obj = deform_meshes[0]
                    override = {'object': first_obj, 'active_object': first_obj, 'view_layer': vl,
                                'scene': export_scene}

                    # Deselect any objects that were already selected
                    for m in vl.objects.selected:
                        m.select_set(state=False, view_layer=vl)

                    # Select only the meshes where we're going to limit the number of weights per vertex
                    for m in deform_meshes:
                        m.select_set(state=True, view_layer=vl)

                    # Run the operator to limit weights
                    utils.op_override(bpy.ops.object.vertex_group_limit_total, override, context,
                                      group_select_mode='BONE_DEFORM', limit=active_scene_settings.limit_num_groups)

        if mesh_objs_after_joining:
            # Remove unused material slots, currently, this can't be disabled. Note that joining meshes automatically
            # merges duplicate material slots into the first of the duplicate slots, so we replicate this merging
            # behaviour even if a mesh isn't joined. This means that any originally duplicate material slot will now be
            # unused.
            #
            # .poll checks if .object is a type that has materials
            # exec checks .active_object and raises an error if it's in edit mode, we'll override it just in-case
            # exec then gets .view_layer
            #   gets active to check mode and then gets all selected objects
            # exec then gets all objects from .view_layer that .poll is valid for and aren't in edit mode
            # Passing in .scene override too in case something tries to get the scene
            with utils.temp_view_layer(export_scene) as vl:
                vl: ViewLayer
                for o in vl.objects.selected:
                    o.select_set(state=False, view_layer=vl)
                for o in mesh_objs_after_joining:
                    o.select_set(state=True, view_layer=vl)
                obj0 = mesh_objs_after_joining[0]
                vl.objects.active = obj0
                override = {'object': obj0, 'active_object': obj0, 'view_layer': vl, 'scene': export_scene}
                utils.op_override(bpy.ops.object.material_slot_remove_unused, override, context)

        # Swap to the export scene
        context.window.scene = export_scene

        return {'FINISHED'}


register_module_classes_factory(__name__, globals())
