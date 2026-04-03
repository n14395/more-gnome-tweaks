import Cogl from 'gi://Cogl';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Clutter from 'gi://Clutter';
import St from 'gi://St';
import {ControlsManager} from 'resource:///org/gnome/shell/ui/overviewControls.js';
import {AppDisplay, AppFolderDialog} from 'resource:///org/gnome/shell/ui/appDisplay.js';
import {WorkspaceAnimationController} from 'resource:///org/gnome/shell/ui/workspaceAnimation.js';
import {OsdWindow} from 'resource:///org/gnome/shell/ui/osdWindow.js';

import {
    PRESETS,
    getAnimationConfig,
    getNotificationBinding,
    getWindowBinding,
    loadCustomPresets,
} from './registry.js';
import {
    getShellMajorVersion,
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
        this._lifecycleActors = new WeakSet();
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
        this._tileGridManager = new TileGridManager(settings);
    }

    enable(capabilities = {}) {
        loadCustomPresets();

        try {
            this._installWindowHooks();
            capabilities.animations = true;
        } catch (e) {
            logDebug(this._settings, `window hooks failed: ${e}`);
            capabilities.animations = false;
        }

        try {
            this._installNotificationHooks();
            capabilities.notifications = true;
        } catch (e) {
            logDebug(this._settings, `notification hooks failed: ${e}`);
            capabilities.notifications = false;
        }

        try {
            this._installSystemTimingHooks();
            capabilities.systemTimings = true;
        } catch (e) {
            logDebug(this._settings, `system timing hooks failed: ${e}`);
            capabilities.systemTimings = false;
        }

        this._lastFocusedWindow = global.display.focus_window ?? null;
        this._settingsChangedId = this._settings.connect('changed', (_, key) => {
            if (key?.startsWith('system-'))
                this._applySystemTimings();
            if (key === 'custom-presets-version')
                loadCustomPresets();
            if (key === 'per-app-overrides')
                this._refreshPerAppOverrides();
        });

        try {
            this._panelManager.enable();
            capabilities.panelLayout = true;
        } catch (e) {
            logDebug(this._settings, `panel layout manager failed: ${e}`);
            capabilities.panelLayout = false;
        }

        try {
            this._topBarManager.enable();
            capabilities.topBar = true;
        } catch (e) {
            logDebug(this._settings, `top bar manager failed: ${e}`);
            capabilities.topBar = false;
        }

        try {
            this._tileGapManager.enable();
            capabilities.tileGaps = true;
        } catch (e) {
            logDebug(this._settings, `tile gap manager failed: ${e}`);
            capabilities.tileGaps = false;
        }

        try {
            this._tileGridManager.enable();
            capabilities.tileGrid = true;
        } catch (e) {
            logDebug(this._settings, `tile grid manager failed: ${e}`);
            capabilities.tileGrid = false;
        }

        logDebug(this._settings, 'animation controller enabled');
    }

    disable() {
        for (const signalId of this._windowSignals)
            try { global.window_manager.disconnect(signalId); } catch (_e) {}
        for (const signalId of this._displaySignals)
            try { global.display.disconnect(signalId); } catch (_e) {}
        this._windowSignals = [];
        this._displaySignals = [];
        this._activeGrab = null;
        this._lastFocusedWindow = null;
        this._clearAnimationWatchdogs();

        try {
            if (this._origShouldAnimateActor)
                Main.wm._shouldAnimateActor = this._origShouldAnimateActor;
            if (this._origCompletedMinimize)
                Main.wm._shellwm.completed_minimize = this._origCompletedMinimize;
            if (this._origCompletedUnminimize)
                Main.wm._shellwm.completed_unminimize = this._origCompletedUnminimize;
        } catch (_e) {}

        try {
            if (this._origUpdateShowingNotification)
                Main.messageTray._updateShowingNotification = this._origUpdateShowingNotification;
            if (this._origHideNotification)
                Main.messageTray._hideNotification = this._origHideNotification;
        } catch (_e) {}

        try { this._restoreSystemTimings(); } catch (_e) {}

        if (this._settingsChangedId) {
            try { this._settings.disconnect(this._settingsChangedId); } catch (_e) {}
            this._settingsChangedId = null;
        }

        try {
            for (const actor of global.get_window_actors())
                resetActor(actor);
            if (Main.messageTray?._bannerBin)
                resetActor(Main.messageTray._bannerBin);
        } catch (_e) {}

        try { this._tileGridManager.disable(); } catch (_e) {}
        try { this._tileGapManager.disable(); } catch (_e) {}
        try { this._topBarManager.disable(); } catch (_e) {}
        try { this._panelManager.disable(); } catch (_e) {}
        logDebug(this._settings, 'animation controller disabled');
    }

    _installWindowHooks() {
        if (!Main.wm?._shouldAnimateActor || !Main.wm?._shellwm?.completed_minimize)
            throw new Error('WindowManager animation hooks not found');

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
                if (action === 'close') {
                    controller._closingActors.add(actor);
                    controller._lifecycleActors.add(actor);
                }
                const originalEase = actor.ease;
                actor.ease = function(...params) {
                    actor.ease = originalEase;
                    controller._runWindowAnimation(actor, action, () => {
                        if (action === 'open') {
                            resetActor(actor);
                            Main.wm._mapWindowDone(global.window_manager, actor);
                        } else {
                            actor.hide();
                            Main.wm._destroyWindowDone(global.window_manager, actor);
                        }
                        if (action === 'close') {
                            controller._closingActors.delete(actor);
                            controller._lifecycleActors.delete(actor);
                        }
                    }, () => {
                        if (action === 'close') {
                            controller._closingActors.delete(actor);
                            controller._lifecycleActors.delete(actor);
                        }
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

            this._lifecycleActors.add(actor);
            this._runWindowAnimation(actor, 'minimize', () => {
                this._lifecycleActors.delete(actor);
                actor.hide();
                this._origCompletedMinimize.call(Main.wm._shellwm, actor);
            }, () => {
                this._lifecycleActors.delete(actor);
                actor.hide();
                this._origCompletedMinimize.call(Main.wm._shellwm, actor);
            });
        }));

        this._windowSignals.push(global.window_manager.connect('unminimize', (_wm, actor) => {
            actor.show();
            if (!this._shouldHandleWindow(actor, 'unminimize')) {
                this._origCompletedUnminimize.call(Main.wm._shellwm, actor);
                return;
            }

            this._lifecycleActors.add(actor);
            this._runWindowAnimation(actor, 'unminimize', () => {
                this._lifecycleActors.delete(actor);
                this._origCompletedUnminimize.call(Main.wm._shellwm, actor);
            }, () => {
                this._lifecycleActors.delete(actor);
                this._origCompletedUnminimize.call(Main.wm._shellwm, actor);
            });
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
        if (!Main.messageTray?._updateShowingNotification || !Main.messageTray?._hideNotification)
            throw new Error('MessageTray notification methods not found');

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
        const isOutgoing = action === 'close' || action === 'minimize';
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
                skipFinalReset: isOutgoing,
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
        config.skipFinalReset = isOutgoing;
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
        if (!actor || this._lifecycleActors.has(actor))
            return;
        if (!this._shouldHandleWindow(actor, action))
            return;

        this._runWindowAnimation(actor, action, () => { resetActor(actor); }, () => { resetActor(actor); });
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
                if (!config.skipFinalReset)
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

        // Overview state shift (ControlsManager._shiftState handles double-tap
        // Super → app grid and shift-overview keybindings by directly easing
        // _stateAdjustment to the next/previous state)
        patchEase(ControlsManager.prototype, '_shiftState',
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

    _bool(key) { try { return this._settings.get_boolean(key); } catch (_e) { return false; } }
    _int(key)  { try { return this._settings.get_int(key); }     catch (_e) { return 0; } }

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
            // Window no longer half-tiled — forget it.  Mutter handles the
            // un-tile transition itself, and the grid manager may have
            // repositioned the window intentionally.
            this._adjusted.delete(actor);
            return;
        }

        const inner = this._int('tile-gap-inner');
        const outer = this._int('tile-gap-outer');
        if (inner <= 0 && outer <= 0) return;

        const workArea = meta.get_work_area_current_monitor();

        // Save original rect on first adjustment; always calculate from it
        // so repeated calls are idempotent (size-changed re-fires after move)
        if (!this._adjusted.has(actor)) {
            const rect = meta.get_frame_rect();
            this._adjusted.set(actor, { x: rect.x, y: rect.y, width: rect.width, height: rect.height });
        }
        const orig = this._adjusted.get(actor);
        let x = orig.x, y = orig.y, w = orig.width, h = orig.height;

        if (maximized === Meta.MaximizeFlags.VERTICAL) {
            // VERTICAL = full height → left or right tile (vertical strip)
            const isLeft = (orig.x <= workArea.x);
            const isRight = (orig.x + orig.width >= workArea.x + workArea.width - 2);

            // Top/bottom outer gaps
            y = orig.y + outer;
            h = orig.height - outer * 2;

            if (isLeft) {
                // Left tile: outer gap on left, half inner gap on right
                x = orig.x + outer;
                w = orig.width - outer - Math.ceil(inner / 2);
            } else if (isRight) {
                // Right tile: half inner gap on left, outer gap on right
                x = orig.x + Math.floor(inner / 2);
                w = orig.width - Math.floor(inner / 2) - outer;
            }
        } else if (maximized === Meta.MaximizeFlags.HORIZONTAL) {
            // HORIZONTAL = full width → top or bottom tile (horizontal strip)
            const isTop = (orig.y <= workArea.y);
            const isBottom = (orig.y + orig.height >= workArea.y + workArea.height - 2);

            // Left/right outer gaps
            x = orig.x + outer;
            w = orig.width - outer * 2;

            if (isTop) {
                y = orig.y + outer;
                h = orig.height - outer - Math.ceil(inner / 2);
            } else if (isBottom) {
                y = orig.y + Math.floor(inner / 2);
                h = orig.height - Math.floor(inner / 2) - outer;
            }
        }

        // Only call move_resize_frame if the position actually changed,
        // to avoid an infinite size-changed signal loop
        const cur = meta.get_frame_rect();
        if (w > 0 && h > 0 &&
            (x !== cur.x || y !== cur.y || w !== cur.width || h !== cur.height))
            meta.move_resize_frame(false, x, y, w, h);
    }

    _restoreOne(actor) {
        const orig = this._adjusted.get(actor);
        if (!orig) return;
        this._adjusted.delete(actor);
        const meta = actor?.meta_window;
        if (meta)
            meta.move_resize_frame(false, orig.x, orig.y, orig.width, orig.height);
    }

    _restoreAll() {
        for (const actor of global.get_window_actors()) {
            if (this._adjusted.has(actor))
                this._restoreOne(actor);
        }
    }
}


// ── Tile grid preview & snap ─────────────────────────────────────────

class TileGridManager {
    constructor(settings) {
        this._settings = settings;
        this._signalIds = [];
        this._grabBeginId = null;
        this._grabEndId = null;
        this._preview = null;
        this._delayTimerId = null;
        this._pollTimerId = null;
        this._previewLoc = null;   // { col, row, w, h } in grid units
        this._dragWindow = null;
        this._mutterSettings = null;
        this._savedEdgeTiling = null;
        this._tiledWindows = new WeakMap();  // window -> original frame rect
    }

    enable() {
        for (const key of [
            'tile-cols', 'tile-rows',
            'tile-preview-enabled', 'tile-preview-distance', 'tile-preview-delay',
            'tile-gaps-enabled', 'tile-gap-inner', 'tile-gap-outer',
        ]) {
            const id = this._settings.connect(`changed::${key}`, () => this._reconfigure());
            this._signalIds.push(id);
        }
        this._reconfigure();
    }

    disable() {
        this._disconnectGrab();
        this._cancelDrag();
        this._destroyPreview();
        for (const id of this._signalIds)
            this._settings.disconnect(id);
        this._signalIds = [];
    }

    _bool(key) { try { return this._settings.get_boolean(key); } catch (_e) { return false; } }
    _int(key)  { try { return this._settings.get_int(key); }     catch (_e) { return 0; } }

    // ── Grab lifecycle ───────────────────────────────────────────

    _reconfigure() {
        if (this._bool('tile-preview-enabled'))
            this._connectGrab();
        else {
            this._disconnectGrab();
            this._cancelDrag();
            this._hidePreview();
        }
    }

    _connectGrab() {
        if (this._grabBeginId) return;
        // Disable GNOME's built-in edge-tiling so it doesn't compete
        try {
            this._mutterSettings = new Gio.Settings({ schema_id: 'org.gnome.mutter' });
            this._savedEdgeTiling = this._mutterSettings.get_boolean('edge-tiling');
            if (this._savedEdgeTiling)
                this._mutterSettings.set_boolean('edge-tiling', false);
        } catch (_e) {
            this._mutterSettings = null;
            this._savedEdgeTiling = null;
        }
        this._grabBeginId = global.display.connect('grab-op-begin',
            (_d, win, op) => this._onGrabBegin(win, op));
        this._grabEndId = global.display.connect('grab-op-end',
            () => this._onGrabEnd());
    }

    _disconnectGrab() {
        if (this._grabBeginId) {
            global.display.disconnect(this._grabBeginId);
            this._grabBeginId = null;
        }
        if (this._grabEndId) {
            global.display.disconnect(this._grabEndId);
            this._grabEndId = null;
        }
        // Restore GNOME's built-in edge-tiling
        if (this._mutterSettings && this._savedEdgeTiling !== null) {
            try { this._mutterSettings.set_boolean('edge-tiling', this._savedEdgeTiling); } catch (_e) {}
            this._mutterSettings = null;
            this._savedEdgeTiling = null;
        }
    }

    _onGrabBegin(win, op) {
        // Only handle window-move grabs (op 1), ignoring resize ops.
        // Bit 1024 is set for keyboard-initiated moves.
        if ((op & ~1024) !== 1 || !win) return;
        this._dragWindow = win;

        // Restore original window size when dragging a previously-tiled window
        const saved = this._tiledWindows.get(win);
        if (saved) {
            this._tiledWindows.delete(win);
            const [mx] = global.get_pointer();
            // Centre the restored width on the cursor, clamped to work area
            const workArea = win.get_work_area_current_monitor();
            let x = mx - Math.round(saved.width / 2);
            x = Math.max(workArea.x, Math.min(x, workArea.x + workArea.width - saved.width));
            try {
                const m = win.get_maximized?.() ?? 0;
                if (m) win.unmaximize(m);
                win.move_resize_frame(false, x, saved.y, saved.width, saved.height);
            } catch (_e) { /* window may have been destroyed */ }
        }

        const delay = Math.max(25, this._int('tile-preview-delay'));
        this._delayTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
            this._delayTimerId = null;
            this._startPolling();
            return GLib.SOURCE_REMOVE;
        });
    }

    _onGrabEnd() {
        const loc = this._previewLoc;
        const win = this._dragWindow;
        this._cancelDrag();
        this._hidePreview();
        if (!loc || !win) return;

        // Save the current frame rect so we can restore it on un-tile
        try {
            const cur = win.get_frame_rect();
            this._tiledWindows.set(win, {
                x: cur.x, y: cur.y, width: cur.width, height: cur.height,
            });
        } catch (_e) { /* ignore */ }

        const workArea = win.get_work_area_current_monitor();
        const rect = this._calcTileRect(loc, workArea);
        // Defer so GNOME Shell finishes its own grab processing first
        GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            try {
                const m = win.get_maximized?.() ?? 0;
                if (m) win.unmaximize(m);
                win.move_resize_frame(false, rect.x, rect.y, rect.width, rect.height);
            } catch (_e) { /* window may have been destroyed */ }
            return GLib.SOURCE_REMOVE;
        });
    }

    _cancelDrag() {
        if (this._delayTimerId) {
            GLib.source_remove(this._delayTimerId);
            this._delayTimerId = null;
        }
        if (this._pollTimerId) {
            GLib.source_remove(this._pollTimerId);
            this._pollTimerId = null;
        }
        this._dragWindow = null;
        this._previewLoc = null;
    }

    // ── Mouse polling ────────────────────────────────────────────

    _startPolling() {
        this._checkMouse();
        this._pollTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
            this._checkMouse();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _checkMouse() {
        if (!this._dragWindow) return;
        const [mx, my] = global.get_pointer();
        const workArea = this._dragWindow.get_work_area_current_monitor();
        const dist = Math.max(1, this._int('tile-preview-distance'));
        const cols = Math.max(1, this._int('tile-cols'));
        const rows = Math.max(1, this._int('tile-rows'));

        const nearL = mx - workArea.x < dist;
        const nearR = workArea.x + workArea.width - mx < dist;
        const nearT = my - workArea.y < dist;
        const nearB = workArea.y + workArea.height - my < dist;

        let loc = null;

        // Corners (checked first since they overlap edge zones)
        if (nearT && nearL)
            loc = { col: 0, row: 0, w: 1, h: 1 };
        else if (nearT && nearR)
            loc = { col: cols - 1, row: 0, w: 1, h: 1 };
        else if (nearB && nearL)
            loc = { col: 0, row: rows - 1, w: 1, h: 1 };
        else if (nearB && nearR)
            loc = { col: cols - 1, row: rows - 1, w: 1, h: 1 };
        // Single edges
        else if (nearT)
            loc = { col: 0, row: 0, w: cols, h: rows };   // top → maximise
        else if (nearB)
            loc = { col: 0, row: rows - 1, w: cols, h: 1 };   // bottom row
        else if (nearL)
            loc = { col: 0, row: 0, w: 1, h: rows };   // left column
        else if (nearR)
            loc = { col: cols - 1, row: 0, w: 1, h: rows };   // right column

        if (loc && !this._locEq(loc, this._previewLoc)) {
            this._previewLoc = loc;
            this._showPreview(loc, workArea);
        } else if (!loc && this._previewLoc) {
            this._previewLoc = null;
            this._hidePreview();
        }
    }

    _locEq(a, b) {
        return a && b && a.col === b.col && a.row === b.row
            && a.w === b.w && a.h === b.h;
    }

    // ── Grid rect calculation ────────────────────────────────────

    _calcTileRect(loc, workArea) {
        const cols = Math.max(1, this._int('tile-cols'));
        const rows = Math.max(1, this._int('tile-rows'));
        const cellW = Math.floor(workArea.width / cols);
        const cellH = Math.floor(workArea.height / rows);

        let x = workArea.x + loc.col * cellW;
        let y = workArea.y + loc.row * cellH;
        let w = loc.w * cellW;
        let h = loc.h * cellH;

        // Absorb remainder pixels at right / bottom edges
        if (loc.col + loc.w === cols)
            w = workArea.width - loc.col * cellW;
        if (loc.row + loc.h === rows)
            h = workArea.height - loc.row * cellH;

        // Apply gaps when enabled
        if (this._bool('tile-gaps-enabled')) {
            const inner = this._int('tile-gap-inner');
            const outer = this._int('tile-gap-outer');
            const hi = Math.floor(inner / 2);
            const gl = loc.col === 0             ? outer : hi;
            const gr = loc.col + loc.w === cols  ? outer : hi;
            const gt = loc.row === 0             ? outer : hi;
            const gb = loc.row + loc.h === rows  ? outer : hi;
            x += gl;  y += gt;
            w -= gl + gr;  h -= gt + gb;
        }

        return { x, y, width: Math.max(w, 1), height: Math.max(h, 1) };
    }

    // ── Preview overlay ──────────────────────────────────────────

    _ensurePreview() {
        if (this._preview) return;
        this._preview = new St.Widget({
            style_class: 'tile-preview',
            visible: false,
        });
        Main.uiGroup.add_child(this._preview);
    }

    _showPreview(loc, workArea) {
        this._ensurePreview();
        const r = this._calcTileRect(loc, workArea);
        this._preview.ease({
            x: r.x, y: r.y, width: r.width, height: r.height,
            opacity: 255, duration: 125,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        this._preview.show();
    }

    _hidePreview() {
        if (!this._preview?.visible) return;
        this._preview.ease({
            opacity: 0, duration: 125,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => { if (this._preview) this._preview.hide(); },
        });
    }

    _destroyPreview() {
        if (this._preview) {
            this._preview.destroy();
            this._preview = null;
        }
    }
}


class TopBarManager {
    constructor(settings) {
        this._settings = settings;
        this._signalIds = [];
        this._origClockUpdate = null;
        this._clockTimerId = null;
        this._styledChildren = [];
        this._deferredApplyIds = [];
        this._childChangedId = null;
        this._boxSignalIds = [];
    }

    enable() {
        this._apply();
        // Re-apply after short delays so that third-party indicators
        // that load icons asynchronously get colored too.
        this._deferredApplyIds = [3000, 10000, 35000, 60000].map(ms =>
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms, () => {
                this._apply();
                return GLib.SOURCE_REMOVE;
            })
        );
        // Watch for indicators added/removed from panel boxes.  Re-apply
        // styles when panel children change.
        const ver = getShellMajorVersion();
        const addSignal = ver >= 47 ? 'child-added' : 'actor-added';
        const removeSignal = ver >= 47 ? 'child-removed' : 'actor-removed';
        // Debounced re-apply: when a new indicator appears, its icon may
        // load asynchronously — wait a moment before re-applying styles.
        const debouncedApply = () => {
            if (this._childChangedId) GLib.source_remove(this._childChangedId);
            this._childChangedId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
                this._childChangedId = null;
                this._apply();
                return GLib.SOURCE_REMOVE;
            });
        };
        for (const box of [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox]) {
            try {
                const addId = box.connect(addSignal, (_b, child) => {
                    this._watchIndicatorVisibility(child, debouncedApply);
                    debouncedApply();
                });
                const removeId = box.connect(removeSignal, debouncedApply);
                this._boxSignalIds.push({box, id: addId}, {box, id: removeId});
            } catch (_e) { /* signal not available */ }
            // Watch existing indicators for visibility changes.  This catches
            // indicators like Pamac that start hidden and become visible later
            // (e.g. after a 30s boot wait + async update check).
            for (const child of box.get_children())
                this._watchIndicatorVisibility(child, debouncedApply);
        }
        for (const key of [
            'topbar-overrides-enabled',
            'activities-button-visible',
            'clock-custom-format-enabled',
            'clock-custom-format',
            'panel-icon-spacing',
            'panel-icon-color',
            'panel-color-symbolic',
            'panel-color-other',
            'panel-color-activities',
        ]) {
            try {
                const id = this._settings.connect(`changed::${key}`, () => this._apply());
                this._signalIds.push(id);
            } catch (_e) { /* key may not exist in older compiled schema */ }
        }
    }

    _watchIndicatorVisibility(container, callback) {
        // The container is an St.Bin; the actual indicator is its .child.
        // Watch the indicator's visibility — when it changes from hidden to
        // visible (e.g. Pamac after finding updates), trigger a re-apply.
        const indicator = container.child || container;
        try {
            const id = indicator.connect('notify::visible', callback);
            this._boxSignalIds.push({box: indicator, id});
        } catch (_e) { /* */ }
    }

    disable() {
        for (const id of (this._deferredApplyIds ?? []))
            GLib.source_remove(id);
        this._deferredApplyIds = [];
        if (this._childChangedId) {
            GLib.source_remove(this._childChangedId);
            this._childChangedId = null;
        }
        for (const {box, id} of this._boxSignalIds) {
            try { box.disconnect(id); } catch (_e) { /* */ }
        }
        this._boxSignalIds = [];
        for (const id of this._signalIds)
            this._settings.disconnect(id);
        this._signalIds = [];
        this._restoreActivities();
        this._restoreClock();
        this._restorePanelStyles();
    }

    _str(key) {
        try { return this._settings.get_string(key); } catch (_e) { return ''; }
    }
    _bool(key) {
        try { return this._settings.get_boolean(key); } catch (_e) { return false; }
    }
    _int(key) {
        try { return this._settings.get_int(key); } catch (_e) { return -1; }
    }

    // ── Activities button ─────────────────────────────────────────────

    _applyActivities() {
        const activities = Main.panel.statusArea?.activities;
        if (!activities) return;

        const visible = this._bool('activities-button-visible');
        activities.container.visible = visible;
    }

    _restoreActivities() {
        const activities = Main.panel.statusArea?.activities;
        if (!activities) return;
        activities.container.visible = true;
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
                        try { dateMenu._updateClock(); } catch (_e) { /* */ }
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
        if (!dateMenu) return;

        if (this._origClockUpdate) {
            // Restore the original _updateClock method and trigger it
            dateMenu._updateClock = this._origClockUpdate;
            this._origClockUpdate = null;
            try { dateMenu._updateClock(); } catch (_e) { /* */ }
        } else {
            // _updateClock didn't exist originally (GNOME 45+ uses
            // bind_property); remove our override and refresh from WallClock
            delete dateMenu._updateClock;
            try {
                if (dateMenu._clock && dateMenu._clockDisplay)
                    dateMenu._clockDisplay.text = dateMenu._clock.clock;
            } catch (_e) { /* */ }
        }
    }

    // ── Panel icon spacing ────────────────────────────────────────────

    // ── Combined panel styles (spacing + icon color) ────────────────

    _applyPanelStyles() {
        this._restorePanelStyles();

        const spacing = this._int('panel-icon-spacing');
        const color = this._str('panel-icon-color');
        if (spacing < 0 && !color) return;

        const spacingCss = spacing >= 0
            ? `padding-left: ${spacing}px; padding-right: ${spacing}px;`
            : null;
        const colorCss = color
            ? `color: ${color} !important;`
            : null;

        // Parse hex color into a Cogl.Color for the ColorizeEffect
        let tintColor = null;
        if (color) {
            try {
                const hex = color.replace('#', '');
                const r = parseInt(hex.substring(0, 2), 16) / 255;
                const g = parseInt(hex.substring(2, 4), 16) / 255;
                const b = parseInt(hex.substring(4, 6), 16) / 255;
                if (!isNaN(r) && !isNaN(g) && !isNaN(b)) {
                    tintColor = new Cogl.Color();
                    tintColor.init_from_4f(r, g, b, 1.0);
                }
            } catch (_e) { /* color parse failed */ }
        }

        // Default to true if keys don't exist in the compiled schema yet
        let colorSymbolic = true, colorOther = true;
        try { colorSymbolic = this._settings.get_boolean('panel-color-symbolic'); }
        catch (_e) { /* key missing — default true */ }
        try { colorOther = this._settings.get_boolean('panel-color-other'); }
        catch (_e) { /* key missing — default true */ }

        // Build combined CSS for indicator containers (spacing + color)
        let containerCss = '';
        if (spacingCss) containerCss += spacingCss + ' ';
        if (colorCss && colorSymbolic) containerCss += colorCss;
        containerCss = containerCss.trim() || null;

        let colorActivities = true;
        try { colorActivities = this._settings.get_boolean('panel-color-activities'); }
        catch (_e) { /* key missing — default true */ }

        for (const box of [Main.panel._leftBox, Main.panel._centerBox, Main.panel._rightBox]) {
            for (const child of box.get_children()) {
                // Apply combined spacing + color to the container itself
                if (containerCss && typeof child.set_style === 'function') {
                    child.set_style(containerCss);
                    child.add_style_class_name('more-tweaks-panel-style');
                    this._styledChildren.push(child);
                }
                // Walk descendants for symbolic icon + label CSS coloring
                if (colorCss && colorSymbolic)
                    this._colorDescendants(child, colorCss);
                // For non-symbolic icons, apply ColorizeEffect directly to
                // each St.Icon (not the container).  This is more reliable
                // than effecting the container because St.Bin containers
                // can have zero allocation when the indicator is hidden.
                if (colorOther && tintColor)
                    this._colorizeNonSymbolicIcons(child, tintColor);
            }
        }

        // The Activities button / workspace indicator uses Clutter paint
        if (color && colorActivities && tintColor) {
            const activities = Main.panel.statusArea?.activities;
            if (activities) {
                try {
                    activities.add_effect_with_name('more-tweaks-colorize',
                        new Clutter.ColorizeEffect({tint: tintColor}));
                    this._styledChildren.push(activities);
                } catch (_e) { /* effect unavailable */ }
            }
        }
    }

    _isSymbolicIcon(actor) {
        if (!(actor instanceof St.Icon)) return false;
        const iconName = actor.icon_name ?? '';
        if (iconName.endsWith('-symbolic')) return true;
        // For GThemedIcon, check only the PRIMARY (first) name.
        // GThemedIcon auto-generates -symbolic fallback names, so
        // checking the full to_string() gives false positives.
        const gicon = actor.gicon;
        if (gicon) {
            try {
                const names = gicon.get_names?.();
                if (names && names.length > 0)
                    return names[0].endsWith('-symbolic');
            } catch (_e) { /* not a ThemedIcon */ }
        }
        return false;
    }

    _getActorChildren(actor) {
        // St.Bin exposes its child via .child property, not get_children().
        // PanelMenu.Button containers are St.Bin, so we must check both.
        const children = [];
        if (typeof actor.get_children === 'function')
            children.push(...actor.get_children());
        if (actor.child && !children.includes(actor.child))
            children.push(actor.child);
        return children;
    }

    _hasNonSymbolicIcon(actor) {
        if (actor instanceof St.Icon && !this._isSymbolicIcon(actor))
            return true;
        for (const child of this._getActorChildren(actor))
            if (this._hasNonSymbolicIcon(child)) return true;
        return false;
    }

    _colorizeNonSymbolicIcons(actor, tintColor) {
        if (actor instanceof St.Icon && !this._isSymbolicIcon(actor)) {
            try {
                try { actor.remove_effect_by_name('more-tweaks-colorize'); }
                catch (_e2) { /* no prior effect */ }
                actor.add_effect_with_name('more-tweaks-colorize',
                    new Clutter.ColorizeEffect({tint: tintColor}));
                this._styledChildren.push(actor);
            } catch (_e) { /* */ }
            return;
        }
        for (const child of this._getActorChildren(actor))
            this._colorizeNonSymbolicIcons(child, tintColor);
    }

    _colorDescendants(actor, css) {
        // Apply CSS color to symbolic icons, labels, and all other
        // St.Widget descendants.  Non-symbolic icons are handled by
        // ColorizeEffect at the container level in _applyPanelStyles.
        const already = typeof actor.has_style_class_name === 'function' &&
            actor.has_style_class_name('more-tweaks-panel-style');
        if (!already && typeof actor.set_style === 'function') {
            actor.set_style(css);
            actor.add_style_class_name('more-tweaks-panel-style');
            this._styledChildren.push(actor);
        }
        for (const child of this._getActorChildren(actor))
            this._colorDescendants(child, css);
    }

    _restorePanelStyles() {
        for (const child of this._styledChildren) {
            try { child.set_style(null); } catch (_e) { /* */ }
            try { child.remove_style_class_name('more-tweaks-panel-style'); } catch (_e) { /* */ }
            try { child.remove_effect_by_name('more-tweaks-colorize'); } catch (_e) { /* */ }
        }
        this._styledChildren = [];
    }

    // ── Orchestration ─────────────────────────────────────────────────

    _apply() {
        if (!this._bool('topbar-overrides-enabled')) {
            this._restoreActivities();
            this._restoreClock();
            this._restorePanelStyles();
            return;
        }
        this._applyActivities();
        this._applyClock();
        this._applyPanelStyles();
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
        // GNOME 47+ renamed Clutter signals from actor-added/removed to child-added/removed.
        const ver = getShellMajorVersion();
        const addSignal = ver >= 47 ? 'child-added' : 'actor-added';
        const removeSignal = ver >= 47 ? 'child-removed' : 'actor-removed';
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
        } catch (_e) {
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
