from typing import cast, Optional, Protocol, Union, overload, Callable, Any
from types import ModuleType
import inspect
import importlib
import platform
import sys
import os

import bpy
from bpy.types import Operator, Context, OperatorProperties, UILayout, Panel
from bpy.props import StringProperty, BoolProperty
import addon_utils

from .registration import register_module_classes_factory, OperatorBase
from .utils import operator_exists, ui_multiline_label

"""This module packages up the cats translation functions into a function and callable operator"""

_IS_LINUX = platform.system() == 'Linux'

# Not sure if this works for every OS
_PYTHON_IS_BUNDLED = sys.executable.startswith(os.path.dirname(bpy.app.binary_path))

# Python 3.10 no longer allows lossy implicit conversions from float to int, which Cats 0.19.0 was using.
_CATS_0_19_0_SUPPORTS_CURRENT_PYTHON = sys.version_info < (3, 10)

if platform.system() != 'Linux':
    # Windows (and possibly other OS) have issues with Cats 0.19.0 on Blender 3.0 and newer as it has internal changes
    # that cause Vertex Group pointers to change when applying Vertex Weight Mix modifiers. Cats 0.19.0 tries to use
    # the resulting stale references after applying the modifiers which can lead to buggy behaviour.
    _CATS_0_19_0_SUPPORTS_CURRENT_BLENDER = (bpy.app.version < (3, 0))
else:
    _CATS_0_19_0_SUPPORTS_CURRENT_BLENDER = True

# Used to find the main module of Cats, must match the 'name' in Cats' bl_info in its package's __init__.py
_CATS_ADDON_NAME = "Cats Blender Plugin"


def _get_cats_module() -> ModuleType:
    """Get Cats' top-level module.

    :raises ModuleNotFoundError: if the Cats addon is not loaded or its top-level module cannot be found"""
    for module in addon_utils.modules(refresh=True):
        if hasattr(module, 'bl_info'):
            bl_info = cast(dict, module.bl_info)
            addon_name = bl_info.get('name', None)
            if addon_name == _CATS_ADDON_NAME:
                return module
    raise ModuleNotFoundError(f"Cats module with expected name '{_CATS_ADDON_NAME}' not found")


def _get_cats_translate_module() -> ModuleType:
    """Get Cats' translate module.

    :return: Cats' 'translate' module
    :raises ModuleNotFoundError: if the Cats translate module could not be found"""
    cats_module = _get_cats_module()

    translate_module_name = cats_module.__name__ + ".tools.translate"

    return importlib.import_module(translate_module_name)


_translate_function = Callable[[str, bool, bool], Any]
_update_dictionary_function = Callable[[list[str], bool, Optional[Operator]], None]


def _is_translate_function(f) -> bool:
    return inspect.isfunction(f) and len(inspect.signature(f).parameters) == 3


def _is_update_dictionary_function(f) -> bool:
    # For now, the checks are the same
    return _is_translate_function(f)


def _get_translate_and_update_dictionary_functions() -> tuple[_translate_function, _update_dictionary_function]:
    """Get Cats' internal translate and update_dictionary functions.

    :return: tuple of the translate function and update_dictionary function
    :raises ModuleNotFoundError: if the module containing the functions can't be found
    :raises AttributeError: if one of the functions can't be found"""
    translate_module = _get_cats_translate_module()

    # Get the function that actually performs translations
    translate_function_name = 'translate'
    translate_function = getattr(translate_module, translate_function_name, None)
    if not _is_translate_function(translate_function):
        raise AttributeError(f"Could not find the expected {translate_function_name} function in"
                             f" {translate_module.__name__}")

    # Get the function to update Cats' internal dictionary, this is used to cache translation results
    update_dictionary_function_name = 'update_dictionary'
    update_dictionary_function = getattr(translate_module, update_dictionary_function_name, None)
    if not _is_update_dictionary_function(update_dictionary_function):
        raise AttributeError(f"Could not find the expected {update_dictionary_function_name} function in"
                             f" {translate_module.__name__}")

    return translate_function, update_dictionary_function


class TranslateFunction(Protocol):
    @overload
    def __call__(self, to_translate: str, is_shape_key=True, calling_op: Operator = None) -> Optional[str]:
        ...

    @overload
    def __call__(self, to_translate: list[str], is_shape_key=True, calling_op: Operator = None) -> dict[str, str]:
        ...

    def __call__(self, to_translate: Union[str, list[str]], is_shape_key=True, calling_op: Operator = None) -> Union[Optional[str], dict[str, str]]:
        ...


# The function that is actually used to perform translations. Starts as None until a translation attempt is made for the
# first time and the function is created to wrap functions retrieved from inspection of Cats.
_cats_translate: Optional[TranslateFunction] = None
# Indicates whether an attempt was made to get the Cats translation functions, but it failed, and therefore no more
# attempts should be made
_cats_op_exists_but_translate_not_found = False


