bl_info = {
    "name": "Avatar Builder",
    "author": "Mysteryem",
    "version": (0, 0, 1),
    "blender": (2, 93, 7),
    "location": "3D View and Object Properties",
    "tracker_url": "https://github.com/Mysteryem/Miscellaneous/issues",
    "category": "3D View",
}

from bpy.utils import register_submodule_factory

# Blender register and unregister
register, unregister = register_submodule_factory(
    __name__,
    [
        'op_build_avatar',
        'shape_key_ops',
        'ui_object',
        'ui_scene',
        'extensions'
    ]
)
