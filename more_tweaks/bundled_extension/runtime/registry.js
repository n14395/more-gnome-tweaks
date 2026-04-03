import GLib from 'gi://GLib';

import {
    BINDINGS,
    PRESETS,
    transformEffect,
} from './catalog.js';


const BINDINGS_BY_ID = new Map(BINDINGS.map(binding => [binding.id, binding]));

let _customPresets = {};

export function loadCustomPresets() {
    const path = GLib.build_filenamev([GLib.get_home_dir(), '.config', 'more-tweaks', 'custom-presets.json']);
    try {
        const [ok, data] = GLib.file_get_contents(path);
        if (ok) {
            const parsed = JSON.parse(new TextDecoder().decode(data));
            _customPresets = {};
            for (const [name, preset] of Object.entries(parsed.presets ?? {})) {
                _customPresets[name] = {
                    ...preset,
                    effect: transformEffect,
                };
            }
        }
    } catch (_error) {
        _customPresets = {};
    }
}

export {PRESETS, BINDINGS};

export function getBinding(prefix) {
    const binding = BINDINGS_BY_ID.get(prefix);
    if (!binding) {
        return {
            enabledKey: `${prefix}-enabled`,
            presetKey: `${prefix}-preset`,
            durationKey: `${prefix}-duration-ms`,
            delayKey: `${prefix}-delay-ms`,
            intensityKey: `${prefix}-intensity`,
            defaultPreset: 'Glide In',
            defaultDuration: 220,
            defaultDelay: 0,
            defaultIntensity: 1.0,
        };
    }

    return {
        enabledKey: `${prefix}-enabled`,
        presetKey: `${prefix}-preset`,
        durationKey: `${prefix}-duration-ms`,
        delayKey: `${prefix}-delay-ms`,
        intensityKey: `${prefix}-intensity`,
        defaultPreset: binding.defaultPreset,
        defaultDuration: binding.defaultDuration,
        defaultDelay: binding.defaultDelay,
        defaultIntensity: binding.defaultIntensity,
        target: binding.target,
        action: binding.action,
        tier: binding.tier,
    };
}

const _QUALITY_SCALES = {
    performance: {duration: 0.7, intensity: 0.7},
    balanced:    {duration: 1.0, intensity: 1.0},
    spectacle:   {duration: 1.2, intensity: 1.15},
};

export function getAnimationConfig(settings, binding) {
    const presetName = settings.get_string(binding.presetKey);
    const fallbackPreset = binding.defaultPreset ?? 'Glide In';
    const preset = _customPresets[presetName] ?? PRESETS[presetName] ?? PRESETS[fallbackPreset] ?? PRESETS['Glide In'];
    const reducedMotion = settings.get_boolean('reduced-motion-mode');
    const quality = _QUALITY_SCALES[settings.get_string('effects-quality')] ?? _QUALITY_SCALES.balanced;
    const duration = settings.get_int(binding.durationKey);
    const intensity = settings.get_double(binding.intensityKey);
    const reducedPresetName = preset.reducedMotionPreset ?? null;
    const effectivePreset = reducedMotion && reducedPresetName && PRESETS[reducedPresetName]
        ? PRESETS[reducedPresetName]
        : preset;

    let finalDuration = Math.round(duration * quality.duration);
    let finalIntensity = intensity * quality.intensity;

    if (reducedMotion) {
        finalDuration = Math.max(90, Math.round(finalDuration * 0.72));
        finalIntensity = Math.max(0.25, finalIntensity * 0.6);
    }

    return {
        ...effectivePreset,
        duration: finalDuration,
        delay: settings.get_int(binding.delayKey),
        intensity: finalIntensity,
        presetName,
    };
}

export function getWindowBinding(metaWindow, action, typeName) {
    const prefix = `${typeName ?? 'window'}-${action}`;
    return getBinding(prefix);
}

export function getNotificationBinding(action) {
    return getBinding(`notification-${action}`);
}
