"""The document caches: search indexes and reusable sessions."""

import fitz
import pytest

from document_session import DocumentSession, DocumentSessionCache
from document_text import (
    SEARCH_LIMIT,
    DocumentIndex,
    DocumentIndexCache,
    build_snippet,
    collapse_whitespace,
    is_searchable,
)


@pytest.fixture
def pdf(tmp_path):
    """A three-page document with known text on each page."""

    def build(name="report.pdf", pages=None):
        pages = pages or [
            "Habersham County annual report",
            "Nothing of interest here",
            "TOTAL PROJECT\nEXPENDITURES 66992.16",
        ]
        document = fitz.open()
        for body in pages:
            page = document.new_page()
            for line_number, line in enumerate(body.split("\n")):
                page.insert_text((72, 100 + 20 * line_number), line)
        path = tmp_path / name
        document.save(str(path))
        document.close()
        return str(path)

    return build


# ----------------------------------------------------------------------
# Whitespace and snippets
# ----------------------------------------------------------------------
def test_collapsing_maps_every_kept_character_back_to_its_origin():
    collapsed, index_map = collapse_whitespace("a  b\n\nc")
    assert collapsed == "a b c"
    assert len(index_map) == len(collapsed)
    assert "a  b\n\nc"[index_map[collapsed.index("c")]] == "c"


def test_leading_and_trailing_whitespace_is_dropped():
    collapsed, _ = collapse_whitespace("   padded   ")
    assert collapsed == "padded"


@pytest.mark.parametrize(
    "query,expected", [("", False), ("a", False), ("ab", True), ("7", True)]
)
def test_a_query_must_be_specific_enough_to_be_worth_running(query, expected):
    """A single letter matches most of a document; a single digit does not."""
    assert is_searchable(query) is expected


def test_a_snippet_is_elided_only_where_text_was_cut():
    text = "x" * 200
    assert build_snippet(text, 100, 105).startswith("…")
    assert build_snippet(text, 0, 5, margin=500) == text


# ----------------------------------------------------------------------
# Searching
# ----------------------------------------------------------------------
def test_a_search_covers_pages_the_row_does_not(pdf):
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0])

    hits = index.search("EXPENDITURES")

    assert [hit.page_number for hit in hits] == [3]
    assert hits[0].in_range is False
    document.close()


def test_a_search_can_be_held_to_the_rows_own_pages(pdf):
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0])

    assert index.search("EXPENDITURES", whole_document=False) == []
    assert index.search("Habersham", whole_document=False)
    document.close()


def test_a_phrase_split_across_lines_still_matches(pdf):
    """The PDF breaks the line; the user types it on one."""
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0, 1, 2])

    assert index.search("TOTAL PROJECT EXPENDITURES")
    document.close()


def test_scraper_text_is_preferred_over_the_raw_page(pdf):
    """What the user can see is what a search should find."""
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0])
    index.set_scraped_text(0, "a correction the user typed")

    hits = index.search("correction")

    assert [hit.source for hit in hits] == ["scraper"]
    assert index.search("Habersham") == [], "raw text shadowed the scraped text"
    document.close()


def test_an_empty_scrape_falls_back_to_the_raw_page(pdf):
    """A table scraper leaves no text; the page still has some."""
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0])
    index.set_scraped_text(0, "   ")

    assert [hit.source for hit in index.search("Habersham")] == ["document"]
    document.close()


class _StubDocument:
    """A document whose pages return text directly.

    Used where the text matters and the PDF layout does not: writing hundreds
    of matches into a real page just runs them off the edge, where they cannot
    be extracted again.
    """

    def __init__(self, pages):
        self._pages = list(pages)
        self.page_count = len(self._pages)

    def load_page(self, index):
        text = self._pages[index]
        return type("_StubPage", (), {"get_text": lambda self, *a, **k: text})()


def test_a_very_common_term_is_bounded():
    """A search for something on every line must not build an endless list."""
    index = DocumentIndex(_StubDocument(["match " * 400]), page_indices=[0])

    assert len(index.search("match")) == SEARCH_LIMIT


def test_the_bound_is_not_hit_by_an_ordinary_search():
    index = DocumentIndex(_StubDocument(["match once here"]), page_indices=[0])

    assert len(index.search("match")) == 1


def test_an_unreadable_page_does_not_fail_the_search(pdf, silent_logger):
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0], logger=silent_logger)
    document.close()  # every extraction will now raise

    assert index.search("anything") == []


def test_out_of_range_hits_say_so(pdf):
    document = fitz.open(pdf())
    index = DocumentIndex(document, page_indices=[0])

    hit = index.search("EXPENDITURES")[0]

    assert "outside this row" in hit.location
    assert "p. 3" in hit.location
    document.close()


# ----------------------------------------------------------------------
# The index cache
# ----------------------------------------------------------------------
def test_the_index_cache_evicts_the_least_recently_used():
    cache = DocumentIndexCache(maxsize=2)
    cache.put("a", DocumentIndex(None))
    cache.put("b", DocumentIndex(None))
    cache.get("a")  # touching 'a' makes 'b' the oldest
    cache.put("c", DocumentIndex(None))

    assert "a" in cache and "c" in cache
    assert "b" not in cache


# ----------------------------------------------------------------------
# The session cache
# ----------------------------------------------------------------------
def test_a_cached_session_comes_back_for_the_same_pages(pdf):
    path = pdf()
    cache = DocumentSessionCache()
    session = DocumentSession(path, "key", None)
    cache.put(session)

    assert cache.take(path, None) is session
    assert cache.take(path, None) is None, "taking twice returned it twice"
    session.close()


def test_a_different_page_range_is_a_different_session(pdf):
    path = pdf()
    cache = DocumentSessionCache()
    session = DocumentSession(path, "key", [0])
    cache.put(session)

    assert cache.take(path, [1]) is None
    assert cache.take(path, [0]) is session
    session.close()


def test_eviction_closes_the_document(pdf):
    """The bound on open files is what makes caching them acceptable."""
    cache = DocumentSessionCache(maxsize=1)
    first = DocumentSession(pdf("one.pdf"), "one", None)
    second = DocumentSession(pdf("two.pdf"), "two", None)

    cache.put(first)
    cache.put(second)

    assert first.doc is None, "the evicted document was left open"
    assert second.doc is not None
    second.close()


def test_close_all_releases_every_document(pdf):
    cache = DocumentSessionCache()
    sessions = [DocumentSession(pdf(f"{n}.pdf"), str(n), None) for n in range(3)]
    for session in sessions:
        cache.put(session)

    cache.close_all()

    assert all(session.doc is None for session in sessions)
    assert len(cache) == 0


def test_an_already_closed_session_is_not_handed_back(pdf):
    """A session closed behind the cache's back must read as a miss."""
    path = pdf()
    cache = DocumentSessionCache()
    session = DocumentSession(path, "key", None)
    cache.put(session)
    session.close()

    assert cache.take(path, None) is None


def test_a_closed_session_is_not_accepted(pdf):
    cache = DocumentSessionCache()
    session = DocumentSession(pdf(), "key", None)
    session.close()

    cache.put(session)

    assert len(cache) == 0
