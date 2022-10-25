from bpy.types import (
    Object,
    UIList,
    UILayout,
    Context,
    bpy_struct,
    Mesh,
    PropertyGroup,
    Operator,
    SpaceProperties,
    Event,
)
from bpy.props import EnumProperty, IntProperty

from typing import Optional, Union, cast
from sys import intern

from .context_collection_ops import (
    PropCollectionType,
    ContextCollectionOperatorBase,
    CollectionRemoveBase,
    CollectionAddBase,
    CollectionMoveBase,
)
from .extensions import ObjectPropertyGroup, KeepUVMapList
from .registration import register_module_classes_factory


_UV_MAP_ITEMS_CACHE = []


def _uv_map_items(self, context: Context):
    global _UV_MAP_ITEMS_CACHE
    items: list[tuple[str, str, str, Union[str, int], int]] = []
    obj = context.object
    me = obj.data
    if isinstance(me, Mesh):
        settings = ObjectPropertyGroup.get_group(obj).get_displayed_settings(context.scene)
        data = settings.mesh_settings.uv_settings.keep_uv_map_list.data
        used_uv_maps = {e.name for e in data}

        # Don't include the current row
        current_row_index = self.index
        if 0 <= current_row_index < len(data):
            used_uv_maps.remove(data[self.index].name)

        for idx, uv_layer in enumerate(me.uv_layers):
            uv_layer_name = uv_layer.name
            if uv_layer_name not in used_uv_maps:
                # uv_layer_name comes from C and therefore must be interned
                uv_layer_name = intern(uv_layer_name)
                item = (uv_layer_name, uv_layer_name, uv_layer_name, "GROUP_UVS", idx)
                items.append(item)
        # It's important to always have at least one item
        if not items:
            # Add an item with an identifier which isn't in the mesh's uv layers
            # Get a set of the names of the uv layers
            all_layer_names = {layer.name for layer in me.uv_layers}
            # Iterate i until it produces a string which doesn't match the name of a uv layer
            i = 0
            i_str = str(i)
            while i_str in all_layer_names:
                i += 1
                i_str = str(i)
            items.append((i_str, "(no remaining uv maps)", "No remaining uv maps", 'ERROR', -1))
    else:
        # This shouldn't happen, be we'll leave it here for safety, since items must always have at least one item
        items.append(('ERROR', "ERROR: Not a Mesh", "ERROR: Not a Mesh", 'ERROR', -1))
    if items != _UV_MAP_ITEMS_CACHE:
        _UV_MAP_ITEMS_CACHE = items
    return items


class KeepUVMapSearch(Operator):
    """Pick UV Map"""
    bl_idname = 'keep_uv_map_search'
    bl_label = "Pick UV Map"
    bl_property = 'available_maps_enum'
    bl_options = {'UNDO', 'INTERNAL'}

    index: IntProperty(min=0)
    available_maps_enum: EnumProperty(items=_uv_map_items, options={'HIDDEN'})

    def execute(self, context: Context) -> set[str]:
        obj = context.object
        group = ObjectPropertyGroup.get_group(obj)
        object_settings = group.get_displayed_settings(context.scene)
        data = object_settings.mesh_settings.uv_settings.keep_uv_map_list.data
        index = self.index
        if index < len(data):
            row = data[index]
            me = obj.data
            if isinstance(me, Mesh):
                uv_layers = me.uv_layers
                name_to_set = self.available_maps_enum
                if uv_layers and name_to_set in uv_layers:
                    row.name = name_to_set
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


