import bpy
from bpy.types import Context, Scene, ViewLayer, ID, ImagePreview, Key, ShapeKey, PropertyGroup, Bone, PoseBone

from types import MethodDescriptorType
from typing import Any, Protocol, Literal, Optional, Union, TypeVar, Sized, Reversible, runtime_checkable
from contextlib import contextmanager
from .registration import dummy_register_factory


# bpy_prop_collection_idprop isn't currently exposed in bpy.types, so it can't actually be imported. It's presence here
# is purely to assist with development where it exists as a fake class.
if hasattr(bpy.types, '_bpy_prop_collection_idprop'):
    # noinspection PyProtectedMember,PyPep8Naming
    from bpy.types import _bpy_prop_collection_idprop as PropCollectionType
else:
    # We can actually get the class from the bpy_prop_collection subclasses
    # Start with bpy_prop_collection as a fallback
    PropCollectionType = bpy.types.bpy_prop_collection
    # Iterate through the subclasses (there should only be one)
    for subclass in bpy.types.bpy_prop_collection.__subclasses__():
        # Attempt to match against the name and available method descriptors
        if (
                subclass.__name__ == 'bpy_prop_collection_idprop' and
                isinstance(getattr(subclass, 'add', None), MethodDescriptorType) and
                isinstance(getattr(subclass, 'remove', None), MethodDescriptorType) and
                isinstance(getattr(subclass, 'move', None), MethodDescriptorType)
        ):
            PropCollectionType = subclass
            break
    if PropCollectionType == bpy.types.bpy_prop_collection:
        print(f"Could not find bpy_prop_collection_idprop, type checks for {__name__} will fall back to"
              f" {bpy.types.bpy_prop_collection}")


_EXECUTION_CONTEXTS = Literal[
    'INVOKE_DEFAULT',
    'INVOKE_REGION_WIN',
    'INVOKE_REGION_CHANNELS',
    'INVOKE_REGION_PREVIEW',
    'INVOKE_AREA',
    'INVOKE_SCREEN',
    'EXEC_DEFAULT',
    'EXEC_REGION_WIN',
    'EXEC_REGION_CHANNELS',
    'EXEC_REGION_PREVIEW',
    'EXEC_AREA',
    'EXEC_SCREEN',
]

_OP_RETURN = set[Literal['RUNNING_MODAL', 'CANCELLED', 'FINISHED', 'PASS_THROUGH', 'INTERFACE']]


class _OperatorProtocol(Protocol):
    """Protocol matching the signature of __call__ of operators from bpy.ops"""
    def __call__(self, *args, **kwargs) -> _OP_RETURN:
        ...


if bpy.app.version >= (3, 2):
    # Passing in context_override as a positional-only argument is deprecated as of Blender 3.2, replaced with
    # Context.temp_override
    def op_override(operator: _OperatorProtocol, context_override: dict[str, Any], context: Context = None,
                    execution_context: Optional[_EXECUTION_CONTEXTS] = None,
                    undo: Optional[bool] = None, /, **operator_args) -> _OP_RETURN:
        """Call an operator with a context override"""
        args = []
        if execution_context is not None:
            args.append(execution_context)
        if undo is not None:
            args.append(undo)

        if context is None:
            context = bpy.context
        # noinspection PyUnresolvedReferences
        with context.temp_override(**context_override):
            return operator(*args, **operator_args)
else:
    def op_override(operator: _OperatorProtocol, context_override: dict[str, Any], context: Context = None,
                    execution_context: Optional[_EXECUTION_CONTEXTS] = None,
                    undo: Optional[bool] = None, /, **operator_args) -> _OP_RETURN:
        """Call an operator with a context override"""
        args = [context_override]
        if execution_context is not None:
            args.append(execution_context)
        if undo is not None:
            args.append(undo)

        return operator(*args, **operator_args)


@contextmanager
def temp_view_layer(scene: Scene) -> ViewLayer:
    """Some operators have no usable context overrides aside from .view_layer. This context manager creates a temporary
    view layer that can then be passed"""
    temp = scene.view_layers.new(name="temp")
    try:
        yield temp
    finally:
        scene.view_layers.remove(temp)


