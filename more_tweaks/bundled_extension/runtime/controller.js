import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Clutter from 'gi://Clutter';
import {ControlsManager} from 'resource:///org/gnome/shell/ui/overviewControls.js';
import {AppDisplay, AppFolderDialog} from 'resource:///org/gnome/shell/ui/appDisplay.js';
import {WorkspaceAnimationController} from 'resource:///org/gnome/shell/ui/workspaceAnimation.js';
import {OsdWindow} from 'resource:///org/gnome/shell/ui/osdWindow.js';

import {
    PRESETS,
    PROFILE_NAMES,
    PROFILES,
    getAnimationConfig,
    getNotificationBinding,
    getWindowBinding,
    loadCustomPresets,
} from './registry.js';
import {
    getWindowTypeName,
    isMoveGrabOp,
    isResizeGrabOp,
    isSupportedWindowAction,
    logDebug,
    positionNotificationBanner,
    resetActor,
} from './utils.js';


export class AnimationController {
    constructor(settings) {
        this._settings = settings;
        this._windowSignals = [];
        this._displaySignals = [];
        this._lastFocusedWindow = null;
        this._sizeChangeState = new WeakMap();
        this._closingActors = new WeakSet();
        this._animationWatchdogs = new Map();
        this._activeGrab = null;
        this._origShouldAnimateActor = null;
        this._origCompletedMinimize = null;
        this._origCompletedUnminimize = null;
        this._origUpdateShowingNotification = null;
        this._origHideNotification = null;
        this._systemTimingPatches = [];
        this._settingsChangedId = null;
        this._panelManager = new PanelLayoutManager(settings);
        this._topBarManager = new TopBarManager(settings);
        this._tileGapManager = new TileGapManager(settings);
    }

    enable() {
        loadCustomPresets();
        this._syncProfileLabel();
        this._installWindowHooks();
        this._installNotificationHooks();
        this._installSystemTimingHooks();
        this._lastFocusedWindow = global.display.focus_window ?? null;
        this._settingsChangedId = this._settings.connect('changed', (_, key) => {
            if (key?.startsWith('system-'))
                this._applySystemTimings();
            if (key === 'custom-presets-version')
                loadCustomPresets();
            if (key === 'per-app-overrides')
                this._refreshPerAppOverrides();
        });
        this._panelManager.enable();
        this._topBarManager.enable();
        this._tileGapManager.enable();
        logDebug(this._settings, 'animation controller enabled');
    }

    disable() {
        for (const signalId of this._windowSignals)
            global.window_manager.disconnect(signalId);
        for (const signalId of this._displaySignals)
            global.display.disconnect(signalId);
        this._windowSignals = [];
        this._displaySignals = [];
        this._activeGrab = null;
        this._lastFocusedWindow = null;
        this._clearAnimationWatchdogs();

        if (this._origShouldAnimateActor)
            Main.wm._shouldAnimateActor = this._origShouldAnimateActor;
        if (this._origCompletedMinimize)
            Main.wm._shellwm.completed_minimize = this._origCompletedMinimize;
        if (this._origCompletedUnminimize)
            Main.wm._shellwm.completed_unminimize = this._origCompletedUnminimize;
        if (this._origUpdateShowingNotification)
            Main.messageTray._updateShowingNotification = this._origUpdateShowingNotification;
        if (this._origHideNotification)
            Main.messageTray._hideNotification = this._origHideNotification;

        this._restoreSystemTimings();
        if (this._settingsChangedId) {
            this._settings.disconnect(this._settingsChangedId);
            this._settingsChangedId = null;
        }

        for (const actor of global.get_window_actors())
            resetActor(actor);
        if (Main.messageTray?._bannerBin)
            resetActor(Main.messageTray._bannerBin);

        this._tileGapManager.disable();
        this._topBarManager.disable();
        this._panelManager.disable();
        logDebug(this._settings, 'animation controller disabled');
    }

    _syncProfileLabel() {
        const profileName = this._settings.get_string('active-profile');
        if (!PROFILE_NAMES.includes(profileName))
            this._settings.set_string('active-profile', 'Balanced');
    }

