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


# Blender register and unregister
register, unregister = bpy.utils.register_submodule_factory(__name__, ['ops', 'ui', 'types'])
