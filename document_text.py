"""Searchable text for a whole document, and the cache that keeps it.

The right-hand panel shows whatever the scraper made of the page in front of
the user. Searching wants something broader: every page of the file, including
the ones this row's page reference excludes, and including pages a table
scraper would have summarised rather than transcribed.

So an index draws from two sources, in this order:

1. **The scraper's own text**, for pages the open session has already read.
   This is what the user is looking at, so a hit reads back exactly as it is
   displayed, and any correction they typed into the panel is searchable.
2. **The document's raw text**, from PyMuPDF, for every other page.

Raw extraction is lazy and cached per page, so opening a document costs
nothing extra and the first search pays only for the pages it has not seen.

This module is Qt-free. It knows about documents and text; the panel draws the
results.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

# Qt reports paragraph and line separators inside selections; treat them, and a
# non-breaking space, as ordinary whitespace when matching.
_WHITESPACE_EXTRAS = {"\u2029", "\u2028", "\u00a0"}

# How far a search reaches. Declared here rather than in the panel so the
# controller can act on the choice without importing from the UI layer.
SEARCH_IN_RANGE = "Only this row's pages"
SEARCH_MARK_OUTSIDE = "Whole document, mark pages outside the row"
SEARCH_ANYWHERE = "Whole document, and let me jump anywhere"

SEARCH_SCOPES = (SEARCH_IN_RANGE, SEARCH_MARK_OUTSIDE, SEARCH_ANYWHERE)

#: A search for something very common is bounded; the caller is told when it bit.
SEARCH_LIMIT = 200

#: How much text to show either side of a hit.
SNIPPET_MARGIN = 45

#: Below this many characters a search matches so much of a document that the
#: result list is noise. Digits are exempt: a year or an amount is short and
#: worth finding.
MINIMUM_QUERY = 2


def collapse_whitespace(text: str) -> tuple[str, list[int]]:
    """Collapse runs of whitespace and map each kept character to its origin.

    Returns ``(collapsed, index_map)`` where ``index_map[i]`` is the index in
    ``text`` that produced ``collapsed[i]``.

    Both the highlighter and the search use this, so a phrase broken across a
    line in the PDF still matches when it is typed on one line.
    """
    collapsed: list[str] = []
    index_map: list[int] = []
    previous_was_space = False

    for index, character in enumerate(text):
        if character.isspace() or character in _WHITESPACE_EXTRAS:
            if not previous_was_space:
                collapsed.append(" ")
                index_map.append(index)
                previous_was_space = True
            continue
        collapsed.append(character)
        index_map.append(index)
        previous_was_space = False

    while collapsed and collapsed[0] == " ":
        collapsed.pop(0)
        index_map.pop(0)
    while collapsed and collapsed[-1] == " ":
        collapsed.pop()
        index_map.pop()

    return "".join(collapsed), index_map


@dataclass(frozen=True)
class SearchHit:
    """One occurrence of a search term."""

    #: Zero-based page within the document.
    page_index: int
    #: One-based page number, as a person would say it.
    page_number: int
    #: Whether this page is one the current row's page reference covers.
    in_range: bool
    #: The matched text with a little of its surroundings.
    snippet: str
    #: Where the match starts within the page's collapsed text. Lets a caller
    #: distinguish two hits on one page.
    offset: int
    #: "scraper" or "document" — which source this page's text came from.
    source: str

    @property
    def location(self) -> str:
        """How this hit is labelled in a result list."""
        label = f"p. {self.page_number}"
        return label if self.in_range else f"{label} (outside this row)"


def build_snippet(text: str, start: int, end: int, margin: int = SNIPPET_MARGIN) -> str:
    """The matched text with some context, elided at both ends."""
    left = max(0, start - margin)
    right = min(len(text), end + margin)
    snippet = text[left:right].strip()
    if left > 0:
        snippet = "…" + snippet
    if right < len(text):
        snippet = snippet + "…"
    return snippet


def is_searchable(query: str) -> bool:
    """Whether a query is specific enough to be worth running."""
    query = (query or "").strip()
    if not query:
        return False
    return len(query) >= MINIMUM_QUERY or query.isdigit()


class DocumentIndex:
    """Every page's text for one document, drawn from scraper then PyMuPDF.

    Holds a reference to an open ``fitz`` document. It does not own it: the
    session that opened the file closes it, and an index outliving its document
    simply stops being able to extract new pages.
    """

    def __init__(self, document, page_indices=(), logger=None):
        """``page_indices`` are the absolute pages the current row covers."""
        self.document = document
        self.in_range_pages = set(int(index) for index in page_indices)
        self.logger = logger
        self._raw_text: dict[int, str] = {}
        self._scraped_text: dict[int, str] = {}

    # ------------------------------------------------------------------
    # Feeding the index
    # ------------------------------------------------------------------
    def set_scraped_text(self, page_index: int, text) -> None:
        """Record what the scraper (or the user) has for one page."""
        self._scraped_text[int(page_index)] = "" if text is None else str(text)

    def set_in_range_pages(self, page_indices) -> None:
        """Update which pages the current row covers, without rebuilding."""
        self.in_range_pages = set(int(index) for index in page_indices)

    @property
    def page_count(self) -> int:
        try:
            return int(self.document.page_count)
        except Exception:  # pragma: no cover - a closed or broken document
            return 0

    def text_for(self, page_index: int) -> tuple[str, str]:
        """``(text, source)`` for one page, extracting raw text if needed."""
        page_index = int(page_index)

        scraped = self._scraped_text.get(page_index)
        if scraped and scraped.strip():
            return scraped, "scraper"

        if page_index in self._raw_text:
            return self._raw_text[page_index], "document"

        text = ""
        try:
            text = self.document.load_page(page_index).get_text() or ""
        except Exception as exc:
            # A page that will not extract is not a reason to fail the search;
            # it simply has nothing to contribute.
            if self.logger:
                self.logger.warning(
                    f"Could not read text from page {page_index + 1}: {exc}"
                )
        self._raw_text[page_index] = text
        return text, "document"

    # ------------------------------------------------------------------
    # Searching
    # ------------------------------------------------------------------
    def search(self, query: str, whole_document: bool = True, limit: int = SEARCH_LIMIT):
        """Every occurrence of ``query``, in page order.

        ``whole_document`` false restricts the search to the pages this row's
        page reference covers. ``limit`` bounds a search for something very
        common; the caller is told when it bit.
        """
        if not is_searchable(query):
            return []

        needle, _ = collapse_whitespace(query.strip())
        needle_lower = needle.lower()
        if not needle_lower:
            return []

        if whole_document:
            pages = range(self.page_count)
        else:
            pages = sorted(self.in_range_pages)

        hits: list[SearchHit] = []
        for page_index in pages:
            text, source = self.text_for(page_index)
            haystack, _ = collapse_whitespace(text)
            haystack_lower = haystack.lower()

            start = 0
            while True:
                position = haystack_lower.find(needle_lower, start)
                if position == -1:
                    break
                end = position + len(needle)
                hits.append(
                    SearchHit(
                        page_index=page_index,
                        page_number=page_index + 1,
                        in_range=page_index in self.in_range_pages,
                        snippet=build_snippet(haystack, position, end),
                        offset=position,
                        source=source,
                    )
                )
                if len(hits) >= limit:
                    return hits
                start = end

        return hits


class DocumentIndexCache:
    """The most recently used document indexes, keyed by file path.

    Building an index is cheap, but the raw text it accumulates is not free to
    re-extract. Keeping the last few means paging back to a document searched a
    moment ago costs nothing.

    Bounded rather than unbounded: a long session over hundreds of documents
    would otherwise hold every page of text it had ever looked at.
    """

    def __init__(self, maxsize: int = 8):
        self.maxsize = max(1, int(maxsize))
        self._entries: "OrderedDict[str, DocumentIndex]" = OrderedDict()

    def get(self, path) -> DocumentIndex | None:
        key = str(path)
        index = self._entries.get(key)
        if index is not None:
            self._entries.move_to_end(key)
        return index

    def put(self, path, index: DocumentIndex) -> None:
        key = str(path)
        self._entries[key] = index
        self._entries.move_to_end(key)
        while len(self._entries) > self.maxsize:
            self._entries.popitem(last=False)

    def discard(self, path) -> None:
        self._entries.pop(str(path), None)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, path) -> bool:
        return str(path) in self._entries
