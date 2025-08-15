import sys
import os
import fitz  # PyMuPDF
import json
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QLabel,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QDialog,
    QInputDialog,
    QComboBox,
    QTextBrowser
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage

# local imports

from settings_window import SettingsDialog
from app_settings import load_settings, save_settings
from mid_manager import MIDManager
from logger import setup_logger
from scraper_loader import select_scraper_class
from audit_runner import run_mid_audit


# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.dirname(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


class TextScrapingReviewApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = setup_logger()
        self.logger.info("Initialized Logger")
        self.setWindowTitle("Text Scraping Review App")
        self.resize(1200, 800)

        self.settings = load_settings()
        self.mode = self.settings.get("userMode", "User").lower()
        self.mid_df = None
        self.current_mid_index = 0
        self.use_table_view = False # Switches based on the format type of the loaded Document

        # Initiate the MID manager if settings are already set
        mid_path = self.settings.get("MIDLocation", "")
        if mid_path:
            try:
                self.mid_manager = MIDManager(mid_path)
                self.logger.info("Successfully loaded MID")
            except Exception as e:
                self.logger.error(f"Failed to Load MID: {e}")
        else:
            self.logger.warning("MID Location not specified, user alerted")
            # Notfiy the user via popup if the MID cannot be loaded
            # NOTE: This still executes at first launch, which is proabably bad form
            QMessageBox.warning(self, "MID Location not Specified", "Please select a Master Input Document in Settings.")


        self.dev_mode_widgets = []
        self.user_mode_widgets = []

        self.doc = None                 # Current page
        self.page_indices = []          # List of all zero-indexed pages recorded in the MID
        self.current_page_index = 0     # Index of current page, not page number
        self.current_agency_yr = None   # Agency-year field
        self.scraped_text = ""          # Text to display in RH column
        self.page_text_cache = []       # List of strings, each containing the text of a page

        self.info_labels = {}           # Dictionary of info to display in UI
        self.manual_review = {          # Structure for tracking user Accept/Rejects (will likely be changed)
            "active_test": None,
            "results": {},  # format: {row_index: {"status": "ACCEPT" or "REJECT", "label": ..., "pages": [...]}}
        }


        # Set up file structure if it doesn't exist
        self.init_files()

        self.init_ui()

        # Attempt to load the first document
        if hasattr(self, "mid_manager") and self.mid_manager.df is not None:
            success = self.load_mid_entry_document()
            if not success:
                self.logger.warning("First MID row failed to load; check file accessibility or page numbers.")
            else:
                self.logger.debug("First MID row loaded successfully")

        

    def init_ui(self):
        self.logger.debug(f"Initializing UI in {self.mode} mode")

        # Document Display Window
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # --- Status Information Panel ---
        info_layout = QVBoxLayout()

        self.entry_index_label = QLabel("Entry 0 of 0")
        self.entry_index_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.entry_index_label)


        # Set information fields
        if self.mode == "dev":
            self.info_fields = ["File", "Format"]

        else:
            # Information fields to display
            self.info_fields = ["File", "Agency", "Year", "Page", "Format"]


        # Dynamically create info fields based on assignment above
        for field in self.info_fields:
            label = QLabel(f"{field.capitalize()}: ")
            label.setStyleSheet("font-weight: bold;")
            info_layout.addWidget(label)
            self.info_labels[field.lower()] = label # set keys to lowercase version of field name



        # --- Control Panel ---
        control_layout = QVBoxLayout()
        load_btn = QPushButton("Load Document")
        load_btn.clicked.connect(self.load_document)
        control_layout.addWidget(load_btn)
        self.logger.debug("Added Load Document button")

        prev_btn = QPushButton("Previous Page")
        prev_btn.clicked.connect(self.prev_page)
        control_layout.addWidget(prev_btn)
        self.logger.debug("Added Previous Page button")

        next_btn = QPushButton("Next Page")
        next_btn.clicked.connect(self.next_page)
        control_layout.addWidget(next_btn)
        self.logger.debug("Added Next Page button")

        scrape_btn = QPushButton("Scrape Page")
        scrape_btn.clicked.connect(self.scrape_page)
        control_layout.addWidget(scrape_btn)
        self.logger.debug("Added Scrape Page button")

        accept_btn = QPushButton("Accept")
        accept_btn.clicked.connect(self.accept_scrape)
        control_layout.addWidget(accept_btn)
        self.logger.debug("Added Accept Scrape button")

        reject_btn = QPushButton("Reject")
        reject_btn.clicked.connect(self.reject_scrape)
        control_layout.addWidget(reject_btn)
        self.logger.debug("Added Reject Scrape button")

        next_entry_btn = QPushButton("Next MID Entry")
        next_entry_btn.clicked.connect(self.next_mid_entry)
        control_layout.addWidget(next_entry_btn)
        self.logger.debug("Added Next MID Entry button")

        prev_entry_btn = QPushButton("Previous MID Entry")
        prev_entry_btn.clicked.connect(self.prev_mid_entry)
        control_layout.addWidget(prev_entry_btn)
        self.logger.debug("Added Previous MID Entry button")

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings)
        control_layout.addWidget(settings_btn)
        self.logger.debug("Added Settings button")

        audit_btn = QPushButton("Run MID Audit")
        audit_btn.clicked.connect(self.run_mid_audit)
        control_layout.addWidget(audit_btn)
        self.dev_mode_widgets.append(audit_btn)
        self.logger.debug("Added Audit button")


        # Dev mode feature to review test failures, will need to dynamically load test names later
        # This field is the drop-down to select the test
        self.failure_test_combo = QComboBox()
        self.failure_test_combo.addItems([
            "table_detected", "text_scraped", "goal_match", "obj_match",
            "keyword_match", "stratobj_match", "pages_parsed", "pdf_found"
        ])
        failures_label = QLabel("Load Failures For Test:")
        control_layout.addWidget(failures_label)
        control_layout.addWidget(self.failure_test_combo)
        self.dev_mode_widgets.append(self.failure_test_combo)
        self.dev_mode_widgets.append(failures_label)

        # Restrict the MID entries to only those that failed the selected test
        load_failures_btn = QPushButton("Load Failures")
        load_failures_btn.clicked.connect(self.handle_load_failures)
        control_layout.addWidget(load_failures_btn)
        self.dev_mode_widgets.append(load_failures_btn)

        export_review_btn = QPushButton("Export Review Results")
        export_review_btn.clicked.connect(self.export_review_results)
        control_layout.addWidget(export_review_btn)
        self.dev_mode_widgets.append(export_review_btn)


        # Fill empty space
        control_layout.addStretch()
        side_panel = QVBoxLayout()
        side_panel.addLayout(info_layout)
        side_panel.addLayout(control_layout)
        main_layout.addLayout(side_panel, 1)
        self.logger.debug("Created Side Panel")

        # --- Viewer Panel ---
        splitter = QSplitter(Qt.Horizontal)
        # PDF Page Display
        self.pdf_label = QLabel("Load a document to begin.")
        self.pdf_label.setAlignment(Qt.AlignCenter)
        splitter.addWidget(self.pdf_label)

        # Scraped Text Display
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(False)  # Allow manual correction
        splitter.addWidget(self.text_edit)

        # Table structured display
        self.table_viewer = QTextBrowser()
        splitter.addWidget(self.table_viewer)
        self.table_viewer.hide()

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 4)

        # hide the dev mode labels if in user mode and v.v.
        self.update_mode_ui()

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
                QMessageBox.critical(self, "Error", f"Failed to create data directory:\n{e}")
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

    # Update read-only information for user
    def update_info_labels(self):
        self.logger.debug("Updating info labels")
        page_num = self.page_indices[self.current_page_index] + 1 if self.page_indices else self.current_page_index + 1
        row = None
        mid_length = len(self.mid_manager.df)
        row = self.mid_manager.get_current_row()
        current_mid_index = self.mid_manager.current_index

        # Display the current MID index and the total number of rows
        if row is not None:
            if hasattr(self, "entry_index_label"):
                self.entry_index_label.setText(
                    f"Entry {current_mid_index + 1:,} of {mid_length:,}"
                )
            current_format_type = row.get("Format_Type", "")

        # Map variables to their display lables manually if they are not the same
        for key, label in self.info_labels.items():
            if key == "page":
                value = page_num
            elif key == "file":
                value = self.current_agency_yr
            elif key == "format":
                value = current_format_type
            elif key in row:
                value = row[key]
            else:
                value = "N/A"
            label.setText(f"{key.capitalize()}: {value}")

    def update_mode_ui(self):
        is_dev = self.mode.lower() == "dev"
        self.logger.info("updating UI for dev mode") if is_dev else self.logger.info("updating UI for user mode")

        for widget in self.dev_mode_widgets:
            widget.setVisible(is_dev)

        for widget in self.user_mode_widgets:
            widget.setVisible(not is_dev)

    # For manual document loading - will likely be depricated
    def load_document(self):
        self.logger.debug("Attempting to load a document")
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if not path:
            return

        self.current_agency_yr = os.path.splitext(os.path.basename(path))[0]
        self.logger.info(f"Loading docuemnt for agency_yr: {self.current_agency_yr}")
        self.doc = fitz.open(path)
        self.current_page_index = 0

        self.show_page()

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
        label = f"{agency} ({year})"

        if not agency_yr:
            self.logger.error(f"MID row missing 'agency_yr' for {label}")
            return False

        self.current_agency_yr = agency_yr

        # Load the file
        # Handle any hyphen-underscore mixups
        filename = f"{agency_yr.replace('-','_')}.pdf"
        path = os.path.join(self.settings.get("dataDirectory", ""), filename)

        if not os.path.isfile(path):
            self.logger.error(f"PDF not found for MID row {label} - expected file: {filename}")
            return False
        try:
            self.doc = fitz.open(path)
            self.page_indices = self.mid_manager.parse_pdf_pages()

            if not self.page_indices:
                self.logger.error(f"No valid pages found for {label} - PDF Page number field: '{row.get('PDF Page Number', '')}' ")
                return False

            self.page_text_cache = [""] * len(self.page_indices)

            try:
                ScraperClass = select_scraper_class(self.settings, int(row.get("Format_Type", -1)))
                pages = [self.doc.load_page(p) for p in self.page_indices]
                Scraper = ScraperClass(pages)
                Scraper.scrape()
                result = Scraper.result
                
                text_result = result.get("text", [])
                if not isinstance(text_result, list):
                    raise ValueError("Expected a list of strings from the Scraper!")

                if len(text_result) != len(self.page_indices):
                    self.logger.warning(f"Scraper returned {len(text_result)} pages, expected {len(self.page_indices)}")

                self.page_text_cache = text_result
                self.logger.info(f"Scraped {len(self.page_text_cache)} pages from {label}")    

            except Exception as e:
                self.logger.error(f"Failed to scrape all pages for {label}: {e}")


            format_type = int(row.get("Format_Type", -1))
            self.use_table_view = format_type in [1,5,6,7,10,11,14,16,17,18]
            if self.use_table_view:
                self.text_edit.hide()
                self.table_viewer.show()
            else:
                self.table_viewer.hide()
                self.text_edit.show()

            # self.current_page_index = 0
            # # PyMuPDF is 0-indexed, add 1 to match user's expected range
            # display_pages = [p+1 for p in self.page_indices]
            # self.logger.info(f"Loaded {filename} for {label}, pages: {display_pages}")
            self.show_page()
            return True

        except Exception as e:
            self.logger.error(f"Error loading {filename} for {label}: {e}")
            return False


    def show_page(self):
        self.logger.debug("Attempting to display a new document page")
        if not self.doc:
            self.logger.warning("Could not load document!")
            return
        if self.page_indices:
            page_number = self.page_indices[self.current_page_index]
        else:
            self.logger.warning("No page reference found, defaulting to page 1!")
            page_number = self.current_page_index
        self.logger.debug(f"Attempting to load index {self.current_page_index}, page {page_number}")
        page = self.doc.load_page(page_number)

        # Render the page and upscale by 2x
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(img)
        self.pdf_label.setPixmap(
            pixmap.scaled(self.pdf_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

        text_content = self.page_text_cache[self.current_page_index]
        if self.use_table_view:
            self.table_viewer.setHtml(text_content)
        else:
            if 0 <= self.current_page_index < len(self.page_text_cache):
                self.text_edit.setPlainText(self.page_text_cache[self.current_page_index])
            else:
                self.text_edit.clear()




        # Display document information
        self.update_info_labels()

    # Simple UI update function when the window size is changed
    def resizeEvent(self, event):
        self.logger.debug("Window resized")
        super().resizeEvent(event)
        self.show_page()

    # Advances to next page and scrapes it
    def next_page(self):
        self.logger.debug("Attempting to load next page")
        if self.page_indices and self.current_page_index < len(self.page_indices) - 1:
            self.page_text_cache[self.current_page_index] = self.text_edit.toPlainText()
            self.logger.debug("Next page is valid")
            self.current_page_index += 1
            self.show_page()
        else:
            self.logger.warning("Attempted to load nonexistent page")

    # Moves to previous page and attempts to scrape it
    def prev_page(self):
        self.logger.debug("Attempting to load previous page")
        if self.page_indices and self.current_page_index > 0:
            self.page_text_cache[self.current_page_index] = self.text_edit.toPlainText()
            self.logger.debug("Previous page is valid")
            self.current_page_index -= 1
            self.show_page()
        else:
            self.logger.warning("Attempted to load nonexistent page")


    # Call the scraping tool engine and run the appropriate scraper on the current page only
    def scrape_page(self):
        self.logger.debug(f"Attempting to scrape page {self.current_page_index}")

        if not self.doc or self.mid_manager.df is None:
            self.logger.warning("Document or MID is missing!")
            QMessageBox.warning(self, "Error", "Document or MID is missing!")
            return
        
        row = self.mid_manager.get_current_row()
        format_type = int(row.get("Format_Type", -1))
        # actual_page_number adds the page index to the start page
        if self.page_indices:
            actual_page_number = self.page_indices[self.current_page_index]
        else:
            actual_page_number = self.current_page_index

        try:
            # For now, hardcode this to pull the basic text scraper
            # TODO: grab the user's scraper-doctype mappings for scraper selection
            ScraperClass = select_scraper_class(self.settings, format_type)


            # Extract the current page to scrape

            page = self.doc.load_page(actual_page_number)
            
            # Create a scraper instance for the page
            scraper = ScraperClass([page])
            scraper.scrape()
            result = scraper.result

            self.scraped_text = result.get("text", [""])
            self.text_edit.setPlainText(self.scraped_text[0])

            # Add 1, as actual_page_number is 0-indexed
            self.logger.debug(f"Scraped page {actual_page_number+1}")

        except Exception as e:
            self.logger.critical(f"failed to scrape page {actual_page_number+1}: {e}")
            QMessageBox.critical(self, "Scrape Error", str(e))


    def accept_scrape(self):
        if self.mode == "dev":
            if self.manual_review["active_test"]:
                idx = self.mid_manager.current_index
                row = self.mid_manager.get_current_row()
                pages = [self.page_indices[self.current_page_index]] if self.page_indices else []
                self.manual_review["results"][idx] = {
                    "status": "ACCEPT",
                    "label": row.get("agency_yr", f"Index {idx}"),
                    "pages": pages
                }
                self.logger.info(f"Manually accepted row {idx}")
            # User is not reviewing a test
            else:
                QMessageBox.warning(self, "Accept", "No active test! Switch to user mode to review scraping results or select a test")
        # User is in User mode
        else:
            if self.doc:
                agency_yr = self.current_agency_yr.replace("-","_")
                output_path = os.path.join(self.accept_dir, f"{agency_yr}_full.txt")
                full_text = "\n\n".join(self.page_text_cache)
                with open(output_path, "w", encoding = "utf-8") as f:
                    # use the contents of the text edit window in case the user made manual edits
                    f.write(full_text)
                self.logger.info(f"Saved accepted scrape to {output_path}")

        # Outside conditional
        self.next_mid_entry()


    def reject_scrape(self):
        if self.mode == "dev":
            if self.manual_review["active_test"]:
                idx = self.mid_manager.current_index
                row = self.mid_manager.get_current_row()
                pages = [self.page_indices[self.current_page_index]] if self.page_indices else []
                self.manual_review["results"][idx] = {
                    "status": "REJECT",
                    "label": row.get("agency_yr", f"Index {idx}"),
                    "pages": pages
                }
                self.logger.info(f"Manually rejected row {idx}")
                self.next_mid_entry()
            else:
                QMessageBox.warning(self, "Reject", "No active test! Switch to user mode to review scraping results or select a test")
        # User Mode:
        else:
            if self.doc:
                agency_yr = self.current_agency_yr.replace("-","_")
                output_path = os.path.join(self.reject_dir, f"{agency_yr}_full.txt")
                full_text = "\n\n".join(self.page_text_cache)
                with open(output_path, "w", encoding = "utf-8") as f:
                    f.write(full_text)
                self.logger.info(f"Saved rejected scrape to {output_path}")



    # Move to the next entry without any output
    def next_mid_entry(self):
        self.advance_to_valid_entry(direction="next")
        # self.scrape_page()

    # Move to previous entry without any output
    def prev_mid_entry(self):
        self.advance_to_valid_entry(direction="prev")
        # self.scrape_page()


    # Handle any missing entries or pages that can't be loaded
    def advance_to_valid_entry(self, direction="next"):
        while True:
            if direction == "next":
                self.mid_manager.next_mid_entry()
            elif direction == "prev":
                self.mid_manager.prev_mid_entry()

            if self.mid_manager.get_current_row() is None:
                self.logger.warning("Reached end of MID entries with no valid document found")
                QMessageBox.warning(self, "No More Entries", "No further valid documents were found")
                break

            success = self.load_mid_entry_document()
            if success:
                self.update_info_labels()
                break
            else:
                current_index = self.mid_manager.current_index
                self.logger.warning(f"Skipping invalid MID entry at index {current_index}")

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
            save_settings(self.settings)
            self.mode = self.settings.get("userMode", "User")
            self.update_mode_ui()

            new_mid_path = self.settings.get("MIDLocation", "")
            if new_mid_path is not None:
                self.mid_manager = MIDManager(new_mid_path)
            else:
                QMessageBox.error("You must select a MID to use the app!")
                self.logger.error("User did not select a MID")
                return
            if new_mid_path != old_mid_path or old_mid_path == "":
                self.logger.info("User updated MID location, attempting to read new data")
                try:
                    sheet_name = self.settings.get("MIDSheetName", 0)
                    self.mid_manager.df = self.mid_manager.load_mid(new_mid_path, sheet_name=sheet_name)
                    QMessageBox.information(self, "MID Reloaded", "Master Input Document Loaded Successfully")
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
                    self.mid_manager.df = old_mid_df
                    self.logger.critical(f"Error Loading MID: {e}")
                    self.logger.warning("Previous MID State Recovered")
                    QMessageBox.critical(self, "Error Loading MID", f"Previous MID state restored. \n\n{str(e)}")
            


    # runs the suite of MID audit functions defined in audit_runner.py
    def run_mid_audit(self):
        self.logger.info("Starting MID Audit")
        try:
            output_path = run_mid_audit(self.mid_manager, self.settings)
            QMessageBox.information(self, "Audit Complete", f"Audit Complete! Output saved to:\n{output_path}")
        except Exception as e:
            self.logger.critical(f"AUDIT FAILED: {e}")
            QMessageBox.critical(self, "Audit Error", str(e))

    # basic handler for the fialure loading function below
    def handle_load_failures(self):
        test_name = self.failure_test_combo.currentText()
        self.load_audit_failures(test_name)


    # Restrict the MID to only entries where the file failed the selected test. Default to cases where the doc loaded but wasn't scraped
    def load_audit_failures(self, test_name="text_scraped"):
        try:
            log_path = os.path.join(self.settings.get("logFileDirectory", "./logs"), "audit_report.json")
            with open(log_path, "r", encoding="utf-8") as f:
                audit_results = json.load(f)

            failed_indices = [
                entry["index"]
                for entry in audit_results
                if entry.get("tests", {}).get(test_name) == "FAIL"
            ]

            if not failed_indices:
                QMessageBox.information(self, "No Failures", f"No failures found for test: {test_name}")
                return

            self.mid_manager.restrict_to_rows(failed_indices)
            self.logger.info(f"Loaded {len(failed_indices)} failure rows for test '{test_name}' into MID view")
            self.load_mid_entry_document()
            
            self.manual_review["active_test"] = test_name
            self.manual_review["results"] = {}
            self.logger.info(f"Manual review mode enabled for test '{test_name}'")



        except Exception as e:
            self.logger.error(f"Failed to load audit failures for '{test_name}': {e}")
            QMessageBox.critical(self, "Error", f"Could not load failures for test '{test_name}':\n{e}")

    # Save manual reveiw results to JSON (Dev mode only)
    def export_review_results(self):
        if not self.manual_review["active_test"]:
            QMessageBox.information(self, "Not in Review Mode", "You must be in manual review mode to export results.")
            return

        try:
            filename = f"{self.manual_review['active_test']}_review.json"
            output_path = os.path.join(self.settings.get("logFileDirectory", "./logs"), filename)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(self.manual_review["results"], f, indent=2)

            self.logger.info(f"Manual review results saved to {output_path}")
            QMessageBox.information(self, "Export Complete", f"Review results saved to:\n{output_path}")
        except Exception as e:
            self.logger.error(f"Failed to export review results: {e}")
            QMessageBox.critical(self, "Export Error", str(e))



if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TextScrapingReviewApp()
    window.show()
    sys.exit(app.exec_())
