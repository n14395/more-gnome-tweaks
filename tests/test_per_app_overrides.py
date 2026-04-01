from __future__ import annotations

import json

from more_tweaks.animation_catalog import PER_APP_ACTIONS


class TestPerAppActions:
    def test_actions_non_empty(self):
        assert len(PER_APP_ACTIONS) > 0

    def test_expected_actions(self):
        assert "open" in PER_APP_ACTIONS
        assert "close" in PER_APP_ACTIONS
        assert "minimize" in PER_APP_ACTIONS
        assert "focus" in PER_APP_ACTIONS

    def test_no_duplicates(self):
        assert len(PER_APP_ACTIONS) == len(set(PER_APP_ACTIONS))


class TestOverrideJsonFormat:
    def test_round_trip(self):
        overrides = [
            {
                "wm_class": "firefox",
                "match_mode": "exact",
                "rules": {
                    "open": {"preset": "Fade In", "duration_ms": 200, "enabled": True},
                    "close": {"preset": "Fade Out", "duration_ms": 150, "enabled": True},
                },
            },
            {
                "wm_class": "code",
                "match_mode": "contains",
                "rules": {
                    "open": {"preset": "Bloom In", "duration_ms": 300, "enabled": False},
                },
            },
        ]
        serialized = json.dumps(overrides)
        parsed = json.loads(serialized)
        assert len(parsed) == 2
        assert parsed[0]["wm_class"] == "firefox"
        assert parsed[0]["rules"]["open"]["preset"] == "Fade In"
        assert parsed[1]["match_mode"] == "contains"
        assert parsed[1]["rules"]["open"]["enabled"] is False

    def test_empty_overrides(self):
        assert json.loads(json.dumps([])) == []

    def test_rule_fields(self):
        rule = {"preset": "Glide In", "duration_ms": 240, "delay_ms": 0, "intensity": 1.0, "enabled": True}
        data = json.loads(json.dumps(rule))
        assert data["preset"] == "Glide In"
        assert data["duration_ms"] == 240
        assert data["enabled"] is True
