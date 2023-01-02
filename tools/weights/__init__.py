import bpy
from bpy.types import Armature, ArmatureModifier, Object

from typing import Iterable


class MultiUserError(RuntimeError):
    pass


def mesh_gen(armature: Armature) -> Iterable[Object]:
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


def get_mesh_dict(armatures: Iterable[Armature], enforce_single_user_meshes=False) -> dict[Armature, set[Object]]:
    armatures = set(armatures)
    mesh_dict: dict[Armature, set[Object]] = {arm: set() for arm in armatures}
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        # Some operations can't be done on multi-user meshes and the enforce_single_user_meshes argument can be set to
        # check for them and raise a MultiUserError if one is found
        if enforce_single_user_meshes and o.data.users > 1:
            for mod in o.modifiers:
                # Blender doesn't seem to care if the armature modifier isn't actually set to use vertex groups (this is
                # based on renaming a bone and seeing what meshes Blender renames the vertex groups of to match)
                if isinstance(mod, ArmatureModifier) and (obj := mod.object) and (data := obj.data) in armatures:
                    raise MultiUserError(f"{o!r} has {data!r} in an armature modifier, but {o!r}'s data {o.data!r} has"
                                         f" multiple users")
        else:
            for mod in o.modifiers:
                # Blender doesn't seem to care if the armature modifier isn't actually set to use vertex groups (this is
                # based on renaming a bone and seeing what meshes Blender renames the vertex groups of to match)
                if isinstance(mod, ArmatureModifier) and (obj := mod.object) and (data := obj.data) in armatures:
                    # noinspection PyTypeChecker
                    mesh_dict[data].add(o)
    return mesh_dict
