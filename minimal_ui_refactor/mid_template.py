"""Build an empty MID from the documents sitting in a folder.

Starting a project means writing a spreadsheet with one row per document
before any reviewing can begin. When the documents are already in the data
directory, that list is just what is in the folder, and typing it out by hand
is both slow and a source of filenames that do not quite match.

The rows carry the filename **without its extension**, because that is what
the application expects: a MID entry with no extension is taken to mean
``.pdf``. One row per document is a starting point, not a rule — a document
carrying several observations gets its row duplicated by hand afterwards.

Qt-free: this decides what goes in the file, the settings dialog asks for it.
"""

from __future__ import annotations

import os

import pandas as pd

#: Sheet the template is written to. The application reads a sheet by name, so
#: this is also what gets stored as the MID's sheet setting.
DEFAULT_SHEET_NAME = "MID"

#: Used when the MID schema does not name a document column.
DEFAULT_DOCUMENT_COLUMN = "Filename"

#: Files that are not documents even though they sit beside them: Office lock
#: files, and anything hidden by the convention of a leading dot.
def _is_listable(name: str) -> bool:
    return bool(name) and not name.startswith(("~$", "."))


def document_stems(directory) -> list[str]:
    """Every document in ``directory``, without its extension.

    Not recursive, because the application does not search subfolders either —
    it looks for each row's document directly in the data directory. That also
    keeps the ``accepted`` and ``rejected`` folders the application creates out
    of the listing, since those are directories rather than files.

    Sorted case-insensitively and de-duplicated: two files differing only by
    extension reduce to one row, which is what a MID wants.
    """
    if not directory or not os.path.isdir(directory):
        return []

    stems = []
    for name in os.listdir(directory):
        if not _is_listable(name):
            continue
        if not os.path.isfile(os.path.join(directory, name)):
            continue
        stem = os.path.splitext(name)[0].strip()
        if stem:
            stems.append(stem)

    # dict.fromkeys keeps the first of each duplicate, having sorted first so
    # that "first" is predictable rather than whatever the filesystem said.
    return list(dict.fromkeys(sorted(stems, key=lambda value: value.lower())))


def write_template(
    path,
    stems,
    column: str = DEFAULT_DOCUMENT_COLUMN,
    sheet_name: str = DEFAULT_SHEET_NAME,
) -> str:
    """Write a one-column spreadsheet of ``stems`` to ``path``.

    ``.csv`` is written as CSV and anything else as an Excel workbook, matching
    what the MID loader will accept back. Returns the path written.
    """
    column = str(column or DEFAULT_DOCUMENT_COLUMN).strip() or DEFAULT_DOCUMENT_COLUMN
    frame = pd.DataFrame({column: list(stems)})

    path = str(path)
    if path.lower().endswith(".csv"):
        frame.to_csv(path, index=False)
    else:
        with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
            frame.to_excel(writer, index=False, sheet_name=sheet_name)
    return path


def document_column_for(settings) -> str:
    """The column the configured schema names for the document filename.

    Using the configured name rather than a fixed one means the generated file
    matches the schema already in force, and can be opened without changing
    anything else.
    """
    schema = (settings or {}).get("midSchema") or {}
    column = str(schema.get("documentColumn") or "").strip()
    return column or DEFAULT_DOCUMENT_COLUMN
