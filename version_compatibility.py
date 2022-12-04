import bpy
from bpy.app import version
from bpy.types import Mesh, Operator

from typing import Union, Optional

from .util_generic_bpy_typing import PropCollection, Prop

LEGACY_POSE_LIBRARY_AVAILABLE = True
"""The legacy pose library system is deprecated and is supposed to be removed in Blender
3.3. Most of the functionality was supposed to be removed in 3.1 and then the Python
interface removed in 3.2, but I guess most of this never happened."""

ASSET_BROWSER_AVAILABLE = hasattr(bpy.types, 'AssetHandle') and version >= (3, 0)
"""The asset browser was added in Blender 3.0"""
if ASSET_BROWSER_AVAILABLE:
    # noinspection PyUnresolvedReferences
    ASSET_HANDLE_TYPE = bpy.types.AssetHandle
else:
    # We use this as a fallback since AssetHandle is a PropertyGroup subclass
    ASSET_HANDLE_TYPE = bpy.types.PropertyGroup


MESH_HAS_COLOR_ATTRIBUTES = hasattr(Mesh, 'color_attributes') and version >= (3, 2)
"""Mesh.color_attributes was added in Blender 3.2"""
if MESH_HAS_COLOR_ATTRIBUTES:
    VERTEX_COLORS_PROP_TYPE = bpy.types.AttributeGroup
    VERTEX_COLORS_ELEMENT_TYPE = bpy.types.Attribute
else:
    VERTEX_COLORS_PROP_TYPE = bpy.types.LoopColors
    VERTEX_COLORS_ELEMENT_TYPE = bpy.types.MeshLoopColorLayer

VERTEX_COLORS_TYPE = Union[VERTEX_COLORS_PROP_TYPE, PropCollection[VERTEX_COLORS_ELEMENT_TYPE], Prop[VERTEX_COLORS_PROP_TYPE]]


def get_vertex_colors(me: Mesh) -> Optional[VERTEX_COLORS_TYPE]:
    """Version compatible accessor for vertex colors. On versions of Blender with Mesh.color_attributes, we get that
    instead of the deprecated Mesh.vertex_colors. Technically color_attributes could be 'face colors'"""
    if MESH_HAS_COLOR_ATTRIBUTES:
        return me.color_attributes
    else:
        return me.vertex_colors


OPERATORS_HAVE_POLL_MESSAGES = hasattr(Operator, 'poll_message_set') and version >= (3, 0)
"""poll_message_set allows operators to set messages in their poll methods. These messages are shown when mousing over
operators shown in UI when the operator is disabled due to the poll method returning False.

On older Blender versions without this method, we may want to display messages in the UI directly in order to explain
why an operator is disabled"""