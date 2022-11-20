from bpy.types import Context, Operator, Menu
from bpy.props import StringProperty, EnumProperty, BoolProperty

from typing import cast, Optional, Iterable, Literal, Union
import operator
from functools import reduce
from dataclasses import dataclass, InitVar, field

from .registration import register_module_classes_factory
from .extensions import (
    ObjectPropertyGroup,
    ScenePropertyGroup,
    ObjectBuildSettings,
    SceneBuildSettings,
)
from .utils import id_prop_copy


@dataclass
class CopyPropsItem:
    """Represents a copyable property or group of copyable properties"""
    id: str
    display_name: str
    display_description: str
    display_icon: str
    unique_id: InitVar[int] = None
    group_props: InitVar[Iterable['CopyPropsItem']] = ()
    class_name_suffix: str = ""
    unique_bit_field_id: Optional[int] = field(default=None, init=False)
    # Since we're declaring an attribute called 'type' it would hide the 'type' from builtins, so we need to declare
    # these attributes before the attribute called 'type'
    self_menu: type[Menu] = field(default=None, init=False)
    copy_menu: type[Menu] = field(default=None, init=False)
    type: Literal['ALL', 'MESH', 'ARMATURE'] = 'ALL'

    class CopyObjectPropsSelfMenuBase(Menu):
        """Base class for a Menu for copying properties from one object settings to another on the same object"""
        bl_label = "Copy To..."

        # To be overridden
        props = set()

        def draw(self, context: Context):
            layout = self.layout
            scene = context.scene

            object_group = ObjectPropertyGroup.get_group(context.object)
            displayed_settings = object_group.get_displayed_settings(scene)
            # We exclude the currently displayed settings as there's no point in pasting to the same settings that we're
            # copying from
            if displayed_settings:
                all_build_settings_names = {displayed_settings.name}
            else:
                # Generally there will always be some displayed settings
                all_build_settings_names = set()
            # If no operators get drawn, all_build_settings_names will still equal itself from when it was created
            none_drawn_set = all_build_settings_names.copy()

            def draw_copy_operator(build_settings: Union[ObjectBuildSettings, SceneBuildSettings]):
                name = build_settings.name
                if name not in all_build_settings_names:
                    all_build_settings_names.add(name)
                    options = layout.operator(CopyObjectProperties.bl_idname, text=name)
                    options.mode = 'SELF'
                    options.paste_to_name = name
                    options.props_to_copy = self.props

            # Draw the operator to copy settings to each SceneBuildSettings (excluding the currently displayed settings)
            for scene_build_settings in ScenePropertyGroup.get_group(scene).collection:
                draw_copy_operator(scene_build_settings)

            # There may be some orphaned settings (matches no SceneBuildSettings), in which case, we should add a
            # separator before them in the menu to signify that they're different
            needs_separator_if_there_are_orphaned_settings = bool(all_build_settings_names)

            # Draw the operator to copy settings to each orphaned ObjectBuildSettings (excluding the currently displayed
            # settings)
            for object_build_settings in object_group.collection:
                is_orphaned = object_build_settings.name not in all_build_settings_names
                if is_orphaned:
                    # Add the separator if we haven't already
                    if needs_separator_if_there_are_orphaned_settings:
                        layout.separator()
                        # Now that the separator has been added, we don't want to add it again
                        needs_separator_if_there_are_orphaned_settings = False
                    # And finally draw the operator for copying to the orphaned ObjectBuildSettings in the menu
                    draw_copy_operator(object_build_settings)

            no_operators_drawn = none_drawn_set == all_build_settings_names
            if no_operators_drawn:
                layout.label(text="No Other Scene Settings Found")

    # Base class for a menu for copying properties from the active object to other selected objects and for displaying
    # the menu for copying properties from one object settings to another on the same object
    class CopyObjectPropsMenuBase(Menu):
        """Base class for a menu for copying properties from the active object to other selected objects and for
        displaying the menu for copying properties from one object settings to another on the same object"""
        bl_label = "Copy Properties"
        # To be overridden
        props = set()
        sub_menu: type[Menu]

        def draw(self, context: Context):
            layout = self.layout
            options = layout.operator(CopyObjectProperties.bl_idname, text="Copy To Other Selected Objects")
            options.mode = 'OTHER_SELECTED'
            options.paste_to_name = ''
            options.props_to_copy = self.props

            layout.separator()

            layout.menu(self.sub_menu.bl_idname)

    def _post_init_bit_field_id(self, unique_id: Optional[int], group_props: Iterable['CopyPropsItem']):
        """Set the internal bitfield id, for use with an ENUM_FLAG EnumProperty, based on either the unique_id or
        group_props"""
        if group_props:
            if unique_id is not None:
                raise ValueError("Only one of group_props or unique_id can be supplied")
            else:
                self.unique_bit_field_id = reduce(operator.or_, (prop.unique_bit_field_id for prop in group_props), 0)
        else:
            if unique_id is None:
                raise ValueError("At least one of unique_bitfield_id or unique_id must be supplied")
            else:
                self.unique_bit_field_id = 1 << unique_id

    def _post_init_menu_classes(self):
        """Create the menu classes used for displaying the operator to copy this property (or group of properties)"""
        prop_id = self.id
        props_set = {prop_id}
        # Lowercase name will be appended to the bl_idnames
        lower_name = prop_id.lower()
        class_suffix = self.class_name_suffix

        if not self.self_menu:
            # (sub)Menu subclass for copying properties to other settings on the same object
            self_menu_name = f'CopyObjectPropsSelfMenu{class_suffix}'
            self_menu_class_attributes = dict(
                bl_idname='object_build_settings_copy_self_' + lower_name,
                props=props_set,
            )
            self_menu_class = cast(
                type[CopyPropsItem.CopyObjectPropsSelfMenuBase],
                type(self_menu_name, (CopyPropsItem.CopyObjectPropsSelfMenuBase,), self_menu_class_attributes)
            )
            self.self_menu = self_menu_class

        if not self.copy_menu:
            # Menu subclass for copying properties to other selected objects or showing the submenu for copying properties
            # to other settings on the same object
            copy_menu_name = f'CopyObjectPropsMenu{class_suffix}'
            copy_menu_class_attributes = dict(
                bl_idname='object_build_settings_copy_' + lower_name,
                props=props_set,
                sub_menu=self.self_menu,
                bl_label=f"Copy {self.display_name} Properties",
            )
            copy_menu_class = cast(
                type[CopyPropsItem.CopyObjectPropsMenuBase],
                type(copy_menu_name, (CopyPropsItem.CopyObjectPropsMenuBase,), copy_menu_class_attributes)
            )
            self.copy_menu = copy_menu_class

    def __post_init__(self, unique_id: Optional[int], group_props: Iterable['CopyPropsItem']):
        # Set the class name suffix if not provided
        class_name_suffix = self.class_name_suffix
        if not class_name_suffix:
            self.class_name_suffix = self.id.replace('_', ' ').title().replace(" ", "")
        # Set the unique_id to a bitfield value
        self._post_init_bit_field_id(unique_id, group_props)
        # Since we can't provide arguments to menus, we need to create menus specifically for this option
        # Create the Menu classes
        self._post_init_menu_classes()

    def to_enum_item(self):
        """Get the enum item for use in an EnumProperty's 'items' argument"""
        return self.id, self.display_name, self.display_description, self.display_icon, self.unique_bit_field_id

    def is_all(self):
        """:return: True if the property is used by all Objects"""
        return self.type == 'ALL'

    def is_mesh(self):
        """:return: True if the property is used by Mesh Objects"""
        return self.is_all() or self.type == 'MESH'

    def is_armature(self):
        """:return: True if the property is used by Armature Objects"""
        return self.is_all() or self.type == 'ARMATURE'


