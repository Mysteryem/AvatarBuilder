import pkgutil
import importlib
import sys
from bpy.utils import register_submodule_factory
bl_info = {
    "name": "Avatar Builder",
    "author": "Mysteryem",
    "version": (0, 0, 1),
    "blender": (2, 93, 7),
    "location": "3D View and Object Properties",
    "tracker_url": "https://github.com/Mysteryem/Miscellaneous/issues",
    "category": "3D View",
}


# Submodules in registration order
_ordered_submodule_names = [
    'integration_cats',
    'op_build_avatar',
    'shape_key_ops',
    'ui_object',
    'ui_scene',
    'ui_mmd_shapes',
    'extensions',
]


def _get_all_module_names(ordered_submodule_names):
    """Finds all modules"""
    # Create a copy so that we don't modify the existing list
    all_submodule_names = list(ordered_submodule_names)
    # Set for quick 'in' checks
    ordered_submodule_names_set = set(all_submodule_names)
    # Prefix seems to be required to import submodules of submodules (not that we have any yet)
    package_prefix = __name__ + "."
    for mod_info in pkgutil.walk_packages(path=__path__, prefix=package_prefix):
        no_prefix_name = mod_info.name[len(package_prefix):]
        if no_prefix_name not in ordered_submodule_names_set:
            all_submodule_names.append(no_prefix_name)
    return all_submodule_names


def _register_all_modules():
    """Register all modules, including those that have no defined register and unregister functions"""
    all_module_names = _get_all_module_names(_ordered_submodule_names)
    # Blender register and unregister
    print(f"All modules to register for {__name__}:\n{all_module_names}")
    return register_submodule_factory(__name__, all_module_names)


if "bpy" in locals():
    print(f"{bl_info['name']} reload detected")
    if "__init__" in locals():
        print("\tReloading __init__")
        importlib.reload(__init__)
    for module_name in _get_all_module_names(_ordered_submodule_names):
        prefixed_module_name = __name__ + "." + module_name
        if prefixed_module_name in sys.modules:
            print(f"\tReloading {prefixed_module_name}")
            module = sys.modules[prefixed_module_name]
            importlib.reload(module)

register, unregister = _register_all_modules()
