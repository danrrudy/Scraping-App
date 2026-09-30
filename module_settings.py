"""Settings that belong to a module rather than to the application.

A *module* is any component that owns some behaviour a user might want to
change — today the document viewer and each right-hand content panel. Each
declares what it can be configured with, instead of the application holding a
flat list of every knob in the program:

    @register_module_settings
    class MyPanel(ContentPanel):
        MODULE_SETTINGS = ModuleSettings(
            module_id="my_panel",
            display_name="My Panel",
            settings=(BoolSetting("doThing", "Do the thing", default=True),),
        )

Stored values live under ``settings["moduleSettings"][module_id]``. Entries are
never pruned, so a module the user has configured before keeps its values even
while it is not loaded.

This module is deliberately Qt-free: it describes settings, it does not draw
them. ``module_settings_dialog.py`` renders whatever is declared here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Key under which every module's values are stored in user settings.
SETTINGS_KEY = "moduleSettings"


@dataclass(frozen=True)
class SettingSpec:
    """One configurable value belonging to a module."""

    key: str
    label: str
    kind: str  # "bool" | "int" | "choice" | "text"
    default: Any = None
    choices: tuple = ()
    minimum: int = 0
    maximum: int = 100
    help: str = ""

    def coerce(self, value):
        """Read a stored value, falling back to the default when unusable."""
        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "y"}
            return bool(self.default) if value is None else bool(value)

        if self.kind == "int":
            try:
                number = int(value)
            except (TypeError, ValueError):
                return int(self.default or 0)
            return max(self.minimum, min(self.maximum, number))

        if self.kind == "choice":
            text = "" if value is None else str(value)
            return text if text in self.choices else self.default

        return "" if value is None else str(value)


def BoolSetting(key, label, *, default=False, help=""):
    return SettingSpec(key, label, "bool", default=default, help=help)


def IntSetting(key, label, *, default=0, minimum=0, maximum=100, help=""):
    return SettingSpec(
        key, label, "int", default=default, minimum=minimum, maximum=maximum, help=help
    )


def ChoiceSetting(key, label, *, choices, default="", help=""):
    return SettingSpec(
        key, label, "choice", default=default, choices=tuple(choices), help=help
    )


def TextSetting(key, label, *, default="", help=""):
    return SettingSpec(key, label, "text", default=default, help=help)


@dataclass(frozen=True)
class ModuleSettings:
    """Everything one module can be configured with."""

    module_id: str
    display_name: str
    settings: tuple[SettingSpec, ...] = field(default_factory=tuple)

    @property
    def defaults(self) -> dict:
        return {spec.key: spec.default for spec in self.settings}

    def resolve(self, stored) -> dict:
        """Merge stored values over the declared defaults, coercing each."""
        stored = stored or {}
        return {spec.key: spec.coerce(stored.get(spec.key)) for spec in self.settings}


_REGISTRY: dict[str, ModuleSettings] = {}


def register_module_settings(target):
    """Register a class's ``MODULE_SETTINGS``. Usable as a decorator."""
    spec = target if isinstance(target, ModuleSettings) else target.MODULE_SETTINGS
    if not spec.module_id:
        raise ValueError("A module settings block needs a module_id")
    _REGISTRY[spec.module_id] = spec
    return target


def registered_modules() -> dict[str, ModuleSettings]:
    """Every module the running program knows how to configure."""
    return dict(_REGISTRY)


def module_spec(module_id: str) -> ModuleSettings | None:
    return _REGISTRY.get(module_id)


def stored_modules(settings) -> tuple[str, ...]:
    """Module ids the user settings file already carries values for."""
    return tuple((settings or {}).get(SETTINGS_KEY, {}) or {})


def resolve(settings, module_id: str) -> dict:
    """The effective values for one module: stored over declared defaults."""
    spec = _REGISTRY.get(module_id)
    stored = ((settings or {}).get(SETTINGS_KEY, {}) or {}).get(module_id, {})
    if spec is None:
        # Unknown module: hand back whatever was stored rather than losing it.
        return dict(stored or {})
    return spec.resolve(stored)


def store(settings, module_id: str, values) -> None:
    """Write one module's values into ``settings``, in place."""
    settings.setdefault(SETTINGS_KEY, {})[module_id] = dict(values or {})


def remember(settings, module_id: str) -> bool:
    """Ensure a loaded module has an entry, so it survives in the settings file.

    Returns ``True`` when something was added, so the caller can decide whether
    the file needs writing.
    """
    section = settings.setdefault(SETTINGS_KEY, {})
    spec = _REGISTRY.get(module_id)
    if spec is None:
        return False

    entry = section.get(module_id)
    if entry is None:
        section[module_id] = spec.defaults
        return True

    # Fill in settings added since the user last saved.
    missing = {
        key: value for key, value in spec.defaults.items() if key not in entry
    }
    if missing:
        entry.update(missing)
        return True
    return False


def visible_modules(settings, active_ids, *, mode="user") -> tuple[str, ...]:
    """Which modules the settings window should offer.

    Non-dev modes show only what is loaded now; dev mode shows everything the
    program knows about plus anything the settings file remembers, so a module
    can be configured before it is switched to.
    """
    if str(mode).lower() != "dev":
        return tuple(dict.fromkeys(active_ids))

    everything = [*active_ids, *sorted(_REGISTRY), *stored_modules(settings)]
    return tuple(dict.fromkeys(everything))