# Icons match the UI boxes
COPY_GENERAL_OBJECT_SETTINGS = CopyPropsItem(
    id='GENERAL',
    display_name="General",
    display_description="General Object settings",
    display_icon='OBJECT_DATA',
    unique_id=0,
)
COPY_ARMATURE_POSE_SETTINGS = CopyPropsItem(
    id='POSE',
    display_name="Pose",
    display_description="Pose settings",
    display_icon='ARMATURE_DATA',
    unique_id=1,
    type='ARMATURE',
)
COPY_MESH_VERTEX_GROUPS_SETTINGS = CopyPropsItem(
    id='VERTEX_GROUPS',
    display_name="Vertex Groups",
    display_description="Vertex Group settings",
    display_icon='GROUP_VERTEX',
    unique_id=2,
    type='MESH',
)
COPY_MESH_SHAPE_KEYS_SETTINGS = CopyPropsItem(
    id='SHAPE_KEYS',
    display_name="Shape Keys",
    display_description="Shape Key settings",
    display_icon='SHAPEKEY_DATA',
    unique_id=3,
    type='MESH',
)
COPY_MESH_MODIFIERS_SETTINGS = CopyPropsItem(
    id='MODIFIERS',
    display_name="Modifiers",
    display_description="Modifier settings",
    display_icon='MODIFIER_DATA',
    unique_id=4,
    type='MESH',
)
COPY_MESH_UV_LAYERS_SETTINGS = CopyPropsItem(
    id='UV_LAYERS',
    display_name="UV Layers",
    display_description="UV Layer settings",
    display_icon='GROUP_UVS',
    unique_id=5,
    type='MESH',
)
COPY_MESH_MATERIALS_SETTINGS = CopyPropsItem(
    id='MATERIALS',
    display_name="Materials",
    display_description="Material settings",
    display_icon='MATERIAL_DATA',
    unique_id=6,
    type='MESH',
)
COPY_MESH_VERTEX_COLORS_SETTINGS = CopyPropsItem(
    id='VERTEX_COLORS',
    display_name="Vertex Colors",
    display_description="Vertex Color settings",
    display_icon='GROUP_VCOL',
    unique_id=7,
    type='MESH'
)
_all_unique_copy_props = (
    COPY_GENERAL_OBJECT_SETTINGS,
    COPY_ARMATURE_POSE_SETTINGS,
    COPY_MESH_VERTEX_GROUPS_SETTINGS,
    COPY_MESH_SHAPE_KEYS_SETTINGS,
    COPY_MESH_MODIFIERS_SETTINGS,
    COPY_MESH_UV_LAYERS_SETTINGS,
    COPY_MESH_MATERIALS_SETTINGS,
    COPY_MESH_VERTEX_COLORS_SETTINGS,
)
# Shortcuts for groups of items at a time
# Bitwise ORs of groups of the items. Note that if we call with operator with {'MESH_MODIFIERS'} as the
# props_to_copy, for example, the received set will actually be {'ALL', 'MESH_MODIFIERS', 'ALL_MESH'}. I guess Blender
# does a bitwise AND and checks for non-zero result, so both of the options will be present in the set. Therefore,
# COPY_ALL_SETTINGS and the other grouped items should only be used as an input to the Operator and should not be used
# within the Operator itself
COPY_ALL_SETTINGS = CopyPropsItem(
    'ALL',
    "All",
    "All settings",
    'DUPLICATE',
    group_props=_all_unique_copy_props,
)
COPY_ALL_ARMATURE_SETTINGS = CopyPropsItem(
    'ALL_ARMATURE',
    "All Armature",
    "All settings for Armature Objects",
    'ARMATURE_DATA',
    type='ARMATURE',
    group_props=filter(CopyPropsItem.is_armature, _all_unique_copy_props),
)
COPY_ALL_MESH_SETTINGS = CopyPropsItem(
    'ALL_MESH',
    "All Mesh",
    "All settings for Mesh Objects",
    'MESH_DATA',
    type='MESH',
    group_props=filter(CopyPropsItem.is_mesh, _all_unique_copy_props),
)
_grouped_copy_props = (COPY_ALL_SETTINGS, COPY_ALL_ARMATURE_SETTINGS, COPY_ALL_MESH_SETTINGS)
_all_copy_props = _all_unique_copy_props + _grouped_copy_props


