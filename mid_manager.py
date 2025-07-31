# mid_manager.py

import pandas as pd
import re
from logger import setup_logger


# Expected structure for the MID
EXPECTED_COLUMNS = [
    "agency_yr", "agency", "year", "agid", "subagency", "stratobj",
    "obj", "goal", "metric", "PDF Page Number", "Format", "Format_Detail",
    "Results_DisplayFormat", "Table Name/Word Search Keyword",
    "Other Detail", "Format_Type"
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
    "Format_Type": int
}

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
