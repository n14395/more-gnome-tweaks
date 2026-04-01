import Clutter from 'gi://Clutter';

import {BaseEffect} from './base-effect.js';
import {clamp, getActorCenter, getIconTarget, resetActor} from './utils.js';


export class DockFunnelEffect extends BaseEffect {
    constructor() {
        super('dock-funnel');
    }

    run(actor, config) {
        const target = getIconTarget(actor);
        const center = getActorCenter(actor);
        const dx = target.x - center.x;
        const dy = target.y - center.y;
        const intensity = config.intensity ?? 1.0;
        const opening = Boolean(config.opening);
        const duration = config.duration;
        const delay = config.delay;

        resetActor(actor);
        actor.set_pivot_point(0.5, 0.5);
        actor.show();

        if (opening) {
            actor.opacity = 0;
            actor.scale_x = 0.12;
            actor.scale_y = 0.04;
            actor.translation_x = dx;
            actor.translation_y = dy;
            actor.rotation_angle_z = 10 * intensity;
            actor.ease({
                opacity: 255,
                scale_x: 1.02,
                scale_y: 1.02,
                translation_x: 0,
                translation_y: 0,
                rotation_angle_z: 0,
                duration: Math.max(1, Math.round(duration * 0.78)),
                delay,
                mode: Clutter.AnimationMode.EASE_OUT_CUBIC,
                onComplete: () => actor.ease({
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: Math.max(1, Math.round(duration * 0.22)),
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    onComplete: () => {
                        resetActor(actor);
                        config.onComplete?.();
                    },
                }),
            });
            return;
        }

        actor.ease({
            opacity: 0,
            scale_x: 0.12,
            scale_y: 0.04,
            translation_x: dx,
            translation_y: dy,
            rotation_angle_z: 12 * intensity,
            duration,
            delay,
            mode: Clutter.AnimationMode.EASE_IN_CUBIC,
            onComplete: () => {
                resetActor(actor);
                config.onComplete?.();
            },
        });
    }
}

export class MagicLampEffect extends BaseEffect {
    constructor() {
        super('magic-lamp');
    }

    run(actor, config) {
        const target = getIconTarget(actor);
        const center = getActorCenter(actor);
        const dx = target.x - center.x;
        const dy = target.y - center.y;
        const intensity = clamp(config.intensity ?? 1.0, 0.25, 2.0);
        const opening = Boolean(config.opening);
        const duration = config.duration;
        const delay = config.delay;
        const stretchX = Math.abs(dx) > Math.abs(dy);

        resetActor(actor);
        actor.show();
        actor.set_pivot_point(0.5, 0.5);

        if (opening) {
            actor.opacity = 0;
            actor.translation_x = dx;
            actor.translation_y = dy;
            actor.scale_x = stretchX ? 0.05 : 0.18;
            actor.scale_y = stretchX ? 0.16 : 0.04;
            actor.rotation_angle_z = stretchX ? 8 * intensity : 12 * intensity;
            actor.ease({
                opacity: 255,
                translation_x: dx * 0.16,
                translation_y: dy * 0.16,
                scale_x: 1.04,
                scale_y: 0.92,
                rotation_angle_z: 0,
                duration: Math.max(1, Math.round(duration * 0.72)),
                delay,
                mode: Clutter.AnimationMode.EASE_OUT_CUBIC,
                onComplete: () => actor.ease({
                    translation_x: 0,
                    translation_y: 0,
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: Math.max(1, Math.round(duration * 0.28)),
                    mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                    onComplete: () => {
                        resetActor(actor);
                        config.onComplete?.();
                    },
                }),
            });
            return;
        }

        actor.ease({
            opacity: 110,
            translation_x: dx * 0.14,
            translation_y: dy * 0.14,
            scale_x: 1.06,
            scale_y: 0.9,
            duration: Math.max(1, Math.round(duration * 0.34)),
            delay,
            mode: Clutter.AnimationMode.EASE_IN_CUBIC,
            onComplete: () => actor.ease({
                opacity: 0,
                translation_x: dx,
                translation_y: dy,
                scale_x: stretchX ? 0.05 : 0.18,
                scale_y: stretchX ? 0.16 : 0.04,
                rotation_angle_z: stretchX ? 10 * intensity : 14 * intensity,
                duration: Math.max(1, Math.round(duration * 0.66)),
                mode: Clutter.AnimationMode.EASE_IN_CUBIC,
                onComplete: () => {
                    resetActor(actor);
                    config.onComplete?.();
                },
            }),
        });
    }
}
