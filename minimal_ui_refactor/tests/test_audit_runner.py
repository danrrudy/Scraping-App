import json

import pytest

import audit_runner


class DeterministicAuditScraper:
    def __init__(self, pages, metadata=None):
        self.pages = pages if isinstance(pages, list) else [pages]
        self.result = None

    def scrape(self):
        self.result = {
            "text": [
                "keyword strategic objective objective goal deterministic text"
            ]
        }


@pytest.mark.integration
@pytest.mark.current_schema
def test_audit_writes_detailed_and_summary_reports(
    tmp_path,
    monkeypatch,
    silent_logger,
    manager_factory,
    mid_row_factory,
    pdf_factory,
):
    data_directory = tmp_path / "data"
    log_directory = tmp_path / "audit-logs"
    log_directory.mkdir()
    pdf_factory(
        name="AGENCY_2024.pdf",
        page_texts=["keyword strategic objective objective goal"],
        directory=data_directory,
    )
    manager = manager_factory(
        [
            mid_row_factory(
                **{
                    "PDF Page Number": "1",
                    "Format_Type": 19,
                    "Format_Type_Updated": 19,
                }
            )
        ]
    )
    settings = {
        "dataDirectory": str(data_directory),
        "logFileDirectory": str(log_directory),
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audit_runner, "setup_logger", lambda: silent_logger)
    monkeypatch.setattr(
        audit_runner, "load_scraper_class", lambda _path: DeterministicAuditScraper
    )

    report_path = audit_runner.run_mid_audit(manager, settings)

    report = json.loads((log_directory / "audit_report.json").read_text())
    summary = json.loads((log_directory / "audit_summary.json").read_text())
    assert report_path == str(log_directory / "audit_report.json")
    assert report[0]["status"] == "PASS"
    assert set(report[0]["tests"].values()) == {"PASS"}
    assert summary["total_entries"] == 1
    assert summary["status_counts"] == {"PASS": 1, "FAIL": 0}


@pytest.mark.integration
def test_audit_records_missing_pdf_as_fatal_failure(
    tmp_path,
    monkeypatch,
    silent_logger,
    manager_factory,
    mid_row_factory,
):
    data_directory = tmp_path / "empty-data"
    log_directory = tmp_path / "audit-logs"
    data_directory.mkdir()
    log_directory.mkdir()
    manager = manager_factory([mid_row_factory(**{"PDF Page Number": "1"})])
    settings = {
        "dataDirectory": str(data_directory),
        "logFileDirectory": str(log_directory),
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audit_runner, "setup_logger", lambda: silent_logger)

    audit_runner.run_mid_audit(manager, settings)

    report = json.loads((log_directory / "audit_report.json").read_text())
    assert report[0]["status"] == "FAIL"
    assert "Missing file" in report[0]["tests"]["fatal"]

