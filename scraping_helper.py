import sys
import os
import fitz  # PyMuPDF
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
    QInputDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage

# local imports

from settings_window import SettingsDialog
from app_settings import load_settings, save_settings
from mid_manager import MIDManager
from logger import setup_logger
from scraper_loader import load_scraper_class
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
        self.mid_df = None
        self.current_mid_index = 0

        mid_path = self.settings.get("MIDLocation", "")
        if mid_path:
            try:
                self.mid_manager = MIDManager(mid_path)
                self.logger.info("Successfully loaded MID")
            except Exception as e:
                self.logger.critical(f"Failed to Load MID: {e}")
                QMessageBox.critical(self, "Error Loading MID", str(e))
        else:
            self.logger.warning("MID Location not specified, user alerted")
            QMessageBox.warning(self, "MID Location not Specified", "Please select a Master Input Document in Settings.")


        self.doc = None
        self.page_indices = [] # List of all zero-indexed pages recorded in the MID
        self.current_page_index = 0
        self.current_agency_yr = None
        self.scraped_text = ""
        self.info_labels = {}
        self.init_files()

        self.init_ui()

        if hasattr(self, "mid_manager") and self.mid_manager.df is not None:
            success = self.load_mid_entry_document()
            if not success:
                self.logger.warning("First MID row failed to load; check file accessibility or page numbers.")
            else:
                self.logger.debug("First MID row loaded successfully")
                # self.scrape_page()

        

    def init_ui(self):
        self.logger.debug("Initializing UI")
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # --- Status Information Panel ---
        info_layout = QVBoxLayout()

        self.entry_index_label = QLabel("Entry 0 of 0")
        self.entry_index_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.entry_index_label)


        self.info_fields = ["File", "Agency", "Year", "Page"]

        # Dynamically create info fields to enhance modularity
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

        accept_btn = QPushButton("Accept Scrape")
        accept_btn.clicked.connect(self.accept_scrape)
        control_layout.addWidget(accept_btn)
        self.logger.debug("Added Accept Scrape button")

        reject_btn = QPushButton("Reject Scrape")
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
        self.logger.debug("Added Audit button")

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

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 4)



    # Create Necessary File Structure
    def init_files(self):
        # Check if the "./data" directory exists; if not, create it
        data_dir = self.settings.get("dataDirectory", "")
        if data_dir and not os.path.exists(data_dir):
            self.logger.warning("./data does not exist! attempting to create directory")
            try:
                os.makedirs(data_dir)
                self.logger.info("Created ./data directory for input files")
            except Exception as e:
                self.logger.error("Failed to Create ./data! Files will not be loaded!")
                QMessageBox.critical(self, "Error", f"Failed to create data directory:\n{e}")
                return
        # TODO: Consolodate this and other file management functions into a utils library

    # Update read-only information for user
    def update_info_labels(self):
        self.logger.debug("Updating info labels")
        page_num = self.page_indices[self.current_page_index] + 1 if self.page_indices else self.current_page_index + 1
        row = None
        mid_length = len(self.mid_manager.df)
        row = self.mid_manager.get_current_row()
        current_mid_index = self.mid_manager.current_index

        if row is not None:
            if hasattr(self, "entry_index_label"):
                self.entry_index_label.setText(
                    f"Entry {current_mid_index + 1:,} of {mid_length:,}"
                )

        for key, label in self.info_labels.items():
            if key == "page":
                value = page_num
            elif key == "file":
                value = self.current_agency_yr
            elif key in row:
                value = row[key]
            else:
                value = "N/A"
            label.setText(f"{key.capitalize()}: {value}")

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

        agency = row.get("agency", "UNKNOWN").strip()
        year = str(row.get("year", "UNKNOWN")).strip()
        agency_yr = row.get("agency_yr", "").strip()
        label = f"{agency} ({year})"

        if not agency_yr:
            self.logger.error(f"MID row missing 'agency_yr' for {label}")
            return False

        self.current_agency_yr = agency_yr
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

            self.current_page_index = 0
            # PyMuPDF is 0-indexed, add 1 to match user's expected range
            display_pages = [p+1 for p in self.page_indices]
            self.logger.info(f"Loaded {filename} for {label}, pages: {display_pages}")
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
        page = self.doc.load_page(page_number)

        # Render the page and upscale by 2x
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(img)
        self.pdf_label.setPixmap(
            pixmap.scaled(self.pdf_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

        # Clear any previous scraped text
        self.text_edit.clear()
        self.scraped_text = ""

        # Scrape the new page
        self.scrape_page()
        # Display document information
        self.update_info_labels()

    def resizeEvent(self, event):
        self.logger.debug("Window resized")
        super().resizeEvent(event)
        self.show_page()

    def next_page(self):
        self.logger.debug("Attempting to load next page")
        if self.page_indices and self.current_page_index < len(self.page_indices) - 1:
            self.logger.debug("Next page is valid")
            self.current_page_index += 1
            self.show_page()

        else:
            self.logger.warning("Attempted to load nonexistent page")

    def prev_page(self):
        self.logger.debug("Attempting to load previous page")
        if self.page_indices and self.current_page_index > 0:
            self.logger.debug("Previous page is valid")
            self.current_page_index -= 1
            self.show_page()

        else:
            self.logger.warning("Attempted to load nonexistent page")

    def scrape_page(self):
        self.logger.debug("Attempting to scrape page")

        if not self.doc or self.mid_manager.df is None:
            self.logger.warning("Document or MID is missing!")
            QMessageBox.warning(self, "Error", "Document or MID is missing!")
            return

        try:
            # For now, hardcode this to pull the basic text scraper
            # TODO: grab the user's scraper-doctype mappings for scraper selection
            scraper_path = os.path.join(os.path.dirname(__file__), "scrapers", "text_scraper.py")
            ScraperClass = load_scraper_class(scraper_path)

            if self.page_indices:
                actual_page_number = self.page_indices[self.current_page_index]
            else:
                actual_page_number = self.current_page_index
            page = self.doc.load_page(actual_page_number)
            scraper = ScraperClass(page)
            result = scraper.scrape()

            self.scraped_text = result.get("text", "")
            self.text_edit.setPlainText(self.scraped_text)

            self.logger.debug(f"Scraped page {actual_page_number+1}")

        except Exception as e:
            self.logger.critical(f"failed to scrape page {actual_page_number+1}: {e}")
            QMessageBox.critical(self, "Scrape Error", str(e))


    def accept_scrape(self):
        """
        Handle acceptance of the scraped text for this page.
        Implement logic to move to second-stage review or save results.
        """
        self.logger.info("Scrape Accepted!")
        QMessageBox.information(
            self, "Accept", f"Scrape accepted for page {self.current_page_index + 1}."
        )

    def reject_scrape(self):
        """
        Handle rejection of the scraped text for this page.
        Implement logic to flag for further review.
        """
        self.logger.info("Scrape REJECTED")
        QMessageBox.warning(
            self, "Reject", f"Scrape rejected for page {self.current_page_index + 1}."
        )

    def next_mid_entry(self):
        self.advance_to_valid_entry(direction="next")
        # self.scrape_page()

    def prev_mid_entry(self):
        self.advance_to_valid_entry(direction="prev")
        # self.scrape_page()

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


    def open_settings(self):
        self.logger.debug("Attempting to open Settings")
        old_mid_path = self.settings.get("MIDLocation", "")
        old_mid_df = self.mid_manager.df
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_() == QDialog.Accepted:
            self.logger.info("User updated settings in-app")
            self.settings = dialog.settings
            save_settings(self.settings)

            new_mid_path = self.settings.get("MIDLocation", "")
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

    def run_mid_audit(self):
        self.logger.info("Starting MID Audit")
        try:
            output_path = run_mid_audit(self.mid_manager, self.settings)
            QMessageBox.information(self, "Audit Complete", f"Audit Complete! Output saved to:\n{output_path}")
        except Exception as e:
            self.logger.critical(f"AUDIT FAILED: {e}")
            QMessageBox.critical(self, "Audit Error", str(e))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TextScrapingReviewApp()
    window.show()
    sys.exit(app.exec_())
