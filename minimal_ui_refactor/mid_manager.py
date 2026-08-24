# mid_manager.py

import re

import pandas as pd
from logger import setup_logger
from mid_schema import (
    EDITED_COLUMN,
    LEGACY_HIERARCHY_COLUMNS,
    LEGACY_SOURCE_COLUMNS,
    MIDSchema,
    WORKFLOW_COLUMN_DEFAULTS,
    clean_value,
    normalize_sheet_name,
)

# Expected structure for the MID
# Compatibility exports for legacy plugins/tests. MIDManager no longer requires
# these columns unless they are selected by the active MIDSchema.
EXPECTED_COLUMNS = list(LEGACY_SOURCE_COLUMNS)


# Ensure columns are properly typecast
COLUMN_TYPES = {
    "agency_yr": str,
    "agency": str,
    "year": int,
    "agid": int,
    "subagency": str,
    "stratobj": str,
    "obj": str,
    "goal": str,
    "metric": str,
    "PDF Page Number": str,
    "Format": str,
    "Format_Detail": str,
    "Results_DisplayFormat": str,
    "Table Name/Word Search Keyword": str,
    "Other Detail": str,
    "Format_Type": int,
    "Format_Type_Updated": int,
    "_flag": bool,
    "_achieved": bool,
    "_aggregate": bool,
    "_future_dated": bool,
    "Class": int,
    "target": str,
    "actual": str,
    "years_to_evaluation": str,  # accepts str or int, ints are parsed out internally for consistency
    "reviewer_status": str,
    "Page": int,
    "_edited": bool,
}

# Heirarchy Definition
LEVELS = list(LEGACY_HIERARCHY_COLUMNS)


