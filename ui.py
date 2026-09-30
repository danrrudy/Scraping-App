from app_settings import load_settings
from logger import setup_logger


class ApplicationMainWindow(QMainWindow):
    def __init__(self, app):
        self.app = app


    def setup(self):
        app = self.app
        app.logger.debug(f"Initializing UI in {app.mode} mode")

        # Set UI Scale

        # Document Display Window
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)

        left_panel = self._build_info_panel()
        center_panel = self._build_viewer_panel()

        main_layout.addLayout(left_panel, 1)
        main_layout.addLayout(center_panel, 4)

        self._setup_menu()
        app._setup_shortcuts()
        app.installEventFilter(app)

        self.updated_mode_ui()





        # --- Action buttons under the status radios ---

        # Reviewer Mode Group



        # --- Control Panel ---
        # Menu action



        # Dev mode feature to review test failures, will need to dynamically load test names later
        # This field is the drop-down to select the test

        # --- Viewer Panel ---
        splitter = QSplitter(Qt.Horizontal)
        # PDF Page Display
        self.pdf_label = QLabel("Load a document to begin.")
        self.pdf_label.setAlignment(Qt.AlignCenter)
        self.pdf_label.setMinimumSize(100, 100)
        self.pdf_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        # self.pdf_label.setWidgetResizable(True)
        splitter.addWidget(self.pdf_label)

        # Scraped Text Display
        self.text_edit = self.configure_text_box(QTextEdit())
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
        self.update_mode_ui()



 # Update read-only information for user
    def update_info_labels(self):
        self.logger.debug("Updating info labels")
        page_num = (
            self.page_indices[self.current_page_index] + 1
            if self.page_indices
            else self.current_page_index + 1
        )
        row = None
        mid_length = len(self.mid_manager.view_indices)
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
                for widget in self.reviewer_mode_widgets:
                    widget.setVisible(True)

# Assembly

        # Fill empty space
        control_layout.addStretch()
        side_panel = QVBoxLayout()
        side_panel.addLayout(info_layout)
        side_panel.addLayout(control_layout)
        main_layout.addLayout(side_panel, 1)
        self.logger.debug("Created Side Panel")




# Build Major Components

#-----------------------------
#     Top Menu
#-----------------------------

    def _setup_menu(self):
        app = self.app

        save_mid_act = QAction("Save MID…", self)
        save_mid_act.triggered.connect(app.save_mid_to_file)
        app.menuBar().addMenu("&File").addAction(save_mid_act)
        save_mid_act.setShortcut("Ctrl+S")



