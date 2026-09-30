"""What clicking the page does, and searching from the text panel."""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="PyQt5 is required for these tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")

from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtGui import QMouseEvent, QPixmap  # noqa: E402

from app_settings import migrate_settings  # noqa: E402
from document_text import (  # noqa: E402
    SEARCH_ANYWHERE,
    SEARCH_IN_RANGE,
    SEARCH_MARK_OUTSIDE,
)
from ui.document_view import (  # noqa: E402
    CLICK_ENTRY,
    CLICK_NOTHING,
    CLICK_PAGE,
    CLICK_ROTATE,
    CLICK_ZOOM,
    MAXIMUM_ZOOM,
    MINIMUM_ZOOM,
    DocumentView,
)


def _click(view, button=Qt.LeftButton, at=(5, 5)):
    event = QMouseEvent(
        QMouseEvent.MouseButtonPress,
        QPoint(*at),
        button,
        button,
        Qt.NoModifier,
    )
    view.page_label.mousePressEvent(event)


@pytest.fixture
def viewer(qtbot):
    view = DocumentView()
    qtbot.addWidget(view)
    view.resize(400, 500)
    # Shown, because zoom is measured against the scroll area's viewport and
    # an unshown widget has not been laid out yet.
    view.show()
    qtbot.waitExposed(view)
    view.show_page_pixmap(QPixmap(200, 300))
    return view


# ----------------------------------------------------------------------
# Choosing a behaviour
# ----------------------------------------------------------------------
def test_rotation_remains_the_default(viewer):
    assert viewer.click_action() == CLICK_ROTATE
    _click(viewer)
    assert viewer.rotation() == 90


@pytest.mark.parametrize("button,expected", [(Qt.LeftButton, 90), (Qt.RightButton, 270)])
def test_left_goes_forwards_and_right_back(viewer, button, expected):
    viewer.apply_settings({"clickAction": CLICK_ROTATE})
    _click(viewer, button)
    assert viewer.rotation() == expected


def test_nothing_means_nothing(viewer):
    viewer.apply_settings({"clickAction": CLICK_NOTHING})
    _click(viewer)
    assert viewer.rotation() == 0
    assert viewer.zoom() == MINIMUM_ZOOM


# ----------------------------------------------------------------------
# Zoom
# ----------------------------------------------------------------------
def test_clicking_zooms_in_and_out(viewer):
    viewer.apply_settings({"clickAction": CLICK_ZOOM})

    _click(viewer)
    zoomed = viewer.zoom()
    assert zoomed > MINIMUM_ZOOM

    _click(viewer, Qt.RightButton)
    assert viewer.zoom() < zoomed


def test_zoom_never_goes_below_fitting_the_window(viewer):
    viewer.apply_settings({"clickAction": CLICK_ZOOM})
    for _ in range(10):
        _click(viewer, Qt.RightButton)
    assert viewer.zoom() == MINIMUM_ZOOM


def test_zoom_is_bounded_above(viewer):
    viewer.apply_settings({"clickAction": CLICK_ZOOM})
    for _ in range(30):
        _click(viewer)
    assert viewer.zoom() == MAXIMUM_ZOOM


def test_zooming_makes_the_page_bigger_than_the_viewport(viewer):
    """Which is what puts it in the scroll area rather than shrinking it."""
    viewer.apply_settings({"clickAction": CLICK_ZOOM})
    fitted = viewer.page_label.width()

    _click(viewer)

    assert viewer.page_label.width() > fitted


def test_the_page_fills_the_pane_once_it_has_been_laid_out(qtbot):
    """The regression this guards: a page that arrives before the layout has
    run was drawn against a viewport of almost no size and left there, showing
    as a thumbnail stranded in an empty pane."""
    from PyQt5.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    view = DocumentView(host)
    layout.addWidget(view)
    host.resize(900, 700)

    # The page arrives first, exactly as it does at start-up.
    view.show_page_pixmap(QPixmap(200, 300))
    host.show()
    qtbot.waitExposed(host)

    viewport = view.page_scroll.viewport()
    assert view.page_label.height() >= viewport.height() * 0.9


def test_resizing_refits_the_page(qtbot, viewer):
    tall = viewer.page_label.height()
    viewer.resize(200, 250)
    qtbot.wait(10)
    assert viewer.page_label.height() < tall


def test_a_new_page_starts_unzoomed(viewer):
    viewer.apply_settings({"clickAction": CLICK_ZOOM})
    _click(viewer)
    assert viewer.zoom() > MINIMUM_ZOOM

    viewer.show_page_pixmap(QPixmap(200, 300))

    assert viewer.zoom() == MINIMUM_ZOOM


def test_switching_away_from_zoom_puts_the_page_back(viewer):
    """A click can no longer undo the zoom, so the setting change must."""
    viewer.apply_settings({"clickAction": CLICK_ZOOM})
    _click(viewer)
    assert viewer.zoom() > MINIMUM_ZOOM

    viewer.apply_settings({"clickAction": CLICK_PAGE})

    assert viewer.zoom() == MINIMUM_ZOOM


