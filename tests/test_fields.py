"""Configurable fields: text boxes, lists, and nested hierarchy levels.

A field is one MID column and how the sidebar presents it. Nothing about a
project's columns is built in: the names, the kinds, the hierarchy and the
shortcuts all come from the settings file.
"""

import pytest

from mid_schema import (
    DEFAULT_MID_SCHEMA,
    FieldConfig,
    MIDSchema,
    coerce_page,
    default_field_label,
    normalize_fields,
)
from test_document_anchor import FILENAME_SCHEMA, _filename_rows


# ----------------------------------------------------------------------
# Definitions
# ----------------------------------------------------------------------
def test_bare_column_names_become_text_fields():
    fields = normalize_fields(["goal", "metric"])

    assert [field.column for field in fields] == ["goal", "metric"]
    assert all(field.kind == "text" for field in fields)
    assert fields[0].label == "Goal"


def test_a_comma_separated_string_is_accepted_too():
    assert [f.column for f in normalize_fields("goal, metric")] == ["goal", "metric"]


def test_full_definitions_carry_kind_options_and_hierarchy():
    (field,) = normalize_fields(
        [
            {
                "column": "status",
                "label": "Status",
                "kind": "radio",
                "options": ["Met", "Not Met", "Met"],
                "hierarchy": True,
                "addShortcut": "F2",
            }
        ]
    )

    assert field.kind == "radio"
    assert field.options == ("Met", "Not Met")
    assert field.hierarchy is True
    assert field.add_shortcut == "F2"
    assert field.is_choice


def test_options_may_be_one_string_per_line():
    (field,) = normalize_fields(
        [{"column": "status", "kind": "dropdown", "options": "Met\nNot Met\n\n"}]
    )
    assert field.options == ("Met", "Not Met")


def test_a_text_field_keeps_no_options_and_an_unknown_kind_is_text():
    (field,) = normalize_fields(
        [{"column": "goal", "kind": "slider", "options": ["a", "b"]}]
    )
    assert field.kind == "text"
    assert field.options == ()


def test_unusable_entries_are_dropped_and_columns_deduplicated():
    fields = normalize_fields([{"column": ""}, 42, "goal", {"column": "goal"}])

    assert [field.column for field in fields] == ["goal"]


def test_definitions_round_trip_through_their_mapping():
    field = FieldConfig("status", kind="dropdown", options=("A", "B"))

    assert FieldConfig.from_mapping(field.to_mapping()) == field


@pytest.mark.parametrize(
    ("column", "expected"),
    [("goal", "Goal"), ("years_to_eval", "Years To Eval"), ("LMIG_Exp", "LMIG Exp"), ("FY", "FY")],
)
def test_default_labels_read_well_without_mangling_abbreviations(column, expected):
    assert default_field_label(column) == expected


# ----------------------------------------------------------------------
# The schema
# ----------------------------------------------------------------------
def test_the_default_schema_names_only_the_document_column():
    schema = MIDSchema.default()

    assert schema.document_column == "Filename"
    assert schema.fields == ()
    assert schema.identifier_columns == ()
    assert DEFAULT_MID_SCHEMA["fields"] == []


def test_a_schema_may_have_no_fields_at_all():
    """A fresh installation has nothing configured yet and must still open."""
    schema = MIDSchema.from_mapping({"documentColumn": "Filename"})

    assert schema.interaction_columns == ()
    assert schema.configured_columns == ("Filename",)


def test_the_old_interaction_columns_setting_still_loads():
    schema = MIDSchema.from_mapping(
        {"documentColumn": "Filename", "interactionColumns": ["a", "b"]}
    )

    assert schema.interaction_columns == ("a", "b")
    # It is written back in the new form.
    assert [f["column"] for f in schema.to_mapping()["fields"]] == ["a", "b"]
    assert "interactionColumns" not in schema.to_mapping()


def test_the_document_column_cannot_also_be_a_field():
    with pytest.raises(ValueError, match="cannot also be an editable field"):
        MIDSchema.from_mapping({"documentColumn": "Filename", "fields": ["Filename"]})


def test_hierarchy_levels_are_the_hierarchy_fields_in_order(test_schema):
    assert test_schema.hierarchy_columns == ("stratobj", "obj", "goal", "metric")
    assert test_schema.hierarchy_below("goal") == ("goal", "metric")
    assert test_schema.hierarchy_below("notes") == ()


def test_hierarchy_fields_are_part_of_a_rows_identity(test_schema):
    assert test_schema.uniqueness_columns == (
        "Filename",
        "agency",
        "year",
        "stratobj",
        "obj",
        "goal",
        "metric",
    )


def test_prior_year_copy_needs_identifiers_and_a_hierarchy(test_schema):
    assert test_schema.supports_prior_year_copy
    assert not MIDSchema.from_mapping(FILENAME_SCHEMA).supports_prior_year_copy
    assert not MIDSchema.from_mapping(
        {"documentColumn": "F", "fields": [{"column": "a", "hierarchy": True}]}
    ).supports_prior_year_copy


