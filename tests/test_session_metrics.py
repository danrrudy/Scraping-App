"""Session statistics: the counters, their formatting, and the sidebar wiring."""

import pytest

import session_metrics
from session_metrics import (
    METRIC_KEYS,
    SessionMetrics,
    UNKNOWN,
    format_duration,
    normalize_metric_keys,
)


class FakeClock:
    """A monotonic clock the test drives, so nothing has to sleep."""

    def __init__(self):
        self.seconds = 0.0

    def __call__(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def metrics(clock):
    return SessionMetrics(clock=clock)


# ----------------------------------------------------------------------
# Counting
# ----------------------------------------------------------------------
def test_session_time_follows_the_clock(metrics, clock):
    clock.advance(90)
    assert metrics.session_seconds == 90


def test_completing_the_same_entry_twice_counts_once(metrics):
    """Revisiting a row to correct it is not a second entry's worth of work."""
    metrics.record_entry_completed("AGENCY-2024")
    metrics.record_entry_completed("AGENCY-2024")

    assert metrics.entries_completed == 1


def test_visiting_and_completing_are_counted_separately(metrics):
    metrics.record_entry_opened("a")
    metrics.record_entry_opened("b")
    metrics.record_entry_completed("a")

    assert metrics.entries_visited == 2
    assert metrics.entries_completed == 1


def test_reopening_one_document_counts_once(metrics):
    """Several observations usually share a document."""
    metrics.record_document_opened("/data/report.pdf")
    metrics.record_document_opened("/data/report.pdf")
    metrics.record_document_opened("/data/other.pdf")

    assert metrics.documents_opened == 2


def test_nothing_is_recorded_for_a_missing_key(metrics):
    metrics.record_entry_opened(None)
    metrics.record_entry_completed(None)
    metrics.record_document_opened("")

    assert (metrics.entries_visited, metrics.entries_completed) == (0, 0)
    assert metrics.documents_opened == 0


# ----------------------------------------------------------------------
# Rates
# ----------------------------------------------------------------------
def test_time_per_entry_is_unknown_before_the_first_entry(metrics, clock):
    clock.advance(300)
    assert metrics.seconds_per_entry is None
    assert metrics.snapshot()["time_per_entry"] == UNKNOWN


def test_time_per_entry_divides_the_session_by_the_entries(metrics, clock):
    clock.advance(600)
    metrics.record_entry_completed("a")
    metrics.record_entry_completed("b")

    assert metrics.seconds_per_entry == 300


def test_projection_needs_both_a_rate_and_a_remaining_count(metrics, clock):
    clock.advance(120)
    metrics.record_entry_completed("a")
    assert metrics.projected_remaining_seconds is None  # no count yet

    metrics.set_entries_remaining(10)
    assert metrics.projected_remaining_seconds == 1200


def test_a_bad_remaining_count_is_ignored_rather_than_raising(metrics):
    metrics.set_entries_remaining("not a number")
    assert metrics.snapshot()["entries_remaining"] == UNKNOWN


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0s"),
        (9, "9s"),
        (59, "59s"),
        (60, "1m 00s"),
        (605, "10m 05s"),
        (3600, "1h 00m"),
        (7845, "2h 10m"),
        (None, UNKNOWN),
    ],
)
def test_durations_read_the_way_a_person_would_say_them(seconds, expected):
    assert format_duration(seconds) == expected


def test_a_negative_duration_does_not_produce_a_negative_string():
    assert format_duration(-5) == "0s"


def test_every_metric_has_a_value_from_the_first_moment(metrics):
    """The statistics window shows all of them, so none may be absent."""
    snapshot = metrics.snapshot()
    assert set(snapshot) == set(METRIC_KEYS)
    assert all(value for value in snapshot.values())


# ----------------------------------------------------------------------
# The stored selection
# ----------------------------------------------------------------------
def test_unknown_metric_keys_are_dropped():
    """A stale settings file must not put a broken label on the sidebar."""
    assert normalize_metric_keys(["session_time", "no_such_metric"]) == ["session_time"]


def test_the_selection_is_returned_in_presentation_order():
    """So the sidebar reads the same way round as the statistics window."""
    scrambled = ["entries_completed", "session_time"]
    assert normalize_metric_keys(scrambled) == ["session_time", "entries_completed"]


