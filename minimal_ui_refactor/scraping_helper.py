import base64
import json
import os
import re
import sys
from io import BytesIO

import fitz  # PyMuPDF
import pandas as pd
from PyQt5.QtCore import QEvent, QProcess, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
)

from app_settings import (
    checkbox_columns,
    load_settings,
    normalize_checkboxes,
    normalize_field_buttons,
    save_settings,
)
from audit_runner import run_mid_audit
from document_session import DocumentSession
from extractor_loader import select_extractor_class
from logger import setup_logger
from mid_manager import MIDManager
from mid_schema import LEGACY_HIERARCHY_COLUMNS, MIDSchema
from scraper_loader import select_scraper_class
import field_formula
import module_settings
from ui import (
    CounterSpec,
    FieldButtonSpec,
    FieldSpec,
    InfoSpec,
    MainWindowUI,
    ToggleSpec,
    UIContext,
)
from ui.widgets import fitz_pixmap_to_qpixmap, pil_to_qpixmap

# local imports
from settings_window import SettingsDialog

# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.dirname(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

BASE_WIDTH = 1200
BASE_HEIGHT = 800

#: Restriction choices the app answers itself rather than from an audit report.
LIVE_RESTRICTIONS = ("same_document", "duplicate_observation")

#: Command-line flag carrying the MID row to reopen on after a restart.
RESUME_FLAG = "--resume-index"

# TextScrapingReviewApp


class TextScrapingReviewApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = setup_logger()
        self.logger.info("Initialized Logger")
        self.setWindowTitle("Text Scraping Review App")
        #        self.resize(1200, 800)

        self.settings = load_settings()
        self.mid_schema = MIDSchema.from_settings(self.settings)
        # Checkboxes are user-defined; their columns are created if the MID
        # does not already have them.
        self.checkbox_specs = normalize_checkboxes(self.settings.get("checkboxes"))
        # Buttons that compute one editable field from the others.
        self.field_button_specs = normalize_field_buttons(
            self.settings.get("fieldButtons")
        )

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
                self.mid_manager = MIDManager(
                    mid_path,
                    sheet_name=self.settings.get("MIDSheetName", 0),
                    schema=self.mid_schema,
                    boolean_columns=self.checkbox_column_names(),
                )

            except Exception as e:
                self.logger.error(f"Failed to Load MID: {e}")
                QMessageBox.critical(
                    self,
                    "MID Load Failed",
                    f"The configured MID could not be loaded:\n\n{e}",
                )
        else:
            self.logger.warning("MID Location not specified, user alerted")
            # Notfiy the user via popup if the MID cannot be loaded
            # NOTE: This still executes at first launch, which is proabably bad form
            QMessageBox.warning(
                self,
                "MID Location not Specified",
                "Please select a Master Input Document in Settings.",
            )

        # Every row pointing at the same document and page range shares one
        # session, so the open PDF and its scraped text are not per-row state.
        self.document_session = None
        self.current_page_index = 0  # Index of current page, not page number
        self.current_document_key = None
        self.current_observation_label = ""
        self.current_observation_stem = "observation"
        self.current_document_name = ""

        self.manual_review = {  # Structure for tracking user Accept/Rejects (will likely be changed)
            "active_test": None,
            "results": {},  # format: {row_index: {"status": "ACCEPT" or "REJECT", "label": ..., "pages": [...]}}
        }
        self.mid_field_keys = list(self.mid_schema.interaction_columns)

        loaded_columns = (
            self.mid_manager.df.columns if hasattr(self, "mid_manager") else []
        )
        self.legacy_hierarchy_enabled = (
            self.mid_schema.is_legacy_hierarchy_compatible(loaded_columns)
            and set(LEGACY_HIERARCHY_COLUMNS).issubset(self.mid_field_keys)
        )

        self.expansion_state = {
            "base_level": None,  # lowest present on the seed row (stratobj|obj|goal|metric|None)
            "working_level": None,  # where the user is currently adding units
            "seed_index": None,  # index of the original (non-generated) row we started from
        }

        # coords from the most recent scrape (overlays live on the session)
        self.cells_by_page = {}  # {page_index: [(x0,y0,x1,y1), ...]} (for later click-to-scrape)
        self.page_dims = {}  # {page_index: (w_pt, h_pt)}         (for later)

        # Set up file structure if it doesn't exist
        self.init_files()

        self.ui = MainWindowUI(
            self, self.build_ui_context(), self.resolved_module_settings()
        )
        self.ui.setup()
        self.installEventFilter(self)
        self.remember_loaded_modules()

        # Reopen where a restart left off, if we were told to.
        self.restore_resume_index()

        # Attempt to load the first document
        if hasattr(self, "mid_manager") and self.mid_manager.df is not None:
            success = self.load_mid_entry_document()
            if not success:
                self.logger.warning(
                    "First MID row failed to load; check file accessibility or page numbers."
                )
            else:
                self.logger.debug("First MID row loaded successfully")

    # ------------------------------------------------------------------
    # Current document
    # ------------------------------------------------------------------
    @property
    def page_indices(self):
        """Zero-based PDF pages the current session covers."""
        return self.document_session.page_indices if self.document_session else []

    @property
    def content_format(self):
        return self.document_session.content_format if self.document_session else ""

    @property
    def current_scrape_result(self):
        return self.document_session.scrape_result if self.document_session else {}

    def current_page_number(self):
        """The one-based page number to record against the current row."""
        if self.document_session:
            return self.document_session.display_page_number(self.current_page_index)
        return self.current_page_index + 1

    # ------------------------------------------------------------------
    # Module settings
    # ------------------------------------------------------------------
    def resolved_module_settings(self):
        """Effective values for every module the program knows about."""
        return {
            module_id: module_settings.resolve(self.settings, module_id)
            for module_id in module_settings.registered_modules()
        }

    def remember_loaded_modules(self):
        """Record the modules on screen so the settings file keeps their values."""
        changed = False
        for module_id in self.ui.active_module_ids():
            changed |= module_settings.remember(self.settings, module_id)
        if changed:
            save_settings(self.settings)
            self.logger.info("Recorded module settings for the loaded modules")

    # ------------------------------------------------------------------
    # Restart
    # ------------------------------------------------------------------
    def has_unsaved_changes(self) -> bool:
        manager = getattr(self, "mid_manager", None)
        return bool(manager is not None and manager.is_modified())

    def restart_application(self):
        """Relaunch, reopening on the row the user is looking at now."""
        self._commit_sidebar_fields()

        if self.has_unsaved_changes():
            choice = QMessageBox.question(
                self,
                "Unsaved Changes",
                "This MID has changes that have not been written to a file.\n\n"
                "Save before restarting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if choice == QMessageBox.Cancel:
                self.logger.info("Restart cancelled by user")
                return
            if choice == QMessageBox.Save and not self.save_mid_to_file():
                # The save was cancelled or failed; do not lose the work.
                self.logger.info("Restart abandoned: MID was not saved")
                return

        resume_index = getattr(getattr(self, "mid_manager", None), "current_index", 0)
        if not self.relaunch(resume_index):
            QMessageBox.critical(
                self, "Restart", "The application could not be relaunched."
            )
            return

        self.logger.info(f"Restarting at MID index {resume_index}")
        QApplication.quit()

    def relaunch(self, resume_index) -> bool:
        """Start a fresh copy of this program, told where to resume."""
        program, arguments = self.relaunch_command(resume_index)
        self.logger.debug(f"Relaunching: {program} {arguments}")
        return QProcess.startDetached(program, arguments)

    @staticmethod
    def relaunch_command(resume_index):
        """The command that starts this program again.

        A frozen build is its own executable; otherwise the interpreter runs
        the same script. Any resume flag already present is replaced so the
        arguments do not grow with each restart.
        """
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, list(sys.argv[1:])
        else:
            program, arguments = sys.executable, list(sys.argv)

        cleaned = []
        skip_next = False
        for argument in arguments:
            if skip_next:
                skip_next = False
                continue
            if argument == RESUME_FLAG:
                skip_next = True
                continue
            if argument.startswith(f"{RESUME_FLAG}="):
                continue
            cleaned.append(argument)

        cleaned.extend([RESUME_FLAG, str(int(resume_index or 0))])
        return program, cleaned

    @staticmethod
    def resume_index_from_arguments(arguments=None):
        """Read the resume position out of the command line, if present."""
        arguments = list(sys.argv if arguments is None else arguments)
        for position, argument in enumerate(arguments):
            value = None
            if argument == RESUME_FLAG and position + 1 < len(arguments):
                value = arguments[position + 1]
            elif argument.startswith(f"{RESUME_FLAG}="):
                value = argument.split("=", 1)[1]
            if value is not None:
                try:
                    return max(0, int(value))
                except ValueError:
                    return None
        return None

    def restore_resume_index(self):
        """Move to the row a previous run was on, if this run was restarted."""
        resume_index = self.resume_index_from_arguments()
        manager = getattr(self, "mid_manager", None)
        if resume_index is None or manager is None or manager.df is None:
            return

        if 0 <= resume_index < len(manager.view_indices):
            manager.current_index = resume_index
            self.logger.info(f"Resumed at MID index {resume_index}")
        else:
            self.logger.warning(
                f"Cannot resume at MID index {resume_index}; it is out of range"
            )

    def get_screen_scale(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return 1.0

        size = screen.availableGeometry()
        width_scale = size.width() / BASE_WIDTH
        height_scale = size.height() / BASE_HEIGHT

        return min(width_scale, height_scale, 1.0)

    def scaled(self, value, scale):
        return int(round(value * scale))

    # ------------------------------------------------------------------
    # UI description
    # ------------------------------------------------------------------
    def build_ui_context(self):
        """Describe the window the UI layer should build.

        This is the only place that translates MID vocabulary into UI terms;
        the ``ui`` package knows nothing about schemas or DataFrames.
        """
        fields = tuple(
            FieldSpec(
                key=key,
                label=key.replace("_", " ").strip().title(),
                expandable=(
                    self.legacy_hierarchy_enabled and key in LEGACY_HIERARCHY_COLUMNS
                ),
            )
            for key in self.mid_field_keys
        )
        # Identifiers the user edits are shown as fields, not as read-only info.
        info = [
            InfoSpec(role, column.replace("_", " ").title())
            for role, column in (
                ("x", self.mid_schema.x_column),
                ("y", self.mid_schema.y_column),
            )
            if column and column not in self.mid_field_keys
        ]
        info.append(InfoSpec("document", "Document"))
        info.append(InfoSpec("observation", "Observation"))
        info.append(InfoSpec("page", "Page"))
        if self.mid_schema.format_column:
            info.append(InfoSpec("format", "Format"))
        info = tuple(info)
        return UIContext(
            mode=self.mode,
            fields=fields,
            toggles=self.toggle_specs(),
            field_buttons=self.field_button_specs_for_ui(),
            info=info,
            restriction_options=self.restriction_options(),
            evaluation_classes=self.settings.get("evaluationClasses", {}) or {},
            default_class=self.settings.get("defaultClass", ""),
        )

    def checkbox_column_names(self):
        """Every MID column the configured checkboxes read or write."""
        return checkbox_columns(self.checkbox_specs)

    def toggle_specs(self):
        """The checkbox definitions as the UI wants to see them."""
        return tuple(
            ToggleSpec(
                key=definition["key"],
                label=definition["label"],
                shortcut=definition["shortcut"],
                counter=(
                    CounterSpec(
                        key=definition["key"],
                        label=definition["counter"]["label"],
                        minimum=definition["counter"]["minimum"],
                        maximum=definition["counter"]["maximum"],
                    )
                    if definition["counter"]
                    else None
                ),
            )
            for definition in self.checkbox_specs
        )

    def field_button_specs_for_ui(self):
        """The computed buttons whose target is an editable field."""
        specs = []
        for definition in self.field_button_specs:
            if definition["target"] not in self.mid_field_keys:
                self.logger.warning(
                    f"Button '{definition['label']}' targets "
                    f"'{definition['target']}', which is not an editable field"
                )
                continue
            specs.append(
                FieldButtonSpec(
                    key=definition["key"],
                    label=definition["label"],
                    target=definition["target"],
                    tooltip=definition["tooltip"],
                )
            )
        return tuple(specs)

    def restriction_options(self):
        """Values offered by the "Restrict to:" selector in the current mode."""
        mode = self.mode.lower()
        if mode == "dev":
            options = [
                "table_detected",
                "text_scraped",
                *[f"field:{column}" for column in self.mid_field_keys],
            ]
            if self.mid_schema.keyword_column:
                options.append("keyword_match")
            options.extend(
                [
                    "pages_parsed",
                    "pdf_found",
                    "_flag",
                    "no_status",
                    "no_t/a",
                    *LIVE_RESTRICTIONS,
                    "none",
                ]
            )
            return options
        if mode == "reviewer":
            return [
                "_flag",
                "_gen",
                "rejected",
                "no_status",
                "no_t/a",
                *LIVE_RESTRICTIONS,
                "none",
            ]
        return []

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

    # Update read-only information for user
    # Update read-only information for user
    # Update read-only information for user
    def update_info_labels(self):
        self.logger.debug("Updating info labels")
        row = self.mid_manager.get_current_row()
        if row is None:
            return

        x_value, y_value = self.mid_schema.observation_key(row)
        ordinal, total = self.mid_manager.document_position()

        self.ui.set_entry_position(
            self.mid_manager.current_index + 1, len(self.mid_manager.view_indices)
        )
        self.ui.set_info_values(
            {
                "x": x_value,
                "y": y_value,
                "document": self.current_document_name or "N/A",
                "observation": f"{ordinal} of {total} in this document",
                "page": self.current_page_number(),
                "format": self.mid_manager.format_type(default=""),
            }
        )
        self.refresh_duplicate_warning()

    def refresh_duplicate_warning(self):
        """Tell the user when this row's identity collides with another."""
        if self.mid_manager.is_duplicate_observation():
            self.ui.set_warning(
                "Another row records the same document and identifiers. "
                'Use "Restrict to: duplicate_observation" to review them.'
            )
        else:
            self.ui.set_warning("")

    def update_mode_ui(self):
        mode = self.mode.lower()
        self.logger.info(f"updating UI for {mode} mode")
        self.ui.apply_mode(mode)

    def load_mid_entry_document(self):
        row = self.mid_manager.get_current_row()
        if row is None:
            self.logger.error("No MID row found")
            return False

        label = self.mid_schema.observation_label(row)
        self.current_observation_label = label
        self.current_observation_stem = self.mid_schema.observation_stem(row)

        # The document, not the X/Y pair, decides whether we are still looking
        # at the same thing. X/Y may be blank until the user assigns them.
        document_key = self.mid_schema.document_key(row)
        if self.current_document_key != document_key:
            self.current_page_index = 0
        self.current_document_key = document_key

        path = self._resolve_document_path(label)
        if not path:
            return False

        # With no page-reference column the whole document is in scope; the
        # session resolves that once it knows the page count.
        page_indices = None
        if self.mid_schema.page_column:
            page_indices = self.mid_manager.parse_pdf_pages()
            if not page_indices:
                self.logger.error(
                    f"No valid pages found for {label} using page column "
                    f"'{self.mid_schema.page_column}'"
                )
                return False

        self.current_document_name = os.path.basename(path)

        if not self._open_document_session(path, page_indices, label):
            return False

        self._focus_page_from_row(row, label)
        self._present_scraped_content()

        self.show_page()
        self.load_mid_fields_from_row()
        self.ui.refresh_highlights()
        return True

    def _resolve_document_path(self, label):
        """Locate the file this row names, or report why we cannot."""
        candidates = self.mid_manager.document_candidates()
        if not candidates:
            self.logger.error(f"MID row {label} does not name a document")
            return ""

        data_directory = self.settings.get("dataDirectory", "")
        path = next(
            (
                os.path.join(data_directory, filename)
                for filename in candidates
                if os.path.isfile(os.path.join(data_directory, filename))
            ),
            "",
        )
        if not path:
            self.logger.error(
                f"PDF not found for MID row {label}; tried: {list(candidates)}"
            )
        return path

    def _open_document_session(self, path, page_indices, label):
        """Reuse the open session when this row covers the same pages."""
        session = self.document_session
        if session is not None and session.matches(path, page_indices):
            self.logger.debug(f"Reusing open session for {path}")
            return True

        if session is not None:
            session.close()
            self.document_session = None

        try:
            session = DocumentSession(
                path, self.current_document_key, page_indices, logger=self.logger
            )
        except Exception as e:
            self.logger.error(f"Error loading {path} for {label}: {e}")
            return False

        self.document_session = session

        try:
            format_type = self.mid_manager.format_type()
            session.scrape(select_scraper_class(self.settings, format_type))
            self.logger.info("got scraper result!")
        except Exception as e:
            self.logger.error(f"Failed to scrape all pages for {label}: {e}")
            session.reset_content()

        return True

    def _focus_page_from_row(self, row, label):
        """Honour this row's Page field within the shared session."""
        session = self.document_session
        focus_page = row.get("Page", None)
        if focus_page in (None, "") or session is None:
            if not session or not session.has_page(self.current_page_index):
                self.current_page_index = 0
            return

        try:
            page_number = int(focus_page)
        except (TypeError, ValueError):
            self.logger.warning(
                f"Invalid Page field in MID for {label}: '{focus_page}'"
            )
            self.current_page_index = 0
            return

        if page_number - 1 in session.page_indices:
            self.current_page_index = session.page_indices.index(page_number - 1)
            self.logger.info(
                f"Set current page index to {self.current_page_index} "
                "based on MID Page field"
            )
        elif not session.has_page(self.current_page_index):
            self.current_page_index = 0

    def _present_scraped_content(self):
        """Show the session's content in the centre and right panes."""
        session = self.document_session
        if session is None:
            return

        if session.content_format == "image":
            self.logger.debug("using image format")
            qpix = pil_to_qpixmap(session.table_image_at(self.current_page_index))
            if qpix is not None:
                self.ui.show_canvas_image(
                    qpix, meta={"page": self.current_page_index, "table": 0}
                )
            self.ui.clear_content()
        else:
            self.logger.debug("showing scraped text panel")
            self.ui.set_content(session.text_at(self.current_page_index))

    def show_page(self):
        self.logger.debug("Attempting to display a new document page")
        session = self.document_session
        if session is None:
            self.logger.warning("Could not load document!")
            return

        overlay_png = session.overlay_at(self.current_page_index)
        if overlay_png:
            self.ui.show_page_png(overlay_png)
            self.update_info_labels()  # keep your normal UI refresh
            return

        self.logger.debug(
            f"Attempting to load index {self.current_page_index}, "
            f"page {session.page_number(self.current_page_index)}"
        )
        self.ui.show_page_pixmap(
            fitz_pixmap_to_qpixmap(session.render_page(self.current_page_index))
        )

        if session.has_page(self.current_page_index):
            self.ui.set_content(session.text_at(self.current_page_index))
            self.ui.refresh_highlights()
        else:
            self.ui.clear_content()

        # Display document information
        self.update_info_labels()

    def resizeEvent(self, event):
        self.logger.debug("Window resized")
        super().resizeEvent(event)
        self.show_page()

    # Advances to next page and scrapes it
    # Advances to next page and scrapes it
    def next_page(self):
        self.logger.debug("Attempting to load next page")
        session = self.document_session
        if session and self.current_page_index < len(session) - 1:
            session.set_text(self.current_page_index, self.ui.content())
            self.logger.debug("Next page is valid")
            self.current_page_index += 1
            self.show_page()
        else:
            self.logger.warning("Attempted to load invalid page")

    # Moves to previous page and attempts to scrape it
    def prev_page(self):
        self.logger.debug("Attempting to load previous page")
        session = self.document_session
        if session and self.current_page_index > 0:
            session.set_text(self.current_page_index, self.ui.content())
            self.logger.debug("Previous page is valid")
            self.current_page_index -= 1
            self.show_page()
        else:
            self.logger.warning("Attempted to load invalid page")

    def accept_scrape(self):
        if self.mode == "dev":
            if self.manual_review["active_test"]:
                idx = self.mid_manager.current_index
                row = self.mid_manager.get_current_row()
                pages = (
                    [self.document_session.page_number(self.current_page_index)]
                    if self.document_session
                    else []
                )
                self.manual_review["results"][idx] = {
                    "status": "ACCEPT",
                    "label": self.mid_schema.observation_label(row),
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
                observation_label = self.mid_schema.observation_label(row)
                notes = self.ui.reviewer_notes_text()
                review_record = {
                    "status": "ACCEPT",
                    "label": observation_label,
                    "notes": notes,
                }
                self.logger.info(
                    f"Reviewer accepted row {idx} ({observation_label}) with notes: {notes}"
                )
                self.mid_manager.set_value(idx, "reviewer_status", "ACCEPT")
                # Here you would typically save the review_record to a database or file.

        # User is in User mode
        else:
            if self.document_session:
                output_path = os.path.join(
                    self.accept_dir, f"{self.current_observation_stem}_full.txt"
                )
                with open(output_path, "w", encoding="utf-8") as f:
                    # use the session text so manual edits are included
                    f.write(self.document_session.full_text())
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
                    [self.document_session.page_number(self.current_page_index)]
                    if self.document_session
                    else []
                )
                self.manual_review["results"][idx] = {
                    "status": "REJECT",
                    "label": self.mid_schema.observation_label(row),
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
                observation_label = self.mid_schema.observation_label(row)
                notes = self.ui.reviewer_notes_text()
                review_record = {
                    "status": "REJECT",
                    "label": observation_label,
                    "notes": notes,
                }
                self.ui.set_toggle("flag", True)
                self.logger.info(
                    f"Reviewer rejected row {idx} ({observation_label}) with notes: {notes}"
                )
                # Here you would typically save the review_record to a database or file.
                self.mid_manager.set_value(idx, "reviewer_status", "REJECT")
            self.next_mid_entry()
        # User Mode:
        else:
            if self.document_session:
                output_path = os.path.join(
                    self.reject_dir, f"{self.current_observation_stem}_full.txt"
                )
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(self.document_session.full_text())
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

    # Record another observation taken from the document already on screen
    def add_observation_from_document(self):
        self._commit_sidebar_fields()
        idx = self.mid_manager.current_index
        if idx is None or self.mid_manager.get_current_row() is None:
            self.logger.error("No MID row to add an observation to")
            return

        new_row = self.mid_manager.clone_for_document(idx)
        if not new_row:
            return

        # Start the new observation on the page the user is looking at.
        new_row["Page"] = self.current_page_number()

        new_idx = self.mid_manager.insert_row_after(idx, new_row)
        self.logger.info(
            f"Added observation on {self.current_document_key} at row {new_idx}"
        )
        self.mid_manager.current_index = new_idx
        self.load_mid_entry_document()
        self.update_info_labels()

        first_field = next(iter(self.mid_field_keys), "")
        if first_field:
            self.ui.focus_field(first_field)

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
            format_type = self.mid_manager.format_type()
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
        old_sheet_name = self.settings.get("MIDSheetName", 0)
        old_schema_mapping = self.mid_schema.to_mapping()
        old_checkboxes = list(self.checkbox_specs)
        old_buttons = list(self.field_button_specs)
        if hasattr(self, "mid_manager"):
            old_mid_df = self.mid_manager.df
        else:
            old_mid_df = None

        old_modules = self.resolved_module_settings()
        dialog = SettingsDialog(
            self.settings,
            self,
            active_modules=self.ui.active_module_ids(),
            mode=self.mode,
        )

        # Save new settings from user's inputs
        if dialog.exec_() == QDialog.Accepted:
            self.logger.info("User updated settings in-app")
            self.settings = dialog.settings
            self._apply_scheme_settings()
            save_settings(self.settings)
            self.mode = self.settings.get("userMode", "User")
            self.update_mode_ui()

            # Module settings take effect immediately; no restart needed.
            new_modules = self.resolved_module_settings()
            if new_modules != old_modules:
                self.ui.apply_module_settings(new_modules)
                self.logger.info("Applied updated module settings")

            new_mid_path = self.settings.get("MIDLocation", "")
            new_sheet_name = self.settings.get("MIDSheetName", 0)
            new_schema = MIDSchema.from_settings(self.settings)
            new_checkboxes = normalize_checkboxes(self.settings.get("checkboxes"))
            new_buttons = normalize_field_buttons(self.settings.get("fieldButtons"))

            old_mid_path = old_mid_path or ""
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
            schema_changed = new_schema.to_mapping() != old_schema_mapping
            checkboxes_changed = new_checkboxes != old_checkboxes
            buttons_changed = new_buttons != old_buttons

            if schema_changed or checkboxes_changed or buttons_changed:
                if schema_changed:
                    changed = "MID column"
                elif checkboxes_changed:
                    changed = "checkbox"
                else:
                    changed = "button"
                QMessageBox.information(
                    self,
                    "Restart Required",
                    f"The {changed} configuration was saved. Restart the "
                    "application to rebuild the sidebar with it.",
                )
                self.logger.info(f"{changed} configuration changed; restart required")
                return

            if mid_changed:
                self.logger.info("MID location/sheet changed; reloading MID")

                try:
                    # Reconstruct only when necessary
                    self.mid_manager = MIDManager(
                        new_mid_path,
                        sheet_name=new_sheet_name,
                        schema=new_schema,
                        boolean_columns=self.checkbox_column_names(),
                    )

                    QMessageBox.information(
                        self,
                        "MID Reloaded",
                        "Master Input Document Loaded Successfully",
                    )

                    sample_columns = list(
                        dict.fromkeys(
                            column
                            for column in (
                                new_schema.document_column,
                                *new_schema.identifier_columns,
                                *new_schema.interaction_columns[:3],
                            )
                            if column
                        )
                    )
                    identity_lines = "".join(
                        f"{role} values ({column}): "
                        f"{self.mid_manager.df[column].nunique():,}\n"
                        for role, column in (
                            ("X", new_schema.x_column),
                            ("Y", new_schema.y_column),
                        )
                        if column
                    )
                    summary = (
                        f"MID loaded successfully.\n\n"
                        f"Rows: {len(self.mid_manager.df):,}\n"
                        f"Columns: {len(self.mid_manager.df.columns)}\n"
                        f"{identity_lines}"
                        f"\nSample rows:\n"
                        f"{self.mid_manager.df[sample_columns].head().to_string(index=False)}"
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
    # basic handler for the failure loading function below
    def handle_load_failures(self):
        test_name = self.ui.restriction_choice()

        # These two are answered from the MID itself, so they need no audit run
        # and behave the same in every mode.
        if test_name in LIVE_RESTRICTIONS:
            self.restrict_to_live_selection(test_name)
            return

        if self.mode.lower() == "dev":
            self.load_audit_failures(test_name)
        elif self.mode.lower() == "reviewer":
            self.restrict_for_reviewer(test_name)

    def restrict_to_live_selection(self, test_name: str):
        """Restrict the view using state the MID already knows."""
        if test_name == "same_document":
            positions = self.mid_manager.document_row_positions()
            empty_message = "This document has no other rows."
        else:
            positions = self.mid_manager.duplicate_observation_positions()
            empty_message = "No rows share an observation identity."

        if not positions:
            QMessageBox.information(self, "No Matches", empty_message)
            return

        self.mid_manager.restrict_to_rows(positions)
        self.logger.info(
            f"Restriction applied: {len(positions)} rows matched '{test_name}'"
        )
        self.manual_review["active_test"] = test_name
        self.manual_review["results"] = {}
        self.load_mid_entry_document()
        self.update_info_labels()

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
                audit_payload = json.load(f)
            audit_results = (
                audit_payload.get("results", [])
                if isinstance(audit_payload, dict)
                else audit_payload
            )

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

    def save_mid_to_file(self) -> bool:
        """Write the MID out. Returns whether it was actually saved."""
        # Commit current editors first
        self._commit_sidebar_fields()

        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            QMessageBox.warning(self, "Save MID", "No MID loaded.")
            return False

        path, _ = QFileDialog.getSaveFileName(
            self, "Save MID", "mid_export.xlsx", "Excel Workbook (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return False

        df_to_save = getattr(self.mid_manager, "master_df", None)
        if df_to_save is None:
            df_to_save = self.mid_manager.df

        try:
            if path.lower().endswith(".csv"):
                df_to_save.to_csv(path, index=False)
            else:
                # default to Excel
                with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
                    df_to_save.to_excel(xw, index=False, sheet_name="MID")
        except Exception as e:
            QMessageBox.critical(self, "Save MID", f"Failed to save:\n{e}")
            return False

        self.mid_manager.mark_saved()
        self.statusBar().showMessage(f"Saved MID to {path}")
        self.logger.info(f"Saved MID to {path}")
        return True

    # Primary function for saving current editor state into the MID
    def _commit_sidebar_fields(self):
        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            return
        # set_value converts view->master, so the view index is what we pass.
        idx = self.mid_manager.current_index
        if idx is None:
            return

        for key, value in self.ui.field_texts().items():
            self.mid_manager.set_value(idx, key, value)

        toggles = self.ui.toggles()
        counters = self.ui.counters()
        for definition in self.checkbox_specs:
            key = definition["key"]
            checked = bool(toggles.get(key, False))
            self.mid_manager.set_value(idx, definition["column"], checked)

            counter = definition["counter"]
            if counter:
                value = int(counters.get(key, 0) or 0)
                # A counter only means something while its checkbox is ticked.
                self.mid_manager.set_value(
                    idx, counter["column"], str(value) if checked and value else ""
                )

        self.logger.info(f"Saved information for {self.current_observation_label}: ")

        self.mid_manager.set_value(
            idx, "classification_scheme", self._safe_text(self.ui.scheme_name()).strip()
        )
        self.mid_manager.set_value(
            idx, "metric_status", self._safe_text(self.ui.metric_status())
        )
        self.mid_manager.set_value(idx, "notes", self.ui.notes_text())
        self.mid_manager.set_value(idx, "Page", self.current_page_number())

        if self.mode.lower() == "reviewer":
            self.mid_manager.set_value(
                idx, "reviewer_comments", self.ui.reviewer_notes_text()
            )
            if self.mid_manager.df.at[idx, "reviewer_status"] not in [
                "ACCEPT",
                "REJECT",
            ]:
                self.mid_manager.set_value(idx, "reviewer_status", "SEEN")

    def _goto_index(self, new_idx: int):
        """Move to a MID row and refresh everything the sidebar shows."""
        self.mid_manager.current_index = new_idx
        self.update_info_labels()
        self.load_mid_fields_from_row()

    def _levels_to_clear(self, level_key: str) -> list[str]:
        order = ["stratobj", "obj", "goal", "metric"]
        if level_key not in order:
            return []
        return order[order.index(level_key) :]

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
            self.ui.set_field_text(k, "")
        if "metric" in to_clear:
            self.ui.set_metric_status("")
        self.ui.focus_field(level_key)

    # --- Button slots ---

    def load_mid_fields_from_row(self):
        """Present the current MID row in the sidebar."""
        manager = getattr(self, "mid_manager", None)
        row = manager.get_current_row() if manager is not None else None
        if row is None:
            self.ui.clear_fields()
            self.ui.set_metric_status("")
            return

        idx = manager.current_index
        toggles = {}
        counters = {}
        for definition in self.checkbox_specs:
            key = definition["key"]
            toggles[key] = bool(manager.df.at[idx, definition["column"]])
            if definition["counter"]:
                counters[key] = self._as_int(row.get(definition["counter"]["column"]))

        self.ui.set_toggles(toggles)
        self.ui.set_counters(counters)
        for key in counters:
            # A counter is only editable while its checkbox is ticked.
            self.ui.set_counter_enabled(key, toggles.get(key, False))

        self.ui.set_notes_text(self._safe_text(row.get("notes", "")))
        self.ui.set_reviewer_notes_text(
            self._safe_text(row.get("reviewer_comments", ""))
        )
        self.ui.set_field_texts({key: row.get(key, "") for key in self.mid_field_keys})

        classes = self.settings.get("evaluationClasses", {}) or {}
        scheme = self._safe_text(row.get("classification_scheme", "")).strip()
        if scheme and scheme in classes:
            self.ui.set_scheme(scheme)
        elif scheme == "" and self.ui.scheme_name() in classes:
            pass  # keep whatever the user last selected
        else:
            default_name = self.settings.get("defaultClass", "")
            if default_name in classes:
                self.ui.set_scheme(default_name)

        self.ui.set_metric_status(self._safe_text(row.get("metric_status", "")))

    def _as_int(self, value) -> int:
        try:
            text = self._safe_text(value).strip()
            return int(text) if text else 0
        except ValueError:
            return 0

    def on_field_button_clicked(self, key: str):
        """Compute one editable field from the others and write it in."""
        definition = next(
            (item for item in self.field_button_specs if item["key"] == key), None
        )
        if definition is None:
            self.logger.error(f"No button definition for '{key}'")
            return

        values = field_formula.field_values(self.ui.field_texts())
        try:
            result = field_formula.evaluate(definition["expression"], values)
        except field_formula.FormulaError as exc:
            # Usually a field that is still empty; tell the user, do not crash.
            self.logger.warning(f"Button '{definition['label']}' failed: {exc}")
            self.ui.set_status_message(f"{definition['label']}: {exc}", 5000)
            return

        text = field_formula.format_result(result, definition["decimals"])
        self.ui.set_field_text(definition["target"], text)
        self.ui.set_status_message(
            f"{definition['target']} = {text}  ({definition['expression']})", 4000
        )
        self.ui.refresh_highlights()

    def on_toggle_changed(self, key: str, checked: bool):
        """React to any sidebar checkbox. The UI owns dependent widget state."""
        message = next(
            (
                definition["message"]
                for definition in self.checkbox_specs
                if definition["key"] == key
            ),
            "",
        )
        if message:
            self.ui.set_status_message(message)
        self.update_info_labels()

    def on_counter_changed(self, key: str, value: int):
        self.update_info_labels()

    def _apply_scheme_settings(self):
        """Push the configured classification schemes into the sidebar."""
        self.ui.set_scheme_options(
            self.settings.get("evaluationClasses", {}) or {},
            self.settings.get("defaultClass", ""),
        )

    def on_scheme_changed(self, scheme_name: str):
        # The sidebar has already rebuilt its options; restore the row's value.
        row = (
            self.mid_manager.get_current_row() if hasattr(self, "mid_manager") else None
        )
        if row is not None:
            self.ui.set_metric_status(self._safe_text(row.get("metric_status", "")))

    def _safe_text(self, v) -> str:
        if v is None:
            return ""
        try:
            if pd.isna(v):
                return ""
        except Exception:
            pass

        return str(v)

    def on_content_transfer(self, target_key: str, text: str):
        """Move a selection from the right-hand panel into a sidebar field.

        Called for both the transfer shortcuts and the panel's context menu.
        """
        if target_key not in self.mid_field_keys:
            self.logger.warning(f"Unknown content transfer target '{target_key}'")
            return

        self.ui.set_field_text(target_key, self._extract_and_apply_status_label(text))
        self.ui.focus_field(target_key)

    def eventFilter(self, obj, event):
        """Stop single-key shortcuts from also being typed into a field."""
        if event.type() == QEvent.KeyPress:
            if (
                event.modifiers() == Qt.NoModifier
                and event.text() in self.ui.reserved_plain_keys()
            ):
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                return True
        return super().eventFilter(obj, event)

    def _extract_and_apply_status_label(self, snippet: str) -> str:
        """
        If snippet contains a classification label, select that radio and remove the label text
        from the snippet. Returns cleaned snippet.
        """
        labels = self.ui.metric_status_labels()
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

            self.ui.set_metric_status(label)

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
