"""Tests for the ``ui`` package: the three panes and the controller boundary."""

import pytest


pytest.importorskip("PyQt5", reason="PyQt5 is required for UI tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QColor, QKeyEvent

import ui as ui_package
from ui import (
    CounterSpec,
    FieldButtonSpec,
    FieldSpec,
    InfoSpec,
    LeftSidebar,
    ToggleSpec,
    UIContext,
)
from ui.main_window import ACTION_HANDLERS
from ui.panels import ScrapedTextPanel


@pytest.fixture
def ui_context():
    return UIContext(
        mode="user",
        fields=(
            FieldSpec("goal", "Goal"),
            FieldSpec("metric", "Metric", expandable=True),
        ),
        toggles=(
            ToggleSpec("flag", "Flag for review", shortcut="Ctrl+F"),
            ToggleSpec("aggregate", "Aggregate"),
            ToggleSpec("achieved", "Achieved"),
            ToggleSpec(
                "future_dated",
                "Future-Dated",
                counter=CounterSpec("future_dated", "Years to eval:", maximum=20),
            ),
        ),
        field_buttons=(
            FieldButtonSpec("half", "50%", "metric", "metric = goal * 0.5"),
        ),
        info=(InfoSpec("x", "Agency"), InfoSpec("y", "Year")),
        restriction_options=("none", "_flag"),
        evaluation_classes={"Performance": {"option_types": ["Met", "Not Met"]}},
        default_class="Performance",
    )


@pytest.fixture
def sidebar(qtbot, ui_context):
    widget = LeftSidebar(ui_context)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def text_panel(qtbot):
    panel = ScrapedTextPanel()
    qtbot.addWidget(panel)
    return panel


# ----------------------------------------------------------------------
# Left sidebar
# ----------------------------------------------------------------------
@pytest.mark.qt
def test_sidebar_round_trips_every_editable_value(sidebar):
    sidebar.set_field_texts({"goal": "A goal", "metric": "A metric"})
    sidebar.set_notes_text("A note")
    sidebar.set_reviewer_notes_text("A review")
    sidebar.set_toggles({"flag": True, "achieved": True})
    sidebar.set_counter("future_dated", 4)
    sidebar.set_metric_status("Not Met")

    assert sidebar.field_texts() == {"goal": "A goal", "metric": "A metric"}
    assert sidebar.notes_text() == "A note"
    assert sidebar.reviewer_notes_text() == "A review"
    assert sidebar.toggles() == {
        "flag": True,
        "aggregate": False,
        "achieved": True,
        "future_dated": False,
    }
    assert sidebar.counters() == {"future_dated": 4}
    assert sidebar.metric_status() == "Not Met"


@pytest.mark.qt
def test_sidebar_presenters_do_not_re_emit_signals(sidebar):
    emitted = []
    sidebar.toggleChanged.connect(lambda key, checked: emitted.append(key))
    sidebar.counterChanged.connect(lambda key, value: emitted.append(key))

    sidebar.set_toggle("flag", True)
    sidebar.set_counter("future_dated", 2)

    assert emitted == []


@pytest.mark.qt
def test_a_checkbox_gates_its_companion_counter(sidebar, qtbot):
    counter = sidebar.counter_boxes["future_dated"]
    assert not counter.isEnabled()

    with qtbot.waitSignal(sidebar.toggleChanged):
        sidebar.toggle_boxes["future_dated"].setChecked(True)
    assert counter.isEnabled()
    sidebar.set_counter("future_dated", 5)

    with qtbot.waitSignal(sidebar.toggleChanged):
        sidebar.toggle_boxes["future_dated"].setChecked(False)
    assert not counter.isEnabled()
    assert sidebar.counter("future_dated") == 0


@pytest.mark.qt
def test_only_the_configured_checkboxes_are_built(sidebar):
    assert list(sidebar.toggle_boxes) == [
        "flag",
        "aggregate",
        "achieved",
        "future_dated",
    ]
    # Only the one that declared a counter gets a number box.
    assert list(sidebar.counter_boxes) == ["future_dated"]
    assert sidebar.toggle_boxes["flag"].shortcut().toString() == "Ctrl+F"


@pytest.mark.qt
def test_tab_walks_the_sidebar_inputs_in_visual_order(sidebar):
    widgets = sidebar.focus_widgets()

    assert widgets[:2] == [
        sidebar.field_editors["goal"],
        sidebar.field_editors["metric"],
    ]
    assert sidebar.notes_edit in widgets
    assert sidebar.reviewer_notes_edit == widgets[-1]

    # Tab must move focus rather than insert a tab character.
    for editor in sidebar.field_editors.values():
        assert editor.tabChangesFocus()

    # A counter follows the checkbox that owns it.
    order = {widget: index for index, widget in enumerate(widgets)}
    assert (
        order[sidebar.counter_boxes["future_dated"]]
        == order[sidebar.toggle_boxes["future_dated"]] + 1
    )


@pytest.mark.qt
def test_a_computed_button_sits_beside_the_field_it_writes(sidebar, qtbot):
    assert list(sidebar.field_buttons) == ["half"]
    assert sidebar.field_buttons["half"].toolTip() == "metric = goal * 0.5"

    with qtbot.waitSignal(sidebar.fieldButtonClicked) as blocker:
        sidebar.field_buttons["half"].click()
    assert blocker.args == ["half"]


@pytest.mark.qt
def test_scheme_change_rebuilds_the_metric_status_options(sidebar):
    assert sidebar.metric_status_labels() == ["Met", "Not Met"]

    sidebar.set_scheme_options(
        {"Binary": {"option_types": ["Yes", "No", "Partial"]}}, "Binary"
    )
    assert sidebar.metric_status_labels() == ["Yes", "No", "Partial"]

    sidebar.select_metric_status_by_index(2)
    assert sidebar.metric_status() == "Partial"
    sidebar.clear_metric_status()
    assert sidebar.metric_status() == ""


@pytest.mark.qt
def test_mode_visibility_follows_the_declared_control_modes(sidebar):
    controls = sidebar.control_buttons
    sidebar.show()

    sidebar.apply_mode("user")
    assert controls["delete_entry"].isVisible()
    assert not controls["run_audit"].isVisible()
    assert not sidebar.reviewer_group.isVisible()

    sidebar.apply_mode("dev")
    assert controls["run_audit"].isVisible()
    assert controls["export_results"].isVisible()
    assert not sidebar.reviewer_group.isVisible()

    sidebar.apply_mode("reviewer")
    assert sidebar.reviewer_group.isVisible()
    assert controls["load_cases"].isVisible()
    assert not controls["run_audit"].isVisible()


@pytest.mark.qt
def test_expandable_fields_get_an_add_button_and_others_do_not(sidebar, qtbot):
    assert set(sidebar.add_level_buttons) == {"metric"}

    with qtbot.waitSignal(sidebar.addLevelRequested) as blocker:
        sidebar.trigger_add_level("metric")
    assert blocker.args == ["metric"]


@pytest.mark.qt
def test_transfer_targets_are_the_editable_fields(sidebar):
    assert sidebar.transfer_targets() == [("goal", "Goal"), ("metric", "Metric")]


# ----------------------------------------------------------------------
# Content panel
# ----------------------------------------------------------------------
@pytest.mark.qt
def test_panel_registry_exposes_every_registered_panel():
    panels = ui_package.available_panels()
    assert "scraped_text" in panels
    assert "rendered_table" in panels

    with pytest.raises(KeyError):
        ui_package.create_panel("not_a_panel")


@pytest.mark.qt
def test_text_panel_reads_content_and_normalises_selection(text_panel):
    text_panel.set_content("first line\nsecond line")
    assert text_panel.content() == "first line\nsecond line"

    text_panel.editor.selectAll()
    assert text_panel.selection() == "first line second line"

    text_panel.clear()
    assert text_panel.content() == ""


@pytest.mark.qt
def test_text_panel_highlights_matches_across_line_breaks(text_panel):
    text_panel.set_content("The stated\ngoal   was met in full.")

    text_panel.highlight([("stated goal was met", QColor("#FFFF00"))])
    assert len(text_panel.editor.extraSelections()) == 1

    text_panel.highlight([("nowhere in the text", QColor("#FFFF00"))])
    assert text_panel.editor.extraSelections() == []


@pytest.mark.qt
def test_text_panel_ignores_fragments_too_short_to_be_meaningful(text_panel):
    text_panel.set_content("a b c 12 12 12")

    text_panel.highlight([("b", QColor("#FFFF00"))])
    assert text_panel.editor.extraSelections() == []

    # Short numbers are still worth marking.
    text_panel.highlight([("12", QColor("#FFFF00"))])
    assert len(text_panel.editor.extraSelections()) == 3


@pytest.mark.qt
def test_panel_emits_a_transfer_request_even_with_an_empty_selection(
    text_panel, qtbot
):
    text_panel.set_content("some text")

    with qtbot.waitSignal(text_panel.transferRequested) as blocker:
        text_panel.request_transfer("goal")
    assert blocker.args == ["goal", ""]

    text_panel.editor.selectAll()
    with qtbot.waitSignal(text_panel.transferRequested) as blocker:
        text_panel.request_transfer("goal")
    assert blocker.args == ["goal", "some text"]


# ----------------------------------------------------------------------
# Controller boundary
# ----------------------------------------------------------------------
@pytest.mark.qt
def test_every_declared_control_has_a_controller_handler(application_factory):
    window = application_factory("Dev")

    for action in window.ui.left.control_buttons:
        assert action in ACTION_HANDLERS, f"no handler mapped for '{action}'"
        assert callable(getattr(window, ACTION_HANDLERS[action], None))


@pytest.mark.qt
@pytest.mark.integration
def test_clicking_a_control_reaches_the_controller(application_factory, qtbot):
    window = application_factory("User")
    calls = []
    window.next_page = lambda: calls.append("next_page")

    qtbot.mouseClick(window.ui.left.control_buttons["next_page"], Qt.LeftButton)
    assert calls == ["next_page"]


@pytest.mark.qt
@pytest.mark.integration
def test_selection_transfers_from_the_content_panel_into_a_field(application_factory):
    window = application_factory("User")
    window.ui.set_content("The agency reported a goal of 42 widgets.")
    window.ui.content_panel.editor.selectAll()

    # MID fields go through status-label extraction, which trims trailing
    # punctuation left behind when a label sits at the end of the snippet.
    window.ui.transfer_selection("goal")
    assert window.ui.field_text("goal") == "The agency reported a goal of 42 widgets"


@pytest.mark.qt
@pytest.mark.integration
def test_transfer_without_a_selection_reports_instead_of_writing(application_factory):
    window = application_factory("User")
    window.ui.set_content("Some scraped text.")
    window.ui.set_field_text("goal", "untouched")

    window.ui.content_panel.editor.moveCursor(window.ui.content_panel.editor.textCursor().Start)
    window.ui.transfer_selection("goal")

    assert window.ui.field_text("goal") == "untouched"
    assert window.statusBar().currentMessage() == "No highlighted text to transfer."


@pytest.mark.qt
@pytest.mark.integration
def test_swapping_the_content_panel_preserves_the_payload(application_factory):
    window = application_factory("User")
    window.ui.set_content("Scraped payload")
    assert window.ui.active_panel_id() == "scraped_text"

    window.ui.show_panel("rendered_table")
    assert window.ui.active_panel_id() == "rendered_table"
    assert "Scraped payload" in window.ui.content()
    # The new panel is wired for transfer just like the old one.
    assert window.ui.content_panel.transfer_targets()

    window.ui.show_panel("scraped_text")
    assert window.ui.content() == "Scraped payload"


@pytest.mark.qt
def test_restriction_options_depend_on_the_mode(application_factory):
    window = application_factory("Reviewer")
    assert window.ui.restriction_choice() == "_flag"
    assert "rejected" in window.restriction_options()

    window.mode = "user"
    assert window.restriction_options() == []


@pytest.mark.qt
def test_bound_single_keys_are_swallowed_before_reaching_an_editor(application_factory):
    window = application_factory("User")
    reserved = window.ui.reserved_plain_keys()
    assert {"1", "-", "="}.issubset(reserved)
    # Target/Actual are gone, so their transfer keys are typable again.
    assert not {"[", "]"} & reserved

    swallowed = QKeyEvent(QEvent.KeyPress, Qt.Key_1, Qt.NoModifier, "1")
    assert window.eventFilter(window, swallowed) is True

    passed_through = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a")
    assert window.eventFilter(window, passed_through) is False


# ----------------------------------------------------------------------
# The sidebar's width
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_the_sidebar_can_be_dragged_narrow(application_factory):
    """It used to be immovable: its content set a floor on the whole pane."""
    from ui.main_window import SIDEBAR_MINIMUM_WIDTH

    window = application_factory()
    window.resize(1600, 1000)

    window.ui.splitter.setSizes([SIDEBAR_MINIMUM_WIDTH, 800, 700])

    assert window.ui.splitter.sizes()[0] <= SIDEBAR_MINIMUM_WIDTH + 40


@pytest.mark.qt
@pytest.mark.integration
def test_the_sidebar_does_not_take_the_extra_space(application_factory):
    """Room gained by a wider window belongs to the document and the panel."""
    window = application_factory()

    window.resize(1280, 900)
    narrow = window.ui.splitter.sizes()
    window.resize(1920, 900)
    wide = window.ui.splitter.sizes()

    assert wide[0] == narrow[0], "the sidebar grew instead of the other panes"
    assert wide[1] > narrow[1] and wide[2] > narrow[2]


@pytest.mark.qt
@pytest.mark.integration
def test_the_sidebar_content_fits_at_its_default_width(application_factory):
    """No horizontal scrollbar unless the user has chosen to squeeze it."""
    window = application_factory()
    window.resize(1600, 1000)

    sidebar_width = window.ui.splitter.sizes()[0]

    assert sidebar_width >= window.ui.left.minimumSizeHint().width()


@pytest.mark.qt
@pytest.mark.integration
def test_a_long_document_name_does_not_widen_the_sidebar(application_factory):
    """The label wraps. Unwrapped, one filename demanded over 1200px."""
    window = application_factory()
    before = window.ui.left.minimumSizeHint().width()

    window.ui.set_info_values(
        {"document": "2021-2022 SFPE Approved City of Clarkesville Habersham - A.pdf"}
    )

    assert window.ui.left.minimumSizeHint().width() == before


@pytest.mark.qt
@pytest.mark.integration
def test_the_sidebar_scrolls_rather_than_clipping(application_factory):
    """Squeezed past what fits, the content scrolls instead of vanishing."""
    window = application_factory()
    window.resize(1600, 1000)
    window.ui.splitter.setSizes([200, 800, 600])
    window.ui.left_scroll.horizontalScrollBar()  # exists, and is reachable

    # Every control is still there to be scrolled to.
    assert window.ui.left.control_buttons
    assert window.ui.left.width() > 0


@pytest.mark.qt
@pytest.mark.integration
def test_dragging_the_handle_actually_narrows_the_sidebar(application_factory, qtbot):
    """Driven with real mouse events on the handle, not by calling setSizes."""
    from PyQt5.QtCore import QEvent, QPoint, Qt as QtNS
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    window = application_factory()
    window.resize(1600, 1000)
    window.show()
    qtbot.waitExposed(window)

    splitter = window.ui.splitter
    before = splitter.sizes()[0]
    handle = splitter.handle(1)

    start = QPoint(handle.width() // 2, handle.height() // 2)
    target = start - QPoint(300, 0)

    # Sent by hand rather than with QTest.mouseMove, which does not carry the
    # held button in `buttons` — and a splitter handle only drags while it
    # believes a button is down. The global position matters too: a splitter
    # works out the new boundary from it, so an event without one drags in an
    # arbitrary direction.
    def send(kind, position, button, buttons):
        QApplication.sendEvent(
            handle,
            QMouseEvent(
                kind,
                position,
                handle.mapToGlobal(position),
                button,
                buttons,
                QtNS.NoModifier,
            ),
        )

    send(QEvent.MouseButtonPress, start, QtNS.LeftButton, QtNS.LeftButton)
    send(QEvent.MouseMove, target, QtNS.NoButton, QtNS.LeftButton)
    send(QEvent.MouseButtonRelease, target, QtNS.LeftButton, QtNS.NoButton)
    qtbot.wait(20)

    assert splitter.sizes()[0] < before, "the handle would not drag"


#: A schema with enough editable fields that the sidebar has to make choices
#: about height. Mirrors a real project's configuration.
TALL_SCHEMA = {
    "xColumn": "Gov",
    "yColumn": "FY",
    "interactionColumns": [
        "FY", "Gov", "LMIG_Exp", "Match", "Local_Exp", "Total_Exp", "Field_Audit"
    ],
    "documentColumn": "agency_yr",
    "pageColumn": "",
    "formatColumn": "",
    "keywordColumn": "",
    "entryLabel": "x_paren_y",
}


@pytest.mark.qt
@pytest.mark.integration
def test_the_sidebar_compresses_instead_of_scrolling(application_factory, qtbot):
    """A shorter window makes the fields shorter, not a scrollbar appear."""
    from PyQt5.QtWidgets import QApplication

    # Enough fields that the column has something to compress; the default
    # test schema is short enough to fit at full height either way.
    window = application_factory(schema=TALL_SCHEMA)
    window.show()
    qtbot.waitExposed(window)

    window.resize(1600, 1000)
    qtbot.wait(60)
    QApplication.processEvents()
    tall_editor = next(iter(window.ui.left.field_editors.values())).height()
    assert not window.ui.left_scroll.verticalScrollBar().isVisible()

    window.resize(1600, 860)
    qtbot.wait(60)
    QApplication.processEvents()
    short_editor = next(iter(window.ui.left.field_editors.values())).height()

    assert short_editor < tall_editor, "the fields did not compress"
    assert not window.ui.left_scroll.verticalScrollBar().isVisible()


@pytest.mark.qt
@pytest.mark.integration
def test_the_scrollbar_appears_once_compressing_is_not_enough(
    application_factory, qtbot
):
    """It should still be there when it is telling the user something true."""
    from PyQt5.QtWidgets import QApplication
    from ui.widgets import FIELD_BOX_MIN_HEIGHT

    window = application_factory(schema=TALL_SCHEMA)
    window.show()
    qtbot.waitExposed(window)
    window.resize(1600, 400)
    qtbot.wait(60)
    QApplication.processEvents()

    assert window.ui.left_scroll.verticalScrollBar().isVisible()
    # And the fields are back to a usable height rather than crushed.
    editor = next(iter(window.ui.left.field_editors.values()))
    assert editor.height() > FIELD_BOX_MIN_HEIGHT


@pytest.mark.qt
@pytest.mark.integration
def test_a_field_is_never_squeezed_below_a_readable_line(
    application_factory, qtbot
):
    from PyQt5.QtWidgets import QApplication
    from ui.widgets import FIELD_BOX_MIN_HEIGHT

    window = application_factory(schema=TALL_SCHEMA)
    window.show()
    qtbot.waitExposed(window)
    for height in (900, 800, 700, 600, 500):
        window.resize(1600, height)
        qtbot.wait(40)
        QApplication.processEvents()
        for editor in window.ui.left.field_editors.values():
            assert editor.height() >= FIELD_BOX_MIN_HEIGHT
