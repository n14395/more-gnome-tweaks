/**
 * GestureController — intercepts and remaps touchpad swipe gestures.
 *
 * GNOME Shell hardcodes:
 *   • 3-finger vertical  → Activities overview  (SwipeTracker in OverviewControls)
 *   • 4-finger horizontal → workspace switch     (SwipeTracker in WorkspaceAnimation)
 *
 * Directions that GNOME does NOT handle by default:
 *   • 3-finger horizontal
 *   • 4-finger vertical
 *
 * This controller wraps the two existing SwipeTracker gesture handlers so
 * they can be suppressed or remapped, and installs a standalone stage
 * handler that captures the four "unowned" directions for custom actions.
 */

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import * as SystemActions from 'resource:///org/gnome/shell/misc/systemActions.js';

// ── action identifiers (must match GSettings string values) ───────────
const ACT_DEFAULT           = 'default';
const ACT_DISABLED          = 'disabled';
const ACT_OVERVIEW          = 'overview';
const ACT_APP_GRID          = 'app-grid';
const ACT_SHOW_DESKTOP      = 'show-desktop';
const ACT_NOTIFICATION      = 'notification-center';
const ACT_QUICK_SETTINGS    = 'quick-settings';
const ACT_WORKSPACE_LEFT    = 'workspace-left';
const ACT_WORKSPACE_RIGHT   = 'workspace-right';
const ACT_SCREENSHOT        = 'screenshot';
const ACT_LOCK_SCREEN       = 'lock-screen';
const ACT_RUN_DIALOG        = 'run-dialog';
const ACT_WINDOW_SWITCHER   = 'window-switcher';

// Minimum cumulative px before we commit to a direction.
const DIR_THRESHOLD = 30;

export class GestureController {
    constructor(settings) {
        this._settings = settings;
        this._overviewPatch  = null;
        this._workspacePatch = null;
        this._freeStageId    = 0;      // handler for "unowned" directions
        this._settingsId     = 0;
        // Per-physical-gesture tracking.
        this._active   = null;          // for wrapped gestures (3fV / 4fH)
        this._free     = null;          // for free gestures (3fH / 4fV)
        this._minimizedWindows = [];    // for "show desktop" undo
    }

    // ── lifecycle ──────────────────────────────────────────────────────

    enable() {
        if (!this._hasKey('gesture-overrides-enabled'))
            return;
        if (this._settings.get_boolean('gesture-overrides-enabled'))
            this._applyAll();

        this._settingsId = this._settings.connect('changed', (_s, key) => {
            if (key.startsWith('gesture-'))
                this._reapply();
        });
    }

    disable() {
        if (this._settingsId) {
            this._settings.disconnect(this._settingsId);
            this._settingsId = 0;
        }
        this._removeAll();
    }

    // ── helpers ────────────────────────────────────────────────────────

    _hasKey(name) {
        try { this._settings.get_boolean(name); return true; }
        catch (_e) { return false; }
    }

    _str(key) {
        try { return this._settings.get_string(key); }
        catch (_e) { return ACT_DEFAULT; }
    }

    _reapply() {
        this._removeAll();
        if (this._hasKey('gesture-overrides-enabled') &&
            this._settings.get_boolean('gesture-overrides-enabled'))
            this._applyAll();
    }

    // ── patch management ──────────────────────────────────────────────

    _applyAll() {
        try { this._patchOverview(); } catch (e) {
            console.warn(`[More Tweaks] Overview gesture patch failed: ${e}`);
        }
        try { this._patchWorkspace(); } catch (e) {
            console.warn(`[More Tweaks] Workspace gesture patch failed: ${e}`);
        }
        try { this._installFreeHandler(); } catch (e) {
            console.warn(`[More Tweaks] Free gesture handler failed: ${e}`);
        }
    }

    _removeAll() {
        this._restorePatch(this._overviewPatch);
        this._overviewPatch = null;
        this._restorePatch(this._workspacePatch);
        this._workspacePatch = null;
        if (this._freeStageId) {
            global.stage.disconnect(this._freeStageId);
            this._freeStageId = 0;
        }
    }

