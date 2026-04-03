from __future__ import annotations

from more_tweaks.animation_catalog import BINDING_DEFINITIONS
from more_tweaks.preset_data import (
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
        known = set(TRANSFORM_PRESETS.keys())
        for name in _all_preset_names():
            assert name in known, (
                f"Preset {name!r} referenced in BINDING_DEFINITIONS but not in TRANSFORM_PRESETS"
            )

    def test_no_extra_presets(self):
        referenced = _all_preset_names()
        # Some presets exist only as preview approximations for runtime-only effects
        preview_only = {"Glass Ripple In", "Glass Ripple Out"}
        for name in TRANSFORM_PRESETS:
            if name in preview_only:
                continue
            assert name in referenced, (
                f"TRANSFORM_PRESETS contains {name!r} which is not referenced by any binding"
            )

    def test_preset_count(self):
        assert len(TRANSFORM_PRESETS) == 65, (
            f"Expected 65 presets, got {len(TRANSFORM_PRESETS)}"
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

    def test_duration_scale_positive(self):
        for name, preset in TRANSFORM_PRESETS.items():
            for i, phase in enumerate(preset.phases):
                assert phase.duration_scale > 0, (
                    f"Preset {name!r} phase {i}: duration_scale must be positive"
                )

    def test_opacity_range(self):
        for name, preset in TRANSFORM_PRESETS.items():
            assert 0 <= preset.setup.opacity <= 255, (
                f"Preset {name!r}: setup.opacity={preset.setup.opacity} out of range 0-255"
            )
            for i, phase in enumerate(preset.phases):
                if phase.opacity is not None:
                    assert 0 <= phase.opacity <= 255, (
                        f"Preset {name!r} phase {i}: opacity={phase.opacity} out of range 0-255"
                    )

    def test_scale_positive(self):
        for name, preset in TRANSFORM_PRESETS.items():
            assert preset.setup.scale_x > 0, f"Preset {name!r}: setup.scale_x must be positive"
            assert preset.setup.scale_y > 0, f"Preset {name!r}: setup.scale_y must be positive"
            for i, phase in enumerate(preset.phases):
                if phase.scale_x is not None:
                    assert phase.scale_x > 0, f"Preset {name!r} phase {i}: scale_x must be positive"
                if phase.scale_y is not None:
                    assert phase.scale_y > 0, f"Preset {name!r} phase {i}: scale_y must be positive"

    def test_pivot_range(self):
        for name, preset in TRANSFORM_PRESETS.items():
            assert 0.0 <= preset.setup.pivot_x <= 1.0, (
                f"Preset {name!r}: pivot_x={preset.setup.pivot_x} out of range 0-1"
            )
            assert 0.0 <= preset.setup.pivot_y <= 1.0, (
                f"Preset {name!r}: pivot_y={preset.setup.pivot_y} out of range 0-1"
            )


PHYSICS_PRESETS = [
    "Jelly Grab", "Wobbly Drop", "Rubber Stretch", "Spring Snap",
    "Snap Wobble", "Release Wobble",
]


class TestPhysicsPresets:
    def test_all_physics_presets_exist(self):
        for name in PHYSICS_PRESETS:
            assert name in TRANSFORM_PRESETS, f"Physics preset {name!r} missing from TRANSFORM_PRESETS"

    def test_physics_presets_have_multiple_phases(self):
        for name in PHYSICS_PRESETS:
            preset = TRANSFORM_PRESETS[name]
            assert len(preset.phases) >= 3, (
                f"Physics preset {name!r} has {len(preset.phases)} phases, expected >= 3 for spring oscillation"
            )

    def test_physics_presets_settle_to_neutral(self):
        """Final phase of each physics preset should return to neutral scale."""
        for name in PHYSICS_PRESETS:
            preset = TRANSFORM_PRESETS[name]
            last = preset.phases[-1]
            if last.scale_x is not None:
                assert last.scale_x == 1.0, f"Physics preset {name!r} final phase scale_x != 1.0"
            if last.scale_y is not None:
                assert last.scale_y == 1.0, f"Physics preset {name!r} final phase scale_y != 1.0"
            if last.rotation_z is not None:
                assert last.rotation_z == 0.0, f"Physics preset {name!r} final phase rotation_z != 0"
