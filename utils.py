import bpy
from bpy.types import Context
from typing import Any, Protocol, Literal, Optional
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

register, unregister = dummy_register_factory()
