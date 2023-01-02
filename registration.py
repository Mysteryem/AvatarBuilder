from collections import defaultdict
from typing import TypeVar, Union, Generic, Optional, Any, Callable, overload, Literal, NamedTuple
from types import ModuleType
from sys import intern

import bpy
from bpy.types import Panel, Operator, UIList, Menu, ID, Bone, PoseBone, PropertyGroup, UILayout, AddonPreferences
from bpy.props import PointerProperty, CollectionProperty, IntProperty, EnumProperty

from .version_compatibility import OPERATORS_HAVE_POLL_MESSAGES


class OperatorBase(Operator):
    if not OPERATORS_HAVE_POLL_MESSAGES:
        # Support for older versions that don't have poll_message_set
        @classmethod
        def poll_message_set(cls, message, *args):
            pass

    @classmethod
    def poll_fail(cls, message: str):
        cls.poll_message_set(message)
        return False


# Prefix
_BL_ID_PREFIX = "em_av_builder"
_PROP_PREFIX = _BL_ID_PREFIX

# Type hint for any Blender type that can have custom properties assigned to it
PropHolderType = Union[ID, Bone, PoseBone]


# Mapping from space type to panel prefix
_PANEL_SPACE_TYPE_PREFIX = {
    'CLIP_EDITOR': 'CLIP',
    'CONSOLE': 'CONSOLE',  # not used by Blender
    'DOPESHEET_EDITOR': 'DOPESHEET',
    'EMPTY': 'EMPTY',  # not used by Blender
    'FILE_BROWSER': 'FILEBROWSER',
    'GRAPH_EDITOR': 'GRAPH',
    'IMAGE_EDITOR': 'IMAGE',
    'INFO': 'INFO',  # not used by Blender
    'NLA_EDITOR': 'NLA',
    # NODE_EDITOR uses the defaultdict below for more specific prefixes
    # 'NODE_EDITOR': 'NODE',
    'OUTLINER': 'OUTLINER',
    'PREFERENCES': 'USERPREF',
    'PROPERTIES': 'PROPERTIES',
    'SEQUENCE_EDITOR': 'SEQUENCER',
    'SPREADSHEET': 'SPREADSHEET',  # not used by Blender
    'STATUSBAR': 'STATUSBAR',  # not used by Blender
    'TEXT_EDITOR': 'TEXT',
    'TOPBAR': 'TOPBAR',
    'VIEW_3D': 'VIEW3D',
}

_NODE_EDITOR_PANEL_SPACE_TYPE_PREFIX = defaultdict(
    lambda: defaultdict(lambda: 'NODE'),
    {
        'LIGHT': defaultdict(lambda: 'NODE', {'CYCLES': 'NODE_CYCLES_LIGHT'}),
        'WORLD': defaultdict(lambda: 'NODE_WORLD', {'CYCLES': 'NODE_CYCLES_WORLD'}),
        'MATERIAL': defaultdict(
            lambda: 'NODE_MATERIAL', {'CYCLES': 'NODE_CYCLES_MATERIAL', 'EEVEE': 'NODE_EEVEE_MATERIAL'}
        ),
        'DATA': defaultdict(lambda: 'NODE_DATA'),
    }
)


def get_panel_prefix(panel_cls: type[Panel], node_type=None, node_engine_type=None):
    space_type = panel_cls.bl_space_type
    if space_type == 'NODE_EDITOR':
        return _NODE_EDITOR_PANEL_SPACE_TYPE_PREFIX[node_type][node_engine_type]
    else:
        return _PANEL_SPACE_TYPE_PREFIX[space_type]


def prefix_classes(classes):
    for cls in classes:
        if hasattr(cls, 'bl_idname'):
            if issubclass(cls, Panel):
                prefix = f"{get_panel_prefix(cls)}_PT_{_BL_ID_PREFIX}_"
            elif issubclass(cls, Operator):
                prefix = f"{_BL_ID_PREFIX}."
            elif issubclass(cls, UIList):
                prefix = "AVATAR_BUILDER_UL_"
            elif issubclass(cls, Menu):
                prefix = "AVATAR_BUILDER_MT_"
            elif issubclass(cls, AddonPreferences):
                continue
            else:
                prefix = f"{_BL_ID_PREFIX}_"
            if not cls.bl_idname.startswith(prefix):
                cls.bl_idname = prefix + cls.bl_idname


# Probably gets all the possible classes (without getting subclasses of subclasses etc.), seems to include:
# Operator, Macro, KeyingSetInfo, Panel, Menu and Node
# _CLASSES_WITH_DESCRIPTION = tuple(
#     t for t in bpy.types.bpy_struct.__subclasses__()
#     if hasattr(t, 'bl_rna')
#     and any(p.identifier == 'bl_description' for p in t.bl_rna.properties)
# )
# We'll just use the ones we care about for now
_CLASSES_WITH_DESCRIPTION = (Operator, Panel, Menu)