class CopyObjectProperties(Operator):
    """Copy Object properties from the active object to other selected objects or a different group on the active
    object"""
    bl_idname = 'copy_object_props'
    bl_label = "Copy Properties"
    bl_options = {'REGISTER', 'UNDO'}

    paste_to_name: StringProperty(
        name="Paste To",
        description="Name of the settings to paste to. When empty, will default to the currently displayed settings of"
                    " the active Object"
    )
    props_to_copy: EnumProperty(
        items=tuple(map(CopyPropsItem.to_enum_item, _all_copy_props)),
        options={'ENUM_FLAG'},
        default={COPY_ALL_SETTINGS.id},
    )
    mode: EnumProperty(
        items=(
            ('OTHER_SELECTED', "Other Selected", "Other selected objects"),
            ('SELF', "Self", "Self"),
        ),
        default='OTHER_SELECTED',
        description="Mode to specify which objects to paste to",
    )
    create: BoolProperty(
        name="Create",
        description="Create new settings when the pasted to settings don't already exist",
        default=True
    )

    def draw(self, context: Context):
        layout = self.layout
        layout.prop(self, 'mode')
        layout.prop(self, 'paste_to_name')
        layout.prop(self, 'create')

    def execute(self, context: Context) -> set[str]:
        props_to_copy: set[str] = self.props_to_copy
        # Remove the grouped items from the set
        props_to_copy = props_to_copy.difference(item.id for item in _grouped_copy_props)
        if not props_to_copy:
            # No properties to copy, so nothing to do. The user can change the properties, so we still need to push an
            # undo
            self.report({'ERROR_INVALID_INPUT'}, "No properties selected to copy")
            return {'FINISHED'}
        mode = self.mode
        copy_object = context.object
        copy_from_settings = ObjectPropertyGroup.get_group(copy_object).get_displayed_settings(context.scene)
        paste_settings_name = self.paste_to_name
        if copy_from_settings is None:
            self.report({'ERROR'}, "Currently displayed Object settings not found")
            # Nothing the user can change will cause the Operator to do anything, so don't push an undo
            return {'CANCELLED'}

        # When the settings to paste to is the empty string, default to the currently visible settings (which we are
        # copying from)
        if not paste_settings_name:
            paste_settings_name = copy_from_settings.name

        # Get the objects we're  pasting to
        paste_objects = set()
        if mode == 'OTHER_SELECTED':
            allowed_types = ObjectPropertyGroup.ALLOWED_TYPES
            paste_objects = set(o for o in context.selected_objects if o.type in allowed_types)
            # Exclude self
            paste_objects.discard(copy_object)
        elif mode == 'SELF':
            paste_objects = {copy_object}

            # If we're pasting to the same Object and settings we're copying from, there's nothing to do, so we can skip
            if copy_from_settings.name == paste_settings_name:
                return {'FINISHED'}

        create = self.create
        for paste_to_obj in paste_objects:
            settings_col = ObjectPropertyGroup.get_group(paste_to_obj).collection
            if paste_settings_name in settings_col:
                paste_to_settings = settings_col[paste_settings_name]
            elif create:
                paste_to_settings = settings_col.add()
                paste_to_settings.name_prop = paste_settings_name
            else:
                continue

            paste_to_mesh_settings = paste_to_settings.mesh_settings
            copy_from_mesh_settings = copy_from_settings.mesh_settings

            if COPY_GENERAL_OBJECT_SETTINGS.id in props_to_copy:
                paste_to_settings.join_order = copy_from_settings.join_order
                paste_to_settings.target_object_name = copy_from_settings.target_object_name
                paste_to_mesh_settings.ignore_reduce_to_two_meshes = copy_from_mesh_settings.ignore_reduce_to_two_meshes

            if COPY_ARMATURE_POSE_SETTINGS.id in props_to_copy:
                id_prop_copy(copy_from_settings, paste_to_settings, 'armature_settings')

            def copy_mesh_group(paste_prop):
                id_prop_copy(copy_from_mesh_settings, paste_to_mesh_settings, paste_prop)

            if COPY_MESH_MATERIALS_SETTINGS.id in props_to_copy:
                copy_mesh_group('material_settings')

            if COPY_MESH_MODIFIERS_SETTINGS.id in props_to_copy:
                copy_mesh_group('modifier_settings')

            if COPY_MESH_UV_LAYERS_SETTINGS.id in props_to_copy:
                copy_mesh_group('uv_settings')

            if COPY_MESH_VERTEX_GROUPS_SETTINGS.id in props_to_copy:
                copy_mesh_group('vertex_group_settings')

            if COPY_MESH_SHAPE_KEYS_SETTINGS.id in props_to_copy:
                copy_mesh_group('shape_key_settings')

            if COPY_MESH_VERTEX_COLORS_SETTINGS.id in props_to_copy:
                copy_mesh_group('vertex_color_settings')

        return {'FINISHED'}


