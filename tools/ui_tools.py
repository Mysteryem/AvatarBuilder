from bpy.types import Context, Panel

from typing import Callable

from .apply_mmd_mappings import ApplyMMDMappings
from .scene_cleanup import PurgeUnusedObjects
from .bone_weight_merge import MergeBoneWeightsToParents, MergeBoneWeightsToActive
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

    def draw_edit_armature(self, context: Context):
        layout = self.layout
        col = layout.column(align=True)
        col.label(text="Merge Weights", icon="BONE_DATA")
        row = col.row(align=True)
        row.operator(MergeBoneWeightsToParents.bl_idname, text="to Parents")
        row.operator(MergeBoneWeightsToActive.bl_idname, text="to Active")

    _DRAW_FUNCS: dict[str, Callable[['ToolsPanel', Context], None]] = {
        'OBJECT': draw_object,
        'EDIT_ARMATURE': draw_edit_armature,
        'POSE': draw_edit_armature,
    }

    @classmethod
    def poll(cls, context: Context) -> bool:
        return context.mode in cls._DRAW_FUNCS

    def draw(self, context: Context):
        self._DRAW_FUNCS[context.mode](self, context)


register_module_classes_factory(__name__, globals())
