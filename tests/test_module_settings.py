"""Settings that modules declare for themselves, and the viewer's rotation."""

import json

import pytest

import module_settings
from module_settings import (
    BoolSetting,
    ChoiceSetting,
    IntSetting,
    ModuleSettings,
    TextSetting,
)


DEMO = ModuleSettings(
    module_id="demo",
    display_name="Demo Module",
    settings=(
        BoolSetting("enabled", "Enabled", default=True),
        IntSetting("count", "Count", default=4, minimum=1, maximum=9),
        ChoiceSetting("mode", "Mode", choices=("a", "b"), default="a"),
        TextSetting("note", "Note", default=""),
    ),
)


# ----------------------------------------------------------------------
# Declaring and resolving
# ----------------------------------------------------------------------
def test_stored_values_are_merged_over_declared_defaults():
    resolved = DEMO.resolve({"count": 7})

    assert resolved == {"enabled": True, "count": 7, "mode": "a", "note": ""}


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({"count": 99}, 9),        # clamped to the declared maximum
        ({"count": -5}, 1),        # clamped to the declared minimum
        ({"count": "3"}, 3),       # a string from a hand-edited file
        ({"count": "junk"}, 4),    # unreadable, so the default stands
        ({}, 4),
    ],
)
def test_unusable_stored_values_fall_back_rather_than_raising(stored, expected):
    assert DEMO.resolve(stored)["count"] == expected


def test_booleans_survive_a_hand_edited_settings_file():
    assert DEMO.resolve({"enabled": "false"})["enabled"] is False
    assert DEMO.resolve({"enabled": "yes"})["enabled"] is True


def test_a_choice_outside_the_options_falls_back():
    assert DEMO.resolve({"mode": "z"})["mode"] == "a"


# ----------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------
def test_a_module_is_remembered_the_first_time_it_loads():
    module_settings.register_module_settings(DEMO)
    settings = {}

    assert module_settings.remember(settings, "demo") is True
    assert settings[module_settings.SETTINGS_KEY]["demo"] == DEMO.defaults

    # Nothing changed the second time.
    assert module_settings.remember(settings, "demo") is False


def test_settings_added_since_the_user_last_saved_are_filled_in():
    module_settings.register_module_settings(DEMO)
    settings = {module_settings.SETTINGS_KEY: {"demo": {"enabled": False}}}

    assert module_settings.remember(settings, "demo") is True
    entry = settings[module_settings.SETTINGS_KEY]["demo"]
    assert entry["enabled"] is False  # the user's value is untouched
    assert entry["count"] == 4        # the new setting arrived at its default


def test_values_for_an_unknown_module_are_handed_back_untouched():
    settings = {module_settings.SETTINGS_KEY: {"gone": {"old": 3}}}

    assert module_settings.resolve(settings, "gone") == {"old": 3}
    assert module_settings.remember(settings, "gone") is False
    assert settings[module_settings.SETTINGS_KEY]["gone"] == {"old": 3}


def test_dev_mode_sees_every_module_and_other_modes_only_what_is_loaded():
    module_settings.register_module_settings(DEMO)
    settings = {module_settings.SETTINGS_KEY: {"gone": {}}}

    assert module_settings.visible_modules(settings, ["scraped_text"]) == (
        "scraped_text",
    )

    dev = module_settings.visible_modules(settings, ["scraped_text"], mode="dev")
    assert "scraped_text" in dev
    assert "document_view" in dev  # registered but not loaded
    assert "gone" in dev           # remembered from an earlier session


# ----------------------------------------------------------------------
# The document viewer's own settings
# ----------------------------------------------------------------------
pytest.importorskip("PyQt5", reason="PyQt5 is required for UI tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")

from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QMouseEvent, QPixmap  # noqa: E402

from ui.document_view import CLICK_NOTHING, DocumentView  # noqa: E402


def _click(view, button):
    event = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPoint(5, 5), button, button, Qt.NoModifier
    )
    view.page_label.mousePressEvent(event)


@pytest.fixture
def viewer(qtbot):
    view = DocumentView()
    qtbot.addWidget(view)
    view.show_page_pixmap(QPixmap(40, 60))
    return view