# Using a function to avoid having to del the variables used, since, if the contents of the function were run directly
# when loading the module, self_menu and copy_menu would remain in globals() if not specifically deleted and then
# register_module_classes_factory would them both as classes to register.
# It also means we won't get any warnings about shadowing global variables in other functions in this file if they use
# the same variable names
def _add_copy_prop_menus_to_module():
    g = globals()
    used_names = set()
    # Add CopyProp Menu classes to globals() so that register_module_classes_factory picks them up
    for copy_prop in _all_copy_props:
        self_menu = copy_prop.self_menu
        self_menu_name = self_menu.__name__

        if self_menu_name in used_names:
            raise RuntimeError(f"{self_menu_name} is already in use by another class, this is a bug")

        used_names.add(self_menu_name)

        copy_menu = copy_prop.copy_menu
        copy_menu_name = copy_menu.__name__

        if copy_menu_name in used_names:
            raise RuntimeError(f"{copy_menu_name} is already in use by another class, this is a bug")

        used_names.add(copy_menu_name)

        # Add to globals
        g[self_menu_name] = self_menu
        g[copy_menu_name] = copy_menu


_add_copy_prop_menus_to_module()
# And tidy up by deleting the function
del _add_copy_prop_menus_to_module

# Since we added the Menu classes to the module's globals(), this will pick them up for registering
register, unregister = register_module_classes_factory(__name__, globals())
