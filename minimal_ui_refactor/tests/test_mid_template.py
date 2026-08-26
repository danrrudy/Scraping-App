"""Generating a starter MID from the documents in a folder."""

import os

import pandas as pd
import pytest

import mid_template
from mid_template import (
    DEFAULT_DOCUMENT_COLUMN,
    DEFAULT_SHEET_NAME,
    document_column_for,
    document_stems,
    write_template,
)


@pytest.fixture
def documents(tmp_path):
    """A data directory holding a few documents, as the application makes it."""

    def build(names=("Beta 2023.pdf", "alpha 2021.pdf", "Gamma 2022.pdf")):
        directory = tmp_path / "data"
        directory.mkdir(exist_ok=True)
        for name in names:
            (directory / name).write_bytes(b"%PDF-1.4\n")
        return directory

    return build


# ----------------------------------------------------------------------
# Listing
# ----------------------------------------------------------------------
def test_extensions_are_stripped(documents):
    """A MID row with no extension is taken to mean .pdf."""
    assert document_stems(documents()) == ["alpha 2021", "Beta 2023", "Gamma 2022"]


def test_rows_are_sorted_case_insensitively(documents):
    directory = documents(("zeta.pdf", "Alpha.pdf", "mid.pdf"))
    assert document_stems(directory) == ["Alpha", "mid", "zeta"]


def test_the_working_subfolders_are_not_listed(documents):
    """The application creates accepted/ and rejected/ inside the data dir."""
    directory = documents()
    for name in ("accepted", "rejected"):
        (directory / name).mkdir()

    stems = document_stems(directory)

    assert "accepted" not in stems and "rejected" not in stems


def test_the_search_does_not_descend(documents):
    """The application looks for each row's document directly in the folder."""
    directory = documents()
    nested = directory / "archive"
    nested.mkdir()
    (nested / "buried.pdf").write_bytes(b"%PDF-1.4\n")

    assert "buried" not in document_stems(directory)


def test_office_lock_files_and_hidden_files_are_skipped(documents):
    directory = documents()
    (directory / "~$open in excel.xlsx").write_text("lock")
    (directory / ".DS_Store").write_text("junk")

    stems = document_stems(directory)

    assert not any(stem.startswith(("~$", ".")) for stem in stems)
    assert len(stems) == 3


def test_two_files_differing_only_by_extension_make_one_row(documents):
    directory = documents(("report.pdf", "report.txt", "other.pdf"))
    assert document_stems(directory) == ["other", "report"]


def test_a_missing_directory_lists_nothing(tmp_path):
    assert document_stems(tmp_path / "not-there") == []
    assert document_stems("") == []
    assert document_stems(None) == []


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------
def test_the_workbook_has_one_named_column(tmp_path, documents):
    target = tmp_path / "MID_template.xlsx"

    write_template(target, document_stems(documents()), column="Filename")

    frame = pd.read_excel(target, sheet_name=DEFAULT_SHEET_NAME)
    assert list(frame.columns) == ["Filename"]
    assert list(frame["Filename"]) == ["alpha 2021", "Beta 2023", "Gamma 2022"]


def test_a_csv_target_is_written_as_a_csv(tmp_path, documents):
    target = tmp_path / "MID_template.csv"

    write_template(target, document_stems(documents()))

    frame = pd.read_csv(target)
    assert list(frame.columns) == [DEFAULT_DOCUMENT_COLUMN]
    assert len(frame) == 3


def test_the_column_comes_from_the_configured_schema():
    settings = {"midSchema": {"documentColumn": "source_file"}}
    assert document_column_for(settings) == "source_file"


@pytest.mark.parametrize(
    "settings",
    [{}, None, {"midSchema": {}}, {"midSchema": {"documentColumn": "  "}}],
)
def test_an_unset_document_column_falls_back(settings):
    assert document_column_for(settings) == DEFAULT_DOCUMENT_COLUMN


def test_the_generated_file_loads_as_a_mid(tmp_path, documents, silent_logger):
    """The point of the exercise: it must be openable by the application."""
    import mid_manager as mid_manager_module
    from mid_manager import MIDManager
    from mid_schema import MIDSchema

    target = tmp_path / "MID_template.xlsx"
    write_template(target, document_stems(documents()), column="Filename")

    schema = MIDSchema.from_mapping(
        {
            "documentColumn": "Filename",
            "xColumn": "",
            "yColumn": "",
            "interactionColumns": ["notes"],
        }
    )
    mid_manager_module.setup_logger = lambda: silent_logger
    manager = MIDManager(str(target), sheet_name=DEFAULT_SHEET_NAME, schema=schema)

    assert len(manager.df) == 3
    # Stored without an extension, and resolved to a .pdf when the row is
    # opened. That is exactly why the rows are written without one.
    assert manager.document_key(0) == "alpha 2021"
    assert "alpha 2021.pdf" in manager.document_candidates(0)


# ----------------------------------------------------------------------
# Through the settings dialog
# ----------------------------------------------------------------------
@pytest.mark.qt
def test_the_button_writes_a_file_and_selects_it(
    qtbot, tmp_path, documents, monkeypatch
):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox

    from app_settings import default_settings
    from settings_window import SettingsDialog

    directory = documents()
    target = tmp_path / "generated.xlsx"

    settings = dict(default_settings)
    settings["dataDirectory"] = str(directory)
    settings["midSchema"] = dict(settings["midSchema"], documentColumn="Filename")

    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    dialog.generate_mid_button.click()

    assert target.exists()
    assert dialog.inputs["MIDLocation"].text() == str(target)
    assert dialog.inputs["MIDSheetName"].text() == DEFAULT_SHEET_NAME


@pytest.mark.qt
def test_an_empty_data_directory_writes_nothing(qtbot, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox

    from app_settings import default_settings
    from settings_window import SettingsDialog

    empty = tmp_path / "empty"
    empty.mkdir()
    settings = dict(default_settings)
    settings["dataDirectory"] = str(empty)

    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    # If the save dialog is reached at all, the guard did not work.
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *a, **k: pytest.fail("asked where to save with nothing to write"),
    )

    dialog.generate_mid_button.click()

    assert warned


@pytest.mark.qt
def test_cancelling_the_save_dialog_changes_nothing(
    qtbot, tmp_path, documents, monkeypatch
):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox

    from app_settings import default_settings
    from settings_window import SettingsDialog

    settings = dict(default_settings)
    settings["dataDirectory"] = str(documents())
    settings["MIDLocation"] = "original.xlsx"

    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    dialog.generate_mid_button.click()

    assert dialog.inputs["MIDLocation"].text() == "original.xlsx"


@pytest.mark.qt
def test_the_button_sits_with_the_mid_controls(qtbot):
    """Asked for "near the existing MID controls", so assert the position."""
    from PyQt5.QtWidgets import QFormLayout

    from app_settings import default_settings
    from settings_window import SettingsDialog

    dialog = SettingsDialog(dict(default_settings))
    qtbot.addWidget(dialog)

    form = dialog.findChild(QFormLayout)
    rows = [
        form.itemAt(index, QFormLayout.FieldRole)
        for index in range(form.rowCount())
    ]
    positions = {}
    for index, item in enumerate(rows):
        if item is None:
            continue
        if item.widget() is dialog.generate_mid_button:
            positions["button"] = index
        if item.widget() is dialog.inputs.get("MIDSheetName"):
            positions["sheet"] = index

    assert "button" in positions and "sheet" in positions
    # Immediately after the sheet selector, which is the last MID control.
    assert positions["button"] == positions["sheet"] + 1
