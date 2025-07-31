# audit_runner.py

import os
import json
import fitz
import re
import pandas as pd
from logger import setup_logger
from scraper_loader import load_scraper_class


def run_mid_audit(mid_manager, settings):
    logger = setup_logger()
    logger.info("Starting structured MID audit")

    total_rows = len(mid_manager.df)
    results = []
    summary = {
        "total_entries": total_rows,
        "status_counts": {"PASS": 0, "FAIL": 0},
        "test_failures": {},  # test_name -> failure count
        "failures_by_agency": {},  # agency -> { year -> [failed_test1, ...]}
        "outcomes_by_format_type": {},  # format_type -> {"PASS": x, "FAIL": y, "failed tests": { test_name: count}}
    }


    # Define test suite
    def test_pdf_found(row, doc, page_indices, settings):
        return doc is not None

    def test_pages_parsed(row, doc, page_indices, settings):
        return bool(page_indices)

    def test_text_scraped(row, doc, page_indices, settings):
        if not page_indices:
            return False

        scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "text_scraper.py")
        ScraperClass = load_scraper_class(scraper_path)

        for page_num in page_indices:
            try:
                page = doc.load_page(page_indices[0])
                scraper = ScraperClass(page)
                result = scraper.scrape()
                text = bool(result.get("text", "").strip())
                if not text:
                    return False    # Fail on first non-scraped page
            except Exception as e:
                logger.warning(f"text_scraped error on page {page_num+1} for {row.get('agency_yr')}: {e}")
                return False

        return True # Only reached if all pages returned valid text

    def test_keyword_match(row, doc, page_indices, settings):
        keyword = row.get("Table Name/Word Search Keyword", "").strip()
        if not keyword:
            return True  # Nothing to match = PASS

        scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "text_scraper.py")
        ScraperClass = load_scraper_class(scraper_path)

        for page_num in page_indices:
            try:
                page = doc.load_page(page_num)
                scraper = ScraperClass(page)
                result = scraper.scrape()
                text = result.get("text", "").lower()
                if keyword.lower() in text:
                    return True  # Match found = PASS
            except Exception as e:
                logger.warning(f"keyword_match error on page {page_num+1} for {row.get('agency_yr')}: {e}")
                return False

        return False  # Keyword not found on any listed page = FAIL

    def test_stratobj_match(row, doc, page_indices, settings):
        stratobj = row.get("stratobj", "").strip()
        if not stratobj:
            return True  # Nothing to match = PASS

        scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "text_scraper.py")
        ScraperClass = load_scraper_class(scraper_path)

        for page_num in page_indices:
            try:
                page = doc.load_page(page_num)
                scraper = ScraperClass(page)
                result = scraper.scrape()
                text = result.get("text", "").lower()
                if stratobj.lower() in text:
                    return True  # Match found = PASS
            except Exception as e:
                logger.warning(f"stratobj_match error on page {page_num+1} for {row.get('agency_yr')}: {e}")
                return False

        return False  # stratobj not found on any listed page = FAIL

    def test_obj_match(row, doc, page_indices, settings):
        obj = row.get("obj", "").strip()
        if not obj:
            return True  # Nothing to match = PASS

        scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "text_scraper.py")
        ScraperClass = load_scraper_class(scraper_path)

        for page_num in page_indices:
            try:
                page = doc.load_page(page_num)
                scraper = ScraperClass(page)
                result = scraper.scrape()
                text = result.get("text", "").lower()
                if obj.lower() in text:
                    return True  # Match found = PASS
            except Exception as e:
                logger.warning(f"obj_match error on page {page_num+1} for {row.get('agency_yr')}: {e}")
                return False

        return False  # obj not found on any listed page = FAIL

    def test_goal_match(row, doc, page_indices, settings):
        goal = row.get("goal", "").strip()
        goal = re.sub(r"\[.*?\]", "", goal).strip()
        logger.debug(f"testing goal {goal} for {row.get("agency", "")}")

        if not goal:
            return True  # Nothing to match = PASS

        scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "text_scraper.py")
        ScraperClass = load_scraper_class(scraper_path)

        for page_num in page_indices:
            try:
                page = doc.load_page(page_num)
                scraper = ScraperClass(page)
                result = scraper.scrape()
                text = result.get("text", "").lower()
                if goal.lower() in text:
                    return True  # Match found = PASS
            except Exception as e:
                logger.warning(f"goal_match error on page {page_num+1} for {row.get('agency_yr')}: {e}")
                return False

        return False  # goal not found on any listed page = FAIL

    def test_table_detected(row, doc, page_indices, settings):
        #Expecting tables in these types
        if row.get("Format_Type") not in [1, 2, 3, 4, 5, 6 ,7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]:
            return True

        logger.debug(f"Using MTT to detect tables in {row.get("agency_yr","")}")
        scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "table_scraper.py")
        ScraperClass = load_scraper_class(scraper_path)

        try:
            for page_num in page_indices:
                page = doc.load_page(page_num)
                scraper = ScraperClass([page])
                result = scraper.scrape()
                if result.get("tables_found", 0) > 0:
                    logger.debug(f"{result.get("tables_found")} table(s) found in {row.get("agency_yr")} page {page_num}")
                    return True # Pass if any page detects a table
        except Exception as e:
            logger.warning(f"table_detected error on {row.get('agency_yr')}: {e}")
            return False 
        logger.debug(f"No tables detected in {row.get("agency_yr")} page {page_num}")
        return False # No tables found

