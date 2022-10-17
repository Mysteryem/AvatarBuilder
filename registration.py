from collections import defaultdict
from typing import TypeVar, Union, Generic, Optional

import bpy
from bpy.types import Panel, Operator, UIList, Menu, ID, Bone, PoseBone, PropertyGroup
from bpy.props import PointerProperty, CollectionProperty, IntProperty

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
            else:
                prefix = f"{_BL_ID_PREFIX}_"
            if not cls.bl_idname.startswith(prefix):
                cls.bl_idname = prefix + cls.bl_idname
        # if prefix_id:
        #     cls.bl_idname = _BL_ID_PREFIX + cls.bl_idname
        # elif hasattr(cls, 'bl_idname'):
        #     raise ValueError(f"{cls} has bl_idname, but it was not set to be prefixed!")

# from inspect import isclass
# from pkgutil import iter_modules
# from pathlib import Path
# from importlib import import_module

# bl_classes = []

# package_dir = Path(__file__).resolve().parent
# for _, module_name, _ in pkgutil.walk_packages(package_dir):
#     module = import_module(f"{__name__}.{module_name}")
#     for attribute_name in dir(module):
#         attribute = getattr(module, attribute_name)
#
#         if isclass(attribute) and hasattr(attribute, 'bl_idname'):
#             bl_classes.append(attribute)

# TODO: maybe replace this with a method that looks through the current variables for classes that have
#  bl_idname
# bl_classes = [
#     SceneBuildSettingsControl,
#     SceneBuildSettingsUIList,
#     SceneBuildSettingsMenu,
#     SceneBuildSettings,
#     ScenePropertyGroup,
#     ScenePanel,
#     BuildAvatarOp,
#     DeleteExportScene,
#     ObjectBuildSettingsControl,
#     ObjectBuildSettingsUIList,
#     ObjectBuildSettings,
#     ObjectPropertyGroup,
#     ObjectPanel,
# ]

# prefix_classes(bl_classes)

# _register_classes, _unregister_classes = bpy.utils.register_classes_factory(bl_classes)


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


class CollectionPropBase(Generic[E]):
    # Unfortunately, PyCharm won't pick up the typing if we try to set
    # data: CollectionProperty(type=<type as argument>)
    # using a passed in argument, so we must provide the annotation in subclasses
    #
    # By setting this property's type to None, it will error if it's not overridden
    data: CollectionProperty(type=None)
    active_index: IntProperty()

    @property
    def active(self) -> Optional[E]:
        if 0 <= self.active_index < len(self.data):
            return self.data[self.active_index]
        else:
            return None


def register_classes_factory(classes):
    prefix_classes(classes)
    return bpy.utils.register_classes_factory(classes)


def register_module_classes_factory(calling_module_name, calling_module_globals):
    # TODO: Alternative could be to iterate through dir(sys.modules[calling_module_name])
    #  or by importing the module
    print(f"Looking for classes to register in {calling_module_name}")
    classes: list[type] = []
    id_prop_groups: list[type[IdPropertyGroup]] = []
    for attribute in calling_module_globals.values():
        if isinstance(attribute, type) and attribute.__module__ == calling_module_name:
            if hasattr(attribute, 'bl_idname'):
                print(f"\tFound {attribute.__name__} in {calling_module_name} via bl_idname")
                classes.append(attribute)
            elif issubclass(attribute, bpy.types.PropertyGroup):
                print(f"\tFound {attribute.__name__} in {calling_module_name} via bpy.types.PropertyGroup")
                classes.append(attribute)
                if issubclass(attribute, IdPropertyGroup):
                    print(f"\t\tIt is also an {IdPropertyGroup.__name__} and will be registered on"
                          f" {attribute._registration_type} as {attribute._registration_name}")
                    id_prop_groups.append(attribute)
            elif issubclass(attribute, bpy.types.bpy_struct):
                print(f"\tFound {attribute.__name__} in {calling_module_name} via bpy.types.bpy_struct (it has been skipped)")

    if id_prop_groups:
        register_classes, unregister_classes = register_classes_factory(classes)

        def register():
            register_classes()
            for id_prop_group in id_prop_groups:
                id_prop_group.register_prop()

        def unregister():
            for id_prop_group in id_prop_groups:
                id_prop_group.unregister_prop()
            unregister_classes()

        return register, unregister
    else:
        return register_classes_factory(classes)


def dummy_register_factory():
    def dummy(): return None
    return dummy, dummy


register, unregister = dummy_register_factory()
