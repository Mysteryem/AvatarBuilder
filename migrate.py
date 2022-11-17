import bpy

from bpy.types import Operator, Context

from .extensions import ObjectPropertyGroup
from .registration import register_module_classes_factory, CollectionPropBase

"""For now, this is a module to assist with development only, but may be expanded upon if further migration is required
in the future"""


def migrate_collection_prop_base_data_to_collection():
    """Changes:
    CollectionPropBase.data renamed to collection
    """
    def convert_data_to_collection(collection_prop_base: CollectionPropBase):
        if 'data' in collection_prop_base:
            collection_prop_base['collection'] = collection_prop_base['data']
            del collection_prop_base['data']
    for obj in bpy.data.objects:
        group = ObjectPropertyGroup.get_group(obj)
        for settings in group.object_settings:
            mesh_settings = settings.mesh_settings
            convert_data_to_collection(mesh_settings.shape_key_settings.shape_key_ops)
            convert_data_to_collection(mesh_settings.uv_settings.keep_uv_map_list)
            convert_data_to_collection(mesh_settings.vertex_group_settings.vertex_group_swaps)
            convert_data_to_collection(mesh_settings.material_settings.materials_remap)


def migrate_0_0_1_to_0_1_0():
    migrate_collection_prop_base_data_to_collection()


class MigrateData(Operator):
    """Internal use Operator for migrating data"""
    bl_idname = 'internal_migrate'
    bl_label = "Migrate"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context: Context) -> set[str]:
        migrate_0_0_1_to_0_1_0()
        return {'FINISHED'}


register, unregister = register_module_classes_factory(__name__, globals())
