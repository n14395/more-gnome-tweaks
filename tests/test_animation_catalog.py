from __future__ import annotations

from more_tweaks.animation_catalog import (
    BINDING_DEFINITIONS,
    GROUP_DEFINITIONS,
    GROUPS_BY_ID,
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


