from __future__ import annotations

from more_tweaks.animation_catalog import BINDING_DEFINITIONS
from more_tweaks.preset_data import (
    NON_PREVIEWABLE_PRESETS,
    TRANSFORM_PRESETS,
    VALID_EASING_MODES,
)


def _all_preset_names() -> set[str]:
    names: set[str] = set()
    for b in BINDING_DEFINITIONS:
        names.update(b.preset_names)
    return names


class TestPresetCoverage:
    def test_all_catalog_presets_are_known(self):
        known = set(TRANSFORM_PRESETS.keys()) | NON_PREVIEWABLE_PRESETS
        for name in _all_preset_names():
            assert name in known, (
                f"Preset {name!r} referenced in BINDING_DEFINITIONS but not in "
                f"TRANSFORM_PRESETS or NON_PREVIEWABLE_PRESETS"
            )

    def test_no_extra_presets(self):
        referenced = _all_preset_names()
        for name in TRANSFORM_PRESETS:
            assert name in referenced, (
                f"TRANSFORM_PRESETS contains {name!r} which is not referenced by any binding"
            )


class TestPresetIntegrity:
    def test_valid_easing_modes(self):
        for name, preset in TRANSFORM_PRESETS.items():
            for i, phase in enumerate(preset.phases):
                assert phase.mode in VALID_EASING_MODES, (
                    f"Preset {name!r} phase {i}: invalid easing mode {phase.mode!r}"
                )

    def test_multi_phase_duration_scales_sum(self):
        for name, preset in TRANSFORM_PRESETS.items():
            if len(preset.phases) > 1:
                total = sum(p.duration_scale for p in preset.phases)
                assert abs(total - 1.0) < 0.05, (
                    f"Preset {name!r}: {len(preset.phases)} phases with "
                    f"duration_scale sum {total:.3f} (expected ~1.0)"
                )

    def test_single_phase_duration_scale(self):
        for name, preset in TRANSFORM_PRESETS.items():
            if len(preset.phases) == 1:
                assert preset.phases[0].duration_scale == 1.0, (
                    f"Preset {name!r}: single phase should have duration_scale=1.0"
                )

    def test_non_empty_phases(self):
        for name, preset in TRANSFORM_PRESETS.items():
            assert len(preset.phases) > 0, f"Preset {name!r} has no phases"

    def test_family_non_empty(self):
        for name, preset in TRANSFORM_PRESETS.items():
            assert preset.family, f"Preset {name!r} has empty family"
