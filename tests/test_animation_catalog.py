from __future__ import annotations

from more_tweaks.animation_catalog import (
    BINDING_DEFINITIONS,
    GROUP_DEFINITIONS,
    GROUPS_BY_ID,
    PROFILE_DEFAULTS,
    PROFILE_NAMES,
)


class TestGroupDefinitions:
    def test_no_duplicate_ids(self):
        ids = [g.id for g in GROUP_DEFINITIONS]
        assert len(ids) == len(set(ids))

    def test_required_fields(self):
        for g in GROUP_DEFINITIONS:
            assert g.id
            assert g.title
            assert g.summary


class TestBindingDefinitions:
    def test_no_duplicate_ids(self):
        ids = [b.id for b in BINDING_DEFINITIONS]
        assert len(ids) == len(set(ids))

    def test_valid_group_references(self):
        for b in BINDING_DEFINITIONS:
            assert b.group_id in GROUPS_BY_ID, (
                f"Binding {b.id} references unknown group {b.group_id!r}"
            )

    def test_default_preset_in_preset_names(self):
        for b in BINDING_DEFINITIONS:
            if b.preset_names:
                assert b.default_preset in b.preset_names, (
                    f"Binding {b.id}: default_preset {b.default_preset!r} "
                    f"not in preset_names"
                )

    def test_required_fields(self):
        for b in BINDING_DEFINITIONS:
            assert b.id
            assert b.title
            assert b.summary
            assert b.target
            assert b.action
            assert b.default_preset
            assert b.default_duration_ms > 0

    def test_computed_keys(self):
        b = BINDING_DEFINITIONS[0]
        assert b.enabled_key == f"{b.id}-enabled"
        assert b.preset_key == f"{b.id}-preset"
        assert b.duration_key == f"{b.id}-duration-ms"
        assert b.delay_key == f"{b.id}-delay-ms"
        assert b.intensity_key == f"{b.id}-intensity"

    def test_valid_tier(self):
        for b in BINDING_DEFINITIONS:
            assert b.tier in {"core", "advanced"}, (
                f"Binding {b.id} has invalid tier {b.tier!r}"
            )


class TestProfiles:
    def test_all_profiles_present(self):
        for name in PROFILE_NAMES:
            assert name in PROFILE_DEFAULTS, (
                f"Profile {name!r} missing from PROFILE_DEFAULTS"
            )

    def test_profile_names_non_empty(self):
        assert len(PROFILE_NAMES) > 0

    def test_profile_presets_reference_valid_names(self):
        binding_by_id = {b.id: b for b in BINDING_DEFINITIONS}
        for profile_name, defaults in PROFILE_DEFAULTS.items():
            for key, value in defaults.items():
                if key.endswith("-preset"):
                    binding_id = key.removesuffix("-preset")
                    if binding_id in binding_by_id:
                        b = binding_by_id[binding_id]
                        if b.preset_names:
                            assert value in b.preset_names, (
                                f"Profile {profile_name!r}, key {key!r}: "
                                f"preset {value!r} not in {b.id} preset_names"
                            )

    def test_profile_keys_reference_valid_bindings(self):
        binding_ids = {b.id for b in BINDING_DEFINITIONS}
        known_suffixes = ("-enabled", "-preset", "-duration-ms", "-delay-ms", "-intensity")
        for profile_name, defaults in PROFILE_DEFAULTS.items():
            for key in defaults:
                matched = False
                for suffix in known_suffixes:
                    if key.endswith(suffix):
                        binding_id = key.removesuffix(suffix)
                        assert binding_id in binding_ids, (
                            f"Profile {profile_name!r}, key {key!r}: "
                            f"unknown binding {binding_id!r}"
                        )
                        matched = True
                        break
                assert matched, (
                    f"Profile {profile_name!r}: unrecognized key format {key!r}"
                )
