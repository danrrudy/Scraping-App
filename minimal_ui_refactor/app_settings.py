# app_settings.py
import json
import os
from copy import deepcopy

import paths
from mid_schema import DEFAULT_MID_SCHEMA

# The sidebar checkboxes are user-defined. Each entry needs only a MID column;
# everything else is derived or optional:
#
#   column   the boolean MID column the checkbox writes to (required)
#   label    what the user sees          (default: the column, prettified)
#   key      how code refers to it       (default: the column without "_")
#   shortcut keyboard shortcut, e.g. "Ctrl+F"
#   message  status-bar text shown when it is toggled
#   counter  an optional numeric companion, enabled only while the box is
#            ticked: {"column", "label", "minimum", "maximum"}
DEFAULT_CHECKBOXES = [
    {
        "column": "_flag",
        "label": "Flag for review",
        "shortcut": "Ctrl+F",
        "message": "Flagged for review.",
    },
    {
        "column": "_aggregate",
        "label": "Aggregate",
        "message": "Flagged as Aggregate",
    },
    {
        "column": "_achieved",
        "label": "Achieved",
        "message": "Toggled achieved status",
    },
    {
        "column": "_future_dated",
        "label": "Future-Dated",
        "counter": {
            "column": "years_to_evaluation",
            "label": "Years to eval:",
            "maximum": 20,
        },
    },
]


def _clean(value):
    return str(value or "").strip()


def _normalize_counter(value):
    """Validate one checkbox's numeric companion, or return ``None``."""
    if not isinstance(value, dict):
        return None
    column = _clean(value.get("column"))
    if not column:
        return None
    try:
        minimum = int(value.get("minimum", 0))
        maximum = int(value.get("maximum", 20))
    except (TypeError, ValueError):
        minimum, maximum = 0, 20
    if maximum < minimum:
        minimum, maximum = maximum, minimum
    return {
        "column": column,
        "label": _clean(value.get("label")) or f"{column.replace('_', ' ').title()}:",
        "minimum": minimum,
        "maximum": maximum,
    }


def normalize_checkboxes(value):
    """Fill in the derivable parts of each checkbox definition.

    Accepts the stored list (or a bare list of column names) and returns
    complete, de-duplicated definitions. Entries without a column are dropped
    rather than raising, so a hand-edited settings file cannot stop the app
    from starting.
    """
    definitions = []
    seen_keys = set()
    seen_columns = set()

    for entry in value or []:
        if isinstance(entry, str):
            entry = {"column": entry}
        if not isinstance(entry, dict):
            continue

        column = _clean(entry.get("column"))
        if not column or column in seen_columns:
            continue

        key = _clean(entry.get("key")) or column.lstrip("_") or column
        if key in seen_keys:
            continue

        seen_keys.add(key)
        seen_columns.add(column)
        definitions.append(
            {
                "key": key,
                "column": column,
                "label": _clean(entry.get("label"))
                or column.lstrip("_").replace("_", " ").title(),
                "shortcut": _clean(entry.get("shortcut")),
                "message": _clean(entry.get("message")),
                "counter": _normalize_counter(entry.get("counter")),
            }
        )

    return definitions


#: What a button may do to the checkbox it is linked to.
CHECKBOX_ACTIONS = ("check", "uncheck", "toggle")


def _normalize_checkbox_action(value):
    action = _clean(value).lower()
    return action if action in CHECKBOX_ACTIONS else "check"


def normalize_field_buttons(value):
    """Fill in the derivable parts of each computed-button definition.

    A button reads the editable fields, evaluates its expression, and writes
    the result into one field:

        {"label": "10%", "target": "Match",
         "expression": "LMIG_Exp * 0.10", "decimals": 2}

    It may also tick a checkbox in the same press. ``checkbox`` names the
    checkbox by its key or its MID column, and ``checkbox_action`` is one of
    :data:`CHECKBOX_ACTIONS`:

        {"label": "Sum", "target": "Total_Exp",
         "expression": "LMIG_Exp + Match", "checkbox": "_aggregate"}

    Entries missing a label, target, or expression are dropped rather than
    raising, so a hand-edited settings file cannot stop the app from starting.
    """
    definitions = []
    seen_keys = set()

    for entry in value or []:
        if not isinstance(entry, dict):
            continue

        label = _clean(entry.get("label"))
        target = _clean(entry.get("target"))
        expression = _clean(entry.get("expression"))
        if not (label and target and expression):
            continue

        key = _clean(entry.get("key")) or _slug(label)
        original = key
        suffix = 2
        while key in seen_keys:
            key = f"{original}_{suffix}"
            suffix += 1
        seen_keys.add(key)

        try:
            decimals = int(entry.get("decimals", 2))
        except (TypeError, ValueError):
            decimals = 2

        checkbox = _clean(entry.get("checkbox"))
        action = _normalize_checkbox_action(entry.get("checkbox_action"))
        definitions.append(
            {
                "key": key,
                "label": label,
                "target": target,
                "expression": expression,
                "decimals": min(6, max(0, decimals)),
                "checkbox": checkbox,
                "checkbox_action": action,
                "tooltip": _clean(entry.get("tooltip"))
                or field_button_summary(target, expression, checkbox, action),
            }
        )

    return definitions


