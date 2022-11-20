import bpy
from typing import Optional, Callable, Any
from itertools import chain
from dataclasses import dataclass

from bpy.props import CollectionProperty, IntProperty, BoolProperty, StringProperty, EnumProperty, PointerProperty
from bpy.types import PropertyGroup, Scene, Context, Object, UILayout, Key, Mesh, Material, WindowManager

from .registration import register_module_classes_factory, _PROP_PREFIX, IdPropertyGroup, CollectionPropBase
from .preferences import object_ui_sync_enabled
from . import utils

# bpy_prop_collection_idprop isn't currently exposed in bpy.types, so it can't actually be imported. It's presence here
# is purely to assist with development where it exists as a fake class.
if hasattr(bpy.types, '_bpy_prop_collection_idprop'):
    # noinspection PyProtectedMember
    from bpy.types import _bpy_prop_collection_idprop as bpy_prop_collection_idprop
else:
    bpy_prop_collection_idprop = bpy.types.bpy_prop_collection


def update_name_ensure_unique(element_updating: PropertyGroup, collection_prop: bpy_prop_collection_idprop,
                              name_prop_name: str, extra_disallowed_names: set[str] = None):
    """Helper function for ensuring name uniqueness with collection properties"""
    # Ensure name uniqueness by renaming the other found element with the same name, if it exists

    # Note that care is needed when renaming another element, since that will call this function too, but for that
    # element

    # The internal name should always be the old name, since it's only this function that updates it after initial
    # creation
    old_name = element_updating.name
    new_name = getattr(element_updating, name_prop_name)
    if extra_disallowed_names is None:
        extra_disallowed_names = set()

    if new_name != old_name:
        try:
            # Get all existing internal names, excluding our new one
            existing_names = {bs.name for bs in collection_prop} - {old_name}
            print(f"Updating name of '{element_updating}' from '{old_name}' to '{new_name}' and ensuring uniqueness")
            if new_name in collection_prop:
                # print("New name already exists!")
                existing_element = collection_prop[new_name]

                existing_element_new_name = new_name

                # Make sure we can't possibly set the existing element's name to the new name of self or any other elements
                disallowed_names = existing_names.union({new_name})
                disallowed_names.update(extra_disallowed_names)

                # Since we just got this element by name, this must be its current name
                existing_element_name = new_name

                # Strip ".[0-9]+" from the end of the name to get the original name
                last_period_idx = existing_element_name.rfind(".")
                if last_period_idx != -1:
                    # Everything after the last period
                    suffix = existing_element_name[last_period_idx + 1:]
                    if suffix.isdigit():
                        # Original name is everything before the last period
                        existing_element_orig_name = existing_element_name[:last_period_idx]
                    else:
                        # The name has "." in it, but either there is nothing after it or there are characters that aren't
                        # digits
                        existing_element_orig_name = existing_element_name
                else:
                    # The name doesn't have "." in it, so use it as is
                    existing_element_orig_name = existing_element_name

                # TODO: Could check if existing_element_orig_name in disallowed_names first

                if existing_element_new_name in disallowed_names:
                    existing_element_new_name = utils.get_unique_name(existing_element_orig_name, disallowed_names)

                # Update the name of the existing element, so it won't conflict with the new name of self and won't conflict
                # with the names of any other elements either

                # print(f"Renaming already existing element with the same name as the new name '{new_name}' to '{existing_element_new_name}'")

                # Need to update the name of self first, otherwise when we change the name_prop of the existing element,
                # it will see the old name of self
                element_updating.name = new_name

                # Return other name change so that it can be propagated correctly to objects when updating a
                # SceneBuildSettings
                return change_name_no_propagate(existing_element, name_prop_name, existing_element_new_name)
                # print(f"Renamed already existing element with the same name as the new name '{new_name}'")
        finally:
            # Always update internal name to match, this name is used when subscripting the collection to get a specific element
            element_updating.name = new_name


def change_name_no_propagate(element_updating: PropertyGroup, name_prop_name: str, new_name: str):
    old_name = element_updating.name
    print(f"Updating name of '{element_updating}' from '{old_name}' to '{new_name}' without propagation")
    element_updating.name = new_name
    setattr(element_updating, name_prop_name, new_name)
    return old_name, new_name


