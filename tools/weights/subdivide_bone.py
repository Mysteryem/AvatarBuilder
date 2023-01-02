import bpy
from mathutils import Matrix, Vector
from bpy.types import (
    Context, Armature, Mesh, Brush, EditBone, Object, VertexGroup, CurveMapping, CurveMap, UILayout
)
from bpy.props import IntProperty, EnumProperty
from mathutils.geometry import intersect_point_line

from math import sqrt
from typing import cast, Iterable, Optional, Callable, Union, Any, Literal, Protocol
from contextlib import contextmanager
from dataclasses import dataclass, field, InitVar
from collections import defaultdict
from functools import partial
from itertools import chain
from operator import attrgetter
from time import perf_counter
import array

from ...registration import OperatorBase, register_module_classes_factory
from ...extensions import ScenePropertyGroup, SubdivideBoneGroup
from . import get_mesh_dict, MultiUserError


ALLOWED_CONTEXT_MODES = {'EDIT_ARMATURE', 'PAINT_WEIGHT', 'POSE'}


def swap_to_edit_mode_and_prepare_for_subdivide(
        context: Context,
        armature_to_subdivided_bone_names: dict[Armature, set[str]]
) -> Callable[[], Any]:
    """Returns a callable to exit edit mode and restore context."""
    mode = context.mode

    if mode not in ALLOWED_CONTEXT_MODES:
        raise RuntimeError(f"Unsupported mode '{mode}'")

    if mode == 'EDIT_ARMATURE':
        # Nothing to do in advance if we're already in edit mode, but we will need to exit EDIT mode at the end
        # otherwise undo/redo will only affect the edit mode data, the armature, and not the meshes whose weights have
        # been modified.
        return lambda: bpy.ops.object.mode_set(mode='OBJECT')

    if mode == 'PAINT_WEIGHT':
        # If in Weight Paint mode, we additionally have to change the active object. Which means we will also have to
        # change the active object back afterwards.
        weight_paint_mesh = context.active_object
        weight_paint_armature = context.pose_object
        view_layer = context.view_layer
        # Swap active object to the armature
        view_layer.objects.active = weight_paint_armature

        def restore_end():
            view_layer.objects.active = weight_paint_mesh
    else:
        restore_end = None

    # Avoid selecting one bone in Pose mode and then swapping to EDIT mode causing the mirrored bone to be selected too
    re_enable_mirror_x = []
    for armature in armature_to_subdivided_bone_names:
        if armature.use_mirror_x:
            re_enable_mirror_x.append(armature)
        armature.use_mirror_x = False

    bpy.ops.object.mode_set(mode='EDIT')

    bones_to_rehide = []
    # Edit bones could be hidden separately from the bones, there doesn't appear to be a way to access the editbone
    # hide state outside of edit mode, so we'll have to set it after entering edit mode.
    # Only selected edit bones that aren't hidden will affected by the subdivide modifier
    for armature, bone_names in armature_to_subdivided_bone_names.items():
        edit_bones = armature.edit_bones
        for bone_name in bone_names:
            edit_bone = edit_bones[bone_name]
            if edit_bone.hide:
                edit_bone.hide = False
                bones_to_rehide.append(edit_bone)
            # The bones should already be selected (even if they were hidden), but we'll make sure they are in-case
            # Blender changes this
            edit_bone.select = True

    # Restore func is to be run after subdividing is complete, restoring the original mode
    def exit_edit_mode():
        # Restore hide state of bones that we had to unhide
        for b in bones_to_rehide:
            b.hide = True
        # Restore use_mirror_x of armatures that we had to set to False
        for arm in re_enable_mirror_x:
            arm.use_mirror_x = True
        # Restore original mode of the active and selected objects
        bpy.ops.object.mode_set(mode='POSE')
        if restore_end is not None:
            # If the original mode was PAINT_WEIGHT, then there is an additional step to set the active object back to
            # the mesh rather than the armature.
            restore_end()

    return exit_edit_mode