    _wrapGesture(gesture, filterFn) {
        if (!gesture?._stageCaptureEvent)
            return null;
        const origBound = gesture._handleEvent.bind(gesture);
        global.stage.disconnect(gesture._stageCaptureEvent);
        const newId = global.stage.connect(
            'captured-event::touchpad',
            (actor, event) => filterFn(actor, event, origBound),
        );
        gesture._stageCaptureEvent = newId;
        return { gesture, origBound, newId };
    }

    _restorePatch(patch) {
        if (!patch) return;
        try { global.stage.disconnect(patch.newId); } catch (_e) {}
        patch.gesture._stageCaptureEvent = global.stage.connect(
            'captured-event::touchpad',
            patch.gesture._handleEvent.bind(patch.gesture),
        );
    }

    // ── action dispatch ───────────────────────────────────────────────

    _dispatch(action) {
        try { this._dispatchInner(action); }
        catch (e) { console.warn(`[More Tweaks] Gesture dispatch '${action}' failed: ${e}`); }
    }

    _dispatchInner(action) {
        switch (action) {
        case ACT_OVERVIEW:
            if (Main.overview.visible)
                Main.overview.hide();
            else
                Main.overview.show();
            break;

        case ACT_APP_GRID:
            if (Main.overview.visible && Main.overview.dash?.showAppsButton?.checked)
                Main.overview.hide();
            else
                Main.overview.showApps();
            break;

        case ACT_SHOW_DESKTOP: {
            const ws = global.workspace_manager.get_active_workspace();
            const wins = ws.list_windows().filter(
                w => !w.minimized && w.window_type === Meta.WindowType.NORMAL);
            if (wins.length > 0) {
                this._minimizedWindows = wins;
                for (const w of wins) w.minimize();
            } else {
                // Restore previously minimized windows
                for (const w of this._minimizedWindows) {
                    if (w.minimized) w.unminimize();
                }
                this._minimizedWindows = [];
            }
            break;
        }

        case ACT_NOTIFICATION:
            // Toggle the calendar / notification panel
            if (Main.panel.statusArea?.dateMenu)
                Main.panel.statusArea.dateMenu._clockDisplay.emit('button-press-event',
                    Clutter.get_current_event() ?? new Clutter.Event());
            // Fallback: try the message tray directly
            else if (Main.messageTray)
                Main.messageTray.toggle();
            break;

        case ACT_QUICK_SETTINGS:
            if (Main.panel.statusArea?.quickSettings)
                Main.panel.statusArea.quickSettings.menu.toggle();
            break;

        case ACT_WORKSPACE_LEFT: {
            const idx = global.workspace_manager.get_active_workspace_index();
            if (idx > 0)
                global.workspace_manager.get_workspace_by_index(idx - 1)
                    .activate(global.get_current_time());
            break;
        }

        case ACT_WORKSPACE_RIGHT: {
            const idx = global.workspace_manager.get_active_workspace_index();
            const n = global.workspace_manager.get_n_workspaces();
            if (idx < n - 1)
                global.workspace_manager.get_workspace_by_index(idx + 1)
                    .activate(global.get_current_time());
            break;
        }

        case ACT_SCREENSHOT:
            Main.screenshotUI?.open().catch(() => {});
            break;

        case ACT_LOCK_SCREEN:
            SystemActions.getDefault().activateLockScreen();
            break;

        case ACT_RUN_DIALOG:
            Main.openRunDialog();
            break;

        case ACT_WINDOW_SWITCHER:
            // Simulate Alt+Tab
            Main.wm._startSwitcher(
                Shell.ActionMode.NORMAL,
                global.display, null,
                Meta.KeyBindingAction.SWITCH_APPLICATIONS);
            break;
        }
    }

    // ── classify direction ────────────────────────────────────────────

    _dir(dx, dy) {
        if (Math.abs(dx) > Math.abs(dy))
            return dx < 0 ? 'left' : 'right';
        return dy < 0 ? 'up' : 'down';
    }

