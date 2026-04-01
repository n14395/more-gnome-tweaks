"""In-app animation preview widget using Adw.TimedAnimation + Cairo."""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk

from .preset_data import PresetPhase, PresetSetup, TransformPreset

EASING_MAP: dict[str, Adw.Easing] = {
    "EASE_OUT_CUBIC": Adw.Easing.EASE_OUT_CUBIC,
    "EASE_IN_CUBIC": Adw.Easing.EASE_IN_CUBIC,
    "EASE_OUT_QUAD": Adw.Easing.EASE_OUT_QUAD,
    "EASE_IN_QUAD": Adw.Easing.EASE_IN_QUAD,
    "EASE_OUT_BOUNCE": Adw.Easing.EASE_OUT_BOUNCE,
    "LINEAR": Adw.Easing.LINEAR,
}

PREVIEW_W = 200
PREVIEW_H = 150
MOCK_W = 140
MOCK_H = 100
TITLEBAR_H = 12


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _scaled(value: float, intensity: float) -> float:
    return value * _clamp(intensity, 0.25, 2.0)


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class AnimationPreviewWidget(Gtk.Box):
    """Plays a transform preset animation on a mock window rectangle."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_margin_top(8)
        self.set_margin_bottom(8)
        self.set_margin_start(8)
        self.set_margin_end(8)

        self._area = Gtk.DrawingArea()
        self._area.set_content_width(PREVIEW_W)
        self._area.set_content_height(PREVIEW_H)
        self._area.set_draw_func(self._draw)
        self.append(self._area)

        replay_btn = Gtk.Button(label="Replay")
        replay_btn.add_css_class("pill")
        replay_btn.set_halign(Gtk.Align.CENTER)
        replay_btn.connect("clicked", self._on_replay)
        self.append(replay_btn)

        # Animation state
        self._opacity = 1.0
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._translate_x = 0.0
        self._translate_y = 0.0
        self._rotation_z = 0.0
        self._rotation_y = 0.0

        self._animations: list[Adw.TimedAnimation] = []
        self._preset: TransformPreset | None = None
        self._duration_ms = 0
        self._delay_ms = 0
        self._intensity = 1.0

    def set_visible_during_wait(self, visible: bool):
        """Set whether the mock window is shown before play() is called."""
        if not visible:
            self._opacity = 0.0
            self._area.queue_draw()

    def play(self, preset: TransformPreset, duration_ms: int, delay_ms: int, intensity: float):
        self._preset = preset
        self._duration_ms = duration_ms
        self._delay_ms = delay_ms
        self._intensity = intensity
        self._stop_all()
        self._apply_setup(preset.setup, intensity)
        self._area.queue_draw()

        if preset.phases:
            GLib.timeout_add(max(delay_ms, 1), self._start_phases)

    def _on_replay(self, _btn):
        if self._preset is not None:
            self.play(self._preset, self._duration_ms, self._delay_ms, self._intensity)

    def _stop_all(self):
        for anim in self._animations:
            anim.skip()
        self._animations.clear()

    def _apply_setup(self, setup: PresetSetup, intensity: float):
        self._opacity = setup.opacity / 255.0
        self._scale_x = setup.scale_x
        self._scale_y = setup.scale_y
        self._translate_x = _scaled(setup.translation_x, intensity)
        self._translate_y = _scaled(setup.translation_y, intensity)
        self._rotation_z = _scaled(setup.rotation_z, intensity)
        self._rotation_y = _scaled(setup.rotation_y, intensity)

    def _start_phases(self):
        if self._preset is None:
            return False
        self._run_phase_chain(list(self._preset.phases), 0)
        return False  # one-shot timeout

    def _run_phase_chain(self, phases: list[PresetPhase], index: int):
        if index >= len(phases):
            return

        phase = phases[index]
        intensity = self._intensity
        duration = max(1, round(self._duration_ms * phase.duration_scale))

        # Snapshot start values
        start_opacity = self._opacity
        start_sx = self._scale_x
        start_sy = self._scale_y
        start_tx = self._translate_x
        start_ty = self._translate_y
        start_rz = self._rotation_z
        start_ry = self._rotation_y

        # Compute target values (None means "don't change")
        target_opacity = phase.opacity / 255.0 if phase.opacity is not None else None
        target_sx = phase.scale_x if phase.scale_x is not None else None
        target_sy = phase.scale_y if phase.scale_y is not None else None
        target_tx = _scaled(phase.translation_x, intensity) if phase.translation_x is not None else None
        target_ty = _scaled(phase.translation_y, intensity) if phase.translation_y is not None else None
        target_rz = _scaled(phase.rotation_z, intensity) if phase.rotation_z is not None else None
        target_ry = _scaled(phase.rotation_y, intensity) if phase.rotation_y is not None else None

        easing = EASING_MAP.get(phase.mode, Adw.Easing.EASE_OUT_CUBIC)

        target = Adw.CallbackAnimationTarget.new(
            lambda t: self._on_tick(
                t,
                start_opacity, target_opacity,
                start_sx, target_sx,
                start_sy, target_sy,
                start_tx, target_tx,
                start_ty, target_ty,
                start_rz, target_rz,
                start_ry, target_ry,
            )
        )

        anim = Adw.TimedAnimation.new(self._area, 0.0, 1.0, duration, target)
        anim.set_easing(easing)
        anim.connect("done", lambda _a: self._run_phase_chain(phases, index + 1))
        self._animations.append(anim)
        anim.play()

    def _on_tick(self, t, s_op, t_op, s_sx, t_sx, s_sy, t_sy, s_tx, t_tx, s_ty, t_ty, s_rz, t_rz, s_ry, t_ry):
        if t_op is not None:
            self._opacity = _lerp(s_op, t_op, t)
        if t_sx is not None:
            self._scale_x = _lerp(s_sx, t_sx, t)
        if t_sy is not None:
            self._scale_y = _lerp(s_sy, t_sy, t)
        if t_tx is not None:
            self._translate_x = _lerp(s_tx, t_tx, t)
        if t_ty is not None:
            self._translate_y = _lerp(s_ty, t_ty, t)
        if t_rz is not None:
            self._rotation_z = _lerp(s_rz, t_rz, t)
        if t_ry is not None:
            self._rotation_y = _lerp(s_ry, t_ry, t)
        self._area.queue_draw()

    def _draw(self, _area, cr, width, height):
        # Background
        cr.set_source_rgba(0.12, 0.12, 0.14, 1.0)
        cr.paint()

        # Mock window centered
        cx = width / 2
        cy = height / 2
        half_w = MOCK_W / 2
        half_h = MOCK_H / 2

        cr.save()
        cr.translate(cx + self._translate_x, cy + self._translate_y)
        cr.rotate(math.radians(self._rotation_z))
        cr.scale(self._scale_x, self._scale_y)

        # Titlebar
        cr.set_source_rgba(0.35, 0.55, 0.80, self._opacity)
        _rounded_rect(cr, -half_w, -half_h, MOCK_W, TITLEBAR_H, 4)
        cr.fill()

        # Body
        cr.set_source_rgba(0.22, 0.24, 0.28, self._opacity)
        cr.rectangle(-half_w, -half_h + TITLEBAR_H, MOCK_W, MOCK_H - TITLEBAR_H)
        cr.fill()

        # Bottom corners
        _rounded_rect(cr, -half_w, -half_h, MOCK_W, MOCK_H, 4)
        cr.set_source_rgba(0.35, 0.55, 0.80, self._opacity * 0.3)
        cr.set_line_width(1.0)
        cr.stroke()

        cr.restore()
