import pytest


pytest.importorskip("PyQt5", reason="PyQt5 is required for application smoke tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")


def _controls(window):
    """Sidebar buttons keyed by the action id declared in ui.left_sidebar."""
    return window.ui.left.control_buttons


@pytest.mark.qt
@pytest.mark.parametrize("mode", ["User", "Dev", "Reviewer"])
def test_main_window_constructs_in_each_supported_mode(application_factory, mode):
    window = application_factory(mode)

    assert window.centralWidget() is not None
    assert window.mode == mode.lower()
    assert set(window.ui.field_texts()) == {"stratobj", "obj", "goal", "metric"}
    assert window.page_indices == [0, 1]
    assert "Page 1" in window.ui.content()


@pytest.mark.qt
def test_mode_specific_controls_have_expected_visibility(application_factory):
    window = application_factory("User")
    controls = _controls(window)
    reviewer_group = window.ui.left.reviewer_group

    assert controls["delete_entry"].isVisible()
    assert not controls["run_audit"].isVisible()
    assert not reviewer_group.isVisible()

    window.mode = "dev"
    window.update_mode_ui()
    assert controls["run_audit"].isVisible()
    assert not reviewer_group.isVisible()

    window.mode = "reviewer"
    window.update_mode_ui()
    assert not controls["run_audit"].isVisible()
    assert reviewer_group.isVisible()


@pytest.mark.qt
def test_navigation_buttons_keep_intended_shortcuts(application_factory):
    window = application_factory("User")
    controls = _controls(window)

    assert controls["next_entry"].shortcut().toString() == "Ctrl+Right"
    assert controls["previous_entry"].shortcut().toString() == "Ctrl+Left"
    assert controls["jump_to_entry"].shortcut().toString() == "Ctrl+O"


@pytest.mark.qt
@pytest.mark.integration
def test_page_navigation_updates_current_page_and_text(application_factory):
    window = application_factory("User")

    window.next_page()
    assert window.current_page_index == 1
    assert "Page 2" in window.ui.content()

    window.prev_page()
    assert window.current_page_index == 0
    assert "Page 1" in window.ui.content()


@pytest.mark.qt
@pytest.mark.integration
def test_sidebar_fields_commit_to_mid_and_reload(application_factory):
    window = application_factory(
        "User",
        extra_settings={
            "checkboxes": [
                {"column": "_flag"},
                {
                    "column": "_future_dated",
                    "counter": {"column": "years_to_evaluation"},
                },
            ]
        },
    )
    window.ui.set_field_text("goal", "Edited goal")
    window.ui.set_notes_text("Edited note")
    window.ui.set_toggle("flag", True)
    window.ui.set_toggle("future_dated", True)
    window.ui.set_counter("future_dated", 3)

    window._commit_sidebar_fields()

    row = window.mid_manager.master_df.iloc[0]
    assert row["goal"] == "Edited goal"
    assert row["notes"] == "Edited note"
    assert bool(row["_flag"]) is True
    assert bool(row["_future_dated"]) is True
    assert row["years_to_evaluation"] == "3"

    window.ui.clear_fields()
    window.load_mid_fields_from_row()
    assert window.ui.field_text("goal") == "Edited goal"
    assert window.ui.counter("future_dated") == 3


@pytest.mark.qt
@pytest.mark.integration
def test_only_the_flag_checkbox_is_built_in(application_factory):
    window = application_factory("User")

    assert list(window.ui.left.toggle_boxes) == ["flag"]
    assert window.ui.left.counter_boxes == {}


# ----------------------------------------------------------------------
# Reviewer verdicts
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_reviewer_accept_records_the_verdict_and_moves_on(
    application_factory, mid_row_factory
):
    window = application_factory(
        "Reviewer", rows=[mid_row_factory(), mid_row_factory(metric="Two")]
    )
    window.ui.set_reviewer_notes_text("Looks right")

    window.accept_scrape()

    row = window.mid_manager.master_df.iloc[0]
    assert row["reviewer_status"] == "ACCEPT"
    assert row["reviewer_comments"] == "Looks right"
    assert bool(row["_flag"]) is False
    assert window.mid_manager.current_index == 1


@pytest.mark.qt
@pytest.mark.integration
def test_reviewer_reject_also_flags_the_row(application_factory, mid_row_factory):
    window = application_factory(
        "Reviewer", rows=[mid_row_factory(), mid_row_factory(metric="Two")]
    )

    window.reject_scrape()

    row = window.mid_manager.master_df.iloc[0]
    assert row["reviewer_status"] == "REJECT"
    assert bool(row["_flag"]) is True
    assert window.mid_manager.current_index == 1


@pytest.mark.qt
@pytest.mark.integration
def test_verdicts_are_ignored_outside_reviewer_mode(application_factory):
    """The buttons do not exist there, so a call is a bug, not a user action."""
    window = application_factory("User")

    window.accept_scrape()
    window.reject_scrape()

    row = window.mid_manager.master_df.iloc[0]
    assert row["reviewer_status"] == ""
    assert bool(row["_flag"]) is False
    assert window.mid_manager.current_index == 0


@pytest.mark.qt
def test_the_data_directory_holds_nothing_but_documents(application_factory):
    """No accepted/ or rejected/ working folders are created beside the PDFs."""
    import os

    window = application_factory("User")
    entries = os.listdir(window.settings["dataDirectory"])

    assert entries == ["AGENCY_2024.pdf"]
