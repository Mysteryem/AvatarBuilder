from bpy.types import Context, SpaceProperties, Object, SpaceView3D

from .ui_object import ObjectPanelView3D
from .extensions import ObjectPropertyGroup


def redraw_object_properties_panels(context: Context):
    view3d_panel_drawn = ObjectPanelView3D.poll(context)
    # Iterate through all areas in the current screen
    for area in context.screen.areas:
        if area.type == 'PROPERTIES':
            # If it's a Properties area, get its SpaceProperties (this is probably an unnecessarily safe way
            # to do so since I suspect there is only ever one Space and that it is always a SpaceProperties)
            space_properties = next((s for s in area.spaces if isinstance(s, SpaceProperties)), None)
            # We only care if the currently displayed properties are Object Properties, since that's where the
            # Object Panel is shown.
            if space_properties is not None and space_properties.context == 'OBJECT':
                # SpaceProperties can pin an ID (should always be an Object if .context == 'OBJECT')
                # Note that space_properties.use_pin_id doesn't actually determine if the pin is used, all it seems
                # to do is change the pin icon in the UI.
                pin_id = space_properties.pin_id
                if isinstance(pin_id, Object):
                    displayed_object = pin_id
                elif pin_id is not None:
                    # Pinned id can be a Mesh, Armature or many other types of Object data (though
                    # shouldn't be since .context == 'OBJECT')
                    displayed_object = None
                else:
                    # If there's no pin, then context.object is used.
                    # Note that if there are no Objects in the current scene, context.object can be None
                    displayed_object = context.object
                if (
                        displayed_object is not None
                        and displayed_object.type in ObjectPropertyGroup.ALLOWED_TYPES
                ):
                    for region in area.regions:
                        # The region in which the Panel is shown is the WINDOW
                        if region.type == 'WINDOW':
                            # Tell the WINDOW region to redraw
                            region.tag_redraw()
                            # If we found the WINDOW region before the end, we can skip the other regions
                            # (HEADER and NAVIGATION_BAR)
                            break
        elif view3d_panel_drawn and area.type == 'VIEW_3D':
            ui_region_shown = False
            # I think there's only ever a single space in the 3D View, but we'll loop to be sure
            for space in area.spaces:
                # SpaceView3D.show_region_ui indicates whether the right shelf (the 'UI' region) is displayed
                if isinstance(space, SpaceView3D) and space.show_region_ui:
                    ui_region_shown = True
                    break

            if ui_region_shown:
                # Find the 'UI' region
                for region in area.regions:
                    if region.type == 'UI':
                        # There doesn't appear to be a way to tell which tab of the UI region is active, nor does there
                        # appear to be a way to tell if a specific Panel is expanded or collapsed, so we will have to
                        # assume that the Panel's tab is active and that the Panel is expanded.
                        # Tell the UI region to redraw
                        region.tag_redraw()
                        # There should only be one UI region, so any remaining regions can be skipped
                        break