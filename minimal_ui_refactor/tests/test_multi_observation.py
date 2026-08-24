"""Several observations recorded from one document.

Covers the shared ``DocumentSession``, the row-splitting control, the live
restrictions, and the duplicate-identity warning.
"""

import pytest

from mid_schema import MIDSchema
from test_document_anchor import FILENAME_SCHEMA, _filename_rows


pytest.importorskip("PyQt5", reason="PyQt5 is required for application tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")


@pytest.fixture
def one_document_app(application_factory):
    """An app whose MID holds three observations, two of them on one file."""

    def build(mode="User"):
        return application_factory(
            mode,
            rows=_filename_rows("REPORT_A.pdf", "REPORT_A.pdf", "REPORT_B.pdf"),
            schema=FILENAME_SCHEMA,
            documents={"REPORT_A.pdf", "REPORT_B.pdf"},
        )

    return build


# ----------------------------------------------------------------------
# Shared document session
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_rows_on_one_document_share_a_session(one_document_app):
    window = one_document_app()
    first_session = window.document_session

    window.next_mid_entry()
    assert window.document_session is first_session, "session was rebuilt"

    window.next_mid_entry()
    assert window.document_session is not first_session
    assert window.current_document_key == "REPORT_B.pdf"


@pytest.mark.qt
@pytest.mark.integration
def test_the_previous_document_is_closed_when_the_session_changes(one_document_app):
    window = one_document_app()
    first_session = window.document_session

    window.mid_manager.current_index = 2
    window.load_mid_entry_document()

    assert first_session.doc is None
    assert window.document_session.doc is not None


@pytest.mark.qt
@pytest.mark.integration
def test_scraped_text_is_shared_between_observations_in_one_file(one_document_app):
    window = one_document_app()
    window.ui.set_content("Corrected page text")
    window.next_page()  # writes the panel back into the shared cache
    window.prev_page()

    window.next_mid_entry()
    assert window.current_document_key == "REPORT_A.pdf"
    assert "Corrected page text" in window.ui.content()


@pytest.mark.qt
@pytest.mark.integration
def test_each_row_still_opens_on_its_own_page(one_document_app):
    window = one_document_app()
    window.mid_manager.set_value(1, "Page", 2)

    window.next_mid_entry()
    assert window.current_page_index == 1
    assert window.current_page_number() == 2


# ----------------------------------------------------------------------
# Splitting a document into observations
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_adding_an_observation_clones_the_document_and_clears_the_fields(
    one_document_app,
):
    window = one_document_app()
    window.ui.set_field_text("agency", "DOJ")
    window.ui.set_field_text("year", "2024")
    window.ui.set_field_text("finding", "First finding")
    window.next_page()

    before = len(window.mid_manager.master_df)
    window.add_observation_from_document()

    assert len(window.mid_manager.master_df) == before + 1
    assert window.mid_manager.current_index == 1
    # Same document, blank identifiers, on the page we were looking at.
    assert window.current_document_key == "REPORT_A.pdf"
    assert window.ui.field_texts() == {"agency": "", "year": "", "finding": ""}
    assert window.current_page_number() == 2

    # The observation we came from kept its values.
    original = window.mid_manager.master_df.iloc[0]
    assert original["agency"] == "DOJ"
    assert original["finding"] == "First finding"


@pytest.mark.qt
@pytest.mark.integration
def test_adding_an_observation_reuses_the_open_session(one_document_app):
    window = one_document_app()
    session = window.document_session

    window.add_observation_from_document()
    assert window.document_session is session


@pytest.mark.qt
@pytest.mark.integration
def test_a_new_observation_is_marked_generated(one_document_app):
    window = one_document_app()
    window.add_observation_from_document()

    assert bool(window.mid_manager.master_df.iloc[1]["_gen"]) is True


@pytest.mark.qt
def test_the_control_exists_only_where_rows_may_be_edited(one_document_app):
    window = one_document_app("User")
    controls = window.ui.left.control_buttons
    assert "add_observation" in controls

    window.ui.apply_mode("user")
    assert controls["add_observation"].isVisible()
    window.ui.apply_mode("reviewer")
    assert not controls["add_observation"].isVisible()


# ----------------------------------------------------------------------
# Counter and duplicate warning
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_the_sidebar_counts_observations_within_the_document(one_document_app):
    window = one_document_app()
    labels = window.ui.left.info_labels

    assert labels["observation"].text() == "Observation: 1 of 2 in this document"

    window.next_mid_entry()
    assert labels["observation"].text() == "Observation: 2 of 2 in this document"

    window.next_mid_entry()
    assert labels["observation"].text() == "Observation: 1 of 1 in this document"


@pytest.mark.qt
@pytest.mark.integration
def test_a_colliding_identity_warns_without_blocking(one_document_app):
    window = one_document_app()
    assert window.ui.warning_text() == ""

    # Give both observations on REPORT_A the same identifiers.
    for position in (0, 1):
        window.mid_manager.set_value(position, "agency", "DOJ")
        window.mid_manager.set_value(position, "year", "2024")

    window.update_info_labels()
    assert "same document and identifiers" in window.ui.warning_text()

    window.mid_manager.set_value(1, "year", "2025")
    window.update_info_labels()
    assert window.ui.warning_text() == ""


# ----------------------------------------------------------------------
# Live restrictions
# ----------------------------------------------------------------------
@pytest.mark.qt
def test_the_live_restrictions_are_offered_in_both_working_modes(one_document_app):
    window = one_document_app("Dev")
    assert "same_document" in window.restriction_options()
    assert "duplicate_observation" in window.restriction_options()

    window.mode = "reviewer"
    assert "same_document" in window.restriction_options()
    assert "duplicate_observation" in window.restriction_options()


@pytest.mark.qt
@pytest.mark.integration
def test_restricting_to_the_current_document_keeps_only_its_rows(one_document_app):
    window = one_document_app("Dev")

    window.restrict_to_live_selection("same_document")
    assert window.mid_manager.view_indices == [0, 1]


@pytest.mark.qt
@pytest.mark.integration
def test_restricting_to_duplicates_walks_the_colliding_rows(one_document_app):
    window = one_document_app("Dev")
    for position in (0, 1):
        window.mid_manager.set_value(position, "agency", "DOJ")
        window.mid_manager.set_value(position, "year", "2024")

    window.restrict_to_live_selection("duplicate_observation")
    assert window.mid_manager.view_indices == [0, 1]


@pytest.mark.qt
@pytest.mark.integration
def test_restricting_to_duplicates_reports_when_there_are_none(
    one_document_app, monkeypatch
):
    from PyQt5.QtWidgets import QMessageBox

    window = one_document_app("Dev")
    shown = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kwargs: shown.append(args)
    )

    window.restrict_to_live_selection("duplicate_observation")
    assert shown, "the user was not told there was nothing to review"
    assert window.mid_manager.view_indices == [0, 1, 2]


# ----------------------------------------------------------------------
# The occurrence seam
# ----------------------------------------------------------------------
def test_identity_is_document_plus_identifiers():
    """Adding an occurrence column later means extending this one property."""
    schema = MIDSchema.from_mapping(FILENAME_SCHEMA)

    assert schema.uniqueness_columns == ("source_file", "agency", "year")
    assert schema.observation_identity(
        {"source_file": "A.pdf", "agency": "DOJ", "year": "2024"}
    ) == ("A.pdf", "DOJ", "2024")
