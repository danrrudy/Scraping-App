"""Description of what the UI should build, supplied by the controller.

``UIContext`` is the only thing the UI layer is told about the application's
data model. It deliberately contains plain strings and mappings so that the
widgets stay ignorant of MIDs, schemas, and pandas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class FieldSpec:
    """One editable free-text field in the left sidebar."""

    key: str
    label: str
    expandable: bool = False  # draws the "+" add-a-row button next to the editor


@dataclass(frozen=True)
class CounterSpec:
    """A numeric companion to a checkbox, live only while it is ticked."""

    key: str
    label: str
    minimum: int = 0
    maximum: int = 20


@dataclass(frozen=True)
class ToggleSpec:
    """One user-defined checkbox in the left sidebar."""

    key: str
    label: str
    shortcut: str = ""
    counter: "CounterSpec | None" = None


@dataclass(frozen=True)
class FieldButtonSpec:
    """A button that computes one editable field from the others."""

    key: str
    label: str
    target: str
    tooltip: str = ""


@dataclass(frozen=True)
class InfoSpec:
    """One read-only label in the left sidebar's information block."""

    key: str
    title: str


@dataclass
class UIContext:
    """Everything ``MainWindowUI`` needs in order to build itself."""

    mode: str = "user"
    fields: Sequence[FieldSpec] = ()
    toggles: Sequence[ToggleSpec] = ()
    field_buttons: Sequence[FieldButtonSpec] = ()
    info: Sequence[InfoSpec] = ()
    restriction_options: Sequence[str] = ()
    evaluation_classes: Mapping[str, Mapping] = field(default_factory=dict)
    default_class: str = ""
    reviewer_notes_enabled: bool = True

    @property
    def field_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.fields)

    @property
    def expandable_field_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.fields if spec.expandable)

    def buttons_for(self, field_key: str) -> tuple[FieldButtonSpec, ...]:
        """The computed buttons that write into ``field_key``."""
        return tuple(
            spec for spec in self.field_buttons if spec.target == field_key
        )

    @property
    def toggle_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.toggles)

    @property
    def counter_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.toggles if spec.counter)

    @property
    def normalized_mode(self) -> str:
        return (self.mode or "user").lower()
