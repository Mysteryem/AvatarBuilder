from .registration import register_module_classes_factory

import bpy
from bpy.types import Operator, Context, PropertyGroup
from bpy.props import StringProperty, EnumProperty, BoolProperty
from types import MethodDescriptorType
from abc import ABC, abstractmethod, ABCMeta
from typing import Union

# bpy_prop_collection_idprop isn't currently exposed in bpy.types, so it can't actually be imported. It's presence here
# is purely to assist with development where it exists as a fake class.
if hasattr(bpy.types, '_bpy_prop_collection_idprop'):
    # noinspection PyProtectedMember,PyPep8Naming
    from bpy.types import _bpy_prop_collection_idprop as PropCollectionType
else:
    PropCollectionType = bpy.types.bpy_prop_collection
    for subclass in bpy.types.bpy_prop_collection.__subclasses__():
        if (
                subclass.__name__ == 'bpy_prop_collection_idprop' and
                isinstance(getattr(subclass, 'add', None), MethodDescriptorType) and
                isinstance(getattr(subclass, 'remove', None), MethodDescriptorType) and
                isinstance(getattr(subclass, 'move', None), MethodDescriptorType)
        ):
            PropCollectionType = subclass
            break
    if PropCollectionType == bpy.types.bpy_prop_collection:
        print(f"Could not find bpy_prop_collection_idprop, type checks for {__name__} will fall back to {bpy.types.bpy_prop_collection}")

r"""
Similar operators to the bpy.ops.wm.context_ operators defined in scripts\startup\bl_operators\wm.py, but for working
with collection properties
"""


# Ideally, this would extend ABC, but Blender has issues with mixing metaclasses (Operator's metaclass is
# bpy_types.RNAMeta)
class ContextCollectionOperatorBase:
    @classmethod
    @abstractmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        ...

    @classmethod
    @abstractmethod
    def get_active_index(cls, context: Context) -> int:
        ...

    @classmethod
    @abstractmethod
    def set_active_index(cls, context: Context, value: int):
        ...

    @classmethod
    def active_index_in_bounds(cls, context: Context):
        return 0 <= cls.get_active_index(context) < len(cls.get_collection(context))


# noinspection PyAbstractClass
class CollectionAddBase(ContextCollectionOperatorBase, Operator):
    """Add a new item to the collection and optionally set it as the active item"""
    bl_label = "Add"

    name: StringProperty(name="New item name", description="Name of the newly created element (optional)")
    do_set_active_index: BoolProperty(name="Set Active Index", description="Set the newly created element as active",
                                      default=True)

    def set_new_item_name(self, data: PropCollectionType, added: PropertyGroup):
        if self.name:
            added.name = self.name

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)
        added = data.add()
        self.set_new_item_name(data, added)
        if self.do_set_active_index:
            self.set_active_index(context, len(data) - 1)
        return {'FINISHED'}


# noinspection PyAbstractClass
class CollectionRemoveBase(ContextCollectionOperatorBase, Operator):
    """Remove the active item from the collection"""
    bl_label = "Remove"

    poll = ContextCollectionOperatorBase.active_index_in_bounds

    def execute(self, context: bpy.types.Context) -> set[str]:
        data = self.get_collection(context)
        active_index = self.get_active_index(context)
        data.remove(active_index)
        was_last_or_out_of_bounds = active_index >= len(data)
        if was_last_or_out_of_bounds:
            new_active_index = max(0, active_index - 1)
            if new_active_index != active_index:
                self.set_active_index(context, new_active_index)
        return {'FINISHED'}


# noinspection PyAbstractClass
class CollectionMoveBase(ContextCollectionOperatorBase, Operator):
    """Move the active item in the collection"""
    bl_label = "Move"

    type: EnumProperty(
        items=(
            ('UP', "Up", "Move active item up, wrapping around if already at the top"),
            ('DOWN', "Down", "Move active item down, wrapping around if already at the bottom"),
            ('TOP', "Top", "Move active item to the top"),
            ('BOTTOM', "Bottom", "Move active item to the bottom"),
        ),
        name="Type",
    )

    poll = ContextCollectionOperatorBase.active_index_in_bounds

    def execute(self, context: bpy.types.Context) -> set[str]:
        data = self.get_collection(context)
        active_index = self.get_active_index(context)
        command = self.type
        if command == 'UP':
            # Previous index, with wrap around to the bottom
            new_index = (active_index - 1) % len(data)
            data.move(active_index, new_index)
            self.set_active_index(context, new_index)
        elif command == 'DOWN':
            # Next index, with wrap around to the top
            new_index = (active_index + 1) % len(data)
            data.move(active_index, new_index)
            self.set_active_index(context, new_index)
        elif command == 'TOP':
            top_index = 0
            if active_index != top_index:
                data.move(active_index, top_index)
                self.set_active_index(context, top_index)
        elif command == 'BOTTOM':
            bottom_index = len(data) - 1
            if active_index != bottom_index:
                data.move(active_index, bottom_index)
                self.set_active_index(context, bottom_index)
        return {'FINISHED'}


