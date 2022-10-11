import bpy
from typing import Optional
from itertools import chain

from bpy.props import CollectionProperty, IntProperty, BoolProperty, StringProperty, EnumProperty, PointerProperty
from bpy.types import PropertyGroup, Scene, Context, Object

from .registration import register_module_classes_factory, _PROP_PREFIX, IdPropertyGroup, CollectionPropBase

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

                suffix_number = 0
                while existing_element_new_name in disallowed_names:
                    suffix_number += 1
                    # my_name -> my_name.001 -> my_name.002 -> my_name.003 etc.
                    existing_element_new_name = f"{existing_element_orig_name}.{suffix_number:03d}"
                    # print(f"Trying new name '{existing_element_new_name}'")

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
    build_settings = scene_group.build_settings

    old_name = self.name
    new_name = self.name_prop

    if old_name != new_name:
        existing_update = update_name_ensure_unique(self, build_settings, 'name_prop')
        if existing_update is None:
            # Propagate name change to object settings of objects in the corresponding scene
            for obj in scene.objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.object_settings
                if old_name in object_settings:
                    object_settings[old_name].name_prop = new_name
        else:
            existing_old_name, existing_new_name = existing_update
            # Propagate name changes to object settings of objects in the corresponding scene
            for obj in scene.objects:
                object_group = ObjectPropertyGroup.get_group(obj)
                object_settings = object_group.object_settings

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
        description="Reduce to two meshes as a final step, one mesh that has shape keys and a second mesh that doesn't have shape keys",
        default=True
    )
    shape_keys_mesh_name: StringProperty(default="Body")
    no_shape_keys_mesh_name: StringProperty(default="MainBody")
    ignore_hidden_objects: BoolProperty(name="Ignore hidden objects", default=True)
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
    do_limit_total: BoolProperty(
        name="Limit Total Weights",
        description="Limit the number of weights per vertex."
                    "\nVRChat's max is 4, Unity's default max is 4, other software may vary"
    )
    limit_num_groups: IntProperty(
        name="Number of weights",
        description="Limit the number of weights per vertex."
                    ,
        default=4,
        min=1,
    )


_DELETE_ = 'DELETE_'
_MERGE_ = 'MERGE_'


class ShapeKeyOp(PropertyGroup):
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

    _types = (
        (DELETE_AFTER, "Delete After", "Delete all shape keys after the specified shape key"),
        (DELETE_BEFORE, "Delete Before", "Delete all shape keys before the specified shape key"),
        (DELETE_BETWEEN, "Delete Between", "Delete all shape keys between (exclusive) the specified shape keys"),
        (DELETE_SINGLE, "Delete Shape", "Delete by name"),
        (MERGE_PREFIX, "Merge Prefix", "Merge shape keys that start with the specified prefix into one shape key"),
        (MERGE_SUFFIX, "Merge Suffix", "Merge shape keys that start with the specified suffix into one shape key"),
        (MERGE_COMMON_BEFORE_DELIMITER, "Merge Common Before Delimiter", "Merge shape keys that start with the same characters up to a delimiter"),
        (MERGE_COMMON_AFTER_DELIMITER, "Merge Common After Delimiter", "Merge shape keys that start with the same characters up to a delimiter"),
        (DELETE_REGEX, "Delete Regex", "Delete shape keys whose name matches a regular expression"),
        # TODO: Do we want some extra functionality that also compares capture groups? This would be for the consecutive mode
        (MERGE_REGEX, "Merge Regex", "Merge shape keys that match the specified regular expression into one shape key"),
    )
    MERGE_OPS = {t[0] for t in _types if t[0].startswith(_MERGE_)}
    DELETE_OPS = {t[0] for t in _types if t[0].startswith(_DELETE_)}
    _type_name_lookup = {t[0]: t[1] for t in _types}

    type: EnumProperty(
        name="Type",
        items=_types
    )
    delete_after_name: StringProperty(
        name="Delete after",
        description="Delete shape keys after the specified shape key",
    )
    delete_before_name: StringProperty(
        name="Delete before",
        description="Delete shape keys before the specified shape key (will not delete the first shape key)",
    )
    pattern: StringProperty(
        name="Pattern",
        description="Prefix, suffix or other pattern used to match shape keys"
    )
    ignore_regex: StringProperty(
        name="Ignore Regex Pattern",
        description="If a shape key's name matches this regex pattern, ignore it from the shape key operation."
                    '\nFor example, to ignore the common names for VRChat visemes, such as vrc.sil, use "vrc\\..+" to'
                    'ignore every shape key starting with "vrc."',
        default=r"vrc\..+",
    )
    # delimiter: StringProperty(
    #     name="Delimiter",
    #     description="Delimiter used to match shape keys"
    # )
    merge_grouping: EnumProperty(
        name="Merge grouping",
        items=[
            ('CONSECUTIVE', "Consecutive", "Only consecutive shape keys matching the pattern will be merged together"),
            ('ALL', "All", "All shape keys matching the same pattern will be merged together"),
        ],
        default='CONSECUTIVE',
    )

    def get_display_name(self):
        # TODO: See if this can be made more informative
        return self._type_name_lookup.get(self.type, "ERROR")


