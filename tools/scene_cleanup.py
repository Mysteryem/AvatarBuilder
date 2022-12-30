import bpy
from bpy.types import (
    PropertyGroup,
    UIList,
    Context,
    Event,
    AnyType,
    UILayout,
    ID,
    KeyingSetPath,
    Key,
    Object,
)
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty

from itertools import chain

from ..extensions import ScenePropertyGroup, WindowManagerPropertyGroup
from ..registration import register_module_classes_factory, OperatorBase
from ..ui_common import draw_expandable_header


# For the full list: https://docs.blender.org/api/current/bpy_types_enum_items/id_type_items.html#rna-enum-id-type-items
_ALL_ID_TYPES = set(x.identifier for x in KeyingSetPath.bl_rna.properties['id_type'].enum_items)


UserMap = dict[ID, set[ID]]


def get_user_map(exclude_set: set[str]) -> UserMap:
    all_types_minus_exclusions = _ALL_ID_TYPES - exclude_set
    return bpy.data.user_map(key_types=all_types_minus_exclusions, value_types=all_types_minus_exclusions)


def get_recursive_users(instance: ID, user_map: UserMap):
    visited = {instance}
    if instance in user_map:
        it = iter(user_map[instance])
        try:
            while True:
                next_id = next(it)
                if next_id in visited:
                    # If we've already seen an ID, then there's a loop in the users
                    continue
                else:
                    visited.add(next_id)
                    if next_id in user_map:
                        it = chain(it, user_map[next_id])
        except StopIteration:
            pass
    visited.remove(instance)
    return visited


class ObjectsListElement(PropertyGroup):
    # The existing 'name' property is used to reference the object by name
    purge: BoolProperty(name="Purge", description="Purge this object")
    # Icon is figured out upon element creation so that we don't have to keep Object references or get Objects by name
    # when drawing the list elements (unless the setting to ignore fake users is enabled)
    icon: StringProperty(options={'HIDDEN'}, default='QUESTION')

    def to_sort_key(self):
        return self.icon, self.name


icon_lookup = {
    'ARMATURE': 'OUTLINER_OB_ARMATURE',
    'CAMERA': 'OUTLINER_OB_CAMERA',
    'CURVE': 'OUTLINER_OB_CURVE',
    'EMPTY': 'OUTLINER_OB_EMPTY',
    'FONT': 'OUTLINER_OB_FONT',
    'GPENCIL': 'OUTLINER_OB_GREASEPENCIL',
    'HAIR': 'OUTLINER_OB_HAIR',
    'LATTICE': 'OUTLINER_OB_LATTICE',
    'LIGHT': 'OUTLINER_OB_LIGHT',
    'LIGHT_PROBE': 'OUTLINER_OB_LIGHTPROBE',
    'MESH': 'OUTLINER_OB_MESH',
    'META': 'OUTLINER_OB_META',
    'POINTCLOUD': 'OUTLINER_OB_POINTCLOUD',
    'SPEAKER': 'OUTLINER_OB_SPEAKER',
    'SURFACE': 'OUTLINER_OB_SURFACE',
    'VOLUME': 'OUTLINER_OB_VOLUME',
}


def obj_to_icon(obj: Object) -> str:
    if obj.type == 'EMPTY':
        if obj.instance_type == 'COLLECTION' and obj.instance_collection:
            icon = 'OUTLINER_OB_GROUP_INSTANCE'
        elif obj.empty_display_type == 'IMAGE':
            icon = 'OUTLINER_OB_IMAGE'
        else:
            field_type = obj.field.type
            if field_type and field_type != 'NONE':
                # alternate: 'OUTLINER_OB_EMPTY'
                icon = 'FORCE_' + field_type
            else:
                icon = 'OUTLINER_OB_EMPTY'
    else:
        icon = icon_lookup.get(obj.type, 'OBJECT_DATA')
    return icon


class UnusedObjectPurge(UIList):
    bl_idname = 'unused_object_purge'

    def draw_item(self, context: Context, layout: UILayout, data: 'PurgeUnusedObjects', item: ObjectsListElement, icon: int,
                  active_data: AnyType, active_property: str, index: int = 0, flt_flag: int = 0):
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(item, 'purge', text="")
        row.label(text=item.name, icon=item.icon)
        if data.ignore_fake_users:
            obj = bpy.data.objects.get(item.name)
            if obj:
                # Would it be useful to display the current number of users? This will include any ignored scenes and
                # collections.
                # row.prop(obj, 'users', text="", emboss=False)

                # Bool property automatically uses the next icon ('FAKE_USER_ON') when True
                row.prop(obj, 'use_fake_user', icon_only=True, icon='FAKE_USER_OFF', emboss=False)

    @staticmethod
    def sort_filter(data: "PurgeUnusedObjects"):
        """Given the list of items from the data, return a list of their new indices after being sorted"""
        items = data.objects_list

        sorted_items = sorted(items, key=ObjectsListElement.to_sort_key)

        item_to_sorted_idx = {item: idx for idx, item in enumerate(sorted_items)}
        return [item_to_sorted_idx[k] for k in items]

    def filter_items(self, context: Context, data: "PurgeUnusedObjects", property: str):
        objects_list = data.objects_list
        name_filter = bpy.types.UI_UL_list.filter_items_by_name(self.filter_name, self.bitflag_filter_item,
                                                                objects_list)
        # Always sorted, since iteration order of the objects is inconsistent
        sort_filter = self.sort_filter(data)
        return name_filter, sort_filter

    @classmethod
    def register(cls):
        cls.use_filter_sort_alpha = True