    // ── overview wrapper (3-finger vertical — GNOME default) ──────────

    _patchOverview() {
        const gesture = Main.overview
            ?._overview?._controls?._swipeTracker?._touchpadGesture;
        if (!gesture) return;
        this._overviewPatch = this._wrapGesture(gesture,
            (a, e, orig) => this._filterOverview(a, e, orig));
    }

    _filterOverview(actor, event, origHandler) {
        if (event.type() !== Clutter.EventType.TOUCHPAD_SWIPE)
            return origHandler(actor, event);

        const phase = event.get_gesture_phase();

        if (phase === Clutter.TouchpadGesturePhase.BEGIN) {
            this._active = { dx: 0, dy: 0, decided: false, suppress: false, action: null };
            return origHandler(actor, event);
        }
        if (!this._active)
            return origHandler(actor, event);

        if (phase === Clutter.TouchpadGesturePhase.UPDATE) {
            const [dx, dy] = event.get_gesture_motion_delta();
            this._active.dx += dx;
            this._active.dy += dy;

            if (!this._active.decided && Math.abs(this._active.dy) > DIR_THRESHOLD) {
                const dir = this._active.dy < 0 ? 'up' : 'down';
                const action = this._str(`gesture-3f-swipe-${dir}`);
                this._active.decided = true;
                this._active.action = action;
                this._active.dir = dir;

                if (action === ACT_DISABLED || (action !== ACT_DEFAULT && action !== ACT_OVERVIEW)) {
                    this._active.suppress = true;
                    return Clutter.EVENT_STOP;
                }
            }
            return this._active.suppress
                ? Clutter.EVENT_STOP
                : origHandler(actor, event);
        }

        if (phase === Clutter.TouchpadGesturePhase.END ||
            phase === Clutter.TouchpadGesturePhase.CANCEL) {
            const st = this._active;
            this._active = null;
            if (st?.suppress) {
                if (phase === Clutter.TouchpadGesturePhase.END &&
                    st.action !== ACT_DISABLED)
                    this._dispatch(st.action);
                return Clutter.EVENT_STOP;
            }
            // For app-grid: let overview gesture finish, then switch view
            if (st?.action === ACT_APP_GRID && st.dir === 'up' &&
                phase === Clutter.TouchpadGesturePhase.END) {
                const result = origHandler(actor, event);
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, () => {
                    if (Main.overview.visible)
                        Main.overview.showApps();
                    return GLib.SOURCE_REMOVE;
                });
                return result;
            }
            return origHandler(actor, event);
        }

