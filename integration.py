import bpy

from .registration import dummy_register_factory


# TODO: Rename to something more like 'get_gret_version' and instead get gret from the addons and look at its version
def check_gret_shape_key_apply_modifiers():
    """Returns a truthy value when valid.
     Returns None when not detected.
     Returns False when detected, but the version could not be determined."""
    if hasattr(bpy.ops, 'gret') and hasattr(bpy.ops.gret, 'shape_key_apply_modifiers'):
        operator = bpy.ops.gret.shape_key_apply_modifiers
        for prop in operator.get_rna_type().properties:
            identifier = prop.identifier
            if identifier == 'modifier_mask':
                # Not yet implemented
                # return identifier
                return False
            elif identifier == 'keep_modifiers':
                return identifier
        return False
    return None


register, unregister = dummy_register_factory()
