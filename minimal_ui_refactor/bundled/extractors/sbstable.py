# extractors/sbstable.py

from base_extractor import BaseExtractor


class sbstable(BaseExtractor):
    """
    Barebones extractor implementation.

    This extractor ignores the scrape content and emits a single,
    well-formed record to demonstrate the canonical output structure.
    """

    def extract(self):
        # Minimal example: one record with a few fields populated
        self._records = [
            {
                "stratobj": "",
                "obj": "",
                "goal": "",
                "metric": "",
                "target": "",
                "actual": "",
                "status": "OK",
            }
        ]

        # Optional legacy/UI payload (safe to omit entirely if unused)
        self._text = ""
