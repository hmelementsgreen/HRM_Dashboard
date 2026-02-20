"""
BLIP data cleanup: raw CSV -> dashboard-ready Excel or CSV.

- Data from START_DATE (weekdays only).
- Aggregates multiple shift rows per person-day (earliest in, latest out).
- Multi-day shifts: cap to same-day end (17:30).
- Valid break 25-60 min or synthetic; MIN_WORK 7h30.
- WFH: for each employee, weekdays in range with no data get one Shift+Break (09:00-17:00, 8h).

Modes:
- Default: process full input -> overwrite output (Excel or CSV).
- --append: process only new input -> append to existing CSV (cumulative). Output must be .csv.
  Use the same --output path every run so new data is appended; dedupe by (First Name, Last Name, Clock In Date, Blip Type) keeps latest.
"""
import pandas as pd
import numpy as np
import random
import argparse
from datetime import datetime, timedelta, time, date
import os

# =================================================
# CONFIG (paths come from CLI; no hardcoded file paths)
# =================================================
START_DATE = date(2026, 1, 27)
MIN_WORK = timedelta(hours=7, minutes=30)
WFH_HOURS = 8
WFH_CLOCK_IN = time(9, 0)
WFH_CLOCK_OUT = time(17, 0)
WFH_BREAK_MINUTES = 30

random.seed(42)


def _normalize_headers(cols):
    return (
        pd.Series(cols)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace(r"[()]", "", regex=True)
        .tolist()
    )


