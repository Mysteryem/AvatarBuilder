from bpy.types import Operator, Context, PropertyGroup, OperatorProperties
from bpy.props import StringProperty, EnumProperty, BoolProperty, IntProperty

from abc import abstractmethod
from typing import Optional, Generic, TypeVar, Union
from dataclasses import dataclass, field

from .utils import PropCollectionType
from .registration import OperatorBase
from . import utils


"""
Base classes for quickly creating Operators for controlling custom CollectionProperties 
"""
B = TypeVar('B', bound='ContextCollectionOperatorBase')
OM = TypeVar('OM', bound=Operator)


# Ideally, this would extend abc.ABC, but Blender has issues with mixing metaclasses (Operator's metaclass is
# bpy_types.RNAMeta)
class ContextCollectionOperatorBase:
    @staticmethod
    def index_in_bounds(collection: PropCollectionType, active_index: int):
        return 0 <= active_index < len(collection)

    @classmethod
    @abstractmethod
    def get_collection(cls, context: Context) -> Optional[PropCollectionType]:
        """Get the collection from the context"""
        ...

    @classmethod
    @abstractmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        """Get the active index from the context"""
        ...

    @classmethod
    @abstractmethod
    def set_active_index(cls, context: Context, value: int):
        """Set the active index in the context"""
        ...

    @classmethod
    def active_index_in_bounds(cls, context: Context):
        """Check if the active index is within the bounds of the collection.
        Returns False if either the collection or active index does not exist."""
        collection = cls.get_collection(context)
        active_index = cls.get_active_index(context)
        if collection is None or active_index is None:
            return False
        else:
            return cls.index_in_bounds(collection, active_index)

    @classmethod
    def op_builder(cls: type[B], class_name_prefix: str, bl_idname_prefix: str, element_label: str,
                   module: Optional[str] = None) -> 'SimpleControlOpBuilder[B]':
        if module is None:
            module = cls.__module__
        return SimpleControlOpBuilder(cls, class_name_prefix, bl_idname_prefix, element_label, module)


E = TypeVar('E', bound=PropertyGroup)


# noinspection PyAbstractClass
class CollectionAddBase(ContextCollectionOperatorBase, Generic[E], OperatorBase):
    """Add a new item to the collection and optionally set it as the active item"""
    bl_label = "Add"
    bl_options = {'UNDO'}
    _use_positional_description = True
    """Position is irrelevant for some collection properties, setting this to False in the subclass will use the
     bl_description or __doc__ of the class instead"""

    _position_items = (
        ('BOTTOM', 'Bottom', "Add the new item to the bottom"),
        ('TOP', 'Top', "Add the new item to the top"),
        ('BEFORE', "Before Active", "Insert the new item before the active item"),
        ('AFTER', "After Active", "Insert the new item after the active item"),
    )
    _description_lookup: dict[str, str] = {item[0]: item[2] for item in _position_items}

    name: StringProperty(name="New item name", description="Name of the newly created element (optional)")
    position: EnumProperty(
        name="Position",
        items=_position_items,
        default='BOTTOM',
    )
    set_as_active: BoolProperty(
        name="Set Active Index",
        description="Set the newly created element as active",
        default=True,
    )

    # noinspection PyUnresolvedReferences
    @classmethod
    def description(cls, context: Context, properties: OperatorProperties) -> str:
        if cls._use_positional_description:
            if not properties.is_property_set('position'):
                last_properties = context.window_manager.operator_properties_last(cls.bl_idname)
                if last_properties:
                    position = last_properties.position
                else:
                    position = properties.position
            else:
                # When not set, this will get the default
                position = properties.position
            lookup = cls._description_lookup
            if position in lookup:
                return lookup[position]
            else:
                # Shouldn't happen, but will fall back to class description or otherwise docstring
                pass
        return getattr(cls, 'bl_description', cls.__doc__)

    def set_new_item_name(self, data: PropCollectionType, added: E):
        """Set the name of a newly created item, defaults to settings .name to self.name"""
        if self.name:
            added.name = self.name

    def modify_newly_created(self, context: Context, data: PropCollectionType, added: E):
        """Modify the newly created item, by default, calls self.set_new_item_name"""
        self.set_new_item_name(data, added)

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)

        if data is None:
            return {'CANCELLED'}

        added = data.add()
        self.modify_newly_created(context, data, added)

        added_item_index = len(data) - 1
        new_item_index = added_item_index
        if self.position == 'TOP':
            new_item_index = 0
            data.move(added_item_index, new_item_index)
        elif self.position == 'BEFORE':
            new_item_index = self.get_active_index(context)
            data.move(added_item_index, new_item_index)
        elif self.position == 'AFTER':
            new_item_index = self.get_active_index(context) + 1
            data.move(added_item_index, new_item_index)

        if self.set_as_active:
            self.set_active_index(context, new_item_index)
        return {'FINISHED'}


