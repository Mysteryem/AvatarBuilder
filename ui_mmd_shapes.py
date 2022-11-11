from bpy.types import Panel, Operator, UIList, Context, UILayout, Mesh, Menu, OperatorProperties, UIPopover
from bpy.props import EnumProperty, IntProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

import os
from typing import Generator, Union, cast, NamedTuple
import csv

from . import cats_translate
from .extensions import ScenePropertyGroup, MmdShapeMapping, MmdShapeMappingGroup
from .registration import register_module_classes_factory
from .context_collection_ops import (
    CollectionAddBase,
    CollectionClearBase,
    CollectionMoveBase,
    CollectionRemoveBase,
    ContextCollectionOperatorBase,
    PropCollectionType,
)


class ShowMappingComment(Operator):
    bl_idname = 'mmd_shape_comment_modify'
    # When non-empty, the label is displayed when mousing over the operator in UI. The description is then displayed
    # below.
    bl_label = ""
    bl_options = {'INTERNAL'}

    use_active: BoolProperty(
        name="Use active",
        description="Use the active mapping. When False, get the mapping by index instead",
        default=False,
        options={'HIDDEN'},
    )
    index: IntProperty(
        name="Index",
        description="Index of the mapping to show the comment of",
        options={'HIDDEN'},
    )
    is_menu: BoolProperty(
        name="Is drawn in menu",
        default=False,
        options={'HIDDEN'},
    )

    @staticmethod
    def get_mapping(use_active: bool, index: int, context: Context):
        shape_mapping_group = ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group
        if use_active:
            index = shape_mapping_group.mmd_shape_mappings_active_index
        data = shape_mapping_group.mmd_shape_mappings
        if 0 <= index < len(data):
            return data[index]
        else:
            return None

    @classmethod
    def description(cls, context: Context, properties: OperatorProperties) -> str:
        # noinspection PyUnresolvedReferences
        use_active = properties.use_active
        # noinspection PyUnresolvedReferences
        index = properties.index
        mapping = cls.get_mapping(use_active, index, context)
        if mapping:
            comment = mapping.comment
            # noinspection PyUnresolvedReferences
            is_menu = properties.is_menu
            if is_menu or not comment:
                mmd_name = mapping.mmd_name
                if mmd_name:
                    return f"Edit comment for {mmd_name}"
                else:
                    return (f"Edit the comment of the active mapping. If a mapping consists of only a comment, the"
                            f" comment will be displayed across every column")
            else:
                return comment
        else:
            if use_active:
                return "ERROR: active mapping not found"
            else:
                return f"ERROR: mapping {index} not found"

    def execute(self, context: Context) -> set[str]:
        mapping = self.get_mapping(self.use_active, self.index, context)
        if mapping:
            def draw_popover(self: UIPopover, context: Context):
                layout = self.layout
                # active_init unfortunately doesn't seem to work with UIPopover, we'll leave it here in-case a Blender
                # update fixes it
                layout.activate_init = True
                layout.prop(mapping, 'comment', text="")
            # Roughly expands to fit the comment with some extra space for additional typing
            # These are purely magic numbers
            ui_units_x = min(max(10, len(mapping.comment) // 2), 40)
            # Draw popup window that lets the user edit the comment
            context.window_manager.popover(draw_popover, ui_units_x=ui_units_x, from_active_button=True)
        else:
            if self.use_active:
                self.report({'ERROR'}, "Active mapping not found")
            else:
                self.report({'ERROR'}, f"Mapping {self.index} not found")
        return {'FINISHED'}


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
        comment = item.comment
        if not item.mmd_name and not item.model_shape and not item.cats_translation_name and comment:
            # We only have a comment, so only draw the comment
            layout.prop(item, 'comment', emboss=False, text="", icon='INFO')
            # The row ends up a slightly different height to non-comment rows if we don't put something in a column_flow
            column_flow = layout.column_flow(columns=1, align=True)
            column_flow.label(text="")
        else:
            row = layout.row(align=True)
            # First drawing an icon ensures there is always a part of the row that can be clicked on to only set that
            # row as active
            row.label(text="", icon='DECORATE')
            # Split the remaining row into 3 columns
            column_flow = row.column_flow(columns=3, align=True)

            # First column for the name of the shape key on the model
            if shape_keys:
                # Annoyingly, we can't get rid of the icon, only replace it with a different one
                column_flow.prop_search(item, 'model_shape', shape_keys, 'key_blocks', text="")
            else:
                column_flow.prop(item, 'model_shape', text="")

            # Second column for the MMD name plus optional comment
            comment = item.comment
            if comment:
                mmd_row = column_flow.row(align=True)
                mmd_row.prop(item, 'mmd_name', text="")
                options = mmd_row.operator(ShowMappingComment.bl_idname, text="", icon='INFO', emboss=False)
                options.index = index
                options.use_active = False
            else:
                column_flow.prop(item, 'mmd_name', text="")

            # Third column for the Cats translation
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


MmdMappingAdd, MmdMappingRemove, MmdMappingMove, MmdMappingsClear = MmdMappingControlBase.create_control_operators_simple(
    class_name_prefix='MmdMapping',
    bl_idname_prefix='mmd_shape_mapping',
    element_label="shape key mapping",
)


class MmdMappingsClearShapeNames(MmdMappingControlBase, Operator):
    """Clear the Shape Key for each shape key mapping"""
    bl_idname = 'mmd_shape_mappings_clear_shape_keys'
    bl_label = "Clear Shape Keys"
    bl_options = {'UNDO'}

    def execute(self, context: Context) -> set[str]:
        mapping: MmdShapeMapping
        for mapping in self.get_collection(context):
            mapping.model_shape = ''
        return {'FINISHED'}


class MmdMappingsAddFromSearchMesh(MmdMappingControlBase, Operator):
    """Load Shape Keys from Search Mesh. Will not add mappings that already exist"""
    bl_idname = 'mmd_shape_mappings_add_from_search_mesh'
    bl_label = "Add From Search Mesh"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.linked_mesh_object is not None

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)
        mapping: MmdShapeMapping
        existing_mappings = {mapping.model_shape for mapping in data}
        me = cast(Mesh, ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.linked_mesh_object.data)
        shape_keys = me.shape_keys
        if shape_keys:
            # Skip the first shape key, the reference ('basis') key
            for key in shape_keys.key_blocks[1:]:
                shape_key_name = key.name
                if shape_key_name not in existing_mappings:
                    mapping = data.add()
                    mapping.model_shape = shape_key_name
        return {'FINISHED'}


class MmdMappingsAddMmdFromSearchMesh(MmdMappingControlBase, Operator):
    """Load MMD Shapes from Search Mesh. Make sure that your Search Mesh is from an imported MMD model
     and still has its Japanese Shape Key names. Will not add mappings that already exist"""
    bl_idname = 'mmd_shape_mappings_add_mmd_from_search_mesh'
    bl_label = "Add MMD From Search Mesh"
    bl_options = {'UNDO'}

    @classmethod
    def poll(cls, context: Context) -> bool:
        return ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.linked_mesh_object is not None

    def execute(self, context: Context) -> set[str]:
        data = self.get_collection(context)
        mapping: MmdShapeMapping
        existing_mappings = {mapping.mmd_name for mapping in data}
        me = cast(Mesh, ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.linked_mesh_object.data)
        shape_keys = me.shape_keys
        if shape_keys:
            # Skip the first shape key, the reference ('basis') key
            for key in shape_keys.key_blocks[1:]:
                shape_key_name = key.name
                if shape_key_name not in existing_mappings:
                    mapping = data.add()
                    mapping.mmd_name = shape_key_name
        return {'FINISHED'}


class MmdShapesAddMenu(Menu):
    bl_idname = "mmd_shape_mapping_add"
    bl_label = "Add"

    def draw(self, context: Context):
        layout = self.layout
        layout.operator(MmdMappingAdd.bl_idname, text="Top", icon='TRIA_UP_BAR').position = 'TOP'
        layout.operator(MmdMappingAdd.bl_idname, text="Before Active", icon='TRIA_UP').position = 'BEFORE'
        layout.operator(MmdMappingAdd.bl_idname, text="After Active", icon='TRIA_DOWN').position = 'AFTER'
        layout.operator(MmdMappingAdd.bl_idname, text="Bottom", icon='TRIA_DOWN_BAR').position = 'BOTTOM'


class MmdShapesSpecialsMenu(Menu):
    bl_idname = 'mmd_shape_mapping_specials'
    bl_label = "MMD Shape Mapping Specials"

    def draw(self, context: Context):
        layout = self.layout
        layout.operator(MmdMappingsAddFromSearchMesh.bl_idname, icon='ADD')
        layout.operator(MmdMappingsAddMmdFromSearchMesh.bl_idname, icon='ADD')
        layout.separator()
        layout.operator(MmdMappingsClear.bl_idname, text="Delete All Mappings", icon='X')
        layout.separator()
        layout.operator(MmdMappingsClearShapeNames.bl_idname, text="Clear All Shape Keys")
        layout.separator()
        options = layout.operator(ShowMappingComment.bl_idname, text="Set Comment", icon='TEXT')
        options.use_active = True
        options.is_menu = True
        layout.separator()
        layout.operator(MmdMappingMove.bl_idname, text="Move To Top", icon="TRIA_UP_BAR").type = 'TOP'
        layout.operator(MmdMappingMove.bl_idname, text="Move To Bottom", icon="TRIA_DOWN_BAR").type = 'BOTTOM'


class ExportShapeSettings(Operator, ExportHelper):
    """Export a .csv containing mmd shape data"""
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
            line = (model_shape, mmd_name, cats_translation_name)
            lines.append(line)
        # Note: newline should be '' when using csv.writer
        with open(self.filepath, 'w', encoding='utf-8', newline='') as file:
            csv.writer(file).writerows(lines)
        return {'FINISHED'}


class ParsedCsvLine(NamedTuple):
    model_shape: str = ""
    mmd_name: str = ""
    cats_translation: str = ""
    comment: str = ""

    def is_only_comment(self):
        return self.comment and not self.model_shape and not self.mmd_name and not self.cats_translation


class ImportShapeSettings(Operator, ImportHelper):
    """Import a .csv containing mmd shape data"""
    bl_idname = "mmd_shapes_import"
    bl_label = "Import Mappings"
    bl_options = {'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(
            ('REPLACE', "Replace", "Replace existing mappings with the imported mappings"),
            ('APPEND', "Append", "Append imported mappings to the end of the existing mappings"),
            ('APPEND_NEW', "Append New", "Append imported mappings to the end of the existing mappings if the MMD name"
                                         " from the imported mapping doesn't already exist."
                                         "\nNote that this currently strips all comments from the imported mappings"
                                         "(comments system needs changes)"),
        ),
        default='REPLACE',
        description="What to do with the existing mappings",
    )

    def execute(self, context: Context) -> set[str]:
        # Note: newline should be '' when using csv.reader
        with open(self.filepath, 'r', encoding='utf-8', newline='') as file:
            reader = csv.reader(file)
            parsed_lines: Union[list[ParsedCsvLine], Generator[ParsedCsvLine]] = []

            for line_no, line_list in enumerate(reader, start=1):
                num_fields = len(line_list)
                expected_fields = len(ParsedCsvLine._fields)
                if num_fields > expected_fields:
                    # If there are extra fields, get only as many as we're expecting
                    parsed_line = ParsedCsvLine(*line_list[:expected_fields])
                else:
                    # If there aren't enough fields, default values for the missing fields will be used
                    parsed_line = ParsedCsvLine(*line_list)

                parsed_lines.append(parsed_line)
                if num_fields < expected_fields:
                    self.report({'WARNING'}, f"Line {line_no} only had {num_fields} fields, (expecting at least"
                                             f" {expected_fields}).")
            mappings = ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.mmd_shape_mappings

            if self.mode == 'REPLACE':
                mappings.clear()
            elif self.mode == 'APPEND_NEW':
                existing_mmd_names = {m.mmd_name for m in mappings}
                # We don't want to exclude lines that have no mapping, e.g. lines that are only comments
                existing_mmd_names.remove("")
                parsed_lines = (p for p in parsed_lines if p.mmd_name not in existing_mmd_names)

            for parsed_line in parsed_lines:
                added = mappings.add()
                added.model_shape = parsed_line.model_shape
                added.mmd_name = parsed_line.mmd_name
                added.cats_translation_name = parsed_line.cats_translation
                added.comment = parsed_line.comment
        return {'FINISHED'}


