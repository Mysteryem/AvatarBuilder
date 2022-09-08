from typing import Union
from bpy.types import UIList, Context, UILayout, Panel, SpaceProperties, Operator
from bpy.props import EnumProperty

from ..registration import register_module_classes_factory
from ..types import ScenePropertyGroup, ObjectPropertyGroup, ObjectBuildSettings
from ..integration import check_gret_shape_key_apply_modifiers


class ObjectBuildSettingsUIList(UIList):
    bl_idname = "object_build_settings"

    def draw_item(self, context: Context, layout: UILayout, data, item, icon, active_data, active_property, index=0,
                  flt_flag=0):
        scene_group = ScenePropertyGroup.get_group(context.scene)
        scene_settings = scene_group.build_settings

        scene_active_name = scene_group.get_active().name
        is_scene_active = item.name == scene_active_name

        index_in_scene_settings = scene_settings.find(item.name)
        is_orphaned = index_in_scene_settings == -1

        row = layout.row(align=True)
        #row.label(text="", icon="SETTINGS")
        if is_scene_active:
            row_icon = "SCENE_DATA"
        elif is_orphaned:
            #row_icon = "ORPHAN_DATA"
            #row_icon = "LIBRARY_DATA_BROKEN"
            #row_icon = "UNLINKED"
            row_icon = "GHOST_DISABLED"
            row.alert = True
        else:
            row_icon = "BLANK1"
        # Display the prop of the scene settings if it exists, this simplifies renaming
        row.prop(item if is_orphaned else scene_settings[index_in_scene_settings], 'name_prop', text="", emboss=False, icon=row_icon)
        row.alert = False
        row.prop(item, "include_in_build", text="")
        #row.alert = True
        #row.enabled = not is_scene_active


