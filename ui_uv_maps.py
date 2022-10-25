from bpy.types import UIList, UILayout, Context, bpy_struct

from typing import Optional

from .context_collection_ops import (
    PropCollectionType,
    ContextCollectionOperatorBase,
    CollectionRemoveBase,
    CollectionAddBase,
    CollectionMoveBase,
)
from .extensions import ObjectPropertyGroup, KeepUVMapList
from .registration import register_module_classes_factory


class KeepUVMapUIList(UIList):
    bl_idname = 'keep_uv_map'

    def draw_item(self, context: Context, layout: UILayout, data: bpy_struct, item: bpy_struct, icon: int, active_data: bpy_struct, active_property: str, index: int = 0, flt_flag: int = 0):
        layout.prop_search(item, 'name', context.object.data, 'uv_layers')

    def draw_filter(self, context: Context, layout: UILayout):
        # No filter
        pass

    def filter_items(self, context: Context, data, property: str):
        # We always want to show every op in order because they are applied in series. No filtering or sorting is ever
        # enabled
        return [], []


class KeepUVMapListControlBase(ContextCollectionOperatorBase):
    @staticmethod
    def get_property(context: Context) -> Optional[KeepUVMapList]:
        group = ObjectPropertyGroup.get_group(context.object)
        object_build_settings = group.get_displayed_settings(context.scene)
        if object_build_settings:
            return object_build_settings.mesh_settings.uv_settings.keep_uv_map_list
        else:
            return None

    @classmethod
    def get_collection(cls, context: Context) -> Optional[PropCollectionType]:
        prop = KeepUVMapListControlBase.get_property(context)
        if prop:
            return prop.data
        else:
            return None

    @classmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        prop = KeepUVMapListControlBase.get_property(context)
        if prop:
            return prop.active_index
        else:
            return None

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        prop = KeepUVMapListControlBase.get_property(context)
        if prop:
            prop.active_index = value


class UVMapListAdd(CollectionAddBase, KeepUVMapListControlBase):
    bl_idname = 'keep_uv_map_list_add'


class UVMapListRemove(CollectionRemoveBase, KeepUVMapListControlBase):
    bl_idname = 'keep_uv_map_list_remove'


class UVMapListMove(CollectionMoveBase, KeepUVMapListControlBase):
    bl_idname = 'keep_uv_map_list_move'


def draw_uv_map_list(layout: UILayout, keep_uv_map_list: KeepUVMapList):
    row = layout.row()
    row.template_list(
        KeepUVMapUIList.bl_idname, "",
        keep_uv_map_list, 'data',
        keep_uv_map_list, 'active_index',
        # Two rows minimum, since there is another option specifically for keeping only one UV Map
        sort_lock=True, rows=2)
    vertical_buttons_col = row.column(align=True)
    vertical_buttons_col.operator(UVMapListAdd.bl_idname, text="", icon="ADD").name = ''
    vertical_buttons_col.operator(UVMapListRemove.bl_idname, text="", icon="REMOVE")
    vertical_buttons_col.separator()
    vertical_buttons_col.operator(UVMapListMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
    vertical_buttons_col.operator(UVMapListMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'


register, unregister = register_module_classes_factory(__name__, globals())