def fix_descriptions(classes):
    """For classes that can use docstrings as descriptions, Blender doesn't strip leading spaces from each line which
    can make the descriptions look bad when displayed in UI. This function will strip leading spaces from each line of
    cls.__doc__ and set that modified description into bl_description iff bl_description does not already exist"""
    for cls in classes:
        # Operator, Menu and Panel has bl_description. UIList does not.
        if issubclass(cls, _CLASSES_WITH_DESCRIPTION):
            if not hasattr(cls, 'bl_description'):
                doc = cls.__doc__
                if doc:
                    lines = doc.splitlines()
                    reformatted_doc = "\n".join(line.lstrip() for line in lines)
                    if reformatted_doc != doc:
                        cls.bl_description = reformatted_doc


T = TypeVar('T', bound='IdPropertyGroup')


# Base class used to provide typed access (and checks) to getting groups from ID types
# Ideally we'd make this an abstract baseclass, but Blender doesn't like that for 'metaclasses'
class IdPropertyGroup:
    _registration_name: str
    _registration_type: type[PropHolderType]

    # Technically, obj can also be a Bone or PoseBone, but we're not using
    @classmethod
    def get_group(cls: type[T], obj: PropHolderType) -> T:
        if isinstance(obj, cls._registration_type):
            group = getattr(obj, cls._registration_name)
            if isinstance(group, cls):
                return group
            else:
                raise ValueError(f"Tried to get a {cls} from {obj}, but got a {type(group)}.")
        else:
            raise ValueError(f"Tried to get a {cls} from {obj}, but {obj} is not a {cls._registration_type}")

    @classmethod
    def register_prop(cls):
        setattr(cls._registration_type, cls._registration_name, PointerProperty(type=cls))

    @classmethod
    def unregister_prop(cls):
        delattr(cls._registration_type, cls._registration_name)


E = TypeVar('E', bound=PropertyGroup)


class CollectionPropBase(Generic[E], PropertyGroup):
    # Unfortunately, PyCharm won't pick up the typing if we try to set
    # collection: CollectionProperty(type=<type as argument>)
    # using a passed in argument, so we must provide the annotation in subclasses
    #
    # By setting this property's type to None, it will error if it's not overridden
    collection: CollectionProperty(type=None)
    active_index: IntProperty()

    def get_element_icon(self, element: Optional[E]):
        """Get the icon of an element"""
        return 'NONE'

    def get_element_label(self, element: Optional[E]):
        """Get the name of an element"""
        if element is None:
            return "(no items)"
        else:
            return element.name

    def get_element_description(self, element: Optional[E]):
        """Get the description of an element"""
        return ""

    def _search_items(self, context):
        """This function cannot be overriden without also overriding the search EnumProperty annotation"""
        items = []
        if context:
            collection = self.collection
            if collection:
                for idx, e in enumerate(collection):
                    item = (
                        intern(str(idx)),
                        intern(self.get_element_label(e)),
                        intern(self.get_element_description(e)),
                        intern(self.get_element_icon(e)),
                        idx
                    )
                    items.append(item)
        if not items:
            # Must have at least one element
            items = [
                (
                    intern('0'),
                    intern(self.get_element_label(None)),
                    intern(self.get_element_description(None)),
                    intern(self.get_element_icon(None)),
                    0,
                )
            ]
        return items

    def _search_items_get(self):
        """This function cannot be overriden without also overriding the search EnumProperty annotation"""
        maximum_index = len(self.collection) - 1
        # Technically, active_index could erroneously be set below 0
        minimum_index = 0
        return max(minimum_index, min(self.active_index, maximum_index))

    def _search_items_set(self, value):
        """This function cannot be overriden without also overriding the search EnumProperty annotation"""
        self.active_index = value

    # Enum 'wrapper' for the active_index property, intended for use in UI
    search: EnumProperty(
        items=_search_items,
        get=_search_items_get,
        set=_search_items_set,
        options={'SKIP_SAVE'},
        # Don't display anything below the popup list displayed with UILayout.prop
        name="",
    )

    def draw_search(self, layout: UILayout, *,
                    new: str = '', unlink: str = '', name_prop: str = 'name', icon: str = 'NONE',
                    new_is_menu: bool = False):
        """UI helper that produces a similar look to UILayout.template_ID but for custom Collection properties.
        icon of 'NONE' will use the icon from get_element_icon"""
        row = layout.row(align=True)
        row.prop(self, 'search', icon_only=True, icon=icon)
        active = self.active
        if active is not None:
            row.prop(active, name_prop, text="")
            if new:
                if new_is_menu:
                    row.menu(new, text="", icon='DUPLICATE')
                else:
                    row.operator(new, text="", icon='DUPLICATE')
            if unlink:
                row.operator(unlink, text="", icon='X')
        else:
            # todo: Might want to display something for when the 'new' Operator isn't specified
            if new:
                if new_is_menu:
                    row.menu(new, text="New", icon='ADD')
                else:
                    row.operator(new, text="New", icon='ADD')

    @property
    def active(self) -> Optional[E]:
        active_index = self.active_index
        collection = self.collection
        if 0 <= active_index < len(collection):
            return collection[active_index]
        else:
            return None


