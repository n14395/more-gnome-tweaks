import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {AnimationController} from './runtime/controller.js';
import {GestureController} from './runtime/gesture-controller.js';

export default class MoreTweaksShellRuntime extends Extension {
    enable() {
        const settings = this.getSettings();
        this._controller = new AnimationController(settings);
        this._controller.enable();
        this._gestureController = new GestureController(settings);
        this._gestureController.enable();
    }

    disable() {
        this._gestureController?.disable();
        this._gestureController = null;
        this._controller?.disable();
        this._controller = null;
    }
}