# See BKE_brush_curve_strength in source/blender/blenkernel/intern/brush.cc
# These are clamped versions of the functions and must be as fast as possible, because they may be called many, many
# times
def _curve_preset_smooth(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        return f * f * (3.0 - 2.0 * f)


def _curve_preset_smoother(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        return f * f * f * (f * (f * 6.0 - 15.0) + 10.0)


def _curve_preset_sphere(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        return sqrt(f * (2.0 - f))


def _curve_preset_root(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        return sqrt(f)


def _curve_preset_sharp(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        return f * f


def _curve_preset_linear(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        return 1.0 - f


def _curve_preset_sharper(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        f = f * f
        return f * f


def _curve_preset_inverse_square(f: float):
    if f < 0.0:
        return 1.0
    elif f > 1.0:
        return 0.0
    else:
        f = 1.0 - f
        return f * (2.0 - f)


# 'CUSTOM', 'SMOOTH', 'SMOOTHER', 'SPHERE', 'ROOT', 'SHARP', 'LIN', 'POW4', 'INVSQUARE', 'CONSTANT'
CURVE_PRESETS: dict[str, Callable[[float], float]] = {
    'SMOOTH': _curve_preset_smooth,
    'SMOOTHER': _curve_preset_smoother,
    'SPHERE': _curve_preset_sphere,
    'ROOT': _curve_preset_root,
    'SHARP': _curve_preset_sharp,
    'LIN': _curve_preset_linear,
    'POW4': _curve_preset_sharper,
    'INVSQUARE': _curve_preset_inverse_square,
    'CONSTANT': lambda f: 1.0,
}


class CreateCurveMappingBrush(OperatorBase):
    bl_label = "Create Curve Mapping"
    bl_idname = 'create_curve_mapping_brush'

    def execute(self, context: Context) -> set[str]:
        brush = SubdivideBoneGroup.create_brush()
        ScenePropertyGroup.get_group(context.scene).tools.subdivide_bone.brush = brush
        return {'FINISHED'}


@dataclass
class CurvePresetShape:
    id: str
    icon: str
    points: list[tuple[float, float]]
    label: str = ""
    description: str = ""

    @property
    def enum_item_extended(self):
        return self.id, self.label, self.description, self.icon

    def apply_to_curve_map(self, curve_map: CurveMap):
        shape_points = self.points
        curve_points = curve_map.points

        num_shape_points = len(shape_points)
        num_curve_points = len(curve_points)
        if num_curve_points > num_shape_points:
            # Remove excess points from the end minus 1 since the first and last points can't be removed.
            # Removing a point seems to re-create all the other pointers to points, so we have to get the point to
            # remove one at a time.
            for _ in range(num_curve_points - num_shape_points):
                curve_points.remove(curve_points[-2])

            for location, point in zip(shape_points, curve_points):
                point.handle_type = 'AUTO'
                point.location = location
        elif num_shape_points > num_curve_points:
            # zip will finish once curve_points is exhausted
            for location, point in zip(shape_points, curve_points):
                point.handle_type = 'AUTO'
                point.location = location

            # Add new points
            for x, y in shape_points[num_curve_points - num_shape_points:]:
                point = curve_points.new(position=x, value=y)
                point.handle_type = 'AUTO'
        else:
            for location, point in zip(shape_points, curve_points):
                point.handle_type = 'AUTO'
                point.location = location

    def apply_to_curve_mapping(self, curve_mapping: CurveMapping):
        self.apply_to_curve_map(curve_mapping.curves[0])
        # Updates point ordering and tells UI to redraw
        curve_mapping.update()

    def apply_to_brush(self, brush: Brush):
        self.apply_to_curve_mapping(brush.curve)


class SetCurvePreset(OperatorBase):
    """It's too much work to try and coerce the bpy.ops.brush.curve_preset operator into operating on our brush due to
    how it only takes the scene and view_layer as overrides, getting the active object from the view_layer and using its
    mode to determine the Paint to use and from there which Brush to use.
    We'll set the presets manually."""
    bl_label = "Preset"
    bl_idname = 'subdivide_bone_curve_preset'
    bl_description = "Set brush shape"

    SHAPES: list[CurvePresetShape] = [
        # Point locations are manually copied from the preset curve shape set by bpy.ops.brush.curve_preset
        CurvePresetShape('SMOOTH', 'SMOOTHCURVE', [(0, 1), (0.25, 0.94), (0.75, 0.06), (1, 0)]),
        CurvePresetShape('ROUND', 'SPHERECURVE', [(0, 1), (0.5, 0.9), (0.86, 0.5), (1, 0)]),
        CurvePresetShape('ROOT', 'ROOTCURVE', [(0, 1), (0.25, 0.95), (0.75, 0.44), (1, 0)]),
        CurvePresetShape('SHARP', 'SHARPCURVE', [(0, 1), (0.25, 0.5), (0.75, 0.04), (1, 0)]),
        CurvePresetShape('LINE', 'LINCURVE', [(0, 1), (1, 0)]),
        CurvePresetShape('MAX', 'NOCURVE', [(0, 1), (1, 1)]),
    ]

    SHAPES_DICT: dict[str, CurvePresetShape] = {s.id: s for s in SHAPES}

    shape: EnumProperty(
        name="Shape",
        items=tuple(s.enum_item_extended + (i,) for i, s in enumerate(SHAPES)),
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        return ScenePropertyGroup.get_group(context.scene).tools.subdivide_bone.brush is not None

    def execute(self, context: Context) -> set[str]:
        brush = ScenePropertyGroup.get_group(context.scene).tools.subdivide_bone.brush
        self.SHAPES_DICT[self.shape].apply_to_brush(brush)
        return {'FINISHED'}


@contextmanager
def set_curve_clipping(brush: Brush):
    if brush is None:
        # Nothing to do if there's no brush
        try:
            yield
        finally:
            pass
        return

    curve_mapping = brush.curve
    old_use_clip = curve_mapping.use_clip
    old_clip_min_x = curve_mapping.clip_min_x
    old_clip_max_x = curve_mapping.clip_max_x
    old_clip_min_y = curve_mapping.clip_min_y
    old_clip_max_y = curve_mapping.clip_max_y
    curve_mapping.use_clip = True
    curve_mapping.clip_min_x = 0
    curve_mapping.clip_min_y = 0
    curve_mapping.clip_max_x = 1.0
    curve_mapping.clip_max_y = 1.0
    try:
        yield
    finally:
        curve_mapping.use_clip = old_use_clip
        curve_mapping.clip_min_y = old_clip_min_y
        curve_mapping.clip_max_y = old_clip_max_y
        curve_mapping.clip_min_x = old_clip_min_x
        curve_mapping.clip_max_x = old_clip_max_x


BonesLists = dict[Armature, list[list[EditBone]]]


def subdivide_and_get_new_edit_bones(context: Context, number_of_cuts: int) -> BonesLists:
    all_selected = set(context.selected_editable_bones)
    selected_bones_per_armature: dict[Armature, list[EditBone]] = {}
    for bone in all_selected:
        selected_bones_per_armature.setdefault(bone.id_data, []).append(bone)
    num_starting_bones_dict: dict[Armature, int] = {}
    for armature, selected_bones in selected_bones_per_armature.items():
        edit_bones = armature.edit_bones
        idx_lookup = {bone: idx for idx, bone in enumerate(edit_bones)}
        # Sort the selected bones into the order they are found in edit_bones
        selected_bones.sort(key=lambda b: idx_lookup[b])

        num_starting_bones_dict[armature] = len(edit_bones)

    # Run subdivide
    bpy.ops.armature.subdivide(number_cuts=number_of_cuts)

    # NOTE: This isn't documented behaviour, so it could change:
    # The new bones are added to the end of the edit bones, in the same order that the original bones are in.
    bones_lists: BonesLists = {}
    for armature, num_starting_bones in num_starting_bones_dict.items():
        new_bones = armature.edit_bones[num_starting_bones:]
        # Number of new bones should be divisible by number_of_cuts, since that's the number of new bones created per
        # initially selected bone
        assert len(new_bones) % number_of_cuts == 0

        # Make an iterator that gets number_of_cuts elements at a time
        new_bones_iter = zip(*(iter(new_bones),) * number_of_cuts)

        bones_list = []
        for original_bone, new_bones_tuple in zip(selected_bones_per_armature[armature], new_bones_iter):
            # First element of the list will be the original bone
            bone_list = [original_bone]
            # The next elements in the list will be the new bones
            #
            # NOTE: This isn't documented behaviour, so it could change:
            # The bones created are such that the first bone is the furthest away from originally selected bone, with
            # each subsequent bone getting closer to the originally selected bone, so we reverse the tuple
            bone_list.extend(reversed(new_bones_tuple))
            bones_list.append(bone_list)

        bones_lists[armature] = bones_list

    return bones_lists


@dataclass(eq=True, frozen=True)
class BoneData:
    armature_obj: Object
    armature: Armature
    bone_name: str
    """The name of the bone that was subdivided"""
    bone_chain_names: tuple[str]
    """The names of the new bones, starting with the bone closest to the head of the subdivided bone"""
    world_space_head: Vector
    """Worldspace head of the subdivided bone"""
    world_space_tail: Vector
    """Worldspace tail of the subdivided bone"""

    @classmethod
    def new(cls, armature_obj: Object, bone_list: list[EditBone]):
        if len(bone_list) < 2:
            raise ValueError(f"bone_list must have at least two bones, but only had {len(bone_list)}")
        if armature_obj.type != 'ARMATURE':
            raise ValueError(f"Expected {armature_obj!r} to be an ARMATURE Object, but its type is {armature_obj.type}")
        original_bone = bone_list[0]
        chain_bones = bone_list[1:]
        wm = armature_obj.matrix_world
        head: Vector = wm @ original_bone.head
        tail: Vector = wm @ chain_bones[-1].tail
        # Freeze so can be hashed
        head.freeze()
        tail.freeze()
        return cls(
            armature_obj=armature_obj,
            armature=cast(Armature, armature_obj.data),
            bone_name=original_bone.name,
            bone_chain_names=tuple(b.name for b in chain_bones),
            world_space_head=head,
            world_space_tail=tail)


@dataclass(eq=True, frozen=True)
class MeshData:
    mesh_obj: Object
    mesh: Mesh
    """Mesh data, purely for convenience"""
    wm_inverted: Matrix
    """Used to convert bone worldspace head/tail to mesh localspace since it's much quicker to convert than to convert
        all vertex positions to worldspace or armature localspace"""

    @classmethod
    def new(cls, mesh_obj: Object):
        if mesh_obj.type != 'MESH':
            raise ValueError(f"Expected {mesh_obj!r} to be a MESH Object, but its type is {mesh_obj.type}")
        # TODO: Should we check somewhere before that the mesh object isn't scaled to zero on one or more axes?
        wm_inverted = mesh_obj.matrix_world.inverted_safe()
        # Freeze so can be hashed
        wm_inverted.freeze()
        return cls(mesh_obj, cast(Mesh, mesh_obj.data), wm_inverted)


@dataclass
class CurveData:
    """Data specific to a single curve used for applying the same effect as using the gradient weight paint tool
    consecutively"""
    curve: InitVar[Union[str, tuple[CurveMapping, CurveMap]]]
    locked_section_weight_multipliers: Optional[list[list[float]]] = None
    section_starting_multipliers: Optional[list[float]] = None
    evaluate_func: Callable[[float], float] = field(init=False)

    def __post_init__(self, curve: Union[str, tuple[CurveMapping, CurveMap]]):
        if isinstance(curve, str):
            self.evaluate_func = CURVE_PRESETS[curve]
        else:
            # Instead of calling CurveMapping.evaluate and specifying the CurveMap argument each time, it seems to be
            # slightly faster to call a partial function with the CurveMap argument already set
            self.evaluate_func = partial(curve[0].evaluate, curve[1])

    def leaves_locked_weights(self):
        return self.locked_section_weight_multipliers is not None and self.section_starting_multipliers is not None

    @classmethod
    def from_brush(cls, operator: OperatorBase, brush: Optional[Brush], num_bones: int) -> 'CurveData':
        if brush is None:
            # Use smooth when no brush is specified. Linear tends to give sharp creases at bends which isn't generally
            # as useful
            return cls('SMOOTH')

        curve_preset = brush.curve_preset
        if curve_preset == 'CUSTOM':
            return cls.from_curve(operator, brush.curve, num_bones)
        else:
            return cls(curve_preset)

    @classmethod
    def from_curve(cls, operator: OperatorBase, curve_mapping: CurveMapping, num_bones: int) -> 'CurveData':
        curve = curve_mapping.curves[0]
        # It isn't recommended to have gradients that start at less than one, because then every bone in the
        # chain will be weighted to the first vertex group by the remainder
        gradient_leaves_leftover_locked_weights = curve.points[0].location.y < 1.0
        if (
                gradient_leaves_leftover_locked_weights
                # If the last point is at or below 0.0, then we quickly know that the curve should evaluate to 0.0 at
                # 1.0
                or curve.points[-1].location.y > 0.0
                # Doesn't usually end up at exactly 0.0, so we'll use isclose (comparing against 1.0 to avoid issues
                # with comparing against 0.0). Since we're most likely only working with single prevision math, it's
                # likely that
                # or not math.isclose(curve_mapping.evaluate(curve, 1.0) + 1.0, 1.0, rel_tol=1e-6)
                # Passing through 0.5 is recommended, but it doesn't produce near-unusable results like not
                # starting at 1.0 and ending at 0.0.
                # or curve_mapping.evaluate(curve, 0.5) != 0.5
        ):
            operator.report({'INFO'}, "Subdividing bone weights works best with a falloff that starts at 1.0 and ends at 0.0")
        if gradient_leaves_leftover_locked_weights:
            # Should always equal curve.points[0].location.y since we're always clamping within [0.0, 1.0]
            gradient_start_multiplier = curve_mapping.evaluate(curve, 0.0)
            # Pre-calculate the percentage of the vertex's original weight that will be available to each
            # vertices in each section.
            # Pre-calculate the percentage of the vertex's original weight that will not be available and how
            # that percentage is split between the previous vertex groups.

            # Multiplier for the weight that gets left over in a previous vertex group, that then gets locked
            # (if we were to have subdivided the weights manually with the gradient tool and if the gradient
            # tool actually respected locked vertex groups)
            gradient_start_remainder_multiplier = 1 - gradient_start_multiplier
            # First two sections are always full starting weight, since they're within the first gradient
            section_starting_multipliers = [1.0, 1.0]
            # The third section starts outside the first gradient, so its starting weight will equal the
            # original weight multiplied by the curve evaluated at 1.0 (the vertex would be evaluated after 1.0,
            # but we assume the curve is clamped, so after 1.0 is the same as 1.0).
            # The fourth section starts after the first and second gradients, so its starting weight will equal
            # the starting weight of the third section multiplied by the curve evaluated at 1.0.
            # This repeats until the last section.
            running_multiplier = gradient_start_multiplier
            previous_multiplier = 1.0
            # These are weights for the locked vertex groups in each section, each index i corresponds to the
            # ith vertex group
            locked_section_weight_multipliers = [[], []]
            running_locked_section_multipliers = []
            for i in range(2, num_bones):
                section_starting_multipliers.append(running_multiplier)
                # Alternatively: previous_multiplier = section_starting_multipliers[i-1]
                running_locked_section_multipliers.append(previous_multiplier * gradient_start_remainder_multiplier)
                locked_section_weight_multipliers.append(running_locked_section_multipliers.copy())
                previous_multiplier = running_multiplier
                running_multiplier *= gradient_start_multiplier
            # Given a gradient_start_multiplier of 0.75 and num_bones of 5 for example:
            # section_starting_multipliers =      [1.0, 1.0,   0.75,         0.5625,                 0.421875]
            # locked_section_weight_multipliers = [ [],  [], [0.25], [0.25, 0.1875], [0.25, 0.1875, 0.140625]]

            # The sum of the start multiplier and previous locked multipliers is always be 1.0 (or close enough
            # due to limited precision) e.g.
            # for start_multiplier, previous_locked_multipliers in zip(
            #         section_starting_multipliers, locked_section_weight_multipliers
            # ):
            #     assert math.isclose(1.0, start_multiplier + sum(previous_locked_multipliers, start=0))
            return cls((curve_mapping, curve), locked_section_weight_multipliers, section_starting_multipliers)
        else:
            # If the gradient starts at 1.0, then each next bone in the chain will have 100% of the original
            # weight to take from. This is the typical, and simpler, case.
            return cls((curve_mapping, curve))


_VG_REMOVE = Callable[[Iterable[int]], None]


class _VgAdd(Protocol):
    def __call__(self, index: Iterable[int], weight: float, *, type: Literal['REPLACE', 'ADD', 'SUBTRACT']): ...


def weight_vertices(
        mesh: Mesh,
        vg_data: list[tuple[VertexGroup, list[VertexGroup], tuple[Vector, Vector]]],
        num_bones: int,
        curve_data: CurveData,
):
    start = perf_counter()
    # The reference shape key and mesh.vertices can become desynced. What users see is the reference shape key, so use
    # that for the 'co'. Hopefully this will be fixed one day.
    if mesh.shape_keys:
        mesh_co_source = mesh.shape_keys.reference_key.data
    else:
        mesh_co_source = mesh.vertices
    # Python arrays are fast to iterate, we can copy the 'co' directly into an array and iterate it 3 values at a time
    # to get each 'co' vector.
    # Single precision float type matching the internal C type of the 'co'.
    co_source = array.array('f', [0.0]) * (len(mesh.vertices) * 3)
    mesh_co_source.foreach_get('co', co_source)
    # zip the iterator with itself 2 times so that our new iterator yields 3-element tuples at a time
    co_source = zip(*([iter(co_source)] * 3))

    curve_evaluate = curve_data.evaluate_func
    curve_leaves_locked_weights = curve_data.leaves_locked_weights()
    locked_section_weight_multipliers = curve_data.locked_section_weight_multipliers
    section_starting_multipliers = curve_data.section_starting_multipliers
    gradient_length_in_bones = 2
    num_bones_over_gradient_length_in_bones = num_bones / gradient_length_in_bones

    vg_remove_lists: list[tuple[_VG_REMOVE, list[int]]] = []
    vg_data_dict: dict[int, tuple[tuple[_VgAdd, ...], Vector, Vector, list[int]]] = {}
    for vg0, vgn, (head, tail) in vg_data:
        # We set the same list instance into both vg_remove_lists and vg_data_dict, so we can add to the list through
        # vg_data_dict when iterating through vertices and then at the end, use the list to remove weights through
        # vg_remove_lists.
        remove_list: list[int] = []
        vg_data_dict[vg0.index] = (tuple(vg.add for vg in vgn), head, tail, remove_list)
        vg_remove_lists.append((vg0.remove, remove_list))

    if not vg_data_dict:
        # Shouldn't normally happen, but nothing to do
        return

    only_one_group = len(vg_data_dict) == 1

    # TODO: Not sure this is needed
    old_mirror_vertex_groups = mesh.use_mirror_vertex_groups
    mesh.use_mirror_vertex_groups = False

    for v, co in zip(mesh.vertices, co_source):
        idx_as_list = None
        # Iterating v.groups is not affected by adding new weights to the current vertex, but is affected if removing
        # weights.
        for g in v.groups:
            group_idx = g.group
            if group_idx not in vg_data_dict:
                continue
            vgn_add, head, tail, vg_remove_list = vg_data_dict[group_idx]
            weight = g.weight

            if idx_as_list is None:
                # Getting v.index for every vertex is slower than iterating with an index alongside v using
                # enumerate(mesh.vertices), but if we're unlikely to need the index of every vertex, it tends to be
                # faster to only get the index from v.index when we do need it
                idx_as_list = [v.index]

            _, normalized_vertex_length_from_tail = intersect_point_line(co, tail, head)
            # The vertex lies within the bone at the following index where the bone at index 0 is the bone
            # closest to the head of the bone before subdivision
            section = int((1.0 - normalized_vertex_length_from_tail) * num_bones)
            if section >= num_bones:
                section = num_bones - 1
            elif section < 0:
                section = 0

            if curve_leaves_locked_weights:
                # Set the weights of the locked groups before this section. The multipliers have been
                # pre-calculated
                # Note that the len(locked_section_weight_multipliers[section]) == max(0, section - 2) so the number of
                # vertex groups iterated will vary with the section
                for vg_add, locked_weight in zip(vgn_add, locked_section_weight_multipliers[section]):
                    vg_add(idx_as_list, weight * locked_weight, type='REPLACE')
                # Since the gradient leaves leftover locked weights, the sum of the leftovers is already in use.
                # We could sum up the leftovers and subtract that or calculate the percentage left after
                # subtraction, we have precalculated the percentage, since the absolute amount varies based on
                # the starting vg0 weight of the vertex.
                weight = section_starting_multipliers[section] * weight
            elif section > 1:
                # TODO: Add an option for "Remove zero weights" or "Don't add zero weights" that enables this
                # If a gradient that starts at 1, after section 1, the weight will be zero, so we can
                # remove it
                #
                # We can only remove weights from the current vertex after we are done iterating, otherwise, we may mess
                # up the iteration, so we add them to a list:
                #
                # Removing weights will offset the pointers of each 'group' element:
                #    Start with iteration:
                #      [group_element0, group_element1] where each group element is an index: weight ->
                #      [0: 0.025, 2: 0.97]
                #      We get group index 0 with weight 0.025 as the first iterated element
                #    Add a new weight (new weight index = 219):
                #      [0: 0.025, 2: 0.97]
                #      No change, because while a new weight has been added to the end in the underlying vertex data, it
                #      has been added at the end.
                #    Remove weight 0:
                #      [2: 0.97, 219: 0.0]
                #      Because we removed the first weight, the internal indices of the weights after the first weight
                #      have now all been reduced by 1.
                #    Iterate next value:
                #      [2: 0.97, 219: 0.0]
                #      The elements are still the same, so we do get the 'next' element, but that 'next' element is now
                #      group index 219 with weight 0.0, when we were expecting to get group index 2 with weight 0.97
                #      next.
                #      We cannot tell in advance what index the removed weight will be at, so we must resort to only
                #      removing weights from a vertex after we are done iterating the vertex's weights.
                vg_remove_list.extend(idx_as_list)
            if section == 0:
                # vertex is in the first section, it is only affected by the first gradient
                normalized_length_in_gradient = (normalized_vertex_length_from_tail - 1) * num_bones_over_gradient_length_in_bones + 1
                bone1_percent_of_weight = curve_evaluate(normalized_length_in_gradient)
                bone0_percent_of_weight = 1 - bone1_percent_of_weight
                bone0_add = vgn_add[section]
                bone1_add = vgn_add[section + 1]
                bone0_add(idx_as_list, weight * bone0_percent_of_weight, type='REPLACE')
                bone1_add(idx_as_list, weight * bone1_percent_of_weight, type='REPLACE')
            elif section == (num_bones - 1):
                # vertex is in the last section, it is only affected by the last gradient
                # The last gradient starts from the tail of the original bone
                normalized_length_in_gradient = normalized_vertex_length_from_tail * num_bones / gradient_length_in_bones
                bone_n_percent_of_weight = curve_evaluate(normalized_length_in_gradient)
                bone_n_minus_1_percent_of_weight = 1 - bone_n_percent_of_weight
                bone_n_minus_1_add = vgn_add[section - 1]
                bone_n_add = vgn_add[section]
                bone_n_minus_1_add(idx_as_list, weight * bone_n_minus_1_percent_of_weight, type='REPLACE')
                bone_n_add(idx_as_list, weight * bone_n_percent_of_weight, type='REPLACE')
            else:
                # vertex is somewhere in the middle, it is affected by two gradients
                normalized_first_gradient_start_from_tail = (num_bones - section + 1 - gradient_length_in_bones) / num_bones
                normalized_length_in_first_gradient = (normalized_vertex_length_from_tail - normalized_first_gradient_start_from_tail) * num_bones_over_gradient_length_in_bones
                # The second gradient starts half a gradient (or one bone's length) further towards the tail of the original bone
                normalized_length_in_second_gradient = normalized_length_in_first_gradient + 0.5
                bone_n_percent_of_weight = curve_evaluate(normalized_length_in_first_gradient)
                bone_n_minus_1_percent_of_weight = 1 - bone_n_percent_of_weight

                bone_n_weight = weight * bone_n_percent_of_weight

                bone_n_plus_1_percent_of_bone_n_weight = curve_evaluate(normalized_length_in_second_gradient)
                bone_n_percent_of_bone_n_weight = 1 - bone_n_plus_1_percent_of_bone_n_weight
                bone_n_minus_1_add = vgn_add[section - 1]
                bone_n_add = vgn_add[section]
                bone_n_plus_1_add = vgn_add[section + 1]
                bone_n_minus_1_add(idx_as_list, weight * bone_n_minus_1_percent_of_weight, type='REPLACE')
                bone_n_add(idx_as_list, bone_n_weight * bone_n_percent_of_bone_n_weight, type='REPLACE')
                bone_n_plus_1_add(idx_as_list, bone_n_weight * bone_n_plus_1_percent_of_bone_n_weight, type='REPLACE')
            if only_one_group:
                break

    for vg_remove_func, indices in vg_remove_lists:
        # Remove weights from vertices.
        if indices:
            vg_remove_func(indices)

    end = perf_counter()
    mesh.use_mirror_vertex_groups = old_mirror_vertex_groups
    print(f"Subdivided weights for {mesh!r} in {end-start}ms")


def weight_mesh(
        mesh_data: MeshData,
        subdivided_bone_data: Iterable[BoneData],
        affected_initial_vertex_group_names: set[str],
        num_bones: int,
        curve_data: CurveData,
):
    mesh_obj = mesh_data.mesh_obj
    vertex_groups = mesh_obj.vertex_groups

    vg_data: list[tuple[VertexGroup, list[VertexGroup], tuple[Vector, Vector]]] = []
    for bone_data in subdivided_bone_data:
        initial_bone_name = bone_data.bone_name
        if initial_bone_name in affected_initial_vertex_group_names:
            wm_inverted = mesh_data.wm_inverted
            tail_before_subdivide_local = wm_inverted @ bone_data.world_space_tail
            active_bone_head_local = wm_inverted @ bone_data.world_space_head
            vg0 = mesh_obj.vertex_groups[initial_bone_name]
            vgs = [vg0]
            for bone_name in bone_data.bone_chain_names:
                if bone_name not in vertex_groups:
                    vgs.append(vertex_groups.new(name=bone_name))
                else:
                    vgs.append(vertex_groups[bone_name])
            vg_data.append((vg0, vgs, (active_bone_head_local, tail_before_subdivide_local)))

    weight_vertices(mesh_data.mesh, vg_data, num_bones, curve_data)


class SubdivideBonesAndWeights(OperatorBase):
    """Subdivide the selected bones and their weights across the length of each bone subdivided.
    Uses the falloff settings of the brush (clamped to the [0,1] range).
    If no brush is specified, uses smooth falloff"""
    bl_label = "Subdivide Weights"
    bl_idname = 'subdivide_bone_and_weights'
    bl_options = {'REGISTER', 'UNDO'}

    number_cuts: IntProperty(name="Number of Cuts", min=1, default=1)

    @classmethod
    def poll_edit_armature(cls, context: Context) -> bool:
        if not context.selected_editable_bones:
            return cls.poll_fail("No selected editable bones")
        return True

    @classmethod
    def poll_pose(cls, context: Context) -> bool:
        if not context.selected_pose_bones:
            return cls.poll_fail("No selected bones")
        return True

    @classmethod
    def poll_paint_weight(cls, context: Context) -> bool:
        if not context.pose_object:
            return cls.poll_fail("No armature opened alongside mesh into weight paint mode")
        if not context.selected_pose_bones:
            return cls.poll_fail("No selected bones")
        return True

    @classmethod
    def poll_general(cls, context: Context) -> bool:
        brush = ScenePropertyGroup.get_group(context.scene).tools.subdivide_bone.brush
        if brush and not brush.curve.curves:
            return cls.poll_fail("ERROR: Brush curve missing curves")
        return True

    @classmethod
    def poll(cls, context: Context) -> bool:
        mode = context.mode
        if mode == 'EDIT_ARMATURE':
            mode_func = cls.poll_edit_armature
        elif mode == 'POSE':
            mode_func = cls.poll_pose
        elif mode == 'PAINT_WEIGHT':
            mode_func = cls.poll_paint_weight
        else:
            return cls.poll_fail("Must be in armature edit, pose or weight paint mode")

        return mode_func(context) and cls.poll_general(context)

    @staticmethod
    def get_armatures(context: Context) -> tuple[dict[Armature, Object], set[Armature]]:
        armature_to_obj: dict[Armature, Object] = {}
        ineligible_armature_data = set()

        mode = context.mode
        if mode == 'EDIT_ARMATURE' or mode == 'POSE':
            armature_objects = context.objects_in_mode
        elif mode == 'PAINT_WEIGHT':
            armature_objects = [context.pose_object]
        else:
            raise RuntimeError(f"Unsupported mode '{mode}'")

        for armature_obj in armature_objects:
            armature = cast(Armature, armature_obj.data)
            if armature in armature_to_obj:
                # It is currently not possible to open armatures with the same data in edit mode, but it is possible
                # in pose mode
                # TODO: Alternatively, we could flat-out reject multi-user armature data
                ineligible_armature_data.add(armature)
            else:
                armature_to_obj[armature] = armature_obj

        return armature_to_obj, ineligible_armature_data

    def get_armature_to_subdivided_bone_names(self, context: Context, ineligible_armature_data: set[Armature]
                                              ) -> Optional[dict[Armature, set[str]]]:
        armature_to_subdivided_bone_names: dict[Armature, set[str]] = defaultdict(set)

        mode = context.mode
        if mode == 'POSE' or mode == 'PAINT_WEIGHT':
            bone_iter = map(attrgetter('bone'), context.selected_pose_bones)
        elif mode == 'EDIT_ARMATURE':
            bone_iter = context.selected_editable_bones
        else:
            raise RuntimeError(f"Unsupported mode '{mode}'")

        for bone in bone_iter:
            # TODO: Need to get the armature objects!
            armature = bone.id_data
            if armature in ineligible_armature_data:
                self.report({'ERROR'}, f"{armature!r} is in edit mode through more than one object")
                return None
            armature_to_subdivided_bone_names[armature].add(bone.name)

        return armature_to_subdivided_bone_names

    def execute(self, context: Context) -> set[str]:
        armature_to_obj, ineligible_armature_data = self.get_armatures(context)

        armature_to_subdivided_bone_names = self.get_armature_to_subdivided_bone_names(
            context, ineligible_armature_data)
        # TODO: Just return 'CANCELLED' if not armature_to_subdivided_bone_names?
        if armature_to_subdivided_bone_names is None:
            return {'CANCELLED'}

        # Get the mesh objects used by each armature
        try:
            mesh_dict = get_mesh_dict(armature_to_subdivided_bone_names, enforce_single_user_meshes=True)
        except MultiUserError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        reversed_mesh_dict: dict[Object, set[Armature]] = defaultdict(set)
        mesh_obj_to_affected_vertex_groups_names: dict[Object, set[str]] = defaultdict(set)
        obj_to_mesh_data: dict[Object, MeshData] = {}
        for armature, mesh_obj_set in mesh_dict.items():
            for mesh_obj in mesh_obj_set:
                reversed_mesh_dict[mesh_obj].add(armature)
                if mesh_obj not in obj_to_mesh_data:
                    obj_to_mesh_data[mesh_obj] = MeshData.new(mesh_obj)
                vertex_groups = mesh_obj.vertex_groups
                for bone_name in armature_to_subdivided_bone_names[armature]:
                    vg = vertex_groups.get(bone_name)
                    if vg:
                        vg_name_set = mesh_obj_to_affected_vertex_groups_names[mesh_obj]
                        if vg in vg_name_set:
                            # Super rare edge-case where a mesh has two (or more) armature modifiers set to different
                            # armatures and both of those armatures contain a bone being subdivided with the same name.
                            # The bone exists in more than one armature, but we can only get the head/tail of the bone
                            # to use from one armature.
                            self.report({'ERROR'}, f"More than one '{bone_name}' bone used by {mesh_obj!r} is being"
                                                   f" subdivided, but only one bone with a specific name can have its"
                                                   f" weights subdivided at once,")
                            return {'CANCELLED'}
                        vg_name_set.add(vg.name)

        exit_edit_mode_func = swap_to_edit_mode_and_prepare_for_subdivide(context, armature_to_subdivided_bone_names)

        # Must be in EDIT mode at this point
        bones_lists = subdivide_and_get_new_edit_bones(context, self.number_cuts)

        # Create the BoneData for each list
        armature_to_bone_data: dict[Armature, list[BoneData]] = defaultdict(list)
        for armature, bone_lists in bones_lists.items():
            armature_obj = armature_to_obj[armature]
            bone_data_list = [BoneData.new(armature_obj, bone_list) for bone_list in bone_lists]
            armature_to_bone_data[armature] = bone_data_list

        # We're done with EDIT mode so return to the previous mode or exit to OBJECT mode if the previous mode was EDIT
        # mode.
        exit_edit_mode_func()

        brush = ScenePropertyGroup.get_group(context.scene).tools.subdivide_bone.brush
        curve_mapping: CurveMapping
        with set_curve_clipping(brush):
            num_cuts = self.number_cuts
            num_bones = num_cuts + 1

            curve_data = CurveData.from_brush(self, brush, num_bones)

            for mesh_obj, armature_set in reversed_mesh_dict.items():
                per_mesh_bone_data = chain.from_iterable(bone_data_list for armature, bone_data_list
                                                         in armature_to_bone_data.items()
                                                         if armature in armature_set)
                per_mesh_affected_vertex_group_names = mesh_obj_to_affected_vertex_groups_names[mesh_obj]
                weight_mesh(obj_to_mesh_data[mesh_obj], per_mesh_bone_data, per_mesh_affected_vertex_group_names,
                            num_bones, curve_data)

        return {'FINISHED'}


def draw_subdivide_bone_ui(context: Context, layout: UILayout):
    subdivide_bone_group = ScenePropertyGroup.get_group(context.scene).tools.subdivide_bone
    box = layout.box()
    box.label(text="Brush for custom falloff:")
    box.template_ID(subdivide_bone_group, 'brush', new=CreateCurveMappingBrush.bl_idname)
    brush = subdivide_bone_group.brush
    if brush:
        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(brush, "curve_preset", text="")

        if brush.curve_preset == 'CUSTOM':
            box.template_curve_mapping(brush, "curve", brush=True)

            col = box.column(align=True)
            row = col.row(align=True)

            for s in SetCurvePreset.SHAPES:
                row.operator(SetCurvePreset.bl_idname, icon=s.icon, text=s.label).shape = s.id

    # TODO: If in edit mode (and possibly for other modes), will need a value displayed in the UI that specified how
    #  many cuts to make, then set that in the OperatorProperties returned by layout.operator
    box.operator(SubdivideBonesAndWeights.bl_idname, icon='BONE_DATA')


register_module_classes_factory(__name__, globals())