    _installWindowHooks() {
        this._origShouldAnimateActor = Main.wm._shouldAnimateActor;
        this._origCompletedMinimize = Main.wm._shellwm.completed_minimize;
        this._origCompletedUnminimize = Main.wm._shellwm.completed_unminimize;

        const controller = this;

        Main.wm._shouldAnimateActor = function(actor, types) {
            const stack = `${new Error().stack}`;
            const action = stack.includes('_destroyWindow@')
                ? 'close'
                : stack.includes('_mapWindow@')
                    ? 'open'
                    : null;

            if (stack.includes('_minimizeWindow') || stack.includes('_unminimizeWindow'))
                return false;

            if (action && controller._shouldHandleWindow(actor, action)) {
                if (action === 'close')
                    controller._closingActors.add(actor);
                const originalEase = actor.ease;
                actor.ease = function(...params) {
                    actor.ease = originalEase;
                    controller._runWindowAnimation(actor, action, () => {
                        if (action === 'open')
                            Main.wm._mapWindowDone(global.window_manager, actor);
                        else
                            Main.wm._destroyWindowDone(global.window_manager, actor);
                        if (action === 'close')
                            controller._closingActors.delete(actor);
                    }, () => {
                        if (action === 'close')
                            controller._closingActors.delete(actor);
                        originalEase.apply(this, params);
                    });
                };
                return true;
            }

            return controller._origShouldAnimateActor.apply(this, [actor, types]);
        };

        Main.wm._shellwm.completed_minimize = function(_actor) {
            return;
        };
        Main.wm._shellwm.completed_unminimize = function(_actor) {
            return;
        };

        this._windowSignals.push(global.window_manager.connect('minimize', (_wm, actor) => {
            if (!this._shouldHandleWindow(actor, 'minimize')) {
                this._origCompletedMinimize.call(Main.wm._shellwm, actor);
                return;
            }

            this._runWindowAnimation(actor, 'minimize', () => {
                actor.hide();
                this._origCompletedMinimize.call(Main.wm._shellwm, actor);
            }, () => this._origCompletedMinimize.call(Main.wm._shellwm, actor));
        }));

        this._windowSignals.push(global.window_manager.connect('unminimize', (_wm, actor) => {
            actor.show();
            if (!this._shouldHandleWindow(actor, 'unminimize')) {
                this._origCompletedUnminimize.call(Main.wm._shellwm, actor);
                return;
            }

            this._runWindowAnimation(actor, 'unminimize', () => {
                this._origCompletedUnminimize.call(Main.wm._shellwm, actor);
            }, () => this._origCompletedUnminimize.call(Main.wm._shellwm, actor));
        }));

        this._windowSignals.push(global.window_manager.connect('size-change', (_wm, actor, op, oldFrameRect) => {
            if (!actor?.meta_window)
                return;

            this._sizeChangeState.set(actor, {
                op,
                oldFrameRect,
                wasMaximized: actor.meta_window.get_maximized?.() ?? actor.meta_window.get_maximize_flags?.() ?? 0,
            });
        }));

        this._windowSignals.push(global.window_manager.connect('size-changed', (_wm, actor) => {
            const state = this._sizeChangeState.get(actor);
            if (!state || !actor?.meta_window)
                return;

            const maximized = actor.meta_window.get_maximized?.() ?? actor.meta_window.get_maximize_flags?.() ?? 0;
            if (!state.wasMaximized && maximized)
                this._runTransientAnimation(actor, 'maximize');
            else if (state.wasMaximized && !maximized)
                this._runTransientAnimation(actor, 'unmaximize');

            this._sizeChangeState.delete(actor);
        }));

        this._displaySignals.push(global.display.connect('notify::focus-window', () => {
            const previousWindow = this._lastFocusedWindow;
            const focusedWindow = global.display.focus_window ?? null;
            const focusChangedBecauseOfClose = this._isClosingWindow(previousWindow);

            if (previousWindow && previousWindow !== focusedWindow && !focusChangedBecauseOfClose)
                this._runTransientAnimation(previousWindow.get_compositor_private?.(), 'defocus');
            if (focusedWindow && !focusChangedBecauseOfClose)
                this._runTransientAnimation(focusedWindow.get_compositor_private?.(), 'focus');

            this._lastFocusedWindow = focusedWindow;
        }));

        this._displaySignals.push(global.display.connect('grab-op-begin', (_display, window, op) => {
            const actor = window?.get_compositor_private?.();
            if (!actor)
                return;

            if (isMoveGrabOp(op)) {
                this._activeGrab = {actor, kind: 'move'};
                this._runTransientAnimation(actor, 'move-start');
                return;
            }

            if (isResizeGrabOp(op)) {
                this._activeGrab = {actor, kind: 'resize'};
                this._runTransientAnimation(actor, 'resize-start');
            }
        }));

        this._displaySignals.push(global.display.connect('grab-op-end', (_display, window, op) => {
            const actor = window?.get_compositor_private?.() ?? this._activeGrab?.actor;
            if (!actor)
                return;

            if (this._activeGrab?.kind === 'move' || isMoveGrabOp(op))
                this._runTransientAnimation(actor, 'move-stop');
            else if (this._activeGrab?.kind === 'resize' || isResizeGrabOp(op))
                this._runTransientAnimation(actor, 'resize-stop');

            this._activeGrab = null;
        }));
    }

