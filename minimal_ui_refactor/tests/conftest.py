import copy
import logging
import os
import sys
from pathlib import Path

import fitz
import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Allows Qt tests to run without opening desktop windows. This must be set
# before PyQt5 is imported by a test module.
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import mid_manager as mid_manager_module
import app_settings as app_settings_module
from app_settings import default_settings
from mid_manager import COLUMN_TYPES, EXPECTED_COLUMNS, MIDManager


@pytest.fixture
def silent_logger():
    logger = logging.getLogger("scraping-app-tests")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    return logger


@pytest.fixture(autouse=True)
def isolate_mid_manager_logging(monkeypatch, silent_logger):
    """Prevent MIDManager tests from creating application log files."""
    monkeypatch.setattr(mid_manager_module, "setup_logger", lambda: silent_logger)


@pytest.fixture
def mid_row_factory():
    """Build a valid synthetic row from the application's current schema."""

    def build(**overrides):
        row = {}
        for column in EXPECTED_COLUMNS:
            column_type = COLUMN_TYPES.get(column, str)
            if column_type is int:
                row[column] = 0
            elif column_type is bool:
                row[column] = False
            else:
                row[column] = ""

        row.update(
            {
                "agency_yr": "AGENCY-2024",
                "agency": "Agency",
                "year": 2024,
                "agid": 1,
                "subagency": "",
                "stratobj": "Strategic objective",
                "obj": "Objective",
                "goal": "Goal",
                "metric": "Metric",
                "PDF Page Number": "1-2",
                "Format": "Text",
                "Format_Detail": "",
                "Results_DisplayFormat": "Text",
                "Table Name/Word Search Keyword": "keyword",
                "Other Detail": "",
                "Format_Type": 19,
                "Format_Type_Updated": 19,
                "Page": 1,
                # Workflow columns are not all required by MIDManager, but the
                # application expects them after loading.
                "classification_scheme": "Performance",
                "metric_status": "Met",
                "target": "Target",
                "actual": "Actual",
                "years_to_evaluation": "",
                "_flag": False,
                "_no_metrics": False,
                "_gen": False,
                "_achieved": False,
                "_future_dated": False,
                "_aggregate": False,
                "notes": "",
                "reviewer_comments": "",
                "reviewer_status": "",
            }
        )
        row.update(overrides)
        return row

    return build


@pytest.fixture
def sample_rows(mid_row_factory):
    return [
        mid_row_factory(metric="Metric A"),
        mid_row_factory(metric="Metric B", Page=2),
        mid_row_factory(
            agency_yr="AGENCY-2025",
            year=2025,
            stratobj="",
            obj="",
            goal="",
            metric="",
        ),
        mid_row_factory(
            agency_yr="OTHER-2025",
            agency="Other Agency",
            year=2025,
            agid=2,
            stratobj="Other strategic objective",
            obj="Other objective",
            goal="Other goal",
            metric="Other metric",
        ),
    ]


@pytest.fixture
def mid_path_factory(tmp_path):
    counter = 0

    def write(rows, *, sheet_name="MID"):
        nonlocal counter
        counter += 1
        path = tmp_path / f"mid_{counter}.xlsx"
        pd.DataFrame(rows).to_excel(path, index=False, sheet_name=sheet_name)
        return path

    return write


@pytest.fixture
def manager_factory(mid_path_factory, sample_rows):
    def build(rows=None, *, sheet_name=0):
        path = mid_path_factory(rows if rows is not None else sample_rows)
        return MIDManager(path, sheet_name=sheet_name)

    return build


@pytest.fixture
def pdf_factory(tmp_path):
    def build(name="AGENCY_2024.pdf", page_texts=None, directory=None):
        target_directory = Path(directory) if directory else tmp_path
        target_directory.mkdir(parents=True, exist_ok=True)
        path = target_directory / name
        document = fitz.open()
        for text in page_texts or ["Page one keyword", "Page two keyword"]:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(path)
        document.close()
        return path

    return build


@pytest.fixture
def app_settings_factory(tmp_path):
    def build(
        *, mid_path, data_directory, mode="User", schema=None, extra_settings=None
    ):
        settings = copy.deepcopy(default_settings)
        log_directory = tmp_path / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        settings.update(
            {
                "MIDLocation": str(mid_path),
                "MIDSheetName": 0,
                "dataDirectory": str(data_directory),
                "logFileDirectory": str(log_directory),
                "userMode": mode,
                "UIScale": "1.0",
                "evaluationClasses": {
                    "Performance": {"option_types": ["Met", "Not Met"]}
                },
                "defaultClass": "Performance",
            }
        )
        if schema is not None:
            settings["midSchema"] = schema
        if extra_settings:
            settings.update(extra_settings)
        return settings

    return build


class DeterministicTextScraper:
    def __init__(self, pages, metadata=None):
        self.pages = pages if isinstance(pages, list) else [pages]
        self.result = None

    def scrape(self):
        self.result = {
            "format": "text",
            "text": [
                f"Page {index + 1}: strategic objective objective goal metric target actual"
                for index, _page in enumerate(self.pages)
            ],
        }


@pytest.fixture
def application_factory(
    qtbot,
    monkeypatch,
    tmp_path,
    silent_logger,
    mid_row_factory,
    mid_path_factory,
    pdf_factory,
    app_settings_factory,
):
    from PyQt5.QtWidgets import QMessageBox

    import mid_manager as mid_manager_module
    import scraping_helper as application_module

    windows = []

    def build(
        mode="User", rows=None, schema=None, documents=None, extra_settings=None
    ):
        data_directory = tmp_path / f"data-{mode.lower()}-{len(windows)}"
        rows = rows or [mid_row_factory()]
        mid_path = mid_path_factory(rows)
        if documents is None:
            documents = {
                str(row["agency_yr"]).replace("-", "_") + ".pdf" for row in rows
            }
        for pdf_name in documents:
            pdf_factory(name=pdf_name, directory=data_directory)

        settings = app_settings_factory(
            mid_path=mid_path,
            data_directory=data_directory,
            mode=mode,
            schema=schema,
            extra_settings=extra_settings,
        )
        monkeypatch.setattr(
            application_module, "load_settings", lambda: copy.deepcopy(settings)
        )
        # The app writes settings back when it first records a module. Keep
        # that away from the developer's real user_settings.json.
        settings_path = tmp_path / f"user_settings-{len(windows)}.json"
        monkeypatch.setattr(
            application_module,
            "save_settings",
            lambda values, path=settings_path: app_settings_module.save_settings(
                values, str(path)
            ),
        )
        monkeypatch.setattr(application_module, "setup_logger", lambda: silent_logger)
        monkeypatch.setattr(mid_manager_module, "setup_logger", lambda: silent_logger)
        monkeypatch.setattr(
            application_module,
            "select_scraper_class",
            lambda _settings, _format_type: DeterministicTextScraper,
        )
        # No test may block on a modal. Individual tests override this when
        # they care which button the user pressed.
        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Cancel
        )
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
        monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

        window = application_module.TextScrapingReviewApp()
        window.settings_path = settings_path
        qtbot.addWidget(window)
        window.show()
        qtbot.wait(1)
        windows.append(window)
        return window

    return build
