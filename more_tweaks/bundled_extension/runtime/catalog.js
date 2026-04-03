import {DeformEffect, DOCK_FUNNEL_CONFIG, MAGIC_LAMP_CONFIG} from './deform-effect.js';
import {ShaderPulseEffect} from './shader-effect.js';
import {TransformEffect} from './transform-effect.js';


export const transformEffect = new TransformEffect('transform');
const dockFunnelEffect = new DeformEffect('dock-funnel', DOCK_FUNNEL_CONFIG);
const magicLampEffect = new DeformEffect('magic-lamp', MAGIC_LAMP_CONFIG);
const shaderPulseEffect = new ShaderPulseEffect();

export const BINDING_GROUPS = [
    {
        id: 'windows',
        title: 'Windows',
        summary: 'Open, close, minimize, and restore motion for regular windows.',
    },
    {
        id: 'window_states',
        title: 'Window States',
        summary: 'Focus and maximize transitions for regular windows.',
    },
    {
        id: 'interactive',
        title: 'Interactive Motion',
        summary: 'Lightweight move and resize reactions inspired by classic compiz responsiveness.',
    },
    {
        id: 'dialogs',
        title: 'Dialogs',
        summary: 'Separate motion language for dialog and modal dialog windows.',
    },
    {
        id: 'notifications',
        title: 'Notifications',
        summary: 'Notification banners with softer, app-owned motion.',
    },
];

const OPEN_PRESETS = [
    'Glide In', 'Bloom In', 'Drift Up', 'Fade In', 'Slide Left In', 'Slide Right In',
    'Slide Down In', 'Compressed Slide Up', 'Squeezed Slide Left', 'Zoom In',
    'Rotate In Left', 'Rotate In Down', 'Flip In Horizontal', 'Fold In Vertical',
    'Fall and Bounce', 'Soft Pop', 'Lantern Rise', 'Glass Ripple In',
];
const CLOSE_PRESETS = [
    'Glide Out', 'Shutter Out', 'Drift Down', 'Fade Out', 'Slide Left Out', 'Slide Right Out',
    'Slide Up Out', 'Compressed Slide Down', 'Squeezed Slide Right', 'Zoom Out',
    'Rotate Out Left', 'Rotate Out Up', 'Flip Out Horizontal', 'Fold Out Vertical',
    'Wiggle Out', 'Soft Collapse', 'Glass Ripple Out',
];
const MINIMIZE_PRESETS = ['Dock Funnel', 'Magic Lamp', 'Drift Down', 'Fade Out', 'Scale Down Soft', 'Vacuum Pull'];
const RESTORE_PRESETS = ['Dock Return', 'Magic Lamp Return', 'Bloom In', 'Glide In', 'Soft Pop', 'Lantern Rise'];
const FOCUS_PRESETS = ['Pulse Focus', 'Halo Focus', 'Settle Focus', 'Wiggle Focus', 'Soft Focus Flash'];
const DEFOCUS_PRESETS = ['Fade Dim', 'Slip Back', 'Shrink Fade', 'Quiet Defocus'];
const MAXIMIZE_PRESETS = ['Expand Settle', 'Bloom In', 'Pulse Focus', 'Zoom In', 'Snap Wobble'];
const UNMAXIMIZE_PRESETS = ['Contract Settle', 'Glide In', 'Settle Focus', 'Soft Pop', 'Release Wobble'];
const MOVE_START_PRESETS = ['Grip Pulse', 'Lift Away', 'Halo Focus', 'Jelly Grab'];
const MOVE_STOP_PRESETS = ['Wobble Settle', 'Settle Focus', 'Soft Pop', 'Wobbly Drop'];
const RESIZE_START_PRESETS = ['Edge Tension', 'Grip Pulse', 'Halo Focus', 'Rubber Stretch'];
const RESIZE_STOP_PRESETS = ['Elastic Settle', 'Wobble Settle', 'Soft Pop', 'Spring Snap'];
const NOTIFICATION_OPEN_PRESETS = ['Drift Up', 'Pulse Focus', 'Fade In', 'Banner Sweep', 'Fold In Vertical'];
const NOTIFICATION_CLOSE_PRESETS = ['Fade Out', 'Drift Down', 'Shutter Out', 'Banner Fold', 'Soft Collapse'];