# noinspection PyAbstractClass
class CollectionDuplicateBase(CollectionAddBase[E]):
    """Duplicate the active item of the collection"""
    bl_label = "Duplicate"

    index_being_duplicated: IntProperty(options={'HIDDEN'})

    @classmethod
    def poll(cls, context: Context) -> bool:
        # Can't duplicate if there isn't an active item to duplicate
        return cls.active_index_in_bounds(context)

    def modify_newly_created(self, context: Context, data: PropCollectionType, added: E):
        source = data[self.index_being_duplicated]

        # Copy every property from source to added
        utils.id_prop_group_copy(source, added)

        # Set new element name and anything else
        super().modify_newly_created(context, data, added)

    def execute(self, context: Context) -> set[str]:
        # We guarantee that the index exists via the poll method
        self.index_being_duplicated = self.get_active_index(context)
        # Create the new element, run modify_newly_created and then set as active (if set_as_active is True)
        return super().execute(context)


# noinspection PyAbstractClass
class CollectionRemoveBase(ContextCollectionOperatorBase, OperatorBase):
    """Remove the active item from the collection"""
    bl_label = "Remove"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        if not cls.active_index_in_bounds(context):
            return cls.poll_fail("No active element")
        return True

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)
        active_index = self.get_active_index(context)

        if data is None or active_index is None:
            return {'CANCELLED'}

        data.remove(active_index)
        was_last_or_out_of_bounds = active_index >= len(data)
        if was_last_or_out_of_bounds:
            new_active_index = max(0, active_index - 1)
            if new_active_index != active_index:
                self.set_active_index(context, new_active_index)
        return {'FINISHED'}


# noinspection PyAbstractClass
class CollectionClearBase(ContextCollectionOperatorBase, OperatorBase):
    """Clear the collection"""
    bl_label = "Clear"
    bl_options = {'UNDO'}

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)
        if data is not None:
            data.clear()
        return {'FINISHED'}


# noinspection PyAbstractClass
class CollectionMoveBase(ContextCollectionOperatorBase, OperatorBase):
    """Move the active item in the collection"""
    bl_label = "Move"
    bl_options = {'UNDO'}

    type: EnumProperty(
        items=(
            ('UP', "Up", "Move active item up, wrapping around if already at the top"),
            ('DOWN', "Down", "Move active item down, wrapping around if already at the bottom"),
            ('TOP', "Top", "Move active item to the top"),
            ('BOTTOM', "Bottom", "Move active item to the bottom"),
        ),
        name="Type",
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        if not cls.active_index_in_bounds(context):
            return cls.poll_fail("No active element")
        collection = cls.get_collection(context)
        # Check the collection separately in-case cls.active_index_in_bounds has been overridden and doesn't care
        # about whether the collection is None
        if collection is None:
            return cls.poll_fail("Collection not found")
        if len(collection) <= 1:
            return cls.poll_fail("Collection must have two or more elements")
        return True

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)
        active_index = self.get_active_index(context)

        if data is None or active_index is None:
            return {'CANCELLED'}

        command = self.type
        if command == 'UP':
            # Previous index, with wrap around to the bottom
            new_index = (active_index - 1) % len(data)
            data.move(active_index, new_index)
            self.set_active_index(context, new_index)
        elif command == 'DOWN':
            # Next index, with wrap around to the top
            new_index = (active_index + 1) % len(data)
            data.move(active_index, new_index)
            self.set_active_index(context, new_index)
        elif command == 'TOP':
            top_index = 0
            if active_index != top_index:
                data.move(active_index, top_index)
                self.set_active_index(context, top_index)
        elif command == 'BOTTOM':
            bottom_index = len(data) - 1
            if active_index != bottom_index:
                data.move(active_index, bottom_index)
                self.set_active_index(context, bottom_index)
        return {'FINISHED'}


