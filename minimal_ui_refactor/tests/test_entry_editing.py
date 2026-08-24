"""Per-entry edit tracking, and the entry label format that names rows.

Two separate flags are at work here:

``MIDManager.entry_is_dirty()``
    In-memory only. True once the user has changed something about the row
    that is open, cleared whenever another row is opened. It is what stops a
    row nobody touched from being written over on the way past.

``mid_schema.EDITED_COLUMN``
    A real MID column, saved with the sheet. False until a change to that row
    is committed, and the basis of "go to the first unedited entry".
"""

import pytest

from mid_schema import EDITED_COLUMN, MIDSchema, entry_label_choices


# ----------------------------------------------------------------------
# The in-memory flag
# ----------------------------------------------------------------------
def test_a_freshly_loaded_row_is_not_dirty(manager_factory):
    manager = manager_factory()

    assert manager.entry_is_dirty() is False


def test_writing_a_real_value_makes_the_current_row_dirty(manager_factory):
    manager = manager_factory()

    manager.set_value(0, "goal", "Changed goal")

    assert manager.entry_is_dirty() is True


def test_rewriting_the_same_value_leaves_the_row_clean(manager_factory):
    """Committing the sidebar rewrites every field, so equality must count."""
    manager = manager_factory()
    original = manager.df.at[0, "goal"]

    manager.set_value(0, "goal", original)

    assert manager.entry_is_dirty() is False


def test_moving_to_another_row_clears_the_flag(manager_factory):
    manager = manager_factory()
    manager.set_value(0, "goal", "Changed goal")

    manager.next_mid_entry()

    assert manager.entry_is_dirty() is False


def test_pending_changes_reports_only_what_would_actually_move(manager_factory):
    manager = manager_factory()
    unchanged = manager.df.at[0, "goal"]

    pending = manager.pending_changes(
        0, {"goal": unchanged, "notes": "New note", "brand_new_column": "value"}
    )

    assert pending == {"notes": "New note", "brand_new_column": "value"}


# ----------------------------------------------------------------------
# The persistent flag
# ----------------------------------------------------------------------
def test_every_row_starts_unedited(manager_factory):
    manager = manager_factory()

    assert manager.master_df[EDITED_COLUMN].tolist() == [False] * 4
    assert manager.is_entry_edited() is False
    assert manager.unedited_count() == 4


def test_the_persistent_flag_survives_a_round_trip(mid_path_factory, sample_rows):
    """A MID saved with the column reopens with the same rows still marked."""
    from mid_manager import MIDManager

    rows = [dict(row) for row in sample_rows]
    rows[1][EDITED_COLUMN] = "TRUE"
    manager = MIDManager(mid_path_factory(rows))

    assert manager.master_df[EDITED_COLUMN].tolist() == [False, True, False, False]
    assert manager.first_unedited_index() == 0
    assert manager.unedited_count() == 3


def test_setting_the_flag_reaches_both_frames_and_the_save_prompt(manager_factory):
    manager = manager_factory()
    manager.mark_saved()

    manager.set_entry_edited(True, 2)

    assert bool(manager.master_df.at[2, EDITED_COLUMN]) is True
    assert bool(manager.df.at[2, EDITED_COLUMN]) is True
    assert manager.is_modified() is True


def test_toggling_the_flag_flips_it_both_ways(manager_factory):
    manager = manager_factory()

    assert manager.toggle_entry_edited() is True
    assert manager.is_entry_edited() is True
    assert manager.toggle_entry_edited() is False
    assert manager.is_entry_edited() is False


def test_marking_the_flag_by_hand_is_not_an_edit_to_the_row(manager_factory):
    """The flag records that a row was edited; it is not one of its edits."""
    manager = manager_factory()

    manager.set_entry_edited(True)

    assert manager.entry_is_dirty() is False