#: How each action reads in a tooltip.
_ACTION_VERBS = {"check": "checks", "uncheck": "unchecks", "toggle": "toggles"}


def field_button_summary(target, expression, checkbox="", action="check"):
    """One line describing what a button does, for tooltips and list rows."""
    summary = f"{target} = {expression}"
    if checkbox:
        verb = _ACTION_VERBS[_normalize_checkbox_action(action)]
        summary += f", {verb} {checkbox}"
    return summary


def _slug(value):
    cleaned = "".join(
        character if character.isalnum() else "_" for character in str(value)
    )
    return cleaned.strip("_").lower() or "button"


def checkbox_columns(definitions):
    """Every MID column the given checkbox definitions read or write."""
    columns = []
    for definition in definitions:
        columns.append(definition["column"])
        if definition.get("counter"):
            columns.append(definition["counter"]["column"])
    return list(dict.fromkeys(columns))

#######################################
# WARNING: NO LOGGING IN THIS FILE    #
# LOGGER CANNOT BE CALLED HERE DUE TO #
# CIRCULAR DEPENDENCIES! WARNINGS AND #
# ERRORS IN THIS FILE ARE WRITTEN TO  #
# CONSOLE ONLY!                       #
#######################################

# Default application settings
# Options defined in settings_window.py
default_settings = {
    "fontSize": "12",  # Font size for display
    "MIDLocation": "",  # File location of the MID
    "MIDSheetName": "",  # Sheet name within the MID to use
    "loggingLevel": "INFO",  # Minimum severity of messages to log
    # NOTE: logs will be saved to ./logs if this variable can't be found by the logger!
    "logFileDirectory": paths.in_app_dir("logs"),  # Default: ./logs
    "logRetention": 10,  # Maximum number of log files to keep
    "consoleOutput": "Both",  # Writes log to console as well
    "scrapingToolDirectory": paths.in_app_dir("scrapers"),  # Default: ./scrapers
    "scrapingTools": {},
    "dataDirectory": paths.in_app_dir("data"),  # Default: ./data
    "defaultScraper": "",  # Name of the scraper to use as a fallback
    "userMode": "User",
    "defaultExtractor": "",
    "extractionTools": {},
    "extractionToolDirectory": paths.in_app_dir("extractors"),
    "evaluationClasses": {},
    "defaultClass": "",
    "UIScale": "1.0",
    "midSchema": deepcopy(DEFAULT_MID_SCHEMA),
    "checkboxes": deepcopy(DEFAULT_CHECKBOXES),
    # Buttons that compute one editable field from the others. Project
    # specific, so empty by default; defined in Settings > Configure Buttons.
    "fieldButtons": [],
    # Per-module settings, keyed by module id. Modules declare what they hold
    # (see module_settings.py); entries for modules that are not currently
    # loaded are kept so a user's configuration survives switching away.
    "moduleSettings": {},
}

# Default location for settings file. Beside the program, so that copying the
# installation somewhere else takes the configuration with it; see paths.py.
SETTINGS_PATH = paths.in_app_dir("user_settings.json")


def load_settings(path=SETTINGS_PATH):
    """Load settings from file or return defaults if file not found or invalid."""
    if not os.path.exists(path):
        save_settings(default_settings, path)
        return deepcopy(default_settings)

    try:
        # utf-8-sig, not utf-8: several Windows editors write a byte-order mark
        # when saving JSON, and reading that as plain utf-8 fails on the very
        # first character. The settings would then silently revert to defaults
        # and the next save would overwrite the user's real configuration.
        with open(path, "r", encoding="utf-8-sig") as f:
            user_settings = json.load(f)

            filtered_settings = {
                key: value
                for key, value in user_settings.items()
                if key in default_settings
            }

            unexpected_keys = set(user_settings) - set(default_settings)
            if unexpected_keys:
                print(f"[Warning] Ignored unknown setting(s): {unexpected_keys}")

            # Merge defaults with user settings (preserve fallback values)
            merged = deepcopy(default_settings)
            merged.update(filtered_settings)

            # Confirm that Logging directory exists or create
            log_dir = merged.get("logFileDirectory")
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            return merged
    except Exception as e:
        print(f"[Warning] Failed to load settings: {e}")
        return deepcopy(default_settings)


def save_settings(settings, path=SETTINGS_PATH):
    """Save settings to file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[Error] Failed to save settings: {e}")
