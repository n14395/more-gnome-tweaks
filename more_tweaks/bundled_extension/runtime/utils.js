import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {PACKAGE_VERSION} from 'resource:///org/gnome/shell/misc/config.js';


let _shellMajorVersion = null;

export function getShellMajorVersion() {
    if (_shellMajorVersion !== null)
        return _shellMajorVersion;
    try {
        const major = parseInt(PACKAGE_VERSION.split('.')[0], 10);
        _shellMajorVersion = isNaN(major) ? 0 : major;
    } catch (_e) {
        _shellMajorVersion = 0;
    }
    return _shellMajorVersion;
}


export function resetActor(actor) {
    if (!actor)
        return;

    actor.remove_all_transitions();
    actor.opacity = 255;
    actor.scale_x = 1.0;
    actor.scale_y = 1.0;
    actor.translation_x = 0;
    actor.translation_y = 0;
    actor.translation_z = 0;
    actor.rotation_angle_x = 0;
    actor.rotation_angle_y = 0;
    actor.rotation_angle_z = 0;
    actor.set_pivot_point(0.5, 0.5);
}

export function animationMode(name, fallback = Clutter.AnimationMode.EASE_OUT_CUBIC) {
    return Clutter.AnimationMode[name] ?? fallback;
}

export function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
}

export function notificationMonitor(currentMonitorIndex) {
    const monitorIndex = currentMonitorIndex ?? global.display.get_current_monitor();
    return Main.layoutManager.monitors[monitorIndex] ?? Main.layoutManager.primaryMonitor;
}

export function positionNotificationBanner(banner, currentMonitorIndex) {
    if (!banner)
        return;

    const monitorIndex = currentMonitorIndex ?? global.display.get_current_monitor();
    const monitor = notificationMonitor(monitorIndex);
    const panelBox = Main.layoutManager.panelBox;
    const panelHeight = monitorIndex === Main.layoutManager.primaryIndex
        ? panelBox?.height ?? 0
        : 0;
    const topOffset = monitor.y + panelHeight + 8;

    banner.set_y(topOffset);
}

export function getWindowTypeName(metaWindow) {
    if (!metaWindow)
        return 'window';

    switch (metaWindow.window_type) {
    case Meta.WindowType.DIALOG:
        return 'dialog';
    case Meta.WindowType.MODAL_DIALOG:
        return 'modaldialog';
    default:
        return 'window';
    }
}

export function isSupportedWindowAction(metaWindow, action) {
    const type = getWindowTypeName(metaWindow);
    if (type !== 'window' && (action === 'minimize' || action === 'unminimize'))
        return false;
    if (type !== 'window' && [
        'maximize',
        'unmaximize',
        'move-start',
        'move-stop',
        'resize-start',
        'resize-stop',
    ].includes(action))
        return false;
    return [Meta.WindowType.NORMAL, Meta.WindowType.DIALOG, Meta.WindowType.MODAL_DIALOG].includes(
        metaWindow?.window_type);
}

export function isResizeGrabOp(op) {
    return [
        Meta.GrabOp.RESIZING_W,
        Meta.GrabOp.RESIZING_E,
        Meta.GrabOp.RESIZING_S,
        Meta.GrabOp.RESIZING_N,
        Meta.GrabOp.RESIZING_NW,
        Meta.GrabOp.RESIZING_NE,
        Meta.GrabOp.RESIZING_SE,
        Meta.GrabOp.RESIZING_SW,
    ].includes(op);
}

export function isMoveGrabOp(op) {
    return op === Meta.GrabOp.MOVING || op === Meta.GrabOp.MOVING_UNCONSTRAINED;
}

export function getIconTarget(actor) {
    const metaWindow = actor?.meta_window;
    if (!metaWindow)
        return {x: 0, y: 0};

    const [success, rect] = metaWindow.get_icon_geometry();
    if (success)
        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};

    const monitor = Main.layoutManager.monitors[metaWindow.get_monitor()] ?? Main.layoutManager.primaryMonitor;
    return {x: monitor.x + monitor.width / 2, y: monitor.y + monitor.height};
}

export function getActorCenter(actor) {
    const [x, y] = actor.get_transformed_position();
    return {x: x + actor.width / 2, y: y + actor.height / 2};
}

export function logDebug(settings, message) {
    if (!settings?.get_boolean('debug-logging'))
        return;
    console.log(`[More Tweaks Shell Runtime] ${message}`);
}