def register_classes_factory(classes):
    bpy_register, bpy_unregister = bpy.utils.register_classes_factory(classes)

    def combined_register():
        prefix_classes(classes)
        fix_descriptions(classes)
        bpy_register()

    return combined_register, bpy_unregister


@overload
def register_module_classes_factory(calling_module_name: str,
                                    calling_module_globals: dict[str, Any],
                                    return_funcs: Literal[False] = False
                                    ) -> None: ...


@overload
def register_module_classes_factory(calling_module_name: str,
                                    calling_module_globals: dict[str, Any],
                                    return_funcs: Literal[True]
                                    ) -> tuple[Callable[[], None], Callable[[], None]]: ...


def register_module_classes_factory(calling_module_name: str,
                                    calling_module_globals: dict[str, Any],
                                    return_funcs: bool = False
                                    ) -> Optional[tuple[Callable[[], None], Callable[[], None]]]:
    """Looks through calling_module_globals for classes whose __module__ matches the calling_module_name and either have
    a bl_idname attribute or are a subclass of bpy.types.PropertyGroup and creates register and unregister functions for
    the found classes. When return_funcs is False, the created functions are added directly to calling_module_globals"""
    print(f"Looking for classes to register in {calling_module_name}")
    classes: list[type] = []
    id_prop_groups: list[type[IdPropertyGroup]] = []
    for attribute in calling_module_globals.values():
        # We only want types that have been created in the calling module
        if isinstance(attribute, type) and attribute.__module__ == calling_module_name:
            if hasattr(attribute, 'bl_idname'):
                print(f"\tFound {attribute.__name__} in {calling_module_name} via bl_idname")
                classes.append(attribute)
            elif issubclass(attribute, PropertyGroup):
                print(f"\tFound {attribute.__name__} in {calling_module_name} via bpy.types.PropertyGroup")
                classes.append(attribute)
                if issubclass(attribute, IdPropertyGroup):
                    print(f"\t\tIt is also an {IdPropertyGroup.__name__} and will be registered on"
                          f" {attribute._registration_type} as {attribute._registration_name}")
                    id_prop_groups.append(attribute)

    if id_prop_groups:
        # For IdPropertyGroup types, we need to register/unregister the properties on the ID type specified by the
        # IdPropertyGroup in addition to registering the classes.
        register_classes, unregister_classes = register_classes_factory(classes)

        def _register():
            # Classes must be registered before the properties are registered on ID types
            register_classes()
            for id_prop_group in id_prop_groups:
                id_prop_group.register_prop()

        def _unregister():
            # Classes must be unregistered after the properties are unregistered on ID types
            for id_prop_group in id_prop_groups:
                id_prop_group.unregister_prop()
            unregister_classes()

        if return_funcs:
            # Return the functions as a tuple
            return _register, _unregister
        else:
            # Add the functions directly into the module's globals()
            calling_module_globals['register'] = _register
            calling_module_globals['unregister'] = _unregister
    else:
        if return_funcs:
            # Return the functions tuple
            return register_classes_factory(classes)
        else:
            # Get the functions
            _register, _unregister = register_classes_factory(classes)
            # and add them directly into the module's globals
            calling_module_globals['register'] = _register
            calling_module_globals['unregister'] = _unregister


def reverse_partition(s: str, delim: str = '.') -> tuple[str, str, str]:
    """str.partition partitions from the first found delimiter, this function partitions from the last found delimiter
    instead and when the delimiter is not found, the original string is returned as the last element instead of the
    first element"""
    index = s.rfind(delim)
    if index == -1:
        return '', '', s
    else:
        return s[:index], delim, s[index+1:]


class _SubModuleData(NamedTuple):
    module: ModuleType
    module_name_no_prefix: str
    package: ModuleType