def scene_build_settings_update_name(self: 'SceneBuildSettings', context: Context):
    scene = context.scene
    scene_group = ScenePropertyGroup.get_group(scene)
    build_settings = scene_group.collection

    old_name = self.name
    new_name = self.name_prop

    if old_name != new_name:
        existing_update = update_name_ensure_unique(self, build_settings, 'name_prop')
        if existing_update is None:
            # Propagate name change to object settings of objects in the corresponding scene
            for obj in scene.objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.collection
                if old_name in object_settings:
                    object_settings[old_name].name_prop = new_name
        else:
            existing_old_name, existing_new_name = existing_update
            # Propagate name changes to object settings of objects in the corresponding scene
            for obj in scene.objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.collection

                self_settings = None
                existing_settings = None
                if old_name in object_settings:
                    self_settings = object_settings[old_name]
                if existing_old_name in object_settings:
                    existing_settings = object_settings[existing_old_name]

                if self_settings:
                    change_name_no_propagate(self_settings, 'name_prop', new_name)
                if existing_settings:
                    change_name_no_propagate(existing_settings, 'name_prop', existing_new_name)


class MmdShapeKeySettings(PropertyGroup):
    do_remap: BoolProperty(
        name="Remap shape keys for VRChat MMD",
        description="Remap shape keys for VRChat MMD dance worlds. Current mappings are in the MMD Shape Mappings panel"
                    " in the 3D View",
        default=False,
    )
    remap_to: EnumProperty(
        name="Remap to",
        items=(
            ('JAPANESE', "Japanese", "Japanese shape keys are the most widely supported"),
            ('CATS', "Cats Translations", "Occasionally, dances support some of the Cats translations of the Japanese"
                                          " shape keys. It is recommended to instead use the original Japanese due to"
                                          " the wider support."),
        ),
        default='JAPANESE',
        description="Pick which names to remap to",
    )
    avoid_double_activation: BoolProperty(
        name="Avoid Double Activation",
        description="Some VRChat MMD dances activate both the original Japanese and the Cats translation. With this"
                    " enabled, if you end up with both the Japanese and Cats translation as shapes on a Mesh, the one"
                    " you are not remapping to will be renamed to avoid both of the shapes being activated at the same"
                    " time.",
        default=True,
    )
    limit_to_body: BoolProperty(
        name="'Body' Mesh Only",
        description="Only perform remapping on a mesh called Body. VRChat MMD dance worlds usually require that the"
                    " mesh with shape keys on is called Body",
        default=True
    )


class SceneBuildSettings(PropertyGroup):
    # Shown in UI
    # Create export scene as f"Export {build_settings.name} scene"
    name_prop: StringProperty(default="BuildSettings", update=scene_build_settings_update_name)

    # TODO: Property enabled by default to 're-sync vertices with basis shape keys' with description about how the two
    #  can become desynced outside of edit mode and how the FBX exporter exports vertices and not the basis
    # TODO: Or add operator to re-sync vertices with basis shape keys for all objects in scene, maybe in an extra
    #  'tools' panel for Avatar Builder
    # TODO: Or both: add a small button next to the property, that allows users to run the re-sync manually. The
    #  operator should report the number of meshes it checked and how many had their sync fixed

    # TODO: Also property/operator for checking NaNs in UV components?

    reduce_to_two_meshes: BoolProperty(
        name="Reduce to two meshes",
        description="Reduce to two meshes after individual object processing. One mesh that has shape keys and a second"
                    " mesh that doesn't have shape keys",
        default=True
    )
    shape_keys_mesh_name: StringProperty(
        default="Body",
        description="Name to give to the mesh with shape keys",
    )
    no_shape_keys_mesh_name: StringProperty(
        default="MainBody",
        description="Name to give to the mesh without shape keys",
    )
    ignore_hidden_objects: BoolProperty(
        name="Ignore hidden objects",
        default=True,
        description="Ignore hidden Objects from the build"
    )
    # TODO: Needs UI and needs to actually be used
    remove_settings_from_built_avatar: BoolProperty(name="Remove settings from built avatar", default=True)
    # TODO: Add the option below to join mesh UVMaps by index instead of name
    # uv_map_joining: EnumProperty(
    #     items=[
    #         (
    #             'NAME',
    #             "By name",
    #             "Join UV Maps by name, this is the default Blender behaviour when joining meshes"
    #         ),
    #         (
    #             'INDEX',
    #             "By index",
    #             "Join UV Maps by index. This will results in all UV Maps being renamed according to their index"
    #         ),
    #         # TODO: Add a 'FIRST_BY_INDEX_OTHERS_BY_NAME' option, basically, just rename the first UVMap of every mesh to
    #         #  "UVMap" before any joining happens
    #     ],
    #     name="Join UV Maps",
    #     default='INDEX',
    #     description="Specify how UV Maps of meshes should be combined when meshes are joined together",
    # )
    # TODO: Try smartly limiting vertex group weights (dissolving weights into parents or parents of parents if the
    #  vertex is also in that group)
    do_limit_total: BoolProperty(
        name="Limit Total Weights",
        description="Limit the number of deform weights per vertex."
                    "\nVRChat's max is 4, Unity's default max is 4, other software may vary"
    )
    limit_num_groups: IntProperty(
        name="Number of weights",
        description="Limit the number of weights per vertex.",
        default=4,
        min=1,
    )
    mmd_settings: PointerProperty(type=MmdShapeKeySettings)

    def set_name_no_propagate(self, new_name: str):
        change_name_no_propagate(self, 'name_prop', new_name)


