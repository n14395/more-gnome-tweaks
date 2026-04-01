import Clutter from 'gi://Clutter';

import {BaseEffect} from './base-effect.js';
import {resetActor} from './utils.js';


export class ShaderPulseEffect extends BaseEffect {
    constructor() {
        super('shader-pulse');
    }

    run(actor, config) {
        const intensity = config.intensity ?? 1.0;
        const duration = config.duration;
        const opening = Boolean(config.opening);

        resetActor(actor);
        actor.set_pivot_point(0.5, 0.5);
        actor.show();

        if (opening) {
            actor.opacity = 0;
            actor.scale_x = 0.93;
            actor.scale_y = 0.93;
            actor.ease({
                opacity: 255,
                scale_x: 1.02 + 0.01 * intensity,
                scale_y: 1.02 + 0.01 * intensity,
                duration: Math.max(1, Math.round(duration * 0.7)),
                delay: config.delay,
                mode: Clutter.AnimationMode.EASE_OUT_CUBIC,
                onComplete: () => actor.ease({
                    scale_x: 1.0,
                    scale_y: 1.0,
                    duration: Math.max(1, Math.round(duration * 0.3)),
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
            scale_x: 0.88,
            scale_y: 0.88,
            duration,
            delay: config.delay,
            mode: Clutter.AnimationMode.EASE_IN_CUBIC,
            onComplete: () => {
                resetActor(actor);
                config.onComplete?.();
            },
        });
    }
}