#-----------------------------
#     Left Panel
#-----------------------------

    def _build_info_panel():
        app = self.app
        # --- Status Information Panel ---
        info_layout = QVBoxLayout()

        app.entry_index_label = QLabel("Entry 0 of 0")
        app.entry_index_label.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(app.entry_index_label)

        app.info_fields = ["File", "Agency", "Year", "Page", "Format"]

        # Dynamically create info fields based on assignment above
        for field in app.info_fields:
            label = QLabel(f"{field.capitalize()}: ")
            label.setStyleSheet("font-weight: bold;")
            info_layout.addWidget(label)
            app.info_labels[field.lower()] = (
                label  # set keys to lowercase version of field name
            )

        info_layout.addWidget(self._build_mid_fields_group())
        info_layout.addWidget(self._build_reviewer_group())

        return info_layout

    # Build Sub-panels

    def _build_mid_fields_group(self):
        app = self.app

        mid_fields_group = QGroupBox("Fields")
        mid_form = QFormLayout()

        labels_for = {
            "stratobj": "stratobj",
            "obj": "obj",
            "goal": "goal",
            "metric": "metric",
        }

        app._field_highlight_colors = {
            "stratobj": QColor("#FFF2A8"),  # yellow
            "obj": QColor("#CFF7D3"),  # green
            "goal": QColor("#CFE8FF"),  # blue
            "metric": QColor("#FFD1DC"),  # pink
            "target": QColor("#E6D6FF"),  # light purple
            "actual": QColor("#FFE0B2"),  # light orange
        }

        for key in app.mid_field_keys:
            # Build Containers
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            #Construct text box
            editor = self.configure_text_box(QTextEdit())
            # editor.setFixedHeight(70)
            self.mid_field_editors[key] = editor

            # Build + Buttons
            btn = QPushButton("+")
            btn.setFixedWidth(26)
            btn.setToolTip(f"Add new {key} row")
            btn.clicked.connect(lambda _=False, kk=key: self.on_add_level_clicked(kk))

            self.add_level_buttons[key] = btn

            row_layout.addWidget(editor, 1)
            row_layout.addWidget(btn, 0)

            mid_form.addRow(labels_for[key] + ":", row_widget)

        # Add Target and Actual Fields
        self.target_edit = QLineEdit()
        self.actual_edit = QLineEdit()
        mid_form.addRow("Target:", self.target_edit)
        mid_form.addRow("Actual:", self.actual_edit)

        self._add_classification_controls(mid_form)
        self._add_status_controls(mid_form)
        self._add_notes_controls(mid_form)

        mid_fields_group.setLayout(mid_form)

        return mid_fields_group

    def _add_classification_controls(self, mid_form):
        app = self.app
        # --- Metric status radios (Under the Metric editor) ---
        scheme_row = QHBoxLayout()
        scheme_row.setSpacing(8)

        scheme_lbl = QLabel("Classification Scheme:")
        scheme_row.addWidget(scheme_lbl)

        app.class_scheme_combo = QComboBox()
        scheme_row.addWidget(app.class_scheme_combo)
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

        app.metric_status_group = QButtonGroup(app)
        app.metric_status_layout = QHBoxLayout(app.metric_status_container)
        app.metric_status_layout.setSpacing(8)
        app.metric_status_layout.setContentsMargins(0, 0, 0, 0)

        metric_vlayout.addWidget(app.metric_status_container)

        # put the status row right below the metric QTextEdit
        mid_form.addRow("", QWidget())  # tiny spacer line
        mid_form.addRow(metric_container)

        # Detect change in scheme
        app.class_scheme_combo.currentTextChanged.connect(self.on_scheme_changed)
        # Populate corresponding buttons
        self._refresh_class_schemes_from_settings()

    def _add_status_controls(self, mid_form):
        app = self.app

        actions_row = QHBoxLayout()

        self.chk_flag = QCheckBox("Flag for review")
        self.chk_aggregate = QCheckBox("Aggregate")
        self.chk_achieved = QCheckBox("Achieved")
        self.chk_future_dated = QCheckBox("Future-Dated")


        self.years_to_eval_spin = QSpinBox()
        self.years_to_eval_spin.setRange(
            0, 20
        )  # arbitrary
        self.years_to_eval_spin.setSpecialValueText("")
        self.years_to_eval_spin.setEnabled(False)
        self.years_to_eval_spin.setFixedWidth(40)

        years_lbl = QLabel("Years to eval:")

        self.chk_flag.stateChanged.connect(self.on_flag_togggle)
        self.chk_aggregate.stateChanged.connect(self.on_agg_togggle)
        self.chk_achieved.stateChanged.connect(self.on_achieved_toggle)
        self.chk_future_dated.stateChanged.connect(self.on_fd_togggle)
        self.years_to_eval_spin.valueChanged.connect(self.on_years_to_eval_changed)

        actions_row.addWidget(self.chk_flag)
        actions_row.addWidget(self.chk_aggregate)
        actions_row.addWidget(self.chk_achieved)
        actions_row.addWidget(self.chk_future_dated)
        actions_row.addWidget(years_lbl)
        actions_row.addWidget(self.years_to_eval_spin)

        mid_form.addRow(actions_row)


    def _add_notes_controls(self, mid_form):
        app = self.app

        # Notes field
        notes_container = QHBoxLayout()


        if app.mode.lower() == "reviewer":
            original_notes_lbl = "User Notes"
        else:
            original_notes_lbl = "Notes"

        app.notes_lbl = QLabel(original_notes_lbl)
        app.notes = QLineEdit()
        notes_container.addWidget(self.notes_lbl)
        notes_container.addWidget(self.notes)

        mid_form.addRow(notes_container)


    def _build_reviewer_fields_group(self, mid_form):
        app = self.app


        reviewer_group = QGroupBox("Reviewer Tools")
        reviewer_layout = QVBoxLayout()


        app.reviewer_notes_container = QHBoxLayout()
        app.reviewer_notes_lbl = QLabel("Reviewer Notes:")
        app.reviewer_notes = QLineEdit()

        reviewer_notes_container.addWidget(app.reviewer_notes_lbl)
        reviewer_notes_container.addWidget(app.reviewer_notes)

        reviewer_layout.addLayout(reviewer_notes_container)

        app.hint_lbl = QLabel("")
        app.hint_lbl.setWordWrap(True)
        reviewer_layout.addWidget(app.hint_lbl)

        # Reviewer mode buttons
        reviewer_mode_buttons = QHBoxLayout()

        app.btn_accept = self.configure_button(QPushButton("Accept"))
        app.btn_reject = self.configure_button(QPushButton("Reject"))

        app.btn_accept.clicked.connect(app.accept_scrape)
        app.btn_reject.clicked.connect(app.reject_scrape)

        reviewer_mode_buttons.addWidget(app.btn_accept)
        reviewer_mode_buttons.addWidget(app.btn_reject)
        reviewer_layout.addLayout(reviewer_mode_buttons)

        reviewer_group.setLayout(reviewer_layout)
        app.reviewer_mode_widgets.append(reviewer_group)

        return reviewer_group

    def _build_controls_group(self):
        app = self.app

        control_layout = QVBoxLayout()

        prev_btn = self.configure_button(QPushButton("Previous Page"))
        prev_btn.clicked.connect(app.prev_page)
        control_layout.addWidget(prev_btn)
        self.logger.debug("Added Previous Page button")

        next_btn = self.configure_button(QPushButton("Next Page"))
        next_btn.clicked.connect(app.next_page)
        control_layout.addWidget(next_btn)
        self.logger.debug("Added Next Page button")

        next_entry_btn = self.configure_button(QPushButton("Next MID Entry"))
        next_entry_btn.clicked.connect(app.next_mid_entry)
        control_layout.addWidget(next_entry_btn)
        next_entry_btn.setShortcut("Ctrl+Right")
        self.logger.debug("Added Next MID Entry button")

        prev_entry_btn = self.configure_button(QPushButton("Previous MID Entry"))
        prev_entry_btn.clicked.connect(app.prev_mid_entry)
        control_layout.addWidget(prev_entry_btn)
        next_entry_btn.setShortcut("Ctrl+Left")
        self.logger.debug("Added Previous MID Entry button")

        select_entry_btn = self.configure_button(QPushButton("Jump to MID Entry..."))
        select_entry_btn.clicked.connect(app.select_mid_entry)
        control_layout.addWidget(select_entry_btn)
        next_entry_btn.setShortcut("Ctrl+O")
        self.logger.debug("Added Select MID Entry button")

        delete_btn = self.configure_button(QPushButton("Delete this MID Entry"))
        delete_btn.clicked.connect(app.delete_mid_entry)
        control_layout.addWidget(delete_btn)
        self.user_mode_widgets.append(delete_btn)
        self.dev_mode_widgets.append(delete_btn)

        copy_btn = self.configure_button(QPushButton("Copy Previous Year"))
        copy_btn.clicked.connect(app.duplicate_prior_year)
        control_layout.addWidget(copy_btn)
        self.user_mode_widgets.append(copy_btn)
        self.dev_mode_widgets.append(copy_btn)

        settings_btn = self.configure_button(QPushButton("Settings"))
        settings_btn.clicked.connect(app.open_settings)
        control_layout.addWidget(settings_btn)
        self.logger.debug("Added Settings button")

        audit_btn = self.configure_button(QPushButton("Run MID Audit"))
        audit_btn.clicked.connect(app.run_mid_audit)
        control_layout.addWidget(audit_btn)
        self.dev_mode_widgets.append(audit_btn)
        self.logger.debug("Added Audit button")

        control_layout.addStretch()
        return control_layout

    def _add_restriction_controls(self, control_layout):
        app = self.app

        app.failure_test_combo = QComboBox()
        if app.mode.lower() == "dev":
            app.failure_test_combo.addItems(
                [
                    "table_detected",
                    "text_scraped",
                    "goal_match",
                    "obj_match",
                    "keyword_match",
                    "stratobj_match",
                    "pages_parsed",
                    "pdf_found",
                    "_flag",
                    "no_status",
                    "no_t/a",
                    "none",
                ]
            )
        elif app.mode.lower() == "reviewer":
            app.failure_test_combo.addItems(
                [
                    "_flag",
                    "_gen",
                    "rejected",
                    "no_status",
                    "no_t/a",
                    "none",
                ]
            )

        failures_label = QLabel("Restrict to:")

        control_layout.addWidget(failures_label)
        control_layout.addWidget(app.failure_test_combo)
        app.dev_mode_widgets.append(app.failure_test_combo)
        app.reviewer_mode_widgets.append(app.failure_test_combo)
        app.dev_mode_widgets.append(failures_label)
        app.reviewer_mode_widgets.append(failures_label)

        # Restrict the MID entries to only those that failed the selected test
        load_failures_btn = self.configure_button(QPushButton("Load Cases"))
        load_failures_btn.clicked.connect(app.handle_load_failures)
        control_layout.addWidget(load_failures_btn)

        self.dev_mode_widgets.append(load_failures_btn)
        self.reviewer_mode_widgets.append(load_failures_btn)

        export_review_btn = self.configure_button(QPushButton("Export Review Results"))
        export_review_btn.clicked.connect(app.export_review_results)
        control_layout.addWidget(export_review_btn)

        app.dev_mode_widgets.append(export_review_btn)




#-----------------------------
#     Center Panel
#-----------------------------

    def _build_viewer_panel():


#-----------------------------
#     Right Panel
#-----------------------------

    def _build_text_panel():




# Helper Functions

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

    def apply_global_font(self, app, base_font_size, scale):
        font = QFont()
        font.setPointSize(max(base_font_size, int(round(base_font_size * scale))))
        app.setFont(font)

    def configure_button(self, btn):
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        btn.setMinimumHeight(24)
        return btn

    def configure_text_box(self, text_box):
        text_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        text_box.setMinimumWidth(150)
        text_box.setMinimumHeight(32)
        return text_box

    def configure_list_box(self, list_box):
        list_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        list_box.setMinimumWidth(160)
        return list_box