def _draw_pattern_prop(layout: UILayout, _shape_keys: Key, item: "ShapeKeyOp", label: str):
    layout.prop(item, 'pattern', text=label)


def _draw_delete_between_props(layout: UILayout, shape_keys: Key, item: "ShapeKeyOp", label: str):
    row = layout.row(align=True)
    row.prop_search(item, 'delete_after_name', shape_keys, 'key_blocks', text=label)
    row.prop_search(item, 'delete_before_name', shape_keys, 'key_blocks', text="")


@dataclass
class ShapeKeyOpData:
    id: str
    label: str
    description: str
    list_label: str
    draw_props: Callable[[UILayout, Key, "ShapeKeyOp", str], Any]
    menu_label: str


_DELETE_ = 'DELETE_'
_MERGE_ = 'MERGE_'


class ShapeKeyOp(PropertyGroup):
    # TODO: IGNORE_ ops that effectively hide the shape keys they match from the rest of the operations?
    DELETE_AFTER = _DELETE_ + 'AFTER'
    DELETE_BEFORE = _DELETE_ + 'BEFORE'
    DELETE_BETWEEN = _DELETE_ + 'BETWEEN'
    DELETE_SINGLE = _DELETE_ + 'SINGLE'
    DELETE_REGEX = _DELETE_ + 'REGEX'
    MERGE_PREFIX = _MERGE_ + 'PREFIX'
    MERGE_SUFFIX = _MERGE_ + 'SUFFIX'
    MERGE_COMMON_BEFORE_DELIMITER = _MERGE_ + 'COMMON_BEFORE_DELIMITER'
    MERGE_COMMON_AFTER_DELIMITER = _MERGE_ + 'COMMON_AFTER_DELIMITER'
    MERGE_REGEX = _MERGE_ + 'REGEX'
    GROUPING_ALL_ICON = 'WORLD_DATA'
    GROUPING_CONSECUTIVE_ICON = 'THREE_DOTS'

    _TYPE_DATA = (
        ShapeKeyOpData(
            id=DELETE_AFTER,
            label="Delete After",
            description="Delete all shape keys after the specified shape key",
            list_label="After:",
            draw_props=lambda layout, shape_keys, item, label: layout.prop_search(item, 'delete_after_name', shape_keys, 'key_blocks', text=label),
            menu_label="After Shape Key",
        ),
        ShapeKeyOpData(
            id=DELETE_BEFORE,
            label="Delete Before",
            description="Delete all shape keys before the specified shape key, excluding the reference ('basis') shape"
                        " key",
            list_label="Before:",
            draw_props=lambda layout, shape_keys, item, label: layout.prop_search(item, 'delete_before_name', shape_keys, 'key_blocks', text=label),
            menu_label="Before Shape Key",
        ),
        ShapeKeyOpData(
            id=DELETE_BETWEEN,
            label="Delete Between",
            description="Delete all shape keys between (exclusive) the specified shape keys",
            list_label="Between:",
            draw_props=_draw_delete_between_props,
            menu_label="Between Two Shape Keys",
        ),
        ShapeKeyOpData(
            id=DELETE_SINGLE,
            label="Delete Shape",
            description="Delete by name",
            list_label="Name:",
            draw_props=lambda layout, shape_keys, item, label: layout.prop_search(item, 'pattern', shape_keys, 'key_blocks', text=label),
            menu_label="Specific Shape Key",
        ),
        ShapeKeyOpData(
            id=DELETE_REGEX,
            label="Delete Regex",
            description="Delete shape keys whose name matches a regular expression",
            list_label="Regex:",
            draw_props=_draw_pattern_prop,
            menu_label="By Regex Pattern",
        ),
        ShapeKeyOpData(
            id=MERGE_PREFIX,
            label="Merge Prefix",
            description="Merge shape keys that start with the specified prefix into one shape key",
            list_label="Prefix:",
            draw_props=_draw_pattern_prop,
            menu_label="By Prefix",
        ),
        ShapeKeyOpData(
            id=MERGE_SUFFIX,
            label="Merge Suffix",
            description="Merge shape keys that start with the specified suffix into one shape key",
            list_label="Suffix:",
            draw_props=_draw_pattern_prop,
            menu_label="By Suffix",
        ),
        ShapeKeyOpData(
            id=MERGE_COMMON_BEFORE_DELIMITER,
            label="Merge Common Before Delimiter",
            description="Merge shape keys that start with the same characters up to a delimiter. If the delimiter is"
                        " not found, the entire name is considered the common part",
            list_label="Before Delimiter:",
            draw_props=_draw_pattern_prop,
            menu_label="By Common Part Before Delimiter",
        ),
        ShapeKeyOpData(
            id=MERGE_COMMON_AFTER_DELIMITER,
            label="Merge Common After Delimiter",
            description="Merge shape keys that have the same characters after a delimiter. If the delimiter is not"
                        " found, the entire name is considered the common part",
            list_label="After Delimiter:",
            draw_props=_draw_pattern_prop,
            menu_label="By Common Part After Delimiter",
        ),
        ShapeKeyOpData(
            id=MERGE_REGEX,
            label="Merge Regex",
            description="Merge shape keys that match the specified regular expression into one shape key. If the"
                        " expression contains capture groups, they must match to be merged",
            list_label="Regex:",
            draw_props=_draw_pattern_prop,
            menu_label="By Regex",
        ),
    )
    OPS_DICT: dict[str, ShapeKeyOpData] = {t.id: t for t in _TYPE_DATA}
    TYPE_ITEMS: tuple[str, str, str] = tuple((t.id, t.label, t.description) for t in OPS_DICT.values())
    MERGE_OPS_DICT: dict[str, ShapeKeyOpData] = {k: v for k, v in OPS_DICT.items() if k.startswith(_MERGE_)}
    DELETE_OPS_DICT: dict[str, ShapeKeyOpData] = {k: v for k, v in OPS_DICT.items() if k.startswith(_DELETE_)}

    type: EnumProperty(
        name="Type",
        items=TYPE_ITEMS,
        options={'HIDDEN'},
    )
    delete_after_name: StringProperty(
        name="Delete after",
        description="Delete shape keys after the specified shape key",
    )
    delete_before_name: StringProperty(
        name="Delete before",
        description="Delete shape keys before the specified shape key (will not delete the first shape key)",
    )
    # TODO: When updating pattern (that is regex) or ignore_regex, try to compile the regex, if an error occurs, update
    #  a hidden property that stores whether the regex is valid, then, the UI can draw the property and element in the
    #  UI list with .alert = True when the regex is invalid. Also, the op can be skipped when attempting to build
    pattern: StringProperty(
        name="Pattern",
        description="Prefix, suffix or other pattern used to match shape keys"
    )
    # TODO: Replace with IGNORE_ op
    ignore_regex: StringProperty(
        name="Ignore Regex Pattern",
        description="If a shape key's name matches this regex pattern, ignore it from the shape key operation."
                    '\nFor example, to ignore the common names for VRChat visemes, such as vrc.sil, use "vrc\\..+" to'
                    'ignore every shape key starting with "vrc."',
        default=r"vrc\..+",
    )
    merge_grouping: EnumProperty(
        name="Merge grouping",
        items=[
            ('CONSECUTIVE', "Consecutive", "Only consecutive shape keys matching the pattern will be merged together",
             GROUPING_CONSECUTIVE_ICON, 0),
            ('ALL', "All", "All shape keys matching the same pattern will be merged together", GROUPING_ALL_ICON, 1),
        ],
        default='CONSECUTIVE',
    )


