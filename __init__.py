bl_info = {
    "name": "Avatar Builder",
    "author": "Mysteryem",
    "version": (0, 0, 1),
    "blender": (2, 93, 7),
    "location": "3D View and Object Properties",
    "tracker_url": "https://github.com/Mysteryem/Miscellaneous/issues",
    "category": "3D View",
}

import bpy
import importlib

__all__ = [
    'ops',
    'ui',
    'extensions',
]

for submodule in __all__:
    globals()[submodule] = importlib.import_module("." + submodule, __name__)

# Blender register and unregister
register, unregister = bpy.utils.register_submodule_factory(__name__, __all__)
