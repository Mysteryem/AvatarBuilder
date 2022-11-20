import bpy
from bpy.types import AddonPreferences, Context, UILayout
from bpy.props import BoolProperty

from typing import Optional, cast

from .registration import register_module_classes_factory


class AvatarBuilderAddonPreferences(AddonPreferences):
    # bl_idname must match the addon name
    bl_idname = __package__

    object_ui_sync: BoolProperty(
        name="Object UI Sync",
        description="Sync display of settings on Objects to show only the active settings of the Scene",
        default=True,
    )

    def draw(self, context: Context):
        layout: UILayout = self.layout
        layout.prop(self, 'object_ui_sync')


def object_ui_sync_enabled(context: Optional[Context] = None):
    """Get whether Object UI Sync is enabled"""
    if context is None:
        context = bpy.context
    preferences = cast(AvatarBuilderAddonPreferences, context.preferences.addons[__package__].preferences)
    return preferences.object_ui_sync


register_module_classes_factory(__name__, globals())