function binding(definition) {
    return {
        tier: 'core',
        defaultDelay: 0,
        defaultIntensity: 1.0,
        ...definition,
    };
}

export const BINDINGS = [
    binding({id: 'window-open', groupId: 'windows', target: 'window', action: 'open', defaultPreset: 'Glide In', defaultDuration: 240, presetNames: OPEN_PRESETS}),
    binding({id: 'window-close', groupId: 'windows', target: 'window', action: 'close', defaultPreset: 'Glide Out', defaultDuration: 220, presetNames: CLOSE_PRESETS}),
    binding({id: 'window-minimize', groupId: 'windows', target: 'window', action: 'minimize', defaultPreset: 'Dock Funnel', defaultDuration: 280, presetNames: MINIMIZE_PRESETS}),
    binding({id: 'window-unminimize', groupId: 'windows', target: 'window', action: 'unminimize', defaultPreset: 'Dock Return', defaultDuration: 320, presetNames: RESTORE_PRESETS}),
    binding({id: 'window-focus', groupId: 'window_states', target: 'window', action: 'focus', defaultPreset: 'Halo Focus', defaultDuration: 170, defaultIntensity: 0.85, tier: 'advanced', presetNames: FOCUS_PRESETS}),
    binding({id: 'window-defocus', groupId: 'window_states', target: 'window', action: 'defocus', defaultPreset: 'Quiet Defocus', defaultDuration: 140, defaultIntensity: 0.75, tier: 'advanced', presetNames: DEFOCUS_PRESETS}),
    binding({id: 'window-maximize', groupId: 'window_states', target: 'window', action: 'maximize', defaultPreset: 'Expand Settle', defaultDuration: 220, defaultIntensity: 0.9, tier: 'advanced', presetNames: MAXIMIZE_PRESETS}),
    binding({id: 'window-unmaximize', groupId: 'window_states', target: 'window', action: 'unmaximize', defaultPreset: 'Contract Settle', defaultDuration: 220, defaultIntensity: 0.9, tier: 'advanced', presetNames: UNMAXIMIZE_PRESETS}),
    binding({id: 'window-move-start', groupId: 'interactive', target: 'window', action: 'move-start', defaultPreset: 'Grip Pulse', defaultDuration: 120, defaultIntensity: 0.75, tier: 'advanced', presetNames: MOVE_START_PRESETS}),
    binding({id: 'window-move-stop', groupId: 'interactive', target: 'window', action: 'move-stop', defaultPreset: 'Wobble Settle', defaultDuration: 190, defaultIntensity: 0.8, tier: 'advanced', presetNames: MOVE_STOP_PRESETS}),
    binding({id: 'window-resize-start', groupId: 'interactive', target: 'window', action: 'resize-start', defaultPreset: 'Edge Tension', defaultDuration: 120, defaultIntensity: 0.75, tier: 'advanced', presetNames: RESIZE_START_PRESETS}),
    binding({id: 'window-resize-stop', groupId: 'interactive', target: 'window', action: 'resize-stop', defaultPreset: 'Elastic Settle', defaultDuration: 190, defaultIntensity: 0.8, tier: 'advanced', presetNames: RESIZE_STOP_PRESETS}),
    binding({id: 'dialog-open', groupId: 'dialogs', target: 'dialog', action: 'open', defaultPreset: 'Bloom In', defaultDuration: 220, presetNames: OPEN_PRESETS}),
    binding({id: 'dialog-close', groupId: 'dialogs', target: 'dialog', action: 'close', defaultPreset: 'Shutter Out', defaultDuration: 210, presetNames: CLOSE_PRESETS}),
    binding({id: 'dialog-focus', groupId: 'dialogs', target: 'dialog', action: 'focus', defaultPreset: 'Pulse Focus', defaultDuration: 160, defaultIntensity: 0.85, tier: 'advanced', presetNames: FOCUS_PRESETS}),
    binding({id: 'dialog-defocus', groupId: 'dialogs', target: 'dialog', action: 'defocus', defaultPreset: 'Fade Dim', defaultDuration: 130, defaultIntensity: 0.75, tier: 'advanced', presetNames: DEFOCUS_PRESETS}),
    binding({id: 'modaldialog-open', groupId: 'dialogs', target: 'modaldialog', action: 'open', defaultPreset: 'Drift Up', defaultDuration: 240, presetNames: OPEN_PRESETS}),
    binding({id: 'modaldialog-close', groupId: 'dialogs', target: 'modaldialog', action: 'close', defaultPreset: 'Fade Out', defaultDuration: 200, presetNames: CLOSE_PRESETS}),
    binding({id: 'modaldialog-focus', groupId: 'dialogs', target: 'modaldialog', action: 'focus', defaultPreset: 'Settle Focus', defaultDuration: 150, defaultIntensity: 0.8, tier: 'advanced', presetNames: FOCUS_PRESETS}),
    binding({id: 'modaldialog-defocus', groupId: 'dialogs', target: 'modaldialog', action: 'defocus', defaultPreset: 'Quiet Defocus', defaultDuration: 130, defaultIntensity: 0.75, tier: 'advanced', presetNames: DEFOCUS_PRESETS}),
    binding({id: 'notification-open', groupId: 'notifications', target: 'notification', action: 'open', defaultPreset: 'Drift Up', defaultDuration: 220, presetNames: NOTIFICATION_OPEN_PRESETS}),
    binding({id: 'notification-close', groupId: 'notifications', target: 'notification', action: 'close', defaultPreset: 'Fade Out', defaultDuration: 180, presetNames: NOTIFICATION_CLOSE_PRESETS}),
];

