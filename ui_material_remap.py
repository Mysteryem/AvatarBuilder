from bpy.types import Operator, Context, UILayout, Object, Event, SpaceProperties
from bpy.props import EnumProperty

from sys import intern
from typing import Union

from .extensions import MaterialRemap, ObjectPropertyGroup
from .registration import register_module_classes_factory
from . import utils


_MAT_SLOT_ITEMS_CACHE = []


# self seems to be a sort of partial operator, it has access to only
# ['__doc__', '__module__', '__slots__', 'bl_rna', 'rna_type', 'slots_enum']
# when used as the items of the slots_enum property in KeepOnlyMaterialSlotSearch
def _material_slot_items(self, context: Context):
    global _MAT_SLOT_ITEMS_CACHE
    obj = context.object
    items: list[tuple[str, str, str, Union[str, int], int]] = []
    for idx, slot in enumerate(obj.material_slots):
        unique_id = str(idx)
        mat = slot.material
        if mat:
            label = intern(mat.name)
            icon = utils.get_preview(mat).icon_id
        else:
            label = "(empty slot)"
            icon = 'MATERIAL_DATA'
        items.append((unique_id, label, label, icon, idx))
    # It's important to always have at least one item
    if not items:
        items.append(('0', "(no material slots)", "Mesh has no material slots", 'ERROR', 0))
    if items != _MAT_SLOT_ITEMS_CACHE:
        _MAT_SLOT_ITEMS_CACHE = items
    return items


class KeepOnlyMaterialSlotSearch(Operator):
    """Pick Material Slot"""
    bl_idname = 'keep_only_material_slot_search'
    bl_label = "Pick Material Slot"
    bl_property = 'slots_enum'

    slots_enum: EnumProperty(items=_material_slot_items, options={'HIDDEN'})

    def execute(self, context: Context) -> set[str]:
        obj = context.object
        # Get the index of the EnumProperty
        material_slot_index = self.properties['slots_enum']
        # Set the keep_only_mat_slot index property
        group = ObjectPropertyGroup.get_group(obj)
        object_settings = group.get_displayed_settings(context.scene)
        object_settings.mesh_settings.material_settings.keep_only_mat_slot = material_slot_index
        region = context.region
        if region and isinstance(context.space_data, SpaceProperties):
            # We've changed the keep_only_mat_slot property, update the UI region so that it displays the new value
            # immediately. Without this, the UI won't show the property's new value until another part of the ui causes
            # a redraw (this can be as simple as mousing over a property)
            region.tag_redraw()
        return {'FINISHED'}

    def invoke(self, context: Context, event: Event) -> set[str]:
        context.window_manager.invoke_search_popup(self)
        return {'FINISHED'}


class RefreshRemapList(Operator):
    bl_idname = 'material_remap_refresh_list'
    bl_label = "Refresh Remap List"

    def execute(self, context: Context) -> set[str]:
        obj = context.object
        object_build_settings = ObjectPropertyGroup.get_group(obj).get_displayed_settings(context.scene)
        material_settings = object_build_settings.mesh_settings.material_settings
        if material_settings.materials_main_op == 'REMAP':
            data = material_settings.materials_remap.data
            material_slots = obj.material_slots
            num_mappings = len(data)
            num_slots = len(material_slots)
            if num_mappings != num_slots:
                if num_mappings > num_slots:
                    # Remove the excess mappings
                    # Iterate in reverse so that we remove the last element each time, so that the indices don't change
                    # while iterating
                    for i in reversed(range(num_slots, num_mappings)):
                        data.remove(i)
                else:
                    # For each missing mapping, add a new mapping and set it to the current material in the
                    # corresponding slot
                    for slot in material_slots[num_mappings:num_slots]:
                        added = data.add()
                        added.to_mat = slot.material
            return {'FINISHED'}
        else:
            return {'CANCELLED'}


def draw_material_remap_list(layout: UILayout, obj: Object, material_remap: MaterialRemap):
    box = layout.box()
    box.use_property_decorate = False
    box.use_property_split = False
    col_flow = box.column_flow(columns=2, align=True)
    col1 = col_flow.column()
    col2 = col_flow.column()
    for idx, (slot, remap) in enumerate(zip(obj.material_slots, material_remap.data)):
        mat = slot.material
        row = col1.row()
        if mat:
            label = f"{slot.material.name}:"
            row.label(text=label, icon_value=utils.get_preview(mat).icon_id)
        else:
            row.label(text="(empty):", icon='MATERIAL_DATA')
        row.label(text="", icon='FORWARD')
        to_mat = remap.to_mat
        if to_mat:
            col2.prop(remap, 'to_mat', text="", icon_value=utils.get_preview(to_mat).icon_id)
        else:
            col2.prop(remap, 'to_mat', text="", icon='MATERIAL_DATA')
    num_slots = len(obj.material_slots)
    num_remaps = len(material_remap.data)
    if num_slots != num_remaps:
        if num_slots > num_remaps:
            # There are more slots than remaps, the user needs to refresh the list
            box.label(text=f"There are {num_slots - num_remaps} material slots that don't have mappings", icon='ERROR')
            box.label(text=f"Refresh the list to add the missing mappings", icon='BLANK1')
        else:
            # There are extra, unused slots, the user should refresh the list to remove the extras
            box.label(text=f"Removed slots, please refresh to remove mappings:", icon='ERROR')
            col_flow = box.column_flow(columns=2, align=True)
            col_flow.alert = True
            col1 = col_flow.column()
            col2 = col_flow.column()
            for remap in material_remap.data[num_slots:]:
                row = col1.row()
                row.label(text="Removed slot:")
                row.label(text="", icon='FORWARD')
                col2.prop(remap, 'to_mat', text="", emboss=False)
        # Draw operator button to refresh the list
        box.operator(RefreshRemapList.bl_idname)


register, unregister = register_module_classes_factory(__name__, globals())
