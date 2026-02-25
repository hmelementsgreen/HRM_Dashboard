"""
Build combined employee-day dataset: Leave (absence) + BLIP time/attendance.
Grain: one row per employee per calendar day. Full outer join on employee + date.

Usage:
  python build_combined_daily.py [--absence-csv PATH] [--blip-csv PATH] [--out PATH] [--months 2025-11 2025-12]

Output: combined_employee_day.csv (or --out path).
"""
import os
import argparse
import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ABSENCE_CSV = os.path.join(_PROJECT_ROOT, "AbsenseReport_Cleaned_Final.csv")
DEFAULT_BLIP_CSV = os.path.join(_PROJECT_ROOT, "blip_cumulative.csv")
DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "combined_employee_day.csv")


def _normalize_employee(s):
    return " ".join(str(s).strip().split()) if s else ""


def _normalize_employee_series(ser):
    return ser.fillna("").astype(str).apply(_normalize_employee)


def build_leave_daily(absence_csv_path, months_tuple=None):
    """One row per employee per date. Multiple leave types on same day -> single row with first/primary type and concatenated extras."""
    from absence_daily import load_absence_and_expand_daily

    daily = load_absence_and_expand_daily(absence_csv_path, months_tuple=months_tuple)
    if daily.empty:
        return pd.DataFrame(columns=["employee", "date", "leave_type", "Team names", "Country", "Organisation", "case_id", "purpose", "is_weekday", "month", "week_start"])

    daily["date_norm"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["employee_norm"] = _normalize_employee_series(daily["employee"])

    # Collapse to one row per employee-date: take first leave type; keep first Team/Country/Org, first case_id; concat purposes if multiple
    agg = daily.groupby(["employee_norm", "date_norm"], as_index=False).agg(
        employee=("employee", "first"),
        date=("date_norm", "first"),
        leave_type=("absence_category", "first"),
        leave_types_all=("absence_category", lambda x: "; ".join(sorted(set(x.astype(str))))),
        Team_names=("Team names", "first"),
        Country=("Country", "first"),
        Organisation=("Organisation", "first"),
        case_id=("case_id", "first"),
        purpose=("purpose", lambda x: " | ".join(x.dropna().astype(str).unique())),
        is_weekday=("is_weekday", "first"),
        month=("month", "first"),
        week_start=("week_start", "first"),
    ).rename(columns={"Team_names": "Team names"})
    return agg


def build_blip_daily(blip_csv_path):
    """One row per employee per date with aggregated BLIP metrics."""
    from blip_preprocess import process_blip_df

    path = (blip_csv_path or "").strip().lower()
    if path.endswith(".csv"):
        df = pd.read_csv(blip_csv_path)
    else:
        df = pd.read_excel(blip_csv_path, skiprows=1, engine="openpyxl")
    df = process_blip_df(df, update_source_for_export=False)

    df["date_norm"] = pd.to_datetime(df["date"]).dt.normalize()
    df["employee_norm"] = _normalize_employee_series(df["employee"])

    # Optional: keep only shift rows for worked hours (or keep all and aggregate)
    shift_only = df[df["blip_type_norm"].astype(str).str.strip().str.lower() == "shift"].copy() if "blip_type_norm" in df.columns else df
    if shift_only.empty:
        shift_only = df

    blip_daily = shift_only.groupby(["employee_norm", "date_norm"], as_index=False).agg(
        employee=("employee", "first"),
        date=("date_norm", "first"),
        worked_hours=("worked_hours", "sum"),
        duration_hours=("duration_hours", "sum"),
        break_hours=("break_hours", "sum"),
        has_clockout=("has_clockout", "any"),
        location_mismatch_any=("location_mismatch", "any"),
        location_mismatch_count=("location_mismatch", "sum"),
        shift_count=("employee", "count"),
    ).rename(columns={"location_mismatch_any": "location_mismatch"})
    return blip_daily


def build_combined(absence_csv_path, blip_csv_path, months_tuple=None):
    """Full outer join leave_daily and blip_daily on employee_norm + date."""
    leave = build_leave_daily(absence_csv_path, months_tuple=months_tuple)
    blip = build_blip_daily(blip_csv_path)

    if leave.empty and blip.empty:
        return pd.DataFrame()

    leave_key = leave.copy()
    leave_key["_key_emp"] = leave_key["employee_norm"] if "employee_norm" in leave_key.columns else _normalize_employee_series(leave_key["employee"])
    leave_key["_key_date"] = pd.to_datetime(leave_key["date"]).dt.normalize()
    if "employee_norm" not in leave_key.columns:
        leave_key["employee_norm"] = leave_key["_key_emp"]

    blip_key = blip.copy()
    blip_key["_key_emp"] = blip_key["employee_norm"]
    blip_key["_key_date"] = pd.to_datetime(blip_key["date"]).dt.normalize()

    merged = pd.merge(
        leave_key,
        blip_key,
        on=["_key_emp", "_key_date"],
        how="outer",
        suffixes=("", "_blip"),
    )

    # Prefer leave employee/date when both present
    for col in ["employee", "date"]:
        if f"{col}_blip" in merged.columns:
            merged[col] = merged[col].fillna(merged[f"{col}_blip"])
            merged = merged.drop(columns=[f"{col}_blip"], errors="ignore")
    merged["date"] = pd.to_datetime(merged["date"]).dt.normalize()

    # Drop key columns and any duplicate-named
    merged = merged.drop(columns=["_key_emp", "_key_date", "date_norm"], errors="ignore")
    for c in list(merged.columns):
        if c.endswith("_blip"):
            merged = merged.drop(columns=[c], errors="ignore")

    # Normalize employee for output
    if "employee" in merged.columns:
        merged["employee"] = merged["employee"].fillna(merged.get("employee_norm", "")).apply(_normalize_employee)
    if "employee_norm" in merged.columns:
        merged = merged.drop(columns=["employee_norm"], errors="ignore")

    # Fill missing leave with "No leave"
    if "leave_type" in merged.columns:
        merged["leave_type"] = merged["leave_type"].fillna("No leave")
    else:
        merged["leave_type"] = "No leave"

    # Fill missing BLIP numeric with 0
    for col in ["worked_hours", "duration_hours", "break_hours", "location_mismatch_count", "shift_count"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)
    if "location_mismatch" in merged.columns:
        merged["location_mismatch"] = np.where(merged["location_mismatch"].isna(), False, merged["location_mismatch"].astype(bool))
    if "has_clockout" in merged.columns:
        merged["has_clockout"] = np.where(merged["has_clockout"].isna(), False, merged["has_clockout"].astype(bool))

    # Optional: is_weekday, month, week_start from date if missing
    if "is_weekday" not in merged.columns or merged["is_weekday"].isna().any():
        merged["is_weekday"] = merged["date"].dt.weekday.lt(5).astype(int)
    if "month" not in merged.columns or merged["month"].isna().any():
        merged["month"] = merged["date"].dt.to_period("M").astype(str)
    if "week_start" not in merged.columns or merged["week_start"].isna().any():
        merged["week_start"] = (merged["date"] - pd.to_timedelta(merged["date"].dt.weekday, unit="D")).dt.normalize()

    return merged


def main():
    parser = argparse.ArgumentParser(description="Build combined employee-day CSV (Leave + BLIP).")
    parser.add_argument("--absence-csv", "-a", default=DEFAULT_ABSENCE_CSV, help="Absence cleaned CSV path")
    parser.add_argument("--blip-csv", "-b", default=DEFAULT_BLIP_CSV, help="BLIP cumulative CSV path")
    parser.add_argument("--out", "-o", default=DEFAULT_OUT, help="Output combined CSV path")
    parser.add_argument("--months", "-m", nargs="*", help="Filter absence to these months (e.g. 2025-11 2025-12); default all")
    args = parser.parse_args()

    months_tuple = tuple(args.months) if args.months else None

    if not os.path.isfile(args.absence_csv):
        print(f"Absence file not found: {args.absence_csv}", file=__import__("sys").stderr)
        return 1
    if not os.path.isfile(args.blip_csv):
        print(f"BLIP file not found: {args.blip_csv}", file=__import__("sys").stderr)
        return 1

    combined = build_combined(args.absence_csv, args.blip_csv, months_tuple=months_tuple)
    if combined.empty:
        print("No data produced.", file=__import__("sys").stderr)
        return 1

    combined.to_csv(args.out, index=False, date_format="%Y-%m-%d")
    print(f"Wrote {len(combined)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
