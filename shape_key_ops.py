from typing import Optional

from bpy.props import EnumProperty
from bpy.types import UIList, Context, UILayout, Menu, Key

from .context_collection_ops import (
    ContextCollectionOperatorBase,
    PropCollectionType,
    CollectionAddBase,
)
from .extensions import ShapeKeyOp, ObjectBuildSettings, ObjectPropertyGroup, ShapeKeySettings
from .registration import register_module_classes_factory


class ShapeKeyOpsUIList(UIList):
    bl_idname = "shapekey_ops_list"

    def draw_item(self, context: Context, layout: UILayout, data, item: ShapeKeyOp, icon: int, active_data: ShapeKeyOp,
                  active_property: str, index: int = 0, flt_flag: int = 0):
        self.use_filter_show = False

        row = layout.row(align=True)

        op_type = item.type
        shape_keys = item.id_data.data.shape_keys

        if op_type in ShapeKeyOp.DELETE_OPS_DICT:
            op = ShapeKeyOp.DELETE_OPS_DICT[op_type]
            row.label(text=op.list_label, icon="TRASH")
            op.draw_props(row, shape_keys, item, "")
        elif op_type in ShapeKeyOp.MERGE_OPS_DICT:
            op = ShapeKeyOp.MERGE_OPS_DICT[op_type]

            if item.merge_grouping == 'CONSECUTIVE':
                mode_icon = ShapeKeyOp.GROUPING_CONSECUTIVE_ICON
            elif item.merge_grouping == 'ALL':
                mode_icon = ShapeKeyOp.GROUPING_ALL_ICON
            else:
                mode_icon = "NONE"

            row.label(text=op.list_label, icon="FULLSCREEN_EXIT")
            op.draw_props(row, shape_keys, item, "")
            options = row.operator('wm.context_cycle_enum', text="", icon=mode_icon)
            options.wrap = True
            options.data_path = 'object.' + item.path_from_id('merge_grouping')
        else:
            # This shouldn't happen normally
            row.label(text="ERROR: Unknown Op Type", icon="QUESTION")

    def draw_filter(self, context: Context, layout: UILayout):
        # No filter
        pass

    def filter_items(self, context: Context, data, property: str):
        # We always want to show every op in order because they are applied in series. No filtering or sorting is ever
        # enabled
        return [], []


class ShapeKeyOpsListBase(ContextCollectionOperatorBase):
    @staticmethod
    def get_shape_key_settings(context: Context) -> Optional[ObjectBuildSettings]:
        obj = context.object
        group = ObjectPropertyGroup.get_group(obj)
        return group.get_displayed_settings(context.scene)

    @classmethod
    def get_collection(cls, context: Context) -> Optional[PropCollectionType]:
        settings = cls.get_shape_key_settings(context)
        if settings is not None:
            return settings.mesh_settings.shape_key_settings.shape_key_ops.collection
        else:
            return None

    @classmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        settings = cls.get_shape_key_settings(context)
        if settings is not None:
            return settings.mesh_settings.shape_key_settings.shape_key_ops.active_index
        else:
            return None

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        settings = cls.get_shape_key_settings(context)
        if settings is not None:
            settings.mesh_settings.shape_key_settings.shape_key_ops.active_index = value


_op_builder = ShapeKeyOpsListBase.op_builder(
    class_name_prefix='ShapeKeyOpsList',
    bl_idname_prefix='shape_key_ops_list',
    element_label="shape key op",
)
ShapeKeyOpsListRemove = _op_builder.remove.build()
ShapeKeyOpsListMove = _op_builder.move.build()


@_op_builder.add.decorate
class ShapeKeyOpsListAdd(ShapeKeyOpsListBase, CollectionAddBase[ShapeKeyOp]):
    type: EnumProperty(
        items=ShapeKeyOp.TYPE_ITEMS,
        name="Type",
        description="Type of the added shape key op"
    )

    def modify_newly_created(self, context: Context, data: PropCollectionType, added: ShapeKeyOp):
        super().modify_newly_created(context, data, added)
        added.type = self.type


class ShapeKeyOpsListAddDeleteSubMenu(Menu):
    """Add an op that deletes shape keys"""
    bl_idname = 'shape_key_ops_list_add_delete_submenu'
    bl_label = "Delete"

    def draw(self, context: Context):
        layout = self.layout
        for op in ShapeKeyOp.DELETE_OPS_DICT.values():
            layout.operator(ShapeKeyOpsListAdd.bl_idname, text=op.menu_label).type = op.id