        return origHandler(actor, event);
    }

    // ── workspace wrapper (4-finger horizontal — GNOME default) ───────

    _patchWorkspace() {
        const gesture = Main.wm
            ?._workspaceAnimation?._swipeTracker?._touchpadGesture;
        if (!gesture) return;
        this._workspacePatch = this._wrapGesture(gesture,
            (a, e, orig) => this._filterWorkspace(a, e, orig));
    }

    _filterWorkspace(actor, event, origHandler) {
        if (event.type() !== Clutter.EventType.TOUCHPAD_SWIPE)
            return origHandler(actor, event);

        const phase = event.get_gesture_phase();

        if (phase === Clutter.TouchpadGesturePhase.BEGIN) {
            this._active = { dx: 0, dy: 0, decided: false, suppress: false, action: null };
            return origHandler(actor, event);
        }
        if (!this._active)
            return origHandler(actor, event);

        if (phase === Clutter.TouchpadGesturePhase.UPDATE) {
            const [dx, dy] = event.get_gesture_motion_delta();
            this._active.dx += dx;
            this._active.dy += dy;

            if (!this._active.decided && Math.abs(this._active.dx) > DIR_THRESHOLD) {
                const dir = this._active.dx < 0 ? 'left' : 'right';
                const action = this._str(`gesture-4f-swipe-${dir}`);
                this._active.decided = true;
                this._active.action = action;

                if (action === ACT_DISABLED ||
                    (action !== ACT_DEFAULT && action !== ACT_WORKSPACE_LEFT && action !== ACT_WORKSPACE_RIGHT)) {
                    this._active.suppress = true;
                    return Clutter.EVENT_STOP;
                }
            }
            return this._active.suppress
                ? Clutter.EVENT_STOP
                : origHandler(actor, event);
        }

        if (phase === Clutter.TouchpadGesturePhase.END ||
            phase === Clutter.TouchpadGesturePhase.CANCEL) {
            const st = this._active;
            this._active = null;
            if (st?.suppress) {
                if (phase === Clutter.TouchpadGesturePhase.END &&
                    st.action !== ACT_DISABLED)
                    this._dispatch(st.action);
                return Clutter.EVENT_STOP;
            }
            return origHandler(actor, event);
        }

        return origHandler(actor, event);
    }

    // ── free handler (3-finger H + 4-finger V — no GNOME default) ────

    _installFreeHandler() {
        this._freeStageId = global.stage.connect(
            'captured-event::touchpad',
            this._onFreeGesture.bind(this),
        );
    }

    _onFreeGesture(_actor, event) {
        if (event.type() !== Clutter.EventType.TOUCHPAD_SWIPE)
            return Clutter.EVENT_PROPAGATE;

        const nFingers = event.get_touchpad_gesture_finger_count();
        const phase = event.get_gesture_phase();

        // Only handle the "unowned" combos: 3-finger horizontal, 4-finger vertical.
        const is3fH = nFingers === 3;   // we care about left/right
        const is4fV = nFingers === 4;   // we care about up/down
        if (!is3fH && !is4fV)
            return Clutter.EVENT_PROPAGATE;

        if (phase === Clutter.TouchpadGesturePhase.BEGIN) {
            this._free = { dx: 0, dy: 0, decided: false, claimed: false, action: null };
            return Clutter.EVENT_PROPAGATE;   // let other handlers see BEGIN
        }

        if (!this._free)
            return Clutter.EVENT_PROPAGATE;

        if (phase === Clutter.TouchpadGesturePhase.UPDATE) {
            const [dx, dy] = event.get_gesture_motion_delta();
            this._free.dx += dx;
            this._free.dy += dy;

            if (!this._free.decided) {
                const adx = Math.abs(this._free.dx);
                const ady = Math.abs(this._free.dy);
                const total = Math.max(adx, ady);
                if (total < DIR_THRESHOLD)
                    return Clutter.EVENT_PROPAGATE;

                const dir = this._dir(this._free.dx, this._free.dy);

                // Only claim directions that are "ours":
                //   3-finger left/right   and   4-finger up/down
                const ours = (is3fH && (dir === 'left' || dir === 'right')) ||
                             (is4fV && (dir === 'up' || dir === 'down'));
                if (!ours) {
                    // Vertical 3f or horizontal 4f → belongs to existing handlers
                    this._free.decided = true;
                    this._free.claimed = false;
                    return Clutter.EVENT_PROPAGATE;
                }

                const key = `gesture-${nFingers}f-swipe-${dir}`;
                const action = this._str(key);
                this._free.decided = true;
                this._free.action = action;

                if (action === ACT_DISABLED || action === ACT_DEFAULT) {
                    this._free.claimed = false;
                    return Clutter.EVENT_PROPAGATE;
                }

                this._free.claimed = true;
                return Clutter.EVENT_STOP;
            }

            return this._free.claimed ? Clutter.EVENT_STOP : Clutter.EVENT_PROPAGATE;
        }

        if (phase === Clutter.TouchpadGesturePhase.END ||
            phase === Clutter.TouchpadGesturePhase.CANCEL) {
            const st = this._free;
            this._free = null;

            if (st?.claimed) {
                if (phase === Clutter.TouchpadGesturePhase.END &&
                    st.action && st.action !== ACT_DISABLED)
                    this._dispatch(st.action);
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        }

        return Clutter.EVENT_PROPAGATE;
    }
}
