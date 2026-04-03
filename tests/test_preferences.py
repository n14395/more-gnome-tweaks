from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_prefs(tmp_path):
    prefs_dir = tmp_path / "more-tweaks"
    prefs_file = prefs_dir / "preferences.json"
    with (
        patch("more_tweaks.preferences._CONFIG_DIR", prefs_dir),
        patch("more_tweaks.preferences._PREFS_FILE", prefs_file),
    ):
        from more_tweaks.preferences import Preferences
        prefs = Preferences()
        yield prefs, prefs_file


class TestPreferences:
    def test_defaults(self, tmp_prefs):
        prefs, _ = tmp_prefs
        assert prefs.hide_unavailable is False
        assert prefs.show_command_hints is True
        assert prefs.confirm_individual_reset is False
        assert prefs.default_export_dir == ""
        assert prefs.startup_category == "last"

    def test_set_and_get(self, tmp_prefs):
        prefs, _ = tmp_prefs
        prefs.set("hide_unavailable", True)
        assert prefs.hide_unavailable is True

    def test_persistence(self, tmp_prefs):
        prefs, prefs_file = tmp_prefs
        prefs.set("show_command_hints", False)
        prefs.set("default_export_dir", "/tmp/exports")

        assert prefs_file.exists()
        saved = json.loads(prefs_file.read_text())
        assert saved["show_command_hints"] is False
        assert saved["default_export_dir"] == "/tmp/exports"

        # Reload from file
        with (
            patch("more_tweaks.preferences._CONFIG_DIR", prefs_file.parent),
            patch("more_tweaks.preferences._PREFS_FILE", prefs_file),
        ):
            from more_tweaks.preferences import Preferences
            prefs2 = Preferences()
            assert prefs2.show_command_hints is False
            assert prefs2.default_export_dir == "/tmp/exports"

    def test_set_noop_no_callback(self, tmp_prefs):
        prefs, _ = tmp_prefs
        calls = []
        prefs.connect_changed(calls.append)
        prefs.set("hide_unavailable", False)  # same as default
        assert calls == []

    def test_callback_fires_on_change(self, tmp_prefs):
        prefs, _ = tmp_prefs
        calls = []
        prefs.connect_changed(calls.append)
        prefs.set("hide_unavailable", True)
        assert calls == ["hide_unavailable"]

    def test_ignores_wrong_type_on_load(self, tmp_prefs):
        _, prefs_file = tmp_prefs
        prefs_file.parent.mkdir(parents=True, exist_ok=True)
        prefs_file.write_text(json.dumps({
            "hide_unavailable": "not a bool",
            "show_command_hints": 42,
            "startup_category": "appearance",
        }))
        with (
            patch("more_tweaks.preferences._CONFIG_DIR", prefs_file.parent),
            patch("more_tweaks.preferences._PREFS_FILE", prefs_file),
        ):
            from more_tweaks.preferences import Preferences
            prefs = Preferences()
            # Wrong types ignored, keep defaults
            assert prefs.hide_unavailable is False
            assert prefs.show_command_hints is True
            # Correct type loaded
            assert prefs.startup_category == "appearance"

    def test_corrupt_file_uses_defaults(self, tmp_prefs):
        _, prefs_file = tmp_prefs
        prefs_file.parent.mkdir(parents=True, exist_ok=True)
        prefs_file.write_text("not valid json{{{")
        with (
            patch("more_tweaks.preferences._CONFIG_DIR", prefs_file.parent),
            patch("more_tweaks.preferences._PREFS_FILE", prefs_file),
        ):
            from more_tweaks.preferences import Preferences
            prefs = Preferences()
            assert prefs.hide_unavailable is False
            assert prefs.startup_category == "last"
