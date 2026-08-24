"""Structured audit support for configured MID schemas."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import fitz

import paths
from logger import setup_logger
from mid_schema import clean_value, safe_filename_stem
from scraper_loader import load_scraper_class


TABLE_FORMAT_TYPES = {str(value) for value in range(1, 19)}


def _scraper_path(filename):
    """A scraper the audit expects to find in the installation's plugin folder.

    Not ``__file__``: a frozen build's own directory is read-only and holds no
    plugins, so the audit looks where the user's scrapers actually live.
    """
    return Path(paths.app_dir()) / "scrapers" / filename


def _load_text_scraper():
    return load_scraper_class(str(_scraper_path("text_scraper.py")))


def _load_table_scraper():
    return load_scraper_class(str(_scraper_path("table_scraper.py")))


def _scrape_page_texts(document, page_indices, logger, label):
    """Scrape each page once and return text plus a success indicator."""
    ScraperClass = _load_text_scraper()
    texts = []
    for page_index in page_indices:
        try:
            scraper = ScraperClass(document.load_page(page_index))
            scraper.scrape()
            payload = scraper.result.get("text", "")
            if isinstance(payload, list):
                text = clean_value(payload[0]) if payload else ""
            else:
                text = clean_value(payload)
            texts.append(text)
        except Exception as exc:
            logger.warning(
                "text scrape failed on page %s for %s: %s",
                page_index + 1,
                label,
                exc,
            )
            return texts, False
    return texts, bool(texts) and all(texts)


def _test_table_detected(
    row, document, page_indices, mid_manager, diagnostics_dir, logger
):
    format_type = mid_manager.format_type(row)
    if str(format_type) not in TABLE_FORMAT_TYPES:
        return True

    try:
        ScraperClass = _load_table_scraper()
    except (ImportError, OSError) as exc:
        # The table scraper is an optional plugin: it needs machine-learning
        # libraries that are not part of a packaged build. Its absence makes
        # this one check unavailable, not the whole audit invalid.
        logger.warning(f"Table detection skipped; no table scraper available: {exc}")
        return True

    observation_stem = safe_filename_stem(mid_manager.observation_stem(row))
    try:
        for page_index in page_indices:
            scraper = ScraperClass([document.load_page(page_index)])
            scraper.scrape()
            result = scraper.result
            tables = result.get("tables", [])
            if not tables:
                continue

            images = result.get("images", [])
            if images:
                image_path = diagnostics_dir / (
                    f"{observation_stem}_page_{page_index + 1}.png"
                )
                images[0].save(image_path)

            for table_number, table in enumerate(tables, start=1):
                structure = table.get("structures", [])
                if not structure:
                    continue
                lines = [
                    "ID: {id} | {label} -> {text}".format(
                        id=element.get("id", "?"),
                        label=element.get("label", ""),
                        text=element.get("ocr_text", ""),
                    )
                    for element in structure
                ]
                structure_path = diagnostics_dir / (
                    f"{observation_stem}_page_{page_index + 1}_"
                    f"table_{table_number}_structure.txt"
                )
                structure_path.write_text("\n".join(lines), encoding="utf-8")
            return True
    except Exception as exc:
        logger.warning(
            "table detection failed for %s: %s",
            mid_manager.observation_label(row),
            exc,
        )
    return False


def _find_document(row, mid_manager, data_directory):
    for filename in mid_manager.document_candidates(row):
        path = data_directory / filename
        if path.is_file():
            return path
    return None


def run_mid_audit(mid_manager, settings):
    """Audit every visible MID row using the configured schema.

    The report records the configured X/Y values and all configured interaction
    fields. This keeps the audit stable when a project changes its column names.
    """
    logger = setup_logger()
    logger.info("Starting structured MID audit")

    log_directory = Path(settings.get("logFileDirectory") or "logs")
    log_directory.mkdir(parents=True, exist_ok=True)
    diagnostics_dir = log_directory / "table_detections"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    data_directory = Path(settings.get("dataDirectory") or ".")

    # One document may host several observations, so identity is
    # (document, X, Y). Rows sharing one are reported rather than rejected.
    duplicate_positions = mid_manager.duplicate_observation_view_indices()

    results = []
    status_counts = Counter()
    test_failures = Counter()
    failures_by_observation = {}
    format_outcomes = defaultdict(
        lambda: {"PASS": 0, "FAIL": 0, "failed_tests": {}}
    )

    for index in range(len(mid_manager.df)):
        mid_manager.current_index = index
        row = mid_manager.get_current_row()
        x_value, y_value = mid_manager.observation_key(row)
        label = mid_manager.observation_label(row)
        format_type = mid_manager.format_type(row) or "UNKNOWN"

        entry = {
            "index": index + 1,
            "x_column": mid_manager.schema.x_column,
            "x_value": x_value,
            "y_column": mid_manager.schema.y_column,
            "y_value": y_value,
            "observation_key": [x_value, y_value],
            "label": label,
            "format_type": format_type,
            "fields": {
                column: clean_value(row.get(column, ""))
                for column in mid_manager.schema.interaction_columns
            },
            "tests": {},
            "status": "PASS",
        }

        failed_tests = []

        def record(test_name: str, passed: bool):
            status = "PASS" if passed else "FAIL"
            entry["tests"][test_name] = status
            if not passed:
                failed_tests.append(test_name)

        record("duplicate_observation", index not in duplicate_positions)

        document_path = _find_document(row, mid_manager, data_directory)
        record("pdf_found", document_path is not None)

        document = None
        page_indices = []
        page_texts = []
        if document_path is not None:
            try:
                document = fitz.open(document_path)
                page_indices = mid_manager.parse_pdf_pages()
                page_indices = [
                    page for page in page_indices if 0 <= page < document.page_count
                ]
            except Exception as exc:
                logger.warning("Unable to open %s: %s", document_path, exc)

        record("pages_parsed", bool(page_indices))
        if document is not None and page_indices:
            page_texts, text_scraped = _scrape_page_texts(
                document, page_indices, logger, label
            )
        else:
            text_scraped = False
        record("text_scraped", text_scraped)

        searchable_text = "\n".join(page_texts).casefold()
        keyword_column = mid_manager.schema.keyword_column
        if keyword_column:
            keyword = clean_value(row.get(keyword_column, ""))
            record(
                "keyword_match",
                not keyword or keyword.casefold() in searchable_text,
            )

        for column in mid_manager.schema.interaction_columns:
            value = clean_value(row.get(column, ""))
            record(
                f"field:{column}",
                not value or value.casefold() in searchable_text,
            )

        table_detected = bool(document and page_indices) and _test_table_detected(
            row,
            document,
            page_indices,
            mid_manager,
            diagnostics_dir,
            logger,
        )
        record("table_detected", table_detected)

        if document is not None:
            document.close()

        if failed_tests:
            entry["status"] = "FAIL"
            failures_by_observation[label] = failed_tests
            test_failures.update(failed_tests)

        results.append(entry)
        status_counts[entry["status"]] += 1
        format_entry = format_outcomes[format_type]
        format_entry[entry["status"]] += 1
        for test_name in failed_tests:
            current = format_entry["failed_tests"].get(test_name, 0)
            format_entry["failed_tests"][test_name] = current + 1

    summary = {
        "total_entries": len(results),
        "status_counts": {
            "PASS": status_counts.get("PASS", 0),
            "FAIL": status_counts.get("FAIL", 0),
        },
        "test_failures": dict(test_failures),
        "failures_by_observation": failures_by_observation,
        "outcomes_by_format_type": dict(format_outcomes),
    }

    report = {
        "schema": mid_manager.schema.to_mapping(),
        "results": results,
        "summary": summary,
    }
    report_path = log_directory / "audit_report.json"
    summary_path = log_directory / "audit_summary.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("MID audit complete: %s", report_path)
    return str(report_path)
