"""Python mirror of the JS PRESETS from bundled_extension/runtime/catalog.js.

All preset families are included — deform and shader presets approximate
their runtime behaviour using the same transform properties.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PresetPhase:
    opacity: int | None = None
    scale_x: float | None = None
    scale_y: float | None = None
    translation_x: float | None = None
    translation_y: float | None = None
    rotation_z: float | None = None
    rotation_y: float | None = None
    duration_scale: float = 1.0
    mode: str = "EASE_OUT_CUBIC"


@dataclass(frozen=True, slots=True)
class PresetSetup:
    opacity: int = 255
    scale_x: float = 1.0
    scale_y: float = 1.0
    translation_x: float = 0.0
    translation_y: float = 0.0
    rotation_z: float = 0.0
    rotation_y: float = 0.0
    pivot_x: float = 0.5
    pivot_y: float = 0.5


@dataclass(frozen=True, slots=True)
class TransformPreset:
    family: str
    setup: PresetSetup
    phases: tuple[PresetPhase, ...]


# fmt: off

TRANSFORM_PRESETS: dict[str, TransformPreset] = {
    # ── Slide family ──────────────────────────────────────────────────
    "Glide In": TransformPreset("Slide",
        PresetSetup(opacity=0, scale_x=0.96, scale_y=0.92, translation_y=24.0, rotation_z=-1.5),
        (PresetPhase(opacity=255, scale_x=1.0, scale_y=1.0, translation_y=0.0, rotation_z=0.0, mode="EASE_OUT_CUBIC"),)),
    "Glide Out": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_x=1.04, scale_y=0.94, translation_y=24.0, rotation_z=1.5, mode="EASE_IN_CUBIC"),)),
    "Drift Up": TransformPreset("Slide",
        PresetSetup(opacity=0, translation_y=38.0, scale_x=0.98, scale_y=0.98),
        (PresetPhase(opacity=255, translation_y=0.0, scale_x=1.0, scale_y=1.0, mode="EASE_OUT_CUBIC"),)),
    "Drift Down": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, translation_y=38.0, scale_x=0.98, scale_y=0.98, mode="EASE_IN_CUBIC"),)),
    "Slide Left In": TransformPreset("Slide",
        PresetSetup(opacity=0, translation_x=44.0),
        (PresetPhase(opacity=255, translation_x=0.0, mode="EASE_OUT_CUBIC"),)),
    "Slide Right In": TransformPreset("Slide",
        PresetSetup(opacity=0, translation_x=-44.0),
        (PresetPhase(opacity=255, translation_x=0.0, mode="EASE_OUT_CUBIC"),)),
    "Slide Down In": TransformPreset("Slide",
        PresetSetup(opacity=0, translation_y=-42.0),
        (PresetPhase(opacity=255, translation_y=0.0, mode="EASE_OUT_CUBIC"),)),
    "Slide Left Out": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, translation_x=-44.0, mode="EASE_IN_CUBIC"),)),
    "Slide Right Out": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, translation_x=44.0, mode="EASE_IN_CUBIC"),)),
    "Slide Up Out": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, translation_y=-42.0, mode="EASE_IN_CUBIC"),)),
    "Compressed Slide Up": TransformPreset("Slide",
        PresetSetup(opacity=0, scale_y=0.82, translation_y=52.0),
        (PresetPhase(opacity=255, scale_y=1.04, translation_y=0.0, mode="EASE_OUT_CUBIC", duration_scale=0.76),
         PresetPhase(scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.24))),
    "Compressed Slide Down": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_y=0.82, translation_y=50.0, mode="EASE_IN_CUBIC"),)),
    "Squeezed Slide Left": TransformPreset("Slide",
        PresetSetup(opacity=0, scale_x=0.78, translation_x=62.0),
        (PresetPhase(opacity=255, scale_x=1.0, translation_x=0.0, mode="EASE_OUT_CUBIC"),)),
    "Squeezed Slide Right": TransformPreset("Slide",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_x=0.78, translation_x=62.0, mode="EASE_IN_CUBIC"),)),

    # ── Fade family ───────────────────────────────────────────────────
    "Fade In": TransformPreset("Fade",
        PresetSetup(opacity=0),
        (PresetPhase(opacity=255, mode="EASE_OUT_CUBIC"),)),
    "Fade Out": TransformPreset("Fade",
        PresetSetup(),
        (PresetPhase(opacity=0, mode="EASE_IN_CUBIC"),)),

    # ── Pop family ────────────────────────────────────────────────────
    "Bloom In": TransformPreset("Pop",
        PresetSetup(opacity=0, scale_x=0.88, scale_y=0.88, translation_y=18.0),
        (PresetPhase(opacity=255, scale_x=1.03, scale_y=1.03, translation_y=0.0, mode="EASE_OUT_CUBIC", duration_scale=0.82),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.18))),
    "Soft Pop": TransformPreset("Pop",
        PresetSetup(opacity=0, scale_x=0.92, scale_y=0.92),
        (PresetPhase(opacity=255, scale_x=1.02, scale_y=1.02, mode="EASE_OUT_CUBIC", duration_scale=0.68),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.32))),

    # ── Zoom family ───────────────────────────────────────────────────
    "Zoom In": TransformPreset("Zoom",
        PresetSetup(opacity=0, scale_x=0.86, scale_y=0.86),
        (PresetPhase(opacity=255, scale_x=1.02, scale_y=1.02, mode="EASE_OUT_CUBIC", duration_scale=0.7),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.3))),
    "Zoom Out": TransformPreset("Zoom",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_x=0.82, scale_y=0.82, mode="EASE_IN_CUBIC"),)),

    # ── Rotate family ─────────────────────────────────────────────────
    "Rotate In Left": TransformPreset("Rotate",
        PresetSetup(opacity=0, rotation_z=-18.0, translation_x=24.0, scale_x=0.94, scale_y=0.94),
        (PresetPhase(opacity=255, rotation_z=0.0, translation_x=0.0, scale_x=1.0, scale_y=1.0, mode="EASE_OUT_CUBIC"),)),
    "Rotate In Down": TransformPreset("Rotate",
        PresetSetup(opacity=0, rotation_z=-16.0, translation_y=-18.0, scale_x=0.94, scale_y=0.94),
        (PresetPhase(opacity=255, rotation_z=0.0, translation_y=0.0, scale_x=1.0, scale_y=1.0, mode="EASE_OUT_CUBIC"),)),
    "Rotate Out Left": TransformPreset("Rotate",
        PresetSetup(),
        (PresetPhase(opacity=0, rotation_z=-16.0, translation_x=-20.0, scale_x=0.94, scale_y=0.94, mode="EASE_IN_CUBIC"),)),
    "Rotate Out Up": TransformPreset("Rotate",
        PresetSetup(),
        (PresetPhase(opacity=0, rotation_z=16.0, translation_y=-20.0, scale_x=0.94, scale_y=0.94, mode="EASE_IN_CUBIC"),)),

    # ── Flip family ───────────────────────────────────────────────────
    "Flip In Horizontal": TransformPreset("Flip",
        PresetSetup(opacity=0, rotation_y=80.0, scale_x=0.96, scale_y=0.96),
        (PresetPhase(opacity=255, rotation_y=0.0, scale_x=1.0, scale_y=1.0, mode="EASE_OUT_CUBIC"),)),
    "Flip Out Horizontal": TransformPreset("Flip",
        PresetSetup(),
        (PresetPhase(opacity=0, rotation_y=-80.0, scale_x=0.96, scale_y=0.96, mode="EASE_IN_CUBIC"),)),

    # ── Fold family ───────────────────────────────────────────────────
    "Shutter Out": TransformPreset("Fold",
        PresetSetup(pivot_y=0.5),
        (PresetPhase(opacity=0, scale_x=0.98, scale_y=0.08, translation_y=6.0, mode="EASE_IN_CUBIC"),)),
    "Fold In Vertical": TransformPreset("Fold",
        PresetSetup(opacity=0, pivot_y=0.0, scale_y=0.18),
        (PresetPhase(opacity=255, scale_y=1.0, mode="EASE_OUT_CUBIC"),)),
    "Fold Out Vertical": TransformPreset("Fold",
        PresetSetup(pivot_y=0.0),
        (PresetPhase(opacity=0, scale_y=0.18, mode="EASE_IN_CUBIC"),)),

    # ── Bounce family ─────────────────────────────────────────────────
    "Fall and Bounce": TransformPreset("Bounce",
        PresetSetup(opacity=0, translation_y=-84.0),
        (PresetPhase(opacity=255, translation_y=10.0, mode="EASE_OUT_CUBIC", duration_scale=0.6),
         PresetPhase(translation_y=-6.0, mode="EASE_OUT_QUAD", duration_scale=0.18),
         PresetPhase(translation_y=0.0, mode="EASE_OUT_BOUNCE", duration_scale=0.22))),

    # ── Signature family ──────────────────────────────────────────────
    "Lantern Rise": TransformPreset("Signature",
        PresetSetup(opacity=0, translation_y=34.0, scale_x=0.9, scale_y=0.84, rotation_z=-2.5),
        (PresetPhase(opacity=255, translation_y=-6.0, scale_x=1.03, scale_y=1.02, rotation_z=0.8, mode="EASE_OUT_CUBIC", duration_scale=0.72),
         PresetPhase(translation_y=0.0, scale_x=1.0, scale_y=1.0, rotation_z=0.0, mode="EASE_OUT_QUAD", duration_scale=0.28))),
    "Soft Collapse": TransformPreset("Signature",
        PresetSetup(),
        (PresetPhase(opacity=180, scale_x=1.02, scale_y=0.95, mode="EASE_IN_CUBIC", duration_scale=0.45),
         PresetPhase(opacity=0, scale_x=0.84, scale_y=0.74, translation_y=20.0, mode="EASE_IN_CUBIC", duration_scale=0.55))),

    # ── Scale family ──────────────────────────────────────────────────
    "Scale Down Soft": TransformPreset("Scale",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_x=0.62, scale_y=0.62, mode="EASE_IN_CUBIC"),)),
    "Vacuum Pull": TransformPreset("Deform",
        PresetSetup(pivot_x=0.5, pivot_y=1.0),
        (PresetPhase(opacity=0, scale_x=0.18, scale_y=0.04, translation_y=76.0, mode="EASE_IN_CUBIC"),)),

    # ── Focus family ──────────────────────────────────────────────────
    "Pulse Focus": TransformPreset("Focus",
        PresetSetup(opacity=210, scale_x=0.94, scale_y=0.94),
        (PresetPhase(opacity=255, scale_x=1.04, scale_y=1.04, mode="EASE_OUT_CUBIC", duration_scale=0.7),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.3))),
    "Halo Focus": TransformPreset("Focus",
        PresetSetup(opacity=220, scale_x=0.97, scale_y=0.97),
        (PresetPhase(opacity=255, scale_x=1.02, scale_y=1.02, mode="EASE_OUT_CUBIC", duration_scale=0.6),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.4))),
    "Settle Focus": TransformPreset("Focus",
        PresetSetup(scale_x=1.02, scale_y=1.02),
        (PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_CUBIC"),)),
    "Wiggle Focus": TransformPreset("Focus",
        PresetSetup(rotation_z=-3.0),
        (PresetPhase(rotation_z=3.0, mode="EASE_OUT_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=-2.0, mode="EASE_IN_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=1.2, mode="EASE_IN_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=0.0, mode="EASE_OUT_CUBIC", duration_scale=0.25))),
    "Soft Focus Flash": TransformPreset("Focus",
        PresetSetup(opacity=225),
        (PresetPhase(opacity=255, mode="EASE_OUT_CUBIC", duration_scale=0.5),
         PresetPhase(opacity=245, mode="EASE_OUT_QUAD", duration_scale=0.5))),

    # ── Defocus family ────────────────────────────────────────────────
    "Fade Dim": TransformPreset("Defocus",
        PresetSetup(),
        (PresetPhase(opacity=228, mode="EASE_OUT_CUBIC"),)),
    "Slip Back": TransformPreset("Defocus",
        PresetSetup(),
        (PresetPhase(opacity=232, scale_x=0.985, scale_y=0.985, translation_y=6.0, mode="EASE_OUT_CUBIC"),)),
    "Shrink Fade": TransformPreset("Defocus",
        PresetSetup(),
        (PresetPhase(opacity=220, scale_x=0.97, scale_y=0.97, mode="EASE_OUT_CUBIC"),)),
    "Quiet Defocus": TransformPreset("Defocus",
        PresetSetup(),
        (PresetPhase(opacity=235, mode="EASE_OUT_CUBIC"),)),

    # ── State family ──────────────────────────────────────────────────
    "Expand Settle": TransformPreset("State",
        PresetSetup(scale_x=0.97, scale_y=0.97),
        (PresetPhase(scale_x=1.02, scale_y=1.02, mode="EASE_OUT_CUBIC", duration_scale=0.68),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.32))),
    "Contract Settle": TransformPreset("State",
        PresetSetup(scale_x=1.03, scale_y=1.03),
        (PresetPhase(scale_x=0.985, scale_y=0.985, mode="EASE_OUT_CUBIC", duration_scale=0.65),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.35))),

    # ── Interactive family ────────────────────────────────────────────
    "Grip Pulse": TransformPreset("Interactive",
        PresetSetup(scale_x=0.98, scale_y=0.98),
        (PresetPhase(scale_x=1.01, scale_y=1.01, mode="EASE_OUT_CUBIC", duration_scale=0.45),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.55))),
    "Lift Away": TransformPreset("Interactive",
        PresetSetup(translation_y=6.0, scale_x=0.99, scale_y=0.99),
        (PresetPhase(translation_y=-6.0, scale_x=1.01, scale_y=1.01, mode="EASE_OUT_CUBIC", duration_scale=0.58),
         PresetPhase(translation_y=0.0, scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.42))),
    "Wobble Settle": TransformPreset("Interactive",
        PresetSetup(rotation_z=-3.2),
        (PresetPhase(rotation_z=2.4, mode="EASE_OUT_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=-1.8, mode="EASE_IN_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=1.0, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(rotation_z=0.0, mode="EASE_OUT_QUAD", duration_scale=0.3))),
    "Edge Tension": TransformPreset("Interactive",
        PresetSetup(scale_x=1.01, scale_y=0.99),
        (PresetPhase(scale_x=0.995, scale_y=1.005, mode="EASE_OUT_CUBIC", duration_scale=0.5),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.5))),
    "Elastic Settle": TransformPreset("Interactive",
        PresetSetup(scale_x=1.03, scale_y=0.97),
        (PresetPhase(scale_x=0.985, scale_y=1.015, mode="EASE_OUT_CUBIC", duration_scale=0.34),
         PresetPhase(scale_x=1.01, scale_y=0.99, mode="EASE_IN_CUBIC", duration_scale=0.26),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.4))),
    "Jelly Grab": TransformPreset("Interactive",
        PresetSetup(scale_x=0.96, scale_y=1.04, rotation_z=-1.5),
        (PresetPhase(scale_x=1.03, scale_y=0.97, rotation_z=1.0, mode="EASE_OUT_CUBIC", duration_scale=0.4),
         PresetPhase(scale_x=0.99, scale_y=1.01, rotation_z=-0.4, mode="EASE_IN_CUBIC", duration_scale=0.3),
         PresetPhase(scale_x=1.0, scale_y=1.0, rotation_z=0.0, mode="EASE_OUT_QUAD", duration_scale=0.3))),
    "Wobbly Drop": TransformPreset("Interactive",
        PresetSetup(rotation_z=-4.5, scale_x=1.02, scale_y=0.98),
        (PresetPhase(rotation_z=3.5, scale_x=0.98, scale_y=1.02, mode="EASE_OUT_CUBIC", duration_scale=0.2),
         PresetPhase(rotation_z=-2.5, scale_x=1.01, scale_y=0.99, mode="EASE_IN_CUBIC", duration_scale=0.18),
         PresetPhase(rotation_z=1.8, scale_x=0.995, scale_y=1.005, mode="EASE_IN_CUBIC", duration_scale=0.16),
         PresetPhase(rotation_z=-0.8, mode="EASE_IN_CUBIC", duration_scale=0.14),
         PresetPhase(rotation_z=0.0, scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.32))),
    "Rubber Stretch": TransformPreset("Interactive",
        PresetSetup(scale_x=1.04, scale_y=0.96),
        (PresetPhase(scale_x=0.97, scale_y=1.03, mode="EASE_OUT_CUBIC", duration_scale=0.35),
         PresetPhase(scale_x=1.015, scale_y=0.985, mode="EASE_IN_CUBIC", duration_scale=0.3),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.35))),
    "Spring Snap": TransformPreset("Interactive",
        PresetSetup(scale_x=1.05, scale_y=0.95, rotation_z=1.2),
        (PresetPhase(scale_x=0.97, scale_y=1.03, rotation_z=-0.8, mode="EASE_OUT_CUBIC", duration_scale=0.25),
         PresetPhase(scale_x=1.02, scale_y=0.98, rotation_z=0.5, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(scale_x=0.99, scale_y=1.01, rotation_z=-0.2, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(scale_x=1.0, scale_y=1.0, rotation_z=0.0, mode="EASE_OUT_QUAD", duration_scale=0.35))),

    # ── State family (maximize/unmaximize physics) ────────────────────
    "Snap Wobble": TransformPreset("State",
        PresetSetup(scale_x=0.95, scale_y=0.95),
        (PresetPhase(scale_x=1.04, scale_y=1.04, mode="EASE_OUT_CUBIC", duration_scale=0.3),
         PresetPhase(scale_x=0.98, scale_y=0.98, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(scale_x=1.015, scale_y=1.015, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.3))),
    "Release Wobble": TransformPreset("State",
        PresetSetup(scale_x=1.04, scale_y=1.04),
        (PresetPhase(scale_x=0.97, scale_y=0.97, mode="EASE_OUT_CUBIC", duration_scale=0.3),
         PresetPhase(scale_x=1.02, scale_y=1.02, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(scale_x=0.99, scale_y=0.99, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.3))),

    # ── Banner family ─────────────────────────────────────────────────
    "Banner Sweep": TransformPreset("Banner",
        PresetSetup(opacity=0, translation_x=26.0, scale_x=0.96),
        (PresetPhase(opacity=255, translation_x=0.0, scale_x=1.0, mode="EASE_OUT_CUBIC"),)),
    "Banner Fold": TransformPreset("Banner",
        PresetSetup(pivot_y=0.0),
        (PresetPhase(opacity=0, scale_y=0.16, mode="EASE_IN_CUBIC"),)),

    # ── Playful family ────────────────────────────────────────────────
    "Wiggle Out": TransformPreset("Playful",
        PresetSetup(),
        (PresetPhase(rotation_z=4.0, mode="EASE_OUT_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=-5.0, mode="EASE_IN_CUBIC", duration_scale=0.25),
         PresetPhase(rotation_z=2.0, opacity=180, mode="EASE_IN_CUBIC", duration_scale=0.2),
         PresetPhase(rotation_z=0.0, opacity=0, scale_x=0.92, scale_y=0.92, mode="EASE_IN_CUBIC", duration_scale=0.3))),
    # ── Dock / Deform family (preview approximation) ────────────────────
    # Runtime versions animate toward the actual dock icon position.
    # Preview uses a fixed downward offset to simulate a bottom-panel dock.
    "Dock Funnel": TransformPreset("Dock",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_x=0.12, scale_y=0.04, translation_x=0.0, translation_y=80.0,
                     rotation_z=12.0, mode="EASE_IN_CUBIC"),)),
    "Dock Return": TransformPreset("Dock",
        PresetSetup(opacity=0, scale_x=0.12, scale_y=0.04, translation_x=0.0, translation_y=80.0, rotation_z=10.0),
        (PresetPhase(opacity=255, scale_x=1.02, scale_y=1.02, translation_x=0.0, translation_y=0.0,
                     rotation_z=0.0, mode="EASE_OUT_CUBIC", duration_scale=0.78),
         PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.22))),
    "Magic Lamp": TransformPreset("Dock",
        PresetSetup(),
        (PresetPhase(opacity=110, translation_y=11.0, scale_x=1.06, scale_y=0.9,
                     mode="EASE_IN_CUBIC", duration_scale=0.34),
         PresetPhase(opacity=0, translation_y=80.0, scale_x=0.18, scale_y=0.04,
                     rotation_z=14.0, mode="EASE_IN_CUBIC", duration_scale=0.66))),
    "Magic Lamp Return": TransformPreset("Dock",
        PresetSetup(opacity=0, scale_x=0.18, scale_y=0.04, translation_y=80.0, rotation_z=12.0),
        (PresetPhase(opacity=255, translation_y=12.0, scale_x=1.04, scale_y=0.92,
                     rotation_z=0.0, mode="EASE_OUT_CUBIC", duration_scale=0.72),
         PresetPhase(translation_y=0.0, scale_x=1.0, scale_y=1.0,
                     mode="EASE_OUT_QUAD", duration_scale=0.28))),
    # ── Shader family (preview approximation) ────────────────────────
    # Runtime versions use Clutter shaders.  Preview approximates the
    # visible scale+opacity envelope.
    "Glass Ripple In": TransformPreset("Shader",
        PresetSetup(opacity=0, scale_x=0.93, scale_y=0.93),
        (PresetPhase(opacity=255, scale_x=1.02, scale_y=1.02,
                     mode="EASE_OUT_CUBIC", duration_scale=0.7),
         PresetPhase(scale_x=1.0, scale_y=1.0,
                     mode="EASE_OUT_QUAD", duration_scale=0.3))),
    "Glass Ripple Out": TransformPreset("Shader",
        PresetSetup(),
        (PresetPhase(opacity=0, scale_x=0.88, scale_y=0.88,
                     mode="EASE_IN_CUBIC"),)),
}

# fmt: on


VALID_EASING_MODES = frozenset({
    "EASE_OUT_CUBIC",
    "EASE_IN_CUBIC",
    "EASE_OUT_QUAD",
    "EASE_IN_QUAD",
    "EASE_OUT_BOUNCE",
    "LINEAR",
})
