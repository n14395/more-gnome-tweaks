from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Choice:
    value: object
    label: str


@dataclass(frozen=True, slots=True)
class Tweak:
    id: str
    name: str
    summary: str
    description: str
    category: str
    schema: str
    key: str
    value_type: str
    control: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    choices: tuple[Choice, ...] = field(default_factory=tuple)
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    command_hint: str | None = None


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    name: str
    description: str
    icon_name: str
    parent: str | None = None
