from typing import Optional
import functools
import re

from bpy.types import WindowManager, FCurve, Keyframe, Operator, Object, Action, PoseBone

"""The Pose Library Addon is the in-development replacement for the deprecated, Legacy Pose Library system. This module
also has some code for working with the Legacy Pose Library"""


def is_pose_library_enabled() -> bool:
    return hasattr(WindowManager, 'pose_assets')


def find_keyframe(fcurve: FCurve, frame: float) -> Optional[Keyframe]:
    """Copied from scripts\\addons\\pose_library\\pose_creation.py"""
    # Binary search adapted from https://pythonguides.com/python-binary-search/
    keyframes = fcurve.keyframe_points
    low = 0
    high = len(keyframes) - 1
    mid = 0

    # Accept any keyframe that's within 'epsilon' of the requested frame.
    # This should account for rounding errors and the likes.
    epsilon = 1e-4
    frame_lowerbound = frame - epsilon
    frame_upperbound = frame + epsilon
    while low <= high:
        mid = (high + low) // 2
        keyframe = keyframes[mid]
        if keyframe.co.x < frame_lowerbound:
            low = mid + 1
        elif keyframe.co.x > frame_upperbound:
            high = mid - 1
        else:
            return keyframe
    return None


_POSE_BONE_ARRAY_PROPERTIES = {prop.identifier: getattr(prop, 'is_array', False) for prop in PoseBone.bl_rna.properties}


def apply_pose_from_action(obj: Object, action: Action, frame: int):
    # @functools.cache
    # def is_indexed_property(pose_bone_prop_name: str):
    #     prop = PoseBone.bl_rna.properties[pose_bone_prop_name]
    #     return getattr(prop, 'is_array', False)

    # @functools.cache
    # def obj_resolve(data_path: str):
    #     return obj.path_resolve(data_path)
    #
    # # Each path will be resolved as many times as there are indices for the property (3 for location/scale properties, 4
    # # for rotation properties), so we can use a cache to only resolve once per property
    # @functools.lru_cache(maxsize=4)
    # def data_path_setter_resolve(data_path: str):
    #     idx = data_path.rfind('.')
    #     parent_path = data_path[:idx]
    #     property_path = data_path[idx+1:]
    #     parent = obj_resolve(parent_path)
    #     prop = getattr(parent, property_path)
    #     if hasattr(prop, '__setitem__'):
    #         return prop.__setitem__
    #     else:
    #         return lambda _, value: setattr(parent, property_path, value)

    # Note, only supports attributes that are immediate properties of PoseBone
    bone_and_attribute_pattern = re.compile(r'pose.bones\["(.+)"]\.(\w+)')
    pose_bones = obj.pose.bones

    @functools.cache
    def get_bone(bone_name: str):
        return pose_bones.get(bone_name)

    # Each path will be resolved as many times as there are indices for the property (3 for location/scale properties, 4
    # for rotation properties), so we can use a cache to only resolve once per property
    @functools.lru_cache(maxsize=4)
    def data_path_setter_resolve(data_path: str):
        match = bone_and_attribute_pattern.match(data_path)
        if match is None:
            return None, None

        bone = get_bone(match.group(1))
        if bone is None:
            return None, None

        bone_prop_name = match.group(2)
        if bone_prop_name in _POSE_BONE_ARRAY_PROPERTIES:
            is_array = _POSE_BONE_ARRAY_PROPERTIES[bone_prop_name]
            if is_array:
                return None, getattr(bone, bone_prop_name)
            else:
                return bone_prop_name, bone
        else:
            print(f"Unknown PoseBone property {bone_prop_name} in {action!r}")
            return None, None

    # Iterate through all the fcurves
    for c in action.fcurves:
        # We can't evaluate the fcurve at the time of the frame because pose_markers don't have to affect all bones. The
        # way this is represented in the fcurves is as keyframes. If we were to evaluate the fcurve at a time where a
        # keyframe doesn't exist, we could cause unwanted changes to the pose, instead, we must iterate through the
        # keyframes and find the keyframe at the time of the frame we want (if it exists)
        #
        # Find the keyframe that is sufficiently close enough to the frame we want (frame time (co.x) is stored as a
        # float, so there may be precision errors)
        k = find_keyframe(c, frame)
        if k:
            # co is a Vector of (time, value)
            co = k.co
            if co.x == frame:
                holder_attribute, prop_or_holder = data_path_setter_resolve(c.data_path)
                if prop_or_holder:
                    if holder_attribute:
                        # The property is not an array, so we access it via its name on the holder of the attribute
                        setattr(prop_or_holder, holder_attribute, co.y)
                    else:
                        # array_index indicates the index within the resolved path
                        prop_or_holder[c.array_index] = co.y
                else:
                    print(f"Could not apply pose for data_path '{c.data_path}' in {action!r} on {obj!r}")


def apply_legacy_pose_marker(calling_op: Operator, obj: Object, marker_name: str):
    """Apply a legacy pose marker.

    The bpy.ops.poselib.apply_pose Operator can only be run from either the Properties Editor or from Pose mode, so we
    apply the pose_marker manually.

    For most models, this seems to actually be faster than calling the operator from within Pose mode and that's not
    even including the time that would be needed to switch to Pose mode, select all the bones, restore the
    bone selection afterwards and set the mode back to Object mode."""
    pose_lib = obj.pose_library
    if pose_lib is None:
        calling_op.report({'WARNING'}, f"Could not apply legacy pose library marker '{marker_name}':"
                                       f" no legacy pose library exists on {obj!r}")
        return

    marker = pose_lib.pose_markers.get(marker_name)
    if marker is None:
        calling_op.report({'WARNING'}, f"Could not find legacy pose library marker '{marker_name}' on"
                                       f" {obj!r}")
        return

    apply_pose_from_action(obj, pose_lib, marker.frame)