# List all tests here and define them above. This is the list that is looped over.
    tests = [
        ("pdf_found", test_pdf_found),
        ("pages_parsed", test_pages_parsed),
        ("text_scraped", test_text_scraped),
        ("keyword_match", test_keyword_match),
        ("stratobj_match", test_stratobj_match),
        ("obj_match", test_obj_match),
        ("goal_match", test_goal_match),
        ("table_detected", test_table_detected),
    ]

    # Loop over each row in the MID to run tests
    for i in range(total_rows):
        mid_manager.current_index = i
        row = mid_manager.get_current_row()
        agency_yr = row.get("agency_yr", f"UNKNOWN_{i}")
        agency = row.get("agency", "UNKNOWN")
        year = row.get("year", "UNKNOWN")
        format_type = row.get("Format_Type", "UNKNOWN")
        stratobj = row.get("stratobj", "UNKNOWN")
        obj = row.get("obj", "UNKNOWN")
        goal = row.get("goal", "UNKNOWN")
        label = f"{row.get('agency', 'UNKNOWN')} ({row.get('year', 'UNKNOWN')})"
        logger.debug(f"Auditing line {i} of {total_rows}")

        entry = {
            "index": i,
            "agency_yr": agency_yr,
            "agency": agency,
            "year": int(year) if pd.notna(year) else "UNKNOWN",
            "format_type": int(format_type) if pd.notna(format_type) else "UNKNOWN",
            "stratobj": stratobj,
            "obj": obj,
            "goal": goal,
            "label": label,
            "tests": {},
            "status": "PASS"
        }

        try:
            filename = f"{agency_yr.replace('-', '_')}.pdf"
            path = os.path.join(settings.get("dataDirectory", ""), filename)
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Missing file: {filename}")

            doc = fitz.open(path)
            page_indices = mid_manager.parse_pdf_pages()

            for test_name, test_func in tests:
                try:
                    passed = test_func(row, doc, page_indices, settings)
                    entry["tests"][test_name] = "PASS" if passed else "FAIL"
                    if not passed:
                        entry["status"] = "FAIL"
                        summary["test_failures"][test_name] = summary["test_failures"].get(test_name, 0) + 1
                except Exception as e:
                    entry["tests"][test_name] = f"ERROR: {e}"
                    entry["status"] = "FAIL"
                    summary["test_failures"][test_name] = summary["test_failures"].get(test_name, 0) + 1
                    logger.warning(f"{test_name} ERROR for {agency_yr}: {e}")

        except Exception as e:
            entry["status"] = "FAIL"
            entry["tests"]["fatal"] = str(e)
            logger.warning(f"AUDIT FATAL ERROR for {agency_yr}: {e}")
            summary["test_failures"]["fatal"] = summary["test_failures"].get("fatal", 0) + 1

        results.append(entry)

        summary["status_counts"][entry["status"]] += 1

        agency = entry["agency"]
        year = str(entry["year"])
        fmt = str(entry["format_type"])

        failed_tests = [test for test, result in entry["tests"].items() if result == "FAIL" or result.startswith("ERROR")]

        # Track outcomes by agency-year
        if entry["status"] == "FAIL":
            summary["failures_by_agency"].setdefault(agency, {})
            summary["failures_by_agency"][agency].setdefault(year, [])
            summary["failures_by_agency"][agency][year].extend(failed_tests)

        # Outcomes by Format Type
        outcome_bucket = summary["outcomes_by_format_type"].setdefault(str(fmt), {"PASS": 0, "FAIL": 0, "failed_tests": {}})
        outcome_bucket[entry["status"]] += 1
        for test in failed_tests:
            outcome_bucket["failed_tests"][test] = outcome_bucket["failed_tests"].get(test, 0) + 1



    # Save Audit file to the logs directory
    log_dir = settings.get("logFileDirectory", "./logs")
    output_path = os.path.join(log_dir, "audit_report.json")
    summary_path = os.path.join(log_dir, "audit_summary.json")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        for agency, failures in summary["failures_by_agency"].items():
            summary["failures_by_agency"][agency] = {
                year: sorted(set(tests)) for year, tests in failures.items()
            }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        logger.info(f"Audit finished. Detailed report: {output_path}")
        logger.info(f"Summary saved to: {summary_path}")
        return output_path

    except Exception as e:
        logger.critical(f"Failed to save audit output: {e}")
        raise RuntimeError(f"Failed to save audit output: {e}")