del _DELETE_, _MERGE_


class ShapeKeyOps(CollectionPropBase[ShapeKeyOp]):
    collection: CollectionProperty(type=ShapeKeyOp)


def object_build_settings_update_name(self: 'ObjectBuildSettings', context: Context):
    # id_data is the ID that owns this which should be the object
    obj = self.id_data
    object_group = ObjectPropertyGroup.get_group(obj)

    all_scene_build_settings = set(chain.from_iterable(ScenePropertyGroup.get_group(s).collection.keys() for s in bpy.data.scenes))
    update_name_ensure_unique(self, object_group.collection, 'name_prop', extra_disallowed_names=all_scene_build_settings)


class ArmatureSettings(PropertyGroup):
    # Armature object properties
    armature_export_pose: EnumProperty(
        name="Export pose",
        description="Pose to set when exporting",
        items=[
            ('REST', "Rest Position", ""),
            ('POSE', "Pose Position", ""),
            ('CUSTOM_ASSET_LIBRARY', "Custom", ""),
            ('CUSTOM_POSE_LIBRARY', "Pose Library Marker (deprecated)", ""),
        ],
        default="POSE"
    )
    armature_export_pose_library_marker: StringProperty(name="Pose", description="Pose Library Marker (deprecated)")

    # TODO: Find out how asset viewer stuff works as the replacement for Pose Libraries
    #armature_export_pose_asset_library: PointerProperty()

    # TODO: Access via obj.pose_markers[name] when used
    armature_export_pose_pose_library_marker_name: StringProperty()

    # Change all the armature modifiers on meshes using this armature to the following setting for Preserve volume
    # modifier-controlled/yes/no
    armature_export_pose_preserve_volume: EnumProperty(
        name="Preserve volume",
        items=[
            ('MODIFIER', "Modifier controlled", ""),
            ('YES', "Enabled", ""),
            ('NO', "Disabled", ""),
        ],
        default='MODIFIER',
        description="Intended for use to override modifier settings when exporting for VRM, which requires a T-pose."
                    "\n\nWhen a model has been exported in an A-pose, put into a T-pose in Unity and exported as a VRM,"
                    " putting that VRM back into the original A-pose can result in a different appearance to how the"
                    " model was original exported."
                    "\n\nEnabling Preserve Volume and changing the pose to a T-pose before exporting may produce better"
                    " results than when exporting in an A-pose."
    )


