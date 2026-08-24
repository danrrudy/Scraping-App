import pandas as pd
import pytest


def test_valid_mid_loads_and_casts_known_column_types(manager_factory, mid_row_factory):
    manager = manager_factory(
        [mid_row_factory(year="2024", Format_Type="19", _flag="True")]
    )

    assert int(manager.df.at[0, "year"]) == 2024
    assert int(manager.df.at[0, "Format_Type"]) == 19
    assert bool(manager.df.at[0, "_flag"]) is True
    assert manager.view_indices == [0]


def test_missing_anchor_column_is_rejected(manager_factory, mid_row_factory):
    """The column naming each row's document is the one hard requirement."""
    row = mid_row_factory()
    row.pop("agency_yr")

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


@pytest.mark.xfail(
    reason="MIDManager.select_mid_entry currently rejects the valid zero-based index 0",
    strict=True,
)
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


def test_group_bounds_find_contiguous_agency_year_block(manager_factory):
    manager = manager_factory()

    assert manager.group_bounds(0) == (0, 1)
    assert manager.group_bounds(1) == (0, 1)
    assert manager.group_bounds(2) == (2, 2)


@pytest.mark.current_schema
def test_clone_for_child_preserves_parents_and_clears_descendants(manager_factory):
    manager = manager_factory()

    child = manager.clone_for_child(0, "goal")

    assert child["stratobj"] == "Strategic objective"
    assert child["obj"] == "Objective"
    assert child["goal"] == ""
    assert child["metric"] == ""
    assert child["metric_status"] == ""
    assert bool(child["_gen"]) is True


@pytest.mark.current_schema
def test_parent_lookup_respects_current_hierarchy(manager_factory, mid_row_factory):
    rows = [
        mid_row_factory(obj="", goal="", metric=""),
        mid_row_factory(goal="", metric=""),
        mid_row_factory(metric="Metric A"),
    ]
    manager = manager_factory(rows)

    assert manager.find_parent_for_obj(2) == 0
    assert manager.find_parent_for_goal(2) == 1


@pytest.mark.current_schema
@pytest.mark.xfail(
    reason="Flag propagation currently updates only the view DataFrame, not master_df",
    strict=True,
)
def test_propagated_flag_is_persistent_in_master_dataframe(
    manager_factory, mid_row_factory
):
    rows = [
        mid_row_factory(obj="", goal="", metric=""),
        mid_row_factory(goal="", metric=""),
        mid_row_factory(metric="Metric A"),
    ]
    manager = manager_factory(rows)

    manager.propagate_flag_from_index(0, True)

    assert manager.df["_flag"].tolist() == [True, True, True]
    assert manager.master_df["_flag"].tolist() == [True, True, True]


@pytest.mark.current_schema
@pytest.mark.xfail(
    reason="duplicate_prior_year currently retains the template row it claims to replace",
    strict=True,
)
def test_duplicate_prior_year_replaces_current_block(manager_factory, mid_row_factory):
    rows = [
        mid_row_factory(metric="Prior metric A"),
        mid_row_factory(metric="Prior metric B"),
        mid_row_factory(
            agency_yr="AGENCY-2025",
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
    current_rows = manager.master_df[manager.master_df["agency_yr"] == "AGENCY-2025"]

    assert created == 2
    assert current_rows["metric"].tolist() == ["Prior metric A", "Prior metric B"]
    assert current_rows["_gen"].tolist() == [True, True]


@pytest.mark.current_schema
def test_duplicate_prior_year_requires_a_prior_year(manager_factory, mid_row_factory):
    manager = manager_factory(
        [mid_row_factory(agency_yr="AGENCY-2025", year=2025)]
    )

    with pytest.raises(ValueError, match="No prior-year rows"):
        manager.duplicate_prior_year()

