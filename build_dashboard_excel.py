"""
Build one Excel workbook with two refined sheets (same data as fed into the dashboard):
  - Sheet "Absence": processed absence/leave data
  - Sheet "BLIP": processed BLIP time & attendance data

Usage:
  python build_dashboard_excel.py [--absence-csv PATH] [--blip PATH] [--out PATH]

Output: Variance_Excel.xlsx (or --out path).
"""
import os
import argparse
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ABSENCE_CSV = os.path.join(_PROJECT_ROOT, "AbsenseReport_Cleaned_Final.csv")
DEFAULT_BLIP = os.path.join(_PROJECT_ROOT, "blip_cumulative.csv")
DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "Variance_Excel.xlsx")
LEAVE_YEAR_START = pd.Timestamp("2026-01-01")
METRIC_COL = "Absence duration for period in days"
ENTITLEMENT_DAYS_COL = "leave_entitlement_days"
# Leave types (same order as dashboard)
LEAVE_TYPES = [
    "Annual Leave",
    "WFH",
    "Medical + Sickness",
    "External & additional assignments",
    "Other (excl. WFH, Travel)",
]
# Manual overrides when Absence has blank/wrong Team or Country and employee is not in BLIP (normalized name -> (team, country))
TEAM_COUNTRY_OVERRIDES = {
    "Lydia Kerbel": ("DE BDM", "Germany"),
}

# Exact column order for Employees sheet
EMPLOYEE_SHEET_COLUMNS = [
    "Employee",
    "Team",
    "Country",
    "Leave Allowance",
    "Leave taken",
    "Annual Leave",
    "WFH",
    "Medical + Sickness",
    "External & additional assignments",
    "Other (excl. WFH, Travel)",
    "Worked hours",
]


def _normalize_employee(s):
    return " ".join(str(s).strip().split()) if s else ""


def _first_last(s):
    """Reduce to First + Last name for matching (avoids duplicate rows from middle names)."""
    parts = str(s).strip().split() if s else []
    if len(parts) >= 2:
        return parts[0] + " " + parts[-1]
    return parts[0] if parts else ""


# Exclude these employees from the dashboard (First + Last name, case-insensitive match after normalize).
EXCLUDED_EMPLOYEES = frozenset(
    {s.strip().lower() for s in [
        "First Name Last Name",  # Header/placeholder that appeared as a row
    ] if s and s.strip()}
)


