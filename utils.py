import bpy
from bpy.types import (
    Context,
    Scene,
    ViewLayer,
    ID,
    ImagePreview,
    Key,
    ShapeKey,
    PropertyGroup,
    Bone,
    PoseBone,
    bpy_prop_collection,
    Object,
    ArmatureModifier,
    Armature,
    UILayout,
)

from types import MethodDescriptorType
from typing import Any, Protocol, Literal, Optional, Union, TypeVar, Sized, Reversible, Iterable, SupportsFloat

from contextlib import contextmanager
import re
from textwrap import TextWrapper


_Numeric = Union[float, int]


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
    """Protocol matching the operators returned bpy.ops.<module>"""
    # todo: Add some other functions such as poll or import bpy.ops._BPyOpsSubModOp directly
    def __call__(self, *args, **kwargs) -> _OP_RETURN:
        ...

    def get_rna_type(self):
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


def id_prop_group_copy(from_group: PropertyHolderType, to_group: PropertyHolderType):
    """Copy all properties from from_group to to_group. This is a direct copy, update functions will not be called."""
    if type(from_group) != type(to_group):
        # To support cases where one type extends another, or even completely separate types, we would first have to
        # find all properties from the bl_rna of each type, taking care to avoid the 'rna_type' property and possibly
        # any properties which use their own getters and setters
        raise TypeError("Both groups must be the same type")
    # .items() and .keys() won't return properties that are set to their default value and have never been modified
    non_default_keys = set()
    # We get the existing keys of to_group before copying because we may be about to add some extra keys when copying.
    # This is a minor optimisation so that we have to iterate less.
    to_group_existing_keys = to_group.keys()
    for k, v in from_group.items():
        non_default_keys.add(k)
        to_group[k] = v
    for k in to_group_existing_keys:
        if k not in non_default_keys:
            # Delete the property, effectively restoring it to its default value when read
            del to_group[k]


def id_prop_copy(from_owner: PropertyHolderType, to_owner: PropertyHolderType, id_prop_name: str):
    """Copy a single custom property (id property) from one PropertyGroup or ID type to another.
    No checks are made that from_owner and to_owner have the same type because it is allowed for different types to have
    the same custom property.
    No checks are made that to_owner has the property being copied because the property may not be set if it hasn't
    been changed since creation (i.e., the property not existing indicates that the default value should be used).
    """
    # If we want stricter checks:
    # if strict:
    #     # Perform checks that both from_owner and to_owner have the property in question and that the type of the
    #     # properties match
    #     from_properties = from_owner.bl_rna.properties
    #     if id_prop_name not in from_properties:
    #         raise ValueError(f"'{id_prop_name}' not found on {from_owner!r}")
    #     to_properties = to_owner.bl_rna.properties
    #     if id_prop_name not in to_properties:
    #         raise ValueError(f"'{id_prop_name}' not found on {to_owner!r}")
    #     from_prop_type = type(from_properties[id_prop_name])
    #     to_prop_type = type(to_properties[id_prop_name])
    #     if from_prop_type != to_prop_type:
    #         raise ValueError(f"Property types do not match: Type of '{id_prop_name}' on {from_owner!r} is"
    #                          f" {from_prop_type}, but type of '{id_prop_name}' on {to_owner!r} is {to_prop_type}")
    if id_prop_name in from_owner:
        # The property exists in from_owner, so copy it to to_owner
        to_owner[id_prop_name] = from_owner[id_prop_name]
    elif id_prop_name in to_owner:
        # The property doesn't exist in from_owner, but does in to_owner, so delete it from to_owner
        del to_owner[id_prop_name]
    else:
        # Neither property holder has the property in question. For each, either the property doesn't exist or the
        # default value is being used.
        pass


# Naming this _T_co breaks PyCharm's code analysis for some reason
_T = TypeVar('_T')


# Type hint for sized and reversible
class SizedAndReversible(Sized, Reversible[_T], Protocol[_T]):
    pass


# Type hint for supports len and getitem, this is a copy of the Protocol in _typeshed used by type checkers for the
# builtin 'reverse' function (_typeshed does not exist at runtime).
class SupportsLenAndGetItem(Protocol[_T]):
    def __len__(self) -> int: ...
    def __getitem__(self, item) -> _T: ...


def enumerate_reversed(my_list: Union[SizedAndReversible[_T], SupportsLenAndGetItem[_T]]) -> Iterable[tuple[int, _T]]:
    """like `reversed(enumerate(my_list))` if it was possible.
    Does not create a copy of my_list like `reversed(list(enumerate(my_list)))` (faster)
    Does not have to subtract the iterated index from the length of my_list in each iteration (faster)
    Comparable in speed to `enumerate(reversed(my_list))`
    """
    return zip(reversed(range(len(my_list))), reversed(my_list))


