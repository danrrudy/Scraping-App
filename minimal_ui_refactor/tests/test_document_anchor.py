"""The document filename anchors a MID row; X/Y identifiers are optional.

Only the column naming each row's document has to exist in the sheet. X/Y may
be absent, blank, or listed as editable fields so they can be assigned in the
app.
"""

import pandas as pd
import pytest

from mid_schema import MIDSchema


FILENAME_SCHEMA = {
    "xColumn": "agency",
    "yColumn": "year",
    "interactionColumns": ["agency", "year", "finding"],
    "documentColumn": "source_file",
    "pageColumn": "",
    "formatColumn": "",
    "keywordColumn": "",
}


def _filename_rows(*documents, **overrides):
    rows = []
    for document in documents:
        row = {"source_file": document, "agency": "", "year": "", "finding": ""}
        row.update(overrides)
        rows.append(row)
    return rows


# ----------------------------------------------------------------------
# Schema configuration
# ----------------------------------------------------------------------
def test_a_filename_column_is_enough_to_configure_a_schema():
    schema = MIDSchema.from_mapping(
        {
            "xColumn": "",
            "yColumn": "",
            "interactionColumns": ["finding"],
            "documentColumn": "source_file",
        }
    )

    assert schema.identifier_columns == ()
    assert schema.required_source_columns == ("source_file",)


def test_identifiers_may_be_editable_when_a_filename_column_exists():
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)

    assert schema.editable_identifiers == ("agency", "year")
    assert schema.required_source_columns == ("source_file",)


def test_identifiers_stay_read_only_when_they_compose_the_filename():
    with pytest.raises(ValueError, match="cannot also be editable fields"):
        MIDSchema.from_mapping(
            {
                "xColumn": "agency",
                "yColumn": "year",
                "interactionColumns": ["agency", "finding"],
                "documentColumn": "",
            }
        )


def test_a_schema_with_no_anchor_at_all_is_rejected():
    with pytest.raises(ValueError, match="document filename column"):
        MIDSchema.from_mapping(
            {
                "xColumn": "",
                "yColumn": "",
                "interactionColumns": ["finding"],
                "documentColumn": "",
            }
        )


def test_only_the_anchor_column_must_exist_in_the_sheet():
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)

    schema.validate_columns(["source_file"])
    assert set(schema.creatable_columns(["source_file"])) == {
        "agency",
        "year",
        "finding",
    }

    with pytest.raises(ValueError, match="missing required column"):
        schema.validate_columns(["agency", "year", "finding"])


# ----------------------------------------------------------------------
# Row identity
# ----------------------------------------------------------------------
def test_label_and_stem_fall_back_to_the_document_when_unassigned():
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)
    row = {"source_file": "Report 2024.pdf", "agency": "", "year": ""}

    assert schema.document_name(row) == "Report 2024.pdf"
    assert schema.document_key(row) == "Report 2024.pdf"
    assert schema.observation_label(row) == "Report 2024.pdf"
    assert schema.observation_stem(row) == "Report_2024"
    assert schema.observation_identity(row) == ("Report 2024.pdf", "", "")
    assert schema.is_assigned(row) is False
    assert schema.document_candidates(row) == ("Report 2024.pdf",)


def test_assigned_identifiers_take_over_the_label_and_stem():
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)
    row = {"source_file": "Report 2024.pdf", "agency": "DOJ", "year": "2024"}

    assert schema.observation_label(row) == "DOJ — 2024"
    # Document first, then the identifiers: several observations taken from one
    # file must not overwrite each other on export.
    assert schema.observation_stem(row) == "Report_2024__DOJ__2024"
    # The document is still where the file comes from.
    assert schema.document_candidates(row) == ("Report 2024.pdf",)


def test_a_row_naming_no_document_offers_no_candidates():
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)

    assert schema.document_candidates({"source_file": "", "agency": "", "year": ""}) == ()


def test_a_filename_without_an_extension_still_resolves_to_a_pdf():
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)

    assert schema.document_candidates({"source_file": "AGENCY-2024"}) == (
        "AGENCY-2024.pdf",
        "AGENCY_2024.pdf",
    )


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------
def test_missing_editable_columns_are_created_rather_than_rejected(
    manager_factory, mid_path_factory
):
    from mid_manager import MIDManager

    path = mid_path_factory(_filename_rows("A.pdf"))
    # Drop everything but the anchor from the sheet.
    frame = pd.read_excel(path)
    frame[["source_file"]].to_excel(path, index=False, sheet_name="MID")

    manager = MIDManager(path, schema=MIDSchema.from_mapping(FILENAME_SCHEMA))

    assert manager.df.at[0, "source_file"] == "A.pdf"
    for column in ("agency", "year", "finding"):
        assert manager.df.at[0, column] == ""


def test_blank_identifiers_load_when_a_document_anchors_the_row(
    mid_path_factory,
):
    from mid_manager import MIDManager

    path = mid_path_factory(_filename_rows("A.pdf", "B.pdf"))
    manager = MIDManager(path, schema=MIDSchema.from_mapping(FILENAME_SCHEMA))

    assert len(manager.df) == 2
    assert manager.observation_key(0) == ("", "")
    assert manager.document_key(0) == "A.pdf"


def test_a_blank_document_is_rejected(mid_path_factory):
    from mid_manager import MIDManager

    rows = _filename_rows("A.pdf", "")
    # An entirely empty row does not survive an Excel round trip, so give the
    # unanchored row some content.
    rows[1]["finding"] = "orphaned note"
    path = mid_path_factory(rows)

    with pytest.raises(ValueError, match="must name a document"):
        MIDManager(path, schema=MIDSchema.from_mapping(FILENAME_SCHEMA))


