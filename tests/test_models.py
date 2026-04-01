from __future__ import annotations

import dataclasses

import pytest

from more_tweaks.models import Category, Choice, Tweak


class TestChoice:
    def test_creation(self):
        c = Choice(value="dark", label="Dark")
        assert c.value == "dark"
        assert c.label == "Dark"

    def test_frozen(self):
        c = Choice(value="x", label="X")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.value = "y"  # type: ignore[misc]


class TestCategory:
    def test_creation(self):
        cat = Category(id="desktop", name="Desktop", description="Desc", icon_name="icon")
        assert cat.id == "desktop"
        assert cat.name == "Desktop"
        assert cat.description == "Desc"
        assert cat.icon_name == "icon"

    def test_frozen(self):
        cat = Category(id="a", name="A", description="", icon_name="")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cat.id = "b"  # type: ignore[misc]


class TestTweak:
    def test_creation(self):
        t = Tweak(
            id="test-tweak",
            name="Test Tweak",
            summary="A test",
            description="A test tweak",
            category="desktop",
            schema="org.gnome.desktop.interface",
            key="enable-animations",
            value_type="boolean",
            control="boolean",
        )
        assert t.id == "test-tweak"
        assert t.name == "Test Tweak"
        assert t.value_type == "boolean"
        assert t.control == "boolean"

    def test_defaults(self):
        t = Tweak(
            id="t", name="T", summary="S", description="D",
            category="c", schema="s", key="k",
            value_type="string", control="text",
        )
        assert t.tags == ()
        assert t.choices == ()
        assert t.min_value is None
        assert t.max_value is None
        assert t.step is None
        assert t.command_hint is None

    def test_frozen(self):
        t = Tweak(
            id="t", name="T", summary="S", description="D",
            category="c", schema="s", key="k",
            value_type="string", control="text",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.id = "x"  # type: ignore[misc]

    def test_with_choices(self):
        choices = (Choice(value="a", label="A"), Choice(value="b", label="B"))
        t = Tweak(
            id="t", name="T", summary="S", description="D",
            category="c", schema="s", key="k",
            value_type="string", control="choice",
            choices=choices,
        )
        assert len(t.choices) == 2
        assert t.choices[0].value == "a"

    def test_with_range(self):
        t = Tweak(
            id="t", name="T", summary="S", description="D",
            category="c", schema="s", key="k",
            value_type="int", control="number",
            min_value=0, max_value=100, step=1,
        )
        assert t.min_value == 0
        assert t.max_value == 100
        assert t.step == 1
