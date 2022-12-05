from bpy.types import (
    ID,
    bpy_struct,
    FloatProperty,
    IntProperty,
    BoolProperty,
    CollectionProperty,
)

from typing import (
    Protocol,
    Optional,
    Union,
    TypeVar,
    Sequence,
    Iterator,
    overload,
)

"""Generic structural typing for bpy_prop_collection and bpy_prop_array, intended for use with
https://github.com/Mysteryem/pycharm-blender."""

# The key type used varies. If the element type has a .name attribute, then str keys can probably be used
# Note: collections in bpy.data may be able to accept tuple[str, str], which seems to be used for accessing data from a
#       specific library
_prop_collection_key = Union[int, str]

# Element type
_E = TypeVar('_E')

# RNA type
# Could add bound=bpy_struct?
_R = TypeVar('_R')


class Prop(Protocol[_R]):
    """Generic Protocol representing a bpy_prop (not yet implemented in pycharm-blender)"""
    pass
    def as_bytes(self) -> bytes: ...
    def path_from_id(self) -> str: ...
    def update(self): pass
    # I would guess this is not actually Optional, but there's no way to tell
    # (also bpy_prop
    rna_type: Optional[_R]
    # data might not be Optional
    data: Optional[bpy_struct]
    id_data: Optional[ID]


class PropCollection(Prop[_R], Protocol[_R, _E]):
    """Generic Protocol representing a bpy_prop_collection"""
    def __bool__(self, /) -> bool: ...
    def __contains__(self, key, /) -> bool: ...
    def __delitem__(self, key, /): pass
    @overload
    def __getitem__(self, key: _prop_collection_key) -> _E: ...
    @overload
    def __getitem__(self, s: slice) -> Sequence[_E]: ...
    def __getitem__(self, key_or_slice: Union[_prop_collection_key, slice]) -> Union[_E, Sequence[_E]]: ...
    def __iter__(self) -> Iterator[_E]: ...
    def __len__(self, /) -> int: ...
    def __setitem__(self, key, value, /): pass
    def find(self, key: str) -> int: ...
    def foreach_get(self, attr, seq): pass
    def foreach_set(self, attr, seq): pass
    def get(self, key: Union[str, tuple[str, Optional[str]]], default=None) -> _E: ...
    def items(self) -> list[tuple[_prop_collection_key, _E]]: ...
    def keys(self) -> list[str]: ...
    def values(self) -> list[_E]: ...


class PropCollectionE(PropCollection[CollectionProperty, _E], Protocol[_E]):
    """Generic Protocol representing a bpy_prop_collection without an rna_type instance.
    An example would be Key.key_blocks where it is a collection of ShapeKey, so would be hinted with
    PropCollectionE[ShapeKey]"""
    pass


class PropCollectionIDProp(PropCollectionE[_E], Protocol[_E]):
    """Generic Protocol representing a user added CollectionProperty on an ID type or Bone/PoseBone"""
    def add(self) -> _E: ...
    def remove(self, key: int, /): ...
    def move(self, key: int, pos: int, /): ...
    def clear(self): ...


class PropArray(Prop[_R], Protocol[_R, _E]):
    def __bool__(self, /) -> bool: ...
    def __contains__(self, key, /) -> bool: ...
    def __delitem__(self, key, /): pass
    @overload
    def __getitem__(self, key: int) -> _E: ...
    @overload
    def __getitem__(self, s: slice) -> Sequence[_E]: ...
    def __getitem__(self, key: Union[int, slice]) -> Union[_E, Sequence[_E]]: ...
    def __iter__(self) -> Iterator[_E]: ...
    def __len__(self, /) -> int: ...
    def __setitem__(self, key, value, /): pass
    def foreach_get(self, seq): pass
    def foreach_set(self, seq): pass


class PropArrayFloat(PropArray[type[FloatProperty], float], Protocol):
    pass


class PropArrayInt(PropArray[type[IntProperty], int], Protocol):
    pass


class PropArrayBool(PropArray[type[BoolProperty], bool], Protocol):
    pass


# Example structural typing for Mesh.vertices:
#  Union[MeshVertices, PropCollection[MeshVertices, MeshVertex]]
# At runtime, Blender gives access to the attributes and functions of the rna_type directly from a bpy_prop_collection,
# so a Union of the rna_type and the PropCollection Protocol fits better. Almost every PropCollection has an rna_type,
# but for those that don't, use:
#  PropCollection[None, <element type>]

# Example structural typing for Image.pixels:
#  PropArrayFloat

# Example typing for MeshVertex.co:
#  mathutils.Vector
# While technically it would be PropArrayFloat, MeshVertex.co is set to a subtype that automatically converts to a
# Vector when accessed, so mathutils.Vector can be used in type hints directly.
