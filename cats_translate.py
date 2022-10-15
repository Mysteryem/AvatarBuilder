from typing import cast, Optional, Protocol, Union, overload
import inspect

import bpy
from bpy.types import Operator, Context
from bpy.props import StringProperty, BoolProperty

from .registration import register_module_classes_factory

"""This module packages up the cats translation functions into a function and callable operator"""

# Must match the 'name' in Cats' bl_info
CATS_ADDON_NAME = "Cats Blender Plugin"


class TranslateFunction(Protocol):
    @overload
    def __call__(self, to_translate: str, is_shape_key=True, calling_op: Operator = None) -> Optional[str]:
        ...

    @overload
    def __call__(self, to_translate: list[str], is_shape_key=True, calling_op: Operator = None) -> dict[str, str]:
        ...

    def __call__(self, to_translate: Union[str, list[str]], is_shape_key=True, calling_op: Operator = None) -> Union[Optional[str], dict[str, str]]:
        ...


_cats_translate: Optional[TranslateFunction] = None
# Indicates whether an attempt was made to get the Cats translation functions, but it failed, and therefore no more
# attempts should be made
_cats_op_exists_but_translate_not_found = False


def cats_exists() -> bool:
    """A quick check for if the Cats addon is loaded"""
    # TODO: Check other operator modules in-case this specific one gets removed
    return hasattr(bpy.ops, 'cats_common')


@overload
def cats_translate(to_translate: str, is_shape_key: bool = False, calling_op: Operator = None
                   ) -> Optional[str]:
    ...


@overload
def cats_translate(to_translate: list[str], is_shape_key: bool = False, calling_op: Operator = None
                   ) -> Optional[dict[str, str]]:
    ...


def cats_translate(to_translate: Union[str, list[str]], is_shape_key: bool = False, calling_op: Operator = None
                   ) -> Optional[Union[str, dict[str, str]]]:
    """Translate a string using Cats"""
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


def _cats_setup(calling_operator: Optional[Operator]):
    global _cats_translate, _cats_op_exists_but_translate_not_found
    if _cats_translate is not None:
        # Already set up
        return
    # TODO: See if we can find a way to get the name of the cats package without addon_utils
    import addon_utils
    import importlib
    # {x.bl_info['name']: x for x in addon_utils.modules(refresh=False)]}
    cats_module = None
    for module in addon_utils.modules(refresh=False):
        if hasattr(module, 'bl_info'):
            bl_info = cast(dict, module.bl_info)
            addon_name = bl_info.get('name', None)
            if addon_name == CATS_ADDON_NAME:
                cats_module = module
                break
    if cats_module is not None:
        try:
            translate_module = importlib.import_module(cats_module.__name__ + ".tools.translate")

            if (
                    # Check the translate function is as expected
                    hasattr(translate_module, 'translate')
                    and inspect.isfunction(translate_module.translate)
                    and len(inspect.signature(translate_module.translate).parameters) == 3

                    # Check the update_dictionary function is as expected
                    and hasattr(translate_module, 'update_dictionary')
                    and inspect.isfunction(translate_module.update_dictionary)
                    and len(inspect.signature(translate_module.update_dictionary).parameters) == 3
            ):
                # Define the translate function
                def temp_cats_translate(to_translate: Union[str, list[str]], is_shape_key=True, calling_op: Operator = None):
                    # While the Cats functions have options for if shape keys are being translated, all they do is
                    # force google translations when bpy.context.scene.use_google_only is True. use_google_only defaults
                    # to False and is how we want to do our translations always.
                    if isinstance(to_translate, list):
                        translate_module.update_dictionary(to_translate, False, calling_op)
                        translated = {}
                        for s in to_translate:
                            translation, success = translate_module.translate(s, is_shape_key, False)
                            if success:
                                translated[s] = translation
                        return translated
                    else:
                        translate_module.update_dictionary([to_translate], False, calling_op)
                        # TODO: Cats sets the second argument, add_space to True when translating shape keys, not sure
                        #  why
                        translation, success = translate_module.translate(to_translate, is_shape_key, False)
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
                    _cats_op_exists_but_translate_not_found = True
                    raise e
                else:
                    _cats_translate = temp_cats_translate
                    # Return without setting _cats_op_exists_but_translate_not_found to True
                    return

        except ModuleNotFoundError:
            # TODO: Print something
            pass

    _cats_op_exists_but_translate_not_found = True


class CatsTranslate(Operator):
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

    @classmethod
    def poll(cls, context: Context) -> bool:
        return not _cats_op_exists_but_translate_not_found and cats_exists()

    def execute(self, context: Context) -> set[str]:
        translated = cats_translate(self.to_translate, self.is_shape_key, self)
        if translated is None:
            if _cats_translate is None:
                self.report({'ERROR'}, "Cats appears to be loaded, but the translate functions could not be found")
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


register, unregister = register_module_classes_factory(__name__, globals())