    _installNotificationHooks() {
        this._origUpdateShowingNotification = Main.messageTray._updateShowingNotification;
        this._origHideNotification = Main.messageTray._hideNotification;

        Main.messageTray._updateShowingNotification = this._updateShowingNotification.bind(this);
        Main.messageTray._hideNotification = this._hideNotification.bind(this);
    }

    _getWindowBinding(actor, action) {
        const typeName = getWindowTypeName(actor?.meta_window);
        return getWindowBinding(actor?.meta_window, action, typeName);
    }

    _getPerAppOverride(metaWindow, action) {
        if (!metaWindow)
            return null;
        const wmClass = (metaWindow.get_wm_class?.() ?? '').toLowerCase();
        if (!wmClass)
            return null;
        if (!this._perAppOverridesCache)
            this._refreshPerAppOverrides();
        for (const entry of this._perAppOverridesCache) {
            const target = (entry.wm_class ?? '').toLowerCase();
            const mode = entry.match_mode ?? 'exact';
            const matched = mode === 'contains'
                ? wmClass.includes(target)
                : wmClass === target;
            if (matched && entry.rules?.[action])
                return entry.rules[action];
        }
        return null;
    }

    _refreshPerAppOverrides() {
        const raw = this._settings.get_string('per-app-overrides');
        try {
            this._perAppOverridesCache = raw ? JSON.parse(raw) : [];
        } catch (_e) {
            this._perAppOverridesCache = [];
        }
    }

    _shouldHandleWindow(actor, action) {
        if (!actor?.meta_window || !isSupportedWindowAction(actor.meta_window, action))
            return false;

        const appOverride = this._getPerAppOverride(actor.meta_window, action);
        if (appOverride)
            return appOverride.enabled !== false;

        const binding = this._getWindowBinding(actor, action);
        return this._settings.get_boolean(binding.enabledKey);
    }

    _isClosingWindow(metaWindow) {
        const actor = metaWindow?.get_compositor_private?.();
        return actor ? this._closingActors.has(actor) : false;
    }

    _runWindowAnimation(actor, action, onComplete, fallback) {
        const appOverride = this._getPerAppOverride(actor?.meta_window, action);
        if (appOverride) {
            if (appOverride.enabled === false) {
                fallback?.();
                return;
            }
            const binding = this._getWindowBinding(actor, action);
            const presetName = appOverride.preset ?? this._settings.get_string(binding.presetKey);
            const preset = PRESETS[presetName] ?? PRESETS[binding.defaultPreset] ?? PRESETS['Glide In'];
            const config = {
                ...preset,
                duration: appOverride.duration_ms ?? this._settings.get_int(binding.durationKey),
                delay: appOverride.delay_ms ?? this._settings.get_int(binding.delayKey),
                intensity: appOverride.intensity ?? this._settings.get_double(binding.intensityKey),
                presetName,
            };
            config.onComplete = this._withAnimationWatchdog(actor, config, onComplete);
            logDebug(this._settings, `${action} [app override] -> ${config.presetName}`);
            try {
                config.effect.run(actor, config);
            } catch (error) {
                this._clearAnimationWatchdog(actor);
                fallback?.();
            }
            return;
        }

        const binding = this._getWindowBinding(actor, action);
        if (!this._settings.get_boolean(binding.enabledKey)) {
            fallback?.();
            return;
        }

        const config = getAnimationConfig(this._settings, binding);
        config.onComplete = this._withAnimationWatchdog(actor, config, onComplete);
        logDebug(this._settings, `${binding.target} ${action} -> ${config.presetName}`);
        try {
            config.effect.run(actor, config);
        } catch (error) {
            this._clearAnimationWatchdog(actor);
            logDebug(this._settings, `${binding.target} ${action} failed: ${error}`);
            fallback?.();
        }
    }

    _runTransientAnimation(actor, action) {
        if (!this._shouldHandleWindow(actor, action))
            return;

        this._runWindowAnimation(actor, action, () => {}, () => {});
    }

    _updateShowingNotification(currentMonitorIndex = global.display.get_current_monitor()) {
        const binding = getNotificationBinding('open');
        if (!this._settings.get_boolean(binding.enabledKey)) {
            this._origUpdateShowingNotification.call(Main.messageTray, currentMonitorIndex);
            return;
        }

        Main.messageTray._notification.acknowledged = true;
        Main.messageTray._notification.playSound();

        if (Main.messageTray._notification.urgency === 3 || Main.messageTray._notification.source.policy.forceExpanded)
            Main.messageTray._expandBanner(true);

        Main.messageTray._notificationState = 1;
        const banner = Main.messageTray._bannerBin;
        positionNotificationBanner(banner, currentMonitorIndex);
        const config = getAnimationConfig(this._settings, binding);
        config.onComplete = this._withAnimationWatchdog(banner, config, () => {
            resetActor(banner);
            Main.messageTray._notificationState = 2;
            Main.messageTray._showNotificationCompleted();
            Main.messageTray._updateState();
        });
        logDebug(this._settings, `notification open -> ${config.presetName}`);
        try {
            config.effect.run(banner, config);
        } catch (error) {
            this._clearAnimationWatchdog(banner);
            logDebug(this._settings, `notification open failed: ${error}`);
            this._origUpdateShowingNotification.call(Main.messageTray, currentMonitorIndex);
        }
    }

