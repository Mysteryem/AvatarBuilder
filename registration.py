from collections import defaultdict
from typing import Type

import bpy
from bpy.types import Panel, Operator, UIList, Menu

# Prefix
_BL_ID_PREFIX = "mysteryem_avatar_builder"
_PROP_PREFIX = _BL_ID_PREFIX

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


def get_panel_prefix(panel_cls: Type[Panel], node_type=None, node_engine_type=None):
    space_type = panel_cls.bl_space_type
    if space_type == 'NODE_EDITOR':
        return _NODE_EDITOR_PANEL_SPACE_TYPE_PREFIX[node_type][node_engine_type]
    else:
        return _PANEL_SPACE_TYPE_PREFIX[space_type]


def prefix_classes(classes):
    for cls in classes:
        if hasattr(cls, 'bl_idname'):
            if issubclass(cls, Panel):
                cls.bl_idname = get_panel_prefix(cls) + "_PT_" + _BL_ID_PREFIX + "_" + cls.bl_idname
            elif issubclass(cls, Operator):
                cls.bl_idname = _BL_ID_PREFIX + "." + cls.bl_idname
            elif issubclass(cls, UIList):
                cls.bl_idname = "AVATAR_BUILDER_UL_" + cls.bl_idname
            elif issubclass(cls, Menu):
                cls.bl_idname = "AVATAR_BUILDER_MT_" + cls.bl_idname
            else:
                cls.bl_idname = _BL_ID_PREFIX + "_" + cls.bl_idname
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


def register_classes_factory(classes):
    # TODO: Is this going to prefix every time we unload and re-load the addon?
    prefix_classes(classes)
    return bpy.utils.register_classes_factory(classes)


def register_module_classes_factory(calling_module_name, calling_module_globals):
    # TODO: Alternative could be to iterate through dir(sys.modules[calling_module_name])
    #  or by importing the module
    classes = []
    for attribute in calling_module_globals.values():
        if isinstance(attribute, type) and attribute.__module__ == calling_module_name:
            if hasattr(attribute, 'bl_idname'):
                print(f"Found {attribute.__name__} in {calling_module_name} via bl_idname")
                classes.append(attribute)
            elif issubclass(attribute, bpy.types.PropertyGroup):
                print(f"Found {attribute.__name__} in {calling_module_name} via bpy.types.PropertyGroup")
                classes.append(attribute)
            elif issubclass(attribute, bpy.types.bpy_struct):
                print(f"Found {attribute.__name__} in {calling_module_name} via bpy.types.bpy_struct (it has been skipped)")

    return register_classes_factory(classes)