def test_repeated_identifiers_are_allowed_while_they_are_still_editable(
    mid_path_factory,
):
    from mid_manager import MIDManager

    rows = _filename_rows("A.pdf", "B.pdf")
    for row in rows:
        row["agency"], row["year"] = "DOJ", "2024"

    path = mid_path_factory(rows)
    manager = MIDManager(path, schema=MIDSchema.from_mapping(FILENAME_SCHEMA))

    assert len(manager.df) == 2


def test_the_same_pair_in_two_documents_is_not_a_duplicate(mid_path_factory):
    """Identity is (document, X, Y), so one pair may appear in several files."""
    from mid_manager import MIDManager

    rows = _filename_rows("A.pdf", "B.pdf")
    for row in rows:
        row["agency"], row["year"] = "DOJ", "2024"

    path = mid_path_factory(rows)
    manager = MIDManager(path, schema=MIDSchema.from_mapping(FILENAME_SCHEMA))

    assert manager.duplicate_observation_positions() == []


def test_the_same_pair_twice_in_one_document_is_reported_not_fatal(
    mid_path_factory, caplog
):
    from mid_manager import MIDManager

    rows = _filename_rows("A.pdf", "A.pdf", "B.pdf")
    for row in rows:
        row["agency"], row["year"] = "DOJ", "2024"

    path = mid_path_factory(rows)
    # Loading must succeed: identifiers are assigned in the app, so a MID saved
    # mid-assignment has to be able to reopen.
    manager = MIDManager(path, schema=MIDSchema.from_mapping(FILENAME_SCHEMA))

    assert manager.duplicate_observation_positions() == [0, 1]
    assert manager.is_duplicate_observation(0) is True
    assert manager.is_duplicate_observation(2) is False


def test_unassigned_rows_do_not_count_as_duplicates(mid_path_factory):
    from mid_manager import MIDManager

    read_only = dict(FILENAME_SCHEMA, interactionColumns=["finding"])
    path = mid_path_factory(_filename_rows("A.pdf", "B.pdf", "C.pdf"))

    manager = MIDManager(path, schema=MIDSchema.from_mapping(read_only))
    assert len(manager.df) == 3


# ----------------------------------------------------------------------
# In the application
# ----------------------------------------------------------------------
qt = pytest.importorskip("PyQt5", reason="PyQt5 is required for application tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")


@pytest.mark.qt
@pytest.mark.integration
def test_a_filename_only_mid_loads_and_identifiers_are_editable(application_factory):
    window = application_factory(
        rows=_filename_rows("REPORT_A.pdf", "REPORT_B.pdf"),
        schema=FILENAME_SCHEMA,
        documents={"REPORT_A.pdf", "REPORT_B.pdf"},
    )

    # The row loaded even though it carries no identifiers.
    assert window.current_document_key == "REPORT_A.pdf"
    assert set(window.ui.field_texts()) == {"agency", "year", "finding"}

    # X/Y are editable fields, so they are not also read-only info labels.
    assert set(window.ui.left.info_labels) == {"document", "observation", "page"}

    window.ui.set_field_text("agency", "DOJ")
    window.ui.set_field_text("year", "2024")
    window._commit_sidebar_fields()

    row = window.mid_manager.master_df.iloc[0]
    assert row["agency"] == "DOJ"
    assert row["year"] == "2024"
    assert row["source_file"] == "REPORT_A.pdf"


@pytest.mark.qt
@pytest.mark.integration
def test_assigned_identifiers_survive_navigating_away_and_back(application_factory):
    window = application_factory(
        rows=_filename_rows("REPORT_A.pdf", "REPORT_B.pdf"),
        schema=FILENAME_SCHEMA,
        documents={"REPORT_A.pdf", "REPORT_B.pdf"},
    )

    window.ui.set_field_text("agency", "DOJ")
    window.next_mid_entry()
    assert window.current_document_key == "REPORT_B.pdf"
    assert window.ui.field_text("agency") == ""

    window.prev_mid_entry()
    assert window.current_document_key == "REPORT_A.pdf"
    assert window.ui.field_text("agency") == "DOJ"


@pytest.mark.qt
@pytest.mark.integration
def test_exported_text_is_named_after_the_document_when_unassigned(
    application_factory, tmp_path, monkeypatch
):
    from pathlib import Path

    window = application_factory(
        rows=_filename_rows("REPORT_A.pdf"),
        schema=FILENAME_SCHEMA,
        documents={"REPORT_A.pdf"},
    )
    monkeypatch.setattr(window, "next_mid_entry", lambda: None)
    window.page_text_cache = ["Only page"]

    window.accept_scrape()
    assert (Path(window.accept_dir) / "REPORT_A_full.txt").is_file()


@pytest.mark.qt
@pytest.mark.integration
def test_export_names_keep_observations_from_one_file_apart(
    application_factory, monkeypatch
):
    from pathlib import Path

    window = application_factory(
        rows=_filename_rows("REPORT_A.pdf"),
        schema=FILENAME_SCHEMA,
        documents={"REPORT_A.pdf"},
    )
    monkeypatch.setattr(window, "next_mid_entry", lambda: None)

    window.ui.set_field_text("agency", "DOJ")
    window.ui.set_field_text("year", "2024")
    window._commit_sidebar_fields()
    window.load_mid_entry_document()

    window.accept_scrape()
    assert (Path(window.accept_dir) / "REPORT_A__DOJ__2024_full.txt").is_file()