    _hideNotification(animate, currentMonitorIndex = global.display.get_current_monitor()) {
        if (!animate) {
            this._origHideNotification.call(Main.messageTray, animate, currentMonitorIndex);
            return;
        }

        Main.messageTray._notificationFocusGrabber.ungrabFocus();
        if (Main.messageTray._bannerClickedId) {
            Main.messageTray._banner.disconnect(Main.messageTray._bannerClickedId);
            Main.messageTray._bannerClickedId = 0;
        }
        if (Main.messageTray._bannerUnfocusedId) {
            Main.messageTray._banner.disconnect(Main.messageTray._bannerUnfocusedId);
            Main.messageTray._bannerUnfocusedId = 0;
        }
        Main.messageTray._resetNotificationLeftTimeout();

        const binding = getNotificationBinding('close');
        if (!this._settings.get_boolean(binding.enabledKey)) {
            this._origHideNotification.call(Main.messageTray, animate, currentMonitorIndex);
            return;
        }

        const banner = Main.messageTray._bannerBin;
        positionNotificationBanner(banner, currentMonitorIndex);
        const config = getAnimationConfig(this._settings, binding);
        config.onComplete = this._withAnimationWatchdog(banner, config, () => {
            resetActor(banner);
            Main.messageTray._notificationState = 0;
            Main.messageTray._hideNotificationCompleted();
            Main.messageTray._updateState();
        });
        logDebug(this._settings, `notification close -> ${config.presetName}`);
        try {
            config.effect.run(banner, config);
        } catch (error) {
            this._clearAnimationWatchdog(banner);
            logDebug(this._settings, `notification close failed: ${error}`);
            this._origHideNotification.call(Main.messageTray, animate, currentMonitorIndex);
        }
    }

    _withAnimationWatchdog(actor, config, onComplete) {
        this._clearAnimationWatchdog(actor);

        let finished = false;
        const finish = () => {
            if (finished)
                return;

            finished = true;
            this._clearAnimationWatchdog(actor);
            onComplete?.();
        };

        const timeoutMs = Math.max(1, (config.delay ?? 0) + (config.duration ?? 0) + 120);
        const sourceId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, timeoutMs, () => {
            logDebug(this._settings, `animation watchdog completed ${config.presetName}`);
            try {
                resetActor(actor);
            } catch (_error) {
            }
            finish();
            return GLib.SOURCE_REMOVE;
        });

