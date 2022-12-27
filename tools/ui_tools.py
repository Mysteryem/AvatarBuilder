from bpy.types import Context, Panel

from .apply_mmd_mappings import ApplyMMDMappings
from ..registration import register_module_classes_factory


"""UI for separately runnable tools"""


class ObjectToolsPanel(Panel):
    """Separately runnable tools that are run from Object mode"""
    bl_idname = "object_tools"
    bl_label = "Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Avatar Builder"
    # After MMD Mappings and before Object Settings
    bl_order = 4

    @classmethod
    def poll(cls, context: Context) -> bool:
        return context.mode == 'OBJECT'

    def draw(self, context: Context):
        layout = self.layout
        layout.operator(ApplyMMDMappings.bl_idname, text="Apply MMD Mappings", icon="SHAPEKEY_DATA")


register_module_classes_factory(__name__, globals())
