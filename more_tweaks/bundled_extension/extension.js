import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {AnimationController} from './runtime/controller.js';
import {GestureController} from './runtime/gesture-controller.js';
import {getShellMajorVersion} from './runtime/utils.js';

export default class MoreTweaksShellRuntime extends Extension {
    enable() {
        const settings = this.getSettings();
        this._settings = settings;
        const capabilities = {};

        // Report detected GNOME Shell version
        const shellVersion = getShellMajorVersion();
        try { settings.set_string('detected-shell-version', String(shellVersion)); }
        catch (_e) { /* key may not exist in older schema */ }

        // Animation controller (window/dialog/notification animations,
        // system timings, top bar, tiling, panel layout)
        try {
            this._controller = new AnimationController(settings);
            this._controller.enable(capabilities);
        } catch (e) {
            console.error(`[More Tweaks] AnimationController failed: ${e}`);
            this._controller = null;
            capabilities.animations ??= false;
        }

        // Gesture controller
        try {
            this._gestureController = new GestureController(settings);
            this._gestureController.enable();
            capabilities.gestures = true;
        } catch (e) {
            console.error(`[More Tweaks] GestureController failed: ${e}`);
            this._gestureController = null;
            capabilities.gestures = false;
        }

        // Write final capabilities
        try { settings.set_string('active-capabilities', JSON.stringify(capabilities)); }
        catch (_e) { /* key may not exist */ }
    }

    disable() {
        try { this._gestureController?.disable(); } catch (_e) {}
        this._gestureController = null;

        try { this._controller?.disable(); } catch (_e) {}
        this._controller = null;

        // Clear capabilities and version on disable
        if (this._settings) {
            try { this._settings.set_string('active-capabilities', ''); } catch (_e) {}
            try { this._settings.set_string('detected-shell-version', ''); } catch (_e) {}
        }
        this._settings = null;
    }
}
