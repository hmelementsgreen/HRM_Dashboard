"""
Load leave entitlement from BrightHR Holiday Summary Report (Days).
Supports Excel and CSV. Uses column "Holiday Entitlement (including Carry Over)".
Matches employee by First + Middle + Last name.
"""
import os
import pandas as pd

LEAVE_YEAR_START = pd.Timestamp("2026-01-01")
ENTITLEMENT_COL = "Holiday Entitlement (including Carry Over)"

# Rows where the built "employee" name matches these (case-insensitive) are dropped as metadata, not people.
HOLIDAY_SUMMARY_NON_EMPLOYEE = frozenset({
    "company",
    "current holiday year",
    "elements green ltd",
    "first name last name",
    "holiday summary report",
    "period time run",
})
# Explicit exclusions by request (exact match on full name, case-insensitive).
HOLIDAY_SUMMARY_EXCLUDED_EMPLOYEES = frozenset({
    "dilara kamphuis",
    "toby roberts",
})


def _is_non_employee_row(employee_str):
    """True if this string is known report metadata/headers, not an employee name."""
    if not employee_str or not isinstance(employee_str, str):
        return True
    key = employee_str.strip().lower()
    if not key:
        return True
    if key in HOLIDAY_SUMMARY_NON_EMPLOYEE or key in HOLIDAY_SUMMARY_EXCLUDED_EMPLOYEES:
        return True
    for bad in HOLIDAY_SUMMARY_NON_EMPLOYEE:
        if bad in key:  # e.g. "current holiday year 2:41:37 pm"
            return True
    # Drop rows that look like report titles (e.g. "Holiday Summary Report (Hours)")
    if "holiday summary" in key or "report (hours)" in key or "report (days)" in key:
        return True
    if key.startswith("period time run") or "gmt/utc" in key:
        return True
    return False


def _safe_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _normalize_employee(first, last, middle=None):
    """Build employee name: First Middle Last (matches absence data format)."""
    parts = [_safe_str(first), _safe_str(middle), _safe_str(last)]
    return " ".join(p for p in parts if p)


def _find_header_row(df_raw):
    """Find row index where 'First Name' and entitlement column appear."""
    for i, row in df_raw.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if "first name" in row_str and "holiday entitlement" in row_str:
            return i
    return None


def load_holiday_summary(path):
    """
    Load Holiday Summary Report and extract employee -> entitlement mapping.
    Uses column "Holiday Entitlement (including Carry Over)".
    Returns (df_entitlement, err_msg). df_entitlement has columns: employee, Team, entitlement.
    """
    if not path or not os.path.isfile(path):
        return None, f"File not found: {path}"

    path_lower = path.strip().lower()
    try:
        if path_lower.endswith(".csv"):
            df_raw = pd.read_csv(path, header=None)
        else:
            df_raw = pd.read_excel(path, engine="openpyxl", header=None)
    except Exception as e:
        return None, str(e)

    if df_raw.empty:
        return None, "File is empty"

    # Find header row (BrightHR has metadata rows before header)
    header_idx = _find_header_row(df_raw)
    if header_idx is not None:
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = df_raw.iloc[header_idx].astype(str).str.strip()
    else:
        df = df_raw.copy()
        df.columns = [str(c).strip() for c in df.columns]

    df.columns = [str(c).strip() for c in df.columns]
    cols_lower = {c.lower(): c for c in df.columns}

    # Build employee name (First + Middle + Last)
    first_col = next((cols_lower[k] for k in ["first name", "firstname"] if k in cols_lower), None)
    last_col = next((cols_lower[k] for k in ["last name", "lastname"] if k in cols_lower), None)
    middle_col = next((cols_lower[k] for k in ["middle name", "middlename"] if k in cols_lower), None)

    if not first_col or not last_col:
        return None, "Could not find First Name and Last Name columns"

    df["employee"] = df.apply(
        lambda r: _normalize_employee(r.get(first_col), r.get(last_col), r.get(middle_col)),
        axis=1,
    )
    df["employee"] = df["employee"].str.strip()
    df = df[df["employee"] != ""]
    # Drop rows that are report metadata/headers (Company, First Name Last Name, Holiday Summary Report, etc.)
    df = df[~df["employee"].apply(_is_non_employee_row)]

    # Team
    team_col = next((cols_lower[k] for k in ["team(s)", "team", "teams"] if k in cols_lower), None)
    df["Team"] = df[team_col].fillna("").astype(str).str.strip() if team_col else ""

    # Entitlement: use exact column "Holiday Entitlement (including Carry Over)"
    ent_col = next((c for c in df.columns if "holiday entitlement" in c.lower() and "carry over" in c.lower()), None)
    if not ent_col:
        ent_col = next((c for c in df.columns if "holiday entitlement" in c.lower()), None)
    if not ent_col:
        return None, f"Could not find column '{ENTITLEMENT_COL}'"

    df["entitlement"] = pd.to_numeric(df[ent_col], errors="coerce").fillna(0)
    df["entitlement"] = df["entitlement"].apply(lambda x: round(x * 2) / 2 if pd.notna(x) else 0)  # round to 0.5

    # employee_short = First + Last (no middle) for matching with absence data
    df["employee_short"] = (df[first_col].apply(_safe_str) + " " + df[last_col].apply(_safe_str)).str.strip()

    out = df[["employee", "Team", "entitlement", "employee_short"]].copy()
    out = out.drop_duplicates(subset=["employee"], keep="first")
    return out, None