def _cats_setup(calling_operator: Optional[Operator]):
    global _cats_translate, _cats_op_exists_but_translate_not_found

    if _cats_translate is not None:
        # Already set up
        return

    # Try and find the Cats module for performing translations and the functions within it that we need to perform
    # translations
    # There are a lot of things that can go wrong, so assume there is an error from the start
    _cats_op_exists_but_translate_not_found = True

    translate, update_dictionary = _get_translate_and_update_dictionary_functions()

    # Define the translate function
    def temp_cats_translate(to_translate: Union[str, list[str]], is_shape_key=True, calling_op: Operator = None):
        # While the Cats functions have options for if shape keys are being translated, all they do is
        # force google translations when bpy.context.scene.use_google_only is True. use_google_only defaults
        # to False and is how we want to do our translations always.
        if isinstance(to_translate, list):
            # update_dictionary is what actually connects to google translate
            # It might be possible to check calling_op.has_reports to determine if an error has occurred during
            # translation
            update_dictionary(to_translate, False, calling_op)
            translated = {}
            for s in to_translate:
                translation, success = translate(s, is_shape_key, False)
                if success:
                    translated[s] = translation
            return translated
        else:
            update_dictionary([to_translate], False, calling_op)
            # Cats sets the second argument, add_space to True when translating shape keys, not sure why
            translation, success = translate(to_translate, is_shape_key, False)
            if success:
                return translation
            else:
                return None

    # Test out the translate function and if no exceptions occur, set it as cats_translate
    try:
        # This is "The 5 minute hypothesis", the chance of it existing in Cats' dictionary already is next
        # to nothing, so this should result in testing that the google translate part works
        temp_cats_translate('世界五分前仮説', True, calling_operator)
    except Exception as e:
        # Something we weren't expecting has gone wrong, we will assume that something will go wrong every
        # time. If the exception is a one-off, e.g. internet connection failed, the user will unfortunately
        # be required to restart Blender to try again.
        print("ERROR: An error has occurred when testing the Cats translation integration. Cats translation"
              " integration will be disabled.")
        raise e
    else:
        # Set the internal function used for translating
        _cats_translate = temp_cats_translate
        # We have successfully found all the functions required and tested them out without issue
        _cats_op_exists_but_translate_not_found = False
        return


# The operators received from bpy.ops.<module> are Python classes that simply store a _module and _func that match
# bpy.ops._module._func. Attempting to call/poll/introspect performs a lookup based on the _module and _func.
# See <install dir>\<version>\scripts\modules\bpy\ops.py in your Blender distribution for details
# noinspection PyUnresolvedReferences
_cats_exists_check_ops = [bpy.ops.cats_translate.all, bpy.ops.cats_translate.objects, bpy.ops.cats_translate.shapekeys]


def cats_exists() -> bool:
    """A quick check for if the Cats addon is loaded, intended for use in poll functions"""
    # Check a few in-case one gets removed in the future
    return any(map(operator_exists, _cats_exists_check_ops))


@overload
def cats_translate(
        to_translate: str,
        is_shape_key: bool = False,
        calling_op: Operator = None
) -> Optional[str]:
    """Translate a single string using Cats"""
    ...


@overload
def cats_translate(
        to_translate: list[str],
        is_shape_key: bool = False,
        calling_op: Operator = None
) -> Optional[dict[str, str]]:
    """Translate a list of strings using Cats"""
    ...


def cats_translate(
        to_translate: Union[str, list[str]],
        is_shape_key: bool = False,
        calling_op: Operator = None
) -> Optional[Union[str, dict[str, str]]]:
    """Translate a string or list of strings using Cats.

    :raises ModuleNotFoundError: if the Cats translate module can't be found
    :raises AttributeError: if Cats' internal translation functions can't be found"""
    # TODO: does cats_exists() need to be checked? e.g. what happens if we create the _cats_translate function, but then
    #  disable/remove/update Cats?
    if _cats_translate is not None and cats_exists():
        return _cats_translate(to_translate, is_shape_key, calling_op)
    else:
        if not _cats_op_exists_but_translate_not_found and cats_exists():
            _cats_setup(None)
            if _cats_translate is not None:
                return _cats_translate(to_translate, is_shape_key, calling_op)
            else:
                return None
        else:
            return None


