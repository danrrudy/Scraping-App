from pathlib import Path

import pytest

import extractor_loader
import scraper_loader
from base_extractor import BaseExtractor
from base_scraper import BaseScraper


class ValidScraper(BaseScraper):
    def scrape(self):
        self._output = {
            "page": [1],
            "text": ["scraped text"],
            "method": self.__class__.__name__,
        }


class ValidExtractor(BaseExtractor):
    def extract(self):
        self._records = [{"goal": "Goal text", "target": None}]


def test_scraper_result_is_unavailable_before_scrape():
    scraper = ValidScraper(pages=[object()])

    with pytest.raises(ValueError, match="has not been run"):
        _ = scraper.result


def test_scraper_contract_validates_and_adds_default_status():
    scraper = ValidScraper(pages=[object()])
    scraper.scrape()

    result = scraper.result

    assert result["text"] == ["scraped text"]
    assert result["method"] == "ValidScraper"
    assert result["status"] == "OK"


@pytest.mark.parametrize(
    "output",
    [
        "not a dictionary",
        {"text": ["text"], "method": "ValidScraper"},
        {"page": [1], "method": "ValidScraper"},
        {"page": [1], "text": ["text"], "method": "WrongName"},
    ],
)
def test_scraper_contract_rejects_invalid_output(output):
    scraper = ValidScraper(pages=[object()])
    scraper._output = output

    with pytest.raises(ValueError):
        _ = scraper.result


def test_extractor_contract_normalizes_records():
    extractor = ValidExtractor(scrape_output={"text": ["text"]})
    extractor.extract()

    result = extractor.result

    assert result["format"] == "records"
    assert result["records"] == [
        {"goal": "Goal text", "target": "", "status": "OK"}
    ]


@pytest.mark.parametrize(
    "records",
    [
        {"goal": "not a list"},
        ["not a dictionary"],
        [{"unknown": "value"}],
        [{"goal": 123}],
    ],
)
def test_extractor_contract_rejects_invalid_records(records):
    extractor = ValidExtractor(scrape_output={})
    extractor._records = records

    with pytest.raises(ValueError):
        _ = extractor.result


def test_dynamic_scraper_loader_returns_subclass(tmp_path, monkeypatch, silent_logger):
    monkeypatch.setattr(scraper_loader, "setup_logger", lambda: silent_logger)
    plugin = tmp_path / "custom_scraper.py"
    plugin.write_text(
        "\n".join(
            [
                "from base_scraper import BaseScraper",
                "class CustomScraper(BaseScraper):",
                "    def scrape(self):",
                "        self._output = {'page': [1], 'text': ['ok'], 'method': self.__class__.__name__}",
            ]
        ),
        encoding="utf-8",
    )

    loaded = scraper_loader.load_scraper_class(plugin)

    assert issubclass(loaded, BaseScraper)
    assert loaded.__name__ == "CustomScraper"


def test_dynamic_extractor_loader_returns_subclass(
    tmp_path, monkeypatch, silent_logger
):
    monkeypatch.setattr(extractor_loader, "setup_logger", lambda: silent_logger)
    plugin = tmp_path / "custom_extractor.py"
    plugin.write_text(
        "\n".join(
            [
                "from base_extractor import BaseExtractor",
                "class CustomExtractor(BaseExtractor):",
                "    def extract(self):",
                "        self._records = []",
            ]
        ),
        encoding="utf-8",
    )

    loaded = extractor_loader.load_extractor_class(plugin)

    assert issubclass(loaded, BaseExtractor)
    assert loaded.__name__ == "CustomExtractor"


def test_dynamic_loader_rejects_module_without_required_subclass(
    tmp_path, monkeypatch, silent_logger
):
    monkeypatch.setattr(scraper_loader, "setup_logger", lambda: silent_logger)
    plugin = tmp_path / "not_a_scraper.py"
    plugin.write_text("class Unrelated: pass\n", encoding="utf-8")

    with pytest.raises(ImportError, match="No subclass of BaseScraper"):
        scraper_loader.load_scraper_class(plugin)


def test_scraper_selection_prefers_matching_format(monkeypatch, silent_logger):
    monkeypatch.setattr(scraper_loader, "setup_logger", lambda: silent_logger)
    monkeypatch.setattr(scraper_loader, "load_scraper_class", lambda path: path)
    settings = {
        "scrapingTools": {
            "default": {"path": "default.py", "format_types": []},
            "matched": {"path": "matched.py", "format_types": [19]},
        },
        "defaultScraper": "default",
    }

    assert scraper_loader.select_scraper_class(settings, 19) == "matched.py"


def test_scraper_selection_falls_back_to_configured_default(
    monkeypatch, silent_logger
):
    monkeypatch.setattr(scraper_loader, "setup_logger", lambda: silent_logger)
    monkeypatch.setattr(scraper_loader, "load_scraper_class", lambda path: path)
    settings = {
        "scrapingTools": {
            "default": {"path": "default.py", "format_types": []},
        },
        "defaultScraper": "default",
    }

    assert scraper_loader.select_scraper_class(settings, 999) == "default.py"


def test_extractor_selection_raises_when_no_tool_is_available(
    monkeypatch, silent_logger
):
    monkeypatch.setattr(extractor_loader, "setup_logger", lambda: silent_logger)

    with pytest.raises(ValueError, match="No extractor found"):
        extractor_loader.select_extractor_class(
            {"extractionTools": {}, "defaultExtractor": ""}, 19
        )

