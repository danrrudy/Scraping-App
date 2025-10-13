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
    "_future_dated": bool
}

# Heirarchy Definition
LEVELS = ["stratobj", "obj", "goal", "metric"]



class MIDManager:
    def __init__(self, path, sheet_name=0):
        self.logger = setup_logger()
        self.df = self.load_mid(path, sheet_name)
        self.current_index = 0
        self.logger.info("Initialized MIDManager")

    def load_mid(self, path, sheet_name=0):
        """Loads and validates the Master Input Document (MID) Excel file."""
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)  # Read all as string first
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
        if self.df is not None and 0 <= self.current_index < len(self.df):
            return self.df.iloc[self.current_index]
        else:
            return None

    # Allow next_ and prev_mid_entry to run over by 1 so that get_current_row can return None when the end is reached
    def next_mid_entry(self):
        if self.df is not None and self.current_index < len(self.df):
            self.current_index += 1

    def prev_mid_entry(self):
        if self.df is not None and self.current_index >= 0:
            self.current_index -= 1

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
    def restrict_to_rows(self, row_indices):
        """Restrict MID to a subset of row indices for focused review."""
        self.df = self.df.iloc[row_indices].reset_index(drop=True)
        self.current_index = 0

    # Heirarchy Helpers

    def _has_val(self, row, key:str) -> bool:
        v = row.get(key, None)
        if isinstance(v, float) and pd.insa(v):
            return False
        return bool(str(v).strip()) if v is not None else False


    def lowest_present_level(self, row: dict) -> str | None:
        """
        Return the lowest level that already has a value on this row.
        E.g., if metric present -> 'metric'; elif goal -> 'goal'; elif obj -> 'obj';
        elif stratobj -> 'stratobj'; else None.
        """
        for key in reversed(LEVELS):  # metric -> goal -> obj -> stratobj
            if self._has_val(row, key):
                return key
        return None

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
        Insert new_row after position after_pos, return the new absolute index.
        Preserves ordering by reindexing.
        """
        top = self.df.iloc[: after_pos + 1]
        bottom = self.df.iloc[after_pos + 1 :]
        new_df = pd.concat([top, pd.DataFrame([new_row]), bottom], ignore_index=True)
        self.df = new_df
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

