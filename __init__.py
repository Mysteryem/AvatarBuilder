import pkgutil
import importlib
import sys
from bpy.utils import register_submodule_factory
from .registration import register_module_classes_factory
bl_info = {
    "name": "Avatar Builder",
    "author": "Mysteryem",
    "version": (0, 0, 1),
    "blender": (2, 93, 7),
    "location": "3D View and Object Properties",
    "tracker_url": "https://github.com/Mysteryem/Miscellaneous/issues",
    "category": "3D View",
}


# Submodules with registration/unregistration, in registration order
_ordered_register_submodule_names = [
    'cats_translate',
    'op_build_avatar',
    'shape_key_ops',
    'ui_object',
    'ui_scene',
    'extensions'
]


def _get_non_register_module_names(ordered_register_submodule_names):
    """Finds all modules"""
    # Extra modules that don't need any registration
    non_register_submodule_names = []
    # Set for quick 'in' checks
    register_submodule_names = set(ordered_register_submodule_names)
    # Prefix seems to be required to find submodules of subpackages (not that we have any yet)
    package_prefix = __name__ + "."
    for mod_info in pkgutil.walk_packages(path=__path__, prefix=package_prefix):
        no_prefix_name = mod_info.name[len(package_prefix):]
        if no_prefix_name not in register_submodule_names:
            non_register_submodule_names.append(no_prefix_name)
    return non_register_submodule_names


def _add_register_unregister_to_module(module, dummy: bool):
    # Dynamically created register/unregister functions by this function will be replaced if they already exist.
    # This identifier can be used to identify such dynamically registered functions
    dynamic_identifier = "_dynamic_register"
    # The value doesn't matter, since we only check for its existence, but we'll give it a descriptive value
    dynamic_identifier_value = f"Indicates a dynamically added register/unregister function added by {__name__}"
    has_register = hasattr(module, 'register') and not hasattr(module.register, dynamic_identifier)
    has_unregister = hasattr(module, 'unregister') and not hasattr(module.unregister, dynamic_identifier)

    if has_register:
        if has_unregister:
            # Nothing to do, module already has both register and unregister so is handling registration itself
            print(f"{module} already has both 'register' and 'unregister'")
        else:
            raise RuntimeError(f"{module} has a 'register' function, but is missing the corresponding 'unregister'"
                               f" function")
    else:
        if has_unregister:
            raise RuntimeError(f"{module} has an 'unregister' function, but is missing the corresponding 'register'"
                               f" function")
        else:
            if dummy:
                # There's nothing to actually (un)register for this module, but it needs both functions to work with
                # bpy.utils.register_submodule_factory

                # Might not be a good idea to create a closure around a module, so get the name as a separate variable
                # and create closures around that instead
                module_name = module.__name__

                def dummy_register():
                    print(f"Registering module {module_name} with no class or property registrations")

                # Mark as a dynamically set function
                setattr(dummy_register, dynamic_identifier, dynamic_identifier_value)

                module.register = dummy_register

                def dummy_unregister():
                    print(f"Unregistering module {module_name} with no class or property registrations")

                # Mark as a dynamically set function
                setattr(dummy_unregister, dynamic_identifier, dynamic_identifier_value)

                module.unregister = dummy_unregister
            else:
                # Find all the classes defined in the module that need registration and create functions for both
                # registering and unregistering
                register_classes, unregister_classes = register_module_classes_factory(module.__name__, module.__dict__)
                # Mark as a dynamically set functions
                setattr(register_classes, dynamic_identifier, dynamic_identifier_value)
                setattr(unregister_classes, dynamic_identifier, dynamic_identifier_value)
                # Add the functions to the module
                module.register = register_classes
                module.unregister = unregister_classes


def _add_register_unregister(all_submodule_names, dummy: bool):
    for module_str in all_submodule_names:
        # Relative import the module
        relative_module = importlib.import_module('.' + module_str, __name__)
        _add_register_unregister_to_module(relative_module, dummy)


def _register_all_modules():
    """Register all modules, including those that have no defined register and unregister functions"""
    non_register_module_names = _get_non_register_module_names(_ordered_register_submodule_names)
    _add_register_unregister(_ordered_register_submodule_names, dummy=False)
    _add_register_unregister(non_register_module_names, dummy=True)
    all_module_names = list(_ordered_register_submodule_names)
    all_module_names += non_register_module_names
    # Blender register and unregister
    print(f"All modules to register for {__name__}:\n{all_module_names}")
    return register_submodule_factory(__name__, all_module_names)


def _reload(locals_dict):
    if "__init__" in locals_dict:
        print("\tReloading __init__")
        importlib.reload(locals_dict['__init__'])
    non_register_submodule_names = _get_non_register_module_names(_ordered_register_submodule_names)
    modules_to_check = ((_ordered_register_submodule_names, True), (non_register_submodule_names, False))
    for module_names, dummy_register in modules_to_check:
        for module_name in module_names:
            prefixed_module_name = __name__ + "." + module_name
            if prefixed_module_name in sys.modules:
                print(f"\tReloading {prefixed_module_name}")
                module = sys.modules[prefixed_module_name]
                module = importlib.reload(module)
                # TODO: Investigate if this works properly
                #  What happens if a module didn't used to have register/unregister functions, but in an update they get
                #  added, since normally, a reload keeps any attributes dynamically added to the module?
                # Re-add any missing register and unregister functions and replace any dynamically added ones in-case
                # the module has received changes
                _add_register_unregister_to_module(module, dummy_register)


if "register" in locals():
    print(f"{bl_info['name']} reload detected")
    _reload(locals())

register, unregister = _register_all_modules()