# class ContextOperatorBase:
#     data_path: StringProperty(name="Collection Property Data Path")
#     active_index_data_path: StringProperty(name="Active Index Property Data Path")
#
#     def context_get_collection(self: Operator, context: Context) -> Union[type[Ellipsis], bpy_prop_collection_idprop]:
#         try:
#             collection = context.path_resolve(self.data_path)
#             if isinstance(collection, bpy_prop_collection_idprop):
#                 return collection
#             else:
#                 self.report({'ERROR_INVALID_CONTEXT'}, f"Found {self.data_path}, but it is not a {bpy_prop_collection_idprop}")
#                 return Ellipsis
#         except ValueError as ve:
#             self.report({'ERROR_INVALID_CONTEXT'}, str(ve))
#             return Ellipsis
#
#     def context_get_active_index(self: Operator, context: Context) -> Union[int, type[Ellipsis]]:
#         active_index_prop = context.path_resolve(self.active_index_data_path, False)
#         if active_index_prop.rna_type != bpy.types.IntProperty:
#             self.report({'ERROR_INVALID_CONTEXT'},
#                         f"Found active_index property, but it is a {active_index_prop.rna_type} when it should be a"
#                         f" {bpy.types.IntProperty}")
#             return Ellipsis
#         else:
#             return context.path_resolve(self.active_index_data_path)
#
#     def context_set_active_index(self: Operator, value: int):
#         if 'FINISHED' not in bpy.ops.wm.context_set_int(data_path=self.active_index_data_path, value=value):
#             self.report({'ERROR'}, f"Could not set {self.active_index_data_path} to {value}")
#
#
# class ContextCollectionAdd(ContextOperatorBase, Operator):
#     """Add a new item to the collection and optionally set it as the active item"""
#     bl_idname = "context_collection_add"
#     bl_label = "Add"
#
#     name: StringProperty(name="New item name", description="Name of the newly created element (optional)")
#
#     def execute(self, context: Context) -> set[str]:
#         data = self.context_get_collection(context)
#         if data is not Ellipsis:
#             if self.active_index_data_path:
#                 if self.context_get_active_index(context) is Ellipsis:
#                     return {'FINISHED'}
#                 set_active_index = True
#             else:
#                 set_active_index = False
#
#             added = data.add()
#             if self.name:
#                 added.name = self.name
#
#             if set_active_index:
#                 self.context_set_active_index(len(data) - 1)
#         return {'FINISHED'}
#
#
# class ContextCollectionRemoveActive(ContextOperatorBase, Operator):
#     """Remove the active item from the collection"""
#     bl_idname = "context_collection_remove_active"
#     bl_label = "Remove"
#
#     def execute(self, context: bpy.types.Context) -> set[str]:
#         data = self.context_get_collection(context)
#         active_index = self.context_get_active_index(context)
#         if data is not Ellipsis and active_index is not Ellipsis:
#             data.remove(active_index)
#             was_last_or_out_of_bounds = active_index >= len(data)
#             if was_last_or_out_of_bounds:
#                 new_active_index = max(0, active_index - 1)
#                 if new_active_index != active_index:
#                     self.context_set_active_index(new_active_index)
#         return {'FINISHED'}
#
#
# class ContextCollectionMoveActive(ContextOperatorBase, Operator):
#     """Move the active item in the collection"""
#     bl_idname = "context_collection_move_active"
#     bl_label = "Move"
#
#     type: EnumProperty(
#         items=(
#             ('UP', "Up", "Move active item up, wrapping around if already at the top"),
#             ('DOWN', "Down", "Move active item down, wrapping around if already at the bottom"),
#             ('TOP', "Top", "Move active item to the top"),
#             ('BOTTOM', "Bottom", "Move active item to the bottom"),
#         ),
#         name="Type",
#     )
#
#     def execute(self, context: bpy.types.Context) -> set[str]:
#         data = self.context_get_collection(context)
#         active_index = self.context_get_active_index(context)
#         if data is not Ellipsis and active_index is not Ellipsis:
#             command = self.type
#             if command == 'UP':
#                 # Previous index, with wrap around to the bottom
#                 new_index = (active_index - 1) % len(data)
#                 data.move(active_index, new_index)
#                 self.context_set_active_index(new_index)
#             elif command == 'DOWN':
#                 # Next index, with wrap around to the top
#                 new_index = (active_index + 1) % len(data)
#                 data.move(active_index, new_index)
#                 self.context_set_active_index(new_index)
#             elif command == 'TOP':
#                 top_index = 0
#                 if active_index != top_index:
#                     data.move(active_index, top_index)
#                     self.context_set_active_index(top_index)
#             elif command == 'BOTTOM':
#                 bottom_index = len(data) - 1
#                 if active_index != bottom_index:
#                     data.move(active_index, bottom_index)
#                     self.context_set_active_index(bottom_index)
#         return {'FINISHED'}


# register, unregister = register_module_classes_factory(__name__, globals())