del _DELETE_, _MERGE_


class ShapeKeyOps(CollectionPropBase[ShapeKeyOp], PropertyGroup):
    data: CollectionProperty(type=ShapeKeyOp)


def object_build_settings_update_name(self: 'ObjectBuildSettings', context: Context):
    # id_data is the ID that owns this which should be the object
    obj = self.id_data
    object_group = ObjectPropertyGroup.get_group(obj)

    all_scene_build_settings = set(chain.from_iterable(ScenePropertyGroup.get_group(s).build_settings.keys() for s in bpy.data.scenes))
    update_name_ensure_unique(self, object_group.object_settings, 'name_prop', extra_disallowed_names=all_scene_build_settings)


class ObjectSettings(PropertyGroup):
    target_object_name: StringProperty(
        name="Built name",
        description="The name of the object once building is complete.\n"
                    "All objects with the same name will be joined together (if they're the same type)\n"
                    "Leave blank to keep the current name"
    )


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
        default='KEEP'
    )
    shape_key_ops: PointerProperty(type=ShapeKeyOps)
    # TODO: BoolProperty to remove shape keys that do next to nothing
    # TODO: FloatProperty to specify how much movement is still considered nothing
    # TODO: BoolProperty to do a special mmd convert: translate according to user dictionary and rename conflicts with
    #  Cats translation names operation


class UVSettings(PropertyGroup):
    # TODO: Extend this to a collection property so that multiple can be kept
    # UV Layer to keep
    keep_only_uv_map: StringProperty(name="UV Map to keep", description="Name of the only UV map to keep on this mesh")


class VertexGroupSettings(PropertyGroup):
    # Clean up vertex groups that aren't used by the armature
    remove_non_deform_vertex_groups: BoolProperty(
        name="Remove non-deform",
        default=True,
        description="Remove vertex groups that don't have an associated deform bone"
    )
    do_limit_total: BoolProperty("")
    limit_num_groups: IntProperty(
        name="Number of weights",
        description="Limit the number of weights per vertex.",
        default=4,
        min=1,
    )
    # TODO: Try smartly limiting vertex group weights


class VertexColorSettings(PropertyGroup):
    remove_vertex_colors: BoolProperty(
        name="Remove vertex colors",
        default=True,
        description="Remove all vertex colors"
    )


class MaterialSettings(PropertyGroup):
    # TODO: Extend to being able to re-map materials from one to another
    keep_only_material: StringProperty(
        name="Material to keep",
        description="Name of the only Material to keep on the mesh"
    )
    # materials_remap
    remap_materials: BoolProperty(default=False)
    # materials_remap: CollectionProperty(type=<custom type needed?>)


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
    object_settings: PointerProperty(type=ObjectSettings)
    armature_settings: PointerProperty(type=ArmatureSettings)
    mesh_settings: PointerProperty(type=MeshSettings)


class ScenePropertyGroup(IdPropertyGroup, PropertyGroup):
    _registration_name = f'{_PROP_PREFIX}_scene_settings_group'
    _registration_type = Scene

    # The main collection and its active index
    build_settings: CollectionProperty(type=SceneBuildSettings)
    build_settings_active_index: IntProperty()

    # Tag export scenes as such so that they and they can be detected more easily for deletion
    is_export_scene: BoolProperty(
        name="Is an export scene",
        description="True only for export scenes created by running the Avatar Builder"
    )
    export_scene_source_scene: StringProperty(
        name="Source Scene name",
        description="Name of the scene this export scene was created from and should swap back to when deleted",
    )

    def get_active(self) -> Optional[SceneBuildSettings]:
        settings = self.build_settings
        active_index = self.build_settings_active_index
        if settings and 0 <= active_index < len(settings):
            return settings[active_index]
        else:
            return None


class ObjectPropertyGroup(IdPropertyGroup, PropertyGroup):
    _registration_name = f'{_PROP_PREFIX}_object_settings_group'
    _registration_type = Object

    object_settings: CollectionProperty(type=ObjectBuildSettings)
    object_settings_active_index: IntProperty()
    sync_active_with_scene: BoolProperty(name="Toggle scene sync", default=True)

    def get_active_settings(self) -> Optional[ObjectBuildSettings]:
        settings = self.object_settings
        active_index = self.object_settings_active_index
        if settings and 0 <= active_index < len(settings):
            return settings[active_index]
        else:
            return None

    def get_synced_settings(self, scene: Scene) -> Optional[ObjectBuildSettings]:
        active_build_settings = ScenePropertyGroup.get_group(scene).get_active()
        if active_build_settings and active_build_settings.name in self.object_settings:
            return self.object_settings[active_build_settings.name]
        else:
            return None

    def get_displayed_settings(self, scene: Scene) -> Optional[ObjectBuildSettings]:
        if self.sync_active_with_scene:
            return self.get_synced_settings(scene)
        else:
            return self.get_active_settings()


register, unregister = register_module_classes_factory(__name__, globals())
