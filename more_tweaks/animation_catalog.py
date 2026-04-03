from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BindingDefinition:
    id: str
    group_id: str
    title: str
    summary: str
    target: str
    action: str
    default_preset: str
    default_duration_ms: int
    default_delay_ms: int = 0
    default_intensity: float = 1.0
    tier: str = "core"
    preset_names: tuple[str, ...] = ()

    @property
    def enabled_key(self) -> str:
        return f"{self.id}-enabled"

    @property
    def preset_key(self) -> str:
        return f"{self.id}-preset"

    @property
    def duration_key(self) -> str:
        return f"{self.id}-duration-ms"

    @property
    def delay_key(self) -> str:
        return f"{self.id}-delay-ms"

    @property
    def intensity_key(self) -> str:
        return f"{self.id}-intensity"


@dataclass(frozen=True, slots=True)
class GroupDefinition:
    id: str
    title: str
    summary: str


OPEN_PRESETS = (
    "Glide In",
    "Bloom In",
    "Drift Up",
    "Fade In",
    "Slide Left In",
    "Slide Right In",
    "Slide Down In",
    "Compressed Slide Up",
    "Squeezed Slide Left",
    "Zoom In",
    "Rotate In Left",
    "Rotate In Down",
    "Flip In Horizontal",
    "Fold In Vertical",
    "Fall and Bounce",
    "Soft Pop",
    "Lantern Rise",
)

CLOSE_PRESETS = (
    "Glide Out",
    "Shutter Out",
    "Drift Down",
    "Fade Out",
    "Slide Left Out",
    "Slide Right Out",
    "Slide Up Out",
    "Compressed Slide Down",
    "Squeezed Slide Right",
    "Zoom Out",
    "Rotate Out Left",
    "Rotate Out Up",
    "Flip Out Horizontal",
    "Fold Out Vertical",
    "Wiggle Out",
    "Soft Collapse",
)

MINIMIZE_PRESETS = (
    "Dock Funnel",
    "Magic Lamp",
    "Drift Down",
    "Fade Out",
    "Scale Down Soft",
    "Vacuum Pull",
)

RESTORE_PRESETS = (
    "Dock Return",
    "Magic Lamp Return",
    "Bloom In",
    "Glide In",
    "Soft Pop",
    "Lantern Rise",
)

FOCUS_PRESETS = (
    "Pulse Focus",
    "Halo Focus",
    "Settle Focus",
    "Wiggle Focus",
    "Soft Focus Flash",
)

DEFOCUS_PRESETS = (
    "Fade Dim",
    "Slip Back",
    "Shrink Fade",
    "Quiet Defocus",
)

MAXIMIZE_PRESETS = (
    "Expand Settle",
    "Bloom In",
    "Pulse Focus",
    "Zoom In",
    "Snap Wobble",
)

UNMAXIMIZE_PRESETS = (
    "Contract Settle",
    "Glide In",
    "Settle Focus",
    "Soft Pop",
    "Release Wobble",
)

MOVE_START_PRESETS = (
    "Grip Pulse",
    "Lift Away",
    "Halo Focus",
    "Jelly Grab",
)

MOVE_STOP_PRESETS = (
    "Wobble Settle",
    "Settle Focus",
    "Soft Pop",
    "Wobbly Drop",
)

RESIZE_START_PRESETS = (
    "Edge Tension",
    "Grip Pulse",
    "Halo Focus",
    "Rubber Stretch",
)

RESIZE_STOP_PRESETS = (
    "Elastic Settle",
    "Wobble Settle",
    "Soft Pop",
    "Spring Snap",
)

NOTIFICATION_OPEN_PRESETS = (
    "Drift Up",
    "Pulse Focus",
    "Fade In",
    "Banner Sweep",
    "Fold In Vertical",
)

NOTIFICATION_CLOSE_PRESETS = (
    "Fade Out",
    "Drift Down",
    "Shutter Out",
    "Banner Fold",
    "Soft Collapse",
)

