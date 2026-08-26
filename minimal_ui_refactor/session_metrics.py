"""What this session has done, and how fast it is going.

One :class:`SessionMetrics` object lives on the controller for the lifetime of
a run. The controller tells it when something happens — a row was opened, a row
was written to, a document was loaded — and it answers with formatted values
for the statistics window and, when the user has asked for them, for the
sidebar.

Nothing here is persisted. A metric describes *this run*: closing the
application discards it, and the restart button starts a fresh one.

This module is deliberately Qt-free, like :mod:`module_settings`. It holds the
numbers and decides how they read; the dialogs draw them.

Durations are measured with a monotonic clock rather than the wall clock, so a
daylight-saving change or an NTP correction part-way through a long session
cannot make the elapsed time jump or go backwards. The one wall-clock value —
when the session started — is stamped once at construction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

#: Shown when a metric has nothing meaningful to say yet — most often a rate
#: before the first entry has been completed. An em dash rather than "0", which
#: would claim a measurement we have not made.
UNKNOWN = "—"


@dataclass(frozen=True)
class MetricSpec:
    """One thing worth counting, and how to describe it to a user."""

    key: str
    label: str
    #: One line for the statistics window, explaining what is being counted.
    description: str


#: Every metric, in the order they are presented. The statistics window shows
#: all of them; the sidebar shows whichever subset the user pinned.
METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "session_time",
        "Session time",
        "How long the application has been open.",
    ),
    MetricSpec(
        "entries_completed",
        "Entries completed",
        "Rows written to in this session. Revisiting a row already counted "
        "does not count it twice.",
    ),
    MetricSpec(
        "time_per_entry",
        "Time per entry",
        "Session time divided by entries completed, so it includes reading "
        "and breaks, not just typing.",
    ),
    MetricSpec(
        "entries_visited",
        "Entries visited",
        "Rows opened in this session, whether or not anything was recorded.",
    ),
    MetricSpec(
        "documents_opened",
        "Documents opened",
        "Distinct files loaded. Several rows often share one document.",
    ),
    MetricSpec(
        "entries_remaining",
        "Entries remaining",
        "Rows in the current view that have never been edited.",
    ),
    MetricSpec(
        "projected_remaining",
        "Projected time remaining",
        "Entries remaining at the current time per entry. An estimate, and a "
        "rough one early in a session.",
    ),
    MetricSpec(
        "session_started",
        "Session started",
        "Clock time this run began.",
    ),
)

#: Key -> spec, for lookups from stored settings.
METRICS_BY_KEY = {spec.key: spec for spec in METRIC_SPECS}

#: Every valid key, in presentation order.
METRIC_KEYS = tuple(spec.key for spec in METRIC_SPECS)


def normalize_metric_keys(value) -> list[str]:
    """Clean a stored list of metric keys.

    Unknown keys are dropped and duplicates collapsed, so a hand-edited or
    out-of-date settings file cannot put a broken label on the sidebar. The
    result is returned in presentation order rather than the order it was
    stored in, so the sidebar reads the same way as the statistics window.
    """
    if isinstance(value, str):
        value = [value]
    chosen = {str(key).strip() for key in (value or [])}
    return [key for key in METRIC_KEYS if key in chosen]


def format_duration(seconds) -> str:
    """A duration a person can read at a glance: ``2h 05m``, ``7m 12s``, ``9s``.

    Precision falls away as the magnitude grows — seconds stop being
    interesting once a session is hours old, and would only make the number
    harder to compare against the last time it was looked at.
    """
    if seconds is None:
        return UNKNOWN
    seconds = int(max(0, round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


class SessionMetrics:
    """Counters and timings for one run of the application."""

    def __init__(self, clock=time.monotonic, now=datetime.now):
        """``clock`` and ``now`` are injectable so tests need not sleep."""
        self._clock = clock
        self._started_monotonic = clock()
        self._started_at = now()

        # Sets, not counters: a row revisited is not a second entry, and a
        # document reopened for the next observation is not a second document.
        self._completed_entries: set = set()
        self._visited_entries: set = set()
        self._opened_documents: set = set()
        self._entries_remaining: int | None = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record_entry_opened(self, entry_key) -> None:
        """A row was presented to the user."""
        if entry_key is not None:
            self._visited_entries.add(str(entry_key))

    def record_entry_completed(self, entry_key) -> None:
        """A row was actually written to.

        Called only when a commit wrote something, so a row the user merely
        navigated through is not counted as work done.
        """
        if entry_key is not None:
            self._completed_entries.add(str(entry_key))

    def record_document_opened(self, path) -> None:
        """A document was loaded from disk."""
        if path:
            self._opened_documents.add(str(path))

    def set_entries_remaining(self, count) -> None:
        """How many rows are still unedited, as the MID currently sees it."""
        try:
            self._entries_remaining = max(0, int(count))
        except (TypeError, ValueError):
            self._entries_remaining = None

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    @property
    def session_seconds(self) -> float:
        return max(0.0, self._clock() - self._started_monotonic)

    @property
    def entries_completed(self) -> int:
        return len(self._completed_entries)

    @property
    def entries_visited(self) -> int:
        return len(self._visited_entries)

    @property
    def documents_opened(self) -> int:
        return len(self._opened_documents)

    @property
    def seconds_per_entry(self) -> float | None:
        """Mean session seconds per completed entry, or ``None`` before the first."""
        completed = self.entries_completed
        if not completed:
            return None
        return self.session_seconds / completed

    @property
    def projected_remaining_seconds(self) -> float | None:
        """How long the unedited rows would take at the current rate."""
        rate = self.seconds_per_entry
        if rate is None or self._entries_remaining is None:
            return None
        return rate * self._entries_remaining

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------
    def value(self, key: str) -> str:
        """One metric, formatted for display. Unknown keys give :data:`UNKNOWN`."""
        return self.snapshot().get(key, UNKNOWN)

    def snapshot(self) -> dict[str, str]:
        """Every metric, formatted, keyed by metric key."""
        remaining = self._entries_remaining
        return {
            "session_time": format_duration(self.session_seconds),
            "entries_completed": f"{self.entries_completed:,}",
            "time_per_entry": format_duration(self.seconds_per_entry),
            "entries_visited": f"{self.entries_visited:,}",
            "documents_opened": f"{self.documents_opened:,}",
            "entries_remaining": UNKNOWN if remaining is None else f"{remaining:,}",
            "projected_remaining": format_duration(self.projected_remaining_seconds),
            "session_started": self._started_at.strftime("%H:%M"),
        }

    def rows(self, keys=None):
        """``(spec, formatted value)`` pairs, in presentation order.

        ``keys`` limits the result to a subset; ``None`` gives every metric,
        which is what the statistics window shows.
        """
        values = self.snapshot()
        wanted = METRIC_KEYS if keys is None else normalize_metric_keys(keys)
        return [(METRICS_BY_KEY[key], values[key]) for key in wanted]
