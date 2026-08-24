from pathlib import Path

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
@pytest.mark.current_schema
def test_sidebar_fields_commit_to_mid_and_reload(application_factory):
    window = application_factory("User")
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
def test_user_accept_and_reject_write_to_isolated_output_directories(
    application_factory, monkeypatch
):
    window = application_factory("User")
    monkeypatch.setattr(window, "next_mid_entry", lambda: None)
    window.document_session.page_text_cache = ["First page", "Second page"]

    # Export names are document-first so observations taken from one file
    # cannot overwrite each other.
    name = "AGENCY-2024__Agency__2024_full.txt"

    window.accept_scrape()
    accepted = Path(window.accept_dir) / name
    assert accepted.read_text(encoding="utf-8") == "First page\n\nSecond page"

    window.reject_scrape()
    rejected = Path(window.reject_dir) / name
    assert rejected.read_text(encoding="utf-8") == "First page\n\nSecond page"