class KeepUVMapUIList(UIList):
    bl_idname = 'keep_uv_map'

    def draw_item(self, context: Context, layout: UILayout, data: bpy_struct, item: PropertyGroup, icon: int,
                  active_data: bpy_struct, active_property: str, index: int = 0, flt_flag: int = 0):
        # Need a label of some kind so that rows can be selected as active
        row = layout.row(align=True)
        data = context.object.data
        if isinstance(data, Mesh):
            uv_layers = data.uv_layers
            row.alert = not (uv_layers and item.name in uv_layers)
        row.label(text="", icon='DECORATE')
        text = item.name if item.name else " "
        row.operator(KeepUVMapSearch.bl_idname, text=text, icon='GROUP_UVS').index = index

    def draw_filter(self, context: Context, layout: UILayout):
        # No filter
        pass

    def filter_items(self, context: Context, data, property: str):
        # We always want to show every op in order because they are applied in series. No filtering or sorting is ever
        # enabled
        return [], []


class KeepUVMapListControlBase(ContextCollectionOperatorBase):
    @staticmethod
    def get_property(context: Context) -> Optional[KeepUVMapList]:
        group = ObjectPropertyGroup.get_group(context.object)
        object_build_settings = group.get_displayed_settings(context.scene)
        if object_build_settings:
            return object_build_settings.mesh_settings.uv_settings.keep_uv_map_list
        else:
            return None

    @classmethod
    def get_collection(cls, context: Context) -> Optional[PropCollectionType]:
        prop = KeepUVMapListControlBase.get_property(context)
        if prop:
            return prop.data
        else:
            return None

    @classmethod
    def get_active_index(cls, context: Context) -> Optional[int]:
        prop = KeepUVMapListControlBase.get_property(context)
        if prop:
            return prop.active_index
        else:
            return None

    @classmethod
    def set_active_index(cls, context: Context, value: int):
        prop = KeepUVMapListControlBase.get_property(context)
        if prop:
            prop.active_index = value


class UVMapListAdd(CollectionAddBase, KeepUVMapListControlBase):
    bl_idname = 'keep_uv_map_list_add'

    @classmethod
    def poll(cls, context: Context) -> bool:
        data = context.object.data
        if isinstance(data, Mesh):
            uv_layers = data.uv_layers
            if uv_layers:
                collection = cls.get_collection(context)
                return collection is not None and len(collection) < len(uv_layers)
        return False

    def set_new_item_name(self, data: PropCollectionType, added: PropertyGroup):
        if not self.properties.is_property_set('name'):
            # Automatic name by the first uv map name not already in the collection
            existing_names = {e.name for e in data}
            obj = cast(Object, data.id_data)
            me = cast(Mesh, obj.data)
            for uv_layer in me.uv_layers:
                uv_layer_name = uv_layer.name
                if uv_layer_name not in existing_names:
                    added.name = uv_layer_name
                    return
        else:
            return super().set_new_item_name(data, added)


class UVMapListRemove(CollectionRemoveBase, KeepUVMapListControlBase):
    bl_idname = 'keep_uv_map_list_remove'


class UVMapListMove(CollectionMoveBase, KeepUVMapListControlBase):
    bl_idname = 'keep_uv_map_list_move'


def draw_uv_map_list(layout: UILayout, keep_uv_map_list: KeepUVMapList):
    row = layout.row(align=True)
    row.template_list(
        KeepUVMapUIList.bl_idname, "",
        keep_uv_map_list, 'data',
        keep_uv_map_list, 'active_index',
        # Two rows minimum, since there is another option specifically for keeping only one UV Map
        sort_lock=True, rows=2)
    row.separator()
    vertical_buttons_col = row.column(align=True)
    vertical_buttons_col.operator(UVMapListAdd.bl_idname, text="", icon="ADD")
    vertical_buttons_col.operator(UVMapListRemove.bl_idname, text="", icon="REMOVE")
    row.separator()
    vertical_buttons_col2 = row.column(align=True)
    vertical_buttons_col2.operator(UVMapListMove.bl_idname, text="", icon="TRIA_UP").type = 'UP'
    vertical_buttons_col2.operator(UVMapListMove.bl_idname, text="", icon="TRIA_DOWN").type = 'DOWN'


register, unregister = register_module_classes_factory(__name__, globals())