# ----------------------------------------------------------------------
# Page and entry steps are requests, not actions
# ----------------------------------------------------------------------
def test_page_mode_asks_rather_than_moves(viewer, qtbot):
    viewer.apply_settings({"clickAction": CLICK_PAGE})

    with qtbot.waitSignal(viewer.pageStepRequested) as blocker:
        _click(viewer)
    assert blocker.args == [1]

    with qtbot.waitSignal(viewer.pageStepRequested) as blocker:
        _click(viewer, Qt.RightButton)
    assert blocker.args == [-1]


def test_entry_mode_asks_rather_than_moves(viewer, qtbot):
    viewer.apply_settings({"clickAction": CLICK_ENTRY})

    with qtbot.waitSignal(viewer.entryStepRequested) as blocker:
        _click(viewer)
    assert blocker.args == [1]


def test_page_mode_does_not_rotate_or_zoom(viewer):
    viewer.apply_settings({"clickAction": CLICK_PAGE})
    _click(viewer)
    assert viewer.rotation() == 0
    assert viewer.zoom() == MINIMUM_ZOOM


# ----------------------------------------------------------------------
# The setting that used to be a checkbox
# ----------------------------------------------------------------------
def test_an_old_rotation_setting_becomes_the_rotate_action():
    settings = {"moduleSettings": {"document_view": {"clickRotation": True}}}
    assert migrate_settings(settings) is True
    assert settings["moduleSettings"]["document_view"] == {
        "clickAction": CLICK_ROTATE
    }


def test_rotation_switched_off_becomes_nothing_not_the_new_default():
    """Someone who turned clicking off must not find it switched back on."""
    settings = {"moduleSettings": {"document_view": {"clickRotation": False}}}
    migrate_settings(settings)
    assert settings["moduleSettings"]["document_view"]["clickAction"] == CLICK_NOTHING


def test_other_viewer_settings_survive_the_migration():
    settings = {
        "moduleSettings": {
            "document_view": {
                "clickRotation": True,
                "keepRotationBetweenPages": True,
            }
        }
    }
    migrate_settings(settings)
    assert settings["moduleSettings"]["document_view"]["keepRotationBetweenPages"]


def test_migrating_twice_changes_nothing_the_second_time():
    settings = {"moduleSettings": {"document_view": {"clickRotation": True}}}
    migrate_settings(settings)
    assert migrate_settings(settings) is False


# ----------------------------------------------------------------------
# Searching, through the whole application
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_a_search_reports_its_hits_to_the_panel(application_factory):
    window = application_factory()
    panel = window.ui.content_panel

    window.search_document("strategic")

    assert panel.results_list.isVisible()
    assert panel.results_list.count() >= 1
    assert "match" in panel.search_status.text()


@pytest.mark.qt
@pytest.mark.integration
def test_a_search_with_no_hits_says_so(application_factory):
    window = application_factory()
    panel = window.ui.content_panel

    window.search_document("nowhereinthisdocument")

    assert panel.results_list.count() == 0
    assert "No match" in panel.search_status.text()


@pytest.mark.qt
@pytest.mark.integration
def test_the_scope_setting_decides_how_far_a_search_reaches(application_factory):
    window = application_factory()
    panel = window.ui.content_panel

    panel.apply_settings({"searchScope": SEARCH_IN_RANGE})
    assert window.ui.search_scope() == SEARCH_IN_RANGE

    panel.apply_settings({"searchScope": SEARCH_ANYWHERE})
    assert window.ui.search_scope() == SEARCH_ANYWHERE


@pytest.mark.qt
@pytest.mark.integration
def test_choosing_a_result_moves_to_that_page(application_factory):
    window = application_factory()

    window.go_to_document_page(0)

    assert window.current_page_index == 0


@pytest.mark.qt
@pytest.mark.integration
def test_a_page_outside_the_row_is_previewed_not_adopted(application_factory):
    """The current page is written into the MID, so a peek must not change it."""
    window = application_factory()
    before = window.current_page_index

    # A page the session does not cover.
    window.go_to_document_page(999)

    assert window.current_page_index == before


@pytest.mark.qt
@pytest.mark.integration
def test_the_index_is_reused_for_the_same_document(application_factory):
    window = application_factory()

    first = window.document_index()
    second = window.document_index()

    assert first is second


@pytest.mark.qt
@pytest.mark.integration
def test_hiding_the_search_bar_clears_what_it_showed(application_factory):
    window = application_factory()
    panel = window.ui.content_panel
    window.search_document("strategic")
    assert panel.results_list.isVisible()

    panel.apply_settings({"showSearchBar": False})

    assert not panel.search_bar.isVisible()
    assert panel.results_list.count() == 0


@pytest.mark.qt
@pytest.mark.integration
def test_clicking_the_page_can_step_entries(application_factory, mid_row_factory):
    """The click routes through normal navigation, so the sidebar commits."""
    window = application_factory(rows=[mid_row_factory(), mid_row_factory(year=2025)])
    assert window.mid_manager.current_index == 0

    window.step_entry(1)
    assert window.mid_manager.current_index == 1

    window.step_entry(-1)
    assert window.mid_manager.current_index == 0


@pytest.mark.qt
@pytest.mark.integration
def test_stepping_a_page_uses_the_ordinary_page_controls(application_factory):
    window = application_factory()
    start = window.current_page_index

    # A one-page document has nowhere to go, and must not wrap round.
    window.step_page(-1)

    assert window.current_page_index == start
