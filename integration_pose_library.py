from typing import cast
import numpy as np

from bpy.types import WindowManager, FCurve, Operator, Object, Action, TimelineMarker, WorkSpace, Armature

"""The Pose Library Addon is the in-development replacement for the deprecated, Legacy Pose Library system. This module
also has some code for working with the Legacy Pose Library"""


def is_pose_library_enabled() -> bool:
    # The new Pose Library addon adds these two properties when enabled
    return hasattr(WindowManager, 'pose_assets') and hasattr(WorkSpace, 'active_pose_asset_index')


def has_keyframe(fcurve: FCurve, frame_to_find: float) -> bool:
    """Return True iff the FCurve has a key on the source frame.
    Modified from PoseActionCreator._has_key_on_frame from scripts\\addons\\pose_library\\pose_creation.py"""
    points = fcurve.keyframe_points
    if not points:
        return False
    margin = 0.001
    high = len(points) - 1
    low = 0
    while low <= high:
        mid = (high + low) // 2
        diff = points[mid].co.x - frame_to_find
        if abs(diff) < margin:
            return True
        if diff < 0:
            # Frame to find is bigger than the current middle.
            low = mid + 1
        else:
            # Frame to find is smaller than the current middle
            high = mid - 1
    return False


def apply_pose_from_pose_action(obj: Object, action: Action, evaluation_time: float = 0.0):
    """Apply the pose of the Object from the specified Action to all bones.
    For Pose Library Addon poses, evaluate at the default time of 0.
    Forcefully affects all bones by deselecting all bones. Does not reselect them afterwards.
    Takes into account whether each fcurve is muted, skipping it if so."""
    armature: Armature = cast(Armature, obj.data)
    # Pose.apply_pose_from_action only updates selected bones, or, if none are selected, updates all bones.
    #
    # Deselect all bones so that every bone is affected.
    #
    # Note that while selecting all bones achieves the same effect, hidden pose bones are considered deselected, so it
    # is simpler to deselect all bones, since we don't have to care about whether bones are hidden. Also note that
    # while a PoseBone shares the same select state as its Bone, it has its own hide states separate from the Bone's
    # hide state.
    #
    # This also means that an alternative to deselecting all bones would be hiding all PoseBones, but that could leave
    # hidden bones selected, which could cause problems with addons that don't understand that if something is hidden it
    # should be considered deselected (as described in Blender's API documentation).
    bones = armature.bones
    bones.foreach_set('select', np.zeros(len(bones), dtype=bool))
    # Apply the pose to every bone now that they are all deselected
    obj.pose.apply_pose_from_action(action, evaluation_time=evaluation_time)


def apply_pose_from_legacy_pose_action(obj: Object, action: Action, marker: TimelineMarker):
    """Apply the pose of the Object at the TimelineMarker of the specified Legacy Pose Library Action.
    This deselects all bones and does not reselect them afterwards."""

    # Legacy Pose Library poses set properties based on the keyframes that exist at the specified frame.
    # Pose.apply_pose_from_action masks which bones are affected based on the selection, but this is not specific enough
    # for Legacy Pose Library Actions because each pose could contain only some properties of each bone. To create a
    # more specific mask we can mute the properties that we don't want to affect (and then restore the mutes
    # afterwards).

    # Note that if action is the .action attribute of the animation_data of an Object, this function will cause that
    # Object to update its animation state! This is a side effect of changing .mute in FCurves.
    # Generally speaking, a Legacy Pose Library shouldn't be assigned as an Object's animation_data's .action unless the
    # user has assigned it directly from the Action Editor within the Dope Sheet Editor.
    # Copy objects will always be unaffected because we clear animation_data in order to remove any drivers on copy
    # objects.

    # Each marker has an associated frame
    frame = marker.frame
    restore_mute_list: list[FCurve] = []
    try:
        for c in action.fcurves:
            # We can't directly evaluate the fcurve at the time of the frame because pose_markers don't have to affect all
            # bones.
            # The way this is represented in the fcurves is as keyframes. If we were to evaluate the fcurve at a time
            # where a keyframe doesn't exist, we could cause unwanted changes to the pose because it would interpolate
            # between the keyframe before and after the time we evaluated at.
            #
            # If there is not a keyframe at the specified frame, mute the fcurve so that it isn't used when applying the
            # pose.
            # We don't expect any FCurves to be muted already, but if there are, we'll skip them
            if not c.mute and not has_keyframe(c, frame):
                c.mute = True
                # Add the fcurve to the list of fcurves to unmute
                restore_mute_list.append(c)
        # Apply the pose at the evaluated frame (automatically skipping any muted fcurves)
        apply_pose_from_pose_action(obj, action, frame)
    finally:
        # Restore mutes that were changed
        for c in restore_mute_list:
            c.mute = False


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

    # The Legacy Pose Library stores each pose in a specific keyframe, specified by the TimelineMarker
    apply_pose_from_legacy_pose_action(obj, pose_lib, marker)