def test_the_first_unedited_row_skips_the_ones_already_done(manager_factory):
    manager = manager_factory()
    manager.set_entry_edited(True, 0)
    manager.set_entry_edited(True, 1)

    assert manager.first_unedited_index() == 2
    assert manager.first_unedited_index(start=3) == 3
    assert manager.unedited_count() == 2


def test_no_unedited_row_left_reports_nothing(manager_factory):
    manager = manager_factory()
    for position in range(len(manager.df)):
        manager.set_entry_edited(True, position)

    assert manager.first_unedited_index() is None
    assert manager.unedited_count() == 0


def test_a_restricted_view_only_considers_its_own_rows(manager_factory):
    manager = manager_factory()
    manager.restrict_to_rows([1, 3])
    manager.set_entry_edited(True, 0)  # view position 0 is master row 1

    assert bool(manager.master_df.at[1, EDITED_COLUMN]) is True
    assert manager.first_unedited_index() == 1
    assert manager.unedited_count() == 1


def test_a_new_observation_starts_unedited(manager_factory):
    manager = manager_factory()
    manager.set_entry_edited(True, 0)

    new_row = manager.clone_for_document(0)

    assert bool(new_row[EDITED_COLUMN]) is False


# ----------------------------------------------------------------------
# Entry label formats
# ----------------------------------------------------------------------
LABEL_ROW = {"agency": "DOJ", "year": "2024", "agency_yr": "DOJ-2024.pdf"}


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("x_dash_y", "DOJ — 2024"),
        ("x_paren_y", "DOJ (2024)"),
        ("x_space_y", "DOJ 2024"),
        ("xy", "DOJ2024"),
        ("y_dash_x", "2024 — DOJ"),
        ("document", "DOJ-2024.pdf"),
        ("document_xy", "DOJ-2024.pdf (DOJ — 2024)"),
    ],
)
def test_each_entry_label_format_names_a_row_its_own_way(key, expected):
    schema = MIDSchema.from_mapping({"entryLabel": key})

    assert schema.observation_label(LABEL_ROW) == expected


def test_every_offered_choice_is_a_format_that_works():
    """Nothing may be listed in the dropdown that the schema cannot apply."""
    for key, label in entry_label_choices():
        assert label
        assert MIDSchema.from_mapping({"entryLabel": key}).observation_label(LABEL_ROW)


def test_the_default_keeps_the_label_the_application_always_used():
    assert MIDSchema.legacy().observation_label(LABEL_ROW) == "DOJ — 2024"


def test_an_unknown_stored_format_falls_back_rather_than_failing():
    """Settings files are hand-edited; a typo must not stop the app starting."""
    schema = MIDSchema.from_mapping({"entryLabel": "no-such-format"})

    assert schema.entry_label == "x_dash_y"
    assert schema.observation_label(LABEL_ROW) == "DOJ — 2024"
    assert schema.to_mapping()["entryLabel"] == "x_dash_y"


def test_a_blank_identifier_does_not_leave_a_stray_separator():
    schema = MIDSchema.from_mapping({"entryLabel": "x_paren_y"})
    row = {"agency": "DOJ", "year": "", "agency_yr": "DOJ-2024.pdf"}

    assert schema.observation_label(row) == "DOJ"


def test_a_row_with_no_identifiers_still_falls_back_to_the_document():
    schema = MIDSchema.from_mapping({"entryLabel": "x_paren_y"})
    row = {"agency": "", "year": "", "agency_yr": "DOJ-2024.pdf"}

    assert schema.observation_label(row) == "DOJ-2024.pdf"


# ----------------------------------------------------------------------
# The application
# ----------------------------------------------------------------------
@pytest.fixture
def three_row_app(application_factory, mid_row_factory):
    def build(mode="User"):
        rows = [
            mid_row_factory(goal="First goal"),
            mid_row_factory(goal="Second goal", Page=2),
            mid_row_factory(goal="Third goal"),
        ]
        return application_factory(mode, rows=rows)

    return build


