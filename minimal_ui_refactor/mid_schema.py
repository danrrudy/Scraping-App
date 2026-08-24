"""Configurable column roles for Master Input Documents.

The schema deliberately describes only flat MID behavior. Legacy hierarchy
operations remain in ``mid_manager.py`` until that system is redesigned.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd


LEGACY_HIERARCHY_COLUMNS = ("stratobj", "obj", "goal", "metric")

LEGACY_SOURCE_COLUMNS = (
    "agency_yr",
    "agency",
    "year",
    "agid",
    "subagency",
    "stratobj",
    "obj",
    "goal",
    "metric",
    "PDF Page Number",
    "Format",
    "Format_Detail",
    "Results_DisplayFormat",
    "Table Name/Word Search Keyword",
    "Other Detail",
    "Format_Type",
    "Format_Type_Updated",
    "Page",
)

DEFAULT_MID_SCHEMA = {
    "xColumn": "agency",
    "yColumn": "year",
    "interactionColumns": list(LEGACY_HIERARCHY_COLUMNS),
    "documentColumn": "agency_yr",
    "pageColumn": "PDF Page Number",
    "formatColumn": "Format_Type_Updated",
    "keywordColumn": "Table Name/Word Search Keyword",
}

# These columns support the current review workflow. They are created in
# memory when absent, so a source MID does not need to contain them.
WORKFLOW_COLUMN_DEFAULTS = {
    "classification_scheme": "",
    "metric_status": "",
    "target": "",
    "actual": "",
    "years_to_evaluation": "",
    "_flag": False,
    "_no_metrics": False,
    "_gen": False,
    "_achieved": False,
    "_future_dated": False,
    "_aggregate": False,
    "notes": "",
    "reviewer_comments": "",
    "reviewer_status": "",
    "Page": "",
}

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _column_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [part.strip() for part in value.split(",")]
    elif isinstance(value, Iterable):
        values = [str(part).strip() for part in value]
    else:
        values = []
    return tuple(dict.fromkeys(value for value in values if value))


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


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

    x_column: str
    y_column: str
    interaction_columns: tuple[str, ...]
    document_column: str = ""
    page_column: str = ""
    format_column: str = ""
    keyword_column: str = ""

    @classmethod
    def legacy(cls) -> "MIDSchema":
        return cls.from_mapping(DEFAULT_MID_SCHEMA)

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "MIDSchema":
        return cls.from_mapping(settings.get("midSchema", DEFAULT_MID_SCHEMA))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "MIDSchema":
        data = dict(DEFAULT_MID_SCHEMA)
        if mapping:
            data.update(mapping)
        schema = cls(
            x_column=clean_value(data.get("xColumn")),
            y_column=clean_value(data.get("yColumn")),
            interaction_columns=_column_list(data.get("interactionColumns", [])),
            document_column=clean_value(data.get("documentColumn")),
            page_column=clean_value(data.get("pageColumn")),
            format_column=clean_value(data.get("formatColumn")),
            keyword_column=clean_value(data.get("keywordColumn")),
        )
        schema.validate_configuration()
        return schema

    def to_mapping(self) -> dict[str, Any]:
        return {
            "xColumn": self.x_column,
            "yColumn": self.y_column,
            "interactionColumns": list(self.interaction_columns),
            "documentColumn": self.document_column,
            "pageColumn": self.page_column,
            "formatColumn": self.format_column,
            "keywordColumn": self.keyword_column,
        }

    def validate_configuration(self) -> None:
        if not self.document_column and not (self.x_column and self.y_column):
            raise ValueError(
                "Configure a document filename column, or both X and Y "
                "identifier columns for a filename to be composed from."
            )
        if self.x_column and self.x_column == self.y_column:
            raise ValueError("X and Y identifier columns must be different.")
        if not self.interaction_columns:
            raise ValueError("Select at least one MID column to interact with.")
        if not self.document_column and self.editable_identifiers:
            # With no filename column the X/Y pair *is* the filename, so making
            # it editable would repoint the row at a different document.
            raise ValueError(
                "Without a document filename column the X/Y identifiers name "
                "the file, so they cannot also be editable fields: "
                f"{sorted(self.editable_identifiers)}"
            )

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

    def observation_key(self, row: Mapping[str, Any]) -> tuple[str, str]:
        return clean_value(row.get(self.x_column)), clean_value(row.get(self.y_column))

    def observation_label(self, row: Mapping[str, Any]) -> str:
        x_value, y_value = self.observation_key(row)
        if x_value or y_value:
            return f"{x_value} — {y_value}"
        # Unassigned rows are still worth naming; fall back to the document.
        return self.document_name(row) or "unidentified observation"

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
        an identity; the X/Y pair distinguishes them within it.

        Seam: if one document ever needs the same X/Y pair twice (two tables
        for the same agency-year, say), add an ``occurrence`` column to the
        schema and append it here. Everything that checks for duplicates reads
        this property.
        """
        columns = [self.document_column] if self.document_column else []
        columns.extend(self.identifier_columns)
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
        base_value = self.document_name(row)
        if not base_value:
            return ()
        _, extension = os.path.splitext(base_value)
        candidates = [base_value if extension else f"{base_value}.pdf"]

        # Compatibility with legacy agency-year values whose PDFs use underscores.
        underscored = candidates[0].replace("-", "_")
        if underscored != candidates[0]:
            candidates.append(underscored)
        return tuple(dict.fromkeys(candidates))

    def format_type(self, row: Mapping[str, Any], default: int = -1) -> int:
        if not self.format_column:
            return default
        try:
            return int(clean_value(row.get(self.format_column)))
        except (TypeError, ValueError):
            return default

    def is_legacy_hierarchy_compatible(self, columns: Iterable[str]) -> bool:
        available = set(columns)
        required = set(LEGACY_HIERARCHY_COLUMNS) | {"agency", "year"}
        return required.issubset(available)
