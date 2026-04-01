import {BaseEffect} from './base-effect.js';
import {animationMode, clamp, resetActor} from './utils.js';


function scaled(value, intensity) {
    return value * clamp(intensity, 0.25, 2.0);
}

function buildSetup(setup, intensity) {
    return {
        opacity: setup.opacity ?? 255,
        scale_x: setup.scaleX ?? 1.0,
        scale_y: setup.scaleY ?? 1.0,
        translation_x: scaled(setup.translationX ?? 0, intensity),
        translation_y: scaled(setup.translationY ?? 0, intensity),
        translation_z: scaled(setup.translationZ ?? 0, intensity),
        rotation_angle_x: scaled(setup.rotationX ?? 0, intensity),
        rotation_angle_y: scaled(setup.rotationY ?? 0, intensity),
        rotation_angle_z: scaled(setup.rotationZ ?? 0, intensity),
        pivot_x: setup.pivotX ?? 0.5,
        pivot_y: setup.pivotY ?? 0.5,
    };
}

function buildPhase(phase, intensity, duration, delay, onComplete) {
    const result = {
        opacity: phase.opacity,
        scale_x: phase.scaleX,
        scale_y: phase.scaleY,
        translation_x: phase.translationX === undefined ? undefined : scaled(phase.translationX, intensity),
        translation_y: phase.translationY === undefined ? undefined : scaled(phase.translationY, intensity),
        translation_z: phase.translationZ === undefined ? undefined : scaled(phase.translationZ, intensity),
        rotation_angle_x: phase.rotationX === undefined ? undefined : scaled(phase.rotationX, intensity),
        rotation_angle_y: phase.rotationY === undefined ? undefined : scaled(phase.rotationY, intensity),
        rotation_angle_z: phase.rotationZ === undefined ? undefined : scaled(phase.rotationZ, intensity),
        duration: Math.max(1, Math.round(duration * (phase.durationScale ?? 1))),
        delay,
        mode: animationMode(phase.mode),
        onComplete,
    };

    for (const [key, value] of Object.entries(result)) {
        if (value === undefined)
            delete result[key];
    }

    return result;
}

function runPhases(actor, phases, intensity, duration, delay, finalComplete) {
    const queue = [...phases];

    const next = () => {
        const phase = queue.shift();
        if (!phase) {
            finalComplete();
            return;
        }

        actor.ease(buildPhase(phase, intensity, duration, 0, () => next()));
    };

    const first = queue.shift();
    if (!first) {
        finalComplete();
        return;
    }

    actor.ease(buildPhase(first, intensity, duration, delay, () => next()));
}

export class TransformEffect extends BaseEffect {
    constructor(name) {
        super(name);
    }

    run(actor, config) {
        const intensity = config.intensity ?? 1.0;
        const setup = buildSetup(config.setup ?? {}, intensity);
        resetActor(actor);
        actor.set_pivot_point(setup.pivot_x, setup.pivot_y);
        actor.opacity = setup.opacity;
        actor.scale_x = setup.scale_x;
        actor.scale_y = setup.scale_y;
        actor.translation_x = setup.translation_x;
        actor.translation_y = setup.translation_y;
        actor.translation_z = setup.translation_z;
        actor.rotation_angle_x = setup.rotation_angle_x;
        actor.rotation_angle_y = setup.rotation_angle_y;
        actor.rotation_angle_z = setup.rotation_angle_z;
        actor.show();

        runPhases(
            actor,
            config.phases ?? [],
            intensity,
            config.duration,
            config.delay,
            () => {
                resetActor(actor);
                config.onComplete?.();
            },
        );
    }
}
