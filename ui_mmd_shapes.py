from bpy.types import Panel, Operator, UIList, Context, UILayout, Mesh

from . import cats_translate
from .extensions import ScenePropertyGroup, MmdShapeMapping, MmdShapeMappingGroup
from .registration import register_module_classes_factory
from .context_collection_ops import (
    CollectionAddBase,
    CollectionMoveBase,
    CollectionRemoveBase,
    ContextCollectionOperatorBase,
    PropCollectionType,
)


class MmdMappingList(UIList):
    bl_idname = "mmd_shapes"

    def draw_item(self, context: Context, layout: UILayout, data: MmdShapeMappingGroup, item: MmdShapeMapping,
                  icon: int, active_data: MmdShapeMappingGroup, active_property: str, index: int = 0,
                  flt_flag: int = 0):
        shape_keys = None
        linked_obj = data.linked_mesh_object
        if linked_obj:
            linked_mesh = linked_obj.data
            if isinstance(linked_mesh, Mesh):
                temp_shape_keys = linked_mesh.shape_keys
                if temp_shape_keys:
                    shape_keys = temp_shape_keys

        row = layout.row(align=True)
        row.label(text="", icon='DECORATE')
        column_flow = row.column_flow(columns=3, align=True)
        if shape_keys:
            # Annoyingly, we can't get rid of the icon, only replace it with a different one
            column_flow.prop_search(item, 'model_shape', shape_keys, 'key_blocks', text="")
        else:
            column_flow.prop(item, 'model_shape', text="")
        column_flow.prop(item, 'mmd_name', text="")
        cats_row = column_flow.row(align=True)
        cats_row.prop(item, 'cats_translation_name', text="")
        op_row = cats_row.row(align=True)
        op_row.enabled = bool(item.mmd_name)
        translate_options = op_row.operator(cats_translate.CatsTranslate.bl_idname, text="", icon='WORLD_DATA')
        translate_options.to_translate = item.mmd_name
        translate_options.is_shape_key = True
        # Path from context to the property
        translate_options.data_path = 'scene.' + item.path_from_id('cats_translation_name')


class MmdMappingControlBase(ContextCollectionOperatorBase):
    @classmethod
    def get_collection(cls, context: Context) -> PropCollectionType:
        return ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings

    @classmethod
    def get_active_index(cls, context: Context) -> int:
        return ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings_active_index

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings_active_index = value


class MmdMappingAdd(MmdMappingControlBase, CollectionAddBase):
    """Add a new shape key mapping"""
    bl_idname = 'mmd_shape_mapping_add'


class MmdMappingRemove(MmdMappingControlBase, CollectionRemoveBase):
    """Remove the active shape key mapping"""
    bl_idname = 'mmd_shape_mapping_remove'


class MmdMappingMove(MmdMappingControlBase, CollectionMoveBase):
    """Move the active shape key mapping"""
    bl_idname = 'mmd_shape_mapping_move'


class LoadDefaults(Operator):
    """Load default mmd shape data."""
    bl_idname = "mmd_shapes_load_defaults"
    bl_label = "Load Default Mappings"
    bl_options = {'UNDO'}

    def execute(self, context: Context) -> set[str]:
        return {'FINISHED'}


class ExportShapeSettings(Operator):
    """Export a .csv containing mmd shape data"""
    bl_idname = "mmd_shapes_export"
    bl_label = "Export Mappings"
    bl_options = {'UNDO'}

    def execute(self, context: Context) -> set[str]:
        return {'FINISHED'}


class ImportShapeSettings(Operator):
    """Import a .csv containing mmd shape data"""
    bl_idname = "mmd_shapes_import"
    bl_label = "Import Mappings"
    bl_options = {'UNDO'}

    def execute(self, context: Context) -> set[str]:
        return {'FINISHED'}


class CatsTranslateAll(Operator):
    """Translate all shapes with Cats"""
    bl_idname = "mmd_shapes_translate_all"
    bl_label = "Translate All MMD with Cats"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return cats_translate.CatsTranslate.poll(context)

    def execute(self, context: Context) -> set[str]:
        mappings = ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings
        to_translate = [m.mmd_name for m in mappings if m.mmd_name]
        translations = cats_translate.cats_translate(to_translate, is_shape_key=True, calling_op=self)
        if translations:
            for mapping in mappings:
                mmd_name = mapping.mmd_name
                if mmd_name:
                    translation = translations.get(mmd_name)
                    if translation is not None:
                        mapping.cats_translation_name = translation
        return {'FINISHED'}


class MmdShapeMappingsPanel(Panel):
    bl_idname = "mmd_shapes"
    bl_label = "MMD Shape Mappings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Avatar Builder"

    def draw(self, context: Context):
        layout = self.layout
        group = ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group

        col = layout.column()

        col.prop(group, 'linked_mesh_object')

        list_row = col.row()
        # Column for the list and its header
        main_list_col = list_row.column()

        # Header for the UI List
        row = main_list_col.row()

        # Spacer to match UI List
        row.label(text="", icon="BLANK1")
        header_flow = row.column_flow(columns=3, align=True)
        header_flow.label(text="Shape Key")
        header_flow.label(text="MMD")
        header_flow.label(text="Cats Translation")
        # Second spacer to roughly match scroll bar
        row.label(text="", icon="BLANK1")

        # Draw the list
        row = main_list_col.row()
        row.template_list(MmdMappingList.bl_idname, "", group, 'mmd_shape_mappings', group, 'mmd_shape_mappings_active_index')

        # Second column for the list controls
        list_controls_col = list_row.column()
        # Spacer to match header in the main column
        row = list_controls_col.row()
        row.label(text="", icon='BLANK1')

        # Add list controls vertically
        vertical_buttons_col = list_controls_col.column(align=True)
        vertical_buttons_col.operator(MmdMappingAdd.bl_idname, text="", icon="ADD")
        vertical_buttons_col.operator(MmdMappingRemove.bl_idname, text="", icon="REMOVE")
        vertical_buttons_col.separator()
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'

        if not cats_translate.cats_exists():
            col.label(text="Cats addon not found")
            col.label(text="Translating is disabled")
        elif not cats_translate.CatsTranslate.poll(context):
            col.label(text="Unsupported Cats version")
            col.label(text="Translating is disabled")
        else:
            col.operator(CatsTranslateAll.bl_idname, icon="WORLD")


register, unregister = register_module_classes_factory(__name__, globals())