class ShapeKeySettings(PropertyGroup):
    # TODO: Might there be any merit in allowing for APPLY_MIX after running CUSTOM ops?
    shape_keys_main_op: EnumProperty(
        name="Operation",
        items=[
            ('KEEP', "Keep", "Keep all the shape keys"),
            ('APPLY_MIX', "Apply Mix", "Set the mesh to the current mix of all the shape keys and then delete all the shape keys"),
            ('DELETE_ALL', "Delete All", "Delete all the shape keys"),
            ('CUSTOM', "Custom", "Merge or delete shape keys according to a series of custom operations"),
        ],
        default='KEEP',
        description="Operation to apply to the shape keys of this mesh",
    )
    shape_key_ops: PointerProperty(type=ShapeKeyOps)
    # TODO: BoolProperty to remove shape keys that do next to nothing
    # TODO: FloatProperty to specify how much movement is still considered nothing


class KeepUVMapList(CollectionPropBase[PropertyGroup]):
    # We only need the .name property, so we can use a plain PropertyGroup
    collection: CollectionProperty(type=PropertyGroup)


class UVSettings(PropertyGroup):
    # TODO: Extend this to a collection property so that multiple can be kept
    # UV Layers to keep
    uv_maps_to_keep: EnumProperty(
        name="UV Maps To Keep",
        items=(
            # All as the default so that newly created settings don't mess with the uv maps
            ('KEEP_ALL', "All", "Keep all the UV Maps"),
            # First should cover the majority of use cases
            ('FIRST', "First", "Keep the first UV Map"),
            # Single can be useful if a model is intended to be atlased differently (or not at all) for certain
            # platforms
            ('SINGLE', "Single", "Keep a single UV Map"),
            # For full control, a list is available
            # TODO: Also reorder by the order in the list
            ('LIST', "Choose", "Choose which UV Maps to keep. Duplicates entries will be ignored"),
            ('NONE', "None", "Delete all the UV Maps")
        ),
        description="Operation "
    )
    keep_only_uv_map: StringProperty(name="UV Map to keep", description="Name of the only UV map to keep on this mesh")
    keep_uv_map_list: PointerProperty(type=KeepUVMapList)


class VertexGroupSwap(PropertyGroup):
    swap_with: StringProperty()


class VertexGroupSwapCollection(CollectionPropBase[VertexGroupSwap]):
    collection: CollectionProperty(type=VertexGroupSwap)
    enabled: BoolProperty(
        name="Vertex Group swaps",
        description="On rare occasions, you may want to replace a vertex group with another. When enabled, provides a"
                    " list where you can choose vertex groups to have their weights swapped with another vertex group."
    )