class ImportPresetMenu(Menu):
    """Load preset MMD Mappings created from Miku Append v1.10, Mirai Akari v1.0, Shishiro Botan and a few miscellaneous
    models"""
    bl_idname = 'mmd_mappings_presets'
    bl_label = "Import Preset"

    PRESETS_DIRECTORY = "resources"
    MOST_COMMON = "mmd_mappings_most_common.csv"
    VERY_COMMON = "mmd_mappings_very_common.csv"
    COMMON = "mmd_mappings_common.csv"
    FULL = "mmd_mappings_full.csv"

    RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")

    def draw(self, context: Context):
        layout = self.layout
        # Don't open the file selection window (invoke), go straight to calling execute
        layout.operator_context = 'EXEC_DEFAULT'
        file_names_text_and_icon = (
            (ImportPresetMenu.MOST_COMMON, "Most Common (recommended for basic MMD support", 'SOLO_OFF'),
            (ImportPresetMenu.VERY_COMMON, "Common (recommended for more full MMD support)", 'SOLO_ON'),
            (ImportPresetMenu.COMMON, "Common + Miku Append + Misc", 'NONE'),
            (ImportPresetMenu.FULL, "All (Miku + Akari + Botan + Misc)", 'NONE'),
        )
        for file_name, text, icon in file_names_text_and_icon:
            filepath = os.path.join(ImportPresetMenu.RESOURCE_DIR, file_name)
            options = layout.operator(ImportShapeSettings.bl_idname, text=text, icon=icon)
            options.mode = 'APPEND'
            options.filepath = filepath


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

    @classmethod
    def poll(cls, context: Context) -> bool:
        # Don't show the Panel in export scenes
        return not ScenePropertyGroup.get_group(context.scene).is_export_scene

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
        vertical_buttons_col.menu(MmdShapesSpecialsMenu.bl_idname, text="", icon='DOWNARROW_HLT')
        vertical_buttons_col.separator()
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
        vertical_buttons_col.operator(MmdMappingMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'
        vertical_buttons_col.separator()
        vertical_buttons_col.operator(ImportShapeSettings.bl_idname, text="", icon="IMPORT")
        vertical_buttons_col.menu(ImportPresetMenu.bl_idname, text="", icon="PRESET")
        vertical_buttons_col.separator()
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