@pytest.mark.qt
def test_clicking_the_page_turns_it(viewer):
    assert viewer.rotation() == 0

    _click(viewer, Qt.LeftButton)
    assert viewer.rotation() == 90
    _click(viewer, Qt.LeftButton)
    assert viewer.rotation() == 180

    _click(viewer, Qt.RightButton)
    assert viewer.rotation() == 90


@pytest.mark.qt
def test_rotation_wraps_in_both_directions(viewer):
    _click(viewer, Qt.RightButton)
    assert viewer.rotation() == 270

    for _ in range(3):
        _click(viewer, Qt.RightButton)
    assert viewer.rotation() == 0


@pytest.mark.qt
def test_rotation_reports_itself(viewer, qtbot):
    with qtbot.waitSignal(viewer.rotationChanged) as blocker:
        _click(viewer, Qt.LeftButton)
    assert blocker.args == [90]


@pytest.mark.qt
def test_click_rotation_can_be_switched_off(viewer):
    _click(viewer, Qt.LeftButton)
    assert viewer.rotation() == 90

    # Choosing another behaviour also straightens the page back up: a click
    # can no longer undo the rotation it made.
    viewer.apply_settings({"clickAction": CLICK_NOTHING})
    assert viewer.rotation() == 0

    _click(viewer, Qt.LeftButton)
    assert viewer.rotation() == 0


@pytest.mark.qt
def test_each_page_starts_upright_unless_asked_otherwise(viewer):
    _click(viewer, Qt.LeftButton)
    viewer.show_page_pixmap(QPixmap(40, 60))
    assert viewer.rotation() == 0

    viewer.apply_settings({"clickRotation": True, "keepRotationBetweenPages": True})
    _click(viewer, Qt.LeftButton)
    viewer.show_page_pixmap(QPixmap(40, 60))
    assert viewer.rotation() == 90


@pytest.mark.qt
def test_a_rotated_page_is_drawn_rotated(viewer):
    upright = viewer.page_label.pixmap().size()
    _click(viewer, Qt.LeftButton)
    turned = viewer.page_label.pixmap().size()

    # A portrait page becomes landscape once it is on its side.
    assert (upright.width() < upright.height()) != (turned.width() < turned.height())


# ----------------------------------------------------------------------
# In the application
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_the_loaded_modules_are_written_into_the_settings_file(application_factory):
    window = application_factory("User")

    stored = json.loads(window.settings_path.read_text(encoding="utf-8"))
    assert set(stored["moduleSettings"]) == {"document_view", "scraped_text"}


@pytest.mark.qt
@pytest.mark.integration
def test_the_panel_decides_how_many_number_keys_transfer(application_factory):
    window = application_factory("User")
    assert {"1", "2", "3", "4"}.issubset(window.ui.reserved_plain_keys())

    window.ui.apply_module_settings(
        {"scraped_text": {"numberKeyTransfer": False}, "document_view": {}}
    )
    assert not {"1", "2", "3", "4"} & window.ui.reserved_plain_keys()

    window.ui.apply_module_settings(
        {"scraped_text": {"numberKeyTransfer": True, "transferFieldCount": 2}}
    )
    reserved = window.ui.reserved_plain_keys()
    assert {"1", "2"}.issubset(reserved)
    assert not {"3", "4"} & reserved


@pytest.mark.qt
@pytest.mark.integration
def test_turning_off_highlighting_clears_it(application_factory):
    window = application_factory("User")
    window.ui.set_field_text("goal", "strategic objective")
    window.ui.refresh_highlights()
    assert window.ui.content_panel.editor.extraSelections()

    window.ui.apply_module_settings(
        {"scraped_text": {"highlightFieldMatches": False}}
    )
    window.ui.refresh_highlights()
    assert window.ui.content_panel.editor.extraSelections() == []


@pytest.mark.qt
@pytest.mark.integration
def test_switching_panel_applies_that_panel_s_own_settings(application_factory):
    window = application_factory("User")
    window.ui.apply_module_settings(
        {
            "scraped_text": {"numberKeyTransfer": True, "transferFieldCount": 4},
            "rendered_table": {"openExternalLinks": True},
        }
    )

    window.ui.show_panel("rendered_table")
    assert window.ui.content_panel.setting("openExternalLinks") is True
    assert window.ui.active_module_ids() == ("document_view", "rendered_table")
    # The table panel declares no transfer keys, so none are bound.
    assert not {"1", "2", "3", "4"} & window.ui.reserved_plain_keys()
