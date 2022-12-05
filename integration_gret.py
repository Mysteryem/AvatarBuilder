import bpy
from bpy.types import Object, UILayout

from typing import Union, Literal

from . import utils


# noinspection PyUnresolvedReferences
_apply_modifiers_op = bpy.ops.gret.shape_key_apply_modifiers


def check_gret_shape_key_apply_modifiers() -> Union[str, Literal[False], None]:
    """When valid, returns a truthy string that also indicates version.
     When not detected, returns None.
     When detected, but the version could not be determined, returns False."""
    if utils.operator_exists(_apply_modifiers_op):
        for prop in _apply_modifiers_op.get_rna_type().properties:
            identifier = prop.identifier
            if identifier == 'modifier_mask' or identifier == 'keep_modifiers':
                return identifier
        return False
    return None


def _run_gret_shape_key_apply_modifiers_keep_modifiers(obj: Object, modifier_names_to_apply: set[str]):
    """Older version of Gret applies all non-disabled modifiers.
    Temporarily enables modifiers in modifier_names_to_apply and disables other modifiers, runs the operator and then
    restore the modifiers that were temporarily disabled."""
    mods_to_enable = []
    try:
        for mod in obj.modifiers:
            if mod.name in modifier_names_to_apply:
                # Normally we're only applying enabled modifiers, but this should make the code more robust
                mod.show_viewport = True
            elif mod.show_viewport:
                # Record that this modifier needs to be re-enabled
                mods_to_enable.append(mod.name)
                # Disable the modifier so that it doesn't get applied
                mod.show_viewport = False
        # noinspection PyUnresolvedReferences
        # Apply all non-disabled modifiers
        return utils.op_override(_apply_modifiers_op, {'object': obj})
    finally:
        # Restore modifiers that were temporarily disabled
        modifiers = obj.modifiers
        # The operator isn't our code, so don't assume that all the modifiers we expect to still exist actually
        # do
        expected_modifier_not_found = []
        for mod_name in mods_to_enable:
            mod = modifiers.get(mod_name)
            if mod:
                mod.show_viewport = True
            else:
                expected_modifier_not_found.append(mod_name)


def _run_gret_shape_key_apply_modifiers_modifier_mask(obj: Object, modifier_names_to_apply: set[str]):
    """Newer version of Gret. Only supports up to 32 modifiers (Blender limitation for BoolVectorProperty), uses a mask
    to decide which modifiers to apply.
    Figures out in advance if it's even possible to apply all the modifiers, then repeatedly calls the operator until
    all the modifiers in modifier_names_to_apply have been applied."""
    max_modifiers_per_call = 32
    full_mask = []
    context_override = {'object': obj}

    # Create the mask and find the index of the last modifier that needs to be applied
    last_apply_index = -1
    for i, mod in enumerate(obj.modifiers):
        if mod.name in modifier_names_to_apply:
            full_mask.append(True)
            last_apply_index = i
        else:
            full_mask.append(False)

    if last_apply_index == -1:
        # There are no modifiers to apply, so there is nothing to do
        return {'FINISHED'}
    elif last_apply_index < max_modifiers_per_call:
        # The last modifier that needs to be applied is within the first 32 modifiers, we can simply call the
        # operator once with a mask up to the last modifier that needs to be applied
        mask_up_to_and_including_last = full_mask[:last_apply_index + 1]
        return utils.op_override(_apply_modifiers_op, context_override, modifier_mask=mask_up_to_and_including_last)
    else:
        # The last modifier to apply is after the first 32 modifiers, so we need to apply the operator multiple
        # times until all the modifiers, that we want to apply, have been applied.
        # First check if we can apply all the modifiers when we have the limitation of only being able to apply
        # modifiers within the first 32 modifiers at a time. If there are 32 or more modifiers that won't be
        # applied, that are before the last modifier that will be applied, we cannot apply all the modifiers.
        num_no_apply_before_last_apply = sum(1 for do_apply in full_mask[:last_apply_index] if not do_apply)

        if num_no_apply_before_last_apply >= max_modifiers_per_call:
            raise RuntimeError(f"Only the first {max_modifiers_per_call} modifiers can be applied per call to"
                               f" gret, but there are {num_no_apply_before_last_apply} modifiers that aren't"
                               f" being applied before the last modifier which is being applied. This makes it"
                               f" impossible to apply all the modifiers in {modifier_names_to_apply} on"
                               f" {obj!r}")

        # Apply all the modifiers
        last_modifiers_length = len(obj.modifiers)
        while True:
            mask_this_call = full_mask[:max_modifiers_per_call]
            if any(mask_this_call):
                utils.op_override(_apply_modifiers_op, context_override, modifier_mask=mask_this_call)

                # Remove the indices for all modifiers we've applied, in reverse so that the indices of the
                # other elements we're going to pop don't change when we pop an index
                # _todo: The amount of leading do_apply == False will only increase as we go through all the
                #  masks, we could keep track of this and use it to reduce how far we need to iterate through
                #  mask_this_call
                count_to_apply = 0
                for i, do_apply in utils.enumerate_reversed(mask_this_call):
                    if do_apply:
                        full_mask.pop(i)
                        count_to_apply += 1

                # Safety check. Ensure that the number of modifiers has decreased by the expected amount (we don't trust
                # the gret operator to raise exceptions when applying a modifier fails). Note that we specifically don't
                # keep a reference to obj.modifiers in-case applying some modifiers internally re-creates it.
                new_modifiers_length = len(obj.modifiers)
                expected_number_of_modifiers = last_modifiers_length - count_to_apply
                if new_modifiers_length != expected_number_of_modifiers:
                    raise RuntimeError(f"{new_modifiers_length - expected_number_of_modifiers} modifiers failed to"
                                       f" apply on {obj!r}")
                else:
                    last_modifiers_length = new_modifiers_length
            else:
                # We've already checked if it's possible to apply all the modifiers we want to apply, so if we get a
                # mask with no modifiers to apply, we're done because all that's left are the modifiers we're not
                # applying
                return {'FINISHED'}


def run_gret_shape_key_apply_modifiers(obj: Object, modifier_names_to_apply: set[str]):
    gret_check = check_gret_shape_key_apply_modifiers()
    if gret_check == 'keep_modifiers':
        _run_gret_shape_key_apply_modifiers_keep_modifiers(obj, modifier_names_to_apply)
    elif gret_check == 'modifier_mask':
        _run_gret_shape_key_apply_modifiers_modifier_mask(obj, modifier_names_to_apply)
    else:
        raise RuntimeError("Gret addon not found or version incompatible")


def draw_gret_download(layout: UILayout):
    col = layout.column()
    op = col.operator('wm.url_open', text="Get Gret Addon", icon='URL')
    op.url = "https://github.com/greisane/gret"
