# mid_manager.py

import re

import pandas as pd
from logger import setup_logger
from mid_schema import (
    EDITED_COLUMN,
    PAGE_COLUMN,
    MIDSchema,
    WORKFLOW_COLUMN_DEFAULTS,
    clean_value,
    coerce_page,
    normalize_sheet_name,
)


class MIDManager:
    def __init__(self, path, sheet_name=0, schema=None, boolean_columns=()):
        """``boolean_columns`` are extra true/false columns to guarantee.

        User-defined checkboxes name their own MID columns, which the sheet
        will not have the first time they are used.
        """
        self.logger = setup_logger()
        self.schema = schema or MIDSchema.default()
        self.boolean_columns = tuple(dict.fromkeys(boolean_columns))
        df = self.load_mid(path, sheet_name)
        self.master_df = df
        self.view_indices = list(range(len(df)))
        self.df = df.copy()
        self._current_index = 0
        # Set whenever a value actually changes, cleared when the MID is
        # written out; drives the unsaved-changes prompt on restart.
        self._modified = False
        # Set whenever a value on the *current* row changes, cleared on every
        # move to another row. Purely in-memory: it is what tells a navigation
        # away from an untouched row not to write over it.
        self._entry_dirty = False
        self.logger.info("Initialized MIDManager")

    # ------------------------------------------------------------------
    # Current row
    # ------------------------------------------------------------------
    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value) -> None:
        """Moving to another row abandons the edit tracking for the old one."""
        value = int(value)
        if value != self._current_index:
            self._entry_dirty = False
        self._current_index = value

    def load_mid(self, path, sheet_name=0):
        """Loads and validates the Master Input Document (MID) Excel file."""
        sheet_name = normalize_sheet_name(sheet_name)
        try:
            df = pd.read_excel(
                path, sheet_name=sheet_name, dtype=str, keep_default_na=False
            )  # Read all as string first
        except Exception as e:
            raise RuntimeError(f"Failed to load MID file: {e}")

        df.columns = [str(column).strip() for column in df.columns]
        self.schema.validate_columns(df.columns)

        # Only the anchor has to exist in the sheet. Everything else the schema
        # refers to is created empty so it can be filled in from the app and
        # written out on export.
        created_columns = self.schema.creatable_columns(df.columns)
        for column in created_columns:
            df[column] = ""
        if created_columns:
            self.logger.warning(
                f"MID has no column(s) {list(created_columns)}; created empty. "
                "Values entered in the app are written when you export the MID."
            )

        # Source values stay text: the application does not know what a
        # project's columns mean, and text is what the sidebar reads and
        # writes. The workflow columns below are the exception.
        for column in df.columns:
            df[column] = df[column].fillna("").astype(str).str.strip()

        self._validate_anchor(df)
        self._warn_about_duplicate_observations(df)

        defaults = dict(WORKFLOW_COLUMN_DEFAULTS)
        for column in self.boolean_columns:
            defaults.setdefault(column, "" if not column.startswith("_") else False)

        for column, default in defaults.items():
            if column not in df.columns:
                df[column] = default
            elif isinstance(default, bool):
                df[column] = (
                    df[column]
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .isin(["true", "1", "yes", "y"])
                )

        # The page is the one column compared with numbers, so it is the one
        # column whose type is enforced: an int, or blank.
        df[PAGE_COLUMN] = df[PAGE_COLUMN].map(coerce_page).astype(object)

        return df

    def _validate_anchor(self, df):
        """Every row must say which document it refers to."""
        anchor_columns = list(self.schema.required_source_columns)
        blank_anchor = df[anchor_columns].eq("").any(axis=1)
        if not blank_anchor.any():
            return

        rows = (df.index[blank_anchor] + 2).tolist()[:10]
        if self.schema.document_column:
            raise ValueError(
                f"Every MID row must name a document in '{self.schema.document_column}'. "
                f"Check spreadsheet row(s): {rows}"
            )
        raise ValueError(
            "MID X/Y identifiers compose the filename and cannot be blank. "
            f"Check spreadsheet row(s): {rows}"
        )

    def _duplicate_mask(self, df):
        """Rows whose identity is shared with another row.

        Reported, never fatal: identifiers are assigned inside the app, so a
        MID saved mid-assignment would otherwise refuse to reopen. Rows with
        any blank identity value are unassigned, not duplicates.
        """
        blank = pd.Series(False, index=df.index)
        columns = list(self.schema.uniqueness_columns)
        if not columns or not self.schema.identifier_columns:
            # Nothing distinguishes observations within a document yet.
            return blank

        assigned = df[columns].ne("").all(axis=1)
        if not assigned.any():
            return blank

        duplicates = blank.copy()
        duplicates.loc[assigned] = df.loc[assigned].duplicated(columns, keep=False)
        return duplicates

    def _warn_about_duplicate_observations(self, df):
        duplicates = self._duplicate_mask(df)
        if not duplicates.any():
            return
        examples = (
            df.loc[duplicates, list(self.schema.uniqueness_columns)]
            .drop_duplicates()
            .head(5)
            .apply(tuple, axis=1)
            .tolist()
        )
        self.logger.warning(
            f"{int(duplicates.sum())} MID row(s) share an observation identity "
            f"with another row. Example(s): {examples}"
        )

    def duplicate_observation_positions(self) -> list[int]:
        """Master positions of rows that share an identity with another row."""
        if self.master_df is None or self.master_df.empty:
            return []
        mask = self._duplicate_mask(self.master_df)
        return [int(position) for position in self.master_df.index[mask]]

    def duplicate_observation_view_indices(self) -> set[int]:
        """The same rows as :meth:`duplicate_observation_positions`, as view indices.

        The two numbering schemes differ whenever a restriction is active, so
        callers iterating ``df`` should use this one.
        """
        duplicates = set(self.duplicate_observation_positions())
        if not duplicates:
            return set()
        return {
            view_index
            for view_index, master_position in enumerate(self.view_indices)
            if master_position in duplicates
        }

    def is_duplicate_observation(self, index=None) -> bool:
        """Whether the row at a view index collides with another row."""
        view_index = self.current_index if index is None else index
        return view_index in self.duplicate_observation_view_indices()

    def document_row_positions(self, index=None) -> list[int]:
        """Master positions of every row pointing at the same document."""
        if self.master_df is None or self.master_df.empty:
            return []
        row = self._resolve_row(index)
        if row is None:
            return []
        target = self.schema.document_key(row)
        if not target:
            return []
        keys = self.master_df.apply(self.schema.document_key, axis=1)
        return [int(position) for position in self.master_df.index[keys == target]]

    def document_position(self, index=None) -> tuple[int, int]:
        """``(ordinal, total)`` of this row among the rows sharing its document."""
        positions = self.document_row_positions(index)
        master_position = self._master_pos(
            self.current_index if index is None else index
        )
        if not positions or master_position is None:
            return (0, 0)
        try:
            return (positions.index(master_position) + 1, len(positions))
        except ValueError:
            return (0, len(positions))

    def clone_for_document(self, index=None) -> dict:
        """A blank observation on the same document as the given row.

        The anchor is carried over; identifiers, editable fields, and the
        review workflow columns are cleared so the new row starts empty.
        """
        row = self._resolve_row(index)
        if row is None:
            return {}

        new_row = dict(row)
        cleared = set(self.schema.interaction_columns) | set(
            self.schema.identifier_columns
        )
        cleared.discard(self.schema.document_column)

        for column in cleared:
            if column in new_row:
                new_row[column] = ""

        for column, default in WORKFLOW_COLUMN_DEFAULTS.items():
            if column in new_row and column != PAGE_COLUMN:
                new_row[column] = default

        new_row["_gen"] = True
        return new_row

    def document_key(self, index=None):
        row = self._resolve_row(index)
        if row is None:
            return ""
        return self.schema.document_key(row)

    def observation_key(self, index=None):
        row = self._resolve_row(index)
        if row is None:
            return None
        return self.schema.observation_key(row)

    def observation_label(self, index=None):
        row = self._resolve_row(index)
        if row is None:
            return ""
        return self.schema.observation_label(row)

    def observation_stem(self, index=None):
        row = self._resolve_row(index)
        if row is None:
            return "observation"
        return self.schema.observation_stem(row)

    def document_candidates(self, index=None):
        row = self._resolve_row(index)
        if row is None:
            return ()
        return self.schema.document_candidates(row)

    def format_type(self, index=None, default=-1):
        row = self._resolve_row(index)
        if row is None:
            return default
        return self.schema.format_type(row, default=default)

    def _resolve_row(self, index=None):
        """Accept a view index or an already-resolved row mapping."""
        if index is None:
            return self.get_current_row()
        if isinstance(index, (dict, pd.Series)):
            return index
        return self.df.iloc[index]

    def get_current_row(self):
        m = self._master_pos(self.current_index)
        if m is None:
            return None
        return self.master_df.iloc[m]

    # Allow next_ and prev_mid_entry to run over by 1 so that get_current_row can return None when the end is reached
    def next_mid_entry(self):
        if self.view_indices and self.current_index < len(self.view_indices):
            self.current_index += 1

    def prev_mid_entry(self):
        if self.view_indices and self.current_index >= 0:
            self.current_index -= 1

    def select_mid_entry(self, index=None):
        if self.df is not None and index is not None and 0 <= index < len(self.df):
            self.current_index = index

    # Parse the configured page-reference field into a list of zero-indexed
    # page numbers. Removes leading p. and expands ranges (inclusive).
    def parse_pdf_pages(self, index=None):
        row = self.get_current_row() if index is None else self.df.iloc[index]
        if not self.schema.page_column:
            return [0]

        # Pull the configured page reference and remove whitespace.
        page_field = clean_value(row.get(self.schema.page_column, ""))

        if not page_field:
            self.logger.warning(
                f"No page field listed for {self.schema.observation_label(row)} "
                f"on line {str(index)}"
            )
            return []

        self.logger.debug(f"parsing {page_field}")
        page_field = page_field.lower().replace("p.", "")

        # pages is the empty array that the individual document pages will be loaded into
        pages = []

        try:
            # Match comma-separated values like "p.3, p.5-7"
            for part in re.split(r"[,\s]+", page_field):
                if "-" in part:
                    start, end = map(int, part.split("-"))
                    pages.extend(range(start - 1, end))  # zero-indexed
                    self.logger.debug(f"Page range: {start} - {end}")
                elif part.isdigit():
                    pages.append(int(part) - 1)
                    self.logger.debug(f"Single page: {int(part)}")
        except Exception as e:
            self.logger.warning(
                f"Failed to parse page numbers from '{page_field}': {e}"
            )
            return []

        return sorted(set(p for p in pages if p >= 0))

    def restrict_to_rows(self, row_indices):
        """Restrict MID to a subset of *master* row positions for focused review."""
        # row_indices are master positional indices (iloc positions)
        self.view_indices = [int(i) for i in row_indices]
        self.current_index = 0
        self._rebuild_view()

    # ------------------------------------------------------------------
    # Hierarchy helpers
    # ------------------------------------------------------------------
    def get_group_key(self, idx: int) -> tuple[str, str]:
        """Group rows by the configured X/Y observation key."""
        return self.schema.observation_key(self.df.iloc[idx])

    def group_bounds(self, idx: int) -> tuple[int, int]:
        """
        Return (start, end_inclusive) bounds of the contiguous block of rows
        sharing the same configured X/Y observation key as row idx.
        """
        if self.df is None or self.df.empty:
            return (0, -1)
        key = self.get_group_key(idx)
        s = self.df.index.min()
        e = self.df.index.max()
        # expand upward
        i = idx
        while i - 1 >= s and self.get_group_key(i - 1) == key:
            i -= 1
        start = i
        # expand downward
        j = idx
        while j + 1 <= e and self.get_group_key(j + 1) == key:
            j += 1
        end = j
        return (start, end)

    def insert_row_after(self, after_pos: int, new_row: dict) -> int:
        """
        Insert new_row after the *current view* position after_pos.
        Returns the new view index.
        """
        if self.master_df is None:
            return after_pos + 1

        insert_after_master = self._master_pos(after_pos)
        top = self.master_df.iloc[: insert_after_master + 1]
        bottom = self.master_df.iloc[insert_after_master + 1 :]
        self.master_df = pd.concat(
            [top, pd.DataFrame([new_row]), bottom], ignore_index=True
        )

        new_master_pos = insert_after_master + 1

        # shift existing mapped indices that occur after insertion
        self.view_indices = [
            (i + 1) if i >= new_master_pos else i for i in self.view_indices
        ]

        # insert new row into the view right after after_pos
        self.view_indices.insert(after_pos + 1, new_master_pos)

        self._modified = True
        self._rebuild_view()
        return after_pos + 1

    def clone_for_child(self, parent_idx: int, level_column: str) -> dict:
        """A new row one hierarchy level down from ``parent_idx``.

        Copies the parent, keeping the levels above ``level_column`` and
        clearing that level and every level beneath it, so the user fills in
        only what is new. Marked as generated and not yet edited.
        """
        to_clear = self.schema.hierarchy_below(level_column)
        if not to_clear:
            raise ValueError(f"'{level_column}' is not a hierarchy field")
        new_row = self.df.iloc[parent_idx].to_dict()
        for column in to_clear:
            new_row[column] = ""
        new_row["_gen"] = True  # mark programmatically generated rows
        # A row that has just been created has not been edited by anyone yet.
        new_row[EDITED_COLUMN] = False
        return new_row

    def delete_current_row(self):
        if self.master_df is None or self.df is None or self.df.empty:
            return
        if not (0 <= self.current_index < len(self.df)):
            return

        del_master_pos = self._master_pos(self.current_index)

        # delete from master
        self.master_df = self.master_df.drop(
            self.master_df.index[del_master_pos]
        ).reset_index(drop=True)

        # remove from view mapping and shift indices after deleted row
        del self.view_indices[self.current_index]
        self.view_indices = [
            (i - 1) if i > del_master_pos else i for i in self.view_indices
        ]

        if self.current_index >= len(self.view_indices):
            self.current_index = max(0, len(self.view_indices) - 1)

        self._modified = True
        self._rebuild_view()

    def duplicate_prior_year(self, clear_helpers: bool = True) -> int:
        """Rebuild the current X/Y block from the previous Y's hierarchy.

        For the row at ``current_index``, finds the rows with the same X and
        a Y one less, and replaces the current row's contiguous X/Y block
        with one row per prior row, each carrying the prior row's hierarchy
        fields and everything else from the block's first row.

        Returns the number of rows created. Raises ``ValueError`` when the
        schema cannot support it, the current row's Y is not a number, or no
        prior block exists.
        """
        schema = self.schema
        if not schema.supports_prior_year_copy:
            raise ValueError(
                "Copying the previous year needs X and Y identifier columns "
                "and at least one hierarchy field."
            )
        if self.df is None or self.df.empty:
            raise ValueError("MID is empty; nothing to duplicate.")
        if self.current_index is None or not (0 <= self.current_index < len(self.df)):
            raise ValueError("current_index is invalid.")

        x_column, y_column = schema.x_column, schema.y_column
        hierarchy_cols = list(schema.hierarchy_columns)

        cur_row = self.df.iloc[self.current_index]
        x_value = clean_value(cur_row.get(x_column))
        y_raw = cur_row.get(y_column)
        if not x_value:
            raise ValueError(
                f"Current row has no '{x_column}'; cannot locate the prior year."
            )
        try:
            y_value = int(clean_value(y_raw))
        except ValueError:
            raise ValueError(
                f"Current row's '{y_column}' ({y_raw!r}) is not a whole number; "
                "cannot locate the prior year."
            )
        prior_y = y_value - 1

        # The template is the first row of the current block: everything the
        # new rows carry apart from the hierarchy comes from it.
        cur_start, cur_end = self.group_bounds(self.current_index)
        template = self.df.iloc[cur_start].to_dict()

        y_numbers = pd.to_numeric(self.df[y_column], errors="coerce")
        prior_mask = (self.df[x_column].astype(str).str.strip() == x_value) & (
            y_numbers == prior_y
        )
        prior_indices = self.df.index[prior_mask].tolist()
        if not prior_indices:
            raise ValueError(
                f"No prior-year rows found for {x_column}='{x_value}', "
                f"{y_column}={prior_y}."
            )

        # Take the contiguous block around the first hit, keeping only the
        # rows in it that really are that X and prior Y.
        prior_start, prior_end = self.group_bounds(int(prior_indices[0]))
        prior_block = self.df.iloc[prior_start : prior_end + 1]
        prior_block = prior_block[prior_mask.iloc[prior_start : prior_end + 1]]
        if prior_block.empty:
            raise ValueError(
                f"Found prior-year hits, but no coherent block for "
                f"{x_column}='{x_value}', {y_column}={prior_y}."
            )

        new_rows = []
        for _, prior in prior_block.iterrows():
            r = dict(template)
            for column in hierarchy_cols:
                r[column] = clean_value(prior.get(column))
            r["_gen"] = True
            # A row that has just been created has not been edited by anyone yet.
            r[EDITED_COLUMN] = False
            if clear_helpers:
                # The true/false helper columns: the built-in flag and every
                # checkbox column, which by convention start with "_".
                for column in ("_flag", *self.boolean_columns):
                    if column in r and column.startswith("_"):
                        r[column] = False
            new_rows.append(r)

        # Replace the current block in place, preserving the overall order.
        master_start = self._master_pos(cur_start)
        master_end = self._master_pos(cur_end)
        top = self.master_df.iloc[:master_start]
        bottom = self.master_df.iloc[master_end + 1 :]
        replacement = pd.DataFrame(new_rows)
        self.master_df = pd.concat([top, replacement, bottom], ignore_index=True)

        removed = master_end - master_start + 1
        shift = len(replacement) - removed
        self.view_indices = [
            i + shift if i > master_end else i
            for i in self.view_indices
            if not (master_start <= i <= master_end)
        ]
        for offset in range(len(replacement)):
            self.view_indices.insert(cur_start + offset, master_start + offset)

        # Put cursor on the first row of the rebuilt block
        self.current_index = cur_start
        self._modified = True
        self._rebuild_view()

        self.logger.info(
            f"Added {len(new_rows)} rows by duplicating the prior year for "
            f"{x_column}='{x_value}', {y_column}={y_value}."
        )
        return len(new_rows)

    def clear_restriction(self, mid_path: str = "", sheet_name: str = 0):
        """Clear restriction without reloading from disk (preserves unsaved edits)."""
        if self.master_df is None:
            # fallback: if somehow master_df missing, reload
            if mid_path:
                self.master_df = self.load_mid(mid_path, sheet_name)
        self.view_indices = (
            list(range(len(self.master_df))) if self.master_df is not None else []
        )
        self.current_index = 0
        self._rebuild_view()

    def _master_pos(self, view_pos: int | None = None) -> int | None:
        if view_pos is None:
            view_pos = self.current_index
        if self.df is None or self.df.empty:
            return None
        if not (0 <= view_pos < len(self.view_indices)):
            return None
        return int(self.view_indices[view_pos])

    def _rebuild_view(self):
        self.logger.debug("Rebuilding current view")
        if self.master_df is None:
            self.logger.warning("No master df found! returning null values")
            self.df = None
            self.view_indices = []
            self.current_index = 0
            return
        if not self.view_indices:
            self.logger.warning("view indices undefined, returning empty view")
            self.df = self.master_df.iloc[0:0].copy()
            self.current_index = 0
            return
        self.df = self.master_df.iloc[self.view_indices].reset_index(drop=True)
        self.logger.debug(
            f"Rebuilding view with master df of length {len(self.master_df)} and view indices: {len(self.view_indices)}"
        )
        if self.current_index >= len(self.df):
            self.current_index = max(0, len(self.df) - 1)

    def set_value(self, view_pos: int, col: str, value):
        if self.master_df is None or self.df is None:
            return
        if col == PAGE_COLUMN:
            value = coerce_page(value)
        mpos = self._master_pos(view_pos)
        # Committing the sidebar rewrites every field on every navigation, so
        # only a real change counts as an unsaved edit.
        if col not in self.master_df.columns or self._is_edit(
            self.master_df.at[mpos, col], value
        ):
            self._modified = True
            self._entry_dirty = True
        self._write_cell(self.master_df, mpos, col, value)
        self._write_cell(self.df, view_pos, col, value)

    def pending_changes(self, view_pos: int, values) -> dict:
        """Which of ``values`` would actually change row ``view_pos``.

        Lets a caller decide whether a row is worth writing to at all, rather
        than rewriting every field and discovering afterwards that nothing
        moved.
        """
        mpos = self._master_pos(view_pos)
        if self.master_df is None or mpos is None:
            return {}
        return {
            col: value
            for col, value in dict(values).items()
            if col not in self.master_df.columns
            or self._is_edit(self.master_df.at[mpos, col], value)
        }

    @staticmethod
    def _write_cell(frame, row_label, col, value):
        """Write one cell, widening the column if its dtype cannot hold it.

        pandas 3 gives a column that was read or created as text the ``str``
        dtype, and that dtype refuses a non-string scalar outright. pandas 2
        silently widened such a column to ``object`` instead.

        A MID column legitimately holds both: a user-defined counter column
        is created empty, and so is typed as text until the first number
        lands in it. Rather than pin the application to pandas 2, widen the
        column ourselves and carry on, which is what pandas 2 did on our
        behalf.
        """
        try:
            frame.at[row_label, col] = value
        except (TypeError, ValueError):
            frame[col] = frame[col].astype(object)
            frame.at[row_label, col] = value

    @staticmethod
    def _is_edit(current, value) -> bool:
        """Whether writing ``value`` over ``current`` is a real change.

        A MID is read as text, but the application writes native types back:
        an ``int`` page number landing on the string ``"1"`` is not an edit,
        and neither is a ``bool`` landing on the numpy bool beside it.
        """
        if isinstance(value, bool):
            return bool(current) != value
        if current is None or value is None:
            return current is not value
        return str(current).strip() != str(value).strip()

    def is_modified(self) -> bool:
        """Whether the MID holds edits that have not been written to a file."""
        return self._modified

    def mark_saved(self) -> None:
        self._modified = False

    def mark_modified(self) -> None:
        self._modified = True

    # ------------------------------------------------------------------
    # Per-entry edit tracking
    # ------------------------------------------------------------------
    def entry_is_dirty(self) -> bool:
        """Whether the current row has been changed since it was opened.

        In-memory only, and never written to the MID; the persistent record of
        the same idea is :data:`~mid_schema.EDITED_COLUMN`.
        """
        return self._entry_dirty

    def mark_entry_dirty(self) -> None:
        self._entry_dirty = True

    def clear_entry_dirty(self) -> None:
        self._entry_dirty = False

    def _ensure_edited_column(self) -> None:
        """Guarantee the persistent flag exists, for MIDs saved before it did."""
        for frame in (self.master_df, self.df):
            if frame is not None and EDITED_COLUMN not in frame.columns:
                frame[EDITED_COLUMN] = False

    def is_entry_edited(self, index=None) -> bool:
        """Whether a saved change has ever been made to this row."""
        row = self._resolve_row(index)
        if row is None:
            return False
        return bool(row.get(EDITED_COLUMN, False))

    def set_entry_edited(self, value: bool = True, view_pos: int | None = None) -> bool:
        """Write the persistent edited flag. Returns the value it now holds.

        Deliberately not routed through :meth:`set_value`: the flag records
        that the row was edited, it is not itself one of the row's edits.
        """
        if self.master_df is None:
            return False
        if view_pos is None:
            view_pos = self.current_index
        mpos = self._master_pos(view_pos)
        if mpos is None:
            return False

        self._ensure_edited_column()
        value = bool(value)
        if bool(self.master_df.at[mpos, EDITED_COLUMN]) != value:
            self._modified = True
        self._write_cell(self.master_df, mpos, EDITED_COLUMN, value)
        if self.df is not None and 0 <= view_pos < len(self.df):
            self._write_cell(self.df, view_pos, EDITED_COLUMN, value)
        return value

    def toggle_entry_edited(self, view_pos: int | None = None) -> bool:
        """Flip the persistent edited flag. Returns the value it now holds."""
        if view_pos is None:
            view_pos = self.current_index
        return self.set_entry_edited(not self.is_entry_edited(view_pos), view_pos)

    def first_unedited_index(self, start: int = 0) -> int | None:
        """View position of the first row at or after ``start`` not yet edited.

        ``None`` when every row from ``start`` onwards has been edited.
        """
        if self.df is None or self.df.empty:
            return None
        self._ensure_edited_column()
        for view_pos in range(max(0, int(start)), len(self.df)):
            if not bool(self.df.at[view_pos, EDITED_COLUMN]):
                return view_pos
        return None

    def unedited_count(self) -> int:
        """How many rows in the current view have never been edited."""
        if self.df is None or self.df.empty:
            return 0
        self._ensure_edited_column()
        return int((~self.df[EDITED_COLUMN].astype(bool)).sum())