# Extension of bpy.utils.register_submodule_factory that will also register modules without register and unregister
# functions and
def register_submodule_factory(module_name, submodule_names):
    """
    Utility function to create register and unregister functions
    which simply load submodules,
    calling their register & unregister functions if they exist.

    .. note::

       Modules are registered in the order given,
       unregistered in reverse order.
       The load/unload order may differ from register/unregister if a module is set to be registered before its package.

    :arg module_name: The module name, typically ``__name__``.
    :type module_name: string
    :arg submodule_names: List of submodule names to load and unload.
    :type submodule_names: list of strings
    :return: register and unregister functions.
    :rtype: tuple pair of functions
    """

    module = None
    # It's possible that a submodule may want to be registered before its package, in which case, we need to maintain
    # two lists, since the package must be loaded first
    submodules_load_order: list[ModuleType] = []
    submodules_register_order: list[_SubModuleData] = []

    def _register():
        nonlocal module
        try:
            module = __import__(name=module_name, fromlist=submodule_names)
        except Exception as e:
            # Resilience against errors that occur on import. This is only really useful for development, since it will
            # force the modules to be reloaded upon reloading the addon.
            from sys import modules
            for submodule_name in reversed(submodule_names):
                full_module_name = module_name + '.' + submodule_name
                if full_module_name in modules:
                    del modules[full_module_name]
            raise e

        # Map each submodule name to its package name
        # reverse-partition each "package.subpackage.module" submodule name to get
        # {"package.subpackage.module": "package.subpackage"}
        submodule_name_to_package_name: dict[str, str] = {s: reverse_partition(s)[0] for s in submodule_names}

        # Submodules will be entered into this dict in the order they would get loaded based on their registration order
        # (packages will always be before their submodules). This doesn't correspond to the actual load order of the
        # submodules because submodules can load other submodules via imports, and walk_packages used in the main
        # __init__.py imports (and thus loads) each package.
        module_lookup: dict[str, _SubModuleData] = {}

        def get_submodule_data(module_name: str):
            if module_name in module_lookup:
                return module_lookup[module_name]
            else:
                package_name = submodule_name_to_package_name[module_name]
                if package_name:
                    package_data = get_submodule_data(package_name)
                    package = package_data.module
                else:
                    # If the package_name is '', it indicates that the package is the main module
                    package = module
                # given "package.subpackage.module", get "module"
                module_name_no_prefix = reverse_partition(module_name)[2]
                submodule = getattr(package, module_name_no_prefix)
                submodule_data = _SubModuleData(submodule, module_name_no_prefix, package)
                module_lookup[module_name] = submodule_data
                return submodule_data

        submodules_register_order[:] = (get_submodule_data(name) for name in submodule_name_to_package_name.keys())

        submodules_load_order[:] = (submodule_data.module for submodule_data in module_lookup.values())

        successful_registration = []
        mod = None
        try:
            for submodule_data in submodules_register_order:
                mod = submodule_data.module
                if hasattr(mod, 'register'):
                    mod.register()
                    successful_registration.append(mod)
        except Exception as e:
            # Resilience against errors when calling .register of modules
            print("Error occurred during registration, attempting unregister and module unload")
            # Attempt to unregister the module that failed to register
            if hasattr(mod, 'unregister'):
                # noinspection PyBroadException
                try:
                    mod.unregister()
                except Exception:
                    # Since register() failed part way through, we expect unregister() to fail part way through too
                    pass
            # Unregister modules that were successfully registered
            for mod in successful_registration:
                try:
                    if hasattr(mod, 'unregister'):
                        mod.unregister()
                except Exception as unregister_exception:
                    print(f"Ignoring exception when unregistering {mod.__name__}: {unregister_exception}")
            from sys import modules
            # Delete all the modules
            for mod in reversed(submodules_load_order):
                mod_name = mod.__name__
                if mod_name in modules:
                    del modules[mod_name]
            raise e

    def _unregister():
        from sys import modules
        exception = None
        for submodule_data in reversed(submodules_register_order):
            mod = submodule_data.module
            try:
                if hasattr(mod, 'unregister'):
                    mod.unregister()
            except Exception as e:
                # Resilience against errors occurring during .unregister()
                print(f"Exception occurred unregistering {mod.__name__}: {e}")
                if exception is None:
                    # Record that there was an exception, if there's more than one, we'll ignore all but rhe first
                    exception = e
            finally:
                delattr(submodule_data.package, submodule_data.module_name_no_prefix)
        submodules_register_order.clear()

        # Delete all the modules
        for mod in reversed(submodules_load_order):
            del modules[mod.__name__]
        submodules_load_order.clear()

        if exception is not None:
            raise exception

    return _register, _unregister