def rand_time(h1, m1, h2, m2):
    s = random.randint(h1 * 3600 + m1 * 60, h2 * 3600 + m2 * 60)
    return time(s // 3600, (s % 3600) // 60, s % 60)


def rand_lunch_start():
    return rand_time(12, 0, 14, 30)


def get_team_from_group(g):
    team_cols = [c for c in g.columns if "team" in c.lower()]
    if not team_cols:
        return np.nan
    shift = g[g["blip_type"].str.lower() == "shift"]
    for col in team_cols:
        if not shift.empty and shift[col].notna().any():
            return shift[col].dropna().iloc[0]
    for col in team_cols:
        if g[col].notna().any():
            return g[col].dropna().iloc[0]
    return np.nan


def _make_row(fn, ln, day, job_title, team_val, location, blip_type, clock_in, clock_out, duration_td, worked_td, notes):
    """Build one row with dashboard column names (First Name, etc.)."""
    return {
        "First Name": fn,
        "Last Name": ln,
        "Job Title": job_title,
        "Team(s)": team_val,
        "Blip Type": blip_type,
        "Clock In Date": day,
        "Clock In Time": str(clock_in),
        "Clock In Location": location,
        "Clock Out Date": day,
        "Clock Out Time": str(clock_out),
        "Clock Out Location": location,
        "Total Duration": duration_td,
        "Total Excluding Breaks": worked_td,
        "Notes": notes,
    }


# Columns used for dedupe when appending (same person, same date, same type = one row, keep latest)
BLIP_DEDUPE_COLS = ["First Name", "Last Name", "Clock In Date", "Blip Type"]


def main():
    parser = argparse.ArgumentParser(
        description="BLIP data cleanup: raw timesheet CSV -> dashboard Excel or CSV. Use --append for incremental (append to CSV)."
    )
    parser.add_argument("--input", "-i", required=True, help="Input CSV path (this week's or new BLIP timesheet export)")
    parser.add_argument("--output", "-o", required=True, help="Output path: Excel (.xlsx) or CSV (.csv). For --append must be CSV.")
    parser.add_argument("--append", "-a", action="store_true", help="Append new data to existing CSV (incremental); output must be .csv")
    args = parser.parse_args()
    input_path = args.input
    output_path = args.output
    append_mode = args.append

    if append_mode and not output_path.lower().endswith(".csv"):
        print("Error: With --append, output path must be a .csv file.", file=__import__("sys").stderr)
        return 1

    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.")
        return 1

    df = pd.read_csv(input_path, skiprows=1)
    df.columns = _normalize_headers(df.columns)

    df["clock_in_dt"] = pd.to_datetime(
        df["clock_in_date"].astype(str) + " " + df["clock_in_time"].astype(str),
        errors="coerce",
    )
    df["clock_out_dt"] = pd.to_datetime(
        df["clock_out_date"].astype(str) + " " + df["clock_out_time"].astype(str),
        errors="coerce",
    )

    start_dt = pd.Timestamp(START_DATE)
    df = df[df["clock_in_dt"].notna() & (df["clock_in_dt"] >= start_dt)]
    df = df[df["clock_in_dt"].dt.weekday < 5]

    rows = []
    employee_info = {}

    for (fn, ln, day), g in df.groupby(["first_name", "last_name", df["clock_in_dt"].dt.date]):
        day = day if isinstance(day, date) else day.date() if hasattr(day, "date") else day
        key = (fn, ln)
        if key not in employee_info:
            first = g.iloc[0]
            employee_info[key] = {
                "job_title": first.get("job_title", ""),
                "team": get_team_from_group(g),
                "location": first.get("clock_in_location", ""),
            }
        info = employee_info[key]
        team_val = info["team"]
        base = g.iloc[0]
        location = info["location"] or base.get("clock_in_location", "")

        shifts = g[g["blip_type"].str.lower() == "shift"]
        breaks = g[g["blip_type"].str.lower() == "break"]

        notes = None
        break_td = timedelta(minutes=30)
        break_start = rand_lunch_start()

        if shifts.empty or shifts["clock_in_dt"].isna().all():
            clock_in = rand_time(8, 55, 9, 10)
            clock_out = rand_time(17, 25, 17, 45)
            break_start = rand_lunch_start()
            break_td = timedelta(minutes=random.randint(30, 45), seconds=random.randint(0, 59))
            notes = "ADJUSTED (no valid shift)"
        else:
            shift_in = shifts["clock_in_dt"].min()
            shift_out = shifts["clock_out_dt"].max()
            clock_in = shift_in.time() if pd.notna(shift_in) else rand_time(8, 55, 9, 10)

            if pd.isna(shift_out):
                clock_out = rand_time(17, 25, 17, 45)
            else:
                out_date = shift_out.date() if hasattr(shift_out, "date") else shift_out
                in_date = shift_in.date() if hasattr(shift_in, "date") else shift_in
                if out_date != in_date:
                    clock_out = time(17, 30)
                    notes = "ADJUSTED (multi-day shift; first day only)"
                else:
                    clock_out = shift_out.time()

            if breaks.empty:
                break_start = rand_lunch_start()
                break_td = timedelta(minutes=random.randint(30, 45), seconds=random.randint(0, 59))
                if notes is None:
                    notes = "ADJUSTED (break added)"
            else:
                b = breaks.iloc[0]
                if pd.notna(b["clock_in_dt"]) and pd.notna(b["clock_out_dt"]):
                    break_td = b["clock_out_dt"] - b["clock_in_dt"]
                else:
                    break_td = timedelta(minutes=random.randint(30, 45))
                if timedelta(minutes=25) <= break_td <= timedelta(minutes=60):
                    break_start = b["clock_in_dt"].time()
                else:
                    break_start = rand_lunch_start()
                    break_td = timedelta(minutes=random.randint(30, 45))
                    if notes is None:
                        notes = "ADJUSTED (break added)"

            work_td = (
                datetime.combine(day, clock_out)
                - datetime.combine(day, clock_in)
                - break_td
            )
            if work_td < MIN_WORK:
                clock_out = rand_time(17, 25, 17, 45)
                notes = "ADJUSTED (working hours aligned)"

        duration_td = datetime.combine(day, clock_out) - datetime.combine(day, clock_in)
        worked_td = duration_td - break_td

        rows.append(
            _make_row(
                fn, ln, day, info["job_title"], team_val, location,
                "Shift", clock_in, clock_out, duration_td, worked_td, notes
            )
        )
        break_end = (datetime.combine(day, break_start) + break_td).time()
        rows.append(
            _make_row(
                fn, ln, day, info["job_title"], team_val, location,
                "Break", break_start, break_end, break_td, timedelta(0), notes
            )
        )

    # (fn, ln, day) that have at least one row from raw data
    dates_with_data = set()
    for (fn, ln, day), _ in df.groupby(["first_name", "last_name", df["clock_in_dt"].dt.date]):
        d = pd.Timestamp(day).date() if not isinstance(day, date) else day
        dates_with_data.add((fn, ln, d))

    max_date = START_DATE
    for r in rows:
        d = r["Clock In Date"]
        if hasattr(d, "date"):
            d = d.date()
        if d > max_date:
            max_date = d
    all_weekdays = pd.date_range(start=pd.Timestamp(START_DATE), end=pd.Timestamp(max_date), freq="D")
    weekday_dates = [d.date() for d in all_weekdays if d.weekday() < 5]

    for (fn, ln), info in employee_info.items():
        for d in weekday_dates:
            if (fn, ln, d) in dates_with_data:
                continue
            break_start = time(12, 30)
            break_td = timedelta(minutes=WFH_BREAK_MINUTES)
            duration_td = timedelta(hours=WFH_HOURS)
            worked_td = duration_td - break_td
            loc = info.get("location", "")
            rows.append(
                _make_row(
                    fn, ln, d, info["job_title"], info["team"], loc,
                    "Shift", WFH_CLOCK_IN, WFH_CLOCK_OUT, duration_td, worked_td, "WFH"
                )
            )
            rows.append(
                _make_row(
                    fn, ln, d, info["job_title"], info["team"], loc,
                    "Break", break_start, (datetime.combine(d, break_start) + break_td).time(),
                    break_td, timedelta(0), "WFH"
                )
            )

    final_df = pd.DataFrame(rows)
    final_df["Clock In Date"] = pd.to_datetime(final_df["Clock In Date"]).dt.date
    final_df["Clock Out Date"] = pd.to_datetime(final_df["Clock Out Date"]).dt.date
    final_df["Total Duration"] = final_df["Total Duration"].astype(str)
    final_df["Total Excluding Breaks"] = final_df["Total Excluding Breaks"].astype(str)

    new_df = final_df.sort_values(["Clock In Date", "First Name", "Last Name", "Blip Type"])

    if append_mode:
        # Append to existing CSV; dedupe by person + date + type (keep latest)
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        if os.path.exists(output_path):
            try:
                existing = pd.read_csv(output_path)
                for c in new_df.columns:
                    if c not in existing.columns:
                        existing[c] = "" if c not in ["Clock In Date", "Clock Out Date"] else pd.NaT
                existing = existing[new_df.columns]
                combined = pd.concat([existing, new_df], ignore_index=True)
            except Exception as e:
                print(f"Warning: Could not read existing CSV, writing new only: {e}")
                combined = new_df
        else:
            combined = new_df

        # Dedupe: same person, date, blip type -> keep last (new overwrites old)
        dedupe_cols = [c for c in BLIP_DEDUPE_COLS if c in combined.columns]
        if dedupe_cols:
            combined["Clock In Date"] = pd.to_datetime(combined["Clock In Date"], errors="coerce").dt.date
            combined = combined.drop_duplicates(subset=dedupe_cols, keep="last")
        combined = combined.sort_values(["Clock In Date", "First Name", "Last Name", "Blip Type"])
        try:
            combined.to_csv(output_path, index=False)
            print(f"Appended to {output_path} (rows now: {len(combined)})")
            return 0
        except Exception as e:
            print(f"Error writing CSV: {e}")
            return 1

    # Non-append: write Excel (or CSV if path ends with .csv)
    try:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        if output_path.lower().endswith(".csv"):
            new_df.to_csv(output_path, index=False)
            print(f"Output saved to {output_path}")
        else:
            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                new_df.to_excel(writer, sheet_name="Sheet1", startrow=1, index=False)
                writer.sheets["Sheet1"]["A1"] = "Export generated for Dashboard (skiprows=1)"
            print(f"Output saved to {output_path}")
        return 0
    except Exception as e:
        print(f"Error writing output: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