GROUP_DEFINITIONS = (
    GroupDefinition(
        id="windows",
        title="Windows",
        summary="Open, close, minimize, and restore motion for regular windows.",
    ),
    GroupDefinition(
        id="window_states",
        title="Window States",
        summary="Focus and maximize transitions that give windows more presence without replacing GNOME's basic feel.",
    ),
    GroupDefinition(
        id="interactive",
        title="Interactive Motion",
        summary="Lightweight move and resize reactions inspired by classic compiz-style responsiveness.",
    ),
    GroupDefinition(
        id="dialogs",
        title="Dialogs",
        summary="Separate motion language for dialog and modal dialog windows.",
    ),
    GroupDefinition(
        id="notifications",
        title="Notifications",
        summary="Notification banners with softer, app-owned motion instead of shell defaults.",
    ),
)

GROUPS_BY_ID = {group.id: group for group in GROUP_DEFINITIONS}


BINDING_DEFINITIONS = (
    BindingDefinition(
        id="window-open",
        group_id="windows",
        title="Open animation",
        summary="Animate normal windows as they appear.",
        target="window",
        action="open",
        default_preset="Glide In",
        default_duration_ms=240,
        preset_names=OPEN_PRESETS,
    ),
    BindingDefinition(
        id="window-close",
        group_id="windows",
        title="Close animation",
        summary="Animate normal windows as they disappear.",
        target="window",
        action="close",
        default_preset="Glide Out",
        default_duration_ms=220,
        preset_names=CLOSE_PRESETS,
    ),
    BindingDefinition(
        id="window-minimize",
        group_id="windows",
        title="Minimize animation",
        summary="Animate normal windows into the dock edge when they minimize.",
        target="window",
        action="minimize",
        default_preset="Dock Funnel",
        default_duration_ms=280,
        preset_names=MINIMIZE_PRESETS,
    ),
    BindingDefinition(
        id="window-unminimize",
        group_id="windows",
        title="Restore animation",
        summary="Animate minimized windows back into place.",
        target="window",
        action="unminimize",
        default_preset="Dock Return",
        default_duration_ms=320,
        preset_names=RESTORE_PRESETS,
    ),
    BindingDefinition(
        id="window-focus",
        group_id="window_states",
        title="Focus animation",
        summary="Emphasize the newly focused window.",
        target="window",
        action="focus",
        default_preset="Halo Focus",
        default_duration_ms=170,
        default_intensity=0.85,
        preset_names=FOCUS_PRESETS,
    ),
    BindingDefinition(
        id="window-defocus",
        group_id="window_states",
        title="Defocus animation",
        summary="Subtly relax the previously focused window.",
        target="window",
        action="defocus",
        default_preset="Quiet Defocus",
        default_duration_ms=140,
        default_intensity=0.75,
        preset_names=DEFOCUS_PRESETS,
    ),
    BindingDefinition(
        id="window-maximize",
        group_id="window_states",
        title="Maximize animation",
        summary="Accent the moment a normal window expands to a maximized state.",
        target="window",
        action="maximize",
        default_preset="Expand Settle",
        default_duration_ms=220,
        default_intensity=0.9,
        tier="advanced",
        preset_names=MAXIMIZE_PRESETS,
    ),
    BindingDefinition(
        id="window-unmaximize",
        group_id="window_states",
        title="Unmaximize animation",
        summary="Accent the transition back out of a maximized state.",
        target="window",
        action="unmaximize",
        default_preset="Contract Settle",
        default_duration_ms=220,
        default_intensity=0.9,
        tier="advanced",
        preset_names=UNMAXIMIZE_PRESETS,
    ),
    BindingDefinition(
        id="window-move-start",
        group_id="interactive",
        title="Move start",
        summary="Give windows a light pickup response when dragging starts.",
        target="window",
        action="move-start",
        default_preset="Grip Pulse",
        default_duration_ms=120,
        default_intensity=0.75,
        tier="advanced",
        preset_names=MOVE_START_PRESETS,
    ),
    BindingDefinition(
        id="window-move-stop",
        group_id="interactive",
        title="Move stop",
        summary="Let windows settle when a drag ends.",
        target="window",
        action="move-stop",
        default_preset="Wobble Settle",
        default_duration_ms=190,
        default_intensity=0.8,
        tier="advanced",
        preset_names=MOVE_STOP_PRESETS,
    ),
    BindingDefinition(
        id="window-resize-start",
        group_id="interactive",
        title="Resize start",
        summary="React when a manual resize begins.",
        target="window",
        action="resize-start",
        default_preset="Edge Tension",
        default_duration_ms=120,
        default_intensity=0.75,
        tier="advanced",
        preset_names=RESIZE_START_PRESETS,
    ),
    BindingDefinition(
        id="window-resize-stop",
        group_id="interactive",
        title="Resize stop",
        summary="Let the frame settle when a manual resize ends.",
        target="window",
        action="resize-stop",
        default_preset="Elastic Settle",
        default_duration_ms=190,
        default_intensity=0.8,
        tier="advanced",
        preset_names=RESIZE_STOP_PRESETS,
    ),
    BindingDefinition(
        id="dialog-open",
        group_id="dialogs",
        title="Dialog open",
        summary="Animate regular dialog windows.",
        target="dialog",
        action="open",
        default_preset="Bloom In",
        default_duration_ms=220,
        preset_names=OPEN_PRESETS,
    ),
    BindingDefinition(
        id="dialog-close",
        group_id="dialogs",
        title="Dialog close",
        summary="Animate regular dialog windows closing.",
        target="dialog",
        action="close",
        default_preset="Shutter Out",
        default_duration_ms=210,
        preset_names=CLOSE_PRESETS,
    ),
    BindingDefinition(
        id="dialog-focus",
        group_id="dialogs",
        title="Dialog focus",
        summary="Emphasize a dialog when it receives focus.",
        target="dialog",
        action="focus",
        default_preset="Pulse Focus",
        default_duration_ms=160,
        default_intensity=0.85,
        tier="advanced",
        preset_names=FOCUS_PRESETS,
    ),
    BindingDefinition(
        id="dialog-defocus",
        group_id="dialogs",
        title="Dialog defocus",
        summary="Soften a dialog as focus moves elsewhere.",
        target="dialog",
        action="defocus",
        default_preset="Fade Dim",
        default_duration_ms=130,
        default_intensity=0.75,
        tier="advanced",
        preset_names=DEFOCUS_PRESETS,
    ),
    BindingDefinition(
        id="modaldialog-open",
        group_id="dialogs",
        title="Modal dialog open",
        summary="Animate modal dialogs with a more anchored entry.",
        target="modaldialog",
        action="open",
        default_preset="Drift Up",
        default_duration_ms=240,
        preset_names=OPEN_PRESETS,
    ),
    BindingDefinition(
        id="modaldialog-close",
        group_id="dialogs",
        title="Modal dialog close",
        summary="Animate modal dialogs as they dismiss.",
        target="modaldialog",
        action="close",
        default_preset="Fade Out",
        default_duration_ms=200,
        preset_names=CLOSE_PRESETS,
    ),
    BindingDefinition(
        id="modaldialog-focus",
        group_id="dialogs",
        title="Modal focus",
        summary="Give modal dialogs a tighter focus response.",
        target="modaldialog",
        action="focus",
        default_preset="Settle Focus",
        default_duration_ms=150,
        default_intensity=0.8,
        tier="advanced",
        preset_names=FOCUS_PRESETS,
    ),
    BindingDefinition(
        id="modaldialog-defocus",
        group_id="dialogs",
        title="Modal defocus",
        summary="Relax a modal dialog once focus shifts away.",
        target="modaldialog",
        action="defocus",
        default_preset="Quiet Defocus",
        default_duration_ms=130,
        default_intensity=0.75,
        tier="advanced",
        preset_names=DEFOCUS_PRESETS,
    ),
    BindingDefinition(
        id="notification-open",
        group_id="notifications",
        title="Banner open",
        summary="Animate notification banners when they appear.",
        target="notification",
        action="open",
        default_preset="Drift Up",
        default_duration_ms=220,
        preset_names=NOTIFICATION_OPEN_PRESETS,
    ),
    BindingDefinition(
        id="notification-close",
        group_id="notifications",
        title="Banner close",
        summary="Animate notification banners when they disappear.",
        target="notification",
        action="close",
        default_preset="Fade Out",
        default_duration_ms=180,
        preset_names=NOTIFICATION_CLOSE_PRESETS,
    ),
)

BINDINGS_BY_ID = {binding.id: binding for binding in BINDING_DEFINITIONS}

PER_APP_ACTIONS = ("open", "close", "minimize", "unminimize", "focus", "defocus", "maximize", "unmaximize")
