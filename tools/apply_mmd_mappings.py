from bpy.types import Operator, Context, Object, Mesh, ShapeKey, Event
from bpy.props import PointerProperty

from typing import cast

from .. import utils
from ..util_generic_bpy_typing import PropCollection
from ..extensions import ScenePropertyGroup, MmdShapeKeySettings, MmdShapeMapping
from ..registration import OperatorBase, register_module_classes_factory

"""Operator to apply current mmd mappings to selected meshes"""


def _mmd_remap_rename(operator: Operator, mesh_obj: Object, key_blocks: PropCollection[ShapeKey],
                      shape_name_to_mapping: dict[str, MmdShapeMapping], remap_to_japanese: bool,
                      avoid_names: set[str]):
    # Go through existing shape keys
    #   If the shape has a mapping, get what it wants to be renamed to
    #   Else set the desired name to its current name
    #   If the desired name already exists (or is to otherwise be avoided), get a unique name using the
    #     desired name as a base
    #   Store the shape key and its unique, desired name into a list
    # If we were to rename the shape keys during this iteration, we could end up renaming a shape key we are
    # yet to iterate, which would cause its mapping in shape_name_to_mapping to no longer be found.
    desired_names: list[tuple[ShapeKey, str]] = []
    for shape in key_blocks:
        shape_name = shape.name
        if shape_name in shape_name_to_mapping:
            mapping = shape_name_to_mapping[shape_name]
            if remap_to_japanese:
                map_to = mapping.mmd_name
            else:
                cats_translation = mapping.cats_translation_name
                # Fallback to mmd_name if there's no cats translation
                map_to = cats_translation if cats_translation else mapping.mmd_name
            desired_name = map_to if map_to else shape_name
            # Get a unique version of the desired name
            unique_desired_name = utils.get_unique_name(desired_name, avoid_names)
            if unique_desired_name != desired_name:
                operator.report({'WARNING'}, f"The desired mmd mapping name of '{desired_name}' for the Shape Key"
                                             f" '{mapping.model_shape}' on {mesh_obj!r} was already in use. It has been"
                                             f" renamed to '{unique_desired_name}' instead")
        else:
            # No mapping for this shape key
            unique_desired_name = utils.get_unique_name(shape_name, avoid_names)
        # Each shape key must have a unique name, so add this shape key's unique desired name to the set
        # so that other shape keys can't pick the same name
        avoid_names.add(unique_desired_name)
        desired_names.append((shape, unique_desired_name))

    # Now go through the shape keys and rename them to their desired names
    for shape, unique_desired_name in desired_names:
        if shape.name != unique_desired_name:
            # Unlike most types in Blender, if you rename a ShapeKey to one that already exists, the shape
            # key that was renamed will be given a different, unique name, instead of the existing ShapeKey
            # being renamed.
            # For this reason, if we want to rename a ShapeKey to the same name as a ShapeKey that already
            # exists, the ShapeKey that already exists has to be renamed to something else first.
            # TODO: Make this faster by keeping track of all current shape key names in a set and passing in
            #  that set instead of key_blocks directly
            temporary_new_name = utils.get_unique_name(unique_desired_name, key_blocks)
            if temporary_new_name != unique_desired_name:
                # Since we guarantee beforehand that all the names will end up unique, this name typically
                # won't end up used unless it just so happens to match the desired name.
                key_blocks[unique_desired_name].name = temporary_new_name
            shape.name = unique_desired_name