        this._animationWatchdogs.set(actor, sourceId);
        return finish;
    }

    _clearAnimationWatchdog(actor) {
        const sourceId = this._animationWatchdogs.get(actor);
        if (!sourceId)
            return;

        GLib.source_remove(sourceId);
        this._animationWatchdogs.delete(actor);
    }

    _clearAnimationWatchdogs() {
        for (const sourceId of this._animationWatchdogs.values())
            GLib.source_remove(sourceId);
        this._animationWatchdogs.clear();
    }

    _installSystemTimingHooks() {
        this._systemTimingPatches = [];
        const settings = this._settings;

        // Wrap a prototype method so that all ease() calls it makes on the
        // objects returned by getTargets() receive our custom duration.
        const patchEase = (proto, methodName, settingsKey, getTargets) => {
            const orig = proto[methodName];
            if (!orig) return;

            proto[methodName] = function(...args) {
                const dur = settings.get_int(settingsKey);
                if (dur <= 0)
                    return orig.apply(this, args);

                const targets = getTargets(this).filter(Boolean);
                const saved = targets.map(t =>
                    [t, Object.getOwnPropertyDescriptor(t, 'ease')]);

                for (const t of targets) {
                    const origEase = t.ease;
                    t.ease = function(...easeArgs) {
                        const p = easeArgs[easeArgs.length - 1];
                        if (p && typeof p === 'object')
                            p.duration = dur;
                        return origEase.apply(this, easeArgs);
                    };
                }
                try {
                    return orig.apply(this, args);
                } finally {
                    for (const [t, desc] of saved) {
                        if (desc)
                            Object.defineProperty(t, 'ease', desc);
                        else
                            delete t.ease;
                    }
                }
            };

            this._systemTimingPatches.push({target: proto, methodName, orig});
        };

        // Overview show/hide (ControlsManager.animateToOverview/FromOverview
        // read ANIMATION_TIME via their ease calls on _stateAdjustment)
        patchEase(ControlsManager.prototype, 'animateToOverview',
            'system-overview-duration-ms', self => [self._stateAdjustment]);
        patchEase(ControlsManager.prototype, 'animateFromOverview',
            'system-overview-duration-ms', self => [self._stateAdjustment]);

        // Overview ↔ App grid toggle (ControlsManager._onShowAppsButtonToggled
        // eases _stateAdjustment between WINDOW_PICKER and APP_GRID)
        patchEase(ControlsManager.prototype, '_onShowAppsButtonToggled',
            'system-show-apps-duration-ms',
            self => [self._stateAdjustment]);

        // App grid view switching (BaseAppView/AppDisplay.animateSwitch
        // eases this._grid and optionally this._currentDialog)
        patchEase(AppDisplay.prototype, 'animateSwitch',
            'system-app-grid-duration-ms',
            self => [self._grid, self._currentDialog]);

        // App folder open/close (AppFolderDialog zoom methods ease
        // on self and self.child)
        for (const m of ['_zoomAndFadeIn', '_zoomAndFadeOut',
            '_setLighterBackground']) {
            patchEase(AppFolderDialog.prototype, m,
                'system-app-folder-duration-ms', self => [self, self.child]);
        }

        // OSD popup fade (OsdWindow.show and _hide ease on self)
        for (const m of ['show', '_hide']) {
            patchEase(OsdWindow.prototype, m,
                'system-osd-duration-ms', self => [self]);
        }

        // Workspace switch (WorkspaceAnimationController.animateSwitch uses
        // ease_property on MonitorGroup actors — temporarily intercept it on
        // the Clutter.Actor prototype for the duration of the call)
        const origWsSwitch = WorkspaceAnimationController.prototype.animateSwitch;
        if (origWsSwitch) {
            WorkspaceAnimationController.prototype.animateSwitch =
                function(from, to, direction, onComplete) {
                    const dur = settings.get_int(
                        'system-workspace-switch-duration-ms');
                    if (dur <= 0)
                        return origWsSwitch.call(
                            this, from, to, direction, onComplete);

                    const origEp = Clutter.Actor.prototype.ease_property;
                    Clutter.Actor.prototype.ease_property =
                        function(prop, tgt, params) {
                            if (params && typeof params === 'object')
                                params.duration = dur;
                            return origEp.call(this, prop, tgt, params);
                        };
                    try {
                        return origWsSwitch.call(
                            this, from, to, direction, onComplete);
                    } finally {
                        Clutter.Actor.prototype.ease_property = origEp;
                    }
                };
            this._systemTimingPatches.push({
                target: WorkspaceAnimationController.prototype,
                methodName: 'animateSwitch',
                orig: origWsSwitch,
            });
        }

        logDebug(this._settings, 'system timing hooks installed');
    }

    _applySystemTimings() {
        // Timing overrides are read from GSettings on each method call,
        // so no explicit apply step is needed.
        logDebug(this._settings, 'system timing settings updated');
    }

    _restoreSystemTimings() {
        for (const {target, methodName, orig} of this._systemTimingPatches)
            target[methodName] = orig;
        this._systemTimingPatches = [];
    }

    applyProfile(profileName) {
        const profile = PROFILES[profileName];
        if (!profile)
            return false;

        this._settings.set_string('active-profile', profileName);
        for (const [key, value] of Object.entries(profile)) {
            if (typeof value === 'boolean')
                this._settings.set_boolean(key, value);
            else if (typeof value === 'number' && Number.isInteger(value))
                this._settings.set_int(key, value);
            else if (typeof value === 'number')
                this._settings.set_double(key, value);
            else
                this._settings.set_string(key, `${value}`);
        }
        return true;
    }
}


class TileGapManager {
    constructor(settings) {
        this._settings = settings;
        this._signalIds = [];
        this._wmSignalId = null;
        this._adjusted = new WeakMap();  // actor -> {x, y, width, height} original rect
    }