class ObjectPanel(Panel):
    bl_idname = "object_panel"
    bl_label = "Avatar Builder"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    #bl_category = "AvatarBuilder"
    bl_context = "object"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context: Context):
        # guaranteed to be SpaceProperties by the bl_space_type
        # noinspection PyTypeChecker
        space_data: SpaceProperties = context.space_data
        pin_id = space_data.pin_id
        if pin_id is not None:
            # pin object is guaranteed to be an Object because of the bl_context = "object" which says this Panel is
            # only displayed in the Object Properties tab. The Object Properties tab is not available if Object Data is
            # pinned
            obj = pin_id
        else:
            obj = context.object

        # TODO: Currently, we're only building these types, should we be including any others?
        # TODO: Make the set a global variable and uses it elsewhere too
        if not obj or obj.type not in {'MESH', 'ARMATURE'}:
            return False
        scene = context.scene
        # Build settings must be non-empty
        # TODO: Should add a 'clean' or 'purge' button to Scene panel that purges non-existent build settings from all
        #       objects in the current scene. This is because we otherwise have no way to remove the object settings
        #       if we hide the panel when there's no build settings
        return ScenePropertyGroup.get_group(scene).build_settings

    def draw(self, context: Context):
        # noinspection PyTypeChecker
        space_data: SpaceProperties = context.space_data
        pin_id = space_data.pin_id
        if pin_id:
            # poll function has already checked that there's either no pin or that it's an object
            obj = pin_id
        else:
            obj = context.object
        group = ObjectPropertyGroup.get_group(obj)
        object_settings = group.object_settings

        layout = self.layout
        main_column = layout.column(align=True)
        main_col = main_column.column()
        # Sync setting and anything else that should be before things

        header_col = main_col.column()
        header_col.use_property_decorate = True

        row = header_col.row(align=True)
        row.use_property_decorate = False
        row.prop(group, 'sync_active_with_scene', icon="SCENE_DATA", text="")
        row.prop(group, 'sync_active_with_scene', icon="OBJECT_DATA", text="", invert_checkbox=True)

        is_synced = group.sync_active_with_scene
        if group.sync_active_with_scene:
            # Get active_object_settings by name of active_build_settings
            scene_group = ScenePropertyGroup.get_group(context.scene)
            active_build_settings = scene_group.get_active()

            active_object_settings: Union[ObjectBuildSettings, None]
            if active_build_settings:
                active_object_settings = object_settings.get(active_build_settings.name)
            else:
                active_object_settings = None
                if scene_group.build_settings:
                    # Only happens if the active index is out of bounds for some reason, since we hide the panel
                    # when there are no Build Settings
                    header_col.label(text="Active build settings is out of bounds, this shouldn't normally happen,"
                                          " select one in the list in the 3D View and the active build settings index"
                                          " will update automatically")
                    # TODO: Draw button to 'fix' out of bounds index
            if active_object_settings:
                if active_build_settings:
                    row.separator()
                    row.label(text="", icon="SETTINGS")
                    row.prop(active_build_settings, "name_prop", icon="SCENE_DATA", emboss=False, text="")
                    row.use_property_split = True
                    row.prop(active_object_settings, "include_in_build", text="")
            else:
                row.operator(ObjectBuildSettingsControl.bl_idname, text="Add to Avatar Builder", icon="ADD").command = 'ADD'
        else:
            list_row = row.row(align=False)
            list_row.template_list(ObjectBuildSettingsUIList.bl_idname, "", group, 'object_settings', group,'object_settings_active_index', rows=3)
            vertical_buttons_col = row.column(align=True)
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="ADD").command = 'ADD'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="REMOVE").command = 'REMOVE'
            vertical_buttons_col.separator()
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_UP").command = 'UP'
            vertical_buttons_col.operator(ObjectBuildSettingsControl.bl_idname, text="", icon="TRIA_DOWN").command = 'DOWN'

            object_settings_active_index = group.object_settings_active_index
            num_object_settings = len(object_settings)
            if num_object_settings > 0 and 0 <= object_settings_active_index < num_object_settings:
                active_object_settings = object_settings[object_settings_active_index]
            else:
                active_object_settings = None

        if active_object_settings:
            # Extra col for label when disabled
            if not active_object_settings.include_in_build:
                disabled_label_col = main_col.column()
                disabled_label_col.alignment = 'RIGHT'
                disabled_label_col.use_property_split = True
                disabled_label_col.use_property_decorate = True
                disabled_label_col.label(text="Disabled. Won't be included in build")

            # Display the properties for the active settings
            settings_enabled = active_object_settings.include_in_build
            properties_col = main_column.column(align=True)
            properties_col.use_property_split = True
            properties_col.use_property_decorate = False
            properties_col.enabled = settings_enabled

            ################
            # General Object
            ################
            object_box = properties_col.box()
            object_box_col = object_box.column()
            object_box_col.label(text="Object", icon="OBJECT_DATA")
            object_box_col.prop(active_object_settings, 'target_object_name')

            if obj.type == 'ARMATURE':
                armature_box = properties_col.box()
                armature_box_col = armature_box.column()
                armature_box_col.label(text="Pose", icon="ARMATURE_DATA")

                export_pose = active_object_settings.armature_export_pose

                armature_box_col.prop(active_object_settings, 'armature_export_pose')

                armature_preserve_volume_col = armature_box_col.column()
                armature_preserve_volume_col.enabled = export_pose != 'REST'
                armature_preserve_volume_col.prop(active_object_settings, 'armature_export_pose_preserve_volume')

                armature_pose_custom_col = armature_box_col.column()
                armature_pose_custom_col.enabled = export_pose.startswith("CUSTOM")
                if export_pose == 'CUSTOM_POSE_LIBRARY' and obj.pose_library:
                    pose_library = obj.pose_library

                    if pose_library:
                        armature_pose_custom_col.prop_search(
                            active_object_settings,
                            'armature_export_pose_library_marker',
                            pose_library,
                            'pose_markers', icon="DOT")
                else:
                    # TODO: elif for `export_pose == 'CUSTOM_ASSET_LIBRARY':`
                    armature_pose_custom_col.enabled = False
                    armature_pose_custom_col.prop(
                        active_object_settings,
                        'armature_export_pose_library_marker', icon="DOT")

            elif obj.type == 'MESH':
                ###############
                # Vertex Groups
                ###############
                if obj.vertex_groups:
                    vertex_groups_box = properties_col.box()

                    vertex_groups_box_col = vertex_groups_box.column()
                    vertex_groups_box_col.label(text="Vertex Groups", icon="GROUP_VERTEX")
                    vertex_groups_box_col.prop(active_object_settings, 'remove_non_deform_vertex_groups')
                    # TODO: Remove empty vertex groups? Probably not very important, since it won't result in much
                    #  extra data, assuming they even get exported at all

                ############
                # Shape keys
                ############
                if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1:
                    shape_keys_box = properties_col.box()
                    shape_keys_box_col = shape_keys_box.column()
                    shape_keys_box_col.label(text="Shape keys", icon="SHAPEKEY_DATA")
                    # ------------------------
                    # delete_col
                    delete_col = shape_keys_box_col.column(align=True)
                    delete_col.prop_search(active_object_settings, 'delete_shape_keys_after', obj.data.shape_keys, 'key_blocks')
                    delete_col.prop_search(active_object_settings, 'delete_shape_keys_before', obj.data.shape_keys, 'key_blocks')

                    shape_keys_box_col.prop(active_object_settings, 'shape_keys_op')

                    # Shape key merge
                    merge_col = shape_keys_box_col.column(align=True)
                    merge_col.enabled = active_object_settings.shape_keys_op == 'MERGE'
                    merge_col.prop(active_object_settings, 'merge_shape_keys')
                    merge_setting = active_object_settings.merge_shape_keys

                    if merge_setting == 'PREFIX':
                        text_label = "Merge Prefix"
                    elif merge_setting == 'SUFFIX':
                        text_label = "Merge Suffix"
                    else:  # merge_setting == 'COMMON_BEFORE_LAST' or merge_setting == 'COMMON_AFTER_FIRST':
                        text_label = "Merge Delimiter"

                    merge_col.alert = merge_col.enabled and not active_object_settings.merge_shape_keys_prefix_suffix
                    merge_col.prop(active_object_settings, 'merge_shape_keys_prefix_suffix', text=text_label)
                    merge_col.alert = False
                    merge_col.prop(active_object_settings, 'merge_shape_keys_pattern')
                    merge_col.prop(active_object_settings, 'merge_shape_keys_ignore_prefix')
                    # ------------------------

                ################
                # Mesh Modifiers
                ################
                mesh_modifiers_box = properties_col.box()
                mesh_modifiers_box_col = mesh_modifiers_box.column(align=True)
                mesh_modifiers_box_col.label(text="Modifiers", icon="MODIFIER_DATA")
                if active_object_settings.apply_non_armature_modifiers == 'APPLY_KEEP_SHAPES_GRET':
                    gret_available = check_gret_shape_key_apply_modifiers()
                    mesh_modifiers_box_col.alert = not gret_available
                    mesh_modifiers_box_col.prop(active_object_settings, 'apply_non_armature_modifiers')

                    if not gret_available:
                        if gret_available is None:
                            mesh_modifiers_box_col.label("Gret addon operator not found")
                        else:
                            mesh_modifiers_box_col.label("Unsupported version of Gret")
                    mesh_modifiers_box_col.alert = False
                else:
                    mesh_modifiers_box_col.prop(active_object_settings, 'apply_non_armature_modifiers')

                ################
                # Mesh UV Layers
                ################
                if obj.data.uv_layers:
                    uv_layers_box = properties_col.box()
                    uv_layers_box_col = uv_layers_box.column()
                    uv_layers_box_col.label(text="UV Layers", icon="GROUP_UVS")
                    uv_layers_box_col.prop_search(active_object_settings, 'keep_only_uv_map', obj.data, 'uv_layers', icon="GROUP_UVS")

                ################
                # Mesh Materials
                ################
                if obj.data.materials:
                    materials_box = properties_col.box()
                    materials_box_col = materials_box.column()
                    materials_box_col.label(text="Materials", icon="MATERIAL_DATA")
                    materials_box_col.prop_search(active_object_settings, 'keep_only_material', obj.data, 'materials')

            # all_icons = ['NONE', 'QUESTION', 'ERROR', 'CANCEL', 'TRIA_RIGHT', 'TRIA_DOWN', 'TRIA_LEFT', 'TRIA_UP', 'ARROW_LEFTRIGHT', 'PLUS', 'DISCLOSURE_TRI_RIGHT', 'DISCLOSURE_TRI_DOWN', 'RADIOBUT_OFF', 'RADIOBUT_ON', 'MENU_PANEL', 'BLENDER', 'GRIP', 'DOT', 'COLLAPSEMENU', 'X', 'DUPLICATE', 'TRASH', 'COLLECTION_NEW', 'OPTIONS', 'NODE', 'NODE_SEL', 'WINDOW', 'WORKSPACE', 'RIGHTARROW_THIN', 'BORDERMOVE', 'VIEWZOOM', 'ADD', 'REMOVE', 'PANEL_CLOSE', 'COPY_ID', 'EYEDROPPER', 'CHECKMARK', 'AUTO', 'CHECKBOX_DEHLT', 'CHECKBOX_HLT', 'UNLOCKED', 'LOCKED', 'UNPINNED', 'PINNED', 'SCREEN_BACK', 'RIGHTARROW', 'DOWNARROW_HLT', 'FCURVE_SNAPSHOT', 'OBJECT_HIDDEN', 'TOPBAR', 'STATUSBAR', 'PLUGIN', 'HELP', 'GHOST_ENABLED', 'COLOR', 'UNLINKED', 'LINKED', 'HAND', 'ZOOM_ALL', 'ZOOM_SELECTED', 'ZOOM_PREVIOUS', 'ZOOM_IN', 'ZOOM_OUT', 'DRIVER_DISTANCE', 'DRIVER_ROTATIONAL_DIFFERENCE', 'DRIVER_TRANSFORM', 'FREEZE', 'STYLUS_PRESSURE', 'GHOST_DISABLED', 'FILE_NEW', 'FILE_TICK', 'QUIT', 'URL', 'RECOVER_LAST', 'THREE_DOTS', 'FULLSCREEN_ENTER', 'FULLSCREEN_EXIT', 'BRUSHES_ALL', 'LIGHT', 'MATERIAL', 'TEXTURE', 'ANIM', 'WORLD', 'SCENE', 'OUTPUT', 'SCRIPT', 'PARTICLES', 'PHYSICS', 'SPEAKER', 'TOOL_SETTINGS', 'SHADERFX', 'MODIFIER', 'BLANK1', 'FAKE_USER_OFF', 'FAKE_USER_ON', 'VIEW3D', 'GRAPH', 'OUTLINER', 'PROPERTIES', 'FILEBROWSER', 'IMAGE', 'INFO', 'SEQUENCE', 'TEXT', 'SPREADSHEET', 'SOUND', 'ACTION', 'NLA', 'PREFERENCES', 'TIME', 'NODETREE', 'CONSOLE', 'TRACKER', 'ASSET_MANAGER', 'NODE_COMPOSITING', 'NODE_TEXTURE', 'NODE_MATERIAL', 'UV', 'OBJECT_DATAMODE', 'EDITMODE_HLT', 'UV_DATA', 'VPAINT_HLT', 'TPAINT_HLT', 'WPAINT_HLT', 'SCULPTMODE_HLT', 'POSE_HLT', 'PARTICLEMODE', 'TRACKING', 'TRACKING_BACKWARDS', 'TRACKING_FORWARDS', 'TRACKING_BACKWARDS_SINGLE', 'TRACKING_FORWARDS_SINGLE', 'TRACKING_CLEAR_BACKWARDS', 'TRACKING_CLEAR_FORWARDS', 'TRACKING_REFINE_BACKWARDS', 'TRACKING_REFINE_FORWARDS', 'SCENE_DATA', 'RENDERLAYERS', 'WORLD_DATA', 'OBJECT_DATA', 'MESH_DATA', 'CURVE_DATA', 'META_DATA', 'LATTICE_DATA', 'LIGHT_DATA', 'MATERIAL_DATA', 'TEXTURE_DATA', 'ANIM_DATA', 'CAMERA_DATA', 'PARTICLE_DATA', 'LIBRARY_DATA_DIRECT', 'GROUP', 'ARMATURE_DATA', 'COMMUNITY', 'BONE_DATA', 'CONSTRAINT', 'SHAPEKEY_DATA', 'CONSTRAINT_BONE', 'CAMERA_STEREO', 'PACKAGE', 'UGLYPACKAGE', 'EXPERIMENTAL', 'BRUSH_DATA', 'IMAGE_DATA', 'FILE', 'FCURVE', 'FONT_DATA', 'RENDER_RESULT', 'SURFACE_DATA', 'EMPTY_DATA', 'PRESET', 'RENDER_ANIMATION', 'RENDER_STILL', 'LIBRARY_DATA_BROKEN', 'BOIDS', 'STRANDS', 'GREASEPENCIL', 'LINE_DATA', 'LIBRARY_DATA_OVERRIDE', 'GROUP_BONE', 'GROUP_VERTEX', 'GROUP_VCOL', 'GROUP_UVS', 'FACE_MAPS', 'RNA', 'RNA_ADD', 'MOUSE_LMB', 'MOUSE_MMB', 'MOUSE_RMB', 'MOUSE_MOVE', 'MOUSE_LMB_DRAG', 'MOUSE_MMB_DRAG', 'MOUSE_RMB_DRAG', 'MEMORY', 'PRESET_NEW', 'DECORATE', 'DECORATE_KEYFRAME', 'DECORATE_ANIMATE', 'DECORATE_DRIVER', 'DECORATE_LINKED', 'DECORATE_LIBRARY_OVERRIDE', 'DECORATE_UNLOCKED', 'DECORATE_LOCKED', 'DECORATE_OVERRIDE', 'FUND', 'TRACKER_DATA', 'HEART', 'ORPHAN_DATA', 'USER', 'SYSTEM', 'SETTINGS', 'OUTLINER_OB_EMPTY', 'OUTLINER_OB_MESH', 'OUTLINER_OB_CURVE', 'OUTLINER_OB_LATTICE', 'OUTLINER_OB_META', 'OUTLINER_OB_LIGHT', 'OUTLINER_OB_CAMERA', 'OUTLINER_OB_ARMATURE', 'OUTLINER_OB_FONT', 'OUTLINER_OB_SURFACE', 'OUTLINER_OB_SPEAKER', 'OUTLINER_OB_FORCE_FIELD', 'OUTLINER_OB_GROUP_INSTANCE', 'OUTLINER_OB_GREASEPENCIL', 'OUTLINER_OB_LIGHTPROBE', 'OUTLINER_OB_IMAGE', 'OUTLINER_COLLECTION', 'RESTRICT_COLOR_OFF', 'RESTRICT_COLOR_ON', 'HIDE_ON', 'HIDE_OFF', 'RESTRICT_SELECT_ON', 'RESTRICT_SELECT_OFF', 'RESTRICT_RENDER_ON', 'RESTRICT_RENDER_OFF', 'RESTRICT_INSTANCED_OFF', 'OUTLINER_DATA_EMPTY', 'OUTLINER_DATA_MESH', 'OUTLINER_DATA_CURVE', 'OUTLINER_DATA_LATTICE', 'OUTLINER_DATA_META', 'OUTLINER_DATA_LIGHT', 'OUTLINER_DATA_CAMERA', 'OUTLINER_DATA_ARMATURE', 'OUTLINER_DATA_FONT', 'OUTLINER_DATA_SURFACE', 'OUTLINER_DATA_SPEAKER', 'OUTLINER_DATA_LIGHTPROBE', 'OUTLINER_DATA_GP_LAYER', 'OUTLINER_DATA_GREASEPENCIL', 'GP_SELECT_POINTS', 'GP_SELECT_STROKES', 'GP_MULTIFRAME_EDITING', 'GP_ONLY_SELECTED', 'GP_SELECT_BETWEEN_STROKES', 'MODIFIER_OFF', 'MODIFIER_ON', 'ONIONSKIN_OFF', 'ONIONSKIN_ON', 'RESTRICT_VIEW_ON', 'RESTRICT_VIEW_OFF', 'RESTRICT_INSTANCED_ON', 'MESH_PLANE', 'MESH_CUBE', 'MESH_CIRCLE', 'MESH_UVSPHERE', 'MESH_ICOSPHERE', 'MESH_GRID', 'MESH_MONKEY', 'MESH_CYLINDER', 'MESH_TORUS', 'MESH_CONE', 'MESH_CAPSULE', 'EMPTY_SINGLE_ARROW', 'LIGHT_POINT', 'LIGHT_SUN', 'LIGHT_SPOT', 'LIGHT_HEMI', 'LIGHT_AREA', 'CUBE', 'SPHERE', 'CONE', 'META_PLANE', 'META_CUBE', 'META_BALL', 'META_ELLIPSOID', 'META_CAPSULE', 'SURFACE_NCURVE', 'SURFACE_NCIRCLE', 'SURFACE_NSURFACE', 'SURFACE_NCYLINDER', 'SURFACE_NSPHERE', 'SURFACE_NTORUS', 'EMPTY_AXIS', 'STROKE', 'EMPTY_ARROWS', 'CURVE_BEZCURVE', 'CURVE_BEZCIRCLE', 'CURVE_NCURVE', 'CURVE_NCIRCLE', 'CURVE_PATH', 'LIGHTPROBE_CUBEMAP', 'LIGHTPROBE_PLANAR', 'LIGHTPROBE_GRID', 'COLOR_RED', 'COLOR_GREEN', 'COLOR_BLUE', 'TRIA_RIGHT_BAR', 'TRIA_DOWN_BAR', 'TRIA_LEFT_BAR', 'TRIA_UP_BAR', 'FORCE_FORCE', 'FORCE_WIND', 'FORCE_VORTEX', 'FORCE_MAGNETIC', 'FORCE_HARMONIC', 'FORCE_CHARGE', 'FORCE_LENNARDJONES', 'FORCE_TEXTURE', 'FORCE_CURVE', 'FORCE_BOID', 'FORCE_TURBULENCE', 'FORCE_DRAG', 'FORCE_FLUIDFLOW', 'RIGID_BODY', 'RIGID_BODY_CONSTRAINT', 'IMAGE_PLANE', 'IMAGE_BACKGROUND', 'IMAGE_REFERENCE', 'NODE_INSERT_ON', 'NODE_INSERT_OFF', 'NODE_TOP', 'NODE_SIDE', 'NODE_CORNER', 'ANCHOR_TOP', 'ANCHOR_BOTTOM', 'ANCHOR_LEFT', 'ANCHOR_RIGHT', 'ANCHOR_CENTER', 'SELECT_SET', 'SELECT_EXTEND', 'SELECT_SUBTRACT', 'SELECT_INTERSECT', 'SELECT_DIFFERENCE', 'ALIGN_LEFT', 'ALIGN_CENTER', 'ALIGN_RIGHT', 'ALIGN_JUSTIFY', 'ALIGN_FLUSH', 'ALIGN_TOP', 'ALIGN_MIDDLE', 'ALIGN_BOTTOM', 'BOLD', 'ITALIC', 'UNDERLINE', 'SMALL_CAPS', 'CON_ACTION', 'MOD_LENGTH', 'MOD_DASH', 'MOD_LINEART', 'HOLDOUT_OFF', 'HOLDOUT_ON', 'INDIRECT_ONLY_OFF', 'INDIRECT_ONLY_ON', 'CON_CAMERASOLVER', 'CON_FOLLOWTRACK', 'CON_OBJECTSOLVER', 'CON_LOCLIKE', 'CON_ROTLIKE', 'CON_SIZELIKE', 'CON_TRANSLIKE', 'CON_DISTLIMIT', 'CON_LOCLIMIT', 'CON_ROTLIMIT', 'CON_SIZELIMIT', 'CON_SAMEVOL', 'CON_TRANSFORM', 'CON_TRANSFORM_CACHE', 'CON_CLAMPTO', 'CON_KINEMATIC', 'CON_LOCKTRACK', 'CON_SPLINEIK', 'CON_STRETCHTO', 'CON_TRACKTO', 'CON_ARMATURE', 'CON_CHILDOF', 'CON_FLOOR', 'CON_FOLLOWPATH', 'CON_PIVOT', 'CON_SHRINKWRAP', 'MODIFIER_DATA', 'MOD_WAVE', 'MOD_BUILD', 'MOD_DECIM', 'MOD_MIRROR', 'MOD_SOFT', 'MOD_SUBSURF', 'HOOK', 'MOD_PHYSICS', 'MOD_PARTICLES', 'MOD_BOOLEAN', 'MOD_EDGESPLIT', 'MOD_ARRAY', 'MOD_UVPROJECT', 'MOD_DISPLACE', 'MOD_CURVE', 'MOD_LATTICE', 'MOD_TINT', 'MOD_ARMATURE', 'MOD_SHRINKWRAP', 'MOD_CAST', 'MOD_MESHDEFORM', 'MOD_BEVEL', 'MOD_SMOOTH', 'MOD_SIMPLEDEFORM', 'MOD_MASK', 'MOD_CLOTH', 'MOD_EXPLODE', 'MOD_FLUIDSIM', 'MOD_MULTIRES', 'MOD_FLUID', 'MOD_SOLIDIFY', 'MOD_SCREW', 'MOD_VERTEX_WEIGHT', 'MOD_DYNAMICPAINT', 'MOD_REMESH', 'MOD_OCEAN', 'MOD_WARP', 'MOD_SKIN', 'MOD_TRIANGULATE', 'MOD_WIREFRAME', 'MOD_DATA_TRANSFER', 'MOD_NORMALEDIT', 'MOD_PARTICLE_INSTANCE', 'MOD_HUE_SATURATION', 'MOD_NOISE', 'MOD_OFFSET', 'MOD_SIMPLIFY', 'MOD_THICKNESS', 'MOD_INSTANCE', 'MOD_TIME', 'MOD_OPACITY', 'REC', 'PLAY', 'FF', 'REW', 'PAUSE', 'PREV_KEYFRAME', 'NEXT_KEYFRAME', 'PLAY_SOUND', 'PLAY_REVERSE', 'PREVIEW_RANGE', 'ACTION_TWEAK', 'PMARKER_ACT', 'PMARKER_SEL', 'PMARKER', 'MARKER_HLT', 'MARKER', 'KEYFRAME_HLT', 'KEYFRAME', 'KEYINGSET', 'KEY_DEHLT', 'KEY_HLT', 'MUTE_IPO_OFF', 'MUTE_IPO_ON', 'DRIVER', 'SOLO_OFF', 'SOLO_ON', 'FRAME_PREV', 'FRAME_NEXT', 'NLA_PUSHDOWN', 'IPO_CONSTANT', 'IPO_LINEAR', 'IPO_BEZIER', 'IPO_SINE', 'IPO_QUAD', 'IPO_CUBIC', 'IPO_QUART', 'IPO_QUINT', 'IPO_EXPO', 'IPO_CIRC', 'IPO_BOUNCE', 'IPO_ELASTIC', 'IPO_BACK', 'IPO_EASE_IN', 'IPO_EASE_OUT', 'IPO_EASE_IN_OUT', 'NORMALIZE_FCURVES', 'VERTEXSEL', 'EDGESEL', 'FACESEL', 'CURSOR', 'PIVOT_BOUNDBOX', 'PIVOT_CURSOR', 'PIVOT_INDIVIDUAL', 'PIVOT_MEDIAN', 'PIVOT_ACTIVE', 'CENTER_ONLY', 'ROOTCURVE', 'SMOOTHCURVE', 'SPHERECURVE', 'INVERSESQUARECURVE', 'SHARPCURVE', 'LINCURVE', 'NOCURVE', 'RNDCURVE', 'PROP_OFF', 'PROP_ON', 'PROP_CON', 'PROP_PROJECTED', 'PARTICLE_POINT', 'PARTICLE_TIP', 'PARTICLE_PATH', 'SNAP_FACE_CENTER', 'SNAP_PERPENDICULAR', 'SNAP_MIDPOINT', 'SNAP_OFF', 'SNAP_ON', 'SNAP_NORMAL', 'SNAP_GRID', 'SNAP_VERTEX', 'SNAP_EDGE', 'SNAP_FACE', 'SNAP_VOLUME', 'SNAP_INCREMENT', 'STICKY_UVS_LOC', 'STICKY_UVS_DISABLE', 'STICKY_UVS_VERT', 'CLIPUV_DEHLT', 'CLIPUV_HLT', 'SNAP_PEEL_OBJECT', 'GRID', 'OBJECT_ORIGIN', 'ORIENTATION_GLOBAL', 'ORIENTATION_GIMBAL', 'ORIENTATION_LOCAL', 'ORIENTATION_NORMAL', 'ORIENTATION_VIEW', 'COPYDOWN', 'PASTEDOWN', 'PASTEFLIPUP', 'PASTEFLIPDOWN', 'VIS_SEL_11', 'VIS_SEL_10', 'VIS_SEL_01', 'VIS_SEL_00', 'AUTOMERGE_OFF', 'AUTOMERGE_ON', 'UV_VERTEXSEL', 'UV_EDGESEL', 'UV_FACESEL', 'UV_ISLANDSEL', 'UV_SYNC_SELECT', 'GP_CAPS_FLAT', 'GP_CAPS_ROUND', 'FIXED_SIZE', 'TRANSFORM_ORIGINS', 'GIZMO', 'ORIENTATION_CURSOR', 'NORMALS_VERTEX', 'NORMALS_FACE', 'NORMALS_VERTEX_FACE', 'SHADING_BBOX', 'SHADING_WIRE', 'SHADING_SOLID', 'SHADING_RENDERED', 'SHADING_TEXTURE', 'OVERLAY', 'XRAY', 'LOCKVIEW_OFF', 'LOCKVIEW_ON', 'AXIS_SIDE', 'AXIS_FRONT', 'AXIS_TOP', 'LAYER_USED', 'LAYER_ACTIVE', 'OUTLINER_OB_CURVES', 'OUTLINER_DATA_CURVES', 'CURVES_DATA', 'OUTLINER_OB_POINTCLOUD', 'OUTLINER_DATA_POINTCLOUD', 'POINTCLOUD_DATA', 'OUTLINER_OB_VOLUME', 'OUTLINER_DATA_VOLUME', 'VOLUME_DATA', 'CURRENT_FILE', 'HOME', 'DOCUMENTS', 'TEMP', 'SORTALPHA', 'SORTBYEXT', 'SORTTIME', 'SORTSIZE', 'SHORTDISPLAY', 'LONGDISPLAY', 'IMGDISPLAY', 'BOOKMARKS', 'FONTPREVIEW', 'FILTER', 'NEWFOLDER', 'FOLDER_REDIRECT', 'FILE_PARENT', 'FILE_REFRESH', 'FILE_FOLDER', 'FILE_BLANK', 'FILE_BLEND', 'FILE_IMAGE', 'FILE_MOVIE', 'FILE_SCRIPT', 'FILE_SOUND', 'FILE_FONT', 'FILE_TEXT', 'SORT_DESC', 'SORT_ASC', 'LINK_BLEND', 'APPEND_BLEND', 'IMPORT', 'EXPORT', 'LOOP_BACK', 'LOOP_FORWARDS', 'BACK', 'FORWARD', 'FILE_ARCHIVE', 'FILE_CACHE', 'FILE_VOLUME', 'FILE_3D', 'FILE_HIDDEN', 'FILE_BACKUP', 'DISK_DRIVE', 'MATPLANE', 'MATSPHERE', 'MATCUBE', 'MONKEY', 'CURVES', 'ALIASED', 'ANTIALIASED', 'MAT_SPHERE_SKY', 'MATSHADERBALL', 'MATCLOTH', 'MATFLUID', 'WORDWRAP_OFF', 'WORDWRAP_ON', 'SYNTAX_OFF', 'SYNTAX_ON', 'LINENUMBERS_OFF', 'LINENUMBERS_ON', 'SCRIPTPLUGINS', 'DISC', 'DESKTOP', 'EXTERNAL_DRIVE', 'NETWORK_DRIVE', 'SEQ_SEQUENCER', 'SEQ_PREVIEW', 'SEQ_LUMA_WAVEFORM', 'SEQ_CHROMA_SCOPE', 'SEQ_HISTOGRAM', 'SEQ_SPLITVIEW', 'SEQ_STRIP_META', 'SEQ_STRIP_DUPLICATE', 'IMAGE_RGB', 'IMAGE_RGB_ALPHA', 'IMAGE_ALPHA', 'IMAGE_ZDEPTH', 'HANDLE_AUTOCLAMPED', 'HANDLE_AUTO', 'HANDLE_ALIGNED', 'HANDLE_VECTOR', 'HANDLE_FREE', 'VIEW_PERSPECTIVE', 'VIEW_ORTHO', 'VIEW_CAMERA', 'VIEW_PAN', 'VIEW_ZOOM', 'BRUSH_BLOB', 'BRUSH_BLUR', 'BRUSH_CLAY', 'BRUSH_CLAY_STRIPS', 'BRUSH_CLONE', 'BRUSH_CREASE', 'BRUSH_FILL', 'BRUSH_FLATTEN', 'BRUSH_GRAB', 'BRUSH_INFLATE', 'BRUSH_LAYER', 'BRUSH_MASK', 'BRUSH_MIX', 'BRUSH_NUDGE', 'BRUSH_PINCH', 'BRUSH_SCRAPE', 'BRUSH_SCULPT_DRAW', 'BRUSH_SMEAR', 'BRUSH_SMOOTH', 'BRUSH_SNAKE_HOOK', 'BRUSH_SOFTEN', 'BRUSH_TEXDRAW', 'BRUSH_TEXFILL', 'BRUSH_TEXMASK', 'BRUSH_THUMB', 'BRUSH_ROTATE', 'GPBRUSH_SMOOTH', 'GPBRUSH_THICKNESS', 'GPBRUSH_STRENGTH', 'GPBRUSH_GRAB', 'GPBRUSH_PUSH', 'GPBRUSH_TWIST', 'GPBRUSH_PINCH', 'GPBRUSH_RANDOMIZE', 'GPBRUSH_CLONE', 'GPBRUSH_WEIGHT', 'GPBRUSH_PENCIL', 'GPBRUSH_PEN', 'GPBRUSH_INK', 'GPBRUSH_INKNOISE', 'GPBRUSH_BLOCK', 'GPBRUSH_MARKER', 'GPBRUSH_FILL', 'GPBRUSH_AIRBRUSH', 'GPBRUSH_CHISEL', 'GPBRUSH_ERASE_SOFT', 'GPBRUSH_ERASE_HARD', 'GPBRUSH_ERASE_STROKE', 'KEYTYPE_KEYFRAME_VEC', 'KEYTYPE_BREAKDOWN_VEC', 'KEYTYPE_EXTREME_VEC', 'KEYTYPE_JITTER_VEC', 'KEYTYPE_MOVING_HOLD_VEC', 'HANDLETYPE_FREE_VEC', 'HANDLETYPE_ALIGNED_VEC', 'HANDLETYPE_VECTOR_VEC', 'HANDLETYPE_AUTO_VEC', 'HANDLETYPE_AUTO_CLAMP_VEC', 'COLORSET_01_VEC', 'COLORSET_02_VEC', 'COLORSET_03_VEC', 'COLORSET_04_VEC', 'COLORSET_05_VEC', 'COLORSET_06_VEC', 'COLORSET_07_VEC', 'COLORSET_08_VEC', 'COLORSET_09_VEC', 'COLORSET_10_VEC', 'COLORSET_11_VEC', 'COLORSET_12_VEC', 'COLORSET_13_VEC', 'COLORSET_14_VEC', 'COLORSET_15_VEC', 'COLORSET_16_VEC', 'COLORSET_17_VEC', 'COLORSET_18_VEC', 'COLORSET_19_VEC', 'COLORSET_20_VEC', 'COLLECTION_COLOR_01', 'COLLECTION_COLOR_02', 'COLLECTION_COLOR_03', 'COLLECTION_COLOR_04', 'COLLECTION_COLOR_05', 'COLLECTION_COLOR_06', 'COLLECTION_COLOR_07', 'COLLECTION_COLOR_08', 'SEQUENCE_COLOR_01', 'SEQUENCE_COLOR_02', 'SEQUENCE_COLOR_03', 'SEQUENCE_COLOR_04', 'SEQUENCE_COLOR_05', 'SEQUENCE_COLOR_06', 'SEQUENCE_COLOR_07', 'SEQUENCE_COLOR_08', 'SEQUENCE_COLOR_09', 'LIBRARY_DATA_INDIRECT', 'LIBRARY_DATA_OVERRIDE_NONEDITABLE', 'EVENT_A', 'EVENT_B', 'EVENT_C', 'EVENT_D', 'EVENT_E', 'EVENT_F', 'EVENT_G', 'EVENT_H', 'EVENT_I', 'EVENT_J', 'EVENT_K', 'EVENT_L', 'EVENT_M', 'EVENT_N', 'EVENT_O', 'EVENT_P', 'EVENT_Q', 'EVENT_R', 'EVENT_S', 'EVENT_T', 'EVENT_U', 'EVENT_V', 'EVENT_W', 'EVENT_X', 'EVENT_Y', 'EVENT_Z', 'EVENT_SHIFT', 'EVENT_CTRL', 'EVENT_ALT', 'EVENT_OS', 'EVENT_F1', 'EVENT_F2', 'EVENT_F3', 'EVENT_F4', 'EVENT_F5', 'EVENT_F6', 'EVENT_F7', 'EVENT_F8', 'EVENT_F9', 'EVENT_F10', 'EVENT_F11', 'EVENT_F12', 'EVENT_ESC', 'EVENT_TAB', 'EVENT_PAGEUP', 'EVENT_PAGEDOWN', 'EVENT_RETURN', 'EVENT_SPACEKEY']
            # for icon in all_icons:
            #     try:
            #         properties_col.label(text=icon, icon=icon)
            #     except:
            #         pass

            if is_synced:
                #final_col = layout.column()
                #properties_col.enabled = True
                final_col = main_column.column(align=True)
                final_col.operator(ObjectBuildSettingsControl.bl_idname, text="Remove from Avatar Builder", icon="TRASH").command = 'REMOVE'


