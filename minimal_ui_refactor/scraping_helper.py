import json
import os
import sys

import fitz  # PyMuPDF
import pandas as pd
from PyQt5.QtCore import QEvent, QProcess, Qt, QTimer
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
from document_session import DocumentSession, DocumentSessionCache
from document_text import (
    SEARCH_ANYWHERE,
    SEARCH_IN_RANGE,
    SEARCH_LIMIT,
    DocumentIndex,
    DocumentIndexCache,
)
from logger import setup_logger
from mid_manager import MIDManager
from mid_schema import MIDSchema
import paths
import session_metrics
from session_metrics import SessionMetrics
from statistics_dialog import REFRESH_MILLISECONDS, StatisticsDialog
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

#: Restriction choices answered from the MID's own state, in every mode.
LIVE_RESTRICTIONS = ("same_document", "duplicate_observation")

#: Restriction choices answered from one MID column, in every mode.
COLUMN_RESTRICTIONS = ("_flag", "_gen", "rejected")

#: The choice that lifts a restriction.
NO_RESTRICTION = "none"

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
        # Built before the MID loads, so the session clock starts at the
        # moment the window did rather than when the first row appeared.
        self.metrics = SessionMetrics()
        self.statistics_timer = None
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
        self.current_mid_index = 0

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
        # Recently-used documents, so stepping back to one does not re-scrape
        # it, and their search indexes, so it is not re-read either.
        self.session_cache = DocumentSessionCache()
        self.index_cache = DocumentIndexCache()
        self.current_page_index = 0  # Index of current page, not page number
        self.current_document_key = None
        self.current_observation_label = ""
        self.current_observation_stem = "observation"
        self.current_document_name = ""
        # True while a row is being presented in the sidebar. Widgets that
        # slip a signal through while they are being filled in must not be
        # mistaken for the user typing.
        self._loading_entry = False

        self.mid_field_keys = list(self.mid_schema.interaction_columns)

        # Set up file structure if it doesn't exist
        self.init_files()

        self.ui = MainWindowUI(
            self, self.build_ui_context(), self.resolved_module_settings()
        )
        self.ui.setup()
        self.installEventFilter(self)
        self.remember_loaded_modules()
        self.apply_statistics_settings()

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
    # Session statistics
    # ------------------------------------------------------------------
    def open_statistics(self):
        """Show every metric for this session, read-only."""
        self.refresh_statistics()
        StatisticsDialog(self.metrics, self).exec_()

    def pinned_statistic_keys(self):
        """Which metrics the user has asked to see on the main window."""
        return session_metrics.normalize_metric_keys(
            self.settings.get("statisticsOnMainWindow", [])
        )

    def apply_statistics_settings(self):
        """Rebuild the sidebar's statistics block from the current settings.

        Called at start-up and again whenever Settings closes, so pinning a
        metric takes effect immediately rather than at the next restart.
        """
        keys = self.pinned_statistic_keys()
        self.ui.set_statistic_specs(
            [(key, session_metrics.METRICS_BY_KEY[key].label) for key in keys]
        )

        # The clock only needs to tick while something is showing it.
        if keys:
            if self.statistics_timer is None:
                self.statistics_timer = QTimer(self)
                self.statistics_timer.setInterval(REFRESH_MILLISECONDS)
                self.statistics_timer.timeout.connect(self.refresh_statistics)
            self.statistics_timer.start()
            self.refresh_statistics()
        elif self.statistics_timer is not None:
            self.statistics_timer.stop()

    def refresh_statistics(self):
        """Re-read the metrics that depend on the MID, then repaint the block."""
        manager = getattr(self, "mid_manager", None)
        if manager is not None and manager.df is not None:
            self.metrics.set_entries_remaining(manager.unedited_count())
        self.ui.set_statistic_values(self.metrics.snapshot())

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
        bundle = paths.macos_bundle()
        if bundle is not None:
            # Re-running the binary inside Contents/MacOS starts a process that
            # macOS does not recognise as the application. ``open -n`` asks
            # Launch Services for a second instance of the bundle instead.
            program = "open"
            prefix = ["-n", "-a", str(bundle), "--args"]
            arguments = prefix + list(sys.argv[1:])
        elif getattr(sys, "frozen", False):
            program, arguments = sys.executable, list(sys.argv[1:])
            prefix = []
        else:
            program, arguments = sys.executable, list(sys.argv)
            prefix = []

        cleaned = list(prefix)
        skip_next = False
        for argument in arguments[len(prefix):]:
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
                key=field.column,
                label=field.label,
                kind=field.kind,
                options=field.options,
                expandable=field.hierarchy,
                add_shortcut=field.add_shortcut,
            )
            for field in self.mid_schema.fields
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
            prior_year_copy=self.mid_schema.supports_prior_year_copy,
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
            checkbox = definition.get("checkbox", "")
            if checkbox and not self.checkbox_key_for(checkbox):
                # The button still works; only its checkbox link is dropped.
                self.logger.warning(
                    f"Button '{definition['label']}' is linked to checkbox "
                    f"'{checkbox}', which is not one of the configured checkboxes"
                )
            specs.append(
                FieldButtonSpec(
                    key=definition["key"],
                    label=definition["label"],
                    target=definition["target"],
                    tooltip=definition["tooltip"],
                )
            )
        return tuple(specs)

    def audit_test_names(self):
        """The audit checks a dev-mode restriction may be drawn from."""
        options = [
            "table_detected",
            "text_scraped",
            *[f"field:{column}" for column in self.mid_field_keys],
        ]
        if self.mid_schema.keyword_column:
            options.append("keyword_match")
        options.extend(["pages_parsed", "pdf_found"])
        return options

    def restriction_options(self):
        """Values offered by the "Restrict to:" selector in the current mode.

        Dev mode reviews the *scrape*: it may restrict to the rows a check in
        the last audit report failed. Reviewer mode reviews the *entries*: it
        may restrict to the rows a reviewer has already rejected. Both share
        the column-backed and live restrictions.
        """
        mode = self.mode.lower()
        if mode == "dev":
            return [
                *self.audit_test_names(),
                "_flag",
                *LIVE_RESTRICTIONS,
                NO_RESTRICTION,
            ]
        if mode == "reviewer":
            return [*COLUMN_RESTRICTIONS, *LIVE_RESTRICTIONS, NO_RESTRICTION]
        return []

    # Create Necessary File Structure
    def init_files(self):
        # Check if the data directory exists; if not, create it
        data_dir = self.settings.get("dataDirectory", "")
        if data_dir and not os.path.exists(data_dir):
            self.logger.warning(
                f"Data directory {data_dir} does not exist; attempting to create it"
            )
            try:
                os.makedirs(data_dir)
                self.logger.info(f"Created data directory {data_dir}")
            except Exception as e:
                self.logger.error(
                    "Failed to create the data directory! Files will not be loaded!"
                )
                QMessageBox.critical(
                    self, "Error", f"Failed to create data directory:\n{e}"
                )

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
        self.ui.set_entry_edited_checked(self.mid_manager.is_entry_edited())
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

        # The one we are leaving goes back to the cache rather than being
        # closed, so returning to it costs nothing. The cache closes whatever
        # it evicts.
        if session is not None:
            self.session_cache.put(session)
            self.document_session = None

        cached = self.session_cache.take(path, page_indices)
        if cached is not None:
            self.logger.debug(f"Reusing cached session for {path}")
            self.document_session = cached
            return True

        self.metrics.record_document_opened(path)

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

    # ------------------------------------------------------------------
    # Searching the document
    # ------------------------------------------------------------------
    def document_index(self):
        """The search index for the open document, built or reused.

        Rebuilt when the cached index belongs to a document that has since
        been closed — an evicted session takes its PDF with it.
        """
        session = self.document_session
        if session is None or session.doc is None:
            return None

        index = self.index_cache.get(session.path)
        if index is None or index.document is not session.doc:
            index = DocumentIndex(session.doc, session.page_indices, logger=self.logger)
            self.index_cache.put(session.path, index)

        index.set_in_range_pages(session.page_indices)
        # What the scraper made of each page, including anything the user has
        # corrected in the panel, so a search finds what they can see.
        for local_index, absolute in enumerate(session.page_indices):
            index.set_scraped_text(absolute, session.text_at(local_index))
        return index

    def search_document(self, query):
        """Find ``query`` across the open document and hand back the hits."""
        index = self.document_index()
        if index is None:
            self.ui.show_search_results(query, [])
            return

        scope = self.ui.search_scope() or SEARCH_IN_RANGE
        hits = index.search(query, whole_document=scope != SEARCH_IN_RANGE)
        may_leave_range = scope == SEARCH_ANYWHERE

        results = [
            {
                "page_index": hit.page_index,
                "location": hit.location,
                "snippet": hit.snippet,
                "selectable": hit.in_range or may_leave_range,
            }
            for hit in hits
        ]
        self.logger.info(
            f"Search for '{query}' found {len(results)} match(es) "
            f"in {self.current_document_name}"
        )
        self.ui.show_search_results(
            query, results, truncated=len(hits) >= SEARCH_LIMIT
        )

    def go_to_document_page(self, page_index):
        """Show the page a search result points at.

        A page this row covers becomes the current page, exactly as the page
        buttons would make it. A page outside the row is *previewed* instead:
        it is drawn, but the current page is left alone, because the current
        page is written into the MID and a row should not come to reference a
        page it is not about.
        """
        session = self.document_session
        if session is None:
            return

        page_index = int(page_index)
        if page_index in session.page_indices:
            self.current_page_index = session.page_indices.index(page_index)
            # The page is written into the row, so moving is an edit to it.
            self.mark_entry_dirty()
            self.show_page()
            self.ui.set_status_message(f"Page {page_index + 1}", 3000)
            return

        self.preview_document_page(page_index)

    def preview_document_page(self, page_index):
        """Draw a page outside this row's range without adopting it."""
        session = self.document_session
        if session is None or session.doc is None:
            return
        try:
            page = session.doc.load_page(int(page_index))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        except Exception as exc:
            self.logger.warning(f"Could not preview page {page_index + 1}: {exc}")
            return

        self.ui.show_page_pixmap(fitz_pixmap_to_qpixmap(pixmap))
        self.ui.set_status_message(
            f"Previewing page {page_index + 1}, which is outside this entry. "
            "Move a page or an entry to go back.",
            0,
        )
        self.logger.info(f"Previewed out-of-range page {page_index + 1}")

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

    # ------------------------------------------------------------------
    # Clicking the page
    # ------------------------------------------------------------------
    def step_page(self, direction: int) -> None:
        """Move a page, from a click on the viewer.

        The viewer asks rather than acts: only here is it known whether there
        is a next page, and stepping past the end should do nothing rather
        than wrap round to the other end of the document.
        """
        if int(direction) > 0:
            self.next_page()
        else:
            self.prev_page()

    def step_entry(self, direction: int) -> None:
        """Move a MID entry, from a click on the viewer.

        Routed through the normal entry navigation so the sidebar is committed
        first; a click must not lose an edit that a button press would keep.
        """
        if int(direction) > 0:
            self.next_mid_entry()
        else:
            self.prev_mid_entry()

    def resizeEvent(self, event):
        self.logger.debug("Window resized")
        super().resizeEvent(event)
        self.show_page()

    # Advances to the next page of the open session
    def next_page(self):
        self.logger.debug("Attempting to load next page")
        session = self.document_session
        if session and self.current_page_index < len(session) - 1:
            session.set_text(self.current_page_index, self.ui.content())
            self.logger.debug("Next page is valid")
            self.current_page_index += 1
            # The page is written into the row, so moving is an edit to it.
            self.mark_entry_dirty()
            self.show_page()
        else:
            self.logger.warning("Attempted to load invalid page")

    # Moves to the previous page of the open session
    def prev_page(self):
        self.logger.debug("Attempting to load previous page")
        session = self.document_session
        if session and self.current_page_index > 0:
            session.set_text(self.current_page_index, self.ui.content())
            self.logger.debug("Previous page is valid")
            self.current_page_index -= 1
            self.mark_entry_dirty()
            self.show_page()
        else:
            self.logger.warning("Attempted to load invalid page")

    # ------------------------------------------------------------------
    # Reviewer verdicts
    # ------------------------------------------------------------------
    def accept_scrape(self):
        self._record_review_verdict("ACCEPT")

    def reject_scrape(self):
        # A rejected row is flagged as well, so it shows up under the flag
        # restriction in every mode.
        self._record_review_verdict("REJECT", flag=True)

    def _record_review_verdict(self, status: str, flag: bool = False):
        """Record the reviewer's verdict on the current row and move on.

        The Accept and Reject buttons exist only in reviewer mode; a call
        from any other mode is a programming error rather than something
        the user did, so it is logged and ignored.
        """
        if self.mode.lower() != "reviewer":
            self.logger.warning(
                f"Ignored reviewer verdict '{status}' in {self.mode} mode"
            )
            return
        manager = getattr(self, "mid_manager", None)
        if manager is None or manager.get_current_row() is None:
            self.logger.error("No MID row to record a verdict on")
            return

        idx = manager.current_index
        label = self.current_observation_label
        notes = self.ui.reviewer_notes_text()
        if flag:
            self.ui.set_toggle("flag", True)
        manager.set_value(idx, "reviewer_status", status)
        self.logger.info(
            f"Reviewer {status.lower()}ed row {idx} ({label}) with notes: {notes}"
        )
        self.next_mid_entry()

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
        """Rebuild this X/Y block from the previous year's hierarchy rows."""
        self._commit_sidebar_fields()
        try:
            created = self.mid_manager.duplicate_prior_year()
        except ValueError as exc:
            self.logger.warning(f"Copy Previous Year failed: {exc}")
            QMessageBox.warning(self, "Copy Previous Year", str(exc))
            return
        self.load_mid_entry_document()
        self.update_info_labels()
        self.ui.set_status_message(
            f"Copied {created} row(s) from the previous year.", 4000
        )

    # ------------------------------------------------------------------
    # Entry edit tracking
    # ------------------------------------------------------------------
    def mark_entry_dirty(self):
        """Record that the user has changed something about the current row.

        Ignored while a row is being loaded, so presenting a row is never
        mistaken for editing it.
        """
        manager = getattr(self, "mid_manager", None)
        if manager is None or self._loading_entry:
            return
        manager.mark_entry_dirty()

    def on_entry_edited_by_user(self):
        """Any sidebar widget the user touched reports through here."""
        self.mark_entry_dirty()

    def set_entry_edited(self, edited: bool = True):
        """Set the current row's persistent edited flag by hand."""
        manager = getattr(self, "mid_manager", None)
        if manager is None or manager.get_current_row() is None:
            return
        value = manager.set_entry_edited(bool(edited))
        self.ui.set_entry_edited_checked(value)
        state = "edited" if value else "unedited"
        self.logger.info(
            f"Marked {self.current_observation_label} "
            f"(row {manager.current_index}) as {state}"
        )
        self.ui.set_status_message(f"Entry marked as {state}.", 3000)

    def goto_first_unedited_entry(self):
        """Jump to the topmost row no change has ever been saved to."""
        manager = getattr(self, "mid_manager", None)
        if manager is None or manager.df is None:
            return
        self._commit_sidebar_fields()

        target = manager.first_unedited_index()
        if target is None:
            self.logger.info("No unedited MID entries remain")
            QMessageBox.information(
                self,
                "No Unedited Entries",
                "Every entry in the current view has been edited.",
            )
            return

        if target == manager.current_index:
            self.ui.set_status_message(
                "This is already the first unedited entry.", 3000
            )
            return

        manager.select_mid_entry(target)
        self.load_mid_entry_document()
        self.update_info_labels()
        self.show_page()
        remaining = manager.unedited_count()
        self.logger.info(
            f"Jumped to first unedited entry at row {target} "
            f"({remaining} unedited entries in view)"
        )
        self.ui.set_status_message(
            f"Entry {target + 1} — {remaining} unedited entries in this view.", 5000
        )

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
        old_statistics = self.pinned_statistic_keys()
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
            save_settings(self.settings)
            self.mode = self.settings.get("userMode", "User")
            self.update_mode_ui()
            new_statistics = self.pinned_statistic_keys()

            # Module settings take effect immediately; no restart needed.
            new_modules = self.resolved_module_settings()
            if new_modules != old_modules:
                self.ui.apply_module_settings(new_modules)
                self.logger.info("Applied updated module settings")

            # Which statistics are pinned is only a matter of what is drawn,
            # so it takes effect now rather than joining the restart list.
            if new_statistics != old_statistics:
                self.apply_statistics_settings()
                self.logger.info(
                    "Statistics on the main window: %s",
                    ", ".join(new_statistics) if new_statistics else "none",
                )

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

    # ------------------------------------------------------------------
    # Restrictions
    # ------------------------------------------------------------------
    def handle_load_failures(self):
        """Apply whatever the "Restrict to:" selector says."""
        self.apply_restriction(self.ui.restriction_choice())

    def apply_restriction(self, test_name: str):
        """Restrict the MID view to the rows ``test_name`` selects.

        ``none`` lifts the restriction. The live and column-backed choices
        are answered from the MID itself; anything else is taken to be the
        name of a check in the last audit report, which only dev mode offers.
        """
        manager = getattr(self, "mid_manager", None)
        if manager is None or manager.df is None or manager.df.empty:
            QMessageBox.information(self, "No MID", "No MID is currently loaded.")
            return

        self._commit_sidebar_fields()
        if test_name == NO_RESTRICTION:
            manager.clear_restriction()
            self.logger.info("Cleared restriction; full MID restored")
            self.load_mid_entry_document()
            self.update_info_labels()
            return

        try:
            positions, empty_message = self._restriction_positions(test_name)
        except Exception as e:
            self.logger.error(f"Failed to restrict MID (test_name={test_name}): {e}")
            QMessageBox.critical(self, "Error", f"Could not restrict MID:\n{e}")
            return

        if not positions:
            QMessageBox.information(self, "No Matches", empty_message)
            return

        manager.restrict_to_rows(positions)
        self.logger.info(
            f"Restriction applied: {len(positions)} rows matched '{test_name}'"
        )
        self.load_mid_entry_document()
        self.update_info_labels()

    def _restriction_positions(self, test_name: str):
        """``(master positions, message when there are none)`` for a choice."""
        manager = self.mid_manager
        if test_name == "same_document":
            return manager.document_row_positions(), "This document has no other rows."
        if test_name == "duplicate_observation":
            return (
                manager.duplicate_observation_positions(),
                "No rows share an observation identity.",
            )
        if test_name in COLUMN_RESTRICTIONS:
            df = manager.master_df
            if test_name == "rejected":
                mask = df["reviewer_status"].astype(str).str.strip().eq("REJECT")
            else:
                mask = df[test_name].astype(bool)
            positions = [int(position) for position in df.index[mask]]
            return positions, f"No rows matched restriction: {test_name}"
        return (
            self._audit_failure_positions(test_name),
            f"No failures found for test: {test_name}",
        )

    def _audit_failure_positions(self, test_name: str) -> list[int]:
        """Master positions of the rows that failed ``test_name`` in the last audit."""
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
        # audit_runner writes entry["index"] = i+1 (1-based), but
        # MIDManager.restrict_to_rows expects 0-based iloc positions.
        return [
            int(entry["index"]) - 1
            for entry in audit_results
            if entry.get("tests", {}).get(test_name) == "FAIL"
            and str(entry.get("index", "")).isdigit()
        ]

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
    def _commit_sidebar_fields(self) -> bool:
        """Write the sidebar into the current MID row, if it is worth writing.

        The sidebar is committed on every navigation, so an untouched row
        would otherwise be rewritten — and stamped as edited — merely by being
        looked at. Nothing is written unless the user changed something *and*
        that change actually differs from what the row already holds.

        Returns whether the row was written to.
        """
        if not hasattr(self, "mid_manager") or self.mid_manager.df is None:
            return False
        # set_value converts view->master, so the view index is what we pass.
        idx = self.mid_manager.current_index
        if idx is None:
            return False

        # Staged rather than written, so that a row nobody touched can be left
        # exactly as it was.
        staged: dict[str, object] = {}

        def commit(column, value):
            staged[column] = value

        for key, value in self.ui.field_texts().items():
            commit(key, value)

        toggles = self.ui.toggles()
        counters = self.ui.counters()
        for definition in self.checkbox_specs:
            key = definition["key"]
            checked = bool(toggles.get(key, False))
            commit(definition["column"], checked)

            counter = definition["counter"]
            if counter:
                value = int(counters.get(key, 0) or 0)
                # A counter only means something while its checkbox is ticked.
                commit(counter["column"], str(value) if checked and value else "")

        commit("notes", self.ui.notes_text())
        commit("Page", self.current_page_number())

        # Read before anything is written: marking a row seen below would
        # otherwise look like an edit the user made.
        user_edited = self.mid_manager.entry_is_dirty()

        if self.mode.lower() == "reviewer":
            commit("reviewer_comments", self.ui.reviewer_notes_text())
            # Marking a row seen is the reviewer workflow's own record of
            # having visited it, not something the user typed, so it happens
            # whether or not they changed anything.
            if self.mid_manager.df.at[idx, "reviewer_status"] not in [
                "ACCEPT",
                "REJECT",
            ]:
                self.mid_manager.set_value(idx, "reviewer_status", "SEEN")
                if not user_edited:
                    self.mid_manager.clear_entry_dirty()

        if not user_edited:
            self.logger.debug(
                f"No user edits to {self.current_observation_label} "
                f"(row {idx}); left unchanged"
            )
            return False

        saved = self.mid_manager.pending_changes(idx, staged)
        if not saved:
            self.logger.debug(
                f"Edits to {self.current_observation_label} (row {idx}) "
                "matched the stored values; left unchanged"
            )
            return False

        for column, value in saved.items():
            self.mid_manager.set_value(idx, column, value)
        # A saved change is what the persistent flag records.
        self.mid_manager.set_entry_edited(True, idx)
        self.ui.set_entry_edited_checked(True)
        # Counted by observation rather than by commit, so revisiting a row to
        # correct it does not report a second entry's worth of work.
        self.metrics.record_entry_completed(self.mid_manager.observation_key(idx))

        details = ", ".join(
            f"{column}={self._format_for_log(value)}" for column, value in saved.items()
        )
        self.logger.info(
            f"Saved information for {self.current_observation_label} "
            f"(row {idx}): {details}"
        )
        return True

    @staticmethod
    def _format_for_log(value, limit: int = 120) -> str:
        """Render one committed cell value as a single, bounded log fragment."""
        text = "" if value is None else str(value)
        text = " ".join(text.split())
        if len(text) > limit:
            text = text[: limit - 1] + "…"
        return repr(text) if isinstance(value, str) else text

    def _goto_index(self, new_idx: int):
        """Move to a MID row and refresh everything the sidebar shows."""
        self.mid_manager.current_index = new_idx
        self.update_info_labels()
        self.load_mid_fields_from_row()

    def on_add_level_clicked(self, level_key: str):
        """Add a row one hierarchy level down, from the "+" beside a field."""
        self._commit_sidebar_fields()
        manager = getattr(self, "mid_manager", None)
        if manager is None or manager.get_current_row() is None:
            return
        idx = manager.current_index
        try:
            new_row = manager.clone_for_child(idx, level_key)
        except ValueError as exc:
            self.logger.error(f"Cannot add a row at '{level_key}': {exc}")
            return

        new_idx = manager.insert_row_after(idx, new_row)
        self.logger.info(
            f"Added a row at the '{level_key}' level below row {idx} (now row {new_idx})"
        )
        self._goto_index(new_idx)
        self.ui.focus_field(level_key)

    # --- Button slots ---

    def load_mid_fields_from_row(self):
        """Present the current MID row in the sidebar."""
        self._loading_entry = True
        try:
            self._present_mid_row()
        finally:
            self._loading_entry = False
            # Filling the widgets is not editing; whatever they emitted on the
            # way in does not count.
            manager = getattr(self, "mid_manager", None)
            if manager is not None:
                manager.clear_entry_dirty()

    def _present_mid_row(self):
        manager = getattr(self, "mid_manager", None)
        # Recorded here rather than on navigation so the first row, which is
        # presented during start-up, is counted like any other.
        if manager is not None and manager.df is not None:
            self.metrics.record_entry_opened(manager.observation_key())

        row = manager.get_current_row() if manager is not None else None
        if row is None:
            self.ui.clear_fields()
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
        self.ui.set_field_texts(
            {key: self._safe_text(row.get(key, "")) for key in self.mid_field_keys}
        )

    def _as_int(self, value) -> int:
        try:
            text = self._safe_text(value).strip()
            return int(text) if text else 0
        except ValueError:
            return 0

    def checkbox_key_for(self, name: str) -> str:
        """The toggle key a button's ``checkbox`` setting refers to.

        Settings may name a checkbox either way round — by the key code uses
        or by the MID column it writes to — so both are accepted.
        """
        name = self._safe_text(name).strip()
        if not name:
            return ""
        for definition in self.checkbox_specs:
            if name in (definition["key"], definition["column"]):
                return definition["key"]
        return ""

    def on_field_button_clicked(self, key: str):
        """Compute one editable field from the others and write it in.

        A button may also be linked to a checkbox, which it sets in the same
        press — but only once the formula has succeeded, so a failed press
        leaves the row exactly as it was.
        """
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
        message = f"{definition['target']} = {text}  ({definition['expression']})"

        toggled = self._apply_button_checkbox(definition)
        if toggled:
            message += f"  [{toggled}]"
        self.ui.set_status_message(message, 4000)
        self.ui.refresh_highlights()

    def _apply_button_checkbox(self, definition) -> str:
        """Set the checkbox a button is linked to; report what it did.

        Returns a description for the status bar, or ``""`` when the button
        has no checkbox linked.
        """
        toggle_key = self.checkbox_key_for(definition.get("checkbox", ""))
        if not toggle_key:
            return ""

        action = definition.get("checkbox_action", "check")
        if action == "toggle":
            checked = not self.ui.is_toggled(toggle_key)
        else:
            checked = action != "uncheck"

        # notify=True so the checkbox behaves exactly as if it were clicked:
        # its companion counter follows, and the usual listeners run.
        self.ui.set_toggle(toggle_key, checked, notify=True)

        label = next(
            (
                item["label"]
                for item in self.checkbox_specs
                if item["key"] == toggle_key
            ),
            toggle_key,
        )
        self.logger.info(
            f"Button '{definition['label']}' "
            f"{'checked' if checked else 'unchecked'} {label}"
        )
        return f"{label} {'checked' if checked else 'unchecked'}"

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

        self.ui.set_field_text(target_key, text.strip())
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


if __name__ == "__main__":
    # The launcher owns start-up: high-DPI attributes have to be set before any
    # QApplication is built, so running this file directly defers to it.
    from main import main

    sys.exit(main())