class VertexGroupSettings(PropertyGroup):
    # Clean up vertex groups that aren't used by the armature
    remove_non_deform_vertex_groups: BoolProperty(
        name="Remove non-deform",
        default=True,
        description="Remove vertex groups that don't have an associated deform bone"
    )
    vertex_group_swaps: PointerProperty(type=VertexGroupSwapCollection)


class VertexColorSettings(PropertyGroup):
    remove_vertex_colors: BoolProperty(
        name="Remove vertex colors",
        default=True,
        description="Remove all vertex colors"
    )


class MaterialRemapElement(PropertyGroup):
    # Note that when meshes are joined together, if a material is in multiple slots, the polygons assigned the same
    # material across multiple slots will all be assigned to the first slot that material is in, therefore, we should
    # always merge materials when they are being remapped to the same material
    # TODO: Can we do something whereby we work with or display a UI for all slots of the mesh/object?
    from_mat: StringProperty()
    # to_mat should be a Pointer so that if a material is only used by a remap, it doesn't count as an orphan, since
    # the remap wants to use it
    to_mat: PointerProperty(type=Material, name="To")
    to_mat_str: StringProperty(name="Internal use", options={'HIDDEN'})


class MaterialRemap(CollectionPropBase[MaterialRemapElement]):
    collection: CollectionProperty(type=MaterialRemapElement)


class MaterialSettings(PropertyGroup):
    def materials_main_op_update(self, context):
        # When switching out from a main op that uses pointer properties, set the equivalent string properties and set
        # the pointer properties to None so that they don't keep being a user for the pointed to ID
        # When switching to a main op that uses pointer properties, try to set the pointers to the IDs specified by the
        # string properties (if the string properties have been set)
        if self.materials_main_op == 'REMAP_SINGLE':
            # New value is REMAP_SINGLE, attempt to set remap_single_material based on the stored string
            material_str = self.remap_single_material_str
            if material_str:
                self.remap_single_material = bpy.data.materials.get(material_str)
        else:
            # New value is not REMAP_SINGLE, if remap_single_material is set, clear it and set remap_single_material_str
            mat = self.remap_single_material
            if mat:
                try:
                    mat_name = mat.name
                except ReferenceError:
                    # Safety check in-case the material no longer exists
                    # '' will never be in bpy.data.materials
                    mat_name = ''
                if mat_name in bpy.data.materials:
                    # As another safety check, only set the string property if the material could be found by name
                    self.remap_single_material_str = mat_name
                self.remap_single_material = None

        if self.materials_main_op == 'REMAP':
            # Refresh length of mappings collection
            data = self.materials_remap.collection
            material_slots = context.object.material_slots
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
            # Restore pointers from strings
            for remap in data:
                mat_str = remap.to_mat_str
                if mat_str:
                    remap.to_mat = bpy.data.materials.get(mat_str)
        else:
            for remap in self.materials_remap.collection:
                mat = remap.to_mat
                if mat:
                    try:
                        # Huh, PyCharm bug. It sees that to_mat is set to None later on and for some reason thinks it
                        # is therefore also None here, despite the fact that mat is reassigned in each iteration.
                        # noinspection PyUnresolvedReferences
                        mat_name = mat.name
                    except ReferenceError:
                        # Safety check in-case the material no longer exists
                        # '' will never be in bpy.data.materials
                        mat_name = ''
                    if mat_name in bpy.data.materials:
                        # As another safety check, only set the string property if the material could be found by name
                        remap.to_mat_str = mat_name
                    remap.to_mat = None

    materials_main_op: EnumProperty(
        name="Operation",
        items=(
            ('KEEP', "None", "Do nothing, keep materials as they currently are"),
            ('KEEP_SINGLE', "Keep One", "Keep only one existing material"),
            ('REMAP_SINGLE', "Remap All", "Replace all materials with a single, different material"),
            ('REMAP', "Remap", "Individually replace each material with a different one"),
        ),
        description="Operation to apply to materials. Note that duplicate materials will always be combined in order to"
                    " keep material behaviour consistent with Blender combining duplicate materials automatically when"
                    " joining meshes. If you want two of the same material in different slots, e.g. one slot will be"
                    " used as a toggle in Unity, either make a copy of the material in advance or remap the duplicate"
                    " to its own unique material using the Remap All operation",
        update=materials_main_op_update,
    )
    keep_only_mat_slot: IntProperty(
        name="Material slot index to keep",
        options={'HIDDEN'},
    )
    # Used to keep reference to a material (by name) without needing to keep a Pointer. If the user changes the main op
    # from REMAP_SINGLE to something else, we don't want to leave the PointerProperty around since it counts as a user
    # of the Material is references, instead, we can store the name into this String property. When changing the main op
    # back to REMAP_SINGLE, we can attempt to restore the PointerProperty
    remap_single_material_str: StringProperty(name="Internal use", options={'HIDDEN'})

    def remap_single_material_update(self, context):
        if self.remap_single_material:
            self.remap_single_material_str = self.remap_single_material.name
        else:
            self.remap_single_material_str = ''
    remap_single_material: PointerProperty(
        type=Material,
        name="Material",
        description="Material to replace"
    )
    materials_remap: PointerProperty(type=MaterialRemap)