def _mmd_remap_add(operator: Operator, mesh_obj: Object, key_blocks: PropCollection[ShapeKey],
                   shape_name_to_mapping: dict[str, MmdShapeMapping], remap_to_japanese: bool,
                   avoid_names: set[str]):
    # Go through existing shape keys
    #  If the shape has a mapping, add a duplicate
    #  Set the duplicated shape key to the name it wanted if possible
    #  If avoid double activation is enabled and the other version exists in the shape keys, rename it
    #    Not that we need to make sure that if we rename a shape key we are yet to iterate to, that mmd
    #    mapping will still occur based on the original name. Maybe we should do the avoid-double-
    #    activation step afterwards instead?

    current_names = avoid_names.copy()
    current_names.update(s.name for s in key_blocks)
    # Rename shape keys that are in the set of names to avoid, we'll get the MmdShapeMapping before renaming
    # since they are mapped by name and add all the information we need to a list.
    # While we could combine this loop and the next loop together, the order in which shape keys get named
    # can become confusing. For simplicity, we'll rename existing shape keys first and then add the copies
    # with their mapped names
    shapes_and_mappings: list[tuple[ShapeKey, MmdShapeMapping]] = []
    for shape in key_blocks:
        shape_name = shape.name
        shapes_and_mappings.append((shape, shape_name_to_mapping.get(shape_name)))
        # Rename the shape key if it's using a name that must be avoided
        if shape_name in avoid_names:
            avoided_name = utils.get_unique_name(shape_name, current_names)
            shape.name = avoided_name
            current_names.add(avoided_name)

    # Create a copy of each shape key and name the copy according to the desired_name
    #
    # An alternative would be to create new shape keys and then copy the co of the original shape key to
    # the copy shape key with foreach_get/set, but this takes about twice the time for meshes with few
    # vertices and gets comparatively worse as the number of vertices increases.

    # Enable 'shape key pinning', showing the active shape key at 1.0 value regardless of its current
    # value and ignoring all other shape keys. We do this so we can easily create a new shape key from
    # mix, where the mix is only the shape key we want to copy.
    orig_pinning = mesh_obj.show_only_shape_key
    mesh_obj.show_only_shape_key = True
    # We're going to add shapes, so make sure we have a copy of the list that isn't going to update as
    # we add more
    for idx, (shape, mapping) in enumerate(shapes_and_mappings):
        if mapping is None:
            continue

        # Get the desired name for the copy
        if remap_to_japanese:
            desired_name = mapping.mmd_name
        else:
            cats_translation = mapping.cats_translation_name
            # Fall back to mmd_name if cats_translation doesn't exist
            desired_name = cats_translation if cats_translation else mapping.mmd_name

        # Get a unique version of the desired name for the copy
        unique_desired_name = utils.get_unique_name(desired_name, avoid_names)
        if unique_desired_name != desired_name:
            operator.report({'WARNING'}, f"The desired mmd mapping name of '{desired_name}' for the Shape Key"
                                         f" '{mapping.model_shape}' on {mesh_obj!r} was already in use. It has been"
                                         f" named '{unique_desired_name}' instead")

        # Shape key must not be muted otherwise it won't be pinned, we will restore the mute state after
        if shape.mute:
            mute = True
            shape.mute = False
        else:
            mute = False
        # Set the active shape key index to 'shape' so that it is pinned
        mesh_obj.active_shape_key_index = idx
        # Create a new shape key from mix (only the pinned shape key) and with the desired name,
        # copying the active shape key.
        mesh_obj.shape_key_add(name=unique_desired_name, from_mix=True)
        current_names.add(unique_desired_name)
        # Restore the mute if the shape key was muted
        if mute:
            shape.mute = True
    # Restore pinning state
    mesh_obj.show_only_shape_key = orig_pinning


def mmd_remap(operator: Operator, scene_property_group: ScenePropertyGroup, mmd_settings: MmdShapeKeySettings,
              mesh_objects: list[Object]):
    if mmd_settings.do_remap:
        mmd_mappings = scene_property_group.mmd_shape_mapping_group.collection

        # Must have a model_shape name, since that's what we will match against
        valid_mmd_mappings = (m for m in mmd_mappings if m.model_shape)

        remap_to_japanese = mmd_settings.remap_to == 'JAPANESE'
        if remap_to_japanese:
            # Must have an mmd_name, since that's what we're mapping to
            valid_mmd_mappings = [m for m in valid_mmd_mappings if m.mmd_name]
        else:
            # Should have a cats translation name, since that's what we're mapping to, but some names are not able to be
            # translated, such as '▲' or 'ω', in which case, the mmd_name is used as a fallback
            valid_mmd_mappings = [m for m in valid_mmd_mappings if m.cats_translation_name or m.mmd_name]

        if not valid_mmd_mappings:
            return

        shape_name_to_mapping = {}
        for mapping in valid_mmd_mappings:
            model_shape = mapping.model_shape
            if model_shape in shape_name_to_mapping:
                existing = shape_name_to_mapping[model_shape]
                operator.report({'WARNING'}, f"Already mapping {model_shape} to"
                                             f" {(existing.mmd_name, existing.cats_translation_name)},"
                                             f" ignoring the additional mapping to"
                                             f" {(mapping.mmd_name, mapping.cats_translation_name)}")
            else:
                shape_name_to_mapping[model_shape] = mapping

        limit_to_body = mmd_settings.limit_to_body
        if limit_to_body:
            # Only perform mappings on the mesh called 'Body'
            mesh_objects = (m for m in mesh_objects if m.name == 'Body')

        for mesh_obj in mesh_objects:
            shape_keys = cast(Mesh, mesh_obj.data).shape_keys
            if not shape_keys:
                continue

            key_blocks = shape_keys.key_blocks
            # Get the original shape key names to shapes in advance to simplify things
            orig_shape_names_to_shapes = {shape.name: shape for shape in key_blocks}

            if mmd_settings.avoid_double_activation:
                # When using an mmd_shape, the equivalent Cats translation must be avoided and vice versa, otherwise
                # some mmd dances may end up activating both the mmd_shape and its Cats translation equivalent
                # Currently, we're avoiding double activation on a per-mesh basis (only checking the shape keys being
                # mapped that exist in this mesh), but it might be worth changing this to check all mappings, even those
                # not used by this mesh
                if remap_to_japanese:
                    # TODO: Do we want to include Cats translations that aren't used by this mesh? Then the option
                    #  would be less about avoiding double activation and more about avoiding potentially any
                    #  unwanted activation
                    # Only the names for shapes that are actually used by this Mesh
                    avoid_names = {
                        shape_name_to_mapping[shape_name].cats_translation_name
                        for shape_name in orig_shape_names_to_shapes
                        if shape_name in shape_name_to_mapping
                    }
                else:
                    # Very unlikely that an mmd_name will end up as a conflict unless an avatar with Japanese
                    # shape keys is set to map to the Cats translations
                    avoid_names = set()
                    for shape_name in orig_shape_names_to_shapes:
                        if shape_name in shape_name_to_mapping:
                            mapping = shape_name_to_mapping[shape_name]
                            # If the mapping doesn't have a cats_translation_name, the mmd_name is used instead, so
                            # there won't be a name to avoid in that case
                            if mapping.cats_translation_name:
                                # There is a cats_translation_name for this mapping, so the mmd_name should be
                                # avoided
                                avoid_names.add(mapping.mmd_name)
            else:
                avoid_names = set()

            if mmd_settings.mode == 'RENAME':
                _mmd_remap_rename(operator, mesh_obj, key_blocks, shape_name_to_mapping, remap_to_japanese, avoid_names)
            elif mmd_settings.mode == 'ADD':
                _mmd_remap_add(operator, mesh_obj, key_blocks, shape_name_to_mapping, remap_to_japanese, avoid_names)


