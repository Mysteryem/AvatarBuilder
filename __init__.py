import pkgutil

from .registration import register_submodule_factory
bl_info = {
    "name": "Avatar Builder",
    "description": "Combine objects to make ready-to-export models",
    "author": "Mysteryem",
    "version": (0, 3, 0),
    "blender": (2, 93, 7),
    "location": "3D View and Object Properties",
    "doc_url": "https://github.com/Mysteryem/AvatarBuilder",
    "tracker_url": "https://github.com/Mysteryem/AvatarBuilder/issues",
    "category": "3D View",
}


# Register extensions first so that other modules can use types from it as pointer or collection properties
_early_ordered_register = [
    # Names to use are the full names without the main package prefix, e.g. "tools.ui_tools" instead of
    # "avatar_builder.tools.ui_tools"
    'extensions'
]


def _get_all_module_names():
    """Finds all modules"""
    early_modules = set(_early_ordered_register)
    # Create a copy so that we don't modify the existing list
    all_submodule_names = _early_ordered_register.copy()
    # Prefix is required to import submodules of submodules
    package_prefix = __name__ + "."
    prefix_length = len(package_prefix)
    for mod_info in pkgutil.walk_packages(path=__path__, prefix=package_prefix):
        no_prefix_name = mod_info.name[prefix_length:]
        if no_prefix_name not in early_modules:
            all_submodule_names.append(no_prefix_name)
    return all_submodule_names


def _register_all_modules():
    """Register all modules
    :raises AttributeError: if a module is missing a 'register' or 'unregister' attribute"""
    all_module_names = _get_all_module_names()
    # Blender register and unregister.
    # Note that unregister removes the modules from sys.modules, effectively reloading the modules when register loads
    # them again.
    # Blender checks for when an Addon's __init__.py has changed on disk and will reload it automatically when enabling
    # the addon.
    # These two combined mean that disabling and re-enabling the addon will reload every module used by the addon.
    print(f"All modules to register for {__name__}:\n{all_module_names}")
    return register_submodule_factory(__name__, all_module_names)


register, unregister = _register_all_modules()
