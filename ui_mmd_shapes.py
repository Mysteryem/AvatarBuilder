from bpy.types import Panel, Operator, UIList, Context, UILayout, Mesh, Menu
from bpy.props import BoolProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

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


# Not using commas because they can be easily used in shape key names. Technically tabs can too via scripting, but they
# show up as boxes in Blender's UI
CSV_DELIMITER = '\t'


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
        # TODO: Replace the '#' prefix with a customisable StringProperty in-case users want to use shape keys starting
        #  with the default of '#'
        model_shape = item.model_shape
        if model_shape.startswith('#'):
            layout.prop(item, 'model_shape', emboss=False, text="")
            # The row ends up a slightly different height to non-comment rows if we don't put something in a column_flow
            column_flow = layout.column_flow(columns=1, align=True)
            column_flow.label(text="")
        else:
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
            cats_row.prop(item, 'cats_translation_name', text="", emboss=False)
            op_row = cats_row.row(align=True)
            op_row.enabled = bool(item.mmd_name)
            translate_options = op_row.operator(cats_translate.CatsTranslate.bl_idname, text="", icon='WORLD_DATA')
            translate_options.to_translate = item.mmd_name
            translate_options.is_shape_key = True
            # Path from context to the property
            translate_options.data_path = 'scene.' + item.path_from_id('cats_translation_name')
            translate_options.custom_description = "Translate the MMD shape key"


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


class MmdShapesAddMenu(Menu):
    bl_idname = "mmd_shape_mapping_add"
    bl_label = "Add"

    def draw(self, context: Context):
        layout = self.layout
        layout.operator(MmdMappingAdd.bl_idname, text="Top", icon='TRIA_UP_BAR').position = 'TOP'
        layout.operator(MmdMappingAdd.bl_idname, text="Before Active", icon='TRIA_UP').position = 'BEFORE'
        layout.operator(MmdMappingAdd.bl_idname, text="After Active", icon='TRIA_DOWN').position = 'AFTER'
        layout.operator(MmdMappingAdd.bl_idname, text="Bottom", icon='TRIA_DOWN_BAR').position = 'BOTTOM'


class LoadDefaults(Operator):
    """Load default mmd shape data."""
    bl_idname = "mmd_shapes_load_defaults"
    bl_label = "Load Default Mappings"
    bl_options = {'UNDO'}

    def execute(self, context: Context) -> set[str]:
        return {'FINISHED'}


class ExportShapeSettings(Operator, ExportHelper):
    """Export a .csv (tab separated) containing mmd shape data"""
    bl_idname = "mmd_shapes_export"
    bl_label = "Export Mappings"
    bl_options = {'UNDO'}

    filename_ext = ".csv"

    def execute(self, context: Context) -> set[str]:
        mappings = ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings
        lines = []
        for mapping in mappings:
            model_shape = mapping.model_shape
            mmd_name = mapping.mmd_name
            cats_translation_name = mapping.cats_translation_name
            if CSV_DELIMITER in model_shape:
                self.report({'WARNING'}, f"The .csv delimiter '{CSV_DELIMITER}' was found in the Shape Key"
                                         f" '{model_shape}', it has been removed in the export")
                model_shape = model_shape.replace(CSV_DELIMITER, "")
            if CSV_DELIMITER in mmd_name:
                self.report({'WARNING'}, f"The .csv delimiter '{CSV_DELIMITER}' was found in the MMD name"
                                         f" '{mmd_name}', it has been removed in the export")
                mmd_name = mmd_name.replace(CSV_DELIMITER, "")
            if CSV_DELIMITER in cats_translation_name:
                self.report({'WARNING'}, f"The .csv delimiter '{CSV_DELIMITER}' was found in the Cats translation name"
                                         f" '{cats_translation_name}', it has been removed in the export")
                cats_translation_name = cats_translation_name.replace(CSV_DELIMITER, "")
            lines.append(model_shape + "\t" + mmd_name + "\t" + cats_translation_name)
        file = open(self.filepath, 'w')
        # Python's writelines doesn't even write lines, have to add the newlines yourself...
        file.writelines(line + "\n" for line in lines)
        file.close()
        return {'FINISHED'}


class ImportShapeSettings(Operator, ImportHelper):
    """Import a .csv (tab separated) containing mmd shape data"""
    bl_idname = "mmd_shapes_import"
    bl_label = "Import Mappings"
    bl_options = {'UNDO'}

    add: BoolProperty(
        name="Add",
        description="Add the imported mappings to the list without clearing the list beforehand"
    )

    def execute(self, context: Context) -> set[str]:
        file = open(self.filepath, 'r')
        lines = file.readlines()
        parsed_lines: list[tuple[str, str, str]] = []
        for line_no, line in enumerate(lines, start=1):
            split = line.split(CSV_DELIMITER)
            num_fields = len(split)
            expected_fields = 3
            if num_fields >= 3:
                # Extra fields may be used for comments in the file
                parsed_lines.append((split[0], split[1], split[2]))
            else:
                self.report({'WARNING'}, f"Failed to parse line {line_no}, got {num_fields} fields, but expected"
                                         f" at least {expected_fields}")
        mappings = ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings
        if not self.add:
            mappings.clear()
        for shape_name, mmd_name, cats_name in parsed_lines:
            added = mappings.add()
            added.model_shape = shape_name
            added.mmd_name = mmd_name
            added.cats_translation_name = cats_name
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

        # Get all mmd_names that are non-empty and filter out any duplicates
        unique_to_translate = set()
        to_translate = []
        for mapping in mappings:
            mmd_name = mapping.mmd_name
            if mmd_name not in unique_to_translate:
                unique_to_translate.add(mmd_name)
                to_translate.append(mmd_name)

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
        vertical_buttons_col.operator_menu_hold(MmdMappingAdd.bl_idname, text="", icon="ADD", menu=MmdShapesAddMenu.bl_idname)
        vertical_buttons_col.operator(MmdMappingRemove.bl_idname, text="", icon="REMOVE")
        vertical_buttons_col.separator()
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_UP_BAR").type = 'TOP'
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_DOWN_BAR").type = 'BOTTOM'
        vertical_buttons_col.separator()
        vertical_buttons_col.operator(ImportShapeSettings.bl_idname, text="", icon="IMPORT")
        vertical_buttons_col.operator(ExportShapeSettings.bl_idname, text="", icon="EXPORT")

        if not cats_translate.cats_exists():
            col.label(text="Cats addon not found")
            col.label(text="Translating is disabled")
        elif not cats_translate.CatsTranslate.poll(context):
            col.label(text="Unsupported Cats version")
            col.label(text="Translating is disabled")
        else:
            col.operator(CatsTranslateAll.bl_idname, icon="WORLD")


register, unregister = register_module_classes_factory(__name__, globals())
