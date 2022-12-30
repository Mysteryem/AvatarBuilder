from bpy.types import Context, SpaceProperties, Object, SpaceView3D, UILayout

from .extensions import ObjectPropertyGroup
from .utils import PropertyHolderType


def draw_expandable_header(layout: UILayout, ui_toggle_data: PropertyHolderType, ui_toggle_prop: str,
                           alert: bool = False, **header_args):
    header_row = layout.row(align=True)
    header_row.use_property_split = False
    # Alert has to be set before drawing sub elements
    header_row.alert = alert
    is_expanded = getattr(ui_toggle_data, ui_toggle_prop)
    expand_icon = 'DISCLOSURE_TRI_DOWN' if is_expanded else 'DISCLOSURE_TRI_RIGHT'

    # We draw everything in the header as the toggle property so that any of it can be clicked on to expand the
    # contents.
    # To debug the clickable regions of the header, set emboss to True in each .prop call and the header_args.

    # Force emboss to be disabled
    header_args['emboss'] = False
    if header_args.get('icon', 'NONE') != 'NONE':

        # Since we have an extra icon to draw, we need to draw an extra prop for the 'expand_icon' only
        header_row.prop(ui_toggle_data, ui_toggle_prop, text="", icon=expand_icon, emboss=False)

        # If we left align the entire header row, it won't expand to fill the entire width, meaning the user
        # can't click on anywhere in the header to expand it, so we create a sub_row that is left aligned and draw
        # the header text there
        sub_row = header_row.row(align=True)
        sub_row.alignment = 'LEFT'
        sub_row.prop(ui_toggle_data, ui_toggle_prop, **header_args)
    else:
        sub_row = header_row.row(align=True)
        sub_row.alignment = 'LEFT'
        sub_row.prop(ui_toggle_data, ui_toggle_prop, icon=expand_icon, **header_args)

    # We then need a third element to expand and fill the rest of the header, ensuring that the entire header can be
    # clicked on.
    # Text needs to be non-empty to actually expand, this does cut the header text off slightly when the Panel is
    # made very narrow, but this will have to do.
    # toggle=1 will hide the tick box
    header_row.prop(ui_toggle_data, ui_toggle_prop, text=" ", toggle=1, emboss=False)
    return is_expanded, header_row, sub_row


def redraw_object_properties_panels(context: Context):
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
        elif area.type == 'VIEW_3D':
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
