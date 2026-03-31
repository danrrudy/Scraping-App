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
    QTextBrowser,
    QGroupBox,
    QFormLayout,
    QButtonGroup,
    QRadioButton,
    QAction,
    QScrollArea,
    QCheckBox,
    QLineEdit,
    QSpinBox,
    QShortcut,
)
from PyQt5.QtCore import Qt, QByteArray, QEvent
from PyQt5.QtGui import QPixmap, QImage, QKeySequence
import base64
from io import BytesIO
import pandas as pd
import re

# local imports

from settings_window import SettingsDialog
from app_settings import load_settings, save_settings
from mid_manager import MIDManager
from logger import setup_logger
from scraper_loader import select_scraper_class
from extractor_loader import select_extractor_class 
from audit_runner import run_mid_audit
from image_canvas import ImageCanvas


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
        self.edit_path = {"layer": None, "stratobj": 0, "obj": 0, "goal": 0, "metric": 0}

        # Initiate the MID manager if settings are already set
        mid_path = self.settings.get("MIDLocation", "")
        if mid_path:
            try:
                self.mid_manager = MIDManager(mid_path)
                # After loading MID DataFrame
                for col, default in [
                    ("classification_scheme", ""), # Scheme name per row
                    ("metric_status", ""),   # radio selection per metric row
                    ("target", ""),                 # Listed goal field
                    ("actual", ""),                 # Lister performance field
                    ("years_to_evaluation", ""),     # str or int for eval point
                    ("_flag", False),        # flag for review
                    ("_no_metrics", False),  # marks a goal saved without metrics
                    ("_gen", False),
                    ("_achieved", False),
                    ("_future_dated", False),
                    ("Page", ""),
                    ("_aggregate", False)           # Indicator for aggregate goals
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
            QMessageBox.warning(self, "MID Location not Specified", "Please select a Master Input Document in Settings.")

        # We keep separate lists of widgets for each mode so they can be dynamically loaded and unloaded
        # Any widget not assigned to a mode will always be shown
        # Widgets assigned to a mode will be shown in that mode, and hidden in others 
        self.dev_mode_widgets = []      # Superset of user mode, distinct from reviewer
        self.user_mode_widgets = []     # Base mode, minimum useful functionality
        self.reviewer_mode_widgets = [] # Superset of user mode, with added review functionality

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
        self.mid_field_editors = {}     #{key: QTextEdit}
        self.mid_field_keys = ["stratobj", "obj", "goal", "metric"]


        self.add_level_buttons = {}
        self.expansion_state = {
            "base_level": None,       # lowest present on the seed row (stratobj|obj|goal|metric|None)
            "working_level": None,    # where the user is currently adding units
            "seed_index": None,       # index of the original (non-generated) row we started from
        }

        # overlays + coords from the most recent scrape
        self.page_overlays = {}   # {page_index: PNG bytes}
        self.cells_by_page = {}   # {page_index: [(x0,y0,x1,y1), ...]} (for later click-to-scrape)
        self.page_dims     = {}   # {page_index: (w_pt, h_pt)}         (for later)


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

    def _pil_to_qpixmap(self, pil_img):
        if pil_img is None:
            self.logger.warning("image was none!")
            return None
        if pil_img.mode in ("RGBA", "LA"):
            fmt = QImage.Format_RGBA8888
            img = pil_img.convert("RGBA")
            bpl = pil_img.width * 4
        else:
            fmt = QImage.Format_RGB888
            img = pil_img.convert("RGB")
            bpl = pil_img.width * 3
        self.logger.debug("converted image")
        data = img.tobytes("raw", img.mode)
        self.logger.debug("converted to raw data")
        qimg = QImage(data, img.width, img.height, bpl, fmt).copy()
        return QPixmap.fromImage(qimg)

    def _build_image_html_per_page(self, scrape_result, page_indices):
        pages = scrape_result.get("result", []) or []
        html_by_page = []

        # Map display order to the internal 0..N page order we scraped
        # (scraper used enumerate(self.pages) so it's already aligned; we still guard on bounds)
        for local_idx, _pdf_zero_index in enumerate(page_indices):
            tables = pages[local_idx] if local_idx < len(pages) else []
            chunks = []
            if tables:
                for t in tables:
                    img = t.get("table_image", None)
                    if img is None:
                        continue
                    src = self._pil_to_data_uri(img)
                    # wrap each with a light border/caption
                    cap = f"Page {t.get('page_number','?')} – Table {t.get('table_index_on_page','?')}"
                    chunks.append(
                        f"<div style='margin:10px 0;'><div style='font-size:12px;color:#888'>{cap}</div>"
                        f"<img src='{src}' style='max-width:100%; height:auto; border:1px solid #ddd;'/></div>"
                    )
            else:
                chunks.append("<div style='color:#999;font-style:italic'>No tables detected on this page.</div>")

            html_by_page.append("<div>" + "".join(chunks) + "</div>")

        return html_by_page

    def _on_table_image_click(self, info: dict):
        self.logger.info(f"Clicked table image: {info}")
        # If you know PDF page width/height in points, map to PDF coords here:
        # pdf_w_pts, pdf_h_pts = self.page_dims[self.current_page_index]
        # x_pdf = info['x_nat'] * (pdf_w_pts / info['nat_w'])
        # y_pdf = info['y_nat'] * (pdf_h_pts / info['nat_h'])
        # ... use x_pdf, y_pdf as needed.
    

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

        mid_fields_group = QGroupBox("Fields")
        mid_form = QFormLayout()

        labels_for = {
            "stratobj": "stratobj",
            "obj": "obj",
            "goal": "goal",
            "metric": "metric"
        }

        for k in self.mid_field_keys:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            editor = QTextEdit()
            editor.setFixedHeight(70)
            self.mid_field_editors[k] = editor

            btn = QPushButton("+")
            btn.setFixedWidth(26)
            btn.setToolTip(f"Add new {k} row")
            btn.clicked.connect(lambda _=False, kk=k: self.on_add_level_clicked(kk))

            self.add_level_buttons[k] = btn

            row_layout.addWidget(editor, 1)
            row_layout.addWidget(btn, 0)

            mid_form.addRow(labels_for[k] + ":", row_widget)

        self.target_edit = QLineEdit()
        self.actual_edit = QLineEdit()
        mid_form.addRow("Target:", self.target_edit)
        mid_form.addRow("Actual:", self.actual_edit)

        mid_fields_group.setLayout(mid_form)
        info_layout.addWidget(mid_fields_group)

        # --- Metric status radios (Under the Metric editor) ---
        scheme_row = QHBoxLayout()
        scheme_row.setSpacing(8)

        scheme_lbl = QLabel("Classification Scheme:")
        scheme_row.addWidget(scheme_lbl)

        self.class_scheme_combo = QComboBox()
        scheme_row.addWidget(self.class_scheme_combo)
        scheme_row.addStretch(1)

        mid_form.addRow("", QWidget())
        mid_form.addRow(scheme_row)

        # Metric Status
        metric_container = QWidget()
        metric_vlayout = QVBoxLayout(metric_container)
        metric_vlayout.setSpacing(4)
        metric_vlayout.setContentsMargins(0, 0, 0, 0)

        metric_lbl = QLabel("Metric Status:")
        metric_vlayout.addWidget(metric_lbl)

        self.metric_status_group = QButtonGroup(self)  # keeps exclusivity
        self.metric_status_buttons = {}  # key -> QRadioButton
        self.metric_status_container = QWidget()
        self.metric_status_layout = QHBoxLayout(self.metric_status_container)
        self.metric_status_layout.setSpacing(8)
        self.metric_status_layout.setContentsMargins(0, 0, 0, 0)

        metric_vlayout.addWidget(self.metric_status_container)

        # put the status row right below the metric QTextEdit
        mid_form.addRow("", QWidget())  # tiny spacer line
        mid_form.addRow(metric_container)

        # Detect change in scheme
        self.class_scheme_combo.currentTextChanged.connect(self.on_scheme_changed)
        # Populate corresponding buttons
        self._refresh_class_schemes_from_settings()


        # --- Action buttons under the status radios ---
        actions_row = QHBoxLayout()
        self.chk_flag = QCheckBox("Flag for review")
        self.chk_aggregate = QCheckBox("Aggregate")
        self.chk_achieved = QCheckBox("Achieved")
        self.chk_future_dated = QCheckBox("Future-Dated")
        self.years_to_eval_spin = QSpinBox()
        self.years_to_eval_spin.setRange(0,20)                  # arbitrary, would be shocked if any are greater than 20
        self.years_to_eval_spin.setSpecialValueText("")
        self.years_to_eval_spin.setEnabled(False)
        self.years_to_eval_spin.setFixedWidth(60)

        years_lbl = QLabel("Years to eval:")
        self.btn_save_goal_no_metrics = QPushButton("Save Goal (no metrics)")

        self.chk_flag.stateChanged.connect(self.on_flag_togggle)
        self.chk_aggregate.stateChanged.connect(self.on_agg_togggle)
        self.chk_achieved.stateChanged.connect(self.on_achieved_toggle)
        self.chk_future_dated.stateChanged.connect(self.on_fd_togggle)
        self.years_to_eval_spin.valueChanged.connect(self.on_years_to_eval_changed)

        # Notes field
        notes_container = QHBoxLayout()
        self.notes_lbl = QLabel("Notes:")
        self.notes = QLineEdit()
        notes_container.addWidget(self.notes_lbl)
        notes_container.addWidget(self.notes)

        self.btn_save_goal_no_metrics.clicked.connect(self.on_save_goal_no_metrics_clicked)

        actions_row.addWidget(self.chk_flag)
        self.chk_flag.setShortcut("Ctrl+F")
        actions_row.addWidget(self.chk_aggregate)
        actions_row.addWidget(self.chk_achieved)
        actions_row.addWidget(self.chk_future_dated)
        actions_row.addWidget(years_lbl)
        actions_row.addWidget(self.years_to_eval_spin)
        actions_row.addWidget(self.btn_save_goal_no_metrics)
        mid_form.addRow(actions_row)


        mid_form.addRow(notes_container)

        expand_group = QGroupBox("Expand to Metrics")
        expand_layout = QVBoxLayout()

        self.hint_lbl = QLabel("")
        self.hint_lbl.setWordWrap(True)
        expand_layout.addWidget(self.hint_lbl)

        # Adaptive depth-first controls
        self.btn_add = QPushButton("")   # label set dynamically
        self.btn_done = QPushButton("")  # label set dynamically

        self.btn_add.clicked.connect(self.on_add_clicked)
        self.btn_done.clicked.connect(self.on_done_clicked)

        expand_layout.addWidget(self.btn_add)
        expand_layout.addWidget(self.btn_done)


        expand_group.setLayout(expand_layout)
        info_layout.addWidget(expand_group)
        expand_group.hide()


        # --- Control Panel ---
        # Menu action
        save_mid_act = QAction("Save MID…", self)
        save_mid_act.triggered.connect(self.save_mid_to_file)
        self.menuBar().addMenu("&File").addAction(save_mid_act)
        save_mid_act.setShortcut("Ctrl+S")

        control_layout = QVBoxLayout()
        # load_btn = QPushButton("Load Document")
        # load_btn.clicked.connect(self.load_document)
        # control_layout.addWidget(load_btn)
        # self.logger.debug("Added Load Document button")

        prev_btn = QPushButton("Previous Page")
        prev_btn.clicked.connect(self.prev_page)
        control_layout.addWidget(prev_btn)
        self.logger.debug("Added Previous Page button")

        next_btn = QPushButton("Next Page")
        next_btn.clicked.connect(self.next_page)
        control_layout.addWidget(next_btn)
        self.logger.debug("Added Next Page button")

        # scrape_btn = QPushButton("Scrape Page")
        # scrape_btn.clicked.connect(self.scrape_page)
        # control_layout.addWidget(scrape_btn)
        # self.logger.debug("Added Scrape Page button")

        # accept_btn = QPushButton("Accept")
        # accept_btn.clicked.connect(self.accept_scrape)
        # control_layout.addWidget(accept_btn)
        # self.logger.debug("Added Accept Scrape button")

        # reject_btn = QPushButton("Reject")
        # reject_btn.clicked.connect(self.reject_scrape)
        # control_layout.addWidget(reject_btn)
        # self.logger.debug("Added Reject Scrape button")

        next_entry_btn = QPushButton("Next MID Entry")
        next_entry_btn.clicked.connect(self.next_mid_entry)
        control_layout.addWidget(next_entry_btn)
        next_entry_btn.setShortcut("Ctrl+Right")
        self.logger.debug("Added Next MID Entry button")

        prev_entry_btn = QPushButton("Previous MID Entry")
        prev_entry_btn.clicked.connect(self.prev_mid_entry)
        control_layout.addWidget(prev_entry_btn)
        next_entry_btn.setShortcut("Ctrl+Left")
        self.logger.debug("Added Previous MID Entry button")

        select_entry_btn = QPushButton("Jump to MID Entry...")
        select_entry_btn.clicked.connect(self.select_mid_entry)
        control_layout.addWidget(select_entry_btn)
        next_entry_btn.setShortcut("Ctrl+O")
        self.logger.debug("Added Select MID Entry button")

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
        failures_label = QLabel("Restrict to:")
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
        self.text_edit.setReadOnly(True) 
        self.text_edit.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.text_edit.setUndoRedoEnabled(False)
        self.text_edit.show()
        splitter.addWidget(self.text_edit)
        self.text_edit.setVisible(True)

        # Image viewer & mouse tracker
        self.image_canvas = ImageCanvas(self, enable_zoom=True)
        # self.image_canvas.show()
        # self.image_canvas.pointClicked.connect(self._on_table_image_click)  # define handler below
        # splitter.addWidget(self.image_canvas)


        # # Table structured display
        self.table_viewer = QTextBrowser()
        # splitter.addWidget(self.table_viewer)
        # self.dev_mode_widgets.append(self.table_viewer)
        # # self.table_viewer.show()

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter, 4)

        self._setup_shortcuts()
        self.installEventFilter(self)

        # hide the dev mode labels if in user mode and v.v.
        # self.update_mode_ui()

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
            current_format_type = row.get("Format_Type_Updated", "")

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
        self.refresh_expansion_controls()

    def update_mode_ui(self):
        # Cache mode in case of race conditions
        mode = self.mode.lower()
        self.logger.info(f"updating UI for {mode} mode")

        match mode:
            # always set the current mode last in case any widget is a member of multiple lists
            case "dev":
                for widget in self.user_mode_widgets:
                    widget.setVisible(False)
                for widget in self.reviewer_mode_widgets:
                    widget.setVisible(False)
                for widget in self.dev_mode_widgets:
                    widget.setVisible(True)
            case "user":
                for widget in self.dev_mode_widgets:
                    widget.setVisible(False)
                for widget in self.reviewer_mode_widgets:
                    widget.setVisible(False)
                for widget in self.user_mode_widgets:
                    widget.setVisible(True)
            case "reviewer":
                for widget in self.user_mode_widgets:
                    widget.setVisible(False)
                for widget in self.dev_mode_widgets:
                    widget.setVisible(False)
                for widget in self.user_mode_widgets:
                    widget.setVisible(True)


    # For manual document loading - depricated
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

        if hasattr(self, "current_agency_yr") and self.current_agency_yr != agency_yr:
            self.current_page_index=0

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
                format_type = int(row.get("Format_Type_Updated", -1))
                ScraperClass = select_scraper_class(self.settings, format_type)
                pages = [self.doc.load_page(p) for p in self.page_indices]
                Scraper = ScraperClass(pages)
                Scraper.scrape()
                result = Scraper.result
                self.logger.info("got scraper result!")
                self.current_scrape_result = result or {}               

                if str(result.get("format", "")).lower() == "image":
                    self.logger.debug("using image format")
                    result_pages = result.get("result",[]) or []
                    self._page_table_images = []
                    for local_idx, _pdf_idx in enumerate(self.page_indices):
                        self.logger.debug("iter page")
                        tables = result_pages[local_idx] if local_idx < len(result_pages) else []
                        pil_img = tables[0].get("table_image") if tables else None
                        self._page_table_images.append(pil_img)

                    img = self._page_table_images[self.current_page_index]
                    self.logger.debug("got image")
                    qpix = self._pil_to_qpixmap(img) if img is not None else None   
                    self.logger.debug("converted to qpixmap")
                    if qpix is not None:
                        self.image_canvas.set_image(qpix, meta = {"page": self.current_page_index, "table": 0}, fit = True)
                        self.image_canvas.show() 
                        # if hasattr(self, "text_edit"): self.text_edit.hide()
                        self.logger.debug("displayed")
                    # #switch to HTML viewer
                    # self.use_table_view = True 
                    # self.text_edit.setVisible(False)
                    self.image_canvas.setVisible(True)
                    text_result = []
                else:
                    text_result = result.get("text")
                    self.page_text_cache = text_result
                    self.text_edit.setPlainText(self.page_text_cache[self.current_page_index])
                    self.logger.debug("showing text editor")
                    self.image_canvas.setVisible(False)
                    self.image_canvas.hide()
                    self.text_edit.setVisible(True)
                    self.text_edit.show()




                # self.logger.debug(f"html to render: {text_result[0]}")


                if not isinstance(text_result, list):
                    raise ValueError("Expected a list of strings from the Scraper!")

                # if len(text_result) != len(self.page_indices):
                #     self.logger.warning(f"Scraper returned {len(text_result)} pages, expected {len(self.page_indices)}")

                # self.page_text_cache = text_result
                # self.logger.info(f"Scraped {len(self.page_text_cache)} pages from {label}")    

            except Exception as e:
                self.logger.error(f"Failed to scrape all pages for {label}: {e}")


            # Decide which right-hand widget to show
            is_image = str(self.current_scrape_result.get("format","")).lower() == "image"
            self.use_table_view = is_image or (self.use_table_view)  # image implies table_view
            # self.text_edit.setVisible(not self.use_table_view)
            # self.image_canvas.setVisible(self.use_table_view)

            # self.current_page_index = 0
            # # PyMuPDF is 0-indexed, add 1 to match user's expected range
            # display_pages = [p+1 for p in self.page_indices]
            # self.logger.info(f"Loaded {filename} for {label}, pages: {display_pages}")
            self.show_page()
            self.load_mid_fields_from_row()
            self.refresh_expansion_controls()
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

        p = self.current_page_index

        # NEW: prefer overlay for this page if we have one
        overlay_png = None
        # 1) direct per-page map
        if getattr(self, "page_overlays", None):
            overlay_png = self.page_overlays.get(p)

        # 2) compatibility: allow overlay inside result["pages"][i]["overlay_image"]
        if overlay_png is None and getattr(self, "current_scrape_result", None):
            pages = self.current_scrape_result.get("pages") or []
            for it in pages:
                if it.get("page_index") == p and it.get("overlay_image"):
                    overlay_png = it["overlay_image"]
                    break

        if overlay_png:
            self._show_png_bytes_in_center(overlay_png)
            self.update_info_labels()   # keep your normal UI refresh
            return

        else:

            self.logger.debug(f"Attempting to load index {self.current_page_index}, page {page_number}")
            page = self.doc.load_page(page_number)

            # Render the page and upscale by 2x
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(img)
            self.pdf_label.setPixmap(
                pixmap.scaled(self.pdf_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

            text_content = self.page_text_cache[self.current_page_index]
            # if self.use_table_view:
            #     self.table_viewer.setHtml(text_content)

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
            if not self.use_table_view:
                self.page_text_cache[self.current_page_index] = self.text_edit.toPlainText()
            else:
                self.page_text_cache[self.current_page_index] = self.table_viewer.toHtml()
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
        format_type = int(row.get("Format_Type_Updated", -1))
        # actual_page_number adds the page index to the start page
        if self.page_indices:
            actual_page_number = self.page_indices[self.current_page_index]
        else:
            actual_page_number = self.current_page_index

        try:
            # For now, hardcode this to pull the basic text scraper
            # TODO: grab the user's scraper-doctype mappings for scraper selection
            ScraperClass = select_scraper_class(self.settings, format_type)
            ExtractorClass = select_extractor_class(self.settings, format_type)


            # Extract the current page to scrape

            page = self.doc.load_page(actual_page_number)
            
            # Create a scraper instance for the page
            scraper = ScraperClass([page])
            scraper.scrape()
            result = scraper.result

            extractor = ExtractorClass(result, metadata ={"agency_yr": self.current_agency_yr}) 
            extractor.extract()
            struct = extractor.result 
            if struct.get("format") == "html":
                self.page_text_cache = struct["text"][self.current_page_index]
                self.use_table_view = True 
                self.table_viewer.setHtml(struct["text"][self.current_page_index])
            else:
                self.use_table_view = False 



            self.scraped_text = result.get("text", [""])
            self.text_edit.setPlainText(self.scraped_text[0])

            # Add 1, as actual_page_number is 0-indexed
            self.logger.debug(f"Scraped page {actual_page_number+1}")

        except Exception as e:
            self.logger.critical(f"failed to scrape page {actual_page_number+1}: {e}")
            QMessageBox.critical(self, "Scrape Error", str(e))

    def extract_content(self):
        self.logger.debug(f"Attempting to extract content from page {self.current_page_index}")

        if not self.doc:
            self.logger.warning("Document could not be found!")
            return

        row = self.mid_manager.get_current_row()
        format_type = int(row.get("Format_Type_Updated", -1))
        if self.page_indices:
            actual_page_number = self.page_indices[self.current_page_index]
        else:
            actual_page_number = self.current_page_index

        try:
            print("i need to put something in this block")
            # Extraction logic goes here

        except Exception as e:
            self.logger.critical(f"Failed to scrape page {actual_page_number+1}: {e}")


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
        self.refresh_expansion_controls()
        self._commit_sidebar_fields()
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
        self._commit_sidebar_fields()
        self.advance_to_valid_entry(direction="next")
        self.refresh_expansion_controls()
        # self.scrape_page()

    # Move to previous entry without any output
    def prev_mid_entry(self):
        self._commit_sidebar_fields()
        self.advance_to_valid_entry(direction="prev")
        self.refresh_expansion_controls()
        # self.scrape_page()

    # Move to specified MID entry
    def select_mid_entry(self):
        self._commit_sidebar_fields()
        num, ok = QInputDialog.getInt(self, "Jump to MID Entry", "num", min = 1, max=len(self.mid_manager.df), step=1)
        if not ok: return
        if num < 1 or num > len(self.mid_manager.df):
            QMessageBox.warning("Out of range!")
            return
        self.mid_manager.select_mid_entry(num)
        self.refresh_expansion_controls()
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

            row = self.mid_manager.get_current_row()
            format_type = int(row.get("Format_Type_Updated", -1))
            #if(format_type not in [19, 20, 21, 22, 23]):
            #    continue
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
            self._refresh_class_schemes_from_settings()
            save_settings(self.settings)
            self.mode = self.settings.get("userMode", "User")
            self.update_mode_ui()

            new_mid_path = self.settings.get("MIDLocation", "")
            new_sheet_name = self.settings.get("MIDSheetName", 0)

            old_mid_path = old_mid_path or ""
            old_sheet_name = self.settings.get("MIDSheetName", 0)  # NOTE: see below for better old capture
            # Better: capture old_sheet_name BEFORE dialog (recommended), see next snippet.

            if not new_mid_path:
                QMessageBox.critical(self, "Missing MID", "You must select a MID to use the app!")
                self.logger.error("User did not select a MID")
                return

            # Determine whether the MID source changed (path or sheet)
            mid_changed = (new_mid_path != old_mid_path) or (str(new_sheet_name) != str(old_sheet_name))

            if mid_changed:
                self.logger.info("MID location/sheet changed; reloading MID")

                try:
                    # Reconstruct only when necessary
                    self.mid_manager = MIDManager(new_mid_path, sheet_name=new_sheet_name)

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
                    # Restore prior MID state
                    if old_mid_df is not None:
                        self.mid_manager.df = old_mid_df
                    self.logger.critical(f"Error Loading MID: {e}")
                    self.logger.warning("Previous MID State Recovered")
                    QMessageBox.critical(self, "Error Loading MID", f"Previous MID state restored.\n\n{str(e)}")
            else:
                # MID unchanged; do NOT reconstruct MIDManager (preserves current_index)
                self.logger.debug("MID unchanged; preserving current MIDManager/current_index")



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

    def refresh_expansion_controls(self):
        # deprecated in favor of individual + buttons
        if hasattr(self, "btn_add"):
            self.btn_add.hide()
        if hasattr(self, "btn_done"):
            self.btn_done.hide()
        if hasattr(self, "hint_lbl"):
            self.hint_lbl.setText("")


    def save_mid_to_file(self):
        # Commit current editors first
        self._commit_sidebar_fields()

        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            QMessageBox.warning(self, "Save MID", "No MID loaded.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save MID", "mid_export.xlsx",
            "Excel Workbook (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return

        df = self.mid_manager.df.copy()

        try:
            if path.lower().endswith(".csv"):
                df.to_csv(path, index=False)
            else:
                # default to Excel
                with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
                    df.to_excel(xw, index=False, sheet_name="MID")
            self.statusBar().showMessage(f"Saved MID to {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save MID", f"Failed to save:\n{e}")

    # def set_keyboard_shortcuts(self):
    #     self.chk_flag.setShortcut("Ctrl+F")
    #     self.chk_achieved.setShortcut("Ctrl+A")
    #     self.save_mid_act.setShortcut("Ctrl+S")
    #     self.


    # Utility: save editors into the active row (you already have a similar method)
    def _commit_sidebar_fields(self):
        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            return
        idx = self.mid_manager.current_index
        if idx is None: return
        for k, ed in self.mid_field_editors.items():
            self.mid_manager.df.at[idx, k] = ed.toPlainText().strip()
        self.mid_manager.df.at[idx, "_flag"] = self.chk_flag.isChecked()
        self.logger.info(f"saved flag status: {self.mid_manager.df.at[idx, "_flag"]}")
        self.mid_manager.df.at[idx, "_achieved"] = self.chk_achieved.isChecked()
        self.mid_manager.df.at[idx, "_future_dated"] = self.chk_future_dated.isChecked()
        self.logger.info(f"Saved information for {self.current_agency_yr}: ")
        # metric status and scheme
        scheme = self._safe_text(self.class_scheme_combo.currentText()).strip()
        self.mid_manager.df.at[idx, "classification_scheme"] = scheme
        self.mid_manager.df.at[idx, "metric_status"] = self._safe_text(self._get_metric_status())
        self.mid_manager.df.at[idx, "target"] = self._safe_text(self.target_edit.text()).strip() 
        self.mid_manager.df.at[idx, "actual"] = self._safe_text(self.actual_edit.text()).strip() 
        self.mid_manager.df.at[idx, "notes"] = self._safe_text(self.notes.text()).strip() 
        self.mid_manager.df.at[idx, "Page"] = self.page_indices[self.current_page_index] + 1 if self.page_indices else self.current_page_index + 1

        yrs = self.years_to_eval_spin.value()
        if self.chk_future_dated.isChecked() and yrs > 0:
            self.mid_manager.df.at[idx, "years_to_evaluation"] = str(yrs)
        else:
            self.mid_manager.df.at[idx, "years_to_evaluation"] = ""

    def _clear_field(self, key: str):
        ed = self.mid_field_editors.get(key)
        if ed: ed.clear()

    def _goto_index(self, new_idx: int):
        """Your existing navigation method; ensure it sets current_index then calls update_info_labels/show_page/etc."""
        self.mid_manager.current_index = new_idx
        self.update_info_labels()
        self.load_mid_fields_from_row()
        self.refresh_expansion_controls()
        # show_page() etc. if needed

    def _insert_child_and_goto(self, parent_idx: int, child_level: str) -> int:
        """
        Clone parent row, clear the child_level and below, insert after parent, and move there.
        Returns the new index.
        """
        mm = self.mid_manager
        new_row = mm.clone_for_child(parent_idx, child_level)
        new_idx = mm.insert_row_after(parent_idx, new_row)
        self._goto_index(new_idx)

        # Focus on the editor for the child level
        self._clear_field(child_level)
        return new_idx

    def _text(self, key: str) -> str:
        ed = self.mid_field_editors.get(key)
        return ed.toPlainText().strip() if ed else ""

    def _set_text(self, key: str, value: str):
        ed = self.mid_field_editors.get(key)
        if ed:
            ed.blockSignals(True)
            ed.setPlainText(value or "")
            ed.blockSignals(False)

    def _focus(self, key: str):
        # self.edit_path["layer"] = key
        # for k, v in idx.items():
        #     self.edit_path[k] = v
        ed = self.mid_field_editors.get(key)
        if ed:
            ed.setFocus()

    def _get_metric_status(self) -> str:
        for key, rb in self.metric_status_buttons.items():
            if rb.isChecked():
                return key
        return ""

    def _set_metric_status(self, value: str):
        # value is one of "Exceeded","Met","Unmet","Deferred" or ""
        for key, rb in self.metric_status_buttons.items():
            rb.blockSignals(True)
            rb.setChecked(key == value)
            rb.blockSignals(False)

    def _levels_to_clear(self, level_key: str) -> list[str]:
        order = ["stratobj", "obj", "goal", "metric"]
        if level_key not in order:
            return []
        return order[order.index(level_key)]

    def on_add_level_clicked(self, level_key: str):
        self._commit_sidebar_fields()
        idx = self.mid_manager.current_index
        if idx is None:
            return
        new_row = self.mid_manager.clone_for_child(idx, level_key)
        to_clear = self._levels_to_clear(level_key)

        # Clear metadata where relevant
        if "goal" in to_clear:
            if "_no_metrics" in new_row:
                new_row["_no_metrics"] = False

        if "metric" in to_clear:
            if "metric_status" in new_row:
                new_row["metric_status"] = ""
            if "_achieved" in new_row:
                new_row["_achieved"] = False
            if "_future_dated" in new_row:
                new_row["_future_dated"] = False

        new_idx = self.mid_manager.insert_row_after(idx, new_row)
        self._goto_index(new_idx)

        # Update UI
        for k in to_clear:
            self._set_text(k, "")
        if "metric" in to_clear:
            self._set_metric_status("")
        self._focus(level_key)



    # --- Button slots ---

    def on_next_metric(self):
        """
        Add another Metric under the current Goal.
        If you're on a goal row with empty metric, fill it; if you're already on a metric row, create a sibling metric.
        """
        if not hasattr(self, "mid_manager"): return
        self._commit_sidebar_fields()
        idx = self.mid_manager.current_index
        row = self.mid_manager.df.iloc[idx].to_dict()
        base = self.mid_manager.lowest_present_level(row)

        # If we're on a goal row (goal present, metric empty), stay and let user type metric.
        # If metric already present, create another metric sibling under same goal.
        if base == "goal" and not self.mid_manager._has_val(row, "metric"):
            # Just ensure metric editor is clear and focused
            self._clear_field("metric")
            return

        # Otherwise, create a sibling metric: child_level='metric' clears metric only.
        new_idx = self._insert_child_and_goto(idx, "metric")

    def on_done_goal(self):
        """
        Finish adding metrics for this goal and move to the next seed row (next non-generated).
        """
        if not hasattr(self, "mid_manager"): return
        self._commit_sidebar_fields()
        next_seed = self.mid_manager.next_seed_row_index(self.mid_manager.current_index)
        if next_seed is None:
            # No more seeds; optionally show a toast/status
            self.statusBar().showMessage("No more seed rows.")
            return
        self._goto_index(next_seed)

    def on_next_goal(self):
        """
        Add another Goal under the current Objective. Creates a child goal row (goal+metric cleared).
        """
        if not hasattr(self, "mid_manager"): return
        self._commit_sidebar_fields()
        idx = self.mid_manager.current_index
        new_idx = self._insert_child_and_goto(idx, "goal")

    def on_done_obj(self):
        """
        Finish adding goals for this objective -> move to next seed entry.
        """
        if not hasattr(self, "mid_manager"): return
        self._commit_sidebar_fields()
        next_seed = self.mid_manager.next_seed_row_index(self.mid_manager.current_index)
        if next_seed is None:
            self.statusBar().showMessage("No more seed rows.")
            return
        self._goto_index(next_seed)

    def on_next_obj(self):
        """
        Add another Objective under the current Strategic Objective. Clears obj+goal+metric.
        """
        if not hasattr(self, "mid_manager"): return
        self._commit_sidebar_fields()
        idx = self.mid_manager.current_index
        new_idx = self._insert_child_and_goto(idx, "obj")

    def on_done_strat(self):
        """
        Finish adding objectives for this strategic objective -> move to next seed entry.
        """
        if not hasattr(self, "mid_manager"): return
        self._commit_sidebar_fields()
        next_seed = self.mid_manager.next_seed_row_index(self.mid_manager.current_index)
        if next_seed is None:
            self.statusBar().showMessage("No more seed rows.")
            return
        self._goto_index(next_seed)

    def load_mid_fields_from_row(self):
        row = getattr(self, "mid_manager", None).get_current_row() if hasattr(self, "mid_manager") else None
        if row is None:
            for k, ed in self.mid_field_editors.items():
                ed.clear()
            self._set_metric_status("")
            return

        else:
            idx = self.mid_manager.current_index
            # flagged
            self.chk_flag.blockSignals(True)
            self.chk_flag.setChecked(self.mid_manager.df.at[idx, "_flag"])
            self.chk_flag.blockSignals(False)
            # achieved
            self.chk_achieved.blockSignals(True)
            self.chk_achieved.setChecked(self.mid_manager.df.at[idx, "_achieved"])
            self.chk_achieved.blockSignals(False)
            # future-dated
            self.chk_future_dated.blockSignals(True)
            self.chk_future_dated.setChecked(self.mid_manager.df.at[idx, "_future_dated"])
            self.chk_future_dated.blockSignals(False)
            # target
            self.target_edit.blockSignals(True)
            self.target_edit.setText(self._safe_text(row.get("target", "") or ""))
            self.target_edit.blockSignals(False)
            # actual
            self.actual_edit.blockSignals(True)
            self.actual_edit.setText(self._safe_text(row.get("actual", "") or ""))
            self.actual_edit.blockSignals(False)

            # years_to_eval
            raw_years = self._safe_text(str(row.get("years_to_evaluation", "") or "")).strip()
            try:
                years_val = int(raw_years) if raw_years else 0
            except ValueError:
                years_val = 0

            self.years_to_eval_spin.blockSignals(True)
            self.years_to_eval_spin.setValue(years_val)
            self.years_to_eval_spin.blockSignals(False)

            #enable years box iff future-dated is checked
            is_fd = bool(self.mid_manager.df.at[idx, "_future_dated"])
            self.years_to_eval_spin.setEnabled(is_fd)

            # notes
            self.notes.blockSignals(True)
            self.notes.setText(self._safe_text(row.get("notes", "")) or "")
            self.notes.blockSignals(False)



        for k, ed in self.mid_field_editors.items():
            ed.blockSignals(True)
            ed.setPlainText(row.get(k, "") or "")
            ed.blockSignals(False)


        scheme = self._safe_text(row.get("classification_scheme", "") or "").strip()
        classes = self.settings.get("evaluationClasses", {}) or {}
        if scheme and scheme in classes:
            self.class_scheme_combo.blockSignals(True)
            self.class_scheme_combo.setCurrentText(scheme)
            self.class_scheme_combo.blockSignals(False)
            self._build_metric_status_radios(scheme)
        elif scheme == "" and self.class_scheme_combo.currentText() in classes:
            pass
        else:
            default_name = self.settings.get("defaultClass", "")
            if default_name in classes:
                self.class_scheme_combo.blockSignals(True)
                self.class_scheme_combo.setCurrentText(default_name)
                self.class_scheme_combo.blockSignals(False)
                self._build_metric_status_radios(default_name)               

        self._set_metric_status(row.get("metric_status", "") or "")


    def on_add_clicked(self):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return

        # Read current editor text (captures unsaved typing)
        so_text   = self._text("stratobj")
        obj_text  = self._text("obj")
        goal_text = self._text("goal")
        metr_text = self._text("metric")

        row = mm.df.iloc[idx].to_dict()
        so   = (row.get("stratobj") or "").strip()
        obj  = (row.get("obj") or "").strip()
        goal = (row.get("goal") or "").strip()
        metr = (row.get("metric") or "").strip()
        no_metrics = bool(row.get("_no_metrics", False))

        # 1) Add Strategic Objective
        if so == "":
            if not so_text:
                self.statusBar().showMessage("Type a Strategic Objective first.")
                self._focus("stratobj"); return
            self._commit_sidebar_fields()
            mm.df.at[idx, "obj"] = ""     # keep seed row as SO header
            mm.df.at[idx, "_gen"] = False
            self.update_info_labels()
            self.load_mid_fields_from_row()
            self.refresh_expansion_controls()
            return

        # 2) Add Objective (create an Objective header row)
        if obj == "":
            if not obj_text:
                self.statusBar().showMessage("Type an Objective first.")
                self._focus("obj"); return
            self._commit_sidebar_fields()
            mm.df.at[idx, "obj"] = ""     # keep current row as SO header

            new_row = mm.clone_for_child(idx, "goal")  # clears goal+metric
            new_row["obj"] = obj_text
            new_idx = mm.insert_row_after(idx, new_row)
            self._goto_index(new_idx)
            self._set_text("goal", "")
            self.refresh_expansion_controls()
            return

        # 3) Add Goal (create first metric row under this goal)
        if goal == "":
            if not goal_text:
                self.statusBar().showMessage("Type a Goal first.")
                self._focus("goal"); return
            self._commit_sidebar_fields()
            mm.df.at[idx, "goal"] = ""    # keep current row as Objective header

            new_row = mm.clone_for_child(idx, "metric")  # clears metric
            new_row["goal"] = goal_text
            new_idx = mm.insert_row_after(idx, new_row)
            self._goto_index(new_idx)
            self._set_text("metric", "")
            self.refresh_expansion_controls()
            return

        # 4) Add Metric (commit current metric, open sibling)
        else:
            # goal present -> either metric stage OR terminal goal
            if no_metrics:
                # Treat as ‘done with goal’ – show only the Done button (optional UX)
                self.btn_add.hide()
                self.btn_done.setText("Done with Goal")
                self.btn_done.show()
                self.hint_lbl.setText("<i>This goal has no metrics. Click Done with Goal to continue.</i>")
                return

            # Normal metric stage
            self.btn_add.setText("Add Metric")
            self.btn_done.setText("Done with Goal")
            self.btn_add.show(); self.btn_done.show()
            self.hint_lbl.setText("<i>Add one or more Metrics for this Goal.</i>")
            self._focus("metric")

        self._commit_sidebar_fields()
        sibling = mm.clone_for_child(idx, "metric")     # clears metric only
        new_idx = mm.insert_row_after(idx, sibling)
        self._goto_index(new_idx)
        self._set_text("metric", "")
        self._set_metric_status("")  # clear selection for the next metric
        self.refresh_expansion_controls()

    def on_done_clicked(self):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return

        self._commit_sidebar_fields()
        row = mm.df.iloc[idx].to_dict()
        so   = (row.get("stratobj") or "").strip()
        obj  = (row.get("obj") or "").strip()
        goal = (row.get("goal") or "").strip()

        # Done with Strategic Objective (obj is blank at header)
        if so != "" and obj == "":
            nxt = mm.next_seed_row_index(idx)
            if nxt is None:
                self.statusBar().showMessage("No more seed rows.")
                return
            self._goto_index(nxt)
            return

        # Done with Objective -> go to SO header (same SO, obj=='')
        if so != "" and obj != "" and goal == "":
            parent = mm.find_parent_for_obj(idx)
            if parent is not None:
                self._goto_index(parent)
                self._set_text("obj", "")   # ready for next objective
            return

        # Done with Goal -> go to OBJ header (same SO+OBJ, goal=='')
        if so != "" and obj != "" and goal != "":
            parent = mm.find_parent_for_goal(idx)
            if parent is not None:
                self._goto_index(parent)
                self._set_text("goal", "")  # ready for next goal
            return
    def on_save_goal_no_metrics_clicked(self):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return

        # Read what’s currently typed
        goal_text = self._text("goal")
        if not goal_text:
            self.statusBar().showMessage("Type a Goal first.")
            self._focus("goal"); return

        # Must be on an Objective header (SO+OBJ filled, goal empty)
        row = mm.df.iloc[idx].to_dict()
        so   = (row.get("stratobj") or "").strip()
        obj  = (row.get("obj") or "").strip()
        goal = (row.get("goal") or "").strip()
        if not (so and obj and goal == ""):
            self.statusBar().showMessage("Save Goal (no metrics) is only available when adding goals under an Objective.")
            return

        # Commit any SO/OBJ text (usually already set); keep the header unchanged
        self._commit_sidebar_fields()
        mm.df.at[idx, "goal"] = ""  # ensure this remains the OBJ header row

        # Create a terminal goal row with no metrics
        new_row = mm.clone_for_child(idx, "metric")  # clears metric only
        new_row["goal"] = goal_text
        new_row["_no_metrics"] = True   # mark as terminal goal (no metrics)
        new_idx = mm.insert_row_after(idx, new_row)

        # Return to the OBJ header ready to type the next goal
        self._goto_index(idx)
        self._set_text("goal", "")
        self._set_text("metric", "")
        self._set_metric_status("")
        self.refresh_expansion_controls()
        self.statusBar().showMessage("Saved goal without metrics.")

    def on_flag_togggle(self, state, propogate = False):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return
        row = mm.df.iloc[idx].to_dict()
        self._commit_sidebar_fields()

        
        if propogate:
            mm.propagate_flag_from_index(idx, flagged=True)
            self.statusBar().showMessage("Flagged for review (propagated to children).")
        else:
            mm.df.at[mm.current_index, "_flag"] = (state == Qt.Checked)
            self.statusBar().showMessage("Flagged for review.")

        
        # If you show flags in the table view, refresh that view here as well.
        self.update_info_labels()

    def on_agg_togggle(self, state):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return

        mm.df.at[mm.current_index, "_aggregate"] = (state == Qt.Checked)

        # refresh sidebar.
        self.update_info_labels()

    def on_achieved_toggle(self, state):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return
        mm.df.at[mm.current_index, "_achieved"] = (state == Qt.Checked)

    def on_fd_togggle(self, state):
        mm = getattr(self, "mid_manager", None)
        if not mm or mm.df is None: return
        idx = mm.current_index
        if idx is None: return

        is_fd = (state == Qt.Checked)
        mm.df.at[mm.current_index, "_future_dated"] = is_fd

        self.years_to_eval_spin.setEnabled(is_fd)

        if not is_fd:
            self.years_to_eval_spin.blockSignals(True)
            self.years_to_eval_spin.setValue(0)
            self.years_to_eval_spin.blockSignals(False)
            mm.df.at[idx, "years_to_evaluation"] = ""

    def on_years_to_eval_changed(self, value: int):
        idx = self.mid_manager.current_index

        if value > 0:
            self.mid_manager.df.at[idx, "years_to_evaluation"] = str(value)
        else:
            self.mid_manager.df.at[idx, "years_to_evaluation"] = ""


    def _refresh_class_schemes_from_settings(self):
        classes = self.settings.get("evaluationClasses", {}) or {}
        names = list(classes.keys())

        self.class_scheme_combo.blockSignals(True)
        self.class_scheme_combo.clear()
        self.class_scheme_combo.addItems(names)
        self.class_scheme_combo.blockSignals(False)

        # Load a default class
        default_name = self.settings.get("defaultClass", "")
        if default_name in names:
            self.class_scheme_combo.setCurrentText(default_name)
            self._build_metric_status_radios(default_name)
        elif names:
            self.class_scheme_combo.setCurrentIndex(0)
            self._build_metric_status_radios(names[0])
        else:
            self._build_metric_status_radios(None)

    def _build_metric_status_radios(self, scheme_name: str | None):
        for rb in self.metric_status_buttons.values():
            self.metric_status_group.removeButton(rb)
            rb.setParent(None)
            rb.deleteLater()
        self.metric_status_buttons = {}

        # clear layout widgets
        while self.metric_status_layout.count():
            item = self.metric_status_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        classes = self.settings.get("evaluationClasses", {}) or {}
        options = []
        if scheme_name and scheme_name in classes:
            options = classes[scheme_name].get("option_types", []) or []

        for o in options:
            rb = QRadioButton(str(o))
            self.metric_status_group.addButton(rb)
            self.metric_status_buttons[str(o)] = rb
            self.metric_status_layout.addWidget(rb)

        self.metric_status_layout.addStretch(1)

    def on_scheme_changed(self, scheme_name: str):
        self._build_metric_status_radios(scheme_name)

        # Attempt to restore current row's metric_status
        row = self.mid_manager.get_current_row() if hasattr(self, "mid_manager") else None 
        if row is not None:
            self._set_metric_status(row.get("metric_status", "") or "")

    def _safe_text(self, v) -> str:
        if v is None:
            return ""
        try:
            if pd.isna(v):
                return ""
        except Exception:
            pass

        return str(v)





    def _show_png_bytes_in_center(self, png_bytes: bytes):
        pm = QPixmap()
        pm.loadFromData(QByteArray(png_bytes), "PNG")
        # Use your existing central image widget here; QLabel is common:
        self.pdf_label.setPixmap(pm)
        self.pdf_label.adjustSize()

    def _get_selected_snippet(self) -> str:
        """
        Returns selected text from the scraped-text panel (self.text_edit).
        Normalizes Qt paragraph separators to '\n'.
        """
        if not hasattr(self, "text_edit") or self.text_edit is None:
            return ""
        cur = self.text_edit.textCursor()
        txt = cur.selectedText() or ""
        # QTextCursor.selectedText uses U+2029 for line breaks
        txt = txt.replace("\u2029", " ").strip()
        return txt

    def _fill_mid_field_from_selection(self, field_key: str):
        snippet = self._get_selected_snippet()
        if not snippet:
            self.statusBar().showMessage("No highlighted text to transfer.", 2000)
            return

        cleaned = self._extract_and_apply_status_label(snippet)

        self._set_text(field_key, cleaned)
        self._focus(field_key)


    def _fill_lineedit_from_selection(self, which: str):
        snippet = self._get_selected_snippet()
        if not snippet:
            self.statusBar().showMessage("No highlighted text to transfer.", 2000)
            return

        if which == "target" and hasattr(self, "target_edit"):
            self.target_edit.setText(snippet)
            self.target_edit.setFocus()
        elif which == "actual" and hasattr(self, "actual_edit"):
            self.actual_edit.setText(snippet)
            self.actual_edit.setFocus()

    def _trigger_add_level(self, level_key: str):
        """
        Ctrl+1..4 should behave like clicking the '+' button for that level.
        Uses the actual button if present (preferred), otherwise calls the handler.
        """
        # Preferred: click the real button you created next to the field
        btns = getattr(self, "add_level_buttons", None)
        if isinstance(btns, dict) and level_key in btns and btns[level_key] is not None:
            btns[level_key].click()
            return

        # Fallback: direct handler if you implemented it
        if hasattr(self, "on_add_level_clicked"):
            self.on_add_level_clicked(level_key)

    def _select_metric_status_by_index(self, idx: int):
        buttons = list(self.metric_status_buttons.values())
        if 0 <= idx < len(buttons):
            buttons[idx].setChecked(True)

    def _clear_metric_status(self):
        self.metric_status_group.setExclusive(False)
        for b in self.metric_status_buttons.values():
            b.setChecked(False)
        self.metric_status_group.setExclusive(True)



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
            bind(f"Ctrl+{i+1}", lambda i=i: self._select_metric_status_by_index(i))

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
        # Text transfer (your remap)
        # -------------------------
        bind("1", lambda: self._fill_mid_field_from_selection("stratobj"))
        bind("2", lambda: self._fill_mid_field_from_selection("obj"))
        bind("3", lambda: self._fill_mid_field_from_selection("goal"))
        bind("4", lambda: self._fill_mid_field_from_selection("metric"))

        bind("[", lambda: self._fill_lineedit_from_selection("target"))
        bind("]", lambda: self._fill_lineedit_from_selection("actual"))

        # -------------------------
        # '+' buttons (unchanged)
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
                if key in (Qt.Key_BracketLeft, Qt.Key_BracketRight, Qt.Key_Minus, Qt.Key_Equal):
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
            pattern = r"(?<!\S)" + re.escape(lab) + r"(?!\S)"  # surrounded by whitespace or ends
            m = re.search(pattern, s_norm)
            if not m:
                continue

            # Select the radio button
            rb = self.metric_status_buttons.get(label)
            if rb is not None:
                rb.setChecked(True)

            # Remove that occurrence of the label from the normalized string
            s_norm = (s_norm[:m.start()] + s_norm[m.end():]).strip()

            # Stop after the first match
            break

        # Clean up dangling punctuation at the ends (common when labels are at end)
        s_norm = s_norm.strip(" \t\r\n-–—:;,.()[]{}")

        return s_norm





if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TextScrapingReviewApp()
    window.show()
    sys.exit(app.exec_())