@pytest.mark.qt
@pytest.mark.integration
def test_walking_past_a_row_without_touching_it_leaves_it_alone(three_row_app):
    """The whole point of the in-memory flag: no drive-by writes."""
    window = three_row_app()
    window.mid_manager.mark_saved()
    before = window.mid_manager.master_df.copy()

    window.next_mid_entry()

    assert window.mid_manager.master_df.equals(before)
    assert window.mid_manager.is_modified() is False
    assert bool(before.at[0, EDITED_COLUMN]) is False


@pytest.mark.qt
@pytest.mark.integration
def test_editing_a_row_writes_it_and_marks_it_edited(three_row_app):
    window = three_row_app()

    window.ui.set_field_text("goal", "Rewritten goal")
    window.next_mid_entry()

    assert window.mid_manager.master_df.at[0, "goal"] == "Rewritten goal"
    assert bool(window.mid_manager.master_df.at[0, EDITED_COLUMN]) is True
    # Only the row that was edited.
    assert bool(window.mid_manager.master_df.at[1, EDITED_COLUMN]) is False


@pytest.mark.qt
@pytest.mark.integration
def test_typing_the_value_a_row_already_holds_is_not_a_change(three_row_app):
    window = three_row_app()
    window.mid_manager.mark_saved()

    window.ui.set_field_text("goal", "First goal")
    window.next_mid_entry()

    assert bool(window.mid_manager.master_df.at[0, EDITED_COLUMN]) is False
    assert window.mid_manager.is_modified() is False


@pytest.mark.qt
@pytest.mark.integration
def test_presenting_a_row_is_never_mistaken_for_editing_it(three_row_app):
    window = three_row_app()

    window.load_mid_fields_from_row()

    assert window.mid_manager.entry_is_dirty() is False


@pytest.mark.qt
@pytest.mark.integration
def test_the_menu_jumps_to_the_first_unedited_entry(three_row_app):
    window = three_row_app()
    window.mid_manager.set_entry_edited(True, 0)
    window.mid_manager.set_entry_edited(True, 1)

    window.goto_first_unedited_entry()

    assert window.mid_manager.current_index == 2


@pytest.mark.qt
@pytest.mark.integration
def test_jumping_commits_the_row_being_left(three_row_app):
    window = three_row_app()
    window.ui.set_field_text("goal", "Rewritten goal")

    window.goto_first_unedited_entry()

    assert window.mid_manager.master_df.at[0, "goal"] == "Rewritten goal"
    # Row 0 has just been edited, so the first unedited row is now row 1.
    assert window.mid_manager.current_index == 1


@pytest.mark.qt
@pytest.mark.integration
def test_jumping_with_nothing_left_to_do_stays_put(three_row_app):
    window = three_row_app()
    for position in range(3):
        window.mid_manager.set_entry_edited(True, position)
    window.mid_manager.select_mid_entry(1)

    window.goto_first_unedited_entry()

    assert window.mid_manager.current_index == 1


@pytest.mark.qt
@pytest.mark.integration
def test_the_entry_menu_toggle_marks_and_unmarks_the_current_row(three_row_app):
    window = three_row_app()
    action = window.ui.entry_edited_action

    action.trigger()

    assert action.isChecked() is True
    assert bool(window.mid_manager.master_df.at[0, EDITED_COLUMN]) is True

    action.trigger()

    assert action.isChecked() is False
    assert bool(window.mid_manager.master_df.at[0, EDITED_COLUMN]) is False


@pytest.mark.qt
@pytest.mark.integration
def test_the_menu_toggle_shows_the_flag_of_whichever_row_is_open(three_row_app):
    window = three_row_app()
    window.mid_manager.set_entry_edited(True, 1)

    window.update_info_labels()
    assert window.ui.entry_edited_action.isChecked() is False

    window.next_mid_entry()
    assert window.ui.entry_edited_action.isChecked() is True


