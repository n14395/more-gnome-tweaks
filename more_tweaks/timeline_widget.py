"""Horizontal timeline bar showing animation phases, delay, and duration."""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango, PangoCairo

from .preset_data import TRANSFORM_PRESETS, TransformPreset

TIMELINE_HEIGHT = 48
PHASE_COLORS = (
    (0.35, 0.65, 0.95),
    (0.55, 0.80, 0.50),
    (0.95, 0.70, 0.35),
    (0.85, 0.45, 0.55),
)


def _rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class AnimationTimelineWidget(Gtk.DrawingArea):
    """Draws a horizontal bar chart of animation phases."""

    def __init__(self):
        super().__init__()
        self.set_content_height(TIMELINE_HEIGHT)
        self.set_content_width(320)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

        self._preset: TransformPreset | None = None
        self._preset_name: str = ""
        self._duration_ms: int = 0
        self._delay_ms: int = 0

    def update(self, preset_name: str, duration_ms: int, delay_ms: int, intensity: float):
        self._preset_name = preset_name
        self._preset = TRANSFORM_PRESETS.get(preset_name)
        self._duration_ms = duration_ms
        self._delay_ms = delay_ms
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        bar_h = 22
        bar_y = 4
        label_y = bar_y + bar_h + 4

        if self._preset is None:
            # Non-transform preset placeholder
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.4)
            _rounded_rect(cr, 0, bar_y, width, bar_h, 4)
            cr.fill()
            self._draw_label(cr, width / 2, bar_y + bar_h / 2, "Runtime effect", center=True)
            return

        total = self._delay_ms + self._duration_ms
        if total <= 0:
            return

        x = 0.0

        # Delay segment (hatched gray)
        if self._delay_ms > 0:
            delay_w = (self._delay_ms / total) * width
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.25)
            _rounded_rect(cr, x, bar_y, delay_w, bar_h, 4)
            cr.fill()

            # Hatch pattern
            cr.save()
            cr.rectangle(x, bar_y, delay_w, bar_h)
            cr.clip()
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.15)
            cr.set_line_width(1)
            for i in range(0, int(delay_w + bar_h) + 8, 6):
                cr.move_to(x + i, bar_y)
                cr.line_to(x + i - bar_h, bar_y + bar_h)
                cr.stroke()
            cr.restore()

            self._draw_label(cr, x + delay_w / 2, label_y, f"delay {self._delay_ms}ms", center=True)
            x += delay_w

        # Phase segments
        remaining_w = width - x
        phases = self._preset.phases
        for i, phase in enumerate(phases):
            phase_w = phase.duration_scale * remaining_w
            if phase_w < 1:
                continue
            color = PHASE_COLORS[i % len(PHASE_COLORS)]

            cr.set_source_rgba(*color, 0.7)
            _rounded_rect(cr, x, bar_y, phase_w, bar_h, 4)
            cr.fill()

            # Border
            cr.set_source_rgba(*color, 1.0)
            _rounded_rect(cr, x, bar_y, phase_w, bar_h, 4)
            cr.set_line_width(1)
            cr.stroke()

            # Phase label
            phase_ms = max(1, round(self._duration_ms * phase.duration_scale))
            easing_short = phase.mode.replace("EASE_", "").replace("_", " ").title()
            label = f"{easing_short} {phase_ms}ms"
            if phase_w > 60:
                self._draw_label(cr, x + phase_w / 2, label_y, label, center=True)

            x += phase_w

        # Total label
        total_label = f"Total: {total}ms"
        self._draw_label(cr, width, label_y, total_label, center=False, right_align=True)

    def _draw_label(self, cr, x, y, text, center=False, right_align=False):
        layout = PangoCairo.create_layout(cr)
        layout.set_text(text, -1)
        desc = Pango.FontDescription.from_string("Sans 7")
        layout.set_font_description(desc)
        _, logical = layout.get_pixel_extents()

        tx = x
        if center:
            tx = x - logical.width / 2
        elif right_align:
            tx = x - logical.width

        cr.set_source_rgba(0.7, 0.7, 0.7, 0.9)
        cr.move_to(tx, y)
        PangoCairo.show_layout(cr, layout)
