# mid_manager.py

import pandas as pd
import re
from logger import setup_logger


# Expected structure for the MID
EXPECTED_COLUMNS = [
    "agency_yr", "agency", "year", "agid", "subagency", "stratobj",
    "obj", "goal", "metric", "PDF Page Number", "Format", "Format_Detail",
    "Results_DisplayFormat", "Table Name/Word Search Keyword",
    "Other Detail", "Format_Type", "Format_Type_Updated"
]


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
    "years_to_evaluation": str,             # accepts str or int, ints are parsed out internally for consistency
    "reviewer_status": str,
}

# Heirarchy Definition
LEVELS = ["stratobj", "obj", "goal", "metric"]



class MIDManager:
    def __init__(self, path, sheet_name=0):
        self.logger = setup_logger()
        df = self.load_mid(path, sheet_name)
        self.master_df = df
        self.view_indices = list(range(len(df)))
        self.df = df.copy()
        self.current_index = 0
        self.logger.info("Initialized MIDManager")

    def load_mid(self, path, sheet_name=0):
        """Loads and validates the Master Input Document (MID) Excel file."""
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, dtype=str, keep_default_na=False)  # Read all as string first
        except Exception as e:
            raise RuntimeError(f"Failed to load MID file: {e}")

        missing = [col for col in EXPECTED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"MID file is missing required columns: {missing}")

        # Cast columns to correct types
        for col, col_type in COLUMN_TYPES.items():
            if col in df.columns:
                try:
                    if col_type is int:
                        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
                    elif col_type is bool:
                        df[col] = df[col].astype(str).str.strip() == "True"
                    else:
                        df[col] = df[col].fillna("").astype(str).str.strip()

                except Exception as e:
                    raise ValueError(f"Failed to cast column '{col}' to {col_type}: {e}")

        return df

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
        if self.df is not None and index <= len(self.df) and index > 0:
            self.current_index = index

    # Parse the 'PDF Page Number' field into a list of zero-indexed page numbers
    # Removes leading p. and expands ranges into a list of integers (inclusive)
    def parse_pdf_pages(self, index=None):
        row = self.get_current_row() if index is None else self.df.iloc[index]
        # Pull the plain text entry and remove whitespace
        page_field = str(row.get("PDF Page Number", "")).strip()

        if not page_field:
            self.logger.warning(f"No page field listed for {row.get("agency_yr","")} on line {str(index)}")
            return []

        self.logger.debug(f"parsing {page_field}")
        page_field = page_field.lower().replace("p.", "")

        # pages is the empty array that the individual document pages will be loaded into
        pages = []

        try:
            # Match comma-separated values like "p.3, p.5-7"
            for part in re.split(r"[,\s]+", page_field):
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    pages.extend(range(start - 1, end))  # zero-indexed
                    self.logger.debug(f"Page range: {start} - {end}")
                elif part.isdigit():
                    pages.append(int(part) - 1)
                    self.logger.debug(f"Single page: {int(part)}")
        except Exception as e:
            self.logger.warning(f"Failed to parse page numbers from '{page_field}': {e}")
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



    def get_group_key(self, idx: int) -> str:
        """Group rows by the agency_yr string."""
        return str(self.df.at[idx, "agency_yr"])

    def group_bounds(self, idx: int) -> tuple[int, int]:
        """
        Return (start, end_inclusive) bounds of the contiguous block of rows
        sharing the same agency_yr as row idx.
        """
        if self.df is None or self.df.empty:
            return (0, -1)
        key = self.get_group_key(idx)
        s = self.df.index.min()
        e = self.df.index.max()
        # expand upward
        i = idx
        while i - 1 >= s and str(self.df.at[i - 1, "agency_yr"]) == key:
            i -= 1
        start = i
        # expand downward
        j = idx
        while j + 1 <= e and str(self.df.at[j + 1, "agency_yr"]) == key:
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
        self.master_df = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)

        new_master_pos = insert_after_master + 1

        # shift existing mapped indices that occur after insertion
        self.view_indices = [
            (i + 1) if i >= new_master_pos else i
            for i in self.view_indices
        ]

        # insert new row into the view right after after_pos
        self.view_indices.insert(after_pos + 1, new_master_pos)

        self._rebuild_view()
        return after_pos + 1


    def clone_for_child(self, parent_idx: int, child_level: str) -> dict:
        """
        Copy the parent row, clear all levels at or below the child_level.
        Also mark as generated.
        """
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

        if "_achieved" in new_row: new_row["_achieved"] = False
        if "_future_dated" in new_row: new_row["_future_dated"] = False
        return new_row

    def ensure_gen_flag(self):
        if "_gen" not in self.df.columns:
            self.df["_gen"] = False

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
        if idx is None or self.df is None or self.df.empty: return None
        key = self.get_group_key(idx)
        so = str(self.df.at[idx, "stratobj"]).strip()
        obj = str(self.df.at[idx, "obj"]).strip()
        i = idx
        while i >= 0 and str(self.df.at[i, "agency_yr"]) == key:
            if str(self.df.at[i, "stratobj"]).strip() == so and str(self.df.at[i, "obj"]).strip() == obj:
                if str(self.df.at[i, "goal"]).strip() == "":
                    return i
            i -= 1
        return None

    def find_parent_for_obj(self, idx: int) -> int | None:
        """Find Strategic Objective header row (same agency_yr, same SO, obj == '')."""
        if idx is None or self.df is None or self.df.empty: return None
        key = self.get_group_key(idx)
        so = str(self.df.at[idx, "stratobj"]).strip()
        i = idx
        while i >= 0 and str(self.df.at[i, "agency_yr"]) == key:
            if str(self.df.at[i, "stratobj"]).strip() == so and str(self.df.at[i, "obj"]).strip() == "":
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
        if self.df is None or idx is None: return
        if "_flag" not in self.df.columns:
            self.df["_flag"] = False

        key = self.get_group_key(idx)

        so   = str(self.df.at[idx, "stratobj"]).strip()
        obj  = str(self.df.at[idx, "obj"]).strip()
        goal = str(self.df.at[idx, "goal"]).strip()

        # Always flag current row
        self.df.at[idx, "_flag"] = flagged

        # Compute match depth
        def matches(i: int) -> bool:
            if str(self.df.at[i, "agency_yr"]) != key:
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
                self.df.at[i, "_flag"] = flagged

    def delete_current_row(self):
        if self.master_df is None or self.df is None or self.df.empty:
            return
        if not (0 <= self.current_index < len(self.df)):
            return

        del_master_pos = self._master_pos(self.current_index)

        # delete from master
        self.master_df = self.master_df.drop(self.master_df.index[del_master_pos]).reset_index(drop=True)

        # remove from view mapping and shift indices after deleted row
        del self.view_indices[self.current_index]
        self.view_indices = [
            (i - 1) if i > del_master_pos else i
            for i in self.view_indices
        ]

        if self.current_index >= len(self.view_indices):
            self.current_index = max(0, len(self.view_indices) - 1)

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
            raise ValueError(f"Current row has invalid 'year' ({year_raw}); cannot locate prior year.")

        prior_year = year - 1

        # --- Identify current agency_yr contiguous block (template comes from its first row) ---
        cur_start, cur_end = self.group_bounds(self.current_index)
        template = self.df.iloc[cur_start].to_dict()

        # --- Find prior-year rows for same agency ---
        # Prefer exact match on agency+year (more robust than guessing agency_yr string format).
        prior_mask = (self.df["agency"].astype(str).str.strip() == agency) & (
            pd.to_numeric(self.df["year"], errors="coerce").fillna(-1).astype(int) == prior_year
        )
        prior_indices = self.df.index[prior_mask].tolist()
        if not prior_indices:
            raise ValueError(f"No prior-year rows found for agency='{agency}', year={prior_year}.")

        # If there are multiple disjoint blocks for that agency-year, select the block containing the first match
        # and then expand to its contiguous bounds.
        prior_seed = int(prior_indices[0])
        prior_start, prior_end = self.group_bounds(prior_seed)

        # Sanity: ensure the contiguous block is actually the same agency+prior_year throughout.
        # If not, shrink to only the matching rows within that contiguous range.
        prior_block = self.df.iloc[prior_start : prior_end + 1].copy()
        prior_block = prior_block[
            (prior_block["agency"].astype(str).str.strip() == agency)
            & (pd.to_numeric(prior_block["year"], errors="coerce").fillna(-1).astype(int) == prior_year)
        ]

        if prior_block.empty:
            raise ValueError(f"Found prior-year hits, but no coherent block for agency='{agency}', year={prior_year}.")

        # Extract the hierarchy fields to copy
        hierarchy_cols = ["stratobj", "obj", "goal", "metric"]
        prior_hierarchy = prior_block[hierarchy_cols].fillna("").astype(str).values.tolist()

        # --- Build replacement block for current agency-year ---
        new_rows = []
        for so, obj, goal, metric in prior_hierarchy:
            r = template.copy()
            r["agency"] = agency
            r["year"] = year
            r["agency_yr"] = str(template.get("agency_yr", "")).strip() or str(cur_row.get("agency_yr", "")).strip()

            r["stratobj"] = str(so or "")
            r["obj"] = str(obj or "")
            r["goal"] = str(goal or "")
            r["metric"] = str(metric or "")

            # Mark generated rows (your code already uses _gen in multiple places)
            r["_gen"] = True

            if clear_helpers:
                # Clear common workflow/helper fields if present; keep non-hierarchy metadata intact.
                for k in ["metric_status", "_flag", "_achieved", "_future_dated", "_no_metrics"]:
                    if k in r:
                        r[k] = "" if k == "metric_status" else False

            new_rows.append(r)

        # --- Replace the current block in-place (preserve overall row ordering) ---

        master_start = self._master_pos(cur_start)
        master_end = self._master_pos(cur_end)

        top = self.master_df.iloc[:master_start+1].copy()
        bottom = self.master_df.iloc[master_end + 1 :].copy()
        replacement = pd.DataFrame(new_rows)


        # top = self.master_df.iloc[: insert_after_master + 1]
        # bottom = self.master_df.iloc[insert_after_master + 1 :]
        # self.master_df = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)

        self.master_df = pd.concat([top, replacement, bottom], ignore_index=True)
        self.logger.debug(f"view indices before insertion: {self.view_indices}")
        self.logger.debug(f"master_df indices after insertion: {self.master_df.index.tolist()}")
        self.view_indices = [
            (i + len(replacement)) if i >= master_end else i
            for i in self.view_indices
        ]

        for i in list(range(len(replacement))):
            new_master_pos = master_start + i
            self.view_indices.insert(master_start + i, new_master_pos)

        self.logger.debug(f"Shifted view indices after master replacement: {self.view_indices}")
        # Put cursor on the first row of the rebuilt block
        self.current_index = cur_start

        self._rebuild_view()

        self.logger.info(f"Added {len(new_rows)} rows by duplicating prior year for agency='{agency}', year={year}.")
        return len(new_rows)

    def clear_restriction(self, mid_path: str = "", sheet_name: str = 0):
        """Clear restriction without reloading from disk (preserves unsaved edits)."""
        if self.master_df is None:
            # fallback: if somehow master_df missing, reload
            if mid_path:
                self.master_df = self.load_mid(mid_path, sheet_name)
        self.view_indices = list(range(len(self.master_df))) if self.master_df is not None else []
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
        self.logger.debug(f"Rebuilding view with master df of length {len(self.master_df)} and view indices: {len(self.view_indices)}")
        if self.current_index >= len(self.df):
            self.current_index = max(0, len(self.df) - 1)

    def set_value(self, view_pos: int, col: str, value):
        if self.master_df is None or self.df is None:
            return
        mpos = self._master_pos(view_pos)
        self.master_df.at[mpos, col] = value
        self.df.at[view_pos, col] = value




