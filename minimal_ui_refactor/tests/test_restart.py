"""Restarting the application and coming back to the same MID row."""

import pytest


pytest.importorskip("PyQt5", reason="PyQt5 is required for application tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")

from PyQt5.QtWidgets import QMessageBox  # noqa: E402

import scraping_helper as application_module  # noqa: E402
from scraping_helper import RESUME_FLAG, TextScrapingReviewApp  # noqa: E402


@pytest.fixture
def three_row_app(application_factory, mid_row_factory):
    def build(mode="User"):
        return application_factory(
            mode,
            rows=[
                mid_row_factory(metric="One"),
                mid_row_factory(metric="Two", Page=2),
                mid_row_factory(metric="Three"),
            ],
        )

    return build


@pytest.fixture
def restart_recorder(monkeypatch):
    """Capture the relaunch instead of actually starting a second process."""
    calls = []
    monkeypatch.setattr(
        TextScrapingReviewApp,
        "relaunch",
        lambda self, resume_index: calls.append(resume_index) or True,
    )
    monkeypatch.setattr(application_module.QApplication, "quit", lambda: None)
    return calls


# ----------------------------------------------------------------------
# The relaunch command
# ----------------------------------------------------------------------
def test_the_relaunch_command_carries_the_resume_position(monkeypatch):
    monkeypatch.setattr(application_module.sys, "argv", ["app.py"])
    monkeypatch.setattr(application_module.sys, "executable", "python")

    program, arguments = TextScrapingReviewApp.relaunch_command(5)

    assert program == "python"
    assert arguments == ["app.py", RESUME_FLAG, "5"]


def test_restarting_repeatedly_does_not_accumulate_flags(monkeypatch):
    monkeypatch.setattr(
        application_module.sys, "argv", ["app.py", RESUME_FLAG, "5", "--other"]
    )
    _program, arguments = TextScrapingReviewApp.relaunch_command(9)

    assert arguments == ["app.py", "--other", RESUME_FLAG, "9"]
    assert arguments.count(RESUME_FLAG) == 1


def test_an_equals_form_flag_is_replaced_too(monkeypatch):
    monkeypatch.setattr(
        application_module.sys, "argv", ["app.py", f"{RESUME_FLAG}=5"]
    )
    _program, arguments = TextScrapingReviewApp.relaunch_command(9)

    assert arguments == ["app.py", RESUME_FLAG, "9"]


def test_a_frozen_build_relaunches_itself_rather_than_the_interpreter(monkeypatch):
    monkeypatch.setattr(application_module.sys, "argv", ["app.exe", "--other"])
    monkeypatch.setattr(application_module.sys, "executable", "app.exe")
    monkeypatch.setattr(application_module.sys, "frozen", True, raising=False)

    program, arguments = TextScrapingReviewApp.relaunch_command(2)

    assert program == "app.exe"
    assert arguments == ["--other", RESUME_FLAG, "2"]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["app.py", RESUME_FLAG, "5"], 5),
        (["app.py", f"{RESUME_FLAG}=7"], 7),
        (["app.py"], None),
        (["app.py", RESUME_FLAG], None),
        (["app.py", RESUME_FLAG, "junk"], None),
        (["app.py", RESUME_FLAG, "-3"], 0),
    ],
)
def test_the_resume_position_is_read_back_off_the_command_line(arguments, expected):
    assert TextScrapingReviewApp.resume_index_from_arguments(arguments) == expected


# ----------------------------------------------------------------------
# Unsaved changes
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_navigating_without_editing_is_not_an_unsaved_change(three_row_app):
    window = three_row_app()
    assert window.has_unsaved_changes() is False

    # Committing rewrites every field, but nothing actually changed.
    window.next_mid_entry()
    window.prev_mid_entry()
    assert window.has_unsaved_changes() is False


@pytest.mark.qt
@pytest.mark.integration
def test_editing_a_field_is_an_unsaved_change(three_row_app):
    window = three_row_app()
    window.ui.set_field_text("goal", "Edited")
    window._commit_sidebar_fields()

    assert window.has_unsaved_changes() is True
    window.mid_manager.mark_saved()
    assert window.has_unsaved_changes() is False


@pytest.mark.qt
@pytest.mark.integration
def test_adding_and_deleting_rows_count_as_unsaved_changes(three_row_app):
    window = three_row_app()
    window.add_observation_from_document()
    assert window.has_unsaved_changes() is True


# ----------------------------------------------------------------------
# The restart itself
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_restarting_a_clean_mid_resumes_at_the_current_row(
    three_row_app, restart_recorder
):
    window = three_row_app()
    window.next_mid_entry()
    assert window.mid_manager.current_index == 1

    window.restart_application()
    assert restart_recorder == [1]


@pytest.mark.qt
@pytest.mark.integration
def test_unsaved_changes_prompt_and_saving_goes_ahead(
    three_row_app, restart_recorder, monkeypatch
):
    window = three_row_app()
    window.ui.set_field_text("goal", "Edited")

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Save
    )
    saves = []
    monkeypatch.setattr(
        window, "save_mid_to_file", lambda: saves.append(True) or True
    )

    window.restart_application()

    assert saves == [True]
    assert restart_recorder == [0]


@pytest.mark.qt
@pytest.mark.integration
def test_discarding_restarts_without_saving(
    three_row_app, restart_recorder, monkeypatch
):
    window = three_row_app()
    window.ui.set_field_text("goal", "Edited")

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Discard
    )
    saves = []
    monkeypatch.setattr(window, "save_mid_to_file", lambda: saves.append(True) or True)

    window.restart_application()

    assert saves == []
    assert restart_recorder == [0]


@pytest.mark.qt
@pytest.mark.integration
def test_cancelling_the_prompt_does_not_restart(
    three_row_app, restart_recorder, monkeypatch
):
    window = three_row_app()
    window.ui.set_field_text("goal", "Edited")
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Cancel
    )

    window.restart_application()

    assert restart_recorder == []
    assert window.has_unsaved_changes() is True


@pytest.mark.qt
@pytest.mark.integration
def test_a_cancelled_save_dialog_abandons_the_restart(
    three_row_app, restart_recorder, monkeypatch
):
    """Backing out of the file dialog must not throw the work away."""
    window = three_row_app()
    window.ui.set_field_text("goal", "Edited")

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Save
    )
    monkeypatch.setattr(window, "save_mid_to_file", lambda: False)

    window.restart_application()

    assert restart_recorder == []
    assert window.has_unsaved_changes() is True


@pytest.mark.qt
@pytest.mark.integration
def test_the_new_process_opens_on_the_row_it_was_told_to(
    three_row_app, monkeypatch
):
    monkeypatch.setattr(
        application_module.sys, "argv", ["app.py", RESUME_FLAG, "2"]
    )
    window = three_row_app()

    assert window.mid_manager.current_index == 2
    assert window.mid_manager.get_current_row()["metric"] == "Three"


@pytest.mark.qt
@pytest.mark.integration
def test_an_out_of_range_resume_position_is_ignored(three_row_app, monkeypatch):
    monkeypatch.setattr(
        application_module.sys, "argv", ["app.py", RESUME_FLAG, "99"]
    )
    window = three_row_app()

    assert window.mid_manager.current_index == 0


@pytest.mark.qt
def test_the_restart_control_is_first_in_the_control_panel(three_row_app):
    from ui.left_sidebar import CONTROL_SPECS

    window = three_row_app()
    assert CONTROL_SPECS[0].action == "restart"
    assert "restart" in window.ui.left.control_buttons
    assert window.ui.left.control_buttons["restart"].isVisible()
