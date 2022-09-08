from bpy.utils import register_submodule_factory
register, unregister = register_submodule_factory(__name__, ['object_ui', 'scene_ui'])