class CatsTranslate(OperatorBase):
    """Translate a string using Cats and then store it into a string property accessible from the current context"""
    bl_idname = "cats_translate"
    bl_label = "Cats Translate"
    bl_options = {'UNDO', 'INTERNAL'}

    to_translate: StringProperty(
        name="Text To Translate",
        description="Text to translate with Cats",
    )

    is_shape_key: BoolProperty(
        name="Is Shapekey",
        description="Whether the text being translated is a shape key",
        default=False
    )

    data_path: StringProperty(
        name="Context Data Path",
        description="Data path from the context to set to the translation",
    )

    custom_description: StringProperty(name="Custom Description", options={'HIDDEN'})

    @classmethod
    def poll(cls, context: Context) -> bool:
        if _cats_op_exists_but_translate_not_found:
            # Might just need to disable and re-enable Avatar Builder instead of requiring a Blender restart
            return cls.poll_fail("Cats appears to exist, but its translate functions could not be found. This could be"
                                 " a bug, an unsupported Cats version or could be because an error occurred when trying"
                                 " a test translation. Blender will need to be restarted to try again.")
        if not cats_exists():
            return cls.poll_fail("Cats Addon not found (or version not supported)")

        return True

    @classmethod
    def description(cls, context: Context, properties: OperatorProperties) -> str:
        description = properties.custom_description
        if description:
            return description
        else:
            return CatsTranslate.__doc__

    def execute(self, context: Context) -> set[str]:
        translated = cats_translate(self.to_translate, self.is_shape_key, self)
        if translated is None:
            if _cats_translate is None:
                self.report({'ERROR'}, "Cats appears to be loaded, but the translate functions could not be found. Look"
                                       " for previous errors with more information")
                return {'CANCELLED'}
            else:
                self.report({'ERROR'}, f"Could not translate '{self.to_translate}', check for other errors that may"
                                       f" have more information")
                return {'CANCELLED'}
        else:
            set_string_result = bpy.ops.wm.context_set_string(data_path=self.data_path, value=translated)
            if 'PASS_THROUGH' in set_string_result:
                self.report({'ERROR'}, "Failed to set context string")
                return {'CANCELLED'}
            else:
                return set_string_result


class DevelopmentVersionInstructions(Panel):
    bl_idname = "cats_dev_instructions"
    bl_label = "Cats Development Version"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Avatar Builder"
    # It's only used as a popover UI element
    bl_options = {'INSTANCED'}
    # I don't know if there's a way to make automatically expanding popover panels, the panel itself expands if the UI
    # its popped out of is wider than the bl_ui_units_x, but the contents of the panel doesn't expand with it.
    bl_ui_units_x = 12

    def draw(self, context: Context):
        col = self.layout.column()
        col.label(text="Download instructions:")
        sub = col.column(align=True)
        sub.scale_y = 0.7
        sub.label(text="Click \"Download ZIP\" from the green \"Code\"")
        sub.label(text="dropdown of the development branch:")
        op = col.operator('wm.url_open', text="Cats Development branch", icon='URL')
        op.url = "https://github.com/absolute-quantum/cats-blender-plugin/tree/development"
        col.separator()
        col.label(text="Or download ZIP directly:")
        op = col.operator('wm.url_open', text="Direct ZIP download", icon='URL')
        op.url = "https://github.com/absolute-quantum/cats-blender-plugin/archive/refs/heads/development.zip"


def draw_cats_download(context: Context, layout: UILayout):
    col = layout.column()
    op = col.operator('wm.url_open', text="Get Cats Blender Plugin", icon='URL')
    op.url = "https://github.com/absolute-quantum/cats-blender-plugin"

    if not _CATS_0_19_0_SUPPORTS_CURRENT_BLENDER:
        main_message = "Cats 0.19.0 does not support Blender 3.0 and newer"
    elif not _CATS_0_19_0_SUPPORTS_CURRENT_PYTHON:
        # This won't happen often, it should only happen for Linux users on Blender 3.0.
        # Though, it can happen if users are not using the bundled Python that comes with Blender and are instead
        # using an incorrect Python version (Major and Minor version must match the version Blender comes with)
        if _PYTHON_IS_BUNDLED:
            # Python 3.10 was first bundled with Blender 3.1, so the user's Blender version must be at least 3.1.
            # Since bundled Python is being used, tell the user it's their Blender version which is the issue.
            main_message = "Cats 0.19.0 does not support Blender 3.1 and newer"
        else:
            # Since bundled Python isn't being used, tell the user it's their Python version which is the issue.
            main_message = "Cats 0.19.0 does not support Python 3.10 and newer"
    else:
        # Cats 0.19.0 is supported by the current Blender/Python/OS, there's nothing else to do
        return

    sub = col.column(align=True)
    sub.scale_y = 0.7
    ui_multiline_label(sub, context, main_message)
    ui_multiline_label(sub, context, "If there's no newer Cats version, use the development version")
    col.popover(panel=DevelopmentVersionInstructions.bl_idname)


register_module_classes_factory(__name__, globals())
