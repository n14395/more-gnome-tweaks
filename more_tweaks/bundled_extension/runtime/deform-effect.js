import Clutter from 'gi://Clutter';

import {BaseEffect} from './base-effect.js';
import {clamp, getActorCenter, getIconTarget, resetActor} from './utils.js';


function animMode(name) {
    return Clutter.AnimationMode[name] ?? Clutter.AnimationMode.EASE_OUT_CUBIC;
}


// --- Deform configs ---

export const DOCK_FUNNEL_CONFIG = {
    intensityClamp: null,
    opening: {
        setup: ctx => ({
            opacity: 0,
            scale_x: 0.12,
            scale_y: 0.04,
            translation_x: ctx.dx,
            translation_y: ctx.dy,
            rotation_angle_z: 10 * ctx.intensity,
        }),
        phases: [
            {
                durationScale: 0.78,
                mode: 'EASE_OUT_CUBIC',
                values: () => ({
                    opacity: 255,
                    scale_x: 1.02,
                    scale_y: 1.02,
                    translation_x: 0,
                    translation_y: 0,
                    rotation_angle_z: 0,
                }),
            },
            {
                durationScale: 0.22,
                mode: 'EASE_OUT_QUAD',
                values: () => ({
                    scale_x: 1.0,
                    scale_y: 1.0,
                }),
            },
        ],
    },
    closing: {
        setup: null,
        phases: [
            {
                durationScale: 1.0,
                mode: 'EASE_IN_CUBIC',
                values: ctx => ({
                    opacity: 0,
                    scale_x: 0.12,
                    scale_y: 0.04,
                    translation_x: ctx.dx,
                    translation_y: ctx.dy,
                    rotation_angle_z: 12 * ctx.intensity,
                }),
            },
        ],
    },
};

export const MAGIC_LAMP_CONFIG = {
    intensityClamp: [0.25, 2.0],
    opening: {
        setup: ctx => ({
            opacity: 0,
            translation_x: ctx.dx,
            translation_y: ctx.dy,
            scale_x: ctx.stretchX ? 0.05 : 0.18,
            scale_y: ctx.stretchX ? 0.16 : 0.04,
            rotation_angle_z: (ctx.stretchX ? 8 : 12) * ctx.intensity,
        }),
        phases: [
            {
                durationScale: 0.72,
                mode: 'EASE_OUT_CUBIC',
                values: ctx => ({
                    opacity: 255,
                    translation_x: ctx.dx * 0.16,
                    translation_y: ctx.dy * 0.16,
                    scale_x: 1.04,
                    scale_y: 0.92,
                    rotation_angle_z: 0,
                }),
            },
            {
                durationScale: 0.28,
                mode: 'EASE_OUT_QUAD',
                values: () => ({
                    translation_x: 0,
                    translation_y: 0,
                    scale_x: 1.0,
                    scale_y: 1.0,
                }),
            },
        ],
    },
    closing: {
        setup: null,
        phases: [
            {
                durationScale: 0.34,
                mode: 'EASE_IN_CUBIC',
                values: ctx => ({
                    opacity: 110,
                    translation_x: ctx.dx * 0.14,
                    translation_y: ctx.dy * 0.14,
                    scale_x: 1.06,
                    scale_y: 0.9,
                }),
            },
            {
                durationScale: 0.66,
                mode: 'EASE_IN_CUBIC',
                values: ctx => ({
                    opacity: 0,
                    translation_x: ctx.dx,
                    translation_y: ctx.dy,
                    scale_x: ctx.stretchX ? 0.05 : 0.18,
                    scale_y: ctx.stretchX ? 0.16 : 0.04,
                    rotation_angle_z: (ctx.stretchX ? 10 : 14) * ctx.intensity,
                }),
            },
        ],
    },
};


// --- Generic deform effect ---

export class DeformEffect extends BaseEffect {
    constructor(name, deformConfig) {
        super(name);
        this._deformConfig = deformConfig;
    }

    run(actor, config) {
        const target = getIconTarget(actor);
        const center = getActorCenter(actor);
        const dx = target.x - center.x;
        const dy = target.y - center.y;
        const clampRange = this._deformConfig.intensityClamp;
        const intensity = clampRange
            ? clamp(config.intensity ?? 1.0, clampRange[0], clampRange[1])
            : (config.intensity ?? 1.0);
        const opening = Boolean(config.opening);
        const stretchX = Math.abs(dx) > Math.abs(dy);
        const ctx = {dx, dy, intensity, stretchX};

        resetActor(actor);
        actor.set_pivot_point(0.5, 0.5);
        actor.show();

        const direction = opening
            ? this._deformConfig.opening
            : this._deformConfig.closing;

        if (direction.setup) {
            const setupValues = direction.setup(ctx);
            for (const [key, value] of Object.entries(setupValues))
                actor[key] = value;
        }

        this._runPhases(actor, direction.phases, ctx, config.duration, config.delay, () => {
            if (!config.skipFinalReset)
                resetActor(actor);
            config.onComplete?.();
        });
    }

    _runPhases(actor, phases, ctx, duration, delay, onComplete) {
        const queue = [...phases];

        const next = () => {
            const phase = queue.shift();
            if (!phase) {
                onComplete();
                return;
            }
            actor.ease({
                ...phase.values(ctx),
                duration: Math.max(1, Math.round(duration * phase.durationScale)),
                mode: animMode(phase.mode),
                onComplete: () => next(),
            });
        };

        const first = queue.shift();
        if (!first) {
            onComplete();
            return;
        }
        actor.ease({
            ...first.values(ctx),
            duration: Math.max(1, Math.round(duration * first.durationScale)),
            delay,
            mode: animMode(first.mode),
            onComplete: () => next(),
        });
    }
}
