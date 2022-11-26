import bpy

from bpy.types import Context

from .extensions import ObjectPropertyGroup, ScenePropertyGroup
from .registration import register_module_classes_factory, CollectionPropBase, OperatorBase

"""For now, this is a module to assist with development only, but may be expanded upon if further migration is required
in the future"""


def property_migrate(old_holder, old_name, new_name=None, new_holder=None):
    # Default to the same name if no new_name is provided
    if new_name is None:
        new_name = old_name
    # Default to the same holder if no new_holder is provided
    if new_holder is None:
        new_holder = old_holder

    if old_name in old_holder:
        new_holder[new_name] = old_holder[old_name]
        del old_holder[old_name]


def migrate_collection_prop_base_data_to_collection():
    """Changes:
    CollectionPropBase.data renamed to collection
    """
    def convert_data_to_collection(collection_prop_base: CollectionPropBase):
        property_migrate(collection_prop_base, 'data', 'collection')
    for obj in bpy.data.objects:
        group = ObjectPropertyGroup.get_group(obj)
        for settings in group.collection:
            mesh_settings = settings.mesh_settings
            convert_data_to_collection(mesh_settings.shape_key_settings.shape_key_ops)
            convert_data_to_collection(mesh_settings.uv_settings.keep_uv_map_list)
            convert_data_to_collection(mesh_settings.vertex_group_settings.vertex_group_swaps)
            convert_data_to_collection(mesh_settings.material_settings.materials_remap)


def migrate_all_collection_props_to_collection_prop_base():
    """Changes:
    ScenePropertyGroup and ObjectPropertyGroup converted to CollectionPropBase subtypes, replacing the collection
    properties with 'collection' and the active index properties with 'active_index'"""
    for scene in bpy.data.scenes:
        group = ScenePropertyGroup.get_group(scene)
        mmd_mappings = group.mmd_shape_mapping_group
        property_migrate(mmd_mappings, 'mmd_shape_mappings', 'collection')
        property_migrate(mmd_mappings, 'mmd_shape_mappings_active_index', 'active_index')
        property_migrate(group, 'build_settings', 'collection')
        property_migrate(group, 'build_settings_active_index', 'active_index')
    for obj in bpy.data.objects:
        group = ObjectPropertyGroup.get_group(obj)
        property_migrate(group, 'object_settings', 'collection')
        property_migrate(group, 'object_settings_active_index', 'active_index')


def migrate_general_object_settings():
    """Changes:
    target_object_name and join_order properties have been moved to their own PropertyGroup, this makes it easier to
    copy all general object settings"""
    for obj in bpy.data.objects:
        group = ObjectPropertyGroup.get_group(obj)
        for settings in group.collection:
            general_settings = settings.general_settings
            property_migrate(settings, 'target_object_name', new_holder=general_settings)
            property_migrate(settings, 'join_order', new_holder=general_settings)


def migrate_0_0_1_to_0_1_0():
    migrate_all_collection_props_to_collection_prop_base()
    migrate_collection_prop_base_data_to_collection()
    migrate_general_object_settings()


class MigrateData(OperatorBase):
    """Internal use Operator for migrating data"""
    bl_idname = 'internal_migrate'
    bl_label = "Migrate"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context: Context) -> set[str]:
        migrate_0_0_1_to_0_1_0()
        return {'FINISHED'}


register_module_classes_factory(__name__, globals())
