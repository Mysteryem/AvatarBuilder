import bpy
from bpy.types import Context, Armature, ArmatureModifier, VertexWeightMixModifier

from typing import Optional, cast
from abc import abstractmethod

from ..registration import OperatorBase, register_module_classes_factory
from ..utils import op_override


def mesh_gen(armature: Armature):
    """Generator for all mesh objects that have armature in an ArmatureModifier"""
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        for mod in o.modifiers:
            # Blender doesn't seem to care if the armature modifier isn't actually set to use vertex groups (this is
            # based on renaming a bone and seeing what meshes Blender renames the vertex groups of to match)
            if isinstance(mod, ArmatureModifier):
                obj = mod.object
                if obj and obj.data == armature:
                    yield o
                    break


_MERGE_DICTS = dict[Armature, dict[str, Optional[str]]]


class MergeBoneWeights(OperatorBase):
    """Base class for merge bone weights operators"""
    bl_options = {'UNDO', 'REGISTER'}

    @classmethod
    def poll_edit(cls, context: Context) -> bool:
        if not context.selected_editable_objects:
            return cls.poll_fail("No editable bones selected")
        return True

    @classmethod
    def poll_pose(cls, context: Context) -> bool:
        if not context.selected_pose_bones:
            return cls.poll_fail("No bones selected")
        return True

    @classmethod
    def poll(cls, context: Context) -> bool:
        if context.mode == 'EDIT_ARMATURE':
            return cls.poll_edit(context)
        elif context.mode == 'POSE':
            return cls.poll_pose(context)
        else:
            return cls.poll_fail("Must be in pose mode or edit mode with an armature")

    # Technically, the abstractmethod decorator won't do anything since the metaclass isn't ABCMeta. Unfortunately, it
    # can't be ABCMeta, since bpy.types.Operator already has its own metaclass and I don't know how to resolve the
    # conflict and still have the operator actually work.
    @staticmethod
    @abstractmethod
    def get_merge_dicts(context: Context) -> _MERGE_DICTS:
        """Returns dictionary of bone names mapped to the name of the bone they are to be merged into.
        A value of None indicates that the bone is to be deleted without having its weights merged. This can happen when
        merging weights into parents when a selected bone has no parent."""
        ...

    # Need to order selected bones or find first parent that isn't a bone being deleted
    def execute(self, context: Context) -> set[str]:
        merge_dicts = self.get_merge_dicts(context)

        if not merge_dicts:
            # This shouldn't happen, since the poll methods should return False when there's nothing to do
            return {'FINISHED'}

        # Need to be in edit mode to remove bones
        starting_mode = context.mode
        if starting_mode != 'EDIT_ARMATURE':
            bpy.ops.object.mode_set(mode='EDIT')

        for armature, bone_merges in merge_dicts.items():
            # Delete the bones that we're merging
            edit_bones = armature.edit_bones
            for bone_name in bone_merges:
                edit_bones.remove(edit_bones[bone_name])

        # Can't apply modifiers to other objects while remaining in an EDIT mode because undo/redo won't work fully.
        # It seems as if undo/redo in operators that remain in EDIT mode, or return to EDIT mode once done, handle undo
        # and redo differently. Perhaps it is optimised for undoing/redoing only the relevant EDIT mode operations.
        #
        # Technically, bpy.ops.object.modifier_apply can be made to run from EDIT mode by overriding the edit_object
        # of the context to None, but since we're going to OBJECT mode anyway, there's no need for that override.
        bpy.ops.object.mode_set(mode='OBJECT')

        # In the unlikely case that we have multiple armatures that we're merging bones of and a mesh has multiple of
        # those armatures in armature modifiers, they could be unexpected results if those armatures have bones with
        # the same names because it's not clear what order the vertex weights will be updated in
        affected_meshes = set()
        revisited_affected_meshes = set()

        for armature, bone_merges in merge_dicts.items():
            for mesh_obj in mesh_gen(armature):
                vertex_groups = mesh_obj.vertex_groups
                if mesh_obj.data.users > 1 and any(from_name in vertex_groups for from_name in bone_merges):
                    self.report({'WARNING'}, f"Can't merge weights for {mesh_obj!r} because it has multi-user data")
                    continue

                modifier_names_to_apply: list[str] = []
                vertex_group_names_to_delete: list[str] = []
                modifiers = mesh_obj.modifiers
                for from_name, to_name in bone_merges.items():
                    if from_name not in vertex_groups:
                        continue

                    if to_name is not None:
                        if to_name not in vertex_groups:
                            # The vertex group to transfer the weights to doesn't exist, so create it
                            vertex_groups.new(name=to_name)

                        # Providing an empty name results in an automatic name
                        mod = cast(VertexWeightMixModifier, modifiers.new(name="", type='VERTEX_WEIGHT_MIX'))
                        mod.vertex_group_a = to_name
                        mod.vertex_group_b = from_name
                        # Add the values of group B to group A (group B will be deleted later)
                        mod.mix_mode = 'ADD'
                        # Only affect vertices belonging to group B, since those are the only vertices that have a weight in
                        # group B to start with
                        mod.mix_set = 'B'

                        modifier_names_to_apply.append(mod.name)
                    # The from_name vertex group will always be deleted, even if there isn't a group to transfer its weights
                    # to because it has no parent or recursive parent that isn't also going to be deleted
                    vertex_group_names_to_delete.append(from_name)

                # Apply the modifiers
                if modifier_names_to_apply:
                    # object.modifier_apply fails if it finds that edit_object is not None, because it normally wouldn't be
                    # able to be run on an Object in edit mode. Hopefully there won't be any problems with pretending that
                    # the current armature isn't in edit mode currently so that the operator's poll method succeeds.
                    override = dict(object=mesh_obj)
                    op_move_to_index = bpy.ops.object.modifier_move_to_index
                    op_apply = bpy.ops.object.modifier_apply
                    for mod_name in modifier_names_to_apply:
                        # Move modifier to top to prevent warnings printed to the console about the modifier being applied
                        # not being at the top and potentially having unexpected results
                        op_override(op_move_to_index, override, modifier=mod_name, index=0)
                        op_override(op_apply, override, modifier=mod_name)

                # Remove the vertex groups we don't need. Looking up via names rather than keeping references for safety.
                if vertex_group_names_to_delete:
                    for vg_name in vertex_group_names_to_delete:
                        vertex_groups.remove(vertex_groups[vg_name])
                    # Record that we've made modifications to this mesh
                    if mesh_obj in affected_meshes:
                        revisited_affected_meshes.add(mesh_obj)
                    else:
                        affected_meshes.add(mesh_obj)

        if revisited_affected_meshes:
            # There's no clear order in which the effect of merging bones in the armatures is applied.
            #
            # This can cause unexpected results when bones being merged exist with the same name in multiple armatures.
            #
            # Imagine that Bone in Armature_A is to be merged into Bone_Parent_A, but there is also a Bone in Armature_B
            # that is to be merged into Bone_Parent_B. A bone can only have one vertex group called Bone and depending
            # on the order of Armature_A and Armature_B, different results will be produced.
            self.report({'WARNING'}, f"{len(revisited_affected_meshes)} meshes were affected by the merging of bones in"
                                     f" more than one armature simultaneously, the results may not be as expected")

        # Restoring the mode back to EDIT mode is no good since it messes up undo/redo, but we can restore the mode back
        # to POSE mode ok
        if starting_mode == 'POSE':
            bpy.ops.object.mode_set(mode='POSE')

        return {'FINISHED'}


