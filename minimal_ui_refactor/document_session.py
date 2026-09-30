"""One open document and everything derived from it.

A single file often carries several observations. All the MID rows pointing at
the same document and page range share one ``DocumentSession``, so moving
between those observations neither reopens the PDF nor re-runs the scraper, and
the scraped text is genuinely the same text for all of them: an edit made while
recording one observation is visible from the next.

The session owns the document domain only. It never touches Qt; callers convert
:meth:`render_page` output for display.
"""

from __future__ import annotations

from collections import OrderedDict

import fitz  # PyMuPDF


class DocumentSession:
    """An open document, its scrape, and the page text derived from it."""

    def __init__(self, path, document_key, page_indices=None, logger=None):
        """Open ``path``.

        ``page_indices`` may be ``None``, meaning the whole document — which is
        what a MID with no page-reference column implies. Pages outside the
        document are dropped rather than raising later.
        """
        self.path = str(path)
        self.document_key = document_key
        self.logger = logger
        self.covers_whole_document = page_indices is None

        self.doc = fitz.open(path)
        if page_indices is None:
            page_indices = range(self.doc.page_count)
        self.page_indices = [
            int(index) for index in page_indices if 0 <= int(index) < self.doc.page_count
        ]
        if not self.page_indices:
            self.close()
            raise ValueError(f"No pages in {self.path} matched the MID page reference")

        self.page_text_cache = [""] * len(self.page_indices)
        self.scrape_result = {}
        self.content_format = ""
        self.table_images = []
        self.page_overlays = {}

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    def matches(self, path, page_indices) -> bool:
        """Two rows share a session only if both the file and pages match."""
        if str(path) != self.path:
            return False
        if page_indices is None:
            return self.covers_whole_document
        return [int(index) for index in page_indices] == self.page_indices

    def __len__(self) -> int:
        return len(self.page_indices)

    # ------------------------------------------------------------------
    # Scraping
    # ------------------------------------------------------------------
    def scrape(self, scraper_class) -> dict:
        """Run ``scraper_class`` over every page in this session."""
        pages = [self.doc.load_page(index) for index in self.page_indices]
        scraper = scraper_class(pages)
        scraper.scrape()
        result = scraper.result or {}

        self.scrape_result = result
        self.content_format = str(result.get("format", "")).lower()

        if self.content_format == "image":
            self.table_images = self._collect_table_images(result)
            self.page_text_cache = [""] * len(self.page_indices)
        else:
            text = result.get("text")
            if not isinstance(text, list):
                raise ValueError("Expected a list of strings from the Scraper!")
            self.page_text_cache = list(text)

        return result

    def _collect_table_images(self, result):
        result_pages = result.get("result", []) or []
        images = []
        for local_index, _pdf_index in enumerate(self.page_indices):
            tables = (
                result_pages[local_index] if local_index < len(result_pages) else []
            )
            images.append(tables[0].get("table_image") if tables else None)
        return images

    def reset_content(self) -> None:
        """Forget a failed scrape, keeping the document open."""
        self.scrape_result = {}
        self.content_format = ""
        self.table_images = []
        self.page_text_cache = [""] * len(self.page_indices)

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def has_page(self, index: int) -> bool:
        return 0 <= index < len(self.page_indices)

    def page_number(self, index: int) -> int:
        """The zero-based page in the PDF that session index ``index`` refers to."""
        if self.has_page(index):
            return self.page_indices[index]
        return index

    def display_page_number(self, index: int) -> int:
        """The one-based page number a user would recognise."""
        return self.page_number(index) + 1

    def text_at(self, index: int) -> str:
        return self.page_text_cache[index] if self.has_page(index) else ""

    def set_text(self, index: int, value) -> None:
        if self.has_page(index):
            self.page_text_cache[index] = value

    def full_text(self) -> str:
        return "\n\n".join(self.page_text_cache)

    def table_image_at(self, index: int):
        if 0 <= index < len(self.table_images):
            return self.table_images[index]
        return None

    def overlay_at(self, index: int):
        """PNG bytes overlaying this page, if the scraper produced any."""
        overlay = self.page_overlays.get(index)
        if overlay is not None:
            return overlay

        # Compatibility: some scrapers attach overlays to result["pages"].
        for item in self.scrape_result.get("pages") or []:
            if item.get("page_index") == index and item.get("overlay_image"):
                return item["overlay_image"]
        return None

    def render_page(self, index: int, scale: float = 2.0):
        """Render a page as a ``fitz.Pixmap`` upscaled by ``scale``."""
        page = self.doc.load_page(self.page_number(index))
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale))

    # ------------------------------------------------------------------
    # Lifetime
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self.doc is None:
            return
        try:
            self.doc.close()
        except Exception as exc:  # pragma: no cover - defensive
            if self.logger:
                self.logger.warning(f"Failed to close {self.path}: {exc}")
        finally:
            self.doc = None


class DocumentSessionCache:
    """The most recently used sessions, so going back does not re-scrape.

    Scraping is the slow part of opening a document — every page of the file
    when the MID has no page reference. Without a cache, stepping to the next
    row and back again pays that cost twice.

    A cached session keeps its PDF open, so the bound is a file-handle budget
    as much as a memory one. Evicted sessions are closed; the caller is
    responsible for nothing.

    Cached sessions also keep any correction the user typed into the scraped
    text, which is the same guarantee the shared session already gives rows
    that point at one document.
    """

    def __init__(self, maxsize: int = 8):
        self.maxsize = max(1, int(maxsize))
        self._entries: "OrderedDict[tuple, DocumentSession]" = OrderedDict()

    @staticmethod
    def key_for(path, page_indices) -> tuple:
        """Two rows share a cached session only if file *and* pages match."""
        if page_indices is None:
            return (str(path), None)
        return (str(path), tuple(int(index) for index in page_indices))

    def take(self, path, page_indices):
        """Remove and return a session for these pages, or ``None``.

        Removed rather than merely fetched: the caller becomes the owner, and
        a session that is current must not also sit in the cache where a later
        eviction could close the document out from under it.
        """
        session = self._entries.pop(self.key_for(path, page_indices), None)
        if session is not None and session.doc is None:
            # Closed behind our back; treat it as a miss.
            return None
        return session

    def put(self, session) -> None:
        """Hand a session back for reuse, closing whatever falls off the end."""
        if session is None or session.doc is None:
            return
        key = self.key_for(
            session.path, None if session.covers_whole_document else session.page_indices
        )
        existing = self._entries.pop(key, None)
        if existing is not None and existing is not session:
            existing.close()
        self._entries[key] = session
        while len(self._entries) > self.maxsize:
            _, evicted = self._entries.popitem(last=False)
            evicted.close()

    def close_all(self) -> None:
        for session in self._entries.values():
            session.close()
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
