"""Configurable column roles for Master Input Documents.

A schema names the column that says which document each row is about, the
optional X/Y identifier columns, and the *fields*: the columns the user edits
in the sidebar. Nothing here assumes any particular project's column names.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd


def _join(parts: Iterable[str], separator: str) -> str:
    """Join the parts that have a value, so a blank never leaves a stray gap."""
    return separator.join(part for part in parts if part)


#: How each row is named in the viewer, the logs, and exported filenames.
#: ``{key: (dropdown label, formatter)}``; every formatter is called with the
#: cleaned X value, Y value, and document filename, in that order.
ENTRY_LABEL_FORMATS = {
    "x_dash_y": ("X — Y", lambda x, y, document: _join((x, y), " — ")),
    "x_paren_y": (
        "X (Y)",
        lambda x, y, document: f"{x} ({y})" if x and y else _join((x, y), " "),
    ),
    "x_space_y": ("X Y", lambda x, y, document: _join((x, y), " ")),
    "xy": ("XY", lambda x, y, document: f"{x}{y}"),
    "y_dash_x": ("Y — X", lambda x, y, document: _join((y, x), " — ")),
    "document": ("Filename", lambda x, y, document: document),
    "document_xy": (
        "Filename (X — Y)",
        lambda x, y, document: (
            f"{document} ({_join((x, y), ' — ')})"
            if document and (x or y)
            else _join((document, x, y), " — ")
        ),
    ),
}

#: Composing X and Y with an em dash is what the application always did. A
#: row with no identifiers falls back to its document name regardless.
DEFAULT_ENTRY_LABEL = "x_dash_y"


def entry_label_choices() -> tuple[tuple[str, str], ...]:
    """``(key, dropdown label)`` for every supported entry label format."""
    return tuple((key, label) for key, (label, _) in ENTRY_LABEL_FORMATS.items())


def normalize_entry_label(value: Any) -> str:
    """Coerce a stored entry label key to one this version understands.

    Settings files are hand-edited, so an unknown key falls back to the
    default rather than stopping the application from starting.
    """
    key = clean_value(value)
    return key if key in ENTRY_LABEL_FORMATS else DEFAULT_ENTRY_LABEL


# ----------------------------------------------------------------------
# Fields
# ----------------------------------------------------------------------

#: How a field is edited in the sidebar. ``text`` is a free-text box;
#: ``dropdown`` and ``radio`` offer a fixed list of options.
FIELD_KINDS = ("text", "dropdown", "radio")

#: The field kinds that carry an options list.
CHOICE_FIELD_KINDS = ("dropdown", "radio")


def _option_list(value: Any) -> tuple[str, ...]:
    """Options may arrive as a list or as one string, one option per line."""
    if isinstance(value, str):
        parts = value.splitlines()
    elif isinstance(value, Iterable):
        parts = [str(part) for part in value]
    else:
        parts = []
    cleaned = (part.strip() for part in parts)
    return tuple(dict.fromkeys(part for part in cleaned if part))


def default_field_label(column: str) -> str:
    """A readable label for a column name.

    Underscores become spaces. A name with no capitals of its own is
    title-cased; one that has them (``LMIG_Exp``, ``FY``) is left alone,
    since title-casing would mangle the abbreviation.
    """
    label = column.replace("_", " ").strip()
    return label.title() if label == label.lower() else label


@dataclass(frozen=True)
class FieldConfig:
    """One editable MID column and how the sidebar presents it.

    ``hierarchy`` marks the field as one level of a nested structure: each
    such field gets a ``+`` button that adds a new row below the current
    one, keeping the levels above and clearing this one and those beneath.
    Levels are ordered the way the fields are listed. ``add_shortcut`` is the
    key sequence bound to that button, if any.
    """

    column: str
    label: str = ""
    kind: str = "text"
    options: tuple[str, ...] = ()
    hierarchy: bool = False
    add_shortcut: str = ""

    def __post_init__(self):
        object.__setattr__(self, "column", clean_value(self.column))
        object.__setattr__(
            self, "label", clean_value(self.label) or default_field_label(self.column)
        )
        kind = clean_value(self.kind).lower()
        object.__setattr__(self, "kind", kind if kind in FIELD_KINDS else "text")
        object.__setattr__(
            self,
            "options",
            _option_list(self.options) if self.kind in CHOICE_FIELD_KINDS else (),
        )
        object.__setattr__(self, "hierarchy", bool(self.hierarchy))
        object.__setattr__(self, "add_shortcut", clean_value(self.add_shortcut))

    @property
    def is_choice(self) -> bool:
        return self.kind in CHOICE_FIELD_KINDS

    @classmethod
    def from_mapping(cls, value: Any) -> "FieldConfig | None":
        """Build a field from a stored definition, or ``None`` if unusable.

        A bare string is taken as a column name, which is how fields were
        stored before they had any options.
        """
        if isinstance(value, str):
            value = {"column": value}
        if not isinstance(value, Mapping):
            return None
        field = cls(
            column=value.get("column", ""),
            label=value.get("label", ""),
            kind=value.get("kind", "text"),
            options=value.get("options", ()),
            hierarchy=value.get("hierarchy", False),
            add_shortcut=value.get("addShortcut", value.get("add_shortcut", "")),
        )
        return field if field.column else None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "label": self.label,
            "kind": self.kind,
            "options": list(self.options),
            "hierarchy": self.hierarchy,
            "addShortcut": self.add_shortcut,
        }


def normalize_fields(value: Any) -> tuple[FieldConfig, ...]:
    """Complete, de-duplicated field definitions from whatever was stored.

    Accepts a list of definitions, a list of bare column names, or a
    comma-separated string of column names. Entries without a column are
    dropped rather than raising, so a hand-edited settings file cannot stop
    the application from starting.
    """
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    fields: list[FieldConfig] = []
    seen: set[str] = set()
    for entry in value or []:
        field = FieldConfig.from_mapping(entry)
        if field is None or field.column in seen:
            continue
        seen.add(field.column)
        fields.append(field)
    return tuple(fields)


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

#: What the generated starter MID names its one column, and so what a fresh
#: installation expects to find. Everything else is configured in Settings.
DEFAULT_DOCUMENT_COLUMN = "Filename"

DEFAULT_MID_SCHEMA = {
    "xColumn": "",
    "yColumn": "",
    "fields": [],
    "documentColumn": DEFAULT_DOCUMENT_COLUMN,
    "pageColumn": "",
    "formatColumn": "",
    "keywordColumn": "",
    "entryLabel": DEFAULT_ENTRY_LABEL,
}

# The columns the application itself writes to, whatever the project. They
# are created in memory when absent, so a source MID does not need to
# contain them.
WORKFLOW_COLUMN_DEFAULTS = {
    # The one checkbox every configuration has; reviewer rejection sets it.
    "_flag": False,
    # Rows the application created (added observations, hierarchy children)
    # rather than ones the MID came with.
    "_gen": False,
    "notes": "",
    "reviewer_comments": "",
    "reviewer_status": "",
    # The page the row was last looked at on. Always an int once set.
    "Page": "",
    # Set once the user saves a change to a row, and kept in the exported MID
    # so "which rows have I already been through?" survives closing the app.
    "_edited": False,
}

#: The persistent per-row flag in :data:`WORKFLOW_COLUMN_DEFAULTS`.
EDITED_COLUMN = "_edited"

#: The page column in :data:`WORKFLOW_COLUMN_DEFAULTS`; the one column whose
#: type the application enforces, because it is compared with page indices.
PAGE_COLUMN = "Page"

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def coerce_page(value: Any) -> int | str:
    """A page value as an int, or ``""`` when it does not name a page.

    Spreadsheets hand back ``"3"``, ``3.0`` and ``3`` for the same cell, and
    the page is compared with integer page indices, so it is normalised once
    on the way in rather than at every comparison.
    """
    text = clean_value(value)
    if not text:
        return ""
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return ""
    return number if number > 0 else ""


def safe_filename_stem(value: str, fallback: str = "observation") -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", clean_value(value))
    cleaned = re.sub(r"\s+", "_", cleaned).strip(" ._")
    return cleaned or fallback


def normalize_sheet_name(value: Any) -> int | str:
    """Keep named sheets as strings while accepting persisted numeric indices."""
    if isinstance(value, int):
        return value
    cleaned = clean_value(value)
    if not cleaned:
        return 0
    if cleaned.isdigit():
        return int(cleaned)
    return cleaned


@dataclass(frozen=True)
class MIDSchema:
    """Maps generic MID columns to roles used by the application."""

    x_column: str = ""
    y_column: str = ""
    fields: tuple[FieldConfig, ...] = ()
    document_column: str = ""
    page_column: str = ""
    format_column: str = ""
    keyword_column: str = ""
    #: Key into :data:`ENTRY_LABEL_FORMATS`; how rows are named on screen.
    entry_label: str = DEFAULT_ENTRY_LABEL

    @classmethod
    def default(cls) -> "MIDSchema":
        return cls.from_mapping(DEFAULT_MID_SCHEMA)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "MIDSchema":
        return cls.from_mapping(settings.get("midSchema", DEFAULT_MID_SCHEMA))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "MIDSchema":
        data = dict(DEFAULT_MID_SCHEMA)
        if mapping:
            data.update(mapping)
        # Fields used to be stored as a bare list of column names under
        # ``interactionColumns``; a settings file from then still loads.
        stored_fields = data.get("fields")
        if not stored_fields and "interactionColumns" in data:
            stored_fields = data.get("interactionColumns")
        schema = cls(
            x_column=clean_value(data.get("xColumn")),
            y_column=clean_value(data.get("yColumn")),
            fields=normalize_fields(stored_fields),
            document_column=clean_value(data.get("documentColumn")),
            page_column=clean_value(data.get("pageColumn")),
            format_column=clean_value(data.get("formatColumn")),
            keyword_column=clean_value(data.get("keywordColumn")),
            entry_label=normalize_entry_label(data.get("entryLabel")),
        )
        schema.validate_configuration()
        return schema

    def to_mapping(self) -> dict[str, Any]:
        return {
            "xColumn": self.x_column,
            "yColumn": self.y_column,
            "fields": [field.to_mapping() for field in self.fields],
            "documentColumn": self.document_column,
            "pageColumn": self.page_column,
            "formatColumn": self.format_column,
            "keywordColumn": self.keyword_column,
            "entryLabel": normalize_entry_label(self.entry_label),
        }

    def with_fields(self, fields: Iterable[Any]) -> "MIDSchema":
        """A copy of this schema with a different field list."""
        return MIDSchema.from_mapping(
            dict(self.to_mapping(), fields=[
                field.to_mapping() if isinstance(field, FieldConfig) else field
                for field in fields
            ])
        )

    def validate_configuration(self) -> None:
        if not self.document_column and not (self.x_column and self.y_column):
            raise ValueError(
                "Configure a document filename column, or both X and Y "
                "identifier columns for a filename to be composed from."
            )
        if self.x_column and self.x_column == self.y_column:
            raise ValueError("X and Y identifier columns must be different.")
        if not self.document_column and self.editable_identifiers:
            # With no filename column the X/Y pair *is* the filename, so making
            # it editable would repoint the row at a different document.
            raise ValueError(
                "Without a document filename column the X/Y identifiers name "
                "the file, so they cannot also be editable fields: "
                f"{sorted(self.editable_identifiers)}"
            )
        if self.document_column in self.interaction_columns:
            raise ValueError(
                f"The document filename column '{self.document_column}' "
                "cannot also be an editable field."
            )

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    @property
    def interaction_columns(self) -> tuple[str, ...]:
        """The editable columns, in sidebar order."""
        return tuple(field.column for field in self.fields)

    def field(self, column: str) -> FieldConfig | None:
        return next((field for field in self.fields if field.column == column), None)

    @property
    def hierarchy_columns(self) -> tuple[str, ...]:
        """The fields that form nested levels, outermost first."""
        return tuple(field.column for field in self.fields if field.hierarchy)

    def hierarchy_below(self, column: str) -> tuple[str, ...]:
        """``column`` and every hierarchy level beneath it."""
        levels = self.hierarchy_columns
        if column not in levels:
            return ()
        return levels[levels.index(column):]

    @property
    def supports_prior_year_copy(self) -> bool:
        """Whether "copy the previous Y's hierarchy" can mean anything.

        It needs an X to match on, a Y to count back from, and levels to copy.
        """
        return bool(self.x_column and self.y_column and self.hierarchy_columns)

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------
    @property
    def identifier_columns(self) -> tuple[str, ...]:
        """The configured X/Y columns, skipping any left unconfigured."""
        return tuple(
            column for column in (self.x_column, self.y_column) if column
        )

    @property
    def editable_identifiers(self) -> tuple[str, ...]:
        """Identifier columns the user may fill in from within the app."""
        return tuple(
            column
            for column in self.identifier_columns
            if column in self.interaction_columns
        )

    @property
    def configured_columns(self) -> tuple[str, ...]:
        """Every column this schema refers to, required or not."""
        configured = [
            self.x_column,
            self.y_column,
            *self.interaction_columns,
            self.document_column,
            self.page_column,
            self.format_column,
            self.keyword_column,
        ]
        return tuple(dict.fromkeys(column for column in configured if column))

    @property
    def required_source_columns(self) -> tuple[str, ...]:
        """Columns the MID sheet must already contain.

        Only the anchor is required: the column that says which document a row
        refers to. Everything else is created empty when absent so that
        identifiers and fields can be assigned inside the application.
        """
        if self.document_column:
            return (self.document_column,)
        return self.identifier_columns

    def creatable_columns(self, columns: Iterable[str]) -> tuple[str, ...]:
        """Configured columns that are absent and may be created in memory."""
        available = {str(column).strip() for column in columns}
        required = set(self.required_source_columns)
        return tuple(
            column
            for column in self.configured_columns
            if column not in available and column not in required
        )

    def validate_columns(self, columns: Iterable[str]) -> None:
        available = {str(column).strip() for column in columns}
        missing = [
            column for column in self.required_source_columns if column not in available
        ]
        if missing:
            raise ValueError(
                f"MID is missing required column(s): {missing}. Only the column "
                "that names each row's document must exist in the sheet; other "
                "configured columns are created when they are absent."
            )

    # ------------------------------------------------------------------
    # Rows
    # ------------------------------------------------------------------
    def observation_key(self, row: Mapping[str, Any]) -> tuple[str, str]:
        return clean_value(row.get(self.x_column)), clean_value(row.get(self.y_column))

    def observation_label(self, row: Mapping[str, Any]) -> str:
        """Name this row the way the user asked for in MID settings."""
        x_value, y_value = self.observation_key(row)
        document = self.document_name(row)
        _, formatter = ENTRY_LABEL_FORMATS[normalize_entry_label(self.entry_label)]
        label = clean_value(formatter(x_value, y_value, document))
        # Unassigned rows are still worth naming; fall back to the document.
        return label or document or "unidentified observation"

    def _identity_stem(self, row: Mapping[str, Any]) -> str:
        x_value, y_value = self.observation_key(row)
        if not (x_value or y_value):
            return ""
        return safe_filename_stem(f"{x_value}__{y_value}", fallback="")

    def document_name(self, row: Mapping[str, Any]) -> str:
        """The filename a row refers to, before any extension defaulting."""
        if self.document_column:
            return clean_value(row.get(self.document_column))
        return self._identity_stem(row)

    def document_stem(self, row: Mapping[str, Any]) -> str:
        return os.path.splitext(self.document_name(row))[0]

    def document_key(self, row: Mapping[str, Any]) -> str:
        """Stable answer to "which document is this row about?"."""
        return self.document_name(row)

    @property
    def uniqueness_columns(self) -> tuple[str, ...]:
        """Columns whose combined value should identify one observation.

        A document may host several observations, so the document alone is not
        an identity; the X/Y pair distinguishes them within it. Hierarchy
        fields are part of it too: a nested structure deliberately repeats
        the document and identifiers across its rows, one per level.

        Seam: if one document ever needs the same identity twice, add an
        ``occurrence`` column to the schema and append it here. Everything
        that checks for duplicates reads this property.
        """
        columns = [self.document_column] if self.document_column else []
        columns.extend(self.identifier_columns)
        columns.extend(self.hierarchy_columns)
        return tuple(dict.fromkeys(column for column in columns if column))

    def observation_identity(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        """This row's value for every :attr:`uniqueness_columns` column."""
        return tuple(
            clean_value(row.get(column)) for column in self.uniqueness_columns
        )

    def is_assigned(self, row: Mapping[str, Any]) -> bool:
        """True once every part of the identity has been filled in."""
        identity = self.observation_identity(row)
        return bool(identity) and all(identity)

    def observation_stem(self, row: Mapping[str, Any]) -> str:
        """Filename stem for this row's exported text.

        Always document-first, with the identifiers appended, so several
        observations taken from one document do not overwrite each other.
        """
        parts = [self.document_stem(row), *self.observation_key(row)]
        return safe_filename_stem(
            "__".join(part for part in parts if part), fallback="observation"
        )

    def document_candidates(self, row: Mapping[str, Any]) -> tuple[str, ...]:
        """Filenames to try for this row: as written, defaulting to ``.pdf``."""
        base_value = self.document_name(row)
        if not base_value:
            return ()
        _, extension = os.path.splitext(base_value)
        return (base_value if extension else f"{base_value}.pdf",)

    def format_type(self, row: Mapping[str, Any], default: int = -1) -> int:
        if not self.format_column:
            return default
        try:
            return int(clean_value(row.get(self.format_column)))
        except (TypeError, ValueError):
            return default