class MIDManager:
    def __init__(self, path, sheet_name=0, schema=None, boolean_columns=()):
        """``boolean_columns`` are extra true/false columns to guarantee.

        User-defined checkboxes name their own MID columns, which the sheet
        will not have the first time they are used.
        """
        self.logger = setup_logger()
        self.schema = schema or MIDSchema.legacy()
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

        # Keep generic source values predictable. Domain-specific type coercion
        # can be added later without making the loader schema-specific again.
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
        """Rows whose (document, X, Y) identity is shared with another row.

        Reported, never fatal: identifiers are assigned inside the app, so a
        MID saved mid-assignment would otherwise refuse to reopen. Rows with
        any blank identity value are unassigned, not duplicates.

        The legacy MID deliberately repeats its identity across hierarchy
        rows, so it is exempt.
        """
        blank = pd.Series(False, index=df.index)
        columns = list(self.schema.uniqueness_columns)
        if not columns or self.schema == MIDSchema.legacy():
            return blank
        if not self.schema.identifier_columns:
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
            if column in new_row and column != "Page":
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
        # if self.df is not None and 0 <= self.current_index < len(self.df):
        #     return self.df.iloc[self.current_index]
        # else:
        #     return None

    # Allow next_ and prev_mid_entry to run over by 1 so that get_current_row can return None when the end is reached
    def next_mid_entry(self):
        if self.view_indices and self.current_index < len(self.view_indices):
            self.current_index += 1

    def prev_mid_entry(self):
        if self.view_indices and self.current_index >= 0:
            self.current_index -= 1

    # def next_mid_entry(self):
    #     if self.df is not None and self.current_index < len(self.df):
    #         self.current_index += 1

    # def prev_mid_entry(self):
    #     if self.df is not None and self.current_index >= 0:
    #         self.current_index -= 1

    def select_mid_entry(self, index=None):
        if self.df is not None and index is not None and 0 <= index < len(self.df):
            self.current_index = index

    # Parse the 'PDF Page Number' field into a list of zero-indexed page numbers
    # Removes leading p. and expands ranges into a list of integers (inclusive)
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

    # Only show the rows passed in as an argument (for dev mode)
    # def restrict_to_rows(self, row_indices):
    #     """Restrict MID to a subset of row indices for focused review."""
    #     self.df = self.df.iloc[row_indices].reset_index(drop=True)
    #     self.current_index = 0
    def restrict_to_rows(self, row_indices):
        """Restrict MID to a subset of *master* row positions for focused review."""
        # row_indices are master positional indices (iloc positions)
        self.view_indices = [int(i) for i in row_indices]
        self.current_index = 0
        self._rebuild_view()

    # Heirarchy Helpers

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

    def clone_for_child(self, parent_idx: int, child_level: str) -> dict:
        """
        Copy the parent row, clear all levels at or below the child_level.
        Also mark as generated.
        """
        self._require_legacy_hierarchy()
        parent = self.df.iloc[parent_idx].to_dict()
        assert child_level in LEVELS, f"Unknown child level: {child_level}"
        # Determine which keys to clear
        level_pos = LEVELS.index(child_level)
        to_clear = LEVELS[level_pos:]  # e.g., child_level='goal' clears goal+metric
        new_row = parent.copy()
        for k in to_clear:
            new_row[k] = ""
        new_row["_gen"] = True  # mark programmatically generated rows
        for k in ["metric_status", "target", "actual", "years_to_evaluation"]:
            if k in new_row:
                new_row[k] = ""

        if "_achieved" in new_row:
            new_row["_achieved"] = False
        if "_future_dated" in new_row:
            new_row["_future_dated"] = False
        # A row that has just been created has not been edited by anyone yet.
        new_row[EDITED_COLUMN] = False
        return new_row

    def ensure_gen_flag(self):
        if "_gen" not in self.master_df.columns:
            self.master_df["_gen"] = False
        if "_gen" not in self.df.columns:
            self.df["_gen"] = False

    def _require_legacy_hierarchy(self):
        if not self.schema.is_legacy_hierarchy_compatible(self.df.columns):
            raise ValueError(
                "This operation belongs to the legacy hierarchy and is not "
                "available for the configured generic MID."
            )

    def next_seed_row_index(self, from_idx: int) -> int | None:
        """
        Find the next non-generated row after from_idx; return None if none.
        """
        self.ensure_gen_flag()
        for k in range(from_idx + 1, len(self.df)):
            if not bool(self.df.at[k, "_gen"]):
                return k
        return None

    def find_parent_for_goal(self, idx: int) -> int | None:
        """Find Objective header row (same agency_yr, same SO+OBJ, goal == '')."""
        self._require_legacy_hierarchy()
        if idx is None or self.df is None or self.df.empty:
            return None
        key = self.get_group_key(idx)
        so = str(self.df.at[idx, "stratobj"]).strip()
        obj = str(self.df.at[idx, "obj"]).strip()
        i = idx
        while i >= 0 and self.get_group_key(i) == key:
            if (
                str(self.df.at[i, "stratobj"]).strip() == so
                and str(self.df.at[i, "obj"]).strip() == obj
            ):
                if str(self.df.at[i, "goal"]).strip() == "":
                    return i
            i -= 1
        return None

    def find_parent_for_obj(self, idx: int) -> int | None:
        """Find Strategic Objective header row (same agency_yr, same SO, obj == '')."""
        self._require_legacy_hierarchy()
        if idx is None or self.df is None or self.df.empty:
            return None
        key = self.get_group_key(idx)
        so = str(self.df.at[idx, "stratobj"]).strip()
        i = idx
        while i >= 0 and self.get_group_key(i) == key:
            if (
                str(self.df.at[i, "stratobj"]).strip() == so
                and str(self.df.at[i, "obj"]).strip() == ""
            ):
                return i
            i -= 1
        return None

    def propagate_flag_from_index(self, idx: int, flagged: bool = True):
        """
        Set _flag on the current row and all its descendants within the same agency_yr.
        Descendants are determined by matching the present parent keys on idx.
        - If only stratobj is set => flag all rows with same stratobj (this SO and below)
        - If stratobj+obj set, goal empty => flag same (so,obj) subtree
        - If stratobj+obj+goal set => flag same (so,obj,goal) subtree
        """
        self._require_legacy_hierarchy()
        if self.df is None or idx is None:
            return
        if "_flag" not in self.df.columns:
            self.df["_flag"] = False

        key = self.get_group_key(idx)

        so = str(self.df.at[idx, "stratobj"]).strip()
        obj = str(self.df.at[idx, "obj"]).strip()
        goal = str(self.df.at[idx, "goal"]).strip()

        # Compute match depth
        def matches(i: int) -> bool:
            if self.get_group_key(i) != key:
                return False
            if so and str(self.df.at[i, "stratobj"]).strip() != so:
                return False
            if obj and str(self.df.at[i, "obj"]).strip() != obj:
                return False
            if goal and str(self.df.at[i, "goal"]).strip() != goal:
                return False
            return True

        # Apply to all rows in this group
        for i in range(len(self.df)):
            if matches(i):
                self.set_value(i, "_flag", flagged)

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
        """
        For the currently selected row (self.current_index), duplicate the prior year's
        hierarchy (stratobj/obj/goal/metric) rows into the current agency-year.

        - Copies the number of rows and only stratobj/obj/goal/metric from prior year.
        - Preserves all other fields from the current agency-year template row.
        - Replaces the entire current agency_yr contiguous block with the new block.
        - Returns the number of rows created.

        Raises:
            ValueError if agency/year not available or prior-year block not found.
        """
        self._require_legacy_hierarchy()
        if self.df is None or self.df.empty:
            raise ValueError("MID is empty; nothing to duplicate.")

        if self.current_index is None or not (0 <= self.current_index < len(self.df)):
            raise ValueError("current_index is invalid.")

        cur_row = self.df.iloc[self.current_index]
        agency = str(cur_row.get("agency", "")).strip()
        year_raw = cur_row.get("year", None)

        if not agency:
            raise ValueError("Current row has no 'agency'; cannot locate prior year.")

        try:
            year = int(str(year_raw).strip())
        except Exception:
            raise ValueError(
                f"Current row has invalid 'year' ({year_raw}); cannot locate prior year."
            )

        prior_year = year - 1

        # --- Identify current agency_yr contiguous block (template comes from its first row) ---
        cur_start, cur_end = self.group_bounds(self.current_index)
        template = self.df.iloc[cur_start].to_dict()

        # --- Find prior-year rows for same agency ---
        # Prefer exact match on agency+year (more robust than guessing agency_yr string format).
        prior_mask = (self.df["agency"].astype(str).str.strip() == agency) & (
            pd.to_numeric(self.df["year"], errors="coerce").fillna(-1).astype(int)
            == prior_year
        )
        prior_indices = self.df.index[prior_mask].tolist()
        if not prior_indices:
            raise ValueError(
                f"No prior-year rows found for agency='{agency}', year={prior_year}."
            )

        # If there are multiple disjoint blocks for that agency-year, select the block containing the first match
        # and then expand to its contiguous bounds.
        prior_seed = int(prior_indices[0])
        prior_start, prior_end = self.group_bounds(prior_seed)

        # Sanity: ensure the contiguous block is actually the same agency+prior_year throughout.
        # If not, shrink to only the matching rows within that contiguous range.
        prior_block = self.df.iloc[prior_start : prior_end + 1].copy()
        prior_block = prior_block[
            (prior_block["agency"].astype(str).str.strip() == agency)
            & (
                pd.to_numeric(prior_block["year"], errors="coerce")
                .fillna(-1)
                .astype(int)
                == prior_year
            )
        ]

        if prior_block.empty:
            raise ValueError(
                f"Found prior-year hits, but no coherent block for agency='{agency}', year={prior_year}."
            )

        # Extract the hierarchy fields to copy
        hierarchy_cols = ["stratobj", "obj", "goal", "metric"]
        prior_hierarchy = (
            prior_block[hierarchy_cols].fillna("").astype(str).values.tolist()
        )

        # --- Build replacement block for current agency-year ---
        new_rows = []
        for so, obj, goal, metric in prior_hierarchy:
            r = template.copy()
            r["agency"] = agency
            r["year"] = year
            r["agency_yr"] = (
                str(template.get("agency_yr", "")).strip()
                or str(cur_row.get("agency_yr", "")).strip()
            )

            r["stratobj"] = str(so or "")
            r["obj"] = str(obj or "")
            r["goal"] = str(goal or "")
            r["metric"] = str(metric or "")

            # Mark generated rows (your code already uses _gen in multiple places)
            r["_gen"] = True
            # A row that has just been created has not been edited by anyone yet.
            r[EDITED_COLUMN] = False

            if clear_helpers:
                # Clear common workflow/helper fields if present; keep non-hierarchy metadata intact.
                for k in [
                    "metric_status",
                    "_flag",
                    "_achieved",
                    "_future_dated",
                    "_no_metrics",
                ]:
                    if k in r:
                        r[k] = "" if k == "metric_status" else False

            new_rows.append(r)

        # --- Replace the current block in-place (preserve overall row ordering) ---

        master_start = self._master_pos(cur_start)
        master_end = self._master_pos(cur_end)

        top = self.master_df.iloc[: master_start + 1].copy()
        bottom = self.master_df.iloc[master_end + 1 :].copy()
        replacement = pd.DataFrame(new_rows)

        # top = self.master_df.iloc[: insert_after_master + 1]
        # bottom = self.master_df.iloc[insert_after_master + 1 :]
        # self.master_df = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)

        self.master_df = pd.concat([top, replacement, bottom], ignore_index=True)
        self.logger.debug(f"view indices before insertion: {self.view_indices}")
        self.logger.debug(
            f"master_df indices after insertion: {self.master_df.index.tolist()}"
        )
        self.view_indices = [
            (i + len(replacement)) if i >= master_end else i for i in self.view_indices
        ]

        for i in list(range(len(replacement))):
            new_master_pos = master_start + i
            self.view_indices.insert(master_start + i, new_master_pos)

        self.logger.debug(
            f"Shifted view indices after master replacement: {self.view_indices}"
        )
        # Put cursor on the first row of the rebuilt block
        self.current_index = cur_start

        self._rebuild_view()

        self.logger.info(
            f"Added {len(new_rows)} rows by duplicating prior year for agency='{agency}', year={year}."
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
            self.logger.warning("view indices undefined, returning masteer df")
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
        mpos = self._master_pos(view_pos)
        # Committing the sidebar rewrites every field on every navigation, so
        # only a real change counts as an unsaved edit.
        if col not in self.master_df.columns or self._is_edit(
            self.master_df.at[mpos, col], value
        ):
            self._modified = True
            self._entry_dirty = True
        self.master_df.at[mpos, col] = value
        self.df.at[view_pos, col] = value

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
        self.master_df.at[mpos, EDITED_COLUMN] = value
        if self.df is not None and 0 <= view_pos < len(self.df):
            self.df.at[view_pos, EDITED_COLUMN] = value
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
