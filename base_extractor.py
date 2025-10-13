# extractors/base_extractor.py
from abc import ABC, abstractmethod

class BaseExtractor(ABC):
    """
    Extractors take a scraper output dict (already validated by BaseScraper._enforce_output_format)
    and return a new dict that can replace or augment the displayed text/html.
    """
    def __init__(self, scrape_output, metadata=None):
        self.scrape_output = scrape_output
        self.metadata = metadata or {}
        self._output = None

    @abstractmethod
    def extract(self):
        """Populate self._output with the extractor's result."""
        pass

    @property
    def result(self):
        if self._output is None:
            raise ValueError("Extractor has not been run yet")
        if not isinstance(self._output, dict):
            raise ValueError("Extractor output must be a dict")
        # Required keys for UI integration:
        # - "text": list[str] (one per page) OR str if a single artifact
        # - "format": "html" | "text" (render hint)
        # - "method": class name (like BaseScraper)
        if "text" not in self._output:
            raise ValueError("Extractor output must include 'text'")
        if "format" not in self._output:
            self._output["format"] = "text"
        if self._output.get("method") != self.__class__.__name__:
            raise ValueError(f"'method' must be '{self.__class__.__name__}'")
        return self._output