def get_unique_name(base_name: str, existing_names_or_collection: Union[Iterable[str], bpy_prop_collection],
                    strip_end_numbers: bool = True,
                    number_separator: str = '.',
                    min_number_digits: int = 3,
                    ) -> str:
    if min_number_digits is not None and min_number_digits > 0:
        number_format = f'0{min_number_digits}d'
    else:
        number_format = 'd'
    if isinstance(existing_names_or_collection, bpy_prop_collection):
        # Getting the nth element from an mth element collection appears to scale linearly with n, so checking if the
        # 500th element is in a 1000 element collection will be done in half the time of checking whether the 1000th
        # element is in the same collection.
        # From empirical testing and extrapolation on my hardware, checking if a name (that isn't in the collection) is
        # in a collection of 1024 elements is about the same speed as first creating a set from the keys and checking if
        # the name is in the set instead. Any subsequent checks against a set of any number of elements is negligible
        # compared to a single check in a collection of 1024 elements.
        # Generally we expect to be making 1 __contains__ check most of the time with additional checks being less and
        # less likely.
        # Generally even most, larger collections that have string keys, have under 200 elements (such as a Mesh's shape
        # keys, an Object's vertex groups and bpy.data.objects)
        if len(existing_names_or_collection) > 1024:
            existing_names_set = set(existing_names_or_collection.keys())
        else:
            existing_names_set = existing_names_or_collection
    elif isinstance(existing_names_or_collection, set):
        existing_names_set = existing_names_or_collection
    else:
        existing_names_set = set(existing_names_or_collection)

    if strip_end_numbers and base_name in existing_names_set:
        match = re.fullmatch(r'(.*)' + re.escape(number_separator) + r'\d+', base_name)
        if match:
            # group(0) is the full match, group(1) is the first capture group
            base_name = match.group(1)
    unique_name = base_name
    base_with_separator = base_name + number_separator
    idx = 0
    while unique_name in existing_names_set:
        idx += 1
        unique_name = f"{base_with_separator}{idx:{number_format}}"
    return unique_name


def get_deform_bone_names(obj: Object) -> set[str]:
    """Get a set of the names of all deform bones for a particular Object"""
    deform_bone_names: set[str] = set()
    for mod in obj.modifiers:
        if isinstance(mod, ArmatureModifier) and mod.use_vertex_groups:
            if mod.object and isinstance(mod.object.data, Armature):
                armature = mod.object.data
                for bone in armature.bones:
                    if bone.use_deform:
                        deform_bone_names.add(bone.name)
    return deform_bone_names


def operator_exists(registered_op: _OperatorProtocol):
    """Check if an operator returned by bpy.ops.<module>.<op> actually exists.
    This is much faster than checking if a bpy.ops.<module> exists by checking the size of dir(bpy.ops.<module>)"""
    try:
        registered_op.get_rna_type()
        return True
    except KeyError:
        return False


def _guess_width_from_context(context: Context, margin: Optional[_Numeric] = None):
    if margin is None:
        # This is just a guess since there's usually a few pixels of margin on either side. This usually changes with
        # UI zoom, so it must be applied to region_width
        margin = 14
    region = context.region
    space = context.space_data
    region_width = region.width
    # View3D right shelf seems to start region.width at 20. No idea if this applies to any other UI regions, this is
    # just the only region being used at the moment
    if space.type == 'VIEW_3D' and region.type == 'UI':
        region_width -= 20
    region_width -= margin
    v2d = region.view2d
    # view_width decreases as UI scale increases, so this seems to account for UI zoom making text bigger
    view_width = abs(v2d.region_to_view(0, 0)[0] - v2d.region_to_view(region_width, 0)[0])
    return view_width


# Given two examples of text, a rough recorded average was about 5.13 pixels per character
_AVERAGE_PIXELS_PER_CHARACTER = 6


# placeholder is used when a line is too long. An ellipsis looks almost identical to how Blender cuts off text that is
# too long.
_TEXT_WRAPPER = TextWrapper(break_long_words=False, placeholder='…')


def ui_multiline_label(ui: UILayout, context_or_region_width: Union[Context, _Numeric], text: str,
                       max_lines: Optional[int] = None):
    if isinstance(context_or_region_width, Context):
        ui_width = _guess_width_from_context(context_or_region_width)
    else:
        ui_width = context_or_region_width
    characters_wide = ui_width // _AVERAGE_PIXELS_PER_CHARACTER
    if characters_wide > 0:
        if max_lines is None:
            # Automatic max_lines calculation. Set maximum number of lines to a third of the number of words
            words = text.split()
            # The divisor might need to be adjusted, 2 is also a reasonable value.
            max_lines = len(words) // 3
        # Always allow for at least 1 line
        max_lines = max(1, max_lines)
        _TEXT_WRAPPER.width = int(characters_wide)
        _TEXT_WRAPPER.max_lines = max_lines
        lines = _TEXT_WRAPPER.wrap(text)
        for line in lines:
            ui.label(text=line)


def has_any_enabled_non_armature_modifiers(obj: Object):
    return any(mod.type != 'ARMATURE' and mod.show_viewport for mod in obj.modifiers)