class ApplyMMDMappings(OperatorBase):
    """Apply the current MMD Mappings to the selected meshes
    "do_remap", "limit_to_body" and "name" of the mmd_shape_key_settings argument are ignored"""
    bl_label = "Apply MMD Mappings"
    bl_idname = 'apply_mmd_mappings'
    bl_options = {'REGISTER', 'UNDO'}

    mmd_shape_key_settings: PointerProperty(type=MmdShapeKeySettings)

    @classmethod
    def poll(cls, context: Context) -> bool:
        if context.mode != 'OBJECT':
            return cls.poll_fail("Must be in Object Mode")
        if not context.selected_editable_objects:
            return cls.poll_fail("No editable objects selected")
        if not ScenePropertyGroup.get_group(context.scene).mmd_shape_mapping_group.collection:
            return cls.poll_fail("No mappings defined")
        return True

    def draw(self, context: Context):
        settings = self.mmd_shape_key_settings
        layout = self.layout
        layout.prop(settings, 'remap_to')
        layout.prop(settings, 'mode')
        layout.prop(settings, 'avoid_double_activation')

    def execute(self, context: Context) -> set[str]:
        found_data: set[str] = set()
        mesh_objects: list[Object] = []
        for obj in context.selected_editable_objects:
            if obj.type != 'MESH':
                continue

            me = cast(Mesh, obj.data)
            mesh_name = me.name
            if mesh_name in found_data:
                # A mesh with the same data has already been found
                continue
            found_data.add(mesh_name)

            if (shape_keys := me.shape_keys) and len(shape_keys.key_blocks) > 1:
                mesh_objects.append(obj)

        num_objects = len(mesh_objects)
        message = f"Mapped shape keys of {num_objects} objects"
        if num_objects > 0:
            mmd_remap(self, ScenePropertyGroup.get_group(context.scene), self.mmd_shape_key_settings, mesh_objects)
            if num_objects == 1:
                message = f"Mapped shape keys of '{mesh_objects[0].name}'"
        self.report({'INFO'}, message)
        return {'FINISHED'}

    def invoke(self, context: Context, event: Event) -> set[str]:
        settings = self.mmd_shape_key_settings

        # It seems that 'mmd_shape_key_settings' is always set, even if the operator is called without setting it, so we
        # can't detect when it has been set as opposed to being the default (or last used values being used)
        # Perhaps this is an issue with using a PropertyGroup property
        #
        # If the operator hasn't been called before in this session
        previously_called_operators = context.window_manager.operators
        if self.bl_idname not in previously_called_operators:
            active_scene_settings = ScenePropertyGroup.get_group(context.scene).active
            # ...and active scene settings exist and have mmd_remap enabled:
            if active_scene_settings and (scene_mmd_settings := active_scene_settings.mmd_settings).do_remap:
                # Copy settings from active scene settings
                utils.id_prop_group_copy(scene_mmd_settings, settings)

        # These properties are not displayed in the UI and must always be set to specific values for the Operator to
        # work.
        # Set do_remap to always be True
        settings.do_remap = True
        # Set limit_to_body to always be False
        settings.limit_to_body = False
        # Draw UI with 'OK' button
        return context.window_manager.invoke_props_dialog(self)


register_module_classes_factory(__name__, globals())