def _round_to_half(x):
    """Round to nearest 0.5 (whole or half only)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return x
    return round(v * 2) / 2


def build_employee_summary(df_absence, df_blip, df_entitlement=None):
    """
    One row per employee. Columns: Employee, Team, Country, Working days per week,
    Leave Allowance, Leave taken, leave splits (Annual Leave, WFH, WFH allowed, ...),
    Worked hours, Worked daily avg.
    When df_entitlement is provided (from Holiday Summary Report), use it for Leave Allowance.
    """
    # All unique employees by First+Last only (avoid duplicates from middle name)
    emp_abs = df_absence["employee"].dropna().astype(str).apply(_normalize_employee).apply(_first_last)
    emp_blip = df_blip["employee"].dropna().astype(str).apply(_normalize_employee).apply(_first_last)
    sources = [emp_abs, emp_blip]
    if df_entitlement is not None and not df_entitlement.empty:
        if "employee_short" in df_entitlement.columns:
            emp_ent = df_entitlement["employee_short"].dropna().astype(str).str.strip()
        else:
            emp_ent = df_entitlement["employee"].dropna().astype(str).apply(_normalize_employee).apply(_first_last)
        sources.append(emp_ent)
    all_employees = pd.Series(pd.unique(pd.concat(sources))).dropna()
    all_employees = all_employees[all_employees.str.strip() != ""].sort_values().reset_index(drop=True)
    if EXCLUDED_EMPLOYEES:
        all_employees = all_employees[~all_employees.str.strip().str.lower().isin(EXCLUDED_EMPLOYEES)].reset_index(drop=True)

    df_absence = df_absence.copy() if not df_absence.empty else df_absence
    df_blip = df_blip.copy() if not df_blip.empty else df_blip

    # Team & Country from Absence (first occurrence per employee, by First+Last)
    if not df_absence.empty and "employee" in df_absence.columns:
        df_absence["_emp"] = df_absence["employee"].astype(str).apply(_normalize_employee)
        df_absence["_emp_short"] = df_absence["_emp"].apply(_first_last)
        first_abs = df_absence.drop_duplicates(subset=["_emp_short"], keep="first").set_index("_emp_short")
        team_map = first_abs["Team names"].fillna("").astype(str).to_dict() if "Team names" in first_abs.columns else {}
        country_map = first_abs["Country"].fillna("").astype(str).to_dict() if "Country" in first_abs.columns else {}
    else:
        team_map = {}
        country_map = {}

    # Fallback: Team & Country from BLIP when missing (by First+Last)
    blip_team_map = {}
    blip_country_map = {}
    if not df_blip.empty and "employee" in df_blip.columns:
        if "_emp" not in df_blip.columns:
            df_blip["_emp"] = df_blip["employee"].astype(str).apply(_normalize_employee)
        df_blip["_emp_short"] = df_blip["_emp"].apply(_first_last)
        first_blip = df_blip.drop_duplicates(subset=["_emp_short"], keep="first")
        if "Team(s)" in first_blip.columns:
            blip_team_map = first_blip.set_index("_emp_short")["Team(s)"].fillna("").astype(str).str.strip().to_dict()
        if "Team(s)" in first_blip.columns:
            from absence_daily import infer_country_from_team
            blip_country_map = infer_country_from_team(first_blip.set_index("_emp_short")["Team(s)"].fillna("")).to_dict()

    # Leave allowance: prefer Holiday Summary when provided (key by First+Last only to avoid duplicates)
    leave_allowance_map = {}
    if df_entitlement is not None and not df_entitlement.empty:
        df_ent = df_entitlement.copy()
        short_col = "employee_short" if "employee_short" in df_ent.columns else None
        for _, r in df_ent.iterrows():
            ent = r["entitlement"]
            key = (r[short_col].strip() if short_col and r.get(short_col) else r["employee"]) if short_col else r["employee"]
            key = _normalize_employee(key) if isinstance(key, str) else key
            leave_allowance_map[key] = ent
        if "Team" in df_entitlement.columns:
            from absence_daily import infer_country_from_team
            for _, r in df_ent.iterrows():
                short = r.get("employee_short", "").strip() if short_col else (r["employee"].strip() if isinstance(r.get("employee"), str) else "")
                if not short and "employee" in r:
                    short = _normalize_employee(r["employee"])
                team = r.get("Team", "")
                if short and (short not in team_map or not str(team_map.get(short, "")).strip()):
                    team_map[short] = team
                if short and (short not in country_map or not str(country_map.get(short, "")).strip()):
                    country_map[short] = infer_country_from_team(pd.Series([team])).iloc[0]
    if not leave_allowance_map and not df_absence.empty and ENTITLEMENT_DAYS_COL in df_absence.columns:
        ent = df_absence.dropna(subset=[ENTITLEMENT_DAYS_COL]).drop_duplicates(subset=["_emp"], keep="first").set_index("_emp")[ENTITLEMENT_DAYS_COL]
        leave_allowance_map = pd.to_numeric(ent, errors="coerce").to_dict()

    # Leave days per employee: total and by type (group by First+Last to avoid duplicate rows from middle names)
    if not df_absence.empty and METRIC_COL in df_absence.columns and "absence_category" in df_absence.columns:
        if "_emp" not in df_absence.columns:
            df_absence["_emp"] = df_absence["employee"].astype(str).apply(_normalize_employee)
        if "_emp_short" not in df_absence.columns:
            df_absence["_emp_short"] = df_absence["_emp"].apply(_first_last)
        leave_days = df_absence.groupby("_emp_short", as_index=False)[METRIC_COL].sum().set_index("_emp_short")[METRIC_COL]
        leave_by_type = df_absence.groupby(["_emp_short", "absence_category"], as_index=False)[METRIC_COL].sum()
        leave_pivot = leave_by_type.pivot(index="_emp_short", columns="absence_category", values=METRIC_COL).reindex(columns=LEAVE_TYPES).fillna(0)
    else:
        leave_days = pd.Series(dtype=float)
        leave_pivot = pd.DataFrame(columns=LEAVE_TYPES)

    # First leave date per employee (by First+Last)
    first_leave_year = {}
    if not df_absence.empty and "_emp_short" in df_absence.columns:
        start_col = "start_dt" if "start_dt" in df_absence.columns else next(
            (c for c in df_absence.columns if ("start" in str(c).lower() and "date" in str(c).lower())), None
        )
        if start_col:
            ab = df_absence.dropna(subset=[start_col])
            if not ab.empty:
                first_abs_dates = ab.groupby("_emp_short")[start_col].min()
                for emp, first_dt in first_abs_dates.items():
                    if pd.notna(first_dt) and hasattr(first_dt, "year"):
                        first_leave_year[emp] = first_dt.year

    # BLIP: total worked hours (group by First+Last)
    if not df_blip.empty and "employee" in df_blip.columns:
        if "_emp" not in df_blip.columns:
            df_blip["_emp"] = df_blip["employee"].astype(str).apply(_normalize_employee)
        df_blip["_emp_short"] = df_blip["_emp"].apply(_first_last)
        shift_mask = df_blip["blip_type_norm"].astype(str).str.strip().str.lower() == "shift" if "blip_type_norm" in df_blip.columns else pd.Series(True, index=df_blip.index)
        blip_shift = df_blip[shift_mask]
        worked = blip_shift.groupby("_emp_short").agg(
            total_worked_hours=("worked_hours", "sum"),
            _days=("worked_hours", lambda x: (x.sum() / 8.0) if x.sum() else 0),
        )
        worked["worked_days"] = worked["_days"]
        worked = worked.drop(columns=["_days"], errors="ignore")
    else:
        worked = pd.DataFrame(columns=["total_worked_hours", "worked_days"])

    rows = []
    for emp in all_employees:
        leave_d = float(leave_days.get(emp, 0)) if emp in leave_days.index else 0.0
        allowance = leave_allowance_map.get(emp)
        if allowance is None or (isinstance(allowance, float) and pd.isna(allowance)):
            allowance = 0.0
        allowance = float(allowance)
        if allowance == 0:
            allowance = 20
        if first_leave_year.get(emp) == 2025:
            allowance += 20
        wrk_hrs = float(worked.loc[emp, "total_worked_hours"]) if emp in worked.index else 0.0

        team = team_map.get(emp, "") or blip_team_map.get(emp, "")
        country = country_map.get(emp, "") or blip_country_map.get(emp, "")
        if emp in TEAM_COUNTRY_OVERRIDES:
            ov_team, ov_country = TEAM_COUNTRY_OVERRIDES[emp]
            if ov_team:
                team = ov_team
            if ov_country:
                country = ov_country
        row = {
            "Employee": emp,
            "Team": team,
            "Country": country,
            "Leave Allowance": _round_to_half(allowance),
            "Leave taken": _round_to_half(leave_d),
        }
        for lt in LEAVE_TYPES:
            val = float(leave_pivot.loc[emp, lt]) if emp in leave_pivot.index and lt in leave_pivot.columns else 0.0
            row[lt] = _round_to_half(val)
        row["Worked hours"] = round(wrk_hrs, 1)
        rows.append(row)

    out = pd.DataFrame(rows)

    # Group (Organisation) from Team for rolled-by-group sheet
    from absence_daily import infer_organisation_from_team
    team_series = out.set_index("Employee")["Team"]
    out["Group"] = infer_organisation_from_team(team_series).values

    return out


def main():
    parser = argparse.ArgumentParser(description="Build one Excel workbook with Absence + BLIP refined sheets.")
    parser.add_argument("--absence-csv", "-a", default=DEFAULT_ABSENCE_CSV, help="Absence cleaned CSV path")
    parser.add_argument("--blip", "-b", default=DEFAULT_BLIP, help="BLIP CSV or Excel path")
    parser.add_argument("--out", "-o", default=DEFAULT_OUT, help="Output Excel path (.xlsx)")
    parser.add_argument("--entitlement", "-e", default=None, help="Holiday Summary Report (Excel/CSV) for leave entitlement")
    parser.add_argument("--filter-from", default="2026-01-01", help="Only include absence from this date (default: 2026-01-01)")
    args = parser.parse_args()

    out_path = args.out
    if not out_path.lower().endswith(".xlsx"):
        out_path = out_path.rstrip(".xls") + ".xlsx"

    # Absence: same processing as dashboard, then filter to leave year
    if not os.path.isfile(args.absence_csv):
        print(f"Absence file not found: {args.absence_csv}", file=__import__("sys").stderr)
        return 1
    from absence_daily import process_absence_df
    df_absence = process_absence_df(pd.read_csv(args.absence_csv))
    filter_from = pd.Timestamp(args.filter_from)
    if "start_dt" in df_absence.columns:
        df_absence = df_absence[df_absence["start_dt"].notna() & (df_absence["start_dt"] >= filter_from)].copy()
        print(f"Filtered absence to start_dt >= {filter_from.date()} ({len(df_absence)} rows)")

    # BLIP: same processing as dashboard
    if not os.path.isfile(args.blip):
        print(f"BLIP file not found: {args.blip}", file=__import__("sys").stderr)
        return 1
    from blip_preprocess import process_blip_df
    path_lower = args.blip.strip().lower()
    if path_lower.endswith(".csv"):
        df_blip = pd.read_csv(args.blip)
    else:
        df_blip = pd.read_excel(args.blip, skiprows=1, engine="openpyxl")
    df_blip = process_blip_df(df_blip, update_source_for_export=False)

    # Optional: load entitlement from Holiday Summary Report
    df_entitlement = None
    if args.entitlement and os.path.isfile(args.entitlement):
        from holiday_summary_loader import load_holiday_summary
        df_entitlement, err = load_holiday_summary(args.entitlement)
        if err:
            print(f"Warning: Could not load entitlement from {args.entitlement}: {err}", file=__import__("sys").stderr)
        elif df_entitlement is not None and not df_entitlement.empty:
            print(f"Using entitlement from Holiday Summary: {len(df_entitlement)} employees")

    df_employees = build_employee_summary(df_absence, df_blip, df_entitlement=df_entitlement)

    # Consolidated: one row per Department / Country / Group with aggregated totals
    numeric_cols = ["Leave Allowance", "Leave taken"] + LEAVE_TYPES + ["Worked hours"]
    agg_dict = {"Employee": "count"}
    for c in numeric_cols:
        if c in df_employees.columns:
            agg_dict[c] = "sum"
    by_department = (
        df_employees.groupby("Team", as_index=False)
        .agg(agg_dict)
        .rename(columns={"Employee": "Headcount", "Team": "Department"})
    )
    by_department = by_department[["Department", "Headcount"] + [c for c in numeric_cols if c in by_department.columns]]
    by_department = by_department.round(1)

    by_country = (
        df_employees.groupby("Country", as_index=False)
        .agg(agg_dict)
        .rename(columns={"Employee": "Headcount"})
    )
    by_country = by_country[["Country", "Headcount"] + [c for c in numeric_cols if c in by_country.columns]]
    by_country = by_country.round(1)

    by_group = (
        df_employees.groupby("Group", as_index=False)
        .agg(agg_dict)
        .rename(columns={"Employee": "Headcount"})
    )
    by_group = by_group[["Group", "Headcount"] + [c for c in numeric_cols if c in by_group.columns]]
    by_group = by_group.round(1)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_absence.to_excel(writer, sheet_name="Absence", index=False)
        df_blip.to_excel(writer, sheet_name="BLIP", index=False)
        df_employees[EMPLOYEE_SHEET_COLUMNS].to_excel(writer, sheet_name="Employees", index=False)
        by_department.to_excel(writer, sheet_name="By Department", index=False)
        by_country.to_excel(writer, sheet_name="By Country", index=False)
        by_group.to_excel(writer, sheet_name="By Group", index=False)

    print(f"Wrote workbook: {out_path}")
    print(f"  - Sheet 'Absence': {len(df_absence)} rows")
    print(f"  - Sheet 'BLIP': {len(df_blip)} rows")
    print(f"  - Sheet 'Employees': {len(df_employees)} rows (one per employee)")
    print(f"  - Sheet 'By Department': {len(by_department)} rows (consolidated)")
    print(f"  - Sheet 'By Country': {len(by_country)} rows (consolidated)")
    print(f"  - Sheet 'By Group': {len(by_group)} rows (consolidated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