def test_with_fields_replaces_only_the_fields(test_schema):
    replaced = test_schema.with_fields(["metric"])

    assert replaced.interaction_columns == ("metric",)
    assert replaced.x_column == test_schema.x_column
    assert replaced.document_column == test_schema.document_column


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3), (3.0, 3), ("3.0", 3), (" 12 ", 12), ("", ""), (None, ""), ("x", ""), (0, ""), (-2, "")],
)
def test_page_values_are_ints_or_blank(value, expected):
    assert coerce_page(value) == expected


# ----------------------------------------------------------------------
# In the application
# ----------------------------------------------------------------------
pytest.importorskip("PyQt5", reason="PyQt5 is required for application tests")
pytest.importorskip("pytestqt", reason="pytest-qt is required for Qt fixtures")


CHOICE_SCHEMA = dict(
    FILENAME_SCHEMA,
    fields=[
        "finding",
        {"column": "status", "kind": "radio", "options": ["Met", "Not Met"]},
        {"column": "category", "kind": "dropdown", "options": ["A", "B"]},
    ],
)


@pytest.fixture
def choice_app(application_factory):
    def build(rows=None):
        rows = rows or _filename_rows("REPORT_A.pdf")
        for row in rows:
            row.setdefault("status", "")
            row.setdefault("category", "")
        return application_factory(
            rows=rows, schema=CHOICE_SCHEMA, documents={"REPORT_A.pdf"}
        )

    return build


@pytest.mark.qt
@pytest.mark.integration
def test_list_fields_commit_and_reload_like_text_fields(choice_app):
    window = choice_app()
    window.ui.set_field_text("status", "Not Met")
    window.ui.set_field_text("category", "B")
    window.mark_entry_dirty()

    assert window._commit_sidebar_fields() is True
    row = window.mid_manager.master_df.iloc[0]
    assert row["status"] == "Not Met"
    assert row["category"] == "B"

    window.ui.clear_fields()
    assert window.ui.field_text("status") == ""
    window.load_mid_fields_from_row()
    assert window.ui.field_text("status") == "Not Met"
    assert window.ui.field_text("category") == "B"


@pytest.mark.qt
@pytest.mark.integration
def test_a_stored_value_the_options_do_not_list_is_kept(choice_app):
    rows = _filename_rows("REPORT_A.pdf", status="Partially", category="Z")
    window = choice_app(rows)

    assert window.ui.field_text("category") == "Z"
    # Radios cannot show it, but nothing was written over it either.
    assert window.ui.field_text("status") == ""
    assert window._commit_sidebar_fields() is False
    assert window.mid_manager.master_df.iloc[0]["status"] == "Partially"


@pytest.mark.qt
def test_selections_transfer_only_into_text_fields(choice_app):
    window = choice_app()

    assert window.ui.left.transfer_targets() == [("finding", "Finding")]


@pytest.mark.qt
@pytest.mark.integration
def test_choosing_a_radio_counts_as_an_edit(choice_app):
    window = choice_app()
    assert window.mid_manager.entry_is_dirty() is False

    window.ui.left.field_editors["status"].buttons["Met"].click()

    assert window.mid_manager.entry_is_dirty() is True
    assert window.ui.field_text("status") == "Met"


# ----------------------------------------------------------------------
# Hierarchy in the application
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_the_plus_button_adds_a_row_one_level_down(application_factory):
    window = application_factory()
    before = len(window.mid_manager.master_df)

    window.ui.left.add_level_buttons["goal"].click()

    assert len(window.mid_manager.master_df) == before + 1
    assert window.mid_manager.current_index == 1
    child = window.mid_manager.master_df.iloc[1]
    assert child["stratobj"] == "Strategic objective"
    assert child["obj"] == "Objective"
    assert child["goal"] == ""
    assert child["metric"] == ""
    assert bool(child["_gen"]) is True
    # The sidebar shows the new, partly cleared row.
    assert window.ui.field_text("obj") == "Objective"
    assert window.ui.field_text("goal") == ""


@pytest.mark.qt
@pytest.mark.integration
def test_adding_a_level_commits_the_row_being_left(application_factory):
    window = application_factory()
    window.ui.set_field_text("metric", "Edited before splitting")

    window.on_add_level_clicked("metric")

    assert window.mid_manager.master_df.iloc[0]["metric"] == "Edited before splitting"


@pytest.mark.qt
def test_plus_shortcuts_come_from_the_field_configuration(application_factory):
    from conftest import TEST_SCHEMA

    schema = dict(
        TEST_SCHEMA,
        fields=[
            {"column": "stratobj", "hierarchy": True, "addShortcut": "F1"},
            {"column": "obj", "hierarchy": True},
            {"column": "goal", "hierarchy": True, "addShortcut": "Ctrl+G"},
            {"column": "metric"},
        ],
    )
    window = application_factory(schema=schema)
    buttons = window.ui.left.add_level_buttons

    assert set(buttons) == {"stratobj", "obj", "goal"}
    assert buttons["stratobj"].shortcut().toString() == "F1"
    assert buttons["obj"].shortcut().toString() == ""
    assert buttons["goal"].shortcut().toString() == "Ctrl+G"


@pytest.mark.qt
def test_the_prior_year_control_exists_only_where_it_can_work(application_factory):
    with_hierarchy = application_factory()
    assert "duplicate_year" in with_hierarchy.ui.left.control_buttons

    flat = application_factory(
        rows=_filename_rows("REPORT_A.pdf"),
        schema=FILENAME_SCHEMA,
        documents={"REPORT_A.pdf"},
    )
    assert "duplicate_year" not in flat.ui.left.control_buttons


@pytest.mark.qt
@pytest.mark.integration
def test_copying_the_prior_year_reloads_the_rebuilt_block(
    application_factory, mid_row_factory
):
    rows = [
        mid_row_factory(metric="Prior A"),
        mid_row_factory(metric="Prior B"),
        mid_row_factory(
            Filename="AGENCY_2025", year=2025, stratobj="", obj="", goal="", metric=""
        ),
    ]
    window = application_factory(rows=rows)
    window.mid_manager.select_mid_entry(2)
    window.load_mid_entry_document()

    window.duplicate_prior_year()

    assert len(window.mid_manager.master_df) == 4
    assert window.mid_manager.current_index == 2
    assert window.ui.field_text("metric") == "Prior A"


@pytest.mark.qt
@pytest.mark.integration
def test_a_failed_prior_year_copy_is_reported_not_raised(
    application_factory, monkeypatch
):
    from PyQt5.QtWidgets import QMessageBox

    window = application_factory()
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: shown.append(args[2]))

    window.duplicate_prior_year()

    assert shown and "No prior-year rows" in shown[0]
    assert len(window.mid_manager.master_df) == 1


# ----------------------------------------------------------------------
# The field dialog
# ----------------------------------------------------------------------
@pytest.fixture
def field_dialog(qtbot, mid_path_factory, sample_rows, app_settings_factory, tmp_path):
    from field_dialog import FieldDialog

    settings = app_settings_factory(
        mid_path=mid_path_factory(sample_rows), data_directory=tmp_path
    )
    dialog = FieldDialog(settings, None)
    qtbot.addWidget(dialog)
    return dialog


@pytest.mark.qt
def test_the_dialog_opens_on_the_configured_fields(field_dialog):
    assert [d["column"] for d in field_dialog.definitions] == list(
        ("stratobj", "obj", "goal", "metric")
    )
    assert field_dialog.list_widget.count() == 4
    # Reopening and pressing OK must change nothing.
    schema = field_dialog.build_schema()
    assert schema.hierarchy_columns == ("stratobj", "obj", "goal", "metric")


@pytest.mark.qt
def test_the_editor_writes_back_into_the_selected_field(field_dialog):
    field_dialog.list_widget.setCurrentRow(3)
    field_dialog.kind_combo.setCurrentIndex(field_dialog.kind_combo.findData("radio"))
    field_dialog.options_edit.setPlainText("Met\nNot Met")
    field_dialog.hierarchy_check.setChecked(False)
    field_dialog.label_edit.setText("Result")

    metric = field_dialog.build_schema().field("metric")

    assert metric.kind == "radio"
    assert metric.options == ("Met", "Not Met")
    assert metric.hierarchy is False
    assert metric.label == "Result"


@pytest.mark.qt
def test_a_new_field_can_name_a_column_the_sheet_lacks(field_dialog):
    field_dialog._add()
    field_dialog.column_combo.setCurrentText("brand_new")
    field_dialog.hierarchy_check.setChecked(True)
    field_dialog.shortcut_edit.setText("F5")

    schema = field_dialog.build_schema()

    assert schema.field("brand_new").hierarchy is True
    assert schema.field("brand_new").add_shortcut == "F5"
    assert schema.creatable_columns(field_dialog.columns) == ("brand_new",)


@pytest.mark.qt
def test_the_dialog_refuses_half_finished_fields(field_dialog):
    field_dialog._add()
    with pytest.raises(ValueError, match="needs a MID column"):
        field_dialog.build_schema()

    field_dialog.column_combo.setCurrentText("goal")
    with pytest.raises(ValueError, match="same MID column"):
        field_dialog.build_schema()

    field_dialog.column_combo.setCurrentText("status")
    field_dialog.kind_combo.setCurrentIndex(field_dialog.kind_combo.findData("dropdown"))
    with pytest.raises(ValueError, match="has no options"):
        field_dialog.build_schema()
