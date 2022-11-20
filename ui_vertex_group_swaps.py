from bpy.types import UIList, Context, UILayout

from .extensions import ObjectPropertyGroup, VertexGroupSwap, VertexGroupSwapCollection
from .context_collection_ops import ContextCollectionOperatorBase
from .utils import PropCollectionType
from .registration import register_module_classes_factory


class VertexGroupSwapList(UIList):
    bl_idname = "vertex_group_swap"

    def draw_item(self, context: Context, layout: UILayout, data: VertexGroupSwapCollection, item: VertexGroupSwap,
                  icon: int, active_data: VertexGroupSwapCollection, active_property: str, index: int = 0,
                  flt_flag: int = 0):
        obj = context.object
        row = layout.row(align=True)
        # Draw an icon so there is a part of the row that can be clicked to make that row active
        row.label(text="", icon='DECORATE')
        # Draw the two properties for the names of the vertex groups to swap
        row.prop_search(item, 'name', obj, 'vertex_groups', text="")
        row.prop_search(item, 'swap_with', obj, 'vertex_groups', text="")


class VertexGroupSwapControlBase(ContextCollectionOperatorBase):
    @staticmethod
    def get_vertex_group_settings(context: Context):
        object_settings = ObjectPropertyGroup.get_group(context.object).get_displayed_settings(context.scene)
        if object_settings:
            return object_settings.mesh_settings.vertex_group_settings
        else:
            raise RuntimeError("Context is incorrect, there is currently no displayed ObjectBuildSettings")

    @classmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        return VertexGroupSwapControlBase.get_vertex_group_settings(context).vertex_group_swaps.collection

    @classmethod
    def get_active_index(cls, context: Context) -> int:
        return VertexGroupSwapControlBase.get_vertex_group_settings(context).vertex_group_swaps.active_index

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        VertexGroupSwapControlBase.get_vertex_group_settings(context).vertex_group_swaps.active_index = value


_op_builder = VertexGroupSwapControlBase.op_builder(
    class_name_prefix='VertexGroupSwap', bl_idname_prefix='vg_swap', element_label="Vertex Group Swap",)
VertexGroupSwapAdd = _op_builder.add.build()
VertexGroupSwapRemove = _op_builder.remove.build()
VertexGroupSwapMove = _op_builder.move.build()


def draw_vertex_group_swaps(layout: UILayout, vertex_group_swap_collection: VertexGroupSwapCollection):
    layout.prop(vertex_group_swap_collection, 'enabled')
    if vertex_group_swap_collection.enabled:
        row = layout.row(align=True)
        row.template_list(VertexGroupSwapList.bl_idname, "",
                          vertex_group_swap_collection, 'collection',
                          vertex_group_swap_collection, 'active_index',
                          rows=2)
        vertical_buttons_col = row.column(align=True)
        vertical_buttons_col.operator(VertexGroupSwapAdd.bl_idname, text="", icon="ADD")
        vertical_buttons_col.operator(VertexGroupSwapRemove.bl_idname, text="", icon="REMOVE")
        vertical_buttons_col.separator()
        vertical_buttons_col.operator(VertexGroupSwapMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
        vertical_buttons_col.operator(VertexGroupSwapMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'


del _op_builder
register_module_classes_factory(__name__, globals())