class ModifierSettings(PropertyGroup):
    apply_non_armature_modifiers: EnumProperty(
        name="Apply modifiers",
        items=[
            ('APPLY_IF_NO_SHAPES', "Apply if no shape keys", "Apply non-armature modifiers if there are no shape keys on the mesh (other than the Basis)"),
            ('NONE', "None", ""),
            ('APPLY_IF_POSSIBLE', "Apply if possible", "Apply all modifiers if possible, some modifiers can be applied even when a mesh has shape keys"),
            ('APPLY_FORCED', "Apply (forced)", "Apply modifiers, deleting all shape keys if necessary"),
            ('APPLY_KEEP_SHAPES_GRET', "Apply with shapes (gret addon)", "Apply modifiers. Using the gret addon when the mesh has shape keys"),
        ],
        default='APPLY_IF_POSSIBLE',
    )

    remove_disabled_modifiers: BoolProperty(
        name="Remove disabled modifiers",
        default=True,
        description="Remove all modifiers which are disabled in the viewport"
    )


class MeshSettings(PropertyGroup):
    # TODO: IntProperty for Join priority, used to order meshes that are being joined together (and deciding which mesh
    #  will be the mesh that all the others are joined to, used for both initial joining by name and reduce_to_two)
    ignore_reduce_to_two_meshes: BoolProperty(default=False)
    shape_key_settings: PointerProperty(type=ShapeKeySettings)
    uv_settings: PointerProperty(type=UVSettings)
    vertex_group_settings: PointerProperty(type=VertexGroupSettings)
    vertex_color_settings: PointerProperty(type=VertexColorSettings)
    material_settings: PointerProperty(type=MaterialSettings)
    modifier_settings: PointerProperty(type=ModifierSettings)


class ObjectBuildSettings(PropertyGroup):
    name_prop: StringProperty(default="BuildSettings", update=object_build_settings_update_name)

    include_in_build: BoolProperty(name="Include in build", default=True, description="Include these build settings. This lets you disable the export without deleting settings")
    target_object_name: StringProperty(
        name="Built name",
        description="The name of the object once building is complete.\n"
                    "All objects with the same name will be joined together (if they're the same type)\n"
                    "Leave blank to keep the current name"
    )
    join_order: IntProperty(
        name="Join Order",
        # Generally you would only want to decrease this value, so start at a positive value
        default=10,
        description="The order Objects are joined together affects the order of shape keys/material slots/etc. on the"
                    " combined mesh.\n"
                    "When joining Objects together, the Objects will be joined into the Object with lowest Join Order"
                    " and, in the order of their Join Order.\n"
                    "The combined Object will inherit the lowest Join Order of its parts.\n"
                    "If there is a tie for Join Order, the tie will be solved by comparing the number of Shape Keys"
                    " (most Shape Keys first) and then the Object's name"
    )
    armature_settings: PointerProperty(type=ArmatureSettings)
    mesh_settings: PointerProperty(type=MeshSettings)

    def set_name_no_propagate(self, new_name: str):
        change_name_no_propagate(self, 'name_prop', new_name)


class MmdShapeMapping(PropertyGroup):
    def update_name(self, context):
        """Update name used in filtering and sorting"""
        self.name = self.model_shape + self.mmd_name + self.cats_translation_name

    model_shape: StringProperty(
        name="Shape key name",
        description="Name of the shape key on your model",
        update=update_name
    )
    mmd_name: StringProperty(
        name="Japanese MMD shape name",
        description="The corresponding Japanese MMD shape key",
        update=update_name
    )
    cats_translation_name: StringProperty(
        name="Cats translated MMD shape name",
        description="The Cats translation for the Japanese MMD shape name",
        update=update_name,
    )
    comment: StringProperty(
        name="Comment",
        description="Comment for the MMD mapping"
    )


