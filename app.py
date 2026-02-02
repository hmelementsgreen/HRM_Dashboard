import hashlib
import io
import math
import os
import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

# ----------------------------
# Page config + global styling
# ----------------------------
st.set_page_config(page_title="BrightHR & BLIP Dashboard", layout="wide")

st.markdown(
    """
    <style>
      .eg-title { text-align: center; margin-top: 0.25rem; margin-bottom: 0.25rem; }
      .eg-subtitle { text-align: center; color: #6b7280; margin-top: 0rem; margin-bottom: 1rem; font-size: 0.95rem; }

      div[data-testid="stMetric"] { text-align: center; }
      div[data-testid="stMetricLabel"],
      div[data-testid="stMetricValue"],
      div[data-testid="stMetricDelta"] { justify-content: center; }

      .eg-section-title { margin-top: 0.25rem; margin-bottom: 0.25rem; }

      .eg-vertical-divider-kpi{ border-left: 2px solid #e5e7eb; height: 230px; margin: 0 auto; }
      .eg-vertical-divider-donut{ border-left: 2px solid #e5e7eb; height: 520px; margin: 0 auto; }

      .eg-hint {
        padding: 0.5rem 0.75rem;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        background: #fafafa;
        color: #374151;
        font-size: 0.9rem;
        margin-bottom: 0.75rem;
      }
      .block-container { padding-top: 1rem; padding-bottom: 2rem; }
      .eg-card {
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 0.9rem;
        background: white;
        margin-bottom: 1rem;
      }
      .js-plotly-plot { margin-top: -0.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Constants
# ----------------------------
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH_DEFAULT = os.path.join(_APP_DIR, "AbsenseReport_Cleaned_Final.csv")
METRIC_COL = "Absence duration for period in days"

TYPE_ORDER = [
    "Annual Leave",
    "Medical + Sickness",
    "Other (excl. WFH, Travel)",
    "WFH",
    "Travel",
]

# Cleaned-pipeline categories (if your CSV already contains these)
CLEANED_FINAL_TYPES = {"Annual", "Medical", "Work from home", "Travel", "Others"}
CLEANED_TO_DASH = {
    "Annual": "Annual Leave",
    "Medical": "Medical + Sickness",
    "Work from home": "WFH",
    "Travel": "Travel",
    "Others": "Other (excl. WFH, Travel)",
}

# BrightHR entitlement columns (if present)
ENTITLEMENT_COL = "Leave entitlement"
ENTITLEMENT_UNIT_COL = "Entitlement unit"
ENTITLEMENT_DAYS_COL = "leave_entitlement_days"

# --- keyword-based classification (Absence type + free-text details) ---
WFH_KEYWORDS = ["wfh", "work from home", "work-from-home", "remote", "home working", "telework", "tele-working"]
TRAVEL_KEYWORDS = ["travel", "business trip", "offsite", "onsite", "client visit", "site visit",'london']
ANNUAL_KEYWORDS = ["annual", "holiday", "vacation", "pto",'birthday','birth']
SICK_KEYWORDS = ["sick", "sickness", "medical", "ill", "flu", "gp", "doctor", "hospital", "injury",'migraine','sick-note']

DETAIL_COL_CANDIDATES = [
    "Absence description",
    "Description", "Reason", "Notes", "Comment", "Absence reason", "Absence notes"
]

# ----------------------------
# BLIP (Utilisation) constants + helpers
# ----------------------------
BLIP_COL_FIRST = "First Name"
BLIP_COL_LAST = "Last Name"
BLIP_COL_TEAM = "Team(s)"
BLIP_COL_ROLE = "Job Title"
BLIP_COL_TYPE = "Blip Type"
BLIP_COL_IN_DATE = "Clock In Date"
BLIP_COL_IN_TIME = "Clock In Time"
BLIP_COL_OUT_DATE = "Clock Out Date"
BLIP_COL_OUT_TIME = "Clock Out Time"
BLIP_COL_IN_LOC = "Clock In Location"
BLIP_COL_OUT_LOC = "Clock Out Location"
BLIP_COL_DURATION = "Total Duration"
BLIP_COL_WORKED = "Total Excluding Breaks"
BLIP_XLSX_DEFAULT = os.path.join(_APP_DIR, "blip_integration", "Blip_27_28.xlsx")

def _blip_to_timedelta_safe(s: pd.Series) -> pd.Series:
    x = s.astype(str).replace({"NaT": np.nan, "nan": np.nan, "": np.nan, "None": np.nan})
    return pd.to_timedelta(x, errors="coerce")

def _blip_combine_date_time(d, t):
    d = pd.to_datetime(d, errors="coerce")
    t = t.astype(str).replace({"NaT": np.nan, "nan": np.nan, "": np.nan, "None": np.nan})
    return pd.to_datetime(d.dt.strftime("%Y-%m-%d") + " " + t, errors="coerce")

def _blip_clean_plot(fig, y_title=None, x_title=None):
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, title=x_title)
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6", title=y_title)
    return fig

def _blip_safe_divide(n, d):
    return np.where(d > 0, n / d, np.nan)

def _blip_process_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply BLIP column parsing and derived fields to a raw Excel DataFrame."""
    df.columns = [str(c).strip() for c in df.columns]
    df["employee"] = (
        df.get(BLIP_COL_FIRST, pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
        + " "
        + df.get(BLIP_COL_LAST, pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
    ).str.strip()
    df["date"] = pd.to_datetime(df.get(BLIP_COL_IN_DATE), errors="coerce")
    df["week_start"] = df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")
    df["month"] = df["date"].dt.to_period("M").astype(str)
    df["duration_td"] = _blip_to_timedelta_safe(df.get(BLIP_COL_DURATION, pd.Series(index=df.index, dtype="object")))
    df["worked_td"] = _blip_to_timedelta_safe(df.get(BLIP_COL_WORKED, pd.Series(index=df.index, dtype="object")))
    df["duration_hours"] = df["duration_td"].dt.total_seconds() / 3600
    df["worked_hours"] = df["worked_td"].dt.total_seconds() / 3600
    df["break_hours"] = (df["duration_hours"] - df["worked_hours"]).clip(lower=0)
    if BLIP_COL_IN_TIME in df.columns and BLIP_COL_OUT_TIME in df.columns:
        df["clockin_dt"] = _blip_combine_date_time(df[BLIP_COL_IN_DATE], df[BLIP_COL_IN_TIME])
        df["clockout_dt"] = _blip_combine_date_time(df[BLIP_COL_OUT_DATE], df[BLIP_COL_OUT_TIME])
        df["has_clockout"] = df["clockout_dt"].notna() & df["clockin_dt"].notna()
    else:
        df["clockin_dt"] = pd.NaT
        df["clockout_dt"] = pd.NaT
        df["has_clockout"] = False
    if BLIP_COL_IN_LOC in df.columns and BLIP_COL_OUT_LOC in df.columns:
        df["location_mismatch"] = (
            df[BLIP_COL_IN_LOC].astype(str) != df[BLIP_COL_OUT_LOC].astype(str)
        ) & df["has_clockout"]
    else:
        df["location_mismatch"] = False
    df["blip_type_norm"] = df.get(BLIP_COL_TYPE, "").astype(str).str.strip().str.lower()
    return df

@st.cache_data(show_spinner=False)
def _blip_load_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, skiprows=1, engine="openpyxl")
    return _blip_process_raw_df(df)

def _blip_load_data_from_upload(uploaded_file) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(uploaded_file.read()), skiprows=1, engine="openpyxl")
    return _blip_process_raw_df(df)

def _blip_merge_consecutive(segments):
    if not segments:
        return []
    out = [segments[0].copy()]
    for s in segments[1:]:
        last = out[-1]
        if s["kind"] == last["kind"] and s["start"] <= last["end"]:
            last["end"] = max(last["end"], s["end"])
        else:
            out.append(s.copy())
    return out

def _blip_build_authentic_day_segments(emp_df_day: pd.DataFrame):
    d = emp_df_day.copy()
    d = d[d["clockin_dt"].notna() & d["clockout_dt"].notna()].copy()
    if d.empty:
        return []
    intervals = []
    for _, r in d.iterrows():
        s, e = r["clockin_dt"], r["clockout_dt"]
        if pd.isna(s) or pd.isna(e) or e <= s:
            continue
        bt = str(r.get("blip_type_norm", "")).strip().lower()
        kind = "Break" if bt == "break" else ("Shift" if bt == "shift" else None)
        if kind is None:
            continue
        intervals.append({"start": s, "end": e, "kind": kind})
    if not intervals:
        return []
    cuts = sorted({x for it in intervals for x in (it["start"], it["end"])})
    if len(cuts) < 2:
        return []

    def covered_by(kind, a, b):
        for it in intervals:
            if it["kind"] != kind:
                continue
            if a >= it["start"] and b <= it["end"]:
                return True
        return False

    segs = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b <= a:
            continue
        if covered_by("Break", a, b):
            segs.append({"start": a, "end": b, "kind": "Break"})
        elif covered_by("Shift", a, b):
            segs.append({"start": a, "end": b, "kind": "Work"})
    return _blip_merge_consecutive(segs)

# ----------------------------
# Helpers (Absence)
# ----------------------------
def _norm_for_match(s: str) -> str:
    s = "" if pd.isna(s) else str(s).lower().strip()
    # unify separators so "work-from-home", "work_from_home", "work from home" behave the same
    s = re.sub(r"[\-_\/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _build_fuzzy_pattern(keywords: list[str]) -> re.Pattern:
    """
    - case-insensitive
    - space/hyphen/underscore/slash treated as flexible separators
    - safe boundaries (avoids partial hits inside longer words)
    """
    def kw_to_regex(kw: str) -> str:
        kw = _norm_for_match(kw)
        parts = [re.escape(p) for p in kw.split(" ") if p]
        if not parts:
            return ""
        return r"(?:%s)" % r"[\s\-_\/]*".join(parts)

    variants = [kw_to_regex(k) for k in keywords]
    variants = [v for v in variants if v]
    pat = r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(variants)
    return re.compile(pat, flags=re.IGNORECASE)

# compile once (fast)
WFH_PAT    = _build_fuzzy_pattern(WFH_KEYWORDS)
TRAVEL_PAT = _build_fuzzy_pattern(TRAVEL_KEYWORDS)
ANNUAL_PAT = _build_fuzzy_pattern(ANNUAL_KEYWORDS)
SICK_PAT   = _build_fuzzy_pattern(SICK_KEYWORDS)

def map_absence_type(abs_type: str, details: str = "") -> str:
    t = _norm_for_match(abs_type)
    d = _norm_for_match(details)
    combined = f"{t} {d}".strip()

    # Priority (recommended): Sick > Travel > WFH > Annual > Other
    if SICK_PAT.search(combined):
        return "Medical + Sickness"
    if TRAVEL_PAT.search(combined):
        return "Travel"
    if WFH_PAT.search(combined):
        return "WFH"
    if ANNUAL_PAT.search(combined):
        return "Annual Leave"
    return "Other (excl. WFH, Travel)"

def parse_bright_hr_dt_two_pass(s: pd.Series) -> pd.Series:
    """
    Two-pass parsing for mixed formats:
    1) month-first
    2) re-parse only NaTs with day-first
    """
    s = s.astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    dt = pd.to_datetime(s, errors="coerce", dayfirst=False)
    mask = dt.isna() & s.notna()
    if mask.any():
        dt2 = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
        dt.loc[mask] = dt2
    return dt

def infer_country_from_team(team_series: pd.Series) -> pd.Series:
    """
    Country heuristic based on Team names.
    Default: UK, unless explicitly tagged as DE/Germany.
    """
    t = team_series.fillna("").astype(str).str.upper()
    out = pd.Series(["UK"] * len(t), index=t.index)
    out[t.str.contains(r"\bDE\b") | t.str.contains("GERM")] = "Germany"
    return out

def make_case_id(employee: str, start_dt, end_dt, raw_abs_type: str, team: str, country: str) -> str:
    """
    Stable ID without purpose text (purpose changes shouldn't change the case identity).
    """
    payload = f"{employee}|{start_dt}|{end_dt}|{raw_abs_type}|{team}|{country}"
    return hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()

def expand_to_daily(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Expand each absence row into daily rows between start_dt and end_dt (inclusive).
    Carries case_id into daily rows.
    Adds iso_week + week_start.
    """
    if df_in.empty:
        return df_in.copy()

    rows = []
    for _, r in df_in.iterrows():
        s = r.get("start_dt", pd.NaT)
        e = r.get("end_dt", pd.NaT)
        if pd.isna(s):
            continue
        if pd.isna(e) or e < s:
            e = s

        days = pd.date_range(s.normalize(), e.normalize(), freq="D")
        for d in days:
            rr = r.copy()
            rr["date"] = d
            rr["date_uk"] = d.strftime("%d/%m/%Y")
            rr["week_start"] = (d - pd.Timedelta(days=int(d.weekday()))).normalize()  # Monday
            rr["iso_week"] = f"{rr['week_start'].isocalendar().year}-W{rr['week_start'].isocalendar().week:02d}"
            rr["is_weekday"] = int(d.weekday() < 5)
            rows.append(rr)

    if not rows:
        return df_in.iloc[0:0].copy()

    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["week_start"] = pd.to_datetime(out["week_start"], errors="coerce")
    return out

def _process_absence_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Apply BrightHR absence parsing and derived fields to a raw CSV DataFrame."""
    df = df_raw.copy()

    # Dates (two-pass robust)
    df["start_dt"] = parse_bright_hr_dt_two_pass(df.get("Absence start date", ""))
    df["end_dt"] = parse_bright_hr_dt_two_pass(df.get("Absence end date", ""))

    df["start_date_uk"] = df["start_dt"].dt.strftime("%d/%m/%Y").fillna("")
    df["end_date_uk"] = df["end_dt"].dt.strftime("%d/%m/%Y").fillna("")
    df["month"] = df["start_dt"].dt.to_period("M").astype(str)

    # Ensure Team names exists
    if "Team names" not in df.columns:
        df["Team names"] = ""

    # Employee
    fn = df.get("First name", "").astype(str).str.strip()
    ln = df.get("Last name", "").astype(str).str.strip()
    df["employee"] = (fn + " " + ln).str.strip()

    # Country
    if "Country" not in df.columns:
        df["Country"] = infer_country_from_team(df["Team names"])
    else:
        df["Country"] = df["Country"].fillna("").astype(str).str.strip()
        df["Country"] = df["Country"].replace({"Unknown": "UK", "": "UK"}).fillna("UK")
    df["Country"] = df["Country"].replace({"Unknown": "UK"}).fillna("UK")

    # Metric
    df[METRIC_COL] = pd.to_numeric(df.get(METRIC_COL), errors="coerce").fillna(0)

    # Purpose / description
    detail_col = next((c for c in DETAIL_COL_CANDIDATES if c in df.columns), None)
    df["purpose"] = df[detail_col].astype(str).str.strip() if detail_col else ""

    # Absence category:
    raw_type = df.get("Absence type", "").fillna("").astype(str).str.strip()
    if raw_type.isin(list(CLEANED_FINAL_TYPES)).any():
        df["absence_category"] = raw_type.map(CLEANED_TO_DASH).fillna("Other (excl. WFH, Travel)")
    else:
        if detail_col:
            df["absence_category"] = df.apply(
                lambda r: map_absence_type(r.get("Absence type", ""), r.get(detail_col, "")),
                axis=1
            )
        else:
            df["absence_category"] = df.get("Absence type", "").apply(lambda x: map_absence_type(x, ""))

    # Entitlement cleaning (days only)
    if ENTITLEMENT_COL in df.columns:
        df[ENTITLEMENT_COL] = pd.to_numeric(df[ENTITLEMENT_COL], errors="coerce")

    if ENTITLEMENT_UNIT_COL in df.columns:
        unit = df[ENTITLEMENT_UNIT_COL].fillna("").astype(str).str.strip().str.lower()
        unit_ok = unit.str.contains("day") | unit.eq("")
    else:
        unit_ok = pd.Series([True] * len(df), index=df.index)

    if ENTITLEMENT_COL in df.columns:
        df[ENTITLEMENT_DAYS_COL] = df[ENTITLEMENT_COL]
        df.loc[~unit_ok, ENTITLEMENT_DAYS_COL] = pd.NA
    else:
        df[ENTITLEMENT_DAYS_COL] = pd.NA

    # Evidence case_id (stable)
    df["case_id"] = df.apply(
        lambda r: make_case_id(
            r.get("employee", ""),
            r.get("start_dt", ""),
            r.get("end_dt", ""),
            str(r.get("Absence type", "")),
            str(r.get("Team names", "")),
            str(r.get("Country", "")),
        ),
        axis=1
    )

    return df

@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return _process_absence_df(df)

def load_data_from_upload(uploaded_file) -> pd.DataFrame:
    """Load and process Absence CSV from an uploaded file (not cached)."""
    df = pd.read_csv(io.BytesIO(uploaded_file.read()))
    return _process_absence_df(df)

@st.cache_data
def build_daily_for_months(path: str, months_tuple: tuple[str, ...]) -> pd.DataFrame:
    """
    Performance enhancement:
    Expand to daily ONLY for the selected months (instead of whole dataset).
    Cached by (path, months_tuple).
    """
    df_all = load_data(path)
    df_sub = df_all[df_all["month"].isin(list(months_tuple))].copy()
    return expand_to_daily(df_sub)

def fmt_num(x: float) -> str:
    return f"{x:,.1f}"

def fmt_hours_minutes(h: float) -> str:
    """Format decimal hours as 'Xh Ym' (e.g. 7.5 -> '7h 30m')."""
    if pd.isna(h):
        return ""
    h = float(h)
    hours = int(h)
    minutes = int(round((h - hours) * 60))
    if minutes >= 60:
        hours += 1
        minutes = 0
    return f"{hours}h {minutes}m"

def _hours_axis_ticks(max_hours: float, step: float = 1.0):
    """Return (tickvals, ticktext) for Plotly y-axis in hours and minutes (0 to max_hours)."""
    max_h = max(1.0, float(max_hours))
    n = int(math.ceil(max_h / step)) + 1
    tickvals = [i * step for i in range(n)]
    ticktext = [fmt_hours_minutes(v) for v in tickvals]
    return tickvals, ticktext

def apply_global_filters(
    df_cases: pd.DataFrame,
    df_daily: pd.DataFrame,
    *,
    employee_q: str,
    keyword_q: str,
    depts: list[str],
    countries: list[str],
    cats: list[str],
    use_custom_date: bool,
    date_range: tuple | None
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    Returns (cases_filtered, daily_filtered, filter_summary_string)
    Date filtering is applied on daily; cases are reduced to matching case_ids.
    """
    cases = df_cases.copy()
    daily = df_daily.copy()

    if "employee" in cases.columns:
        cases["employee"] = cases["employee"].fillna("").astype(str)
    if "purpose" in cases.columns:
        cases["purpose"] = cases["purpose"].fillna("").astype(str)

    if not daily.empty:
        for c in ["employee", "purpose", "Team names", "Country", "absence_category", "case_id"]:
            if c in daily.columns:
                daily[c] = daily[c].fillna("").astype(str)

    if employee_q.strip():
        q = employee_q.strip()
        cases = cases[cases["employee"].str.contains(q, case=False, na=False)]
        if not daily.empty:
            daily = daily[daily["employee"].str.contains(q, case=False, na=False)]

    if keyword_q.strip():
        q = keyword_q.strip()
        cases = cases[cases["purpose"].str.contains(q, case=False, na=False)]
        if not daily.empty:
            daily = daily[daily["purpose"].str.contains(q, case=False, na=False)]

    if depts:
        cases = cases[cases["Team names"].isin(depts)]
        if not daily.empty:
            daily = daily[daily["Team names"].isin(depts)]

    if countries:
        cases = cases[cases["Country"].isin(countries)]
        if not daily.empty:
            daily = daily[daily["Country"].isin(countries)]

    if cats:
        cases = cases[cases["absence_category"].isin(cats)]
        if not daily.empty:
            daily = daily[daily["absence_category"].isin(cats)]

    summary_date = "Month selection"
    if use_custom_date and date_range and not daily.empty and "date" in daily.columns:
        d1, d2 = date_range
        daily = daily[(daily["date"].dt.date >= d1) & (daily["date"].dt.date <= d2)]
        summary_date = f"Custom date: {d1.strftime('%d/%m/%Y')} → {d2.strftime('%d/%m/%Y')}"

    if not daily.empty and "case_id" in daily.columns and "case_id" in cases.columns:
        case_ids = set(daily["case_id"].unique().tolist())
        cases = cases[cases["case_id"].isin(case_ids)]

    parts = []
    if employee_q.strip():
        parts.append(f"Employee contains '{employee_q.strip()}'")
    if depts:
        parts.append(f"Dept={len(depts)}")
    if countries:
        parts.append(f"Country={len(countries)}")
    if cats:
        parts.append(f"Types={len(cats)}")
    if keyword_q.strip():
        parts.append(f"Keyword '{keyword_q.strip()}'")
    parts.append(summary_date)

    summary = " | ".join(parts) if parts else "No filters"
    return cases, daily, summary

def compute_annual_employee_balance(
    df_all: pd.DataFrame,
    daily_filtered: pd.DataFrame,
    *,
    weekday_only: bool
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Annual Leave allowance vs usage:
    - Entitlement from df_all (max per employee)
    - Used from daily_filtered (count of daily annual leave rows)
    - Optional weekday-only counting for "used"
    """
    entitlement_conflicts = pd.DataFrame(columns=["employee", "Entitlement value (days)"])

    if "employee" in df_all.columns and ENTITLEMENT_DAYS_COL in df_all.columns:
        ent_raw = df_all[["employee", ENTITLEMENT_DAYS_COL]].dropna().copy()
        ent_raw[ENTITLEMENT_DAYS_COL] = pd.to_numeric(ent_raw[ENTITLEMENT_DAYS_COL], errors="coerce")
        ent_raw = ent_raw.dropna()

        conflicts = ent_raw.groupby("employee")[ENTITLEMENT_DAYS_COL].nunique()
        conflict_emps = conflicts[conflicts > 1].index.tolist()
        if conflict_emps:
            entitlement_conflicts = (
                ent_raw[ent_raw["employee"].isin(conflict_emps)]
                .drop_duplicates()
                .sort_values(["employee", ENTITLEMENT_DAYS_COL], ascending=[True, False])
                .rename(columns={ENTITLEMENT_DAYS_COL: "Entitlement value (days)"})
            )

        ent_by_emp = (
            ent_raw.groupby("employee", as_index=False)[ENTITLEMENT_DAYS_COL]
            .max()
            .rename(columns={ENTITLEMENT_DAYS_COL: "Entitlement (days)"})
        )
    else:
        ent_by_emp = pd.DataFrame(columns=["employee", "Entitlement (days)"])

    used_by_emp = pd.DataFrame(columns=["employee", "Used (days)"])
    if not daily_filtered.empty and "employee" in daily_filtered.columns:
        base = daily_filtered[daily_filtered["absence_category"] == "Annual Leave"].copy()
        if weekday_only and "is_weekday" in base.columns:
            base = base[base["is_weekday"] == 1]

        used_by_emp = (
            base.groupby("employee", as_index=False)
            .size()
            .rename(columns={"size": "Used (days)"})
        )

    meta_cols = [c for c in ["employee", "Team names", "Country"] if c in df_all.columns]
    if meta_cols and "employee" in meta_cols:
        meta = (
            df_all[meta_cols]
            .dropna(subset=["employee"])
            .drop_duplicates()
            .groupby("employee", as_index=False)
            .first()
        )
    else:
        meta = pd.DataFrame(columns=["employee", "Team names", "Country"])

    balance = meta.merge(ent_by_emp, on="employee", how="outer").merge(used_by_emp, on="employee", how="outer")
    if balance.empty:
        return balance, entitlement_conflicts, {}

    balance["Used (days)"] = pd.to_numeric(balance["Used (days)"], errors="coerce").fillna(0)
    balance["Entitlement (days)"] = pd.to_numeric(balance["Entitlement (days)"], errors="coerce")
    balance["Remaining (days)"] = balance["Entitlement (days)"] - balance["Used (days)"]

    for c in ["Entitlement (days)", "Used (days)", "Remaining (days)"]:
        balance[c] = balance[c].round(1)

    for c in ["Team names", "Country"]:
        if c not in balance.columns:
            balance[c] = ""

    quality = {
        "Employees (in balance table)": int(balance["employee"].nunique()) if "employee" in balance.columns else 0,
        "Employees with entitlement": int(balance["Entitlement (days)"].notna().sum()),
        "Employees with annual usage": int((balance["Used (days)"] > 0).sum()),
        "Employees with usage but missing entitlement": int(((balance["Used (days)"] > 0) & (balance["Entitlement (days)"].isna())).sum()),
        "Employees with conflicting entitlement values": int(entitlement_conflicts["employee"].nunique()) if not entitlement_conflicts.empty else 0,
    }

    balance = balance[["employee", "Team names", "Country", "Entitlement (days)", "Used (days)", "Remaining (days)"]]
    return balance, entitlement_conflicts, quality

def rollup_balance(balance: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Step 5: roll up annual leave entitlement/usage to Dept or Country.
    NOTE: this is the fixed version (no syntax errors, no trailing-space column names).
    """
    if balance is None or balance.empty or group_col not in balance.columns:
        return pd.DataFrame()

    tmp = balance.copy()
    tmp[group_col] = tmp[group_col].fillna("").astype(str).str.strip()
    tmp.loc[tmp[group_col] == "", group_col] = "Unassigned"

    tmp["has_entitlement"] = tmp["Entitlement (days)"].notna()
    tmp["has_usage"] = pd.to_numeric(tmp["Used (days)"], errors="coerce").fillna(0) > 0

    agg = (
        tmp.groupby(group_col, dropna=False)
        .agg(
            Employees=("employee", "nunique"),
            Employees_with_entitlement=("has_entitlement", "sum"),
            Employees_with_annual_usage=("has_usage", "sum"),
            Total_Entitlement=("Entitlement (days)", "sum"),
            Total_Used=("Used (days)", "sum"),
        )
        .reset_index()
    )

    missing = (
        tmp[tmp["has_usage"] & (~tmp["has_entitlement"])]
        .groupby(group_col)["employee"]
        .nunique()
        .reset_index(name="Employees_usage_missing_entitlement")
    )

    agg = agg.merge(missing, on=group_col, how="left")
    agg["Employees_usage_missing_entitlement"] = agg["Employees_usage_missing_entitlement"].fillna(0).astype(int)

    agg["Total_Entitlement"] = pd.to_numeric(agg["Total_Entitlement"], errors="coerce").fillna(0)
    agg["Total_Used"] = pd.to_numeric(agg["Total_Used"], errors="coerce").fillna(0)
    agg["Remaining"] = agg["Total_Entitlement"] - agg["Total_Used"]

    agg["Total_Entitlement"] = agg["Total_Entitlement"].round(1)
    agg["Total_Used"] = agg["Total_Used"].round(1)
    agg["Remaining"] = agg["Remaining"].round(1)

    out = agg.rename(columns={
        "Total_Entitlement": "Total Entitlement (days)",
        "Total_Used": "Used (days)",
        "Remaining": "Remaining (days)",
        "Employees_with_entitlement": "Employees (with entitlement)",
        "Employees_with_annual_usage": "Employees (with annual usage)",
        "Employees_usage_missing_entitlement": "Employees (usage but missing entitlement)",
    })

    out = out.sort_values(["Remaining (days)", "Used (days)"], ascending=[True, False])
    return out

def weekly_summary(daily_filtered: pd.DataFrame, group_col: str, week_start: pd.Timestamp) -> pd.DataFrame:
    if daily_filtered.empty or "week_start" not in daily_filtered.columns or group_col not in daily_filtered.columns:
        return pd.DataFrame()

    dfw = daily_filtered[daily_filtered["week_start"] == week_start].copy()
    if dfw.empty:
        return pd.DataFrame()

    out = (
        dfw.groupby([group_col, "absence_category"], dropna=False)
        .size()
        .reset_index(name="Days (count of daily rows)")
        .sort_values(["Days (count of daily rows)"], ascending=False)
    )
    return out

def add_export_metadata(df_out: pd.DataFrame, filters_applied: str) -> pd.DataFrame:
    out = df_out.copy()
    out["generated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    out["filters_applied"] = filters_applied
    return out

# ----------------------------
# Centered heading (shared)
# ----------------------------
st.markdown('<h1 class="eg-title">BrightHR & BLIP Dashboard</h1>', unsafe_allow_html=True)
st.markdown(
    '<div class="eg-subtitle">Absence: Individual → Department → Country → Group / ExCo  |  BLIP: Utilisation</div>',
    unsafe_allow_html=True
)

# ----------------------------
# Sidebar: simple layout (Data & period → Refine view → Exports → BLIP)
# ----------------------------
with st.sidebar:
    st.header("Data & period")
    absence_uploaded = st.file_uploader("Upload Absence CSV", type=["csv"], key="absence_upload", help="Or use path below.")
    csv_path = st.text_input("CSV path", value=CSV_PATH_DEFAULT, disabled=absence_uploaded is not None)
    try:
        if absence_uploaded is not None:
            df = load_data_from_upload(absence_uploaded)
        else:
            df = load_data(csv_path)
    except Exception as e:
        st.error(f"Failed to load Absence CSV: {e}")
        st.stop()

    months_available = sorted([m for m in df["month"].dropna().unique().tolist() if m != "NaT"])
    if not months_available:
        st.error("No valid months found.")
        st.stop()

    preferred_m1 = "2025-11"
    default_m1_index = months_available.index(preferred_m1) if preferred_m1 in months_available else max(len(months_available) - 2, 0)
    month_1 = st.selectbox("Month", options=months_available, index=default_m1_index)

    with st.expander("Compare with another month", expanded=False):
        add_second_month = st.checkbox("Add comparison month", value=False, key="add_second_month")
        if add_second_month:
            month_2_options = [m for m in months_available if m != month_1]
            if month_2_options:
                preferred_m2 = "2025-12"
                default_m2_index = month_2_options.index(preferred_m2) if (month_1 == preferred_m1 and preferred_m2 in month_2_options) else max(len(month_2_options) - 1, 0)
                month_2 = st.selectbox("Comparison month", options=month_2_options, index=default_m2_index)
            else:
                month_2 = None
        else:
            month_2 = None

    months_in_scope = [month_1] + ([month_2] if month_2 else [])
    months_tuple = tuple(months_in_scope)

    if absence_uploaded is not None:
        df_sub = df[df["month"].isin(list(months_tuple))].copy()
        daily_scope = expand_to_daily(df_sub)
    else:
        daily_scope = build_daily_for_months(csv_path, months_tuple)

    with st.expander("Refine view (filters)", expanded=False):
        employee_q = st.text_input("Employee search", value="", key="emp_q")
        keyword_q = st.text_input("Keyword in purpose/description", value="", key="kw_q")
        dept_options_global = sorted([d for d in df["Team names"].fillna("").astype(str).unique().tolist() if d.strip() != ""])
        selected_depts_global = st.multiselect("Departments", options=dept_options_global, default=[], key="depts")
        country_options_global = sorted([c for c in df["Country"].fillna("").astype(str).unique().tolist() if c.strip() != ""])
        selected_countries_global = st.multiselect("Countries", options=country_options_global, default=[], key="countries")
        selected_cats_global = st.multiselect("Absence types", options=TYPE_ORDER, default=[], key="cats")
        use_custom_date = st.checkbox("Use custom date range (evidence + exports)", value=False, key="use_custom_date")
        date_range = None
        if use_custom_date and not daily_scope.empty and "date" in daily_scope.columns:
            min_dt = pd.to_datetime(daily_scope["date"], errors="coerce").min()
            max_dt = pd.to_datetime(daily_scope["date"], errors="coerce").max()
            if pd.isna(min_dt) or pd.isna(max_dt):
                st.info("No valid dates for custom range.")
            else:
                date_range = st.date_input("Custom date range", value=(min_dt.date(), max_dt.date()), key="date_range")

    # Monthly scope (charts): month(s) + optional type
    df_scope = df[df["month"].isin(months_in_scope)].copy()
    if selected_cats_global:
        df_scope = df_scope[df_scope["absence_category"].isin(selected_cats_global)]

    # Daily scope (evidence): already month-filtered; add optional type
    if selected_cats_global and not daily_scope.empty:
        daily_scope = daily_scope[daily_scope["absence_category"].isin(selected_cats_global)].copy()

    # Apply filters consistently
    df_cases_filt, daily_filt, filter_summary = apply_global_filters(
        df_cases=df_scope,
        df_daily=daily_scope,
        employee_q=employee_q,
        keyword_q=keyword_q,
        depts=selected_depts_global,
        countries=selected_countries_global,
        cats=selected_cats_global,
        use_custom_date=use_custom_date,
        date_range=date_range
    )

    st.caption(f"Filters applied: {filter_summary}")

    with st.expander("Exports", expanded=False):
        st.caption("Exports use the filters above.")

        if daily_filt.empty:
            st.info("No filtered daily records to export.")
        else:
            daily_cols_export = [
                "case_id", "date_uk", "date", "iso_week", "week_start",
                "employee", "Team names", "Country", "absence_category",
                METRIC_COL, "purpose", "start_date_uk", "end_date_uk"
            ]
            daily_cols_export = [c for c in daily_cols_export if c in daily_filt.columns]
            export_daily = daily_filt[daily_cols_export].sort_values(["date", "Team names", "employee"])
            export_daily = add_export_metadata(export_daily, filter_summary)
            st.download_button(
                "Download filtered data (CSV)",
                data=export_daily.to_csv(index=False).encode("utf-8"),
                file_name="absence_daily_log_filtered.csv",
                mime="text/csv",
                key="export_daily"
            )
        if not df_cases_filt.empty:
            exco_monthly = (
                df_cases_filt.groupby(["month", "absence_category"])[METRIC_COL]
                .sum()
                .reset_index()
                .sort_values(["month", METRIC_COL], ascending=[True, False])
            )
            exco_monthly = add_export_metadata(exco_monthly, filter_summary)
            st.download_button(
                "Download monthly summary (CSV)",
                data=exco_monthly.to_csv(index=False).encode("utf-8"),
                file_name="monthly_exco_summary.csv",
                mime="text/csv",
                key="export_monthly"
            )

        with st.expander("Weekly exports", expanded=False):
            if daily_filt.empty or "week_start" not in daily_filt.columns:
                st.info("Weekly exports unavailable (no filtered daily records).")
            else:
                today = pd.Timestamp.today().normalize()
                this_week_start = (today - pd.Timedelta(days=int(today.weekday()))).normalize()
                last_week_start = (this_week_start - pd.Timedelta(days=7)).normalize()

                week_starts = sorted([w for w in daily_filt["week_start"].dropna().unique().tolist()])
                week_labels = {w: f"{w.isocalendar().year}-W{w.isocalendar().week:02d} (from {w.strftime('%d/%m/%Y')})" for w in week_starts}

                preset = st.selectbox("Weekly export preset", options=["This week", "Last week", "Pick a week"], index=0, key="weekly_preset")
                if preset == "This week":
                    chosen_week = this_week_start
                elif preset == "Last week":
                    chosen_week = last_week_start
                else:
                    chosen_week = st.selectbox(
                        "Select week (ISO week)",
                        options=week_starts if week_starts else [this_week_start],
                        format_func=lambda w: week_labels.get(w, str(w)),
                        key="weekly_week"
                    )

                dept_week = weekly_summary(daily_filt, "Team names", chosen_week)
                if not dept_week.empty:
                    dept_week = add_export_metadata(dept_week, filter_summary)
                    st.download_button(
                        "Download Weekly Department Summary (CSV)",
                        data=dept_week.to_csv(index=False).encode("utf-8"),
                        file_name=f"weekly_department_summary_{chosen_week.strftime('%Y-%m-%d')}.csv",
                        mime="text/csv",
                        key="export_dept_week"
                    )
                else:
                    st.caption("No department weekly summary for the selected week (current filters).")

                country_week = weekly_summary(daily_filt, "Country", chosen_week)
                if not country_week.empty:
                    country_week = add_export_metadata(country_week, filter_summary)
                    st.download_button(
                        "Download Weekly Country Summary (CSV)",
                        data=country_week.to_csv(index=False).encode("utf-8"),
                        file_name=f"weekly_country_summary_{chosen_week.strftime('%Y-%m-%d')}.csv",
                        mime="text/csv",
                        key="export_country_week"
                    )
                else:
                    st.caption("No country weekly summary for the selected week (current filters).")

                week_daily = daily_filt[daily_filt["week_start"] == chosen_week].copy()
                if not week_daily.empty:
                    drill_cols = [
                        "case_id", "date_uk", "date", "iso_week", "week_start",
                        "employee", "Team names", "Country", "absence_category", METRIC_COL,
                        "purpose", "start_date_uk", "end_date_uk"
                    ]
                    drill_cols = [c for c in drill_cols if c in week_daily.columns]
                    week_daily = week_daily[drill_cols].sort_values(["date", "Team names", "employee"])
                    week_daily = add_export_metadata(week_daily, filter_summary)
                    st.download_button(
                        "Download Weekly Drilldown (Daily Rows) (CSV)",
                        data=week_daily.to_csv(index=False).encode("utf-8"),
                        file_name=f"weekly_drilldown_daily_rows_{chosen_week.strftime('%Y-%m-%d')}.csv",
                        mime="text/csv",
                        key="export_week_drilldown"
                    )
                else:
                    st.caption("No drilldown daily rows for the selected week (current filters).")

    # ----------------------------
    # BLIP Utilisation (sidebar section)
    # ----------------------------
    with st.expander("BLIP Utilisation", expanded=False):
        st.markdown("---")
        blip_uploaded = st.file_uploader("Upload BLIP export (Excel)", type=["xlsx", "xls"], key="blip_upload", help="Upload a file to use instead of a path.")
        blip_xlsx_path = st.text_input("Or enter Excel file path", value=BLIP_XLSX_DEFAULT, disabled=blip_uploaded is not None, key="blip_path")
        expected_daily_hours = st.number_input("Expected daily hours", 0.0, 24.0, 7.5, 0.5, key="blip_expected_hours")
        include_weekends = st.checkbox("Include weekends (utilisation expected uses selected days)", value=False, key="blip_weekends")
        with st.expander("Exception thresholds", expanded=False):
            short_shift_hours = st.number_input("Short shift threshold (hours)", 0.0, 24.0, 2.0, 0.5, key="blip_short")
            long_shift_hours = st.number_input("Long shift threshold (hours)", 0.0, 24.0, 10.0, 0.5, key="blip_long")

        df_blip = None
        f_blip = None
        f_shift = None
        if blip_uploaded is not None or (blip_xlsx_path and str(blip_xlsx_path).strip()):
            try:
                if blip_uploaded is not None:
                    df_blip = _blip_load_data_from_upload(blip_uploaded)
                else:
                    df_blip = _blip_load_data(blip_xlsx_path)
                if df_blip["date"].notna().sum() == 0:
                    st.warning("No valid dates found in BLIP export 'Clock In Date'.")
                    df_blip, f_blip, f_shift = None, None, None
                else:
                    min_dt_blip, max_dt_blip = df_blip["date"].min(), df_blip["date"].max()
                    d1_blip, d2_blip = st.date_input("Date range", value=(min_dt_blip.date(), max_dt_blip.date()), key="blip_daterange")
                    f_blip = df_blip[(df_blip["date"].dt.date >= d1_blip) & (df_blip["date"].dt.date <= d2_blip)].copy()
                    f_shift = f_blip[f_blip["blip_type_norm"].eq("shift")].copy()
                    if not include_weekends:
                        f_shift = f_shift[f_shift["date"].dt.weekday < 5].copy()
            except Exception as e:
                st.warning(f"Failed to load BLIP file: {e}")
                df_blip, f_blip, f_shift = None, None, None

# ----------------------------
# Tabs (bottom-up flow)
# ----------------------------
tab_individual, tab_department, tab_country, tab_group, tab_blip = st.tabs(
    ["Individual (Daily Log)", "Department", "Country", "Group / ExCo", "BLIP Utilisation"]
)
# =========================================================
# TAB 1: INDIVIDUAL (Firmwide KPIs + Individual table + Optional balances + Evidence)
# =========================================================
with tab_individual:
    if use_custom_date:
        st.markdown(
            '<div class="eg-hint">Custom date range is ON: evidence tables + exports follow the custom range. Monthly charts elsewhere still follow the month selector.</div>',
            unsafe_allow_html=True
        )

    # -----------------------------------------------------
    # Compute annual leave balance (used for: headcount + full-time list + optional detailed expander)
    # -----------------------------------------------------
    employee_balance, entitlement_conflicts, _ = compute_annual_employee_balance(
        df,
        daily_filt,
        weekday_only=True
    )

    # -----------------------------------------------------
    # Full-time employee list (entitlement > 0) + headcount KPIs
    # -----------------------------------------------------
    full_time_emps = []
    full_time = 0
    external_consultants = 0

    if employee_balance is not None and not employee_balance.empty:
        eb = employee_balance.copy()
        eb["Entitlement (days)"] = pd.to_numeric(eb["Entitlement (days)"], errors="coerce").fillna(0)

        full_time_emps = (
            eb.loc[eb["Entitlement (days)"] > 0, "employee"]
            .fillna("")
            .astype(str)
            .tolist()
        )
        full_time_emps = [e for e in full_time_emps if e.strip()]

        full_time = int((eb["Entitlement (days)"] > 0).sum())
        external_consultants = int((eb["Entitlement (days)"] == 0).sum())

    # -----------------------------------------------------
    # Period bounds + weeks in selected period (for WFH allowance)
    # -----------------------------------------------------
    periods = [pd.Period(m, freq="M") for m in months_in_scope]
    period_start = min(p.start_time for p in periods).normalize()
    period_end = max(p.end_time for p in periods).normalize()

    all_days = pd.date_range(period_start, period_end, freq="D")
    week_starts = (all_days - pd.to_timedelta(all_days.weekday, unit="D")).normalize()
    weeks_in_period = int(pd.Series(week_starts).nunique())  # strict: 1 WFH per week

    # -----------------------------------------------------
    # Firmwide daily scope (full-time only)
    # -----------------------------------------------------
    firm_daily = daily_scope.copy()
    if full_time_emps:
        firm_daily = firm_daily[firm_daily["employee"].isin(full_time_emps)].copy()

    taken_fw = {}
    if not firm_daily.empty and "absence_category" in firm_daily.columns:
        taken_fw = firm_daily.groupby("absence_category").size().to_dict()

    wfh_taken_fw = int(taken_fw.get("WFH", 0))
    annual_taken_fw = int(taken_fw.get("Annual Leave", 0))
    sick_taken_fw = int(taken_fw.get("Medical + Sickness", 0))
    travel_taken_fw = int(taken_fw.get("Travel", 0))
    other_taken_fw = int(taken_fw.get("Other (excl. WFH, Travel)", 0))

    # -----------------------------------------------------
    # Annual entitled + remaining (firmwide) from employee_balance (full-time)
    # -----------------------------------------------------
    annual_entitled_fw = 0.0
    annual_remaining_fw = 0.0
    if employee_balance is not None and not employee_balance.empty:
        balance_ft = employee_balance.copy()
        balance_ft["Entitlement (days)"] = pd.to_numeric(
            balance_ft["Entitlement (days)"], errors="coerce"
        ).fillna(0)
        balance_ft = balance_ft[balance_ft["Entitlement (days)"] > 0].copy()

        annual_entitled_fw = float(
            pd.to_numeric(balance_ft["Entitlement (days)"], errors="coerce").fillna(0).sum()
        )
        annual_remaining_fw = float(
            pd.to_numeric(balance_ft["Remaining (days)"], errors="coerce").fillna(0).sum()
        )
    else:
        balance_ft = pd.DataFrame()

    wfh_allowed_fw = int(weeks_in_period * (len(full_time_emps) if full_time_emps else 0))

    # =====================================================
    # 1) Firmwide KPIs — polished layout
    # =====================================================
    st.markdown("### Firmwide KPIs")
    st.caption("Quick snapshot for the selected period and filters (full-time employees only).")

    def _fmt_int(x):
        try:
            return f"{int(x):,}"
        except Exception:
            return str(x)

    def _fmt_days(x):
        try:
            return f"{float(x):,.1f}d"
        except Exception:
            return str(x)

    def kpi_tile(title: str, value: str, subtitle: str = ""):
        st.markdown(
            f"""
            <div style="
              border:1px solid #e5e7eb;
              border-radius:18px;
              padding:14px 16px;
              background:linear-gradient(180deg,#ffffff 0%, #fbfbfb 100%);
              box-shadow:0 1px 2px rgba(0,0,0,0.04);
              ">
              <div style="display:flex; align-items:center; justify-content:space-between;">
                <div style="font-size:0.85rem; color:#6b7280; font-weight:600;">{title}</div>
              </div>
              <div style="font-size:2.1rem; font-weight:900; color:#111827; line-height:1.1; margin-top:6px;">
                {value}
              </div>
              <div style="font-size:0.85rem; color:#6b7280; margin-top:6px;">{subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    def soft_card(title: str, body_html: str = "", footer_html: str = ""):
        st.markdown(
            f"""
            <div style="
              border:1px solid #e5e7eb;
              border-radius:18px;
              padding:14px 16px;
              background:#ffffff;
              box-shadow:0 1px 2px rgba(0,0,0,0.04);
              ">
              <div style="font-size:0.95rem; font-weight:800; color:#111827; margin-bottom:10px;">
                {title}
              </div>
              {body_html}
              {footer_html}
            </div>
            """,
            unsafe_allow_html=True
        )

    # --- Hero row ---
    h1, h2, h3, h4 = st.columns([1.2, 1.2, 1.2, 1.2])
    with h1:
        kpi_tile("Full-time employees", _fmt_int(full_time), "Entitlement > 0 days")
    with h2:
        kpi_tile("External consultants", _fmt_int(external_consultants), "Entitlement = 0 days")
    with h3:
        kpi_tile("Absence days taken", _fmt_int(len(firm_daily)) if not firm_daily.empty else "0", "Daily rows in scope")
    with h4:
        kpi_tile(
            "Weeks in period",
            _fmt_int(weeks_in_period),
            f"{period_start.strftime('%d/%m/%Y')} → {period_end.strftime('%d/%m/%Y')}"
        )

    st.markdown("")

    # --- WFH utilisation + Annual summary ---
    row_a, row_b = st.columns([1.35, 1.65])

    wfh_allowed = int(wfh_allowed_fw)
    wfh_taken = int(wfh_taken_fw)
    wfh_pct = 0.0 if wfh_allowed == 0 else min(100.0, (wfh_taken / wfh_allowed) * 100.0)

    with row_a:
        progress_html = f"""
          <div style="display:flex; gap:14px; align-items:flex-end; margin-bottom:10px;">
            <div style="flex:1;">
              <div style="font-size:0.85rem; color:#6b7280; font-weight:600;">WFH utilisation</div>
              <div style="font-size:1.6rem; font-weight:900; color:#111827; line-height:1.1;">{wfh_pct:.0f}%</div>
            </div>
            <div style="text-align:right;">
              <div style="font-size:0.85rem; color:#6b7280;">Allowed</div>
              <div style="font-size:1.1rem; font-weight:800; color:#111827;">{_fmt_int(wfh_allowed)}</div>
              <div style="font-size:0.85rem; color:#6b7280; margin-top:6px;">Taken</div>
              <div style="font-size:1.1rem; font-weight:800; color:#111827;">{_fmt_int(wfh_taken)}</div>
            </div>
          </div>
        """
        soft_card("Work-from-home", progress_html)
        st.progress(wfh_pct / 100.0)

    with row_b:
        body = f"""
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px;">
            <div style="border:1px solid #eef2f7; border-radius:14px; padding:10px 12px; background:#fbfbfb;">
              <div style="font-size:0.8rem; color:#6b7280; font-weight:600;">Annual entitled</div>
              <div style="font-size:1.25rem; font-weight:900; color:#111827;">{_fmt_days(annual_entitled_fw)}</div>
            </div>
            <div style="border:1px solid #eef2f7; border-radius:14px; padding:10px 12px; background:#fbfbfb;">
              <div style="font-size:0.8rem; color:#6b7280; font-weight:600;">Annual taken</div>
              <div style="font-size:1.25rem; font-weight:900; color:#111827;">{_fmt_int(annual_taken_fw)}d</div>
            </div>
            <div style="border:1px solid #eef2f7; border-radius:14px; padding:10px 12px; background:#fbfbfb;">
              <div style="font-size:0.8rem; color:#6b7280; font-weight:600;">Annual remaining</div>
              <div style="font-size:1.25rem; font-weight:900; color:#111827;">{_fmt_days(annual_remaining_fw)}</div>
            </div>
          </div>
          <div style="margin-top:10px; font-size:0.85rem; color:#6b7280;">
            Remaining is summed from employee balances (full-time only).
          </div>
        """
        soft_card("Annual leave", body)

    st.markdown("")

    # --- Other leave + Leave mix donut ---
       # --- Other leave + Leave mix (aligned cards + proper pie) ---
    left_card, right_card = st.columns([1.05, 1.95])

    with left_card:
        body = f"""
          <div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px;">
            <div style="border:1px solid #eef2f7; border-radius:14px; padding:10px 12px; background:#fbfbfb;">
              <div style="font-size:0.8rem; color:#6b7280; font-weight:600;">Sick</div>
              <div style="font-size:1.25rem; font-weight:900; color:#111827;">{_fmt_int(sick_taken_fw)}d</div>
            </div>
            <div style="border:1px solid #eef2f7; border-radius:14px; padding:10px 12px; background:#fbfbfb;">
              <div style="font-size:0.8rem; color:#6b7280; font-weight:600;">Travel</div>
              <div style="font-size:1.25rem; font-weight:900; color:#111827;">{_fmt_int(travel_taken_fw)}d</div>
            </div>
            <div style="border:1px solid #eef2f7; border-radius:14px; padding:10px 12px; background:#fbfbfb;">
              <div style="font-size:0.8rem; color:#6b7280; font-weight:600;">Other</div>
              <div style="font-size:1.25rem; font-weight:900; color:#111827;">{_fmt_int(other_taken_fw)}d</div>
            </div>
          </div>
        """
        soft_card("Other leave taken", body)

    with right_card:
        # Card header
        soft_card(
            "Leave mix (daily rows)",
            body_html="""
              <div style="font-size:0.85rem; color:#6b7280; margin-top:-4px; margin-bottom:6px;">
                Distribution of daily records in the current scope (full-time only).
              </div>
            """
        )

        # Chart inside a matching card container for alignment
        st.markdown(
            """
            <div style="
              border:1px solid #e5e7eb;
              border-top:0;
              border-radius:0 0 18px 18px;
              padding:10px 12px 6px 12px;
              background:#ffffff;
              box-shadow:0 1px 2px rgba(0,0,0,0.04);
              margin-top:-10px;
            ">
            """,
            unsafe_allow_html=True
        )

        if firm_daily.empty:
            st.info("No daily rows in scope to show the mix.")
        else:
            mix = (
                firm_daily.groupby("absence_category")
                .size()
                .reindex(TYPE_ORDER)
                .fillna(0)
                .reset_index(name="count")
            )
            mix = mix[mix["count"] > 0]

            if mix.empty:
                st.info("No leave categories present in the current scope.")
            else:
                fig_mix = px.pie(
                    mix,
                    names="absence_category",
                    values="count",
                    category_orders={"absence_category": TYPE_ORDER},
                )
                # Proper pie labels (percent + value)
                fig_mix.update_traces(
                    textinfo="percent+value",
                    texttemplate="%{value:.0f} (%{percent})",
                    textposition="inside",
                    sort=False
                )
                fig_mix.update_layout(
                    showlegend=True,
                    legend_title_text="Type",
                    margin=dict(l=10, r=10, t=10, b=10),
                )
                st.plotly_chart(fig_mix, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # -----------------------------------------------------
    # 2) Individual leave table (alphabetical, includes remaining days)
    # -----------------------------------------------------
    st.markdown("### Individual Leave Table (Full-time Employees)")
    st.caption("Employee-level summary for the selected period. Sorted alphabetically. Includes Annual remaining (days).")

    if balance_ft.empty or not full_time_emps:
        st.info("No full-time employees with leave entitlement found in the current scope.")
    else:
        emp_taken = (
            daily_scope[daily_scope["employee"].isin(full_time_emps)]
            .groupby(["employee", "absence_category"])
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )

        for col in ["WFH", "Annual Leave", "Medical + Sickness", "Travel", "Other (excl. WFH, Travel)"]:
            if col not in emp_taken.columns:
                emp_taken[col] = 0

        emp_taken = emp_taken.rename(columns={
            "WFH": "WFH taken (days)",
            "Annual Leave": "Annual taken (days)",
            "Medical + Sickness": "Sick taken (days)",
            "Travel": "Travel taken (days)",
            "Other (excl. WFH, Travel)": "Other taken (days)",
        })

        meta = balance_ft[[
            "employee", "Team names", "Country",
            "Entitlement (days)", "Remaining (days)"
        ]].copy().rename(columns={
            "Entitlement (days)": "Annual entitled (days)",
            "Remaining (days)": "Annual remaining (days)"
        })

        ind_tbl = meta.merge(emp_taken, on="employee", how="left").fillna(0)
        ind_tbl["WFH allowed (weeks)"] = weeks_in_period

        ind_tbl["employee"] = ind_tbl["employee"].fillna("").astype(str)
        ind_tbl = ind_tbl.sort_values("employee", ascending=True)

        ind_tbl = ind_tbl[[
            "employee", "Team names", "Country",
            "WFH allowed (weeks)", "WFH taken (days)",
            "Annual entitled (days)", "Annual taken (days)", "Annual remaining (days)",
            "Sick taken (days)", "Travel taken (days)", "Other taken (days)"
        ]]

        for c in ["Annual entitled (days)", "Annual remaining (days)"]:
            ind_tbl[c] = pd.to_numeric(ind_tbl[c], errors="coerce").round(1)

        st.dataframe(ind_tbl, use_container_width=True, hide_index=True)

    st.markdown("---")

    # -----------------------------------------------------
    # 3) Optional: Detailed annual leave balances (expander)
    # -----------------------------------------------------
    st.markdown("### Detailed Annual Leave Balances")
    with st.expander("Detailed Annual Leave Balances (HR view)", expanded=False):
        if entitlement_conflicts is not None and not entitlement_conflicts.empty:
            st.warning("Entitlement values vary for some employees in the dataset. Review below.")
            st.dataframe(entitlement_conflicts, use_container_width=True, hide_index=True)

        if balance_ft.empty:
            st.info("No balance table available in the current scope.")
        else:
            view_tbl = balance_ft.sort_values(["Remaining (days)", "Used (days)"], ascending=[True, False])
            st.dataframe(view_tbl, use_container_width=True, hide_index=True)

    st.markdown("---")

    # -----------------------------------------------------
    # 4) Daily Evidence (Investigation) — Collapsible (NO case_id)
    # -----------------------------------------------------
    st.markdown('<h3 class="eg-section-title">Daily Evidence (Investigation)</h3>', unsafe_allow_html=True)
    st.caption("Open only when evidence is needed. Filters here do not change the rest of the dashboard.")

    with st.expander("Open evidence log + investigation filters", expanded=False):
        ev_col1, ev_col2 = st.columns(2)
        with ev_col1:
            ev_employee_q = st.text_input("Employee search", value="", key="ev_employee_q")
        with ev_col2:
            ev_keyword_q = st.text_input("Keyword in purpose/description", value="", key="ev_keyword_q")

        ev_col3, ev_col4 = st.columns(2)
        with ev_col3:
            ev_dept_options = sorted([
                d for d in df_scope["Team names"].fillna("").astype(str).unique().tolist() if d.strip()
            ])
            ev_depts = st.multiselect("Departments", options=ev_dept_options, default=[], key="ev_depts")
        with ev_col4:
            ev_country_options = sorted([
                c for c in df_scope["Country"].fillna("").astype(str).unique().tolist() if c.strip()
            ])
            ev_countries = st.multiselect("Countries", options=ev_country_options, default=[], key="ev_countries")

        ev_cats = st.multiselect("Absence types", options=TYPE_ORDER, default=[], key="ev_cats")
        ev_use_custom_date = st.checkbox("Use custom date range (evidence only)", value=False, key="ev_use_custom_date")

        ev_date_range = None
        if ev_use_custom_date and (not daily_scope.empty) and ("date" in daily_scope.columns):
            min_dt = pd.to_datetime(daily_scope["date"], errors="coerce").min()
            max_dt = pd.to_datetime(daily_scope["date"], errors="coerce").max()
            if not pd.isna(min_dt) and not pd.isna(max_dt):
                dr = st.date_input(
                    "Custom date range",
                    value=(min_dt.date(), max_dt.date()),
                    key="ev_date_range"
                )
                ev_date_range = dr if isinstance(dr, tuple) else (dr, dr)

        ev_daily = daily_scope.copy()

        if ev_employee_q.strip():
            ev_daily = ev_daily[
                ev_daily["employee"].fillna("").astype(str).str.contains(ev_employee_q.strip(), case=False, na=False)
            ]
        if ev_keyword_q.strip():
            ev_daily = ev_daily[
                ev_daily["purpose"].fillna("").astype(str).str.contains(ev_keyword_q.strip(), case=False, na=False)
            ]
        if ev_depts:
            ev_daily = ev_daily[ev_daily["Team names"].isin(ev_depts)]
        if ev_countries:
            ev_daily = ev_daily[ev_daily["Country"].isin(ev_countries)]
        if ev_cats:
            ev_daily = ev_daily[ev_daily["absence_category"].isin(ev_cats)]
        if ev_use_custom_date and ev_date_range and (not ev_daily.empty) and ("date" in ev_daily.columns):
            d1, d2 = ev_date_range
            ev_daily = ev_daily[(ev_daily["date"].dt.date >= d1) & (ev_daily["date"].dt.date <= d2)]

        if ev_daily.empty:
            st.info("No daily records match the investigation filters.")
        else:
            cols_to_show = [
                "date_uk",
                "employee",
                "Team names",
                "Country",
                "absence_category",
                METRIC_COL,
                "purpose",
                "start_date_uk",
                "end_date_uk",
            ]
            cols_to_show = [c for c in cols_to_show if c in ev_daily.columns]
            ev_daily_sorted = ev_daily.sort_values(["date", "Team names", "employee"], ascending=[True, True, True])
            st.dataframe(ev_daily_sorted[cols_to_show], use_container_width=True, hide_index=True)

# =========================================================
# TAB 2: DEPARTMENT (Step 5 rollup + monthly chart)
# =========================================================
with tab_department:
    if use_custom_date:
        st.markdown(
            '<div class="eg-hint">Reminder: custom date range affects evidence tables + exports. The chart below uses month selection.</div>',
            unsafe_allow_html=True
        )

    st.markdown('<h3 class="eg-section-title">Department Views</h3>', unsafe_allow_html=True)

    # -----------------------------------------------------
    # Department list (authoritative) from scoped case data
    # This guarantees depts like "AG Legal" appear if present in df_cases_filt.
    # -----------------------------------------------------
    if "Team names" in df_cases_filt.columns:
        scope_depts_series = (
            df_cases_filt["Team names"]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
        depts_in_scope = sorted([d for d in scope_depts_series.unique().tolist() if d])
    else:
        depts_in_scope = []

    # -----------------------------------------------------
    # Prepare employee balance (clean + full-time only)
    # -----------------------------------------------------
    if employee_balance is None or employee_balance.empty:
        balance_all = pd.DataFrame()
        balance_ft = pd.DataFrame()
    else:
        balance_all = employee_balance.copy()

        balance_all["Team names"] = (
            balance_all["Team names"]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )

        balance_all["Entitlement (days)"] = pd.to_numeric(
            balance_all["Entitlement (days)"], errors="coerce"
        ).fillna(0)

        # Full-time employees only
        balance_ft = balance_all[balance_all["Entitlement (days)"] > 0].copy()

    # -----------------------------------------------------
    # Department Rollup (Full-time employees only) — clean view
    # -----------------------------------------------------
    st.markdown("### Annual Leave Balance (Department Rollup) — Full-time employees")

    dept_rollup = rollup_balance(balance_ft, "Team names") if not balance_ft.empty else pd.DataFrame()

    if dept_rollup.empty:
        st.info("No full-time employees with leave entitlement in the current scope.")
    else:
        st.dataframe(dept_rollup, use_container_width=True, hide_index=True)

    # -----------------------------------------------------
    # Department drilldown (ALL departments in scope)
    # -----------------------------------------------------
    st.markdown("**Department drilldown (employees)**")

    if not depts_in_scope:
        st.info("No departments found in the current scope.")
    else:
        selected_dept = st.selectbox("Select a department", options=depts_in_scope)

        if balance_all.empty:
            st.info("Employee balance data unavailable for the current scope.")
        else:
            drill_ft = balance_ft[balance_ft["Team names"] == selected_dept].copy()

            if drill_ft.empty:
                # Dept exists in scope, but no full-time employees found
                drill_all = balance_all[balance_all["Team names"] == selected_dept].copy()
                consultants_ct = int((drill_all["Entitlement (days)"] == 0).sum()) if not drill_all.empty else 0

                st.info(
                    f"No full-time employees with leave entitlement found for **{selected_dept}** "
                    f"in the current scope. External consultants: {consultants_ct}."
                )
            else:
                drill_ft = drill_ft.sort_values(
                    ["Remaining (days)", "Used (days)"],
                    ascending=[True, False]
                )
                st.dataframe(
                    drill_ft[["employee", "Entitlement (days)", "Used (days)", "Remaining (days)", "Country"]],
                    use_container_width=True,
                    hide_index=True
                )

    st.markdown("---")
    st.markdown('<h3 class="eg-section-title">Department Level Analysis</h3>', unsafe_allow_html=True)
    st.caption("Absence days by department. Chart filters affect visuals only.")

    # -----------------------------------------------------
    # Monthly department absence chart (case-level data)
    # Normalise dept names to keep consistent labels
    # -----------------------------------------------------
    df_dept = df_cases_filt.copy()
    if "Team names" in df_dept.columns:
        df_dept["Team names"] = (
            df_dept["Team names"]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )

    all_depts_chart = sorted([d for d in df_dept["Team names"].dropna().unique().tolist() if d])
    selected_depts_chart = st.multiselect(
        "Chart filter: departments",
        options=all_depts_chart,
        default=[]
    )

    if selected_depts_chart:
        df_dept = df_dept[df_dept["Team names"].isin(selected_depts_chart)]

    dept_type = (
        df_dept.groupby(["month", "Team names", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )

    dept_list = sorted([d for d in df_dept["Team names"].dropna().unique().tolist() if d])
    if not dept_list:
        st.info("No department data available for the selected scope.")
        st.stop()

    dept_grid = pd.MultiIndex.from_product(
        [months_in_scope, dept_list, TYPE_ORDER],
        names=["month", "Team names", "absence_category"]
    ).to_frame(index=False)

    dept_type = dept_grid.merge(
        dept_type,
        on=["month", "Team names", "absence_category"],
        how="left"
    )
    dept_type[METRIC_COL] = dept_type[METRIC_COL].fillna(0)

    dept_totals = (
        dept_type.groupby("Team names")[METRIC_COL]
        .sum()
        .sort_values(ascending=False)
    )
    dept_type["Team names"] = pd.Categorical(
        dept_type["Team names"],
        categories=dept_totals.index,
        ordered=True
    )

    if month_2:
        left, sep, right = st.columns([5, 0.25, 5])

        with left:
            fig_m1 = px.bar(
                dept_type[dept_type["month"] == month_1],
                x="Team names",
                y=METRIC_COL,
                color="absence_category",
                category_orders={"absence_category": TYPE_ORDER},
            )
            fig_m1.update_layout(
                barmode="stack",
                title=dict(text=month_1, x=0.5),
                legend_title_text="Absence type",
                margin=dict(t=60)
            )
            fig_m1.update_xaxes(tickangle=-35)
            st.plotly_chart(fig_m1, use_container_width=True)

        with sep:
            st.markdown('<div class="eg-vertical-divider-donut">&nbsp;</div>', unsafe_allow_html=True)

        with right:
            fig_m2 = px.bar(
                dept_type[dept_type["month"] == month_2],
                x="Team names",
                y=METRIC_COL,
                color="absence_category",
                category_orders={"absence_category": TYPE_ORDER},
            )
            fig_m2.update_layout(
                barmode="stack",
                title=dict(text=month_2, x=0.5),
                legend_title_text="Absence type",
                margin=dict(t=60)
            )
            fig_m2.update_xaxes(tickangle=-35)
            st.plotly_chart(fig_m2, use_container_width=True)

    else:
        fig_dept = px.bar(
            dept_type[dept_type["month"] == month_1],
            x="Team names",
            y=METRIC_COL,
            color="absence_category",
            category_orders={"absence_category": TYPE_ORDER},
        )
        fig_dept.update_layout(
            barmode="stack",
            title=dict(text=month_1, x=0.5),
            legend_title_text="Absence type",
            margin=dict(t=60)
        )
        fig_dept.update_xaxes(tickangle=-35)
        st.plotly_chart(fig_dept, use_container_width=True)


# =========================================================
# TAB 3: COUNTRY (rollup + evidence drilldown)
# =========================================================
with tab_country:
    if use_custom_date:
        st.markdown(
            '<div class="eg-hint">Reminder: custom date range affects evidence tables + exports. The charts here use month selection.</div>',
            unsafe_allow_html=True
        )

    st.markdown('<h3 class="eg-section-title">Country View</h3>', unsafe_allow_html=True)
    st.caption("Country-level rollup (filtered) + evidence drilldown.")

    if "Country" not in df_cases_filt.columns:
        st.info("No Country field found in the dataset.")
        st.stop()

    country_options = sorted(df_cases_filt["Country"].dropna().unique().tolist())
    if not country_options:
        st.info("No country values found for the current filtered scope.")
        st.stop()

    if "selected_country" not in st.session_state:
        st.session_state.selected_country = country_options[0]

    st.markdown("**Select country**")
    cols = st.columns(len(country_options))
    for i, c in enumerate(country_options):
        if cols[i].button(
            c,
            use_container_width=True,
            type="primary" if st.session_state.selected_country == c else "secondary"
        ):
            st.session_state.selected_country = c

    selected_country = st.session_state.selected_country
    df_country = df_cases_filt[df_cases_filt["Country"] == selected_country].copy()

    st.markdown("---")
    st.markdown("### Annual Leave Balance (Country Rollup) — Filtered")
    country_rollup = rollup_balance(employee_balance, "Country") if not employee_balance.empty else pd.DataFrame()
    if country_rollup.empty:
        st.info("No country rollup available for the current filtered scope.")
    else:
        st.dataframe(country_rollup, use_container_width=True, hide_index=True)

        st.markdown(f"**Selected country drilldown (employees): {selected_country}**")
        drill_emp = employee_balance[employee_balance["Country"] == selected_country].copy()
        if drill_emp.empty:
            st.info("No employees found for this country in the balance table.")
        else:
            drill_emp = drill_emp.sort_values(["Remaining (days)", "Used (days)"], ascending=[True, False])
            st.dataframe(
                drill_emp[["employee", "Team names", "Entitlement (days)", "Used (days)", "Remaining (days)"]],
                use_container_width=True,
                hide_index=True
            )

    st.markdown("---")

    total_days_m1 = float(df_country[df_country["month"] == month_1][METRIC_COL].sum())
    total_days_m2 = float(df_country[df_country["month"] == month_2][METRIC_COL].sum()) if month_2 else None

    k1, k2, k3 = st.columns(3)
    with k1:
        st.metric(f"{selected_country} days ({month_1})", fmt_num(total_days_m1))
    with k2:
        if month_2:
            diff = total_days_m2 - total_days_m1
            if total_days_m1 == 0:
                delta_str = "N/A (baseline 0)" if total_days_m2 != 0 else "0.0%"
            else:
                delta_str = f"{(diff / total_days_m1 * 100):.1f}%"
            st.metric(f"{selected_country} days ({month_2})", fmt_num(total_days_m2), f"{diff:+.1f}d ({delta_str})")
        else:
            st.metric("Departments", str(df_country["Team names"].nunique()))
    with k3:
        st.metric("Employees", str(df_country["employee"].nunique()))

    st.markdown("---")

    pie_country = (
        df_country.groupby(["month", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )
    grid = pd.MultiIndex.from_product([months_in_scope, TYPE_ORDER], names=["month", "absence_category"]).to_frame(index=False)
    pie_country = grid.merge(pie_country, on=["month", "absence_category"], how="left")
    pie_country[METRIC_COL] = pie_country[METRIC_COL].fillna(0)

    def pie_for_month(m: str):
        d = pie_country[pie_country["month"] == m].copy()
        d = d[d[METRIC_COL] > 0]
        if d.empty:
            st.info(f"No absence data for {selected_country} in {m}.")
            return
        fig = px.pie(d, names="absence_category", values=METRIC_COL, category_orders={"absence_category": TYPE_ORDER})
        fig.update_traces(textinfo="percent+value", texttemplate="%{value:.1f}d (%{percent})", textposition="inside", sort=False)
        fig.update_layout(title=dict(text=f"{selected_country} • {m}", x=0.5), legend_title_text="Absence type", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    if month_2:
        c1, c2 = st.columns(2)
        with c1: pie_for_month(month_1)
        with c2: pie_for_month(month_2)
    else:
        pie_for_month(month_1)

    st.markdown("---")

    st.markdown("**Country drilldown (daily log) — Filtered**")
    daily_country = daily_filt[daily_filt["Country"] == selected_country].copy() if not daily_filt.empty else pd.DataFrame()
    drill_cols = ["case_id", "date_uk", "Country", "Team names", "employee", "absence_category", METRIC_COL, "purpose"]
    drill_cols = [c for c in drill_cols if (not daily_country.empty and c in daily_country.columns)]
    if daily_country.empty:
        st.info("No daily records found for the selected country (current filters).")
    else:
        daily_country = daily_country.sort_values(["date", "Team names", "employee"])
        st.dataframe(daily_country[drill_cols], use_container_width=True, hide_index=True)

# =========================================================
# TAB 4: GROUP / EXCO (monthly visuals)
# =========================================================
with tab_group:
    if use_custom_date:
        st.markdown(
            '<div class="eg-hint">Reminder: custom date range affects evidence tables + exports. ExCo charts use month selection.</div>',
            unsafe_allow_html=True
        )

    st.markdown('<h3 class="eg-section-title">Group / ExCo View</h3>', unsafe_allow_html=True)
    st.caption("Monthly KPIs and leave mix (filtered), suitable for senior leadership.")

    st.markdown('<h3 class="eg-section-title">KPIs</h3>', unsafe_allow_html=True)

    monthly_days = df_cases_filt.groupby("month")[METRIC_COL].sum()
    days_m1 = float(monthly_days.get(month_1, 0))

    if month_2:
        days_m2 = float(monthly_days.get(month_2, 0))
        diff = days_m2 - days_m1
        if days_m1 == 0:
            delta_str = "N/A (baseline 0)" if days_m2 != 0 else "0.0%"
        else:
            delta_str = f"{(diff / days_m1 * 100):.1f}%"

        sp_l, c1, c2, c3, sp_r = st.columns([1, 2, 2, 2, 1])
        with c1: st.metric(f"Absence days ({month_1})", fmt_num(days_m1))
        with c2: st.metric(f"Absence days ({month_2})", fmt_num(days_m2))
        with c3: st.metric("Change", fmt_num(diff), delta_str)
    else:
        sp_l, c1, sp_r = st.columns([2, 3, 2])
        with c1: st.metric(f"Absence days ({month_1})", fmt_num(days_m1))

    st.markdown("---")

    st.markdown('<h3 class="eg-section-title">Leave-type KPI breakdown</h3>', unsafe_allow_html=True)

    type_month = (
        df_cases_filt.groupby(["month", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )

    grid = pd.MultiIndex.from_product([months_in_scope, TYPE_ORDER], names=["month", "absence_category"]).to_frame(index=False)
    type_month = grid.merge(type_month, on=["month", "absence_category"], how="left")
    type_month[METRIC_COL] = type_month[METRIC_COL].fillna(0)

    def render_type_kpis_for_month(m: str, show_delta: bool):
        st.markdown(f"**{m}**")
        m_series = type_month[type_month["month"] == m].set_index("absence_category")[METRIC_COL].reindex(TYPE_ORDER).fillna(0)
        baseline = type_month[type_month["month"] == month_1].set_index("absence_category")[METRIC_COL].reindex(TYPE_ORDER).fillna(0)

        cols = st.columns(len(TYPE_ORDER))
        for i, cat in enumerate(TYPE_ORDER):
            v = float(m_series.loc[cat])
            if show_delta and month_2 and m == month_2:
                v0 = float(baseline.loc[cat])
                d = v - v0
                if v0 == 0:
                    pct_str = "N/A" if v != 0 else "0.0%"
                else:
                    pct_str = f"{(d / v0 * 100):+.1f}%"
                cols[i].metric(cat, fmt_num(v), f"{d:+.1f}d ({pct_str})")
            else:
                cols[i].metric(cat, fmt_num(v))

    if month_2:
        left, sep, right = st.columns([5, 0.25, 5])
        with left: render_type_kpis_for_month(month_1, show_delta=False)
        with sep: st.markdown('<div class="eg-vertical-divider-kpi">&nbsp;</div>', unsafe_allow_html=True)
        with right: render_type_kpis_for_month(month_2, show_delta=True)
    else:
        render_type_kpis_for_month(month_1, show_delta=False)

    st.markdown("---")

    st.markdown('<h3 class="eg-section-title">Absence by Type</h3>', unsafe_allow_html=True)

    pie_df = (
        df_cases_filt.groupby(["month", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )

    grid = pd.MultiIndex.from_product([months_in_scope, TYPE_ORDER], names=["month", "absence_category"]).to_frame(index=False)
    pie_df = grid.merge(pie_df, on=["month", "absence_category"], how="left")
    pie_df[METRIC_COL] = pie_df[METRIC_COL].fillna(0)

    def donut_for_month(m: str):
        d = pie_df[pie_df["month"] == m].copy()
        d = d[d[METRIC_COL] > 0]
        if d.empty:
            st.info(f"No absence days for {m}.")
            return

        fig = px.pie(d, names="absence_category", values=METRIC_COL, hole=0.55, category_orders={"absence_category": TYPE_ORDER})
        fig.update_traces(textinfo="percent+value", texttemplate="%{percent} (%{value:.1f}d)", textposition="inside", sort=False)
        fig.update_layout(showlegend=True, legend_title_text="Absence type", margin=dict(l=10, r=10, t=40, b=10), title=dict(text=m, x=0.5, xanchor="center"))
        st.plotly_chart(fig, use_container_width=True)

    if month_2:
        c1, sep2, c2 = st.columns([5, 0.25, 5])
        with c1: donut_for_month(month_1)
        with sep2: st.markdown('<div class="eg-vertical-divider-donut">&nbsp;</div>', unsafe_allow_html=True)
        with c2: donut_for_month(month_2)
    else:
        donut_for_month(month_1)

# =========================================================
# TAB 5: BLIP Utilisation
# =========================================================
with tab_blip:
    st.caption("Data and date range are set in the sidebar (BLIP Utilisation section).")
    if f_shift is None or (hasattr(f_shift, "empty") and f_shift.empty):
        st.info("Configure BLIP data source in the sidebar (upload an Excel file or enter a path).")
    else:
        entries_all = len(f_blip)
        entries_shift = len(f_shift)
        employees_blip = f_shift["employee"].nunique()
        teams_blip = f_shift[BLIP_COL_TEAM].nunique() if BLIP_COL_TEAM in f_shift.columns else 0
        missing_clockouts = (~f_shift["has_clockout"]).sum()
        worked_total = f_shift["worked_hours"].sum(skipna=True)
        duration_total = f_shift["duration_hours"].sum(skipna=True)
        break_total = f_shift["break_hours"].sum(skipna=True)
        avg_worked_shift = f_shift["worked_hours"].mean(skipna=True)

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Entries (all)", f"{entries_all:,}")
        k2.metric("Shift entries", f"{entries_shift:,}")
        k3.metric("Employees", f"{employees_blip:,}")
        k4.metric("Missing clock-outs", f"{int(missing_clockouts):,}")
        k5.metric("Worked hours", fmt_hours_minutes(worked_total))
        k6.metric("Avg worked / shift", fmt_hours_minutes(avg_worked_shift))

        st.markdown(
            f'<div class="eg-hint"><b>Shift totals in selected range:</b> Total Duration = <b>{fmt_hours_minutes(duration_total)}</b> · Break = <b>{fmt_hours_minutes(break_total)}</b> · Worked (excl breaks) = <b>{fmt_hours_minutes(worked_total)}</b></div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")

        st.markdown('<h3 class="eg-section-title">Daily Utilisation (Shift rows only)</h3>', unsafe_allow_html=True)
        daily_blip = f_shift.groupby("date", as_index=False).agg(WorkedHours=("worked_hours", "sum"), Employees=("employee", "nunique"))
        daily_blip["Expected"] = daily_blip["Employees"] * expected_daily_hours
        daily_blip["Utilisation"] = _blip_safe_divide(daily_blip["WorkedHours"].values, daily_blip["Expected"].values)
        fig_daily = px.bar(daily_blip, x="date", y="Utilisation", color=daily_blip["Utilisation"] >= 1.0, color_discrete_map={True: "green", False: "red"})
        fig_daily.add_hline(y=1.0, line_dash="dash")
        fig_daily.update_yaxes(tickformat=".0%")
        st.plotly_chart(_blip_clean_plot(fig_daily, "Utilisation"), use_container_width=True)
        st.markdown("---")

        st.markdown('<h3 class="eg-section-title">Weekly Utilisation (Shift rows only)</h3>', unsafe_allow_html=True)
        weekly_blip = f_shift.groupby("week_start", as_index=False).agg(WorkedHours=("worked_hours", "sum"), Employees=("employee", "nunique"))
        expected_days = 7 if include_weekends else 5
        weekly_blip["Expected"] = weekly_blip["Employees"] * expected_daily_hours * expected_days
        weekly_blip["Utilisation"] = _blip_safe_divide(weekly_blip["WorkedHours"].values, weekly_blip["Expected"].values)
        fig_weekly = px.line(weekly_blip, x="week_start", y="Utilisation", markers=True)
        fig_weekly.add_hline(y=1.0, line_dash="dash")
        fig_weekly.update_yaxes(tickformat=".0%")
        st.plotly_chart(_blip_clean_plot(fig_weekly, "Utilisation"), use_container_width=True)
        st.markdown("---")

        st.markdown('<h3 class="eg-section-title">Monthly Hours (Shift rows only)</h3>', unsafe_allow_html=True)
        monthly_blip = f_shift.groupby("month", as_index=False).agg(WorkedHours=("worked_hours", "sum"), BreakHours=("break_hours", "sum"), DurationHours=("duration_hours", "sum"))
        m_long = monthly_blip.melt(id_vars=["month"], value_vars=["WorkedHours", "BreakHours"], var_name="Type", value_name="Hours")
        fig_monthly = px.bar(m_long, x="month", y="Hours", color="Type")
        st.plotly_chart(_blip_clean_plot(fig_monthly, "Hours", "Month"), use_container_width=True)
        st.markdown("---")

        with st.expander("View Shift-level table (selected range)"):
            show_cols = ["date", "employee", BLIP_COL_TEAM if BLIP_COL_TEAM in f_shift.columns else None, BLIP_COL_ROLE if BLIP_COL_ROLE in f_shift.columns else None, "worked_hours", "break_hours", "duration_hours", "has_clockout", "location_mismatch"]
            show_cols = [c for c in show_cols if c is not None]
            shift_display = f_shift[show_cols].sort_values(["date", "employee"]).copy()
            for col in ["worked_hours", "break_hours", "duration_hours"]:
                if col in shift_display.columns:
                    shift_display[col] = shift_display[col].apply(lambda x: fmt_hours_minutes(x) if pd.notna(x) else "")
            st.dataframe(shift_display, use_container_width=True)

        st.markdown('<h3 class="eg-section-title">Employee View (Work–Break–Work by Day)</h3>', unsafe_allow_html=True)
        if f_blip.empty:
            st.info("No rows available for the selected date range.")
        else:
            emp_list = sorted([e for e in f_blip["employee"].dropna().unique() if str(e).strip() != ""])
            if not emp_list:
                st.info("No employees found in the selected date range.")
            else:
                sel_emp = st.selectbox("Select employee", options=emp_list, index=0, key="blip_emp")
                emp_all = f_blip[f_blip["employee"].eq(sel_emp)].copy()
                emp_all = emp_all[emp_all["clockin_dt"].notna() & emp_all["clockout_dt"].notna()].copy()
                if emp_all.empty:
                    st.warning("No valid clock-in/clock-out timestamps found for this employee in the selected range.")
                else:
                    emp_all["day"] = emp_all["clockin_dt"].dt.date
                    rows_seg = []
                    for day, day_df in emp_all.groupby("day"):
                        segs = _blip_build_authentic_day_segments(day_df)
                        for idx, s in enumerate(segs, start=1):
                            hrs = (s["end"] - s["start"]).total_seconds() / 3600
                            if hrs <= 0:
                                continue
                            rows_seg.append({"date": pd.to_datetime(day), "Segment": f"{idx:02d} {s['kind']}", "Kind": s["kind"], "Hours": hrs, "SegIndex": idx})
                    seg_df = pd.DataFrame(rows_seg)
                    if seg_df.empty:
                        st.warning("Could not construct Work/Break segments from timestamps. Break rows may lack clock-in/out times or only Shift rows exist.")
                    else:
                        seg_order = seg_df.sort_values(["date", "SegIndex"]).groupby("date")["Segment"].apply(list).explode().unique().tolist()
                        fig_seg = px.bar(seg_df, x="date", y="Hours", color="Segment", barmode="stack", category_orders={"Segment": seg_order}, color_discrete_map={seg: ("red" if "Break" in seg else "green") for seg in seg_df["Segment"].unique()})
                        max_h_seg = seg_df["Hours"].max() if not seg_df.empty else 8
                        tickvals_s, ticktext_s = _hours_axis_ticks(max_h_seg)
                        fig_seg.update_layout(yaxis=dict(tickvals=tickvals_s, ticktext=ticktext_s))
                        st.plotly_chart(_blip_clean_plot(fig_seg, y_title="Hours", x_title="Date"), use_container_width=True)
                        daily_totals = seg_df.groupby(["date", "Kind"], as_index=False)["Hours"].sum()
                        piv = daily_totals.pivot(index="date", columns="Kind", values="Hours").fillna(0).reset_index()
                        piv["Total"] = piv.get("Work", 0) + piv.get("Break", 0)
                        piv["Hours beyond 6"] = (piv.get("Work", 0) - 6).clip(lower=0)
                        with st.expander("View daily totals (from timestamps)"):
                            piv_display = piv.sort_values("date").copy()
                            for col in ["Work", "Break", "Total", "Hours beyond 6"]:
                                if col in piv_display.columns:
                                    piv_display[col] = piv_display[col].apply(lambda x: fmt_hours_minutes(x) if pd.notna(x) else "")
                            st.dataframe(piv_display, use_container_width=True)
                        beyond_6_total = piv["Hours beyond 6"].sum()
                        st.caption(f"Total hours beyond 6 (selected period): **{fmt_hours_minutes(beyond_6_total)}**")

        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Exceptions Overview (Shift rows only)</h3>', unsafe_allow_html=True)
        short_shifts = (f_shift["worked_hours"] < short_shift_hours).sum()
        long_shifts = (f_shift["worked_hours"] > long_shift_hours).sum()
        location_mismatch = f_shift["location_mismatch"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Missing clock-outs", int(missing_clockouts))
        c2.metric(f"Short shifts (worked < {fmt_hours_minutes(short_shift_hours)})", int(short_shifts))
        c3.metric(f"Long shifts (worked > {fmt_hours_minutes(long_shift_hours)})", int(long_shifts))
        c4.metric("Location mismatches", int(location_mismatch))
        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Exports</h3>', unsafe_allow_html=True)
        export_ts = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        sort_cols = ["date", "employee"]
        if BLIP_COL_TEAM in f_shift.columns:
            sort_cols = ["date", BLIP_COL_TEAM, "employee"]
        shift_export = f_shift[show_cols].sort_values(sort_cols).copy()
        shift_export["generated_at"] = export_ts
        st.download_button("Download Shift-level table (CSV)", data=shift_export.to_csv(index=False).encode("utf-8"), file_name="blip_shift_table.csv", mime="text/csv", key="blip_export_shift")
        weekly_export = weekly_blip.copy()
        weekly_export["generated_at"] = export_ts
        st.download_button("Download Weekly utilisation summary (CSV)", data=weekly_export.to_csv(index=False).encode("utf-8"), file_name="blip_weekly_utilisation.csv", mime="text/csv", key="blip_export_weekly")
        monthly_export = monthly_blip.copy()
        monthly_export["generated_at"] = export_ts
        st.download_button("Download Monthly hours summary (CSV)", data=monthly_export.to_csv(index=False).encode("utf-8"), file_name="blip_monthly_hours.csv", mime="text/csv", key="blip_export_monthly")