def test_duplicates_collapse():
    assert normalize_metric_keys(["session_time", "session_time"]) == ["session_time"]


@pytest.mark.parametrize("value", [None, [], "", {}])
def test_an_empty_selection_is_empty_not_an_error(value):
    assert normalize_metric_keys(value) == []


def test_rows_limited_to_a_subset(metrics):
    rows = metrics.rows(["entries_completed"])
    assert [spec.key for spec, _ in rows] == ["entries_completed"]


def test_rows_default_to_every_metric(metrics):
    assert [spec.key for spec, _ in metrics.rows()] == list(METRIC_KEYS)


def test_the_default_setting_shows_nothing(monkeypatch):
    """Nothing occupies the sidebar until the user asks for it."""
    from app_settings import default_settings

    assert default_settings["statisticsOnMainWindow"] == []


# ----------------------------------------------------------------------
# The controller and the sidebar
# ----------------------------------------------------------------------
@pytest.mark.qt
@pytest.mark.integration
def test_pinned_metrics_appear_above_the_entry_counter(application_factory):
    window = application_factory(
        extra_settings={"statisticsOnMainWindow": ["session_time"]}
    )

    assert window.ui.pinned_statistic_keys() == ("session_time",)

    sidebar = window.ui.left
    assert sidebar.statistics_layout.count() == 1

    # The requirement is positional: directly above the entry counter.
    stats_at = counter_at = None
    for position in range(sidebar.info_layout.count()):
        item = sidebar.info_layout.itemAt(position)
        if item.layout() is sidebar.statistics_layout:
            stats_at = position
        if item.widget() is sidebar.entry_index_label:
            counter_at = position

    assert stats_at is not None and counter_at is not None
    assert stats_at < counter_at


@pytest.mark.qt
@pytest.mark.integration
def test_no_pinned_metrics_leaves_the_sidebar_alone(application_factory):
    window = application_factory()

    assert window.ui.pinned_statistic_keys() == ()
    assert window.ui.left.statistics_layout.count() == 0


@pytest.mark.qt
@pytest.mark.integration
def test_a_saved_edit_counts_as_a_completed_entry(application_factory):
    window = application_factory(
        extra_settings={"statisticsOnMainWindow": ["entries_completed"]}
    )
    assert window.metrics.entries_completed == 0

    field = next(iter(window.ui.field_texts()))
    window.ui.set_field_text(field, "recorded something")
    window.mark_entry_dirty()
    assert window._commit_sidebar_fields() is True

    assert window.metrics.entries_completed == 1


@pytest.mark.qt
@pytest.mark.integration
def test_merely_looking_at_a_row_does_not_complete_it(application_factory):
    """The commit runs on every navigation; only a real write is work done."""
    window = application_factory()

    assert window._commit_sidebar_fields() is False
    assert window.metrics.entries_completed == 0
    assert window.metrics.entries_visited >= 1


@pytest.mark.qt
@pytest.mark.integration
def test_changing_the_selection_redraws_without_a_restart(application_factory):
    window = application_factory()
    assert window.ui.pinned_statistic_keys() == ()

    window.settings["statisticsOnMainWindow"] = ["session_time", "entries_completed"]
    window.apply_statistics_settings()

    assert window.ui.pinned_statistic_keys() == (
        "session_time",
        "entries_completed",
    )


@pytest.mark.qt
@pytest.mark.integration
def test_the_refresh_timer_runs_only_while_something_shows_it(application_factory):
    window = application_factory()
    assert window.statistics_timer is None or not window.statistics_timer.isActive()

    window.settings["statisticsOnMainWindow"] = ["session_time"]
    window.apply_statistics_settings()
    assert window.statistics_timer.isActive()

    window.settings["statisticsOnMainWindow"] = []
    window.apply_statistics_settings()
    assert not window.statistics_timer.isActive()


@pytest.mark.qt
@pytest.mark.integration
def test_remaining_count_comes_from_the_mid(application_factory):
    window = application_factory()

    window.refresh_statistics()

    assert window.metrics.snapshot()["entries_remaining"] == str(
        window.mid_manager.unedited_count()
    )