@pytest.mark.qt
@pytest.mark.integration
def test_the_entry_submenu_is_available_for_further_controls(three_row_app):
    window = three_row_app()

    assert window.ui.entry_menu is not None
    assert window.ui.entry_menu.title() == "&Entry"


@pytest.mark.qt
@pytest.mark.integration
def test_turning_the_page_is_a_change_to_the_row(three_row_app):
    """The page is written into the row, so choosing a different one counts."""
    window = three_row_app()

    window.next_page()
    window.next_mid_entry()

    assert str(window.mid_manager.master_df.at[0, "Page"]) == "2"
    assert bool(window.mid_manager.master_df.at[0, EDITED_COLUMN]) is True


@pytest.mark.qt
@pytest.mark.integration
def test_reviewer_mode_still_marks_a_row_seen_without_calling_it_edited(
    three_row_app,
):
    """Being visited is the reviewer workflow's own record, not a user edit."""
    window = three_row_app("Reviewer")

    window.next_mid_entry()

    assert window.mid_manager.master_df.at[0, "reviewer_status"] == "SEEN"
    assert bool(window.mid_manager.master_df.at[0, EDITED_COLUMN]) is False
    assert window.mid_manager.master_df.at[0, "goal"] == "First goal"


# ----------------------------------------------------------------------
# The settings dialog
# ----------------------------------------------------------------------
@pytest.fixture
def mid_schema_dialog(qtbot, mid_path_factory, sample_rows, app_settings_factory,
                      tmp_path):
    """The MID column dialog, opened on a real sheet.

    Tests read the schema through ``build_schema`` rather than pressing OK:
    the dialog is never exec'd here, and closing one that was never shown
    blocks on Qt's side without ever reaching the schema.
    """
    from mid_schema_dialog import MIDSchemaDialog

    settings = app_settings_factory(
        mid_path=mid_path_factory(sample_rows), data_directory=tmp_path
    )
    dialog = MIDSchemaDialog(settings, None)
    qtbot.addWidget(dialog)
    return dialog


@pytest.mark.qt
def test_the_mid_dialog_offers_every_entry_label_format(mid_schema_dialog):
    combo = mid_schema_dialog.entry_label_combo

    offered = [
        (combo.itemData(index), combo.itemText(index))
        for index in range(combo.count())
    ]
    assert offered == list(entry_label_choices())
    # It opens on whatever is already configured.
    assert combo.currentData() == "x_dash_y"


@pytest.mark.qt
def test_the_dialog_previews_the_label_against_the_configured_columns(
    mid_schema_dialog,
):
    combo = mid_schema_dialog.entry_label_combo
    preview = mid_schema_dialog.entry_label_preview

    assert preview.text() == "Rows will be labelled: agency — year"

    combo.setCurrentIndex(combo.findData("x_paren_y"))
    assert preview.text() == "Rows will be labelled: agency (year)"

    combo.setCurrentIndex(combo.findData("document"))
    assert preview.text() == "Rows will be labelled: agency_yr"


@pytest.mark.qt
def test_the_dialog_opens_on_the_editable_columns_already_configured(
    mid_schema_dialog,
):
    """Reopening the dialog and pressing OK must not clear the selection."""
    selected = [item.text() for item in mid_schema_dialog.interaction_list.selectedItems()]

    assert sorted(selected) == ["goal", "metric", "obj", "stratobj"]
    assert mid_schema_dialog.build_schema().interaction_columns == (
        "stratobj",
        "obj",
        "goal",
        "metric",
    )


@pytest.mark.qt
def test_the_dialog_carries_the_chosen_entry_label_into_the_schema(
    mid_schema_dialog,
):
    combo = mid_schema_dialog.entry_label_combo
    combo.setCurrentIndex(combo.findData("document_xy"))

    schema = mid_schema_dialog.build_schema()

    assert schema.entry_label == "document_xy"
    # This mapping is what lands in the settings file.
    assert schema.to_mapping()["entryLabel"] == "document_xy"
