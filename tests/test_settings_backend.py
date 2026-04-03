from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from more_tweaks.models import Choice, Tweak


def _make_variant(value, type_string="s"):
    v = MagicMock()
    v.unpack.return_value = value
    v.get_type_string.return_value = type_string
    v.equal = lambda other: other.unpack() == value
    return v


def _make_tweak(**overrides):
    defaults = dict(
        id="test", name="Test", summary="S", description="D",
        category="desktop", schema="org.gnome.desktop.interface",
        key="enable-animations", value_type="boolean", control="boolean",
    )
    defaults.update(overrides)
    return Tweak(**defaults)


@pytest.fixture
def mock_gi():
    """Patch Gio so we can import SettingsBackend without a display."""
    mock_schema = MagicMock()
    mock_schema.has_key.return_value = True

    mock_source = MagicMock()
    mock_source.lookup.return_value = mock_schema

    mock_settings = MagicMock()
    mock_settings.get_value.return_value = _make_variant(True, "b")
    mock_settings.get_default_value.return_value = _make_variant(True, "b")
    mock_settings.set_value.return_value = True
    mock_settings.connect.return_value = 1

    with (
        patch("more_tweaks.settings_backend.Gio.SettingsSchemaSource.get_default", return_value=mock_source),
        patch("more_tweaks.settings_backend.Gio.Settings.new_full", return_value=mock_settings),
    ):
        from more_tweaks.settings_backend import SettingsBackend
        backend = SettingsBackend()
        yield backend, mock_settings, mock_schema, mock_source


class TestIsAvailable:
    def test_available(self, mock_gi):
        backend, _, mock_schema, _ = mock_gi
        mock_schema.has_key.return_value = True
        tweak = _make_tweak()
        assert backend.is_available(tweak) is True

    def test_unavailable_key(self, mock_gi):
        backend, _, mock_schema, _ = mock_gi
        mock_schema.has_key.return_value = False
        tweak = _make_tweak()
        assert backend.is_available(tweak) is False

    def test_unavailable_schema(self, mock_gi):
        backend, _, _, mock_source = mock_gi
        mock_source.lookup.return_value = None
        backend._schemas.clear()
        tweak = _make_tweak(schema="org.nonexistent.Schema")
        assert backend.is_available(tweak) is False


class TestRead:
    def test_read_boolean(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        mock_settings.get_value.return_value = _make_variant(True, "b")
        tweak = _make_tweak()
        assert backend.read(tweak) is True

    def test_read_unavailable_returns_none(self, mock_gi):
        backend, _, mock_schema, _ = mock_gi
        mock_schema.has_key.return_value = False
        tweak = _make_tweak()
        assert backend.read(tweak) is None

    def test_read_feature_toggle(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        mock_settings.get_value.return_value = _make_variant(
            ["scale-monitor-framebuffer"], "as"
        )
        tweak = _make_tweak(
            control="feature-toggle",
            value_type="string",
            choices=(Choice(value="scale-monitor-framebuffer", label="Scale"),),
        )
        assert backend.read(tweak) is True

    def test_read_keybinding(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        mock_settings.get_value.return_value = _make_variant(["<Super>e"], "as")
        tweak = _make_tweak(control="keybinding", value_type="string")
        assert backend.read(tweak) == "<Super>e"


class TestWrite:
    def test_write_boolean(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        tweak = _make_tweak()
        assert backend.write(tweak, False) is True
        mock_settings.set_value.assert_called()

    def test_write_unavailable(self, mock_gi):
        backend, _, mock_schema, _ = mock_gi
        mock_schema.has_key.return_value = False
        tweak = _make_tweak()
        assert backend.write(tweak, True) is False


class TestReset:
    def test_reset(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        tweak = _make_tweak()
        assert backend.reset(tweak) is True
        mock_settings.reset.assert_called_once_with("enable-animations")

    def test_reset_unavailable(self, mock_gi):
        backend, _, mock_schema, _ = mock_gi
        mock_schema.has_key.return_value = False
        tweak = _make_tweak()
        assert backend.reset(tweak) is False


class TestIsDefault:
    def test_default_when_equal(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        val = _make_variant(True, "b")
        mock_settings.get_value.return_value = val
        mock_settings.get_default_value.return_value = val
        tweak = _make_tweak()
        assert backend.is_default(tweak) is True

    def test_not_default_when_different(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        mock_settings.get_value.return_value = _make_variant(False, "b")
        mock_settings.get_default_value.return_value = _make_variant(True, "b")
        tweak = _make_tweak()
        assert backend.is_default(tweak) is False


class TestChangeCallbacks:
    def test_callback_fires(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        received = []
        backend.connect_change_callback(lambda s, k: received.append((s, k)))

        # Force _get_settings to be called, which connects the signal
        tweak = _make_tweak()
        backend.read(tweak)

        # Simulate Gio.Settings firing 'changed' signal
        connect_calls = mock_settings.connect.call_args_list
        fired = False
        for call in connect_calls:
            args = call[0]
            if args[0] == "changed":
                handler = args[1]
                schema = args[2]
                handler(mock_settings, "some-key", schema)
                fired = True
                break

        assert fired, "No 'changed' signal handler was connected"
        assert len(received) == 1
        assert received[0][1] == "some-key"

    def test_suppression(self, mock_gi):
        backend, mock_settings, _, _ = mock_gi
        received = []
        backend.connect_change_callback(lambda s, k: received.append((s, k)))

        tweak = _make_tweak()
        backend.write(tweak, False)

        # Simulate the signal that write would trigger
        connect_calls = mock_settings.connect.call_args_list
        for call in connect_calls:
            args = call[0]
            if args[0] == "changed":
                handler = args[1]
                schema = args[2]
                handler(mock_settings, "enable-animations", schema)
                break

        assert len(received) == 0

    def test_disconnect_callback(self, mock_gi):
        backend, _, _, _ = mock_gi
        received = []
        cb = lambda s, k: received.append((s, k))
        backend.connect_change_callback(cb)
        backend.disconnect_change_callback(cb)
        assert len(backend._change_callbacks) == 0
