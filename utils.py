import bpy
from bpy.types import Context, Scene, ViewLayer, ID, ImagePreview, Key, ShapeKey

from typing import Any, Protocol, Literal, Optional
from contextlib import contextmanager
from .registration import dummy_register_factory


_EXECUTION_CONTEXTS = Literal[
    'INVOKE_DEFAULT',
    'INVOKE_REGION_WIN',
    'INVOKE_REGION_CHANNELS',
    'INVOKE_REGION_PREVIEW',
    'INVOKE_AREA',
    'INVOKE_SCREEN',
    'EXEC_DEFAULT',
    'EXEC_REGION_WIN',
    'EXEC_REGION_CHANNELS',
    'EXEC_REGION_PREVIEW',
    'EXEC_AREA',
    'EXEC_SCREEN',
]

_OP_RETURN = set[Literal['RUNNING_MODAL', 'CANCELLED', 'FINISHED', 'PASS_THROUGH', 'INTERFACE']]


class _OperatorProtocol(Protocol):
    """Protocol matching the signature of __call__ of operators from bpy.ops"""
    def __call__(self, *args, **kwargs) -> _OP_RETURN:
        ...


if bpy.app.version >= (3, 2):
    # Passing in context_override as a positional-only argument is deprecated as of Blender 3.2, replaced with
    # Context.temp_override
    def op_override(operator: _OperatorProtocol, context_override: dict[str, Any], context: Context = None,
                    execution_context: Optional[_EXECUTION_CONTEXTS] = None,
                    undo: Optional[bool] = None, /, **operator_args) -> _OP_RETURN:
        """Call an operator with a context override"""
        args = []
        if execution_context is not None:
            args.append(execution_context)
        if undo is not None:
            args.append(undo)

        if context is None:
            context = bpy.context
        # noinspection PyUnresolvedReferences
        with context.temp_override(**context_override):
            return operator(*args, **operator_args)
else:
    def op_override(operator: _OperatorProtocol, context_override: dict[str, Any], context: Context = None,
                    execution_context: Optional[_EXECUTION_CONTEXTS] = None,
                    undo: Optional[bool] = None, /, **operator_args) -> _OP_RETURN:
        """Call an operator with a context override"""
        args = [context_override]
        if execution_context is not None:
            args.append(execution_context)
        if undo is not None:
            args.append(undo)

        return operator(*args, **operator_args)


@contextmanager
def temp_view_layer(scene: Scene) -> ViewLayer:
    """Some operators have no usable context overrides aside from .view_layer. This context manager creates a temporary
    view layer that can then be passed"""
    temp = scene.view_layers.new(name="temp")
    try:
        yield temp
    finally:
        scene.view_layers.remove(temp)


def get_preview(id: ID) -> ImagePreview:
    if bpy.app.version >= (3, 0):
        # .preview can be None in 3.0+, the new preview_ensure() method can be used.
        # noinspection PyUnresolvedReferences
        preview = id.preview_ensure()
    else:
        preview = id.preview
    return preview


class ReverseRelativeShapeKeyMap:
    def __init__(self, shape_keys: Key):
        reverse_relative_map = {}

        basis_key = shape_keys.reference_key
        for key in shape_keys.key_blocks:
            # Special handling for basis shape key to treat it as if its always relative to itself
            relative_key = basis_key if key == basis_key else key.relative_key
            keys_relative_to_relative_key = reverse_relative_map.get(relative_key)
            if keys_relative_to_relative_key is None:
                keys_relative_to_relative_key = {key}
                reverse_relative_map[relative_key] = keys_relative_to_relative_key
            else:
                keys_relative_to_relative_key.add(key)
        self.reverse_relative_map = reverse_relative_map

    def get_relative_recursive_keys(self, shape_key) -> set[ShapeKey]:
        shape_set = set()

        # Pretty much a depth-first search, but with loop prevention
        def inner_recursive_loop(key, checked_set):
            # Prevent infinite loops by maintaining a set of shapes that we've checked
            if key not in checked_set:
                # Need to add the current key to the set of shapes we've checked before the recursive call
                checked_set.add(key)
                keys_relative_to_shape_key_inner = self.reverse_relative_map.get(key)
                if keys_relative_to_shape_key_inner:
                    for relative_to_inner in keys_relative_to_shape_key_inner:
                        shape_set.add(relative_to_inner)
                        inner_recursive_loop(relative_to_inner, checked_set)

        inner_recursive_loop(shape_key, set())
        return shape_set


register, unregister = dummy_register_factory()