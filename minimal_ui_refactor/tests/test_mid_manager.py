import pytest


def test_source_values_are_read_as_text(manager_factory, mid_row_factory):
    """The application does not know what a project's columns mean."""
    manager = manager_factory([mid_row_factory(year="2024", Format_Type="19")])

    assert manager.df.at[0, "year"] == "2024"
    assert manager.df.at[0, "Format_Type"] == "19"
    assert manager.view_indices == [0]


def test_workflow_booleans_are_read_as_booleans(manager_factory, mid_row_factory):
    manager = manager_factory([mid_row_factory(_flag="True", _gen="yes")])

    assert bool(manager.df.at[0, "_flag"]) is True
    assert bool(manager.df.at[0, "_gen"]) is True


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("3", 3), (3, 3), ("3.0", 3), ("", ""), ("p.3", ""), ("0", ""), (None, "")],
)
def test_the_page_column_is_always_an_int_or_blank(
    manager_factory, mid_row_factory, stored, expected
):
    """The page is compared with page indices, so it is typed on the way in."""
    manager = manager_factory([mid_row_factory(Page=stored)])

    assert manager.df.at[0, "Page"] == expected


def test_a_page_written_from_the_app_is_typed_too(manager_factory, mid_row_factory):
    manager = manager_factory([mid_row_factory(Page="")])

    manager.set_value(0, "Page", "7")

    assert manager.master_df.at[0, "Page"] == 7


def test_missing_anchor_column_is_rejected(manager_factory, mid_row_factory):
    """The column naming each row's document is the one hard requirement."""
    row = mid_row_factory()
    row.pop("Filename")

    with pytest.raises(ValueError, match="missing required column"):
        manager_factory([row])


def test_missing_editable_column_is_created_not_rejected(
    manager_factory, mid_row_factory
):
    """Editable columns are filled in from the app, so absence is not fatal."""
    row = mid_row_factory()
    row.pop("goal")

    manager = manager_factory([row])
    assert manager.df.at[0, "goal"] == ""


@pytest.mark.parametrize(
    ("page_field", "expected"),
    [
        ("p.3", [2]),
        ("3", [2]),
        ("p.3-5", [2, 3, 4]),
        ("p.3, p.5-6", [2, 4, 5]),
        ("1, 1, 2", [0, 1]),
        ("", []),
        ("not-a-page", []),
    ],
)
def test_pdf_page_field_is_normalized(
    manager_factory, mid_row_factory, page_field, expected
):
    manager = manager_factory([mid_row_factory(**{"PDF Page Number": page_field})])

    assert manager.parse_pdf_pages() == expected


def test_navigation_can_move_past_each_boundary(manager_factory, mid_row_factory):
    manager = manager_factory([mid_row_factory()])

    manager.next_mid_entry()
    assert manager.current_index == 1
    assert manager.get_current_row() is None

    manager.current_index = 0
    manager.prev_mid_entry()
    assert manager.current_index == -1
    assert manager.get_current_row() is None


def test_direct_navigation_can_select_first_row(manager_factory):
    manager = manager_factory()
    manager.current_index = 2

    manager.select_mid_entry(0)

    assert manager.current_index == 0


def test_restricted_view_maps_edits_back_to_master_dataframe(manager_factory):
    manager = manager_factory()
    manager.restrict_to_rows([1, 3])

    assert manager.view_indices == [1, 3]
    assert manager.get_current_row()["metric"] == "Metric B"

    manager.set_value(0, "metric", "Edited in restricted view")
    assert manager.df.at[0, "metric"] == "Edited in restricted view"
    assert manager.master_df.at[1, "metric"] == "Edited in restricted view"

    manager.clear_restriction()
    assert manager.view_indices == list(range(len(manager.master_df)))
    assert manager.df.at[1, "metric"] == "Edited in restricted view"


def test_insertion_updates_master_and_restricted_view_mappings(manager_factory):
    manager = manager_factory()
    manager.restrict_to_rows([0, 3])
    new_row = manager.df.iloc[0].to_dict()
    new_row["metric"] = "Inserted metric"

    new_view_index = manager.insert_row_after(0, new_row)

    assert new_view_index == 1
    assert manager.view_indices == [0, 1, 4]
    assert manager.df["metric"].tolist() == [
        "Metric A",
        "Inserted metric",
        "Other metric",
    ]
    assert manager.master_df.at[1, "metric"] == "Inserted metric"


def test_deletion_updates_master_and_current_view(manager_factory):
    manager = manager_factory()
    manager.restrict_to_rows([1, 3])
    manager.current_index = 0

    manager.delete_current_row()

    assert len(manager.master_df) == 3
    assert manager.view_indices == [2]
    assert manager.get_current_row()["agency"] == "Other Agency"


def test_set_value_changes_only_the_targeted_master_row(manager_factory):
    manager = manager_factory()
    manager.restrict_to_rows([2])

    manager.set_value(0, "notes", "Updated note")

    assert manager.df.at[0, "notes"] == "Updated note"
    assert manager.master_df.at[2, "notes"] == "Updated note"
    assert manager.master_df.at[0, "notes"] == ""


# ----------------------------------------------------------------------
# Hierarchy
# ----------------------------------------------------------------------
def test_group_bounds_find_contiguous_xy_block(manager_factory):
    manager = manager_factory()

    assert manager.group_bounds(0) == (0, 1)
    assert manager.group_bounds(1) == (0, 1)
    assert manager.group_bounds(2) == (2, 2)