class MmdShapeMappingGroup(CollectionPropBase[MmdShapeMapping]):
    # Collection for mmd_shape_data
    collection: CollectionProperty(type=MmdShapeMapping)

    # noinspection PyMethodMayBeStatic,PyShadowingBuiltins
    def object_is_mesh_with_shapes(self, object: Object):
        return isinstance(object.data, Mesh) and object.data.shape_keys

    # Linking a mesh changes the UI to allow for searching for shape keys from that mesh when setting .model_shape of
    # each MmdShapeMapping
    linked_mesh_object: PointerProperty(
        name="Search Mesh",
        type=Object,
        poll=object_is_mesh_with_shapes,
        description="Pick a mesh to enable searching from when entering Shape Keys into mappings",
    )


class ScenePropertyGroup(IdPropertyGroup, CollectionPropBase[SceneBuildSettings]):
    _registration_name = f'{_PROP_PREFIX}_scene_settings_group'
    _registration_type = Scene

    # The main collection and its active index
    collection: CollectionProperty(type=SceneBuildSettings)

    # Tag export scenes as such so that they and they can be detected more easily for deletion
    is_export_scene: BoolProperty(
        name="Is an export scene",
        description="True only for export scenes created by running the Avatar Builder"
    )
    export_scene_source_scene: StringProperty(
        name="Source Scene name",
        description="Name of the scene this export scene was created from and should swap back to when deleted",
    )

    mmd_shape_mapping_group: PointerProperty(type=MmdShapeMappingGroup)

    def get_active(self) -> Optional[SceneBuildSettings]:
        settings = self.collection
        active_index = self.active_index
        if settings and 0 <= active_index < len(settings):
            return settings[active_index]
        else:
            return None


class ObjectPropertyGroup(IdPropertyGroup, CollectionPropBase[ObjectBuildSettings]):
    _registration_name = f'{_PROP_PREFIX}_object_settings_group'
    _registration_type = Object

    # Technically, we can't limit which Object types receive the PropertyGroup, but operators and other code can check
    # against the allowed types and skip Objects that don't have a correct type
    ALLOWED_TYPES = {'ARMATURE', 'MESH'}

    collection: CollectionProperty(type=ObjectBuildSettings)

    def get_active_settings(self) -> Optional[ObjectBuildSettings]:
        settings = self.collection
        active_index = self.active_index
        if settings and 0 <= active_index < len(settings):
            return settings[active_index]
        else:
            return None

    def get_synced_settings(self, scene: Scene) -> Optional[ObjectBuildSettings]:
        active_build_settings = ScenePropertyGroup.get_group(scene).get_active()
        if active_build_settings and active_build_settings.name in self.collection:
            return self.collection[active_build_settings.name]
        else:
            return None

    def get_displayed_settings(self, scene: Scene) -> Optional[ObjectBuildSettings]:
        if object_ui_sync_enabled():
            return self.get_synced_settings(scene)
        else:
            return self.get_active_settings()


class WmMeshToggles(PropertyGroup):
    vertex_groups: BoolProperty()
    shape_keys: BoolProperty()
    modifiers: BoolProperty()
    uv_layers: BoolProperty()
    vertex_colors: BoolProperty()
    materials: BoolProperty()


class WmArmatureToggles(PropertyGroup):
    pose: BoolProperty()


class WmObjectToggles(PropertyGroup):
    general: BoolProperty()
    mesh: PointerProperty(type=WmMeshToggles)
    armature: PointerProperty(type=WmArmatureToggles)


class WmSceneToggles(PropertyGroup):
    # General stuff such as whether to ignore hidden objects
    # general: BoolProperty()
    # TODO: Might want to separate vrchat options, e.g., one section for performance stuff and another for mmd and other
    # vrchat: BoolProperty()
    # unity: BoolProperty()
    pass


class UiToggles(PropertyGroup):
    scene: PointerProperty(type=WmSceneToggles)
    object: PointerProperty(type=WmObjectToggles)


class WindowManagerPropertyGroup(IdPropertyGroup, PropertyGroup):
    """Property group for UI toggles (and anything else that might want to be attached to the WindowManager"""
    _registration_name = f'{_PROP_PREFIX}_wm_group'
    _registration_type = WindowManager
    ui_toggles: PointerProperty(type=UiToggles)


register, unregister = register_module_classes_factory(__name__, globals())