def get_preview(id: ID) -> ImagePreview:
    if bpy.app.version >= (3, 0):
        # .preview can be None in 3.0+, the new preview_ensure() method can be used.
        # noinspection PyUnresolvedReferences
        preview = id.preview_ensure()
    else:
        preview = id.preview
    return preview


class ReverseRelativeShapeKeyMap:
    def __init__(self, shape_keys: Key):
        reverse_relative_map = {}

        basis_key = shape_keys.reference_key
        for key in shape_keys.key_blocks:
            # Special handling for basis shape key to treat it as if its always relative to itself
            relative_key = basis_key if key == basis_key else key.relative_key
            keys_relative_to_relative_key = reverse_relative_map.get(relative_key)
            if keys_relative_to_relative_key is None:
                keys_relative_to_relative_key = {key}
                reverse_relative_map[relative_key] = keys_relative_to_relative_key
            else:
                keys_relative_to_relative_key.add(key)
        self.reverse_relative_map = reverse_relative_map

    def get_relative_recursive_keys(self, shape_key) -> set[ShapeKey]:
        shape_set = set()

        # Pretty much a depth-first search, but with loop prevention
        def inner_recursive_loop(key, checked_set):
            # Prevent infinite loops by maintaining a set of shapes that we've checked
            if key not in checked_set:
                # Need to add the current key to the set of shapes we've checked before the recursive call
                checked_set.add(key)
                keys_relative_to_shape_key_inner = self.reverse_relative_map.get(key)
                if keys_relative_to_shape_key_inner:
                    for relative_to_inner in keys_relative_to_shape_key_inner:
                        shape_set.add(relative_to_inner)
                        inner_recursive_loop(relative_to_inner, checked_set)

        inner_recursive_loop(shape_key, set())
        return shape_set


PropertyHolderType = Union[ID, PropertyGroup, Bone, PoseBone]
"""Only ID, PropertyGroup, Bone and PoseBone types can have custom properties assigned"""


def get_id_prop_ensure(holder: PropertyHolderType, prop_name: str):
    if prop_name in holder:
        return holder[prop_name]
    else:
        # TODO: maybe calling .items() or .keys() or .values() would work to ensure all props on holder are created?
        getattr(holder, prop_name)
        return holder[prop_name]


def id_property_group_copy(from_owner: PropertyHolderType, to_owner: PropertyHolderType, id_prop_name: str):
    """Copy a custom property (id property) from one PropertyGroup or ID type to another.
    No checks are made that from_owner and to_owner have the same type because it is allowed for different types to have
    the same custom property.
    No checks are made that to_owner has the property being copied because the property may just not be initialised yet.
    """
    # TODO: Can we check for whether the property should exist on to_owner and that its type matches the type of the
    #  property on from_owner, by using the rna functions/attributes?
    from_prop = get_id_prop_ensure(from_owner, id_prop_name)
    if id_prop_name in to_owner:
        # .update is about 3 times faster than direct assignment
        #   to_owner[id_prop_name] = from_prop
        # or per-item assignment:
        #   to_prop = getattr(to_owner, id_prop_name)
        #   for k, v in getattr(from_owner, id_prop_name).items:
        #       to_prop[k] = v
        to_owner[id_prop_name].update(from_prop)
    else:
        # Prop being pasted to was probably only just created or otherwise hasn't had the prop initialised yet
        to_owner[id_prop_name] = from_prop


_T_co = TypeVar('_T_co')


@runtime_checkable
class SizedAndReversible(Sized, Reversible[_T_co], Protocol[_T_co]):
    pass


def enumerate_reversed(my_list: SizedAndReversible):
    """like `reversed(enumerate(my_list))` if it was possible.
    Does not create a copy of my_list like `reversed(list(enumerate(my_list)))` (faster)
    Does not have to subtract the iterated index from the length of my_list in each iteration (faster)
    Comparable in speed to `enumerate(reversed(my_list))`
    """
    return zip(reversed(range(len(my_list))), reversed(my_list))


register, unregister = dummy_register_factory()
