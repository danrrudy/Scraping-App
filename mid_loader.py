# mid_loader.py

import pandas as pd
from logger import setup_logger

EXPECTED_COLUMNS = [
    "agency_yr", "agency", "year", "agid", "subagency", "stratobj",
    "obj", "goal", "metric", "PDF Page Number", "Format", "Format_Detail",
    "Results_DisplayFormat", "Table Name/Word Search Keyword",
    "Other Detail", "Format_Type"
]

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

def load_mid(path, sheet_name=0):
    logger = setup_logger()
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
