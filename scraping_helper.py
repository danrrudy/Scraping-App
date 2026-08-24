import base64
import json
import os
import re
import sys
from io import BytesIO

import fitz  # PyMuPDF
import pandas as pd
from PyQt5.QtCore import QByteArray, QEvent, QRegExp, Qt
from PyQt5.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_settings import load_settings, save_settings
from audit_runner import run_mid_audit
from extractor_loader import select_extractor_class
from image_canvas import ImageCanvas
from logger import setup_logger
from mid_manager import MIDManager
from scraper_loader import select_scraper_class

# local imports
from settings_window import SettingsDialog

# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.dirname(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

BASE_WIDTH = 1200
BASE_HEIGHT = 800

# TextScrapingReviewApp


class TextScrapingReviewApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = setup_logger()
        self.logger.info("Initialized Logger")
        self.setWindowTitle("Text Scraping Review App")
        #        self.resize(1200, 800)

        self.settings = load_settings()

        manual_scale = float(self.settings.get("UIScale", "1.0"))

        auto_scale = self.get_screen_scale()

        self.ui_scale = min(manual_scale, auto_scale)

        self.logger.info(f"opening application at UI scale {self.ui_scale}")

        self.resize(
            self.scaled(BASE_WIDTH, self.ui_scale),
            self.scaled(BASE_HEIGHT, self.ui_scale),
        )

        self.mode = self.settings.get("userMode", "User").lower()
        self.mid_df = None
        self.current_mid_index = 0
        self.use_table_view = (
            False  # Switches based on the format type of the loaded Document
        )
        self.edit_path = {
            "layer": None,
            "stratobj": 0,
            "obj": 0,
            "goal": 0,
            "metric": 0,
        }

        # Initiate the MID manager if settings are already set
        mid_path = self.settings.get("MIDLocation", "")
        if mid_path:
            try:
                self.mid_manager = MIDManager(mid_path)
                # After loading MID DataFrame
                for col, default in [
                    ("classification_scheme", ""),  # Scheme name per row
                    ("metric_status", ""),  # radio selection per metric row
                    ("target", ""),  # Listed goal field
                    ("actual", ""),  # Lister performance field
                    ("years_to_evaluation", ""),  # str or int for eval point
                    ("_flag", False),  # flag for review
                    ("_no_metrics", False),  # marks a goal saved without metrics
                    ("_gen", False),
                    ("_achieved", False),
                    ("_future_dated", False),
                    ("Page", ""),
                    ("_aggregate", False),  # Indicator for aggregate goals
                    ("reviewer_comments", ""),  # Notes field for reviewer mode
                    ("reviewer_status", ""),  # Accept/Reject/Seen status
                ]:
                    if col not in self.mid_manager.df.columns:
                        self.mid_manager.df[col] = default
                # Ensure helper columns exist

            except Exception as e:
                self.logger.error(f"Failed to Load MID: {e}")
        else:
            self.logger.warning("MID Location not specified, user alerted")
            # Notfiy the user via popup if the MID cannot be loaded
            # NOTE: This still executes at first launch, which is proabably bad form
            QMessageBox.warning(
                self,
                "MID Location not Specified",
                "Please select a Master Input Document in Settings.",
            )

        # We keep separate lists of widgets for each mode so they can be dynamically loaded and unloaded
        # Any widget not assigned to a mode will always be shown
        # Widgets assigned to a mode will be shown in that mode, and hidden in others
        self.dev_mode_widgets = []  # Superset of user mode, distinct from reviewer
        self.user_mode_widgets = []  # Base mode, minimum useful functionality
        self.reviewer_mode_widgets = []  # Superset of user mode, with added review functionality

        self.doc = None  # Current page
        self.page_indices = []  # List of all zero-indexed pages recorded in the MID
        self.current_page_index = 0  # Index of current page, not page number
        self.current_agency_yr = None  # Agency-year field
        self.scraped_text = ""  # Text to display in RH column
        self.page_text_cache = []  # List of strings, each containing the text of a page

        self.info_labels = {}  # Dictionary of info to display in UI
        self.manual_review = {  # Structure for tracking user Accept/Rejects (will likely be changed)
            "active_test": None,
            "results": {},  # format: {row_index: {"status": "ACCEPT" or "REJECT", "label": ..., "pages": [...]}}
        }
        self.mid_field_editors = {}  # {key: QTextEdit}
        self.mid_field_keys = ["stratobj", "obj", "goal", "metric"]

        self.add_level_buttons = {}
        self.expansion_state = {
            "base_level": None,  # lowest present on the seed row (stratobj|obj|goal|metric|None)
            "working_level": None,  # where the user is currently adding units
            "seed_index": None,  # index of the original (non-generated) row we started from
        }

        # overlays + coords from the most recent scrape
        self.page_overlays = {}  # {page_index: PNG bytes}
        self.cells_by_page = {}  # {page_index: [(x0,y0,x1,y1), ...]} (for later click-to-scrape)
        self.page_dims = {}  # {page_index: (w_pt, h_pt)}         (for later)

        # Set up file structure if it doesn't exist
        self.init_files()

        self.init_ui()

        # Attempt to load the first document
        if hasattr(self, "mid_manager") and self.mid_manager.df is not None:
            success = self.load_mid_entry_document()
            if not success:
                self.logger.warning(
                    "First MID row failed to load; check file accessibility or page numbers."
                )
            else:
                self.logger.debug("First MID row loaded successfully")


   
    # Create Necessary File Structure
    def init_files(self):
        # Check if the "./data" directory exists; if not, create it
        data_dir = self.settings.get("dataDirectory", "")
        self.accept_dir = os.path.join(data_dir, "accepted")
        self.formatted_dir = os.path.join(self.accept_dir, "formatted")
        self.reject_dir = os.path.join(data_dir, "rejected")
        if data_dir and not os.path.exists(data_dir):
            self.logger.warning("./data does not exist! attempting to create directory")
            try:
                os.makedirs(data_dir)
                self.logger.info("Created ./data directory for input files")
            except Exception as e:
                self.logger.error("Failed to Create ./data! Files will not be loaded!")
                QMessageBox.critical(
                    self, "Error", f"Failed to create data directory:\n{e}"
                )
                return

        # Stage 1 accepted directory
        if not os.path.exists(self.accept_dir):
            self.logger.info("./data/accepted does not exist, creating")
            try:
                os.makedirs(self.accept_dir)
            except Exception as e:
                self.logger.error("Failed to Create ./data/accepted!")

        # Stage 2 accepted directory
        if not os.path.exists(self.formatted_dir):
            try:
                os.makedirs(self.formatted_dir)
            except Exception as e:
                self.logger.error("Failed to Create ./data/accepted/formatted!")

        # Stage 1 rejected directory
        if not os.path.exists(self.reject_dir):
            self.logger.info("./data/rejected does not exist, creating")
            try:
                os.makedirs(self.reject_dir)
            except Exception as e:
                self.logger.error("Failed to Create ./data/rejected!")

        # TODO: Consolodate this and other file management functions into a utils library

   
    # Actual document loading based on MID entry
    def load_mid_entry_document(self):
        row = self.mid_manager.get_current_row()
        if row is None:
            self.logger.error("No MID row found")
            return False

        # Extract necessary information from the row
        agency = row.get("agency", "UNKNOWN").strip()
        year = str(row.get("year", "UNKNOWN")).strip()
        agency_yr = row.get("agency_yr", "").strip()
        focus_page = row.get("Page", None)

        if hasattr(self, "current_agency_yr") and self.current_agency_yr != agency_yr:
            self.current_page_index = 0

        label = f"{agency} ({year})"

        if not agency_yr:
            self.logger.error(f"MID row missing 'agency_yr' for {label}")
            return False

        self.current_agency_yr = agency_yr

        # Load the file
        # Handle any hyphen-underscore mixups
        filename = f"{agency_yr.replace('-', '_')}.pdf"
        path = os.path.join(self.settings.get("dataDirectory", ""), filename)

        if not os.path.isfile(path):
            self.logger.error(
                f"PDF not found for MID row {label} - expected file: {filename}"
            )
            return False
        try:
            self.doc = fitz.open(path)
            self.page_indices = self.mid_manager.parse_pdf_pages()

            if not self.page_indices:
                self.logger.error(
                    f"No valid pages found for {label} - PDF Page number field: '{row.get('PDF Page Number', '')}' "
                )
                return False

            self.page_text_cache = [""] * len(self.page_indices)

            if focus_page is not None:
                try:
                    page_number = int(focus_page)
                    if page_number > 0 and page_number < max(self.page_indices) + 2:
                        self.current_page_index = self.page_indices.index(
                            page_number - 1
                        )
                        self.logger.info(
                            f"Set current page index to {self.current_page_index} based on MID Page field"
                        )
                except ValueError:
                    self.logger.warning(
                        f"Invalid Page field in MID for {label}: '{focus_page}'"
                    )
                    self.current_page_index = 0

            try:
                format_type = int(row.get("Format_Type_Updated", -1))
                ScraperClass = select_scraper_class(self.settings, format_type)
                pages = [self.doc.load_page(p) for p in self.page_indices]
                Scraper = ScraperClass(pages)
                Scraper.scrape()
                result = Scraper.result
                self.logger.info("got scraper result!")
                self.current_scrape_result = result or {}

                # Image viewer
                if str(result.get("format", "")).lower() == "image":
                    self.logger.debug("using image format")
                    result_pages = result.get("result", []) or []
                    self._page_table_images = []
                    for local_idx, _pdf_idx in enumerate(self.page_indices):
                        self.logger.debug("iter page")
                        tables = (
                            result_pages[local_idx]
                            if local_idx < len(result_pages)
                            else []
                        )
                        pil_img = tables[0].get("table_image") if tables else None
                        self._page_table_images.append(pil_img)

                    img = self._page_table_images[self.current_page_index]
                    self.logger.debug("got image")
                    qpix = self._pil_to_qpixmap(img) if img is not None else None
                    self.logger.debug("converted to qpixmap")
                    if qpix is not None:
                        self.image_canvas.set_image(
                            qpix,
                            meta={"page": self.current_page_index, "table": 0},
                            fit=True,
                        )
                        self.image_canvas.show()
                        # if hasattr(self, "text_edit"): self.text_edit.hide()
                        self.logger.debug("displayed")
                    # #switch to HTML viewer
                    # self.use_table_view = True
                    # self.text_edit.setVisible(False)
                    self.image_canvas.setVisible(True)
                    text_result = []

                # Default to text viewer
                else:
                    text_result = result.get("text")
                    self.page_text_cache = text_result
                    self.text_edit.setPlainText(
                        self.page_text_cache[self.current_page_index]
                    )

                    self.logger.debug("showing text editor")
                    self.image_canvas.setVisible(False)
                    self.image_canvas.hide()
                    self.text_edit.setVisible(True)
                    self.text_edit.show()

                if not isinstance(text_result, list):
                    raise ValueError("Expected a list of strings from the Scraper!")

            except Exception as e:
                self.logger.error(f"Failed to scrape all pages for {label}: {e}")

            # Decide which right-hand widget to show
            is_image = (
                str(self.current_scrape_result.get("format", "")).lower() == "image"
            )
            self.use_table_view = is_image or (
                self.use_table_view
            )  # image implies table_view

            self.show_page()
            self.load_mid_fields_from_row()
            self.highlight_sidebar_matches()
            return True

        except Exception as e:
            self.logger.error(f"Error loading {filename} for {label}: {e}")
            return False

    # This and reject both cover different use cases depending on the mode
    def accept_scrape(self):
        if self.mode == "dev":
            if self.manual_review["active_test"]:
                idx = self.mid_manager.current_index
                row = self.mid_manager.get_current_row()
                pages = (
                    [self.page_indices[self.current_page_index]]
                    if self.page_indices
                    else []
                )
                self.manual_review["results"][idx] = {
                    "status": "ACCEPT",
                    "label": row.get("agency_yr", f"Index {idx}"),
                    "pages": pages,
                }
                self.logger.info(f"Manually accepted row {idx}")
            # User is not reviewing a test
            else:
                QMessageBox.warning(
                    self,
                    "Accept",
                    "No active test! Switch to user mode to review scraping results or select a test",
                )
        elif self.mode.lower() == "reviewer":
            mm = getattr(self, "mid_manager", None)
            if mm is not None:
                idx = mm.current_index
                row = mm.get_current_row()
                agency_yr = row.get("agency_yr", f"Index {idx}")
                notes = self.reviewer_notes.text().strip()
                review_record = {"status": "ACCEPT", "label": agency_yr, "notes": notes}
                self.logger.info(
                    f"Reviewer accepted row {idx} ({agency_yr}) with notes: {notes}"
                )
                self.mid_manager.set_value(idx, "reviewer_status", "ACCEPT")
                # Here you would typically save the review_record to a database or file.

        # User is in User mode
        else:
            if self.doc:
                agency_yr = self.current_agency_yr.replace("-", "_")
                output_path = os.path.join(self.accept_dir, f"{agency_yr}_full.txt")
                full_text = "\n\n".join(self.page_text_cache)
                with open(output_path, "w", encoding="utf-8") as f:
                    # use the contents of the text edit window in case the user made manual edits
                    f.write(full_text)
                self.logger.info(f"Saved accepted scrape to {output_path}")

        # Outside conditional
        self._commit_sidebar_fields()
        self.next_mid_entry()

    def reject_scrape(self):
        if self.mode == "dev":
            if self.manual_review["active_test"]:
                idx = self.mid_manager.current_index
                row = self.mid_manager.get_current_row()
                pages = (
                    [self.page_indices[self.current_page_index]]
                    if self.page_indices
                    else []
                )
                self.manual_review["results"][idx] = {
                    "status": "REJECT",
                    "label": row.get("agency_yr", f"Index {idx}"),
                    "pages": pages,
                }
                self.logger.info(f"Manually rejected row {idx}")
                self.next_mid_entry()
            else:
                QMessageBox.warning(
                    self,
                    "Reject",
                    "No active test! Switch to user mode to review scraping results or select a test",
                )
        elif self.mode.lower() == "reviewer":
            mm = getattr(self, "mid_manager", None)
            if mm is not None:
                idx = mm.current_index
                row = mm.get_current_row()
                agency_yr = row.get("agency_yr", f"Index {idx}")
                notes = self.reviewer_notes.text().strip()
                review_record = {"status": "REJECT", "label": agency_yr, "notes": notes}
                self.chk_flag.setChecked(True)
                self.logger.info(
                    f"Reviewer rejected row {idx} ({agency_yr}) with notes: {notes}"
                )
                # Here you would typically save the review_record to a database or file.
                self.mid_manager.set_value(idx, "reviewer_status", "REJECT")
            self.next_mid_entry()
        # User Mode:
        else:
            if self.doc:
                agency_yr = self.current_agency_yr.replace("-", "_")
                output_path = os.path.join(self.reject_dir, f"{agency_yr}_full.txt")
                full_text = "\n\n".join(self.page_text_cache)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(full_text)
                self.logger.info(f"Saved rejected scrape to {output_path}")

    # Move to the next entry without any output
    def next_mid_entry(self):
        self._commit_sidebar_fields()
        self.advance_to_valid_entry(direction="next")
        # self.scrape_page()

    # Move to previous entry without any output
    def prev_mid_entry(self):
        self._commit_sidebar_fields()
        self.advance_to_valid_entry(direction="prev")
        # self.scrape_page()

    # Move to specified MID entry
    def select_mid_entry(self):
        self._commit_sidebar_fields()
        num, ok = QInputDialog.getInt(
            self,
            "Jump to MID Entry",
            "num",
            min=1,
            max=len(self.mid_manager.df),
            step=1,
        )
        if not ok:
            return
        if num < 1 or num > len(self.mid_manager.df):
            QMessageBox.warning("Out of range!")
            return
        self.mid_manager.select_mid_entry(num - 1)
        self.load_mid_entry_document()
        self.update_info_labels()
        self.show_page()
        # self.scrape_page()

    # Delete the current entry and move to the next
    def delete_mid_entry(self):
        row = self.mid_manager.get_current_row()
        if row is None:
            self.logger.error("No MID row selected to delete.")
            return

        confirmation = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete the current MID entry?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if confirmation == QMessageBox.Yes:
            try:
                self.mid_manager.delete_current_row()
                self.logger.info(
                    f"MID entry {self.current_mid_index} deleted successfully."
                )
                self.load_mid_entry_document()
                self.update_info_labels()
                self.show_page()
            except Exception as e:
                self.logger.error(
                    f"Failed to delete MID entry {self.current_mid_index}: {e}"
                )

    def duplicate_prior_year(self):
        row = self.mid_manager.get_current_row()
        self.mid_manager.duplicate_prior_year()
        self.update_info_labels()

    # Handle any missing entries or pages that can't be loaded
    def advance_to_valid_entry(self, direction="next"):
        while True:
            if direction == "next":
                self.mid_manager.next_mid_entry()
            elif direction == "prev":
                self.mid_manager.prev_mid_entry()

            if self.mid_manager.get_current_row() is None:
                self.logger.warning(
                    "Reached end of MID entries with no valid document found"
                )
                QMessageBox.warning(
                    self, "No More Entries", "No further valid documents were found"
                )
                break

            row = self.mid_manager.get_current_row()
            format_type = int(row.get("Format_Type_Updated", -1))
            # if(format_type not in [19, 20, 21, 22, 23]):
            #    continue
            success = self.load_mid_entry_document()
            if success:
                self.update_info_labels()
                break
            else:
                current_index = self.mid_manager.current_index
                self.logger.warning(
                    f"Skipping invalid MID entry at index {current_index}"
                )

    # Creates an instance of SettingsWindow for user to update settings
    def open_settings(self):
        self.logger.debug("Attempting to open Settings")

        # Save the old MID path in case the user enters an invalid path
        old_mid_path = self.settings.get("MIDLocation", "")
        if hasattr(self, "mid_manager"):
            old_mid_df = self.mid_manager.df
        else:
            old_mid_df = None

        dialog = SettingsDialog(self.settings, self)

        # Save new settings from user's inputs
        if dialog.exec_() == QDialog.Accepted:
            self.logger.info("User updated settings in-app")
            self.settings = dialog.settings
            self._refresh_class_schemes_from_settings()
            save_settings(self.settings)
            self.mode = self.settings.get("userMode", "User")
            self.update_mode_ui()

            new_mid_path = self.settings.get("MIDLocation", "")
            new_sheet_name = self.settings.get("MIDSheetName", 0)

            old_mid_path = old_mid_path or ""
            old_sheet_name = self.settings.get(
                "MIDSheetName", 0
            )  # NOTE: see below for better old capture
            # Better: capture old_sheet_name BEFORE dialog (recommended), see next snippet.

            if not new_mid_path:
                QMessageBox.critical(
                    self, "Missing MID", "You must select a MID to use the app!"
                )
                self.logger.error("User did not select a MID")
                return

            # Determine whether the MID source changed (path or sheet)
            mid_changed = (new_mid_path != old_mid_path) or (
                str(new_sheet_name) != str(old_sheet_name)
            )

            if mid_changed:
                self.logger.info("MID location/sheet changed; reloading MID")

                try:
                    # Reconstruct only when necessary
                    self.mid_manager = MIDManager(
                        new_mid_path, sheet_name=new_sheet_name
                    )

                    QMessageBox.information(
                        self,
                        "MID Reloaded",
                        "Master Input Document Loaded Successfully",
                    )

                    summary = (
                        f"MID loaded successfully.\n\n"
                        f"Rows: {len(self.mid_manager.df):,}\n"
                        f"Columns: {len(self.mid_manager.df.columns)}\n"
                        f"Agencies: {self.mid_manager.df['agency'].nunique()}\n"
                        f"Years: {self.mid_manager.df['year'].nunique()}\n"
                        f"\nSample rows:\n{self.mid_manager.df[['agency', 'year', 'goal']].head().to_string(index=False)}"
                    )
                    self.logger.info(summary)
                    QMessageBox.information(self, "MID Summary", summary)

                except Exception as e:
                    # Restore prior MID state
                    if old_mid_df is not None:
                        self.mid_manager.df = old_mid_df
                    self.logger.critical(f"Error Loading MID: {e}")
                    self.logger.warning("Previous MID State Recovered")
                    QMessageBox.critical(
                        self,
                        "Error Loading MID",
                        f"Previous MID state restored.\n\n{str(e)}",
                    )
            else:
                # MID unchanged; do NOT reconstruct MIDManager (preserves current_index)
                self.logger.debug(
                    "MID unchanged; preserving current MIDManager/current_index"
                )

    # runs the suite of MID audit functions defined in audit_runner.py
    def run_mid_audit(self):
        self.logger.info("Starting MID Audit")
        try:
            output_path = run_mid_audit(self.mid_manager, self.settings)
            QMessageBox.information(
                self,
                "Audit Complete",
                f"Audit Complete! Output saved to:\n{output_path}",
            )
        except Exception as e:
            self.logger.critical(f"AUDIT FAILED: {e}")
            QMessageBox.critical(self, "Audit Error", str(e))

    # basic handler for the fialure loading function below
    def handle_load_failures(self):
        if self.mode.lower() == "dev":
            test_name = self.failure_test_combo.currentText()
            self.load_audit_failures(test_name)
        elif self.mode.lower() == "reviewer":
            test_name = self.failure_test_combo.currentText()
            self.restrict_for_reviewer(test_name)

    def load_audit_failures(self, test_name="text_scraped"):
        """
        Dev-mode restriction helper.

        Special values for test_name:
          - "_flag"     : rows where _flag == True
          - "_gen"      : rows where _gen == True
          - "no_status" : rows where metric_status is blank/empty
          - "no_t/a"    : rows where BOTH target and actual are blank/empty
          - "none"      : clear restriction (reload MID fresh from disk)

        Otherwise, test_name is treated as an audit_report.json test key and we restrict
        to rows where that test == "FAIL".
        """
        try:
            if (
                not hasattr(self, "mid_manager")
                or self.mid_manager.df is None
                or self.mid_manager.df.empty
            ):
                QMessageBox.information(self, "No MID", "No MID is currently loaded.")
                return

            # --- Clear restriction: reload MID from disk (since MIDManager has no clear_restriction()) ---
            if test_name == "none":
                self.mid_manager.clear_restriction()
                self.logger.info("Cleared reviewer restrictions; full MID restored")
                self.load_mid_entry_document()
                return

            df = self.mid_manager.df

            # -------------------------
            # Special “column-based” restrictions
            # -------------------------
            special = {"_flag", "_gen", "no_status", "no_t/a", "rejected"}
            if test_name in special:
                # Ensure helper columns exist with sane defaults
                if test_name == "_gen":
                    try:
                        self.mid_manager.ensure_gen_flag()
                    except Exception:
                        if "_gen" not in df.columns:
                            df["_gen"] = False

                if test_name == "_flag":
                    if "_flag" not in df.columns:
                        df["_flag"] = False

                if test_name == "no_status":
                    if "metric_status" not in df.columns:
                        df["metric_status"] = ""

                if test_name == "no_t/a":
                    # Create if missing (some sheets won’t have these yet)
                    if "target" not in df.columns:
                        df["target"] = ""
                    if "actual" not in df.columns:
                        df["actual"] = ""

                # Build mask per condition
                if test_name in {"_flag", "_gen"}:
                    # Normalize to boolean if it arrived as strings
                    col = test_name
                    if df[col].dtype != bool:
                        df[col] = (
                            df[col]
                            .astype(str)
                            .str.strip()
                            .str.lower()
                            .isin(["true", "1", "yes", "y"])
                        )
                    mask = df[col] == True

                elif test_name == "no_status":
                    mask = df["metric_status"].fillna("").astype(str).str.strip().eq("")

                elif test_name == "rejected":
                    mask = df["reviewer_status "].fillna(
                        "".astype(str).str.strip().eq("REJECT")
                    )

                else:  # "no_t/a"
                    t_blank = df["target"].fillna("").astype(str).str.strip().eq("")
                    a_blank = df["actual"].fillna("").astype(str).str.strip().eq("")
                    mask = t_blank & a_blank

                # IMPORTANT: restrict_to_rows uses iloc, so pass 0-based positional indices
                matching_positions = df.index[mask].tolist()

                if not matching_positions:
                    QMessageBox.information(
                        self, "No Matches", f"No rows matched restriction: {test_name}"
                    )
                    return

                self.mid_manager.restrict_to_rows(matching_positions)
                self.logger.info(
                    f"Restriction applied: {len(matching_positions)} rows matched '{test_name}'"
                )

                # Reset manual review state (optional, but matches your dev-mode review flow)
                self.manual_review["active_test"] = test_name
                self.manual_review["results"] = {}

                self.load_mid_entry_document()
                return

            # -------------------------
            # Default: restrict to audit FAIL rows for a given test
            # -------------------------
            log_path = os.path.join(
                self.settings.get("logFileDirectory", "./logs"), "audit_report.json"
            )
            with open(log_path, "r", encoding="utf-8") as f:
                audit_results = json.load(f)

            # audit_runner writes entry["index"] = i+1 (1-based),
            # but MIDManager.restrict_to_rows expects 0-based iloc positions.
            failed_positions = [
                int(entry["index"]) - 1
                for entry in audit_results
                if entry.get("tests", {}).get(test_name) == "FAIL"
                and str(entry.get("index", "")).isdigit()
            ]

            if not failed_positions:
                QMessageBox.information(
                    self, "No Failures", f"No failures found for test: {test_name}"
                )
                return

            self.mid_manager.restrict_to_rows(failed_positions)
            self.logger.info(
                f"Loaded {len(failed_positions)} failure rows for test '{test_name}' into MID view"
            )

            self.manual_review["active_test"] = test_name
            self.manual_review["results"] = {}
            self.logger.info(f"Manual review mode enabled for test '{test_name}'")

            self.load_mid_entry_document()

        except Exception as e:
            self.logger.error(f"Failed to restrict MID (test_name={test_name}): {e}")
            QMessageBox.critical(self, "Error", f"Could not restrict MID:\n{e}")

    def restrict_for_reviewer(self, test_name: str = "none"):
        """
        Restrict the MID view to rows where df[condition] is True.
        Intended for Reviewer mode. Valid conditions: "_flag", "_gen".
        """
        try:
            if (
                not hasattr(self, "mid_manager")
                or self.mid_manager.df is None
                or self.mid_manager.df.empty
            ):
                QMessageBox.information(self, "No MID", "No MID is currently loaded.")
                return

            # --- Clear restriction: reload MID from disk (since MIDManager has no clear_restriction()) ---
            if test_name == "none":
                self.mid_manager.clear_restriction()
                self.logger.info("Cleared reviewer restrictions; full MID restored")
                self.load_mid_entry_document()
                return

            df = self.mid_manager.df

            # -------------------------
            # Special “column-based” restrictions
            # -------------------------
            special = {"_flag", "_gen", "no_status", "no_t/a", "rejected"}
            if test_name in special:
                # Ensure helper columns exist with sane defaults
                if test_name == "_gen":
                    try:
                        self.mid_manager.ensure_gen_flag()
                    except Exception:
                        if "_gen" not in df.columns:
                            df["_gen"] = False

                if test_name == "_flag":
                    if "_flag" not in df.columns:
                        df["_flag"] = False

                if test_name == "no_status":
                    if "metric_status" not in df.columns:
                        df["metric_status"] = ""

                if test_name == "no_t/a":
                    # Create if missing (some sheets won’t have these yet)
                    if "target" not in df.columns:
                        df["target"] = ""
                    if "actual" not in df.columns:
                        df["actual"] = ""

                # Build mask per condition
                if test_name in {"_flag", "_gen"}:
                    # Normalize to boolean if it arrived as strings
                    col = test_name
                    if df[col].dtype != bool:
                        df[col] = (
                            df[col]
                            .astype(str)
                            .str.strip()
                            .str.lower()
                            .isin(["true", "1", "yes", "y"])
                        )
                    mask = df[col] == True

                elif test_name == "no_status":
                    mask = df["metric_status"].fillna("").astype(str).str.strip().eq("")

                elif test_name == "rejected":
                    mask = (
                        df["reviewer_status"]
                        .fillna("")
                        .astype(str)
                        .str.strip()
                        .eq("REJECT")
                    )

                elif test_name == "no_t/a":  # "no_t/a"
                    t_blank = df["target"].fillna("").astype(str).str.strip().eq("")
                    a_blank = df["actual"].fillna("").astype(str).str.strip().eq("")
                    mask = t_blank & a_blank

                # IMPORTANT: restrict_to_rows uses iloc, so pass 0-based positional indices
                matching_positions = df.index[mask].tolist()

                if not matching_positions:
                    QMessageBox.information(
                        self, "No Matches", f"No rows matched restriction: {test_name}"
                    )
                    return

                self.mid_manager.restrict_to_rows(matching_positions)
                self.logger.info(
                    f"Restriction applied: {len(matching_positions)} rows matched '{test_name}'"
                )

            # Reset review state if you want reviewer mode to behave like the dev-mode review flow
            self.manual_review["active_test"] = test_name
            self.manual_review["results"] = {}

            # Load first row/document in the restricted MID
            self.load_mid_entry_document()

        except Exception as e:
            self.logger.error(
                f"Failed to restrict MID for reviewer (condition={test_name}): {e}"
            )
            QMessageBox.critical(
                self, "Error", f"Could not restrict MID for reviewer:\n{e}"
            )

    # Save manual reveiw results to JSON (Dev mode only)
    def export_review_results(self):
        if not self.manual_review["active_test"]:
            QMessageBox.information(
                self,
                "Not in Review Mode",
                "You must be in manual review mode to export results.",
            )
            return

        try:
            filename = f"{self.manual_review['active_test']}_review.json"
            output_path = os.path.join(
                self.settings.get("logFileDirectory", "./logs"), filename
            )
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(self.manual_review["results"], f, indent=2)

            self.logger.info(f"Manual review results saved to {output_path}")
            QMessageBox.information(
                self, "Export Complete", f"Review results saved to:\n{output_path}"
            )
        except Exception as e:
            self.logger.error(f"Failed to export review results: {e}")
            QMessageBox.critical(self, "Export Error", str(e))

    def save_mid_to_file(self):
        # Commit current editors first
        self._commit_sidebar_fields()

        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            QMessageBox.warning(self, "Save MID", "No MID loaded.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save MID", "mid_export.xlsx", "Excel Workbook (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return

        df_to_save = getattr(self.mid_manager, "master_df", None)
        if df_to_save is None:
            df_to_save = self.mid_manager.df
        # then write df_to_save to Excel

        try:
            if path.lower().endswith(".csv"):
                df_to_save.to_csv(path, index=False)
            else:
                # default to Excel
                with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
                    df_to_save.to_excel(xw, index=False, sheet_name="MID")
            self.statusBar().showMessage(f"Saved MID to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save MID", f"Failed to save:\n{e}")

    # Primary function for saving current editor state into the MID
    def _commit_sidebar_fields(self):
        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            return
        idx = self.mid_manager.current_index  # set_value includes a view->master conversion, so we pass the view index here
        if idx is None:
            return
        for k, ed in self.mid_field_editors.items():
            self.mid_manager.set_value(idx, k, ed.toPlainText().strip())
        self.mid_manager.set_value(idx, "_flag", self.chk_flag.isChecked())
        self.logger.info(f"saved flag status: {self.mid_manager.df.at[idx, '_flag']}")
        self.mid_manager.set_value(idx, "_achieved", self.chk_achieved.isChecked())
        self.mid_manager.set_value(
            idx, "_future_dated", self.chk_future_dated.isChecked()
        )
        self.mid_manager.set_value(idx, "_aggregate", self.chk_aggregate.isChecked())
        self.logger.info(f"Saved information for {self.current_agency_yr}: ")
        # metric status and scheme
        scheme = self._safe_text(self.class_scheme_combo.currentText()).strip()
        self.mid_manager.set_value(idx, "classification_scheme", scheme)
        self.mid_manager.set_value(
            idx, "metric_status", self._safe_text(self._get_metric_status())
        )
        self.mid_manager.set_value(
            idx, "target", self._safe_text(self.target_edit.text()).strip()
        )
        self.mid_manager.set_value(
            idx, "actual", self._safe_text(self.actual_edit.text()).strip()
        )
        self.mid_manager.set_value(
            idx, "notes", self._safe_text(self.notes.text()).strip()
        )
        self.mid_manager.set_value(
            idx,
            "Page",
            self.page_indices[self.current_page_index] + 1
            if self.page_indices
            else self.current_page_index + 1,
        )
        if self.mode.lower() == "reviewer":
            self.mid_manager.set_value(
                idx,
                "reviewer_comments",
                self._safe_text(self.reviewer_notes.text()).strip(),
            )
            if self.mid_manager.df.at[idx, "reviewer_status"] not in [
                "ACCEPT",
                "REJECT",
            ]:
                self.mid_manager.set_value(idx, "reviewer_status", "SEEN")

        yrs = self.years_to_eval_spin.value()
        if self.chk_future_dated.isChecked() and yrs > 0:
            self.mid_manager.set_value(idx, "years_to_evaluation", str(yrs))
        else:
            self.mid_manager.set_value(idx, "years_to_evaluation", "")

    def _clear_field(self, key: str):
        ed = self.mid_field_editors.get(key)
        if ed:
            ed.clear()

    def _goto_index(self, new_idx: int):
        """Your existing navigation method; ensure it sets current_index then calls update_info_labels/show_page/etc."""
        self.mid_manager.current_index = new_idx
        self.update_info_labels()
        self.load_mid_fields_from_row()
        # show_page() etc. if needed

    

    def _setup_shortcuts(self):
        self._shortcuts = []

        def bind(seq, fn):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)

        # -------------------------
        # Radio buttons: Ctrl+1-9
        # -------------------------
        for i in range(9):
            bind(f"Ctrl+{i + 1}", lambda i=i: self._select_metric_status_by_index(i))

        # Clear radio selection
        bind("0", self._clear_metric_status)

        # -------------------------
        # Navigation
        # -------------------------
        bind("-", self.prev_page)
        bind("=", self.next_page)

        # Enter → next MID entry
        bind("Ctrl+Return", self.next_mid_entry)
        bind("Ctrl+Enter", self.next_mid_entry)  # keypad Enter

        # -------------------------
        # Text transfer
        # -------------------------
        bind("1", lambda: self._fill_mid_field_from_selection("stratobj"))
        bind("2", lambda: self._fill_mid_field_from_selection("obj"))
        bind("3", lambda: self._fill_mid_field_from_selection("goal"))
        bind("4", lambda: self._fill_mid_field_from_selection("metric"))

        bind("[", lambda: self._fill_lineedit_from_selection("target"))
        bind("]", lambda: self._fill_lineedit_from_selection("actual"))

        # -------------------------
        # '+' buttons
        # -------------------------
        bind("F1", lambda: self._trigger_add_level("stratobj"))
        bind("F2", lambda: self._trigger_add_level("obj"))
        bind("F3", lambda: self._trigger_add_level("goal"))
        bind("F4", lambda: self._trigger_add_level("metric"))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            mods = event.modifiers()

            # Only swallow the *unmodified* single-key shortcuts
            if mods in (Qt.NoModifier,):
                # digits 0–4
                if key in (Qt.Key_0, Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4):
                    return True

                # [, ], -, =
                if key in (
                    Qt.Key_BracketLeft,
                    Qt.Key_BracketRight,
                    Qt.Key_Minus,
                    Qt.Key_Equal,
                ):
                    return True

            # function keys are fine to pass through (no text insertion anyway)
            # Enter/Return you may also want to swallow if it’s your “next MID entry”
            if key in (Qt.Key_Return, Qt.Key_Enter):
                return True

        return super().eventFilter(obj, event)

    def _scheme_labels(self) -> list[str]:
        """
        Current radio labels in display order from current scheme set).
        """
        btns = getattr(self, "metric_status_buttons", {}) or {}
        return [str(k) for k in btns.keys()]

    def _extract_and_apply_status_label(self, snippet: str) -> str:
        """
        If snippet contains a classification label, select that radio and remove the label text
        from the snippet. Returns cleaned snippet.
        """
        labels = self._scheme_labels()
        if not labels:
            return snippet

        # Prefer longer labels first (handles labels like "Not Met" vs "Met")
        labels_sorted = sorted(labels, key=len, reverse=True)

        s = snippet

        # Normalize whitespace for matching without losing the user's original
        s_norm = re.sub(r"\s+", " ", s).strip()

        for label in labels_sorted:
            lab = label.strip()
            if not lab:
                continue

            # Match label as a standalone token (word boundary-ish), anywhere in string.
            # This works for multi-word labels.
            pattern = (
                r"(?<!\S)" + re.escape(lab) + r"(?!\S)"
            )  # surrounded by whitespace or ends
            m = re.search(pattern, s_norm)
            if not m:
                continue

            # Select the radio button
            rb = self.metric_status_buttons.get(label)
            if rb is not None:
                rb.setChecked(True)

            # Remove that occurrence of the label from the normalized string
            s_norm = (s_norm[: m.start()] + s_norm[m.end() :]).strip()

            # Stop after the first match
            break

        # Clean up dangling punctuation at the ends (common when labels are at end)
        s_norm = s_norm.strip(" \t\r\n-–—:;,.()[]{}")

        return s_norm

    

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TextScrapingReviewApp()
    window.show()
    sys.exit(app.exec_())