class ShapeKeyOpsListAddMergeSubMenu(Menu):
    """Add an op that merges shape keys"""
    bl_idname = 'shape_key_ops_list_add_merge_submenu'
    bl_label = "Merge"

    def draw(self, context: Context):
        layout = self.layout
        for op in ShapeKeyOp.MERGE_OPS_DICT.values():
            layout.operator(ShapeKeyOpsListAdd.bl_idname, text=op.menu_label).type = op.id


class ShapeKeyOpsListAddMenu(Menu):
    """Add a new shape key op to the list"""
    bl_idname = 'shape_key_ops_list_add_menu'
    bl_label = "Add"

    def draw(self, context: Context):
        layout = self.layout
        layout.menu(ShapeKeyOpsListAddDeleteSubMenu.bl_idname, icon='TRASH')
        layout.menu(ShapeKeyOpsListAddMergeSubMenu.bl_idname, icon='FULLSCREEN_EXIT')


def draw_shape_key_ops(shape_keys_box_col: UILayout, settings: ShapeKeySettings, shape_keys: Key):
    shape_key_ops = settings.shape_key_ops

    operations_title_row = shape_keys_box_col.row()
    operations_title_row.label(text="Operations")
    vertical_buttons_col = operations_title_row.row(align=True)
    vertical_buttons_col.menu(ShapeKeyOpsListAddMenu.bl_idname, text="", icon="ADD")
    vertical_buttons_col.operator(ShapeKeyOpsListRemove.bl_idname, text="", icon="REMOVE")
    vertical_buttons_col.separator()
    vertical_buttons_col.operator(ShapeKeyOpsListMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
    vertical_buttons_col.operator(ShapeKeyOpsListMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'
    shape_keys_box_col.template_list(
        ShapeKeyOpsUIList.bl_idname, "",
        shape_key_ops, 'collection',
        shape_key_ops, 'active_index',
        # With the buttons down the side, 4 rows is the minimum we can have, so we put the buttons on top
        sort_lock=True, rows=1)

    active_op_col = shape_keys_box_col.column(align=True)
    active_op = shape_key_ops.active
    if active_op:
        op_type = active_op.type
        if op_type in ShapeKeyOp.DELETE_OPS_DICT:
            if op_type == ShapeKeyOp.DELETE_AFTER:
                active_op_col.prop_search(active_op, 'delete_after_name', shape_keys, 'key_blocks')
            elif op_type == ShapeKeyOp.DELETE_BEFORE:
                active_op_col.prop_search(active_op, 'delete_before_name', shape_keys, 'key_blocks')
            elif op_type == ShapeKeyOp.DELETE_BETWEEN:
                active_op_col.prop_search(active_op, 'delete_after_name', shape_keys, 'key_blocks', text="Key 1")
                active_op_col.prop_search(active_op, 'delete_before_name', shape_keys, 'key_blocks', text="Key 2")
            elif op_type == ShapeKeyOp.DELETE_SINGLE:
                active_op_col.prop_search(active_op, 'pattern', shape_keys, 'key_blocks', text="Name")
            elif op_type == ShapeKeyOp.DELETE_REGEX:
                active_op_col.prop(active_op, 'pattern')
        elif op_type in ShapeKeyOp.MERGE_OPS_DICT:
            if op_type == ShapeKeyOp.MERGE_PREFIX:
                active_op_col.prop(active_op, 'pattern', text="Prefix")
            elif op_type == ShapeKeyOp.MERGE_SUFFIX:
                active_op_col.prop(active_op, 'pattern', text="Suffix")
            elif op_type == ShapeKeyOp.MERGE_COMMON_BEFORE_DELIMITER or op_type == ShapeKeyOp.MERGE_COMMON_AFTER_DELIMITER:
                active_op_col.prop(active_op, 'pattern', text="Delimiter")
            elif op_type == ShapeKeyOp.MERGE_REGEX:
                active_op_col.prop(active_op, 'pattern')

            # Common for all merge ops
            active_op_col.prop(active_op, 'merge_grouping')

        # Common for all ops
        active_op_col.prop(active_op, 'ignore_regex')


del _op_builder
register_module_classes_factory(__name__, globals())