def test_clone_for_child_preserves_parents_and_clears_descendants(manager_factory):
    manager = manager_factory()
    manager.set_entry_edited(True, 0)

    child = manager.clone_for_child(0, "goal")

    assert child["stratobj"] == "Strategic objective"
    assert child["obj"] == "Objective"
    assert child["goal"] == ""
    assert child["metric"] == ""
    assert bool(child["_gen"]) is True
    assert bool(child["_edited"]) is False


def test_clone_for_child_only_knows_the_configured_levels(manager_factory):
    manager = manager_factory()

    with pytest.raises(ValueError, match="not a hierarchy field"):
        manager.clone_for_child(0, "notes")


def test_hierarchy_rows_sharing_a_document_are_not_duplicates(
    manager_factory, mid_row_factory
):
    """One document, one X/Y, several levels: the levels tell them apart."""
    rows = [
        mid_row_factory(obj="", goal="", metric=""),
        mid_row_factory(goal="", metric=""),
        mid_row_factory(metric="Metric A"),
    ]
    manager = manager_factory(rows)

    assert manager.duplicate_observation_positions() == []


def test_two_identical_hierarchy_rows_are_duplicates(manager_factory, mid_row_factory):
    manager = manager_factory([mid_row_factory(), mid_row_factory()])

    assert manager.duplicate_observation_positions() == [0, 1]


def test_duplicate_prior_year_replaces_current_block(manager_factory, mid_row_factory):
    rows = [
        mid_row_factory(metric="Prior metric A"),
        mid_row_factory(metric="Prior metric B", _flag=True),
        mid_row_factory(
            Filename="AGENCY_2025",
            year=2025,
            stratobj="",
            obj="",
            goal="",
            metric="",
        ),
    ]
    manager = manager_factory(rows)
    manager.current_index = 2

    created = manager.duplicate_prior_year()
    current_rows = manager.master_df[manager.master_df["year"] == "2025"]

    assert created == 2
    assert len(manager.master_df) == 4
    assert current_rows["metric"].tolist() == ["Prior metric A", "Prior metric B"]
    # Everything but the hierarchy comes from the current block's row.
    assert current_rows["Filename"].tolist() == ["AGENCY_2025", "AGENCY_2025"]
    assert current_rows["_gen"].tolist() == [True, True]
    assert current_rows["_flag"].tolist() == [False, False]
    assert manager.view_indices == [0, 1, 2, 3]
    assert manager.current_index == 2
    assert manager.is_modified()


def test_duplicate_prior_year_requires_a_prior_year(manager_factory, mid_row_factory):
    manager = manager_factory([mid_row_factory(Filename="AGENCY_2025", year=2025)])

    with pytest.raises(ValueError, match="No prior-year rows"):
        manager.duplicate_prior_year()


def test_duplicate_prior_year_needs_a_numeric_y(manager_factory, mid_row_factory):
    manager = manager_factory([mid_row_factory(year="FY24")])

    with pytest.raises(ValueError, match="not a whole number"):
        manager.duplicate_prior_year()


def test_duplicate_prior_year_needs_a_hierarchy(mid_path_factory, mid_row_factory):
    from mid_manager import MIDManager
    from mid_schema import MIDSchema

    flat = MIDSchema.from_mapping(
        {
            "xColumn": "agency",
            "yColumn": "year",
            "documentColumn": "Filename",
            "fields": ["metric"],
        }
    )
    manager = MIDManager(mid_path_factory([mid_row_factory()]), schema=flat)

    with pytest.raises(ValueError, match="hierarchy field"):
        manager.duplicate_prior_year()


# ----------------------------------------------------------------------
# Column dtypes
# ----------------------------------------------------------------------
def test_a_number_can_be_written_into_a_column_read_as_text(
    manager_factory, mid_row_factory
):
    """A counter column is created empty and typed as text until a number lands.

    pandas 3 types such a column as ``str`` and refuses a non-string scalar,
    where pandas 2 silently widened it. The application has to widen it
    itself.
    """
    manager = manager_factory([mid_row_factory(years="")])

    manager.set_value(0, "years", 4)

    assert str(manager.df.at[0, "years"]) == "4"
    assert str(manager.master_df.at[0, "years"]) == "4"


def test_writing_a_number_leaves_the_other_rows_alone(
    manager_factory, mid_row_factory
):
    """Widening a column must not disturb what the rest of it already holds."""
    manager = manager_factory([mid_row_factory(years=""), mid_row_factory(years="7")])

    manager.set_value(0, "years", 4)

    assert str(manager.df.at[1, "years"]) == "7"


def test_a_boolean_can_be_written_into_a_column_read_as_text(
    manager_factory, mid_row_factory
):
    manager = manager_factory([mid_row_factory(_verified="")])

    manager.set_value(0, "_verified", True)

    assert bool(manager.df.at[0, "_verified"]) is True


def test_the_edited_flag_can_be_set_on_a_column_read_as_text(
    manager_factory, mid_row_factory
):
    """The persistent edited flag writes a bool and bypasses set_value."""
    manager = manager_factory([mid_row_factory()])

    assert manager.set_entry_edited(True, 0) is True
    assert bool(manager.master_df.at[0, "_edited"]) is True
