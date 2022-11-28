import bpy
from bpy.app import version

LEGACY_POSE_LIBRARY_AVAILABLE = True
"""The legacy pose library system is deprecated and is supposed to be removed in Blender
3.3. Most of the functionality was supposed to be removed in 3.1 and then the Python
interface removed in 3.2, but I guess most of this never happened."""

ASSET_BROWSER_AVAILABLE = version >= (3, 0)
"""The asset browser was added in 3.0"""
if ASSET_BROWSER_AVAILABLE:
    # noinspection PyUnresolvedReferences
    ASSET_HANDLE_TYPE = bpy.types.AssetHandle
else:
    # We use this as a fallback since AssetHandle is a PropertyGroup subclass
    ASSET_HANDLE_TYPE = bpy.types.PropertyGroup