class MergeBoneWeightsToParents(MergeBoneWeights):
    """Delete the selected bones and merge their weights into their parents"""
    bl_label = "Merge to Parents"
    bl_idname = "merge_bone_and_weights_to_parents"

    @staticmethod
    def get_merge_dicts(context: Context) -> _MERGE_DICTS:
        if context.mode == 'EDIT_ARMATURE':
            selected_bones = set(context.selected_editable_bones)
        else:
            selected_bones = set(pb.bone for pb in context.selected_pose_bones)

        merge_dicts: _MERGE_DICTS = {}
        for bone in selected_bones:
            parent = bone.parent
            # Find first parent that is not one of the selected bones
            while parent in selected_bones:
                parent = parent.parent
            armature = cast(Armature, bone.id_data)
            if armature in merge_dicts:
                merge_dict = merge_dicts[armature]
            else:
                merge_dict = {}
                merge_dicts[armature] = merge_dict
            merge_dict[bone.name] = parent.name if parent else None
        return merge_dicts


class MergeBoneWeightsToActive(MergeBoneWeights):
    """Delete the selected bones, excluding the active bone, and merge their weights into the active bone"""
    bl_label = "Merge to Active"
    bl_idname = "merge_bone_and_weights_to_active"

    @staticmethod
    def get_merge_dicts(context) -> _MERGE_DICTS:
        mode = context.mode
        if mode == 'EDIT_ARMATURE':
            active_bone = context.active_bone
            active_bone_name = active_bone.name
            armature = cast(Armature, active_bone.id_data)
            return {
                armature: {
                    bone.name: active_bone_name for
                    bone in context.selected_editable_bones if
                    bone != active_bone and bone.id_data == armature
                }
            }
        elif mode == 'POSE':
            active_bone = context.active_pose_bone
            active_bone_name = active_bone.name
            return {
                cast(Armature, active_bone.bone.id_data): {
                    bone.name: active_bone_name for
                    bone in context.selected_pose_bones_from_active_object if
                    bone != active_bone
                }
            }
        else:
            raise ValueError(f"Unexpected context mode {mode}")

    @classmethod
    def poll_edit(cls, context: Context) -> bool:
        if not super().poll_edit(context):
            return False
        active_bone = context.active_bone
        if not active_bone:
            # Probably won't see this unless there's no bones to begin with, since there's almost always an active bone
            # even if it's not selected
            return cls.poll_fail("No active bone selected")
        if not active_bone.select:
            # The user can't tell which bone is the active one if it's not selected
            return cls.poll_fail("Active bone is not selected")
        # There must be at least one other bone selected from the same armature as the active bone
        armature = active_bone.id_data
        if not any(b for b in context.selected_editable_bones if b != active_bone and b.id_data == armature):
            return cls.poll_fail("No bones to merge selected")
        return True

    @classmethod
    def poll_pose(cls, context: Context) -> bool:
        if not super().poll_pose(context):
            return False
        active_bone = context.active_pose_bone
        if not active_bone:
            # Probably won't see this unless there's no bones to begin with, since there's almost always an active bone
            # even if it's not selected
            return cls.poll_fail("No active bone selected")
        if not active_bone.bone.select:
            # The user can't tell which bone is the active one if it's not selected
            return cls.poll_fail("Active bone is not selected")
        if len(context.selected_pose_bones_from_active_object) < 2:
            return cls.poll_fail("No bones to merge selected")
        return True


register_module_classes_factory(__name__, globals())