@dataclass
class _SimpleControlOpData(Generic[B, OM]):
    base: type[B]
    module: str
    class_name: str
    bl_idname: str
    docstring: str
    op_base: type[OM]

    # Would have used __call__ instead of build, but PyCharm seems to be bugged and its type checking breaks with
    #   built_class = my_op_data()
    # But does work with
    #   built_class = my_op_data.__call__()
    def build(self) -> Union[type[B], type[OM]]:
        # type(str, tuple[type, ...], dict[str, Any]) only gives return type hint of 'type'
        # noinspection PyTypeChecker
        return type(
            self.class_name,
            (self.base, self.op_base),
            dict(__doc__=self.docstring, __module__=self.module, bl_idname=self.bl_idname)
        )

    def decorate(self, cls):
        """Decorate an existing class with the generated bl_idname and docstring. This is intended for when the Operator
        needs to override or declare new methods or provide additional documentation"""
        # In the future maybe we could automatically create a subclass that has self.base and self.op_base as its bases
        # if they're missing from cls. Currently, this isn't important, since the classes being decorated always include
        # both base classes in their bases already.
        #
        # Only set the __doc__ attribute when it doesn't already exist in cls.__dict__. This way, we can write more
        # specific docstrings if the operator has additional features.
        # We don't bother setting bl_description, since class registration will set it automatically
        if not cls.__doc__:
            cls.__doc__ = self.docstring
        # For now, we're always setting the bl_idname, it shouldn't exist in cls.__dict__
        if 'bl_idname' in cls.__dict__:
            raise RuntimeError(f"bl_idname already exists on {cls} when it shouldn't")
        else:
            cls.bl_idname = self.bl_idname
        return cls


@dataclass
class SimpleControlOpBuilder(Generic[B]):
    base: type[B]
    class_name_prefix: str
    bl_idname_prefix: str
    element_label: str
    add: _SimpleControlOpData[B, CollectionAddBase] = field(init=False)
    remove: _SimpleControlOpData[B, CollectionRemoveBase] = field(init=False)
    move: _SimpleControlOpData[B, CollectionMoveBase] = field(init=False)
    clear: _SimpleControlOpData[B, CollectionClearBase] = field(init=False)
    duplicate: _SimpleControlOpData[B, CollectionDuplicateBase] = field(init=False)
    module: Optional[str] = None

    def __post_init__(self):
        # PyCharm doesn't infer types of Generic dataclasses, so we must specify the return type hint ourself:
        # https://youtrack.jetbrains.com/issue/PY-48912/PyCharm-does-not-infer-type-of-generic-dataclass-instance
        def make_data(class_suffix: str, bl_idname_suffix: str, docstring: str, op_base: type[OM]
                      ) -> _SimpleControlOpData[B, OM]:
            module = self.module
            if module is None:
                module = self.base.__module__
            return _SimpleControlOpData(
                self.base,
                module,
                self.class_name_prefix + class_suffix,
                self.bl_idname_prefix + bl_idname_suffix,
                docstring.format(self.element_label),
                op_base,
            )

        self.add = make_data('Add', '_add', "Add a new {}", CollectionAddBase)
        self.remove = make_data('Remove', '_remove', "Remove the active {}", CollectionRemoveBase)
        self.move = make_data('Move', '_move', "Move the active {}", CollectionMoveBase)
        self.clear = make_data('Clear', '_clear', "Remove every {}", CollectionClearBase)
        self.duplicate = make_data('Duplicate', '_duplicate', "Duplicate the active {}", CollectionDuplicateBase)