    enable() {
        this._apply();
        for (const key of ['tile-gaps-enabled', 'tile-gap-inner', 'tile-gap-outer']) {
            const id = this._settings.connect(`changed::${key}`, () => this._apply());
            this._signalIds.push(id);
        }
        // Watch for new tile operations
        this._wmSignalId = global.window_manager.connect('size-changed', (_wm, actor) => {
            if (!this._bool('tile-gaps-enabled')) return;
            // Defer to let Mutter finish placing the window
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                this._adjustIfTiled(actor);
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    disable() {
        for (const id of this._signalIds)
            this._settings.disconnect(id);
        this._signalIds = [];
        if (this._wmSignalId) {
            global.window_manager.disconnect(this._wmSignalId);
            this._wmSignalId = null;
        }
        this._restoreAll();
    }

    _bool(key) { try { return this._settings.get_boolean(key); } catch { return false; } }
    _int(key)  { try { return this._settings.get_int(key); }     catch { return 0; } }

    _apply() {
        if (!this._bool('tile-gaps-enabled')) {
            this._restoreAll();
            return;
        }
        // Re-adjust all currently tiled windows
        for (const actor of global.get_window_actors())
            this._adjustIfTiled(actor);
    }

    _adjustIfTiled(actor) {
        const meta = actor?.meta_window;
        if (!meta) return;

        const maximized = meta.get_maximized?.() ?? 0;
        // We handle half-tiles (HORIZONTAL or VERTICAL only, not BOTH which is full maximize)
        const isHalfTiled = (maximized === Meta.MaximizeFlags.HORIZONTAL
                          || maximized === Meta.MaximizeFlags.VERTICAL);
        if (!isHalfTiled) {
            // If previously adjusted but no longer tiled, restore
            if (this._adjusted.has(actor))
                this._restoreOne(actor);
            return;
        }

        const inner = this._int('tile-gap-inner');
        const outer = this._int('tile-gap-outer');
        if (inner <= 0 && outer <= 0) return;

        const rect = meta.get_frame_rect();
        const workArea = meta.get_work_area_current_monitor();

        // Save original rect before first adjustment
        if (!this._adjusted.has(actor))
            this._adjusted.set(actor, { x: rect.x, y: rect.y, width: rect.width, height: rect.height });

        let x = rect.x, y = rect.y, w = rect.width, h = rect.height;

        if (maximized === Meta.MaximizeFlags.HORIZONTAL) {
            // Half-tiled left or right (vertical strip)
            const isLeft = (rect.x <= workArea.x);
            const isRight = (rect.x + rect.width >= workArea.x + workArea.width - 2);

            // Top/bottom outer gaps
            y = rect.y + outer;
            h = rect.height - outer * 2;

            if (isLeft) {
                // Left tile: outer gap on left, half inner gap on right
                x = rect.x + outer;
                w = rect.width - outer - Math.ceil(inner / 2);
            } else if (isRight) {
                // Right tile: half inner gap on left, outer gap on right
                x = rect.x + Math.floor(inner / 2);
                w = rect.width - Math.floor(inner / 2) - outer;
            }
        } else if (maximized === Meta.MaximizeFlags.VERTICAL) {
            // Half-tiled top or bottom (horizontal strip)
            const isTop = (rect.y <= workArea.y);
            const isBottom = (rect.y + rect.height >= workArea.y + workArea.height - 2);

            // Left/right outer gaps
            x = rect.x + outer;
            w = rect.width - outer * 2;

            if (isTop) {
                y = rect.y + outer;
                h = rect.height - outer - Math.ceil(inner / 2);
            } else if (isBottom) {
                y = rect.y + Math.floor(inner / 2);
                h = rect.height - Math.floor(inner / 2) - outer;
            }
        }

        if (w > 0 && h > 0)
            meta.move_resize_frame(true, x, y, w, h);
    }

    _restoreOne(actor) {
        const orig = this._adjusted.get(actor);
        if (!orig) return;
        this._adjusted.delete(actor);
        const meta = actor?.meta_window;
        if (meta)
            meta.move_resize_frame(true, orig.x, orig.y, orig.width, orig.height);
    }

    _restoreAll() {
        for (const actor of global.get_window_actors()) {
            if (this._adjusted.has(actor))
                this._restoreOne(actor);
        }
    }
}


class TopBarManager {
    constructor(settings) {
        this._settings = settings;
        this._signalIds = [];
        this._origActivitiesText = null;
        this._origClockUpdate = null;
        this._clockTimerId = null;
        this._addedStyleClasses = [];
    }

    enable() {
        this._apply();
        for (const key of [
            'topbar-overrides-enabled',
            'activities-button-visible',
            'activities-button-text',
            'clock-custom-format-enabled',
            'clock-custom-format',
            'panel-icon-spacing',
        ]) {
            const id = this._settings.connect(`changed::${key}`, () => this._apply());
            this._signalIds.push(id);
        }
    }

    disable() {
        for (const id of this._signalIds)
            this._settings.disconnect(id);
        this._signalIds = [];
        this._restoreActivities();
        this._restoreClock();
        this._restoreSpacing();
    }

    _str(key) {
        try { return this._settings.get_string(key); } catch { return ''; }
    }
    _bool(key) {
        try { return this._settings.get_boolean(key); } catch { return false; }
    }
    _int(key) {
        try { return this._settings.get_int(key); } catch { return -1; }
    }

    // ── Activities button ─────────────────────────────────────────────

    _applyActivities() {
        const activities = Main.panel.statusArea?.activities;
        if (!activities) return;

        // Save original text once
        if (this._origActivitiesText === null)
            this._origActivitiesText = activities.get_child_at_index?.(0)?.text
                ?? activities.label?.text ?? 'Activities';

        const visible = this._bool('activities-button-visible');
        activities.container.visible = visible;

        if (visible) {
            const customText = this._str('activities-button-text');
            const label = activities.get_child_at_index?.(0) ?? activities.label;
            if (label && customText)
                label.text = customText;
            else if (label && !customText)
                label.text = this._origActivitiesText;
        }
    }

    _restoreActivities() {
        const activities = Main.panel.statusArea?.activities;
        if (!activities) return;
        activities.container.visible = true;
        if (this._origActivitiesText !== null) {
            const label = activities.get_child_at_index?.(0) ?? activities.label;
            if (label) label.text = this._origActivitiesText;
        }
        this._origActivitiesText = null;
    }

    // ── Custom clock format ───────────────────────────────────────────

    _applyClock() {
        const dateMenu = Main.panel.statusArea?.dateMenu;
        if (!dateMenu) return;

        const clock = dateMenu._clock;
        if (!clock) return;

        if (this._bool('clock-custom-format-enabled')) {
            const fmt = this._str('clock-custom-format') || '%H:%M';
            // Save original _updateClock once
            if (!this._origClockUpdate)
                this._origClockUpdate = dateMenu._updateClock?.bind(dateMenu);

            // Replace the clock update function
            dateMenu._updateClock = () => {
                const now = GLib.DateTime.new_now_local();
                dateMenu._clockDisplay.text = now.format(fmt) ?? '';
            };
            // Apply immediately
            dateMenu._updateClock();

            // Ensure updates continue (clock signal may stop calling our override
            // if the internal WallClock only notifies on minute changes but we
            // show seconds).  Add a 1-second timer if the format contains %S.
            if (fmt.includes('%S') && !this._clockTimerId) {
                this._clockTimerId = GLib.timeout_add_seconds(
                    GLib.PRIORITY_DEFAULT, 1, () => {
                        try { dateMenu._updateClock(); } catch { /* */ }
                        return GLib.SOURCE_CONTINUE;
                    }
                );
            } else if (!fmt.includes('%S') && this._clockTimerId) {
                GLib.source_remove(this._clockTimerId);
                this._clockTimerId = null;
            }
        } else {
            this._restoreClock();
        }
    }

    _restoreClock() {
        if (this._clockTimerId) {
            GLib.source_remove(this._clockTimerId);
            this._clockTimerId = null;
        }
        const dateMenu = Main.panel.statusArea?.dateMenu;
        if (dateMenu && this._origClockUpdate) {
            dateMenu._updateClock = this._origClockUpdate;
            this._origClockUpdate = null;
            try { dateMenu._updateClock(); } catch { /* */ }
        }
    }

    // ── Panel icon spacing ────────────────────────────────────────────

    _applySpacing() {
        const spacing = this._int('panel-icon-spacing');
        const className = 'more-tweaks-panel-spacing';

        // Remove old overrides first
        this._restoreSpacing();

        if (spacing < 0) return;

        // Apply padding to each indicator container in the panel
        for (const box of [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox]) {
            for (const child of box.get_children()) {
                child.set_style(`padding-left: ${spacing}px; padding-right: ${spacing}px;`);
                child.add_style_class_name(className);
                this._addedStyleClasses.push(child);
            }
        }
    }

    _restoreSpacing() {
        for (const child of this._addedStyleClasses) {
            try {
                child.set_style(null);
                child.remove_style_class_name('more-tweaks-panel-spacing');
            } catch { /* actor may have been destroyed */ }
        }
        this._addedStyleClasses = [];
    }

    // ── Orchestration ─────────────────────────────────────────────────

    _apply() {
        if (!this._bool('topbar-overrides-enabled')) {
            this._restoreActivities();
            this._restoreClock();
            this._restoreSpacing();
            return;
        }
        this._applyActivities();
        this._applyClock();
        this._applySpacing();
    }
}


class PanelLayoutManager {
    constructor(settings) {
        this._settings = settings;
        this._originalLayout = null;
        this._settingsChangedId = null;
        this._boxSignalIds = [];
        this._republishDebounceId = null;
    }

    enable() {
        this._saveOriginalLayout();
        this._publishAvailableItems();
        this._applyLayout();
        this._settingsChangedId = this._settings.connect(
            'changed::panel-layout', () => this._applyLayout()
        );
        // Watch for indicators being added/removed from panel boxes.
        // GNOME 47+ renamed the Clutter signals to child-added/child-removed.
        const addSignal = 'child-added';
        const removeSignal = 'child-removed';
        for (const box of [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox]) {
            const addId = box.connect(addSignal, () => this._scheduleRepublish());
            const removeId = box.connect(removeSignal, () => this._scheduleRepublish());
            this._boxSignalIds.push({ box, id: addId }, { box, id: removeId });
        }
        // Also re-publish after a short delay to catch late-loading extensions
        this._republishTimeoutId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 3000, () => {
                this._publishAvailableItems();
                this._republishTimeoutId = null;
                return GLib.SOURCE_REMOVE;
            }
        );
    }

    disable() {
        if (this._settingsChangedId) {
            this._settings.disconnect(this._settingsChangedId);
            this._settingsChangedId = null;
        }
        for (const { box, id } of this._boxSignalIds) {
            box.disconnect(id);
        }
        this._boxSignalIds = [];
        if (this._republishDebounceId) {
            GLib.source_remove(this._republishDebounceId);
            this._republishDebounceId = null;
        }
        if (this._republishTimeoutId) {
            GLib.source_remove(this._republishTimeoutId);
            this._republishTimeoutId = null;
        }
        // Clear the available-items key so stale data isn't shown
        this._settings.set_string('panel-items-available', '');
        this._restoreOriginalLayout();
    }

    _scheduleRepublish() {
        // Debounce: multiple actors may be added/removed in quick succession
        if (this._republishDebounceId)
            return;
        this._republishDebounceId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 250, () => {
                this._republishDebounceId = null;
                this._publishAvailableItems();
                return GLib.SOURCE_REMOVE;
            }
        );
    }

    _publishAvailableItems() {
        const statusArea = Main.panel.statusArea ?? {};
        const boxes = {
            left: Main.panel._leftBox,
            center: Main.panel._centerBox,
            right: Main.panel._rightBox,
        };

        // Build a reverse map: actor -> name (only for visible indicators)
        const actorToName = new Map();
        for (const [name, indicator] of Object.entries(statusArea)) {
            if (!indicator?.container)
                continue;
            // Skip indicators that are registered but not actually visible
            // on the top bar (e.g. appMenu on GNOME 44+, dwellClick when
            // accessibility dwell-click is off).
            if (!indicator.container.visible || !indicator.visible)
                continue;
            actorToName.set(indicator.container, name);
        }

        // Walk each box in child order to capture the real layout
        const result = {};
        for (const [zoneName, box] of Object.entries(boxes)) {
            const names = [];
            for (const child of box.get_children()) {
                const name = actorToName.get(child);
                if (name)
                    names.push(name);
            }
            result[zoneName] = names;
        }

        this._settings.set_string(
            'panel-items-available', JSON.stringify(result)
        );
    }

    _saveOriginalLayout() {
        this._originalLayout = {
            left: [...Main.panel._leftBox.get_children()],
            center: [...Main.panel._centerBox.get_children()],
            right: [...Main.panel._rightBox.get_children()],
        };
    }

    _restoreOriginalLayout() {
        if (!this._originalLayout)
            return;

        const boxes = {
            left: Main.panel._leftBox,
            center: Main.panel._centerBox,
            right: Main.panel._rightBox,
        };

        // Remove all children from all boxes first
        for (const box of Object.values(boxes)) {
            for (const child of [...box.get_children()])
                box.remove_child(child);
        }

        // Re-add in original order
        for (const [zoneName, children] of Object.entries(this._originalLayout)) {
            const box = boxes[zoneName];
            for (const child of children)
                box.add_child(child);
        }

        this._originalLayout = null;
    }

    _applyLayout() {
        const raw = this._settings.get_string('panel-layout');
        if (!raw)
            return;

        let layout;
        try {
            layout = JSON.parse(raw);
        } catch {
            return;
        }

        const boxes = {
            left: Main.panel._leftBox,
            center: Main.panel._centerBox,
            right: Main.panel._rightBox,
        };

        // Build name -> actor map from statusArea
        const actorMap = {};
        for (const [name, indicator] of Object.entries(Main.panel.statusArea ?? {})) {
            if (indicator?.container)
                actorMap[name] = indicator.container;
        }

        // Collect actors referenced in the layout
        const managed = new Set();
        for (const zoneName of ['left', 'center', 'right']) {
            for (const itemName of (layout[zoneName] ?? []))
                managed.add(itemName);
        }

        // Remove managed actors from their current parents
        for (const itemName of managed) {
            const actor = actorMap[itemName];
            if (actor) {
                const parent = actor.get_parent();
                if (parent)
                    parent.remove_child(actor);
            }
        }

        // Insert managed actors into target zones in order
        for (const zoneName of ['left', 'center', 'right']) {
            const names = layout[zoneName] ?? [];
            const box = boxes[zoneName];
            for (const itemName of names) {
                const actor = actorMap[itemName];
                if (actor)
                    box.add_child(actor);
            }
        }
    }
}
