# base_extractor.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

_ALLOWED_FIELDS = {"stratobj", "obj", "goal", "metric", "target", "actual", "status"}

class BaseExtractor(ABC):
    def __init__(self, scrape_output, metadata=None):
        self.scrape_output = scrape_output
        self.metadata = metadata or {}

        # NEW: canonical output
        self._records: Optional[List[Dict[str, str]]] = None

        # OPTIONAL: legacy UI payload (your app already expects "text")
        self._text: Any = ""

    @abstractmethod
    def extract(self):
        """Populate self._records (and optionally self._text)."""
        raise NotImplementedError

    def _enforce_records(self, records: Any) -> List[Dict[str, str]]:
        if not isinstance(records, list):
            raise ValueError("Extractor output must be a list of dict records.")

        out: List[Dict[str, str]] = []
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                raise ValueError(f"Record {i} must be a dict.")

            clean: Dict[str, str] = {}
            for k, v in rec.items():
                if k not in _ALLOWED_FIELDS:
                    raise ValueError(
                        f"Record {i} has invalid key '{k}'. Allowed: {sorted(_ALLOWED_FIELDS)}"
                    )
                if v is None:
                    clean[k] = ""
                elif isinstance(v, str):
                    clean[k] = v
                else:
                    raise ValueError(f"Record {i} field '{k}' must be a string (got {type(v).__name__}).")

            # Always ensure status exists and is a string
            clean.setdefault("status", "OK")
            out.append(clean)

        return out

    @property
    def result(self) -> Dict[str, Any]:
        if self._records is None:
            raise ValueError("Extractor has not produced records (self._records is None).")
        records = self._enforce_records(self._records)
        return {
            "method": self.__class__.__name__,
            "format": "records",
            "records": records
        }
