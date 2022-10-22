from bpy.types import Operator, Context, UILayout, Object

from .extensions import MaterialRemap, ObjectPropertyGroup
from .registration import register_module_classes_factory
from . import utils


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