export const PRESETS = {
    'Glide In': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, scaleX: 0.96, scaleY: 0.92, translationY: 24, rotationZ: -1.5}, phases: [{opacity: 255, scaleX: 1.0, scaleY: 1.0, translationY: 0, rotationZ: 0, mode: 'EASE_OUT_CUBIC'}]},
    'Glide Out': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, scaleX: 1.04, scaleY: 0.94, translationY: 24, rotationZ: 1.5, mode: 'EASE_IN_CUBIC'}]},
    'Bloom In': {family: 'Pop', effect: transformEffect, setup: {opacity: 0, scaleX: 0.88, scaleY: 0.88, translationY: 18}, phases: [{opacity: 255, scaleX: 1.03, scaleY: 1.03, translationY: 0, mode: 'EASE_OUT_CUBIC', durationScale: 0.82}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.18}]},
    'Shutter Out': {family: 'Fold', effect: transformEffect, setup: {pivotY: 0.5}, phases: [{opacity: 0, scaleX: 0.98, scaleY: 0.08, translationY: 6, mode: 'EASE_IN_CUBIC'}]},
    'Drift Up': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, translationY: 38, scaleX: 0.98, scaleY: 0.98}, phases: [{opacity: 255, translationY: 0, scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Drift Down': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, translationY: 38, scaleX: 0.98, scaleY: 0.98, mode: 'EASE_IN_CUBIC'}]},
    'Fade In': {family: 'Fade', effect: transformEffect, setup: {opacity: 0}, phases: [{opacity: 255, mode: 'EASE_OUT_CUBIC'}]},
    'Fade Out': {family: 'Fade', effect: transformEffect, setup: {}, phases: [{opacity: 0, mode: 'EASE_IN_CUBIC'}]},
    'Slide Left In': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, translationX: 44}, phases: [{opacity: 255, translationX: 0, mode: 'EASE_OUT_CUBIC'}]},
    'Slide Right In': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, translationX: -44}, phases: [{opacity: 255, translationX: 0, mode: 'EASE_OUT_CUBIC'}]},
    'Slide Down In': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, translationY: -42}, phases: [{opacity: 255, translationY: 0, mode: 'EASE_OUT_CUBIC'}]},
    'Slide Left Out': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, translationX: -44, mode: 'EASE_IN_CUBIC'}]},
    'Slide Right Out': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, translationX: 44, mode: 'EASE_IN_CUBIC'}]},
    'Slide Up Out': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, translationY: -42, mode: 'EASE_IN_CUBIC'}]},
    'Compressed Slide Up': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, scaleX: 1.0, scaleY: 0.82, translationY: 52}, phases: [{opacity: 255, scaleY: 1.04, translationY: 0, mode: 'EASE_OUT_CUBIC', durationScale: 0.76}, {scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.24}]},
    'Compressed Slide Down': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, scaleY: 0.82, translationY: 50, mode: 'EASE_IN_CUBIC'}]},
    'Squeezed Slide Left': {family: 'Slide', effect: transformEffect, setup: {opacity: 0, scaleX: 0.78, scaleY: 1.0, translationX: 62}, phases: [{opacity: 255, scaleX: 1.0, translationX: 0, mode: 'EASE_OUT_CUBIC'}]},
    'Squeezed Slide Right': {family: 'Slide', effect: transformEffect, setup: {}, phases: [{opacity: 0, scaleX: 0.78, translationX: 62, mode: 'EASE_IN_CUBIC'}]},
    'Zoom In': {family: 'Zoom', effect: transformEffect, setup: {opacity: 0, scaleX: 0.86, scaleY: 0.86}, phases: [{opacity: 255, scaleX: 1.02, scaleY: 1.02, mode: 'EASE_OUT_CUBIC', durationScale: 0.7}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.3}]},
    'Zoom Out': {family: 'Zoom', effect: transformEffect, setup: {}, phases: [{opacity: 0, scaleX: 0.82, scaleY: 0.82, mode: 'EASE_IN_CUBIC'}]},
    'Rotate In Left': {family: 'Rotate', effect: transformEffect, setup: {opacity: 0, rotationZ: -18, translationX: 24, scaleX: 0.94, scaleY: 0.94}, phases: [{opacity: 255, rotationZ: 0, translationX: 0, scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Rotate In Down': {family: 'Rotate', effect: transformEffect, setup: {opacity: 0, rotationZ: -16, translationY: -18, scaleX: 0.94, scaleY: 0.94}, phases: [{opacity: 255, rotationZ: 0, translationY: 0, scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Rotate Out Left': {family: 'Rotate', effect: transformEffect, setup: {}, phases: [{opacity: 0, rotationZ: -16, translationX: -20, scaleX: 0.94, scaleY: 0.94, mode: 'EASE_IN_CUBIC'}]},
    'Rotate Out Up': {family: 'Rotate', effect: transformEffect, setup: {}, phases: [{opacity: 0, rotationZ: 16, translationY: -20, scaleX: 0.94, scaleY: 0.94, mode: 'EASE_IN_CUBIC'}]},
    'Flip In Horizontal': {family: 'Flip', effect: transformEffect, setup: {opacity: 0, rotationY: 80, scaleX: 0.96, scaleY: 0.96}, phases: [{opacity: 255, rotationY: 0, scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Flip Out Horizontal': {family: 'Flip', effect: transformEffect, setup: {}, phases: [{opacity: 0, rotationY: -80, scaleX: 0.96, scaleY: 0.96, mode: 'EASE_IN_CUBIC'}]},
    'Fold In Vertical': {family: 'Fold', effect: transformEffect, setup: {opacity: 0, pivotY: 0.0, scaleY: 0.18}, phases: [{opacity: 255, scaleY: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Fold Out Vertical': {family: 'Fold', effect: transformEffect, setup: {pivotY: 0.0}, phases: [{opacity: 0, scaleY: 0.18, mode: 'EASE_IN_CUBIC'}]},
    'Fall and Bounce': {family: 'Bounce', effect: transformEffect, setup: {opacity: 0, translationY: -84}, phases: [{opacity: 255, translationY: 10, mode: 'EASE_OUT_CUBIC', durationScale: 0.6}, {translationY: -6, mode: 'EASE_OUT_QUAD', durationScale: 0.18}, {translationY: 0, mode: 'EASE_OUT_BOUNCE', durationScale: 0.22}]},
    'Soft Pop': {family: 'Pop', effect: transformEffect, setup: {opacity: 0, scaleX: 0.92, scaleY: 0.92}, phases: [{opacity: 255, scaleX: 1.02, scaleY: 1.02, mode: 'EASE_OUT_CUBIC', durationScale: 0.68}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.32}]},
    'Lantern Rise': {family: 'Signature', effect: transformEffect, setup: {opacity: 0, translationY: 34, scaleX: 0.9, scaleY: 0.84, rotationZ: -2.5}, phases: [{opacity: 255, translationY: -6, scaleX: 1.03, scaleY: 1.02, rotationZ: 0.8, mode: 'EASE_OUT_CUBIC', durationScale: 0.72}, {translationY: 0, scaleX: 1.0, scaleY: 1.0, rotationZ: 0, mode: 'EASE_OUT_QUAD', durationScale: 0.28}]},
    'Scale Down Soft': {family: 'Scale', effect: transformEffect, setup: {}, phases: [{opacity: 0, scaleX: 0.62, scaleY: 0.62, mode: 'EASE_IN_CUBIC'}]},
    'Vacuum Pull': {family: 'Deform', effect: transformEffect, setup: {pivotX: 0.5, pivotY: 1.0}, phases: [{opacity: 0, scaleX: 0.18, scaleY: 0.04, translationY: 76, mode: 'EASE_IN_CUBIC'}]},
    'Pulse Focus': {family: 'Focus', effect: transformEffect, setup: {opacity: 210, scaleX: 0.94, scaleY: 0.94}, phases: [{opacity: 255, scaleX: 1.04, scaleY: 1.04, mode: 'EASE_OUT_CUBIC', durationScale: 0.7}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.3}]},
    'Halo Focus': {family: 'Focus', effect: transformEffect, setup: {opacity: 220, scaleX: 0.97, scaleY: 0.97}, phases: [{opacity: 255, scaleX: 1.02, scaleY: 1.02, mode: 'EASE_OUT_CUBIC', durationScale: 0.6}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.4}]},
    'Settle Focus': {family: 'Focus', effect: transformEffect, setup: {scaleX: 1.02, scaleY: 1.02}, phases: [{scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Wiggle Focus': {family: 'Focus', effect: transformEffect, setup: {rotationZ: -3}, phases: [{rotationZ: 3, mode: 'EASE_OUT_CUBIC', durationScale: 0.25}, {rotationZ: -2, mode: 'EASE_IN_CUBIC', durationScale: 0.25}, {rotationZ: 1.2, mode: 'EASE_IN_CUBIC', durationScale: 0.25}, {rotationZ: 0, mode: 'EASE_OUT_CUBIC', durationScale: 0.25}]},
    'Soft Focus Flash': {family: 'Focus', effect: transformEffect, setup: {opacity: 225}, phases: [{opacity: 255, mode: 'EASE_OUT_CUBIC', durationScale: 0.5}, {opacity: 245, mode: 'EASE_OUT_QUAD', durationScale: 0.5}]},
    'Fade Dim': {family: 'Defocus', effect: transformEffect, setup: {}, phases: [{opacity: 228, mode: 'EASE_OUT_CUBIC'}]},
    'Slip Back': {family: 'Defocus', effect: transformEffect, setup: {}, phases: [{opacity: 232, scaleX: 0.985, scaleY: 0.985, translationY: 6, mode: 'EASE_OUT_CUBIC'}]},
    'Shrink Fade': {family: 'Defocus', effect: transformEffect, setup: {}, phases: [{opacity: 220, scaleX: 0.97, scaleY: 0.97, mode: 'EASE_OUT_CUBIC'}]},
    'Quiet Defocus': {family: 'Defocus', effect: transformEffect, setup: {}, phases: [{opacity: 235, mode: 'EASE_OUT_CUBIC'}]},
    'Expand Settle': {family: 'State', effect: transformEffect, setup: {scaleX: 0.97, scaleY: 0.97}, phases: [{scaleX: 1.02, scaleY: 1.02, mode: 'EASE_OUT_CUBIC', durationScale: 0.68}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.32}]},
    'Contract Settle': {family: 'State', effect: transformEffect, setup: {scaleX: 1.03, scaleY: 1.03}, phases: [{scaleX: 0.985, scaleY: 0.985, mode: 'EASE_OUT_CUBIC', durationScale: 0.65}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.35}]},
    'Grip Pulse': {family: 'Interactive', effect: transformEffect, setup: {scaleX: 0.98, scaleY: 0.98}, phases: [{scaleX: 1.01, scaleY: 1.01, mode: 'EASE_OUT_CUBIC', durationScale: 0.45}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.55}]},
    'Lift Away': {family: 'Interactive', effect: transformEffect, setup: {translationY: 6, scaleX: 0.99, scaleY: 0.99}, phases: [{translationY: -6, scaleX: 1.01, scaleY: 1.01, mode: 'EASE_OUT_CUBIC', durationScale: 0.58}, {translationY: 0, scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.42}]},
    'Wobble Settle': {family: 'Interactive', effect: transformEffect, setup: {rotationZ: -3.2}, phases: [{rotationZ: 2.4, mode: 'EASE_OUT_CUBIC', durationScale: 0.25}, {rotationZ: -1.8, mode: 'EASE_IN_CUBIC', durationScale: 0.25}, {rotationZ: 1.0, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {rotationZ: 0, mode: 'EASE_OUT_QUAD', durationScale: 0.3}]},
    'Edge Tension': {family: 'Interactive', effect: transformEffect, setup: {scaleX: 1.01, scaleY: 0.99}, phases: [{scaleX: 0.995, scaleY: 1.005, mode: 'EASE_OUT_CUBIC', durationScale: 0.5}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.5}]},
    'Elastic Settle': {family: 'Interactive', effect: transformEffect, setup: {scaleX: 1.03, scaleY: 0.97}, phases: [{scaleX: 0.985, scaleY: 1.015, mode: 'EASE_OUT_CUBIC', durationScale: 0.34}, {scaleX: 1.01, scaleY: 0.99, mode: 'EASE_IN_CUBIC', durationScale: 0.26}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.4}]},
    'Jelly Grab': {family: 'Interactive', effect: transformEffect, setup: {scaleX: 0.96, scaleY: 1.04, rotationZ: -1.5}, phases: [{scaleX: 1.03, scaleY: 0.97, rotationZ: 1.0, mode: 'EASE_OUT_CUBIC', durationScale: 0.4}, {scaleX: 0.99, scaleY: 1.01, rotationZ: -0.4, mode: 'EASE_IN_CUBIC', durationScale: 0.3}, {scaleX: 1.0, scaleY: 1.0, rotationZ: 0, mode: 'EASE_OUT_QUAD', durationScale: 0.3}]},
    'Wobbly Drop': {family: 'Interactive', effect: transformEffect, setup: {rotationZ: -4.5, scaleX: 1.02, scaleY: 0.98}, phases: [{rotationZ: 3.5, scaleX: 0.98, scaleY: 1.02, mode: 'EASE_OUT_CUBIC', durationScale: 0.2}, {rotationZ: -2.5, scaleX: 1.01, scaleY: 0.99, mode: 'EASE_IN_CUBIC', durationScale: 0.18}, {rotationZ: 1.8, scaleX: 0.995, scaleY: 1.005, mode: 'EASE_IN_CUBIC', durationScale: 0.16}, {rotationZ: -0.8, mode: 'EASE_IN_CUBIC', durationScale: 0.14}, {rotationZ: 0, scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.32}]},
    'Rubber Stretch': {family: 'Interactive', effect: transformEffect, setup: {scaleX: 1.04, scaleY: 0.96}, phases: [{scaleX: 0.97, scaleY: 1.03, mode: 'EASE_OUT_CUBIC', durationScale: 0.35}, {scaleX: 1.015, scaleY: 0.985, mode: 'EASE_IN_CUBIC', durationScale: 0.3}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.35}]},
    'Spring Snap': {family: 'Interactive', effect: transformEffect, setup: {scaleX: 1.05, scaleY: 0.95, rotationZ: 1.2}, phases: [{scaleX: 0.97, scaleY: 1.03, rotationZ: -0.8, mode: 'EASE_OUT_CUBIC', durationScale: 0.25}, {scaleX: 1.02, scaleY: 0.98, rotationZ: 0.5, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {scaleX: 0.99, scaleY: 1.01, rotationZ: -0.2, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {scaleX: 1.0, scaleY: 1.0, rotationZ: 0, mode: 'EASE_OUT_QUAD', durationScale: 0.35}]},
    'Snap Wobble': {family: 'State', effect: transformEffect, setup: {scaleX: 0.95, scaleY: 0.95}, phases: [{scaleX: 1.04, scaleY: 1.04, mode: 'EASE_OUT_CUBIC', durationScale: 0.3}, {scaleX: 0.98, scaleY: 0.98, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {scaleX: 1.015, scaleY: 1.015, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.3}]},
    'Release Wobble': {family: 'State', effect: transformEffect, setup: {scaleX: 1.04, scaleY: 1.04}, phases: [{scaleX: 0.97, scaleY: 0.97, mode: 'EASE_OUT_CUBIC', durationScale: 0.3}, {scaleX: 1.02, scaleY: 1.02, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {scaleX: 0.99, scaleY: 0.99, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {scaleX: 1.0, scaleY: 1.0, mode: 'EASE_OUT_QUAD', durationScale: 0.3}]},
    'Banner Sweep': {family: 'Banner', effect: transformEffect, setup: {opacity: 0, translationX: 26, scaleX: 0.96}, phases: [{opacity: 255, translationX: 0, scaleX: 1.0, mode: 'EASE_OUT_CUBIC'}]},
    'Banner Fold': {family: 'Banner', effect: transformEffect, setup: {pivotY: 0.0}, phases: [{opacity: 0, scaleY: 0.16, mode: 'EASE_IN_CUBIC'}]},
    'Wiggle Out': {family: 'Playful', effect: transformEffect, setup: {}, phases: [{rotationZ: 4, mode: 'EASE_OUT_CUBIC', durationScale: 0.25}, {rotationZ: -5, mode: 'EASE_IN_CUBIC', durationScale: 0.25}, {rotationZ: 2, opacity: 180, mode: 'EASE_IN_CUBIC', durationScale: 0.2}, {rotationZ: 0, opacity: 0, scaleX: 0.92, scaleY: 0.92, mode: 'EASE_IN_CUBIC', durationScale: 0.3}]},
    'Soft Collapse': {family: 'Signature', effect: transformEffect, setup: {}, phases: [{opacity: 180, scaleX: 1.02, scaleY: 0.95, mode: 'EASE_IN_CUBIC', durationScale: 0.45}, {opacity: 0, scaleX: 0.84, scaleY: 0.74, translationY: 20, mode: 'EASE_IN_CUBIC', durationScale: 0.55}]},
    'Dock Funnel': {family: 'Deform', effect: dockFunnelEffect, opening: false},
    'Dock Return': {family: 'Deform', effect: dockFunnelEffect, opening: true},
    'Magic Lamp': {family: 'Deform', effect: magicLampEffect, opening: false},
    'Magic Lamp Return': {family: 'Deform', effect: magicLampEffect, opening: true},
    'Glass Ripple In': {family: 'Shader', effect: shaderPulseEffect, opening: true},
    'Glass Ripple Out': {family: 'Shader', effect: shaderPulseEffect, opening: false},
};