class PurgeUnusedObjects(OperatorBase):
    """Open a dialog to delete Objects in the current scene that are only used by scenes and collections and not by
    other Objects or other data.
    You may want to run this multiple times until no more objects are found"""
    bl_label = "Purge Scene-Only Objects"
    bl_idname = "purge_unused"
    bl_options = {"UNDO"}

    purge_data: BoolProperty(
        name="Purge Data",
        description="After purging an object also purge its data if its data no longer has any users",
        default=True,
    )

    objects_list: CollectionProperty(type=ObjectsListElement, name="Purge List")

    # We need an int property to be able to draw a UIList
    ignored_objects_list_active_index: IntProperty(
        name="_objects_list_active_index",
        # User should never see this and can't do anything with it anyway
        options={'HIDDEN'},
        # We don't intend to have an active index at all, so always supplying a value of -1 will make it so that the
        # active index is always out of bounds and can't be changed (there is different drawing for the active item)
        get=lambda self: -1,
    )

    def all_selected_get(self):
        # Skip the first element which should be the header
        return all(item.purge for item in self.objects_list[1:])

    def all_selected_set(self, value: bool):
        for item in self.objects_list:
            item.purge = value

    all_selected: BoolProperty(
        name="Select/Deselect All",
        description="Select/Deselect All",
        get=all_selected_get,
        set=all_selected_set,
    )

    def update_list(self, context: Context):
        objects_list = self.objects_list
        # Skip the first element as it's a header
        old_list = {e.name: e.purge for e in objects_list[1:]}
        objects_list.clear()

        object_subset = self.object_subset
        if object_subset == 'NOT_IN_BUILD':
            objects = set(context.scene.objects)
            scene_settings = ScenePropertyGroup.get_group(context.scene).active
            if scene_settings:
                objects.difference_update(scene_settings.objects_gen(context.view_layer))
        elif object_subset == 'NOT_IN_ANY_BUILD':
            objects = set(context.scene.objects)
            for scene_settings in ScenePropertyGroup.get_group(context.scene).collection:
                objects.difference_update(scene_settings.objects_gen(context.view_layer))
        elif object_subset == 'NOT_IN_ANY_BUILD_GLOBAL':
            objects = set(context.scene.objects)
            for scene in bpy.data.scenes:
                for scene_settings in ScenePropertyGroup.get_group(scene).collection:
                    objects.difference_update(scene_settings.objects_gen(context.view_layer))
        elif object_subset == 'VISIBLE':
            objects = context.visible_objects
        elif object_subset == 'SELECTED':
            objects = context.selected_objects
        elif object_subset == 'NOT_SELECTED':
            objects = set(context.scene.objects)
            objects.difference_update(context.selected_objects)
        elif object_subset == 'HIDDEN':
            objects = set(context.scene.objects)
            objects.difference_update(context.visible_objects)
        else:
            objects = []

        # Collections are always ignored. Note that this doesn't include Scene Collections, since those are part of the
        # scene and not separate Collection instances found in bpy.data.collections.
        exclude_types: set[str] = {'COLLECTION'}
        exclude_ids: set[ID] = set()

        scene_option = self.scene_option
        if scene_option == 'ALL':
            exclude_types.add('SCENE')
        elif scene_option == 'CONTEXT':
            exclude_ids.add(bpy.context.scene)

        if not self.ignore_fake_users:
            objects = (obj for obj in objects if not obj.use_fake_user)

        user_map = get_user_map(exclude_types)
        for obj in objects:
            if obj not in user_map or not (user_map[obj] - exclude_ids):
                list_element = objects_list.add()
                list_element.name = obj.name
                list_element.icon = obj_to_icon(obj)
                # Get the previous purge setting if it existed otherwise check use_fake_user
                list_element.purge = old_list.get(obj.name, not obj.use_fake_user)

    # Possibly, we could include scenes in the user_map, but ignore them if:
    #   obj.name in scene.objects and scene.user_of_id(obj) == 1
    # since that would indicate that the scene is only a user of obj because obj is in the scene
    # However, this is more complicated, because it appears that if the object is in the "Scene Collection" that adds +1
    # use and if the object is the active object, that also seems to add +1 use. There could be other cases that would
    # have to be taken into account for this to work properly.
    scene_option: EnumProperty(
        name="Ignore Scene Users",
        description="Scenes to ignore when counting users.\n"
                    "If an Object is in a scene, then that scene would normally be counted as a user of that Object."
                    "This has the side-effect that any properties belonging to the Scene that are set to an Object"
                    " don't count as users of that Object.",
        items=(
            ("CONTEXT", "Current", "Ignore only the current scene when counting users"),
            ("ALL", "All", "Ignore all scenes when counting users"),
        ),
        default="CONTEXT",
        update=update_list,
    )

    ignore_fake_users: BoolProperty(
        name="Ignore Fake Users",
        description="Ignore fake users when counting users.\n"
                    "Fake users tell Blender not to purge Objects and other data that are otherwise completely unused."
                    "Unlike some data, Objects don't normally have fake users, but if they do, the fake user setting of"
                    " the Objects can be ignored by enabling this option.",
        default=False,
        update=update_list,
    )

    object_subset: EnumProperty(
        name="Check",
        description="The subset of objects in the current scene to check",
        items=(
            (
                'NOT_IN_BUILD',
                "Not in current Build",
                "Check objects that are not part of the current build"
            ),
            (
                'NOT_IN_ANY_BUILD',
                "Not in any Build (current scene)",
                "Check objects that are not part of any build of the current scene"
            ),
            (
                'NOT_IN_ANY_BUILD_GLOBAL',
                "Not in any Build (all scenes)",
                "Check objects that are not part of any build of any scene"
            ),
            ('VISIBLE', "Visible", "Check objects that are visible"),
            ('HIDDEN', "Hidden", "Check objects that are hidden"),
            ('SELECTED', "Selected", "Check selected objects"),
            ('NOT_SELECTED', "Unselected", "Check objects that are not selected"),
        ),
        update=update_list,
        default="NOT_IN_ANY_BUILD_GLOBAL",
    )

    @classmethod
    def poll(cls, context: Context) -> bool:
        if context.mode != 'OBJECT':
            return cls.poll_fail("Must be in object mode")
        return True

    def draw(self, context: Context):
        layout = self.layout
        col = layout.column()
        # Can't make the UI have too many minimum rows, otherwise there could be problems if it doesn't fit on the
        # user's screen anymore
        min_rows = min(30, max(3, len(self.objects_list)))
        col.template_list(
            UnusedObjectPurge.bl_idname, "",
            self, 'objects_list',
            self, 'ignored_objects_list_active_index',
            sort_lock=True,
            rows=min_rows,
        )

        col.use_property_split = True

        col.prop(self, 'all_selected', text="Deselect All" if self.all_selected else "Select All", expand=True)

        col.separator()

        row = col.row(align=True)
        row.prop(self, 'object_subset', text=f"Subset of {context.scene.name} objects:")

        advanced_setting_visible, _, _ = draw_expandable_header(
            col,
            WindowManagerPropertyGroup.get_group(context.window_manager).ui_toggles.tools, 'objects_purge_settings'
        )
        if advanced_setting_visible:
            col.prop(self, 'purge_data')
            row = col.row(heading="Ignore Scene Users")
            row.prop(self, 'scene_option', expand=True)
            col.prop(self, 'ignore_fake_users')

    def execute(self, context: Context) -> set[str]:
        print("execute called")
        for element in self.objects_list:
            if element.purge:
                obj = bpy.data.objects.get(element.name)
                # Skip any objects that have use_fake_user enabled
                if not obj or obj.use_fake_user:
                    continue
                data = obj.data
                bpy.data.objects.remove(obj)
                # If we're deleting data, only delete it if it's not in use by something else, e.g. another Object
                if self.purge_data and data.users == 0:
                    remove_list = [data]
                    shape_keys = getattr(data, 'shapekeys', None)
                    # I can't imagine a case where shape_keys.users is more than 1, but maybe its possible somehow
                    if isinstance(shape_keys, Key) and shape_keys.users <= 1:
                        remove_list.append(shape_keys)
                    # Use batch_remove so that we don't have to try and find the correct collection based on the
                    # type of the data and so we can remove shape keys at the same time
                    bpy.data.batch_remove(ids=remove_list)
        return {'FINISHED'}

    def invoke(self, context: Context, event: Event) -> set[str]:
        self.update_list(context)
        # 350 is enough to fit our UI options and should be enough for most objects unless they have extraordinarily
        # long names
        return context.window_manager.invoke_props_dialog(self, width=350)


register_module_classes_factory(__name__, globals())
