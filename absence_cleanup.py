"""
Absence data cleanup: raw BrightHR export CSV -> dashboard-ready CSV.

Pipeline:
- Drops unused columns (status, sickness types, toil notes, etc.)
- Maps Team names -> Organisation / Suborganisation (AG/EG/UG)
- WFH detection from Absence type + description (keyword-based)
- Final categories: Annual, Medical, Work from home, External & additional assignments, Others
- Safe encoding fix (ftfy) on First/Last name; exact-dedupe; audit print.

Output is consumed by app.py (Leave Management).
Pass paths each run (e.g. fresh weekly export).
"""
import re
import os
import sys
import argparse
import pandas as pd
import numpy as np

# -------------------------
# CONFIG (no hardcoded paths; use --input / --output)
# -------------------------
TEAM_COL = "Team names"
TYPE_COL = "Absence type"
DESC_COL = "Absence description"

COLS_TO_DROP = [
    "Status reason",
    "Absence status",
    "Is ongoing",
    "Fit note required",
    "Estimated return date",
    "Sickness start date type",
    "Sickness end date type",
    "Toil notes",
]

# -------------------------
# HELPERS
# -------------------------
def normalise_text(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.lower()
        .str.replace(r"[\-/_,;:()\[\]{}|]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def build_pattern(keywords):
    return r"(?:^|[^a-z0-9])(?:%s)(?:$|[^a-z0-9])" % "|".join(
        re.escape(k) for k in keywords
    )


def safe_fix_text_series(s: pd.Series) -> pd.Series:
    """Fix mojibake/encoding using ftfy if available; else return series unchanged."""
    try:
        from ftfy import fix_text
    except Exception:
        return s

    def _fix(x):
        return fix_text(x) if isinstance(x, str) else x

    return s.apply(_fix)


# -------------------------
# PIPELINE
# -------------------------
def run(input_path: str, output_path: str) -> int:
    """
    Run the full absence cleanup pipeline.
    Returns 0 on success, 1 on error.
    """
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        return 1

    df = pd.read_csv(input_path)
    raw_rows = len(df)
    raw_dup_exact = int(df.duplicated().sum())

    df = df.drop(columns=COLS_TO_DROP, errors="ignore")

    if TEAM_COL not in df.columns:
        print(f"Error: Missing required column '{TEAM_COL}'.", file=sys.stderr)
        return 1
    df[TEAM_COL] = df[TEAM_COL].astype(str).str.strip().replace({"nan": np.nan})
    df["Organisation"] = None
    df["Suborganisation"] = None

    teams_eg = {"HR", "UK BDM", "DE BDM", "Engineering", "Operations", "Investment", "Investments"}
    teams_ag = {"Agri"}
    teams_ug = {"Executive", "UG Business Support", "Group Finance", "Property", "Group Legal"}

    df.loc[df[TEAM_COL].isin(teams_eg), ["Organisation", "Suborganisation"]] = ["AG", "EG"]
    df.loc[df[TEAM_COL].isin(teams_ag), ["Organisation", "Suborganisation"]] = ["AG", "AG"]
    df.loc[df[TEAM_COL].isin(teams_ug), ["Organisation", "Suborganisation"]] = ["UG", "UG"]

    for col in [TYPE_COL, DESC_COL]:
        if col not in df.columns:
            print(f"Error: Missing required column '{col}'.", file=sys.stderr)
            return 1

    type_norm = normalise_text(df[TYPE_COL])
    desc_norm = normalise_text(df[DESC_COL])

    wfh_keywords = [
        "wfh", "work from home", "working from home",
        "workfromhome", "remote", "working remotely",
        "home working", "telework", "hybrid"
    ]
    wfh_pattern = build_pattern(wfh_keywords)

    df["Is_WFH"] = (
        type_norm.str.contains(wfh_pattern, regex=True)
        | desc_norm.str.contains(wfh_pattern, regex=True)
    )

    df["Absence_Category_Clean"] = np.select(
        [
            type_norm.eq("annual leave"),
            type_norm.eq("other") & df["Is_WFH"],
        ],
        ["Annual leave", "WFH"],
        default=df[TYPE_COL],
    )

    final_category_map = {
        "Annual leave": "Annual",
        "Maternity leave": "Annual",
        "Bereavement leave": "Annual",
        "Compassionate leave": "Annual",
        "Medical appointment": "Medical",
        "Dental appointment": "Medical",
        "Sickness": "Medical",
        "WFH": "Work from home",
        "Travel": "External & additional assignments",
        "Training / events": "External & additional assignments",
        "Birthday": "External & additional assignments",
        "Birthday leave": "External & additional assignments",
        "Other": "Others",
    }

    df["Absence Category Final"] = (
        df["Absence_Category_Clean"]
        .map(final_category_map)
        .fillna("Others")
    )

    df[TYPE_COL] = df["Absence Category Final"]
    df = df.drop(
        columns=["Is_WFH", "Absence_Category_Clean", "Absence Category Final"],
        errors="ignore",
    )

    for name_col in ["First name", "Last name"]:
        if name_col in df.columns:
            df[name_col] = safe_fix_text_series(df[name_col])

    before = len(df)
    df = df.drop_duplicates()
    after = len(df)
    removed = before - after

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    df.to_csv(output_path, index=False)

    print("Saved:", output_path)
    print(f"Raw rows: {raw_rows}, Raw exact duplicates: {raw_dup_exact}")
    print(f"Rows before dedupe: {before}, Removed: {removed}, Final rows: {after}")
    print("Final Absence types:", sorted(df[TYPE_COL].dropna().unique().tolist()))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Absence data cleanup: raw BrightHR CSV -> dashboard CSV. Pass paths to your fresh data."
    )
    parser.add_argument("--input", "-i", required=True, help="Input CSV path (e.g. this week's BrightHR export)")
    parser.add_argument("--output", "-o", required=True, help="Output CSV path (dashboard will use this file)")
    args = parser.parse_args()
    return run(args.input, args.output)


if __name__ == "__main__":
    sys.exit(main())
