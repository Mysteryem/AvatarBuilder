from bpy.types import Context, Panel

from typing import Callable

from .apply_mmd_mappings import ApplyMMDMappings
from .scene_cleanup import PurgeUnusedObjects
from .bone_weight_merge import MergeBoneWeightsToParents, MergeBoneWeightsToActive
from .weights.subdivide_bone import draw_subdivide_bone_ui
from ..registration import register_module_classes_factory


"""UI for separately runnable tools"""


class ToolsPanel(Panel):
    bl_idname = 'tools'
    bl_label = "Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Avatar Builder"
    bl_options = {'DEFAULT_CLOSED'}
    # After MMD Mappings and before Object Settings
    bl_order = 4

    def draw_object(self, context: Context):
        layout = self.layout
        layout.operator(ApplyMMDMappings.bl_idname, icon="SHAPEKEY_DATA")
        layout.operator(PurgeUnusedObjects.bl_idname, icon="ORPHAN_DATA")

    def draw_pose(self, context: Context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Merge Weights", icon="BONE_DATA")
        row = col.row(align=True)
        row.operator(MergeBoneWeightsToParents.bl_idname, text="to Parents")
        row.operator(MergeBoneWeightsToActive.bl_idname, text="to Active")

        col.separator()

        draw_subdivide_bone_ui(context, col)

    def draw_weight_paint(self, context: Context):
        # TODO: Add support to MergeBoneWeightsToParents for weight paint mode and then use the same function
        layout = self.layout
        col = layout.column(align=True)

        draw_subdivide_bone_ui(context, col)

    _DRAW_FUNCS: dict[str, Callable[['ToolsPanel', Context], None]] = {
        'OBJECT': draw_object,
        'POSE': draw_pose,
        'PAINT_WEIGHT': draw_weight_paint,
    }

    @classmethod
    def poll(cls, context: Context) -> bool:
        return context.mode in cls._DRAW_FUNCS

    def draw(self, context: Context):
        self._DRAW_FUNCS[context.mode](self, context)


register_module_classes_factory(__name__, globals())