# TODO: Split into different operators so that we can use different poll functions, e.g. disable move ops and remove op
#  when there aren't any settings in the array
class ObjectBuildSettingsControl(Operator):
    bl_idname = 'object_build_settings_control'
    bl_label = "Object Build Settings Control"

    command_items = (
        ('ADD', "Add", "Add a new set of build settings, defaults to the active build settings if they don't exist on this Object"),
        ('REMOVE', "Remove", "Remove the currently active build settings"),
        # Disabled if doesn't exist on the object
        ('UP', "Move Up", "Move active build settings up"),
        ('DOWN', "Move Down", "Move active build settings down"),
        ('SYNC', "Sync", "Set the currently displayed settings of to the currently active build settings"),
        ('TOP', "Move to top", "Move active build settings to top"),
        ('BOTTOM', "Move to bottom", "Move active build settings to bottom"),
    )

    command: EnumProperty(
        items=command_items,
        default='ADD',
    )

    @classmethod
    def description(cls, context, properties):
        command = properties.command
        for identifier, _, description in cls.command_items:
            if identifier == command:
                return description
        return f"Error: enum value '{command}' not found"

    def execute(self, context: Context):
        obj = context.object
        object_group = ObjectPropertyGroup.get_group(obj)
        # With sync enabled, we often ignore the active index, instead preferring to use the settings that match the
        # active build settings
        sync_enabled = object_group.sync_active_with_scene

        object_build_settings = object_group.object_settings
        active_index = object_group.object_settings_active_index

        command = self.command

        if sync_enabled:
            if command == 'ADD':
                active_build_settings = ScenePropertyGroup.get_group(context.scene).get_active()
                if active_build_settings and active_build_settings.name not in object_build_settings:
                    added = object_build_settings.add()
                    added.name_prop = active_build_settings.name
                    object_group.object_settings_active_index = len(object_build_settings) - 1
                    return {'FINISHED'}
                else:
                    return {'CANCELLED'}
            elif command == 'REMOVE':
                active_build_settings = ScenePropertyGroup.get_group(context.scene).get_active()
                if active_build_settings:
                    index = object_build_settings.find(active_build_settings.name)
                    if index != -1:
                        object_build_settings.remove(index)
                        was_last_index = active_index >= len(object_build_settings)
                        if was_last_index:
                            object_group.object_settings_active_index = max(0, active_index - 1)
                        return {'FINISHED'}
                    else:
                        return {'CANCELLED'}
            elif command in {'SYNC', 'UP', 'DOWN', 'TOP', 'BOTTOM'}:
                # Sync is enabled, this doesn't make sense
                return {'CANCELLED'}
        else:
            if command == 'ADD':
                added = object_build_settings.add()

                # Rename if not unique and ensure that the internal name is also set
                added_name = added.name_prop
                orig_name = added_name
                unique_number = 0
                # Its internal name of the newly added build_settings will currently be "" since it hasn't been set
                # We could do `while added_name in build_settings:` but I'm guessing Blender has to iterate through each
                # element until `added_name` is found since duplicate names are allowed. Checking against a set should be
                # faster if there are lots
                existing_names = {bs.name for bs in object_build_settings}
                while added_name in existing_names:
                    unique_number += 1
                    added_name = orig_name + " " + str(unique_number)
                if added_name != orig_name:
                    # Assigning the prop will also update the internal name
                    added.name_prop = added_name
                else:
                    added.name = added_name
                # Set active to the new element
                object_group.object_settings_active_index = len(object_build_settings) - 1
            elif command == 'REMOVE':
                object_build_settings.remove(active_index)
                object_group.object_settings_active_index = active_index - 1
            elif command == 'SYNC':
                scene_active = ScenePropertyGroup.get_group(context.scene).get_active()
                if scene_active:
                    index = object_build_settings.find(scene_active.name)
                    if index != -1:
                        object_group.object_settings_active_index = index
                        return {'FINISHED'}
                return {'CANCELLED'}
            elif command == 'UP':
                # Previous index, with wrap around to the bottom
                new_index = (active_index - 1) % len(object_build_settings)
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'DOWN':
                # Next index, with wrap around to the top
                new_index = (active_index + 1) % len(object_build_settings)
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'TOP':
                new_index = 0
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            elif command == 'BOTTOM':
                new_index = len(object_build_settings) - 1
                object_build_settings.move(active_index, new_index)
                object_group.object_settings_active_index = new_index
            return {'FINISHED'}


register, unregister = register_module_classes_factory(__name__, globals())
