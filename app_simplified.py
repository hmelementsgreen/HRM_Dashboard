"""
Simplified Leave Management & Time Utilisation dashboard.
Leave Management: 4 tabs (Individual, Department, Country, Group/ExCo) with bar chart per view.
Time Utilisation: unchanged from main app.
"""
import io
import math
import os
import re
import hashlib
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Leave & Time Utilisation", layout="wide")

st.markdown("""
<style>
  :root {
    --eg-text: #111827; --eg-muted: #6b7280; --eg-border: #e5e7eb; --eg-radius: 12px; --eg-accent: #0d9488; --eg-shadow: 0 2px 8px rgba(0,0,0,0.06);
    --eg-space-sm: 0.75rem; --eg-space-md: 1rem; --eg-space-lg: 1.5rem;
    --eg-font-hero: 2rem; --eg-font-section: 1.25rem; --eg-font-kpi: 1.5rem; --eg-font-label: 0.8rem; --eg-font-caption: 0.9rem;
  }
  .eg-title { text-align: center; margin-top: 0.5rem; margin-bottom: 0.25rem; color: var(--eg-text); font-size: 1.75rem; font-weight: 800; }
  .eg-subtitle { text-align: center; color: var(--eg-muted); margin-bottom: 1.25rem; font-size: 0.95rem; }
  .eg-section-title { margin-top: 0.25rem; margin-bottom: 0.25rem; padding-bottom: 0.35rem; }
  .eg-spacer { height: 1.5rem; }
  .eg-spacer-sm { height: var(--eg-space-sm); }
  .eg-spacer-md { height: var(--eg-space-md); }
  .eg-spacer-lg { height: var(--eg-space-lg); }
  .eg-line-gap { height: 1.5em; }
  .eg-chart-separator { border-left: 2px solid var(--eg-border); min-height: 520px; margin: 0 0.25rem; }
  .eg-text-hero { font-size: var(--eg-font-hero); font-weight: 800; color: var(--eg-accent); }
  .eg-text-section { font-size: var(--eg-font-section); font-weight: 700; color: var(--eg-text); }
  .eg-text-caption { font-size: var(--eg-font-caption); color: var(--eg-muted); }
  .eg-card { border: 1px solid var(--eg-border); border-radius: var(--eg-radius); padding: 14px 16px; box-shadow: var(--eg-shadow); }
  .eg-breadcrumb { font-size: var(--eg-font-caption); color: var(--eg-muted); margin: 0.25rem 0; }
  .eg-kpi-tile { border: none; border-radius: 8px; padding: 14px 16px; background: #fafafa; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
  .eg-kpi-tile .eg-kpi-label { font-size: var(--eg-font-label); color: var(--eg-muted); }
  .eg-kpi-tile .eg-kpi-value { font-size: var(--eg-font-kpi); font-weight: 800; color: var(--eg-text); }
  .eg-kpi-tile .eg-kpi-sub { font-size: 0.75rem; color: var(--eg-muted); }
  div[data-testid="stMetric"] { text-align: center; }
  [data-baseweb="tab-list"] button[aria-selected="true"] { font-weight: 700; border-bottom: 2px solid var(--eg-accent); background: rgba(13, 148, 136, 0.08); }
</style>
""", unsafe_allow_html=True)

# ----------------------------
# Constants
# ----------------------------
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH_DEFAULT = os.path.join(_APP_DIR, "AbsenseReport_Cleaned_Final.csv")
METRIC_COL = "Absence duration for period in days"

TYPE_ORDER = [
    "Annual Leave",
    "WFH",
    "Medical + Sickness",
    "External & additional assignments",
    "Other (excl. WFH, Travel)",
]

ABSENCE_COLOR_MAP = {
    "Annual Leave": "#2563eb",
    "Medical + Sickness": "#dc2626",
    "Other (excl. WFH, Travel)": "#6b7280",
    "WFH": "#16a34a",
    "External & additional assignments": "#7c3aed",
}

CLEANED_FINAL_TYPES = {"Annual", "Medical", "Work from home", "External & additional assignments", "Others"}
CLEANED_TO_DASH = {
    "Annual": "Annual Leave",
    "Medical": "Medical + Sickness",
    "Work from home": "WFH",
    "External & additional assignments": "External & additional assignments",
    "Others": "Other (excl. WFH, Travel)",
}

DETAIL_COL_CANDIDATES = ["Absence description", "Description", "Reason", "Notes", "Comment", "Absence reason", "Absence notes"]

# Entitlement (for Annual Leave allowed vs taken)
ENTITLEMENT_COL = "Leave entitlement"
ENTITLEMENT_UNIT_COL = "Entitlement unit"
ENTITLEMENT_DAYS_COL = "leave_entitlement_days"

# BLIP
BLIP_COL_FIRST = "First Name"
BLIP_COL_LAST = "Last Name"
BLIP_COL_TEAM = "Team(s)"
BLIP_COL_ROLE = "Job Title"
BLIP_COL_TYPE = "Blip Type"
BLIP_XLSX_DEFAULT = os.path.join(_APP_DIR, "blip_cumulative.csv")
WFH_ASSUMED_HOURS = 8.0

# Group/ExCo: Team -> Organisation mapping
TEAMS_EG = {"HR", "UK BDM", "DE BDM", "Engineering", "Operations", "Investment", "Investments"}
TEAMS_AG = {"Agri"}
TEAMS_UG = {"Executive", "UG Business Support", "Group Finance", "Finance", "Property", "Group Legal", "Management"}

# ----------------------------
# Absence helpers (from app.py)
# ----------------------------
def _norm_for_match(s):
    s = "" if pd.isna(s) else str(s).lower().strip()
    s = re.sub(r"[\-_\/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _build_fuzzy_pattern(keywords):
    def kw_to_regex(kw):
        kw = _norm_for_match(kw)
        parts = [re.escape(p) for p in kw.split(" ") if p]
        return r"(?:%s)" % r"[\s\-_\/]*".join(parts) if parts else ""
    variants = [kw_to_regex(k) for k in keywords]
    variants = [v for v in variants if v]
    pat = r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(variants)
    return re.compile(pat, flags=re.IGNORECASE)

WFH_KEYWORDS = ["wfh", "work from home", "work-from-home", "remote", "home working", "telework", "tele-working"]
EXT_ASSIGN_KEYWORDS = [
    "travel", "business trip", "offsite", "onsite", "client visit", "site visit", "birthday", "birthday leave",
    "training", "event", "events", "conference", "workshop", "course", "training day", "visit", "assignment", "external"]
ANNUAL_KEYWORDS = ["annual", "holiday", "vacation", "pto"]
SICK_KEYWORDS = ["sick", "sickness", "medical", "ill", "flu", "gp", "doctor", "hospital", "injury", "migraine", "sick-note", "sick note", "unwell", "incapacity"]

WFH_PAT = _build_fuzzy_pattern(WFH_KEYWORDS)
EXT_PAT = _build_fuzzy_pattern(EXT_ASSIGN_KEYWORDS)
ANNUAL_PAT = _build_fuzzy_pattern(ANNUAL_KEYWORDS)
SICK_PAT = _build_fuzzy_pattern(SICK_KEYWORDS)

def map_absence_type(abs_type, details=""):
    t, d = _norm_for_match(abs_type), _norm_for_match(details)
    combined = f"{t} {d}".strip()
    if SICK_PAT.search(combined): return "Medical + Sickness"
    if EXT_PAT.search(combined): return "External & additional assignments"
    if WFH_PAT.search(combined): return "WFH"
    if ANNUAL_PAT.search(combined): return "Annual Leave"
    return "Other (excl. WFH, Travel)"

def parse_bright_hr_dt_two_pass(s):
    s = s.astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    dt = pd.to_datetime(s, errors="coerce", dayfirst=False)
    mask = dt.isna() & s.notna()
    if mask.any():
        dt.loc[mask] = pd.to_datetime(s[mask], errors="coerce", dayfirst=True)
    return dt

def infer_country_from_team(team_series):
    t = team_series.fillna("").astype(str).str.upper()
    out = pd.Series(["UK"] * len(t), index=t.index)
    out[t.str.contains(r"\bDE\b") | t.str.contains("GERM")] = "Germany"
    return out

def infer_organisation_from_team(team_series):
    """Map Team names -> Organisation (AG/EG/UG) for Group/ExCo view."""
    out = pd.Series(["Other"] * len(team_series), index=team_series.index)
    for i, t in team_series.items():
        val = str(t).strip() if pd.notna(t) else ""
        if val in TEAMS_EG: out.loc[i] = "EG"
        elif val in TEAMS_AG: out.loc[i] = "AG"
        elif val in TEAMS_UG: out.loc[i] = "UG"
    return out

def make_case_id(employee, start_dt, end_dt, raw_abs_type, team, country):
    payload = f"{employee}|{start_dt}|{end_dt}|{raw_abs_type}|{team}|{country}"
    return hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()

def expand_to_daily(df_in):
    if df_in.empty:
        return df_in.copy()
    rows = []
    for _, r in df_in.iterrows():
        s, e = r.get("start_dt", pd.NaT), r.get("end_dt", pd.NaT)
        if pd.isna(s): continue
        if pd.isna(e) or e < s: e = s
        for d in pd.date_range(s.normalize(), e.normalize(), freq="D"):
            rr = r.copy()
            rr["date"] = d
            rr["date_uk"] = d.strftime("%d/%m/%Y")
            rr["week_start"] = (d - pd.Timedelta(days=int(d.weekday()))).normalize()
            rr["iso_week"] = f"{rr['week_start'].isocalendar().year}-W{rr['week_start'].isocalendar().week:02d}"
            rr["is_weekday"] = int(d.weekday() < 5)
            rows.append(rr)
    if not rows:
        return df_in.iloc[0:0].copy()
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["week_start"] = pd.to_datetime(out["week_start"], errors="coerce")
    return out

def _process_absence_df(df_raw):
    df = df_raw.copy()
    df["start_dt"] = parse_bright_hr_dt_two_pass(df.get("Absence start date", ""))
    df["end_dt"] = parse_bright_hr_dt_two_pass(df.get("Absence end date", ""))
    df["start_date_uk"] = df["start_dt"].dt.strftime("%d/%m/%Y").fillna("")
    df["end_date_uk"] = df["end_dt"].dt.strftime("%d/%m/%Y").fillna("")
    df["month"] = df["start_dt"].dt.to_period("M").astype(str)
    if "Team names" not in df.columns:
        df["Team names"] = ""
    fn = df.get("First name", "").astype(str).str.strip()
    ln = df.get("Last name", "").astype(str).str.strip()
    df["employee"] = (fn + " " + ln).str.strip()
    if "Country" not in df.columns:
        df["Country"] = infer_country_from_team(df["Team names"])
    else:
        df["Country"] = df["Country"].fillna("").astype(str).str.strip().replace({"Unknown": "UK", "": "UK"}).fillna("UK")
    df[METRIC_COL] = pd.to_numeric(df.get(METRIC_COL), errors="coerce").fillna(0)
    detail_col = next((c for c in DETAIL_COL_CANDIDATES if c in df.columns), None)
    df["purpose"] = df[detail_col].astype(str).str.strip() if detail_col else ""
    raw_type = df.get("Absence type", "").fillna("").astype(str).str.strip()
    if raw_type.isin(list(CLEANED_FINAL_TYPES)).any():
        df["absence_category"] = raw_type.map(CLEANED_TO_DASH).fillna("Other (excl. WFH, Travel)")
    else:
        df["absence_category"] = df.apply(lambda r: map_absence_type(r.get("Absence type", ""), r.get(detail_col, "")), axis=1) if detail_col else df.get("Absence type", "").apply(lambda x: map_absence_type(x, ""))
    other_mask = df["absence_category"] == "Other (excl. WFH, Travel)"
    if other_mask.any():
        def _details(r):
            parts = [str(r.get("purpose", "") or "")]
            for c in DETAIL_COL_CANDIDATES:
                if c in r.index and c != (detail_col or ""):
                    parts.append(str(r.get(c, "") or ""))
            return " ".join(str(p).strip() for p in parts if p).strip()
        df.loc[other_mask, "absence_category"] = df.loc[other_mask].apply(lambda r: map_absence_type(r.get("Absence type", ""), _details(r)), axis=1)
    df["Organisation"] = infer_organisation_from_team(df["Team names"])
    df["case_id"] = df.apply(lambda r: make_case_id(r.get("employee", ""), r.get("start_dt", ""), r.get("end_dt", ""), str(r.get("Absence type", "")), str(r.get("Team names", "")), str(r.get("Country", ""))), axis=1)

    # Entitlement (days only) for Annual Leave allowed vs taken
    for src_col in [ENTITLEMENT_COL, "Leave allowance"]:
        if src_col in df.columns:
            df[src_col] = pd.to_numeric(df[src_col], errors="coerce")
    if ENTITLEMENT_UNIT_COL in df.columns:
        unit = df[ENTITLEMENT_UNIT_COL].fillna("").astype(str).str.strip().str.lower()
        unit_ok = unit.str.contains("day") | unit.eq("")
    else:
        unit_ok = pd.Series([True] * len(df), index=df.index)
    # Prefer Leave entitlement, fallback to Leave allowance
    if ENTITLEMENT_COL in df.columns:
        df[ENTITLEMENT_DAYS_COL] = df[ENTITLEMENT_COL].fillna(df.get("Leave allowance", pd.NA))
    elif "Leave allowance" in df.columns:
        df[ENTITLEMENT_DAYS_COL] = df["Leave allowance"]
    else:
        df[ENTITLEMENT_DAYS_COL] = pd.NA
    if ENTITLEMENT_UNIT_COL in df.columns:
        df.loc[~unit_ok, ENTITLEMENT_DAYS_COL] = pd.NA

    return df

@st.cache_data
def load_data(path):
    return _process_absence_df(pd.read_csv(path))

def load_data_from_upload(uploaded_file):
    return _process_absence_df(pd.read_csv(io.BytesIO(uploaded_file.read())))

@st.cache_data
def build_daily_for_months(path, months_tuple):
    df_all = load_data(path)
    df_sub = df_all[df_all["month"].isin(list(months_tuple))].copy()
    return expand_to_daily(df_sub)

def fmt_num(x):
    return f"{x:,.1f}"

def _fmt_days_label(v):
    """Show whole numbers unless fractional (e.g. 0.5)."""
    if v <= 0:
        return ""
    return f"{v:.1f}" if abs(v - round(v)) > 1e-6 else f"{int(round(v))}"

def fmt_hours_minutes(h):
    if pd.isna(h): return ""
    h = float(h)
    hours, minutes = int(h), int(round((h - int(h)) * 60))
    if minutes >= 60: hours += 1; minutes = 0
    return f"{hours}h {minutes}m"

def apply_global_filters(df_cases, df_daily, *, employee_q, keyword_q, depts, countries, cats, use_custom_date, date_range):
    cases, daily = df_cases.copy(), df_daily.copy()
    if "employee" in cases.columns: cases["employee"] = cases["employee"].fillna("").astype(str)
    if "purpose" in cases.columns: cases["purpose"] = cases["purpose"].fillna("").astype(str)
    if not daily.empty:
        for c in ["employee", "purpose", "Team names", "Country", "absence_category", "case_id"]:
            if c in daily.columns: daily[c] = daily[c].fillna("").astype(str)
    if employee_q.strip():
        q = employee_q.strip()
        cases = cases[cases["employee"].str.contains(q, case=False, na=False)]
        if not daily.empty: daily = daily[daily["employee"].str.contains(q, case=False, na=False)]
    if keyword_q.strip():
        q = keyword_q.strip()
        cases = cases[cases["purpose"].str.contains(q, case=False, na=False)]
        if not daily.empty: daily = daily[daily["purpose"].str.contains(q, case=False, na=False)]
    if depts:
        cases = cases[cases["Team names"].isin(depts)]
        if not daily.empty: daily = daily[daily["Team names"].isin(depts)]
    if countries:
        cases = cases[cases["Country"].isin(countries)]
        if not daily.empty: daily = daily[daily["Country"].isin(countries)]
    if cats:
        cases = cases[cases["absence_category"].isin(cats)]
        if not daily.empty: daily = daily[daily["absence_category"].isin(cats)]
    summary_date = "Month selection"
    if use_custom_date and date_range and not daily.empty and "date" in daily.columns:
        d1, d2 = date_range
        daily = daily[(daily["date"].dt.date >= d1) & (daily["date"].dt.date <= d2)]
        summary_date = f"Custom: {d1.strftime('%d/%m/%Y')} to {d2.strftime('%d/%m/%Y')}"
    if not daily.empty and "case_id" in daily.columns and "case_id" in cases.columns:
        case_ids = set(daily["case_id"].unique().tolist())
        cases = cases[cases["case_id"].isin(case_ids)]
    parts = []
    if employee_q.strip(): parts.append(f"Employee '{employee_q.strip()}'")
    if depts: parts.append(f"Dept={len(depts)}")
    if countries: parts.append(f"Country={len(countries)}")
    if cats: parts.append(f"Types={len(cats)}")
    parts.append(summary_date)
    return cases, daily, " | ".join(parts) if parts else "No filters"

def kpi_tile(title, value, subtitle=""):
    st.markdown(f'<div class="eg-kpi-tile"><div class="eg-kpi-label">{title}</div><div class="eg-kpi-value">{value}</div><div class="eg-kpi-sub">{subtitle}</div></div>', unsafe_allow_html=True)

def soft_card(title, body_html=""):
    st.markdown(f'<div class="eg-card soft-card" style="margin-bottom:0.5rem;"><div class="eg-section-title" style="margin-bottom:6px;">{title}</div>{body_html}</div>', unsafe_allow_html=True)

def _blip_clean_plot(fig, y_title=None, x_title=None, show_legend=None):
    layout_updates = {"plot_bgcolor": "white", "paper_bgcolor": "white", "margin": dict(l=20, r=20, t=50, b=20), "font": dict(size=12)}
    if show_legend is not None: layout_updates["showlegend"] = show_legend
    fig.update_layout(**layout_updates)
    fig.update_xaxes(showgrid=False, title=x_title)
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6", title=y_title)
    return fig

def _blip_safe_divide(n, d):
    return np.where(d > 0, n / d, np.nan)

def _datetime_to_hour_of_day(ts):
    if pd.isna(ts): return np.nan
    return ts.hour + ts.minute / 60.0 + ts.second / 3600.0

def _normalize_employee(s):
    return " ".join(str(s).strip().split()) if s else ""

def _blip_leave_daily_for_range(df_absence, d1, d2):
    if df_absence is None or df_absence.empty or "start_dt" not in df_absence.columns or "end_dt" not in df_absence.columns:
        return pd.DataFrame()
    d1_ts, d2_ts = pd.Timestamp(d1).normalize(), pd.Timestamp(d2).normalize()
    has_start = df_absence["start_dt"].notna() & (df_absence["start_dt"].dt.normalize() <= d2_ts)
    has_end_ok = df_absence["end_dt"].isna() | (df_absence["end_dt"].dt.normalize() >= d1_ts)
    overlap = df_absence[has_start & has_end_ok].copy()
    if overlap.empty: return pd.DataFrame()
    daily = expand_to_daily(overlap)
    if daily.empty or "date" not in daily.columns: return pd.DataFrame()
    daily["date_norm"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[(daily["date_norm"] >= d1_ts) & (daily["date_norm"] <= d2_ts)].copy()
    return daily.drop(columns=["date_norm"], errors="ignore")

# Import BLIP processing
def _blip_process_raw_df(df):
    from blip_preprocess import process_blip_df
    return process_blip_df(df, update_source_for_export=False)

@st.cache_data(show_spinner=False)
def _blip_load_data(path):
    path_lower = (path or "").strip().lower()
    if path_lower.endswith(".csv"):
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path, skiprows=1, engine="openpyxl")
    return _blip_process_raw_df(df)

def _blip_load_data_from_upload(uploaded_file):
    name = (getattr(uploaded_file, "name", "") or "").lower()
    raw = io.BytesIO(uploaded_file.read())
    if name.endswith(".csv"):
        df = pd.read_csv(raw)
    else:
        df = pd.read_excel(raw, skiprows=1, engine="openpyxl")
    return _blip_process_raw_df(df)

def _blip_merge_consecutive(segments):
    if not segments: return []
    out = [segments[0].copy()]
    for s in segments[1:]:
        last = out[-1]
        if s["kind"] == last["kind"] and s["start"] <= last["end"]:
            last["end"] = max(last["end"], s["end"])
        else:
            out.append(s.copy())
    return out

def _blip_build_authentic_day_segments(emp_df_day):
    d = emp_df_day[emp_df_day["clockin_dt"].notna() & emp_df_day["clockout_dt"].notna()].copy()
    if d.empty: return []
    intervals = []
    for _, r in d.iterrows():
        s, e = r["clockin_dt"], r["clockout_dt"]
        if pd.isna(s) or pd.isna(e) or e <= s: continue
        bt = str(r.get("blip_type_norm", "")).strip().lower()
        kind = "Break" if bt == "break" else ("Shift" if bt == "shift" else None)
        if kind is None: continue
        intervals.append({"start": s, "end": e, "kind": kind})
    if not intervals: return []
    cuts = sorted({x for it in intervals for x in (it["start"], it["end"])})
    if len(cuts) < 2: return []

    def covered_by(kind, a, b):
        for it in intervals:
            if it["kind"] != kind: continue
            if a >= it["start"] and b <= it["end"]: return True
        return False

    segs = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b <= a: continue
        if covered_by("Break", a, b): segs.append({"start": a, "end": b, "kind": "Break"})
        elif covered_by("Shift", a, b): segs.append({"start": a, "end": b, "kind": "Work"})
    return _blip_merge_consecutive(segs)

# ----------------------------
# Allowed vs Taken (Annual Leave, WFH)
# ----------------------------
def _weeks_in_period(months_tuple):
    """Number of week-starts in the selected month(s)."""
    if not months_tuple:
        return 0
    periods = [pd.Period(m, freq="M") for m in months_tuple]
    period_start = min(p.start_time for p in periods).normalize()
    period_end = max(p.end_time for p in periods).normalize()
    all_days = pd.date_range(period_start, period_end, freq="D")
    week_starts = (all_days - pd.to_timedelta(all_days.weekday, unit="D")).normalize()
    return int(pd.Series(week_starts).nunique())

def _get_entitlement_col(df):
    """Find entitlement column (flexible naming)."""
    for c in [ENTITLEMENT_DAYS_COL, ENTITLEMENT_COL, "Leave allowance", "Leave Entitlement"]:
        if c in df.columns:
            return c
    return None

def _allowed_taken_for_scope(df_all, daily_df, scope_employees, months_tuple):
    """
    Compute annual_allowed, annual_taken, wfh_allowed, wfh_taken for a scope.
    scope_employees: list of employee names in scope (or None for all).
    """
    daily = daily_df.copy()
    if scope_employees:
        scope_set = set(str(e).strip() for e in scope_employees if str(e).strip())
        daily["_emp_norm"] = daily["employee"].astype(str).str.strip()
        daily = daily[daily["_emp_norm"].isin(scope_set)].drop(columns=["_emp_norm"], errors="ignore")

    # Taken: count of daily rows per category (consistent with main app)
    taken = daily.groupby("absence_category").size().reindex(TYPE_ORDER).fillna(0)
    annual_taken = int(taken.get("Annual Leave", 0))
    wfh_taken = int(taken.get("WFH", 0))

    # Annual allowed: sum of entitlement for employees in scope (use full df, not filtered by month)
    ent_col = _get_entitlement_col(df_all)
    annual_allowed = 0.0
    if scope_employees and ent_col and "employee" in df_all.columns:
        scope_set = set(str(e).strip() for e in scope_employees if str(e).strip())
        df_all_norm = df_all.copy()
        df_all_norm["_emp_norm"] = df_all_norm["employee"].astype(str).str.strip()
        ent = df_all_norm[df_all_norm["_emp_norm"].isin(scope_set)][["_emp_norm", ent_col]].copy()
        ent[ent_col] = pd.to_numeric(ent[ent_col], errors="coerce")
        ent = ent.dropna(subset=[ent_col])
        if not ent.empty:
            annual_allowed = float(ent.groupby("_emp_norm")[ent_col].max().sum())

    # WFH allowed: weeks × full-time count. Full-time = entitlement > 0.
    full_time = []
    if scope_employees and ent_col:
        scope_set = set(str(e).strip() for e in scope_employees if str(e).strip())
        df_all_norm = df_all.copy()
        df_all_norm["_emp_norm"] = df_all_norm["employee"].astype(str).str.strip()
        ent = df_all_norm[df_all_norm["_emp_norm"].isin(scope_set)][["_emp_norm", ent_col]].copy()
        ent[ent_col] = pd.to_numeric(ent[ent_col], errors="coerce")
        ft = ent.groupby("_emp_norm")[ent_col].max()
        full_time = ft[ft > 0].index.tolist()
    weeks = _weeks_in_period(months_tuple)
    wfh_allowed = int(weeks * len(full_time))

    return {
        "annual_allowed": annual_allowed,
        "annual_taken": annual_taken,
        "wfh_allowed": wfh_allowed,
        "wfh_taken": wfh_taken,
        "taken_by_type": taken,
    }

def compute_annual_employee_balance(df_all, daily_filtered, weekday_only=True):
    """Annual Leave balance: Entitlement (from df_all) vs Used (from daily)."""
    ent_col = _get_entitlement_col(df_all)
    ent_by_emp = pd.DataFrame(columns=["employee", "Entitlement (days)"])
    if ent_col and "employee" in df_all.columns:
        df_norm = df_all.copy()
        df_norm["_emp"] = df_norm["employee"].astype(str).str.strip()
        ent = df_norm[["_emp", ent_col]].dropna()
        ent[ent_col] = pd.to_numeric(ent[ent_col], errors="coerce")
        ent = ent.dropna(subset=[ent_col])
        if not ent.empty:
            ent_by_emp = ent.groupby("_emp")[ent_col].max().reset_index().rename(columns={"_emp": "employee", ent_col: "Entitlement (days)"})
    used_by_emp = pd.DataFrame(columns=["employee", "Used (days)"])
    if not daily_filtered.empty and "employee" in daily_filtered.columns:
        base = daily_filtered[daily_filtered["absence_category"] == "Annual Leave"].copy()
        if weekday_only and "is_weekday" in base.columns:
            base = base[base["is_weekday"] == 1]
        used_by_emp = base.groupby("employee", as_index=False).size().rename(columns={"size": "Used (days)"})
        used_by_emp["employee"] = used_by_emp["employee"].astype(str).str.strip()
    if ent_by_emp.empty and used_by_emp.empty:
        return pd.DataFrame(columns=["employee", "Team names", "Country", "Entitlement (days)", "Used (days)", "Remaining (days)"]), pd.DataFrame(), {}
    if not ent_by_emp.empty and not used_by_emp.empty:
        balance = ent_by_emp.merge(used_by_emp, on="employee", how="outer")
    elif not ent_by_emp.empty:
        balance = ent_by_emp.copy()
        balance["Used (days)"] = 0
    else:
        balance = used_by_emp.copy()
        balance["Entitlement (days)"] = 0
    if all(c in df_all.columns for c in ["employee", "Team names", "Country"]):
        meta = df_all[["employee", "Team names", "Country"]].drop_duplicates("employee")
        meta["employee"] = meta["employee"].astype(str).str.strip()
        balance = balance.merge(meta, on="employee", how="left")
    else:
        balance["Team names"] = ""
        balance["Country"] = ""
    for c in ["Entitlement (days)", "Used (days)"]:
        if c not in balance.columns:
            balance[c] = 0
    balance["Used (days)"] = pd.to_numeric(balance["Used (days)"], errors="coerce").fillna(0)
    balance["Entitlement (days)"] = pd.to_numeric(balance["Entitlement (days)"], errors="coerce").fillna(0)
    balance["Remaining (days)"] = (balance["Entitlement (days)"] - balance["Used (days)"]).round(1)
    out_cols = ["employee", "Team names", "Country", "Entitlement (days)", "Used (days)", "Remaining (days)"]
    return balance[[c for c in out_cols if c in balance.columns]], pd.DataFrame(), {}

def _build_scope_leave_table(df_all, daily_df, scope_employees, months_tuple):
    """Build per-employee leave table for a scope (dept, country, org)."""
    if not scope_employees:
        return pd.DataFrame()
    weeks = _weeks_in_period(months_tuple)
    ent_col = _get_entitlement_col(df_all)
    scope_set = set(str(e).strip() for e in scope_employees if str(e).strip())
    daily = daily_df[daily_df["employee"].astype(str).str.strip().isin(scope_set)].copy()
    if daily.empty:
        return pd.DataFrame()

    # Per-employee taken
    emp_taken = daily.groupby(["employee", "absence_category"]).size().unstack(fill_value=0)
    for c in TYPE_ORDER:
        if c not in emp_taken.columns:
            emp_taken[c] = 0
    emp_taken = emp_taken.reset_index()
    emp_taken["employee"] = emp_taken["employee"].astype(str).str.strip()

    # Per-employee entitlement
    ent_by_emp = pd.DataFrame(columns=["employee", "entitlement"])
    if ent_col and "employee" in df_all.columns:
        df_norm = df_all.copy()
        df_norm["_emp"] = df_norm["employee"].astype(str).str.strip()
        ent = df_norm[df_norm["_emp"].isin(scope_set)][["_emp", ent_col]].copy()
        ent[ent_col] = pd.to_numeric(ent[ent_col], errors="coerce")
        ent_by_emp = ent.groupby("_emp")[ent_col].max().reset_index().rename(columns={"_emp": "employee", ent_col: "entitlement"})

    # Meta (Team, Country)
    meta = daily[["employee", "Team names", "Country"]].drop_duplicates("employee")
    meta["employee"] = meta["employee"].astype(str).str.strip()

    tbl = emp_taken.merge(meta, on="employee", how="left").rename(columns={"Team names": "Team", "Country": "Country"})
    tbl["WFH allowed (weeks)"] = weeks
    tbl["WFH taken (days)"] = tbl["WFH"].astype(int)
    ent_map = ent_by_emp.set_index("employee")["entitlement"] if not ent_by_emp.empty else pd.Series(dtype=float)
    tbl["Annual entitled (days)"] = tbl["employee"].map(ent_map).fillna(0).round(1)
    tbl["Annual taken (days)"] = tbl["Annual Leave"].astype(int)
    tbl["Annual remaining (days)"] = (tbl["Annual entitled (days)"] - tbl["Annual taken (days)"]).clip(lower=0).round(1)
    tbl["Sick taken (days)"] = tbl["Medical + Sickness"].astype(int)
    tbl["Ext. assignments taken (days)"] = tbl["External & additional assignments"].astype(int)
    tbl["Other taken (days)"] = tbl["Other (excl. WFH, Travel)"].astype(int)

    out_cols = ["employee", "Team", "Country", "WFH allowed (weeks)", "WFH taken (days)",
                "Annual entitled (days)", "Annual taken (days)", "Annual remaining (days)",
                "Sick taken (days)", "Ext. assignments taken (days)", "Other taken (days)"]
    return tbl[out_cols].sort_values("employee").rename(columns={"employee": "Employee"})

def _build_org_rollup_table(df_all, daily_df, months_tuple):
    """Build consolidated leave table: one row per Organisation (EG, AG, UG) with aggregated totals."""
    if daily_df.empty or "Organisation" not in daily_df.columns:
        return pd.DataFrame()
    ent_col = _get_entitlement_col(df_all)
    orgs = sorted([o for o in daily_df["Organisation"].dropna().unique() if str(o).strip() and str(o).strip() != "Other"])
    if not orgs:
        return pd.DataFrame()
    rows = []
    for org in orgs:
        org_daily = daily_df[daily_df["Organisation"].astype(str).str.strip() == org].copy()
        scope_emps = org_daily["employee"].dropna().unique().tolist()
        at = _allowed_taken_for_scope(df_all, daily_df, scope_emps, months_tuple)
        taken = at.get("taken_by_type")
        annual_ent = at.get("annual_allowed", 0) or 0
        annual_tkn = int(taken.get("Annual Leave", 0)) if taken is not None else 0
        wfh_allowed = at.get("wfh_allowed", 0) or 0
        rows.append({
            "Organisation": org,
            "Employees": len(scope_emps),
            "WFH allowed (days)": wfh_allowed,
            "WFH taken (days)": int(taken.get("WFH", 0)) if taken is not None else 0,
            "Annual entitled (days)": round(annual_ent, 1),
            "Annual taken (days)": annual_tkn,
            "Annual remaining (days)": round(max(0, annual_ent - annual_tkn), 1),
            "Sick taken (days)": int(taken.get("Medical + Sickness", 0)) if taken is not None else 0,
            "Ext. assignments taken (days)": int(taken.get("External & additional assignments", 0)) if taken is not None else 0,
            "Other taken (days)": int(taken.get("Other (excl. WFH, Travel)", 0)) if taken is not None else 0,
        })
    return pd.DataFrame(rows)

# ----------------------------
# Leave bar chart helpers (split: Allowance & Usage + Other leave)
# ----------------------------
def render_allowance_usage_chart(data_df, title, allowed_taken, height=540, yaxis_max=None):
    """Chart 1: Annual Leave & WFH — Allowed vs Taken (grouped bars)."""
    if data_df is None or data_df.empty or not allowed_taken:
        return
    at = allowed_taken
    taken_by_type = at.get("taken_by_type")
    if taken_by_type is None:
        return
    categories = ["Annual Leave", "WFH"]
    allowed_vals = [at.get("annual_allowed", 0) or 0, at.get("wfh_allowed", 0) or 0]
    taken_vals = [float(taken_by_type.get("Annual Leave", 0)), float(taken_by_type.get("WFH", 0))]
    fig = go.Figure(data=[
        go.Bar(name="Allowed", x=categories, y=allowed_vals, marker_color=["#93c5fd", "#86efac"],
               text=[_fmt_days_label(v) for v in allowed_vals], textposition="outside"),
        go.Bar(name="Taken", x=categories, y=taken_vals, marker_color=[ABSENCE_COLOR_MAP["Annual Leave"], ABSENCE_COLOR_MAP["WFH"]],
               text=[_fmt_days_label(v) for v in taken_vals], textposition="outside"),
    ])
    fig.update_layout(title=title, xaxis_title="", yaxis_title="Days", height=height, barmode="group", bargap=0.35,
                      paper_bgcolor="white", plot_bgcolor="white",
                      showlegend=True, legend=dict(orientation="h", yanchor="top", y=0.96, xanchor="right", x=1, bgcolor="rgba(255,255,255,0.8)"),
                      margin=dict(t=60, b=140, l=50, r=30),
                      font=dict(size=14),
                      xaxis=dict(tickfont=dict(size=14), automargin=True))
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6")
    if yaxis_max: fig.update_yaxes(range=[0, yaxis_max])
    st.plotly_chart(fig, use_container_width=True)

def render_other_leave_chart(data_df, title, allowed_taken, height=420):
    """Chart 2: Medical, Ext assignments, Other — days taken (simple bars)."""
    if data_df is None or data_df.empty or not allowed_taken:
        return
    taken_by_type = allowed_taken.get("taken_by_type")
    if taken_by_type is None:
        return
    categories = ["Medical + Sickness", "External & additional assignments", "Other (excl. WFH, Travel)"]
    taken_vals = [float(taken_by_type.get(c, 0) or 0) for c in categories]
    colors = [ABSENCE_COLOR_MAP.get(c, "#94a3b8") for c in categories]
    fig = go.Figure(data=[
        go.Bar(x=categories, y=taken_vals, marker_color=colors,
               text=[_fmt_days_label(v) for v in taken_vals], textposition="outside")
    ])
    fig.update_layout(title=title, xaxis_title="", yaxis_title="Days", height=height, showlegend=False, bargap=0.35,
                      paper_bgcolor="white", plot_bgcolor="white",
                      margin=dict(t=60, b=140, l=50, r=30),
                      font=dict(size=14),
                      xaxis=dict(tickfont=dict(size=13), tickangle=-15, automargin=True))
    y_max = max(1, max(taken_vals)) if taken_vals else 1
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6", range=[0, y_max])
    st.plotly_chart(fig, use_container_width=True)

def render_leave_bar_chart(data_df, title, height=1080, allowed_taken=None, yaxis_max=None):
    """
    Render split charts: (1) Allowance & Usage for Annual/WFH, (2) Other leave taken.
    """
    if data_df is None or data_df.empty:
        st.info("No data for the selected scope.")
        return
    title_suffix = title.split("—")[-1].strip() if "—" in title else ""
    if allowed_taken:
        c1, sep, c2 = st.columns([1, 0.03, 1])
        with c1:
            render_allowance_usage_chart(data_df, f"Allowance & usage — {title_suffix}", allowed_taken, height=540, yaxis_max=yaxis_max)
        with sep:
            st.markdown('<div class="eg-chart-separator"></div>', unsafe_allow_html=True)
        with c2:
            render_other_leave_chart(data_df, f"Other leave taken — {title_suffix}", allowed_taken, height=540)
    else:
        agg = data_df.groupby("absence_category")[METRIC_COL].sum().reindex(TYPE_ORDER).fillna(0)
        taken_vals = agg.values
        colors = [ABSENCE_COLOR_MAP.get(c, "#94a3b8") for c in TYPE_ORDER]
        fig = go.Figure(data=[
            go.Bar(x=TYPE_ORDER, y=taken_vals, marker_color=colors,
                   text=[_fmt_days_label(float(v)) if v > 0 else "" for v in taken_vals], textposition="outside")
        ])
        fig.update_layout(title=title, xaxis_title="Leave type", yaxis_title="Days", height=height,
                          showlegend=False, bargap=0.35, paper_bgcolor="white", plot_bgcolor="white",
                          margin=dict(t=50, b=120, l=50, r=30),
                          font=dict(size=14), xaxis=dict(tickfont=dict(size=13), tickangle=-20, automargin=True))
        fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6")
        if yaxis_max: fig.update_yaxes(range=[0, yaxis_max])
        st.plotly_chart(fig, use_container_width=True)

# ----------------------------
# Main app
# ----------------------------
st.markdown('<h1 class="eg-title">Leave & Time Utilisation</h1>', unsafe_allow_html=True)
st.markdown('<div class="eg-subtitle">Individual · Department · Country · Group · Time utilisation</div>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("Data & period")
    absence_uploaded = st.file_uploader("Upload Absence CSV", type=["csv"], key="absence_upload")
    csv_path = st.text_input("CSV path", value=CSV_PATH_DEFAULT, disabled=absence_uploaded is not None)
    try:
        df = load_data_from_upload(absence_uploaded) if absence_uploaded else load_data(csv_path)
    except Exception as e:
        st.error(f"Failed to load Absence CSV: {e}")
        st.stop()

    months_available = sorted([m for m in df["month"].dropna().unique().tolist() if m != "NaT"])
    if not months_available:
        st.error("No valid months found.")
        st.stop()

    preferred_m1 = "2025-11"
    default_m1 = months_available.index(preferred_m1) if preferred_m1 in months_available else max(len(months_available) - 2, 0)
    month_1 = st.selectbox("Month", options=months_available, index=default_m1)

    with st.expander("Compare with another month", expanded=False):
        add_second = st.checkbox("Add comparison month", value=False, key="add_second")
        month_2 = None
        if add_second and [m for m in months_available if m != month_1]:
            month_2 = st.selectbox("Comparison month", options=[m for m in months_available if m != month_1], key="month_2")

    months_in_scope = [month_1] + ([month_2] if month_2 else [])
    months_tuple = tuple(months_in_scope)

    if absence_uploaded:
        df_sub = df[df["month"].isin(list(months_tuple))].copy()
        daily_scope = expand_to_daily(df_sub)
    else:
        daily_scope = build_daily_for_months(csv_path, months_tuple)

    st.markdown("---")
    st.subheader("Refine view")
    with st.expander("Filters", expanded=False):
        employee_q = st.text_input("Employee search", value="", key="emp_q")
        keyword_q = st.text_input("Keyword in purpose", value="", key="kw_q")
        dept_options = sorted([d for d in df["Team names"].fillna("").astype(str).unique().tolist() if d.strip()])
        selected_depts = st.multiselect("Departments", options=dept_options, default=[], key="depts")
        country_options = sorted([c for c in df["Country"].fillna("").astype(str).unique().tolist() if c.strip()])
        selected_countries = st.multiselect("Countries", options=country_options, default=[], key="countries")
        selected_cats = st.multiselect("Absence types", options=TYPE_ORDER, default=[], key="cats")
        use_custom_date = st.checkbox("Use custom date range", value=False, key="use_custom_date")
        date_range = None
        if use_custom_date and not daily_scope.empty and "date" in daily_scope.columns:
            min_dt = pd.to_datetime(daily_scope["date"], errors="coerce").min()
            max_dt = pd.to_datetime(daily_scope["date"], errors="coerce").max()
            if pd.notna(min_dt) and pd.notna(max_dt):
                date_range = st.date_input("Custom date range", value=(min_dt.date(), max_dt.date()), key="date_range")

    df_scope = df[df["month"].isin(months_in_scope)].copy()
    if selected_cats:
        df_scope = df_scope[df_scope["absence_category"].isin(selected_cats)]
    if selected_cats and not daily_scope.empty:
        daily_scope = daily_scope[daily_scope["absence_category"].isin(selected_cats)].copy()

    df_cases_filt, daily_filt, filter_summary = apply_global_filters(
        df_cases=df_scope, df_daily=daily_scope,
        employee_q=employee_q, keyword_q=keyword_q,
        depts=selected_depts, countries=selected_countries, cats=selected_cats,
        use_custom_date=use_custom_date, date_range=date_range
    )
    _fs = str(filter_summary).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(f'<p class="eg-breadcrumb">Showing: {_fs}</p>', unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("BLIP Utilisation", expanded=False):
        blip_uploaded = st.file_uploader("Upload BLIP export", type=["xlsx", "xls", "csv"], key="blip_upload")
        blip_xlsx_path = st.text_input("Or BLIP file path", value=BLIP_XLSX_DEFAULT, disabled=blip_uploaded is not None, key="blip_path")
        if st.button("Hard reload BLIP", key="blip_reload"):
            _blip_load_data.clear()
            st.rerun()
        expected_daily_hours = st.number_input("Expected daily hours", 0.0, 24.0, 8.0, 0.5, key="blip_expected_hours")
        short_shift_hours = st.number_input("Short shift threshold (h)", 0.0, 24.0, 2.0, 0.5, key="blip_short")
        long_shift_hours = st.number_input("Long shift threshold (h)", 0.0, 24.0, 10.0, 0.5, key="blip_long")

        df_blip = None
        f_blip = None
        f_shift = None
        if blip_uploaded or (blip_xlsx_path and str(blip_xlsx_path).strip()):
            try:
                df_blip = _blip_load_data_from_upload(blip_uploaded) if blip_uploaded else _blip_load_data(blip_xlsx_path)
                if df_blip["date"].notna().sum() == 0:
                    st.warning("No valid dates in BLIP.")
                    df_blip, f_blip, f_shift = None, None, None
                else:
                    min_dt_blip, max_dt_blip = df_blip["date"].min(), df_blip["date"].max()
                    d1_blip, d2_blip = st.date_input("Date range", value=(min_dt_blip.date(), max_dt_blip.date()), key="blip_daterange")
                    f_blip = df_blip[(df_blip["date"].dt.date >= d1_blip) & (df_blip["date"].dt.date <= d2_blip)].copy()
                    f_shift = f_blip[f_blip["blip_type_norm"].eq("shift")].copy()
                    f_shift = f_shift[f_shift["date"].dt.dayofweek < 5].copy()
            except Exception as e:
                st.warning(f"Failed to load BLIP: {e}")
                df_blip, f_blip, f_shift = None, None, None

# ----- Compute leave firmwide (for Summary and Leave tab) -----
employee_balance, _, _ = compute_annual_employee_balance(df, daily_filt, weekday_only=True)
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
        .str.strip()
        .drop_duplicates()
        .tolist()
    )
    full_time_emps = [e for e in full_time_emps if e]
    full_time = int((eb["Entitlement (days)"] > 0).sum())
    external_consultants = int((eb["Entitlement (days)"] == 0).sum())
periods = [pd.Period(m, freq="M") for m in months_in_scope]
period_start = min(p.start_time for p in periods).normalize()
period_end = max(p.end_time for p in periods).normalize()
all_days = pd.date_range(period_start, period_end, freq="D")
week_starts = (all_days - pd.to_timedelta(all_days.weekday, unit="D")).normalize()
weeks_in_period = int(pd.Series(week_starts).nunique())
firm_daily = daily_scope.copy()
if full_time_emps:
    firm_daily = firm_daily[firm_daily["employee"].astype(str).str.strip().isin(full_time_emps)].copy()
taken_fw = firm_daily.groupby("absence_category").size().to_dict() if not firm_daily.empty and "absence_category" in firm_daily.columns else {}
wfh_taken_fw = int(taken_fw.get("WFH", 0) or 0)
annual_taken_fw = int(taken_fw.get("Annual Leave", 0) or 0)
sick_taken_fw = int(taken_fw.get("Medical + Sickness", 0) or 0)
ext_assign_taken_fw = int(taken_fw.get("External & additional assignments", 0) or 0)
other_taken_fw = int(taken_fw.get("Other (excl. WFH, Travel)", 0) or 0)
annual_entitled_fw = 0.0
annual_remaining_fw = 0.0
if employee_balance is not None and not employee_balance.empty:
    balance_ft = employee_balance.copy()
    balance_ft["Entitlement (days)"] = pd.to_numeric(balance_ft["Entitlement (days)"], errors="coerce").fillna(0)
    balance_ft = balance_ft[balance_ft["Entitlement (days)"] > 0].copy()
    balance_ft["Remaining (days)"] = pd.to_numeric(balance_ft["Remaining (days)"], errors="coerce").fillna(0)
    if full_time_emps:
        balance_ft = balance_ft[balance_ft["employee"].astype(str).str.strip().isin(full_time_emps)].copy()
    annual_entitled_fw = float(balance_ft["Entitlement (days)"].sum())
    annual_remaining_fw = float(balance_ft["Remaining (days)"].sum())
wfh_allowed_fw = int(weeks_in_period * len(full_time_emps))
wfh_pct_fw = 0.0 if wfh_allowed_fw == 0 else min(100.0, (wfh_taken_fw / wfh_allowed_fw) * 100.0)

def _fmt_int(x):
    try: return f"{int(x):,}"
    except Exception: return str(x)
def _fmt_days(x):
    try: return f"{float(x):,.1f}d"
    except Exception: return str(x)

# Main tabs
main_leave, main_time = st.tabs(["Leave Management", "Time Utilisation"])

# =========================================================
# LEAVE MANAGEMENT: Summary + Individual, Department, Country, Group / ExCo
# =========================================================
with main_leave:
    tab_summary, tab_individual, tab_department, tab_country, tab_group = st.tabs(["Summary", "Individual", "Department", "Country", "Group / ExCo"])

    with tab_summary:
        st.markdown('<h3 class="eg-section-title">Firmwide KPIs</h3>', unsafe_allow_html=True)
        st.caption("Quick snapshot for the selected period and filters (full-time employees only).")
        h1, h2, h3, h4 = st.columns([1.2, 1.2, 1.2, 1.2])
        with h1: kpi_tile("Full-time employees", _fmt_int(full_time), "Entitlement > 0 days")
        with h2: kpi_tile("External consultants", _fmt_int(external_consultants), "Entitlement = 0 days")
        with h3: kpi_tile("Absence days taken", _fmt_int(len(firm_daily)) if not firm_daily.empty else "0", "Daily rows in scope")
        with h4: kpi_tile("Weeks in period", _fmt_int(weeks_in_period), f"{period_start.strftime('%d/%m/%Y')} to {period_end.strftime('%d/%m/%Y')}")
        st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
        row_a, row_b = st.columns([1.35, 1.65])
        with row_a:
            progress_html = f"""<div style="display:flex; gap:14px; align-items:flex-end; margin-bottom:10px;">
<div style="flex:1;"><div style="font-size:0.85rem; color:#6b7280; font-weight:600;">WFH utilisation</div><div style="font-size:1.6rem; font-weight:900; color:#111827;">{wfh_pct_fw:.0f}%</div></div>
<div style="text-align:right;"><div style="font-size:0.85rem; color:#6b7280;">Allowed</div><div style="font-size:1.1rem; font-weight:800;">{_fmt_int(wfh_allowed_fw)}</div>
<div style="font-size:0.85rem; color:#6b7280; margin-top:6px;">Taken</div><div style="font-size:1.1rem; font-weight:800;">{_fmt_int(wfh_taken_fw)}</div></div></div>"""
            soft_card("Work-from-home", progress_html)
            st.progress(wfh_pct_fw / 100.0)
        with row_b:
            body = f"""<div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px;">
<div style="border:1px solid #eef2f7; border-radius:var(--eg-radius); padding:10px 12px; background:#fbfbfb;"><div style="font-size:0.8rem; color:var(--eg-muted); font-weight:600;">Annual entitled</div><div style="font-size:1.25rem; font-weight:900;">{_fmt_days(annual_entitled_fw)}</div></div>
<div style="border:1px solid #eef2f7; border-radius:var(--eg-radius); padding:10px 12px; background:#fbfbfb;"><div style="font-size:0.8rem; color:var(--eg-muted); font-weight:600;">Annual taken</div><div style="font-size:1.25rem; font-weight:900;">{_fmt_int(annual_taken_fw)}d</div></div>
<div style="border:1px solid #eef2f7; border-radius:var(--eg-radius); padding:10px 12px; background:#fbfbfb;"><div style="font-size:0.8rem; color:var(--eg-muted); font-weight:600;">Annual remaining</div><div style="font-size:1.25rem; font-weight:900; color:var(--eg-accent);">{_fmt_days(annual_remaining_fw)}</div></div></div>
<div style="margin-top:10px; font-size:0.85rem; color:#6b7280;">Remaining from employee balances (full-time only).</div>"""
            soft_card("Annual leave", body)
        st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
        left_card, right_card = st.columns([1.05, 1.95])
        with left_card:
            body = f"""<div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px;">
<div style="border:1px solid #eef2f7; border-radius:var(--eg-radius); padding:10px 12px; background:#fbfbfb;"><div style="font-size:0.8rem; color:var(--eg-muted); font-weight:600;">Sick</div><div style="font-size:1.25rem; font-weight:900;">{_fmt_int(sick_taken_fw)}d</div></div>
<div style="border:1px solid #eef2f7; border-radius:var(--eg-radius); padding:10px 12px; background:#fbfbfb;"><div style="font-size:0.8rem; color:var(--eg-muted); font-weight:600;">Ext. assignments</div><div style="font-size:1.25rem; font-weight:900;">{_fmt_int(ext_assign_taken_fw)}d</div></div>
<div style="border:1px solid #eef2f7; border-radius:var(--eg-radius); padding:10px 12px; background:#fbfbfb;"><div style="font-size:0.8rem; color:var(--eg-muted); font-weight:600;">Other</div><div style="font-size:1.25rem; font-weight:900;">{_fmt_int(other_taken_fw)}d</div></div></div>"""
            soft_card("Other leave taken", body)

    with tab_individual:
        st.markdown('<h3 class="eg-section-title">Individual</h3>', unsafe_allow_html=True)
        emp_list = sorted([e for e in daily_filt["employee"].dropna().unique() if str(e).strip()]) if not daily_filt.empty else []
        if not emp_list:
            st.info("No employees in the selected scope.")
        else:
            # Build display labels "Name (Team)" for easier identification
            emp_display = []
            for e in emp_list:
                row = daily_filt[daily_filt["employee"].astype(str).str.strip() == str(e).strip()]
                team = (row["Team names"].iloc[0] if not row.empty and "Team names" in row.columns and pd.notna(row["Team names"].iloc[0]) and str(row["Team names"].iloc[0]).strip() else "") or ""
                label = f"{e} ({team})" if team else str(e)
                emp_display.append(label)
            display_to_emp = dict(zip(emp_display, emp_list))
            sel_display = st.selectbox("Select employee", options=emp_display, index=0, key="ind_emp")
            sel_emp = display_to_emp.get(sel_display, emp_list[0])
            emp_data = daily_filt[daily_filt["employee"].astype(str).str.strip() == str(sel_emp).strip()].copy()
            at = _allowed_taken_for_scope(df, daily_filt, [sel_emp], months_tuple)
            # Option B: Scope KPIs
            taken_i = at.get("taken_by_type")
            def _taken_val(key):
                t = taken_i
                if t is None: return 0
                return int(t.get(key, 0)) if hasattr(t, "get") else 0
            i1, i2, i3, i4 = st.columns(4)
            with i1: kpi_tile("Annual allowed", _fmt_days(at.get("annual_allowed", 0) or 0), "Entitlement")
            with i2: kpi_tile("Annual taken", _fmt_int(_taken_val("Annual Leave")), "Days")
            with i3: kpi_tile("WFH allowed", _fmt_int(at.get("wfh_allowed", 0) or 0), "Days")
            with i4: kpi_tile("WFH taken", _fmt_int(_taken_val("WFH")), "Days")
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            render_leave_bar_chart(emp_data, f"Leave by type — {sel_emp} ({month_1}" + (f", {month_2}" if month_2 else "") + ")", allowed_taken=at, yaxis_max=33)
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            # Employee details table
            st.markdown('<h4 class="eg-section-title">Leave details — ' + str(sel_emp) + '</h4>', unsafe_allow_html=True)
            taken = at.get("taken_by_type")
            weeks = _weeks_in_period(months_tuple)
            emp_meta = emp_data[["employee", "Team names", "Country"]].drop_duplicates().iloc[0].to_dict() if not emp_data.empty else {}
            annual_ent = at.get("annual_allowed", 0) or 0
            annual_tkn = int(taken.get("Annual Leave", 0)) if taken is not None else 0
            tbl = pd.DataFrame([{
                "Employee": sel_emp,
                "Team": emp_meta.get("Team names", ""),
                "Country": emp_meta.get("Country", ""),
                "WFH allowed (weeks)": weeks,
                "WFH taken (days)": int(taken.get("WFH", 0)) if taken is not None else 0,
                "Annual entitled (days)": round(annual_ent, 1),
                "Annual taken (days)": annual_tkn,
                "Annual remaining (days)": round(max(0, annual_ent - annual_tkn), 1),
                "Sick taken (days)": int(taken.get("Medical + Sickness", 0)) if taken is not None else 0,
                "Ext. assignments taken (days)": int(taken.get("External & additional assignments", 0)) if taken is not None else 0,
                "Other taken (days)": int(taken.get("Other (excl. WFH, Travel)", 0)) if taken is not None else 0,
            }])
            st.dataframe(tbl, use_container_width=True, hide_index=True)
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            # Daily investigation (expander)
            st.markdown('<h4 class="eg-section-title">Daily investigation</h4>', unsafe_allow_html=True)
            with st.expander("Open daily evidence log", expanded=False):
                ev_keyword_q = st.text_input("Keyword in purpose/description", value="", key="ind_ev_kw")
                ev_cats = st.multiselect("Absence types", options=TYPE_ORDER, default=[], key="ind_ev_cats")
                ev_use_custom_date = st.checkbox("Use custom date range", value=False, key="ind_ev_custom_date")
                ev_date_range = None
                if ev_use_custom_date and not emp_data.empty and "date" in emp_data.columns:
                    min_dt = pd.to_datetime(emp_data["date"], errors="coerce").min()
                    max_dt = pd.to_datetime(emp_data["date"], errors="coerce").max()
                    if pd.notna(min_dt) and pd.notna(max_dt):
                        ev_date_range = st.date_input("Date range", value=(min_dt.date(), max_dt.date()), key="ind_ev_dr")
                ev_daily = emp_data.copy()
                if ev_keyword_q.strip():
                    ev_daily = ev_daily[ev_daily["purpose"].fillna("").astype(str).str.contains(ev_keyword_q.strip(), case=False, na=False)]
                if ev_cats:
                    ev_daily = ev_daily[ev_daily["absence_category"].isin(ev_cats)]
                if ev_use_custom_date and ev_date_range and not ev_daily.empty and "date" in ev_daily.columns:
                    d1, d2 = (ev_date_range[0], ev_date_range[1]) if isinstance(ev_date_range, tuple) else (ev_date_range, ev_date_range)
                    ev_daily = ev_daily[(ev_daily["date"].dt.date >= d1) & (ev_daily["date"].dt.date <= d2)]
                if ev_daily.empty:
                    st.info("No daily records match the filters.")
                else:
                    cols = ["date_uk", "employee", "Team names", "Country", "absence_category", METRIC_COL, "purpose", "start_date_uk", "end_date_uk"]
                    cols = [c for c in cols if c in ev_daily.columns]
                    ev_daily_sorted = ev_daily.sort_values(["date", "absence_category"])
                    st.dataframe(ev_daily_sorted[cols], use_container_width=True, hide_index=True)

    with tab_department:
        st.markdown('<h3 class="eg-section-title">Department</h3>', unsafe_allow_html=True)
        dept_list = sorted([d for d in daily_filt["Team names"].dropna().unique() if str(d).strip()]) if not daily_filt.empty else []
        if not dept_list:
            st.info("No departments in the selected scope.")
        else:
            sel_dept = st.selectbox("Select department", options=dept_list, index=0, key="dept_sel")
            dept_data = daily_filt[daily_filt["Team names"].astype(str).str.strip() == str(sel_dept).strip()].copy()
            scope_emps = dept_data["employee"].dropna().unique().tolist() if not dept_data.empty else []
            at = _allowed_taken_for_scope(df, daily_filt, scope_emps, months_tuple)
            # Option B: Scope KPIs
            d1, d2, d3, d4, d5 = st.columns(5)
            taken_d = at.get("taken_by_type")
            taken = taken_d if taken_d is not None and hasattr(taken_d, "get") else {}
            with d1: kpi_tile("Employees", _fmt_int(len(scope_emps)), sel_dept)
            with d2: kpi_tile("Annual allowed", _fmt_days(at.get("annual_allowed", 0) or 0), "Entitlement")
            with d3: kpi_tile("Annual taken", _fmt_int(int(taken.get("Annual Leave", 0))), "Days")
            with d4: kpi_tile("WFH allowed", _fmt_int(at.get("wfh_allowed", 0) or 0), "Days")
            with d5: kpi_tile("WFH taken", _fmt_int(int(taken.get("WFH", 0))), "Days")
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            render_leave_bar_chart(dept_data, f"Leave by type — {sel_dept} ({month_1}" + (f", {month_2}" if month_2 else "") + ")", allowed_taken=at)
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            # Department leave table (per employee)
            st.markdown('<h4 class="eg-section-title">Leave details — ' + str(sel_dept) + '</h4>', unsafe_allow_html=True)
            dept_tbl = _build_scope_leave_table(df, daily_filt, scope_emps, months_tuple)
            if dept_tbl.empty:
                st.info("No employee data for this department.")
            else:
                st.dataframe(dept_tbl, use_container_width=True, hide_index=True)

    with tab_country:
        st.markdown('<h3 class="eg-section-title">Country</h3>', unsafe_allow_html=True)
        country_list = sorted([c for c in daily_filt["Country"].dropna().unique() if str(c).strip()]) if not daily_filt.empty else []
        if not country_list:
            st.info("No countries in the selected scope.")
        else:
            if "country_sel" not in st.session_state or st.session_state.country_sel not in country_list:
                st.session_state.country_sel = country_list[0]
            sel_country = st.session_state.country_sel
            cols_per_row = 5
            for start in range(0, len(country_list), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for i, c in enumerate(country_list[start : start + cols_per_row]):
                    with row_cols[i]:
                        if st.button(c, key=f"country_btn_{c}", use_container_width=True, type="primary" if c == sel_country else "secondary"):
                            st.session_state.country_sel = c
                            st.rerun()
            st.markdown('<p class="eg-breadcrumb">Leave Management → Country → ' + str(sel_country).replace("<", "&lt;").replace(">", "&gt;") + '</p>', unsafe_allow_html=True)
            country_data = daily_filt[daily_filt["Country"].astype(str).str.strip() == str(sel_country).strip()].copy()
            scope_emps = country_data["employee"].dropna().unique().tolist() if not country_data.empty else []
            at = _allowed_taken_for_scope(df, daily_filt, scope_emps, months_tuple)
            # Option B: Scope KPIs
            c1, c2, c3, c4, c5 = st.columns(5)
            taken_c = at.get("taken_by_type")
            taken = taken_c if taken_c is not None and hasattr(taken_c, "get") else {}
            with c1: kpi_tile("Employees", _fmt_int(len(scope_emps)), sel_country)
            with c2: kpi_tile("Annual allowed", _fmt_days(at.get("annual_allowed", 0) or 0), "Entitlement")
            with c3: kpi_tile("Annual taken", _fmt_int(int(taken.get("Annual Leave", 0))), "Days")
            with c4: kpi_tile("WFH allowed", _fmt_int(at.get("wfh_allowed", 0) or 0), "Days")
            with c5: kpi_tile("WFH taken", _fmt_int(int(taken.get("WFH", 0))), "Days")
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            render_leave_bar_chart(country_data, f"Leave by type — {sel_country} ({month_1}" + (f", {month_2}" if month_2 else "") + ")", allowed_taken=at)
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            st.markdown('<h4 class="eg-section-title">Leave details — ' + str(sel_country).replace("<", "&lt;").replace(">", "&gt;") + '</h4>', unsafe_allow_html=True)
            country_tbl = _build_scope_leave_table(df, daily_filt, scope_emps, months_tuple)
            if country_tbl.empty:
                st.info("No employee data for this country.")
            else:
                st.dataframe(country_tbl, use_container_width=True, hide_index=True)

    with tab_group:
        st.markdown('<h3 class="eg-section-title">Group / ExCo</h3>', unsafe_allow_html=True)
        org_list = sorted([o for o in daily_filt["Organisation"].dropna().unique() if str(o).strip()]) if not daily_filt.empty and "Organisation" in daily_filt.columns else []
        if not org_list:
            st.info("No organisations in the selected scope.")
        else:
            if "org_sel" not in st.session_state or st.session_state.org_sel not in org_list:
                st.session_state.org_sel = org_list[0]
            sel_org = st.session_state.org_sel
            cols_per_row = 5
            for start in range(0, len(org_list), cols_per_row):
                row_cols = st.columns(cols_per_row)
                for i, o in enumerate(org_list[start : start + cols_per_row]):
                    with row_cols[i]:
                        if st.button(o, key=f"org_btn_{o}", use_container_width=True, type="primary" if o == sel_org else "secondary"):
                            st.session_state.org_sel = o
                            st.rerun()
            st.markdown('<p class="eg-breadcrumb">Leave Management → Group / ExCo → ' + str(sel_org).replace("<", "&lt;").replace(">", "&gt;") + '</p>', unsafe_allow_html=True)
            org_data = daily_filt[daily_filt["Organisation"].astype(str).str.strip() == str(sel_org).strip()].copy()
            scope_emps = org_data["employee"].dropna().unique().tolist() if not org_data.empty else []
            at = _allowed_taken_for_scope(df, daily_filt, scope_emps, months_tuple)
            # Option B: Scope KPIs
            o1, o2, o3, o4, o5 = st.columns(5)
            taken_o = at.get("taken_by_type")
            taken = taken_o if taken_o is not None and hasattr(taken_o, "get") else {}
            with o1: kpi_tile("Employees", _fmt_int(len(scope_emps)), sel_org)
            with o2: kpi_tile("Annual allowed", _fmt_days(at.get("annual_allowed", 0) or 0), "Entitlement")
            with o3: kpi_tile("Annual taken", _fmt_int(int(taken.get("Annual Leave", 0))), "Days")
            with o4: kpi_tile("WFH allowed", _fmt_int(at.get("wfh_allowed", 0) or 0), "Days")
            with o5: kpi_tile("WFH taken", _fmt_int(int(taken.get("WFH", 0))), "Days")
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            render_leave_bar_chart(org_data, f"Leave by type — {sel_org} ({month_1}" + (f", {month_2}" if month_2 else "") + ")", allowed_taken=at)
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            # Per-employee table for selected org
            st.markdown('<h4 class="eg-section-title">Leave details — ' + str(sel_org) + '</h4>', unsafe_allow_html=True)
            org_tbl = _build_scope_leave_table(df, daily_filt, scope_emps, months_tuple)
            if org_tbl.empty:
                st.info("No employee data for this organisation.")
            else:
                st.dataframe(org_tbl, use_container_width=True, hide_index=True)
            st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
            # Consolidated table: EG, AG, UG rollup (at the end)
            st.markdown('<h4 class="eg-section-title">Consolidated leave — EG, AG, UG</h4>', unsafe_allow_html=True)
            org_rollup = _build_org_rollup_table(df, daily_filt, months_tuple)
            if org_rollup.empty:
                st.info("No consolidated data for organisations.")
            else:
                st.dataframe(org_rollup, use_container_width=True, hide_index=True)

# =========================================================
# TIME TAB: BLIP Utilisation (unchanged from main app)
# =========================================================
with main_time:
    st.caption("Data and date range are set in the sidebar (BLIP Utilisation section).")
    if f_shift is None or (hasattr(f_shift, "empty") and f_shift.empty):
        st.info("Configure BLIP data source in the sidebar (upload an Excel file or enter a path).")
    else:
        entries_all = len(f_blip)
        entries_shift = len(f_shift)
        employees_blip = f_shift["employee"].nunique()
        missing_clockouts = (~f_shift["has_clockout"]).sum()
        worked_total = f_shift["worked_hours"].sum(skipna=True)
        duration_total = f_shift["duration_hours"].sum(skipna=True)
        break_total = f_shift["break_hours"].sum(skipna=True)
        all_dates_kpi = pd.date_range(start=pd.Timestamp(d1_blip), end=pd.Timestamp(d2_blip), freq="D")
        weekday_dates_kpi = [pd.Timestamp(d).date() for d in all_dates_kpi if getattr(d, "dayofweek", d.weekday()) < 5]
        weekday_set = {(d.year, d.month, d.day) for d in weekday_dates_kpi}
        person_wfh_days = 0
        if not f_shift.empty and "employee" in f_shift.columns:
            shift_dates_norm = pd.to_datetime(f_shift["date"]).dt.normalize()
            for emp in f_shift["employee"].dropna().unique():
                emp = str(emp).strip()
                if not emp: continue
                mask = (f_shift["employee"].astype(str).str.strip() == emp)
                emp_dates_raw = shift_dates_norm.loc[mask].dt.date.dropna().unique()
                emp_dates = set((d.year, d.month, d.day) for d in emp_dates_raw)
                person_wfh_days += len(weekday_set - emp_dates)
        total_worked_incl_wfh = worked_total + (person_wfh_days * WFH_ASSUMED_HOURS)
        total_shifts_incl_wfh = len(f_shift) + person_wfh_days
        avg_worked_shift = total_worked_incl_wfh / total_shifts_incl_wfh if total_shifts_incl_wfh > 0 else 0.0

        k1, k2, k3, k4, k5 = st.columns(5)
        with k1: kpi_tile("Entries (all)", f"{entries_all:,}", "All BLIP rows")
        with k2: kpi_tile("Shift entries", f"{int(total_shifts_incl_wfh):,}", "Incl. WFH as shifts")
        with k3: kpi_tile("Employees", f"{employees_blip:,}", "In selected range")
        with k4: kpi_tile("Worked hours (incl. WFH)", fmt_hours_minutes(total_worked_incl_wfh), "Weekdays only")
        with k5: kpi_tile("Avg worked / shift", fmt_hours_minutes(avg_worked_shift), "Incl. WFH as shifts")
        st.markdown('<div class="eg-spacer-md"></div>', unsafe_allow_html=True)
        shift_totals_body = f"""<div style="font-size:0.9rem;">Total Duration = <b>{fmt_hours_minutes(duration_total)}</b> | Break = <b>{fmt_hours_minutes(break_total)}</b> | Worked = <b>{fmt_hours_minutes(worked_total)}</b></div>"""
        soft_card("Shift totals", shift_totals_body)
        st.caption("Recorded totals above. KPIs include WFH: weekdays with no shift = 8 hrs each. Daily utilisation below.")
        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Daily Utilisation (incl. WFH, weekdays only)</h3>', unsafe_allow_html=True)
        all_dates_daily = pd.date_range(start=pd.Timestamp(d1_blip), end=pd.Timestamp(d2_blip), freq="D")
        weekday_dates = [pd.Timestamp(d).normalize() for d in all_dates_daily if getattr(d, "dayofweek", d.weekday()) < 5]
        full_daily = pd.DataFrame({"date": weekday_dates})
        notes_col = f_shift.get("Notes", pd.Series(index=f_shift.index, dtype=object)).fillna("").astype(str).str.upper()
        f_shift["_is_wfh_note"] = notes_col.str.contains("WFH", na=False)
        wfh_dates_set = set()
        if f_shift["_is_wfh_note"].any():
            wfh_date_norm = pd.to_datetime(f_shift.loc[f_shift["_is_wfh_note"], "date"]).dt.normalize()
            if hasattr(wfh_date_norm.dtype, "tz") and wfh_date_norm.dtype.tz is not None:
                wfh_date_norm = wfh_date_norm.dt.tz_localize(None)
            wfh_dates_set = set(wfh_date_norm.dropna().unique())
        daily_agg = f_shift.groupby("date", as_index=False).agg(WorkedHours=("worked_hours", "sum"), Employees=("employee", "nunique"))
        daily_agg["date"] = pd.to_datetime(daily_agg["date"]).dt.normalize()
        daily_blip = full_daily.merge(daily_agg, on="date", how="left")
        daily_blip["date"] = pd.to_datetime(daily_blip["date"])
        daily_blip["WorkedHours"] = daily_blip["WorkedHours"].fillna(0)
        daily_blip["Employees"] = daily_blip["Employees"].fillna(0).astype(int)
        daily_blip["_date_norm"] = pd.to_datetime(daily_blip["date"]).dt.normalize()
        if hasattr(daily_blip["_date_norm"].dtype, "tz") and daily_blip["_date_norm"].dtype.tz is not None:
            daily_blip["_date_norm"] = daily_blip["_date_norm"].dt.tz_localize(None)
        daily_blip["IsWFHDay"] = daily_blip["_date_norm"].isin(wfh_dates_set)
        daily_blip["Expected"] = daily_blip["Employees"] * expected_daily_hours
        daily_blip["Utilisation"] = _blip_safe_divide(daily_blip["WorkedHours"].values, daily_blip["Expected"].values)
        wfh_explicit_mask = daily_blip["IsWFHDay"] == True
        daily_blip.loc[wfh_explicit_mask & (daily_blip["Employees"] == 0), "WorkedHours"] = expected_daily_hours
        daily_blip.loc[wfh_explicit_mask & (daily_blip["Employees"] == 0), "Expected"] = expected_daily_hours
        daily_blip.loc[wfh_explicit_mask & (daily_blip["Employees"] == 0), "Utilisation"] = 1.0
        daily_blip = daily_blip[(daily_blip["Employees"] > 0) | (daily_blip["IsWFHDay"] == True)].copy()
        daily_blip = daily_blip.drop(columns=["_date_norm"], errors="ignore")
        daily_blip = daily_blip[daily_blip["date"].dt.dayofweek < 5].copy()

        def _util_to_display(y):
            y = np.clip(float(y) if not np.isnan(y) else 0, 0, 1)
            if y <= 0.7: return y * (0.2 / 0.7)
            return 0.2 + (y - 0.7) * (0.8 / 0.3)
        util_display = daily_blip["Utilisation"].apply(_util_to_display)
        fig_daily = go.Figure(data=[
            go.Scatter(x=daily_blip["date"], y=util_display, mode="lines+markers", line=dict(color="#16a34a", width=2),
                marker=dict(size=8), name="Utilisation",
                customdata=np.column_stack((daily_blip["Utilisation"],)),
                hovertemplate="Date: %{x|%d %b}<br>Utilisation: %{customdata[0]:.0%}<extra></extra>")
        ])
        fig_daily.add_hline(y=_util_to_display(1.0), line_dash="dash", line_color="#f59e0b", annotation_text=f"TH: 100% ({expected_daily_hours}h)", annotation_position="right")
        tickvals_display = [0, _util_to_display(0.35), 0.2, _util_to_display(0.8), _util_to_display(0.9), _util_to_display(1.0)]
        ticktext_pct = ["0%", "35%", "70%", "80%", "90%", "100%"]
        fig_daily.update_yaxes(title_text="Utilisation", range=[0, 1], tickvals=tickvals_display, ticktext=ticktext_pct)
        fig_daily.update_xaxes(dtick=86400000, tickformat="%d %b")
        fig_daily.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        fig_daily.update_layout(xaxis_title="Date", yaxis_title="Utilisation", showlegend=False, hovermode="x unified")
        st.plotly_chart(_blip_clean_plot(fig_daily, "Utilisation"), use_container_width=True)
        st.markdown("---")
        with st.expander("View Shift-level table (selected range)"):
            show_cols = ["date", "employee", BLIP_COL_TEAM if BLIP_COL_TEAM in f_shift.columns else None, BLIP_COL_ROLE if BLIP_COL_ROLE in f_shift.columns else None, "worked_hours", "break_hours", "duration_hours", "has_clockout", "location_mismatch"]
            show_cols = [c for c in show_cols if c is not None]
            shift_display = f_shift[show_cols].sort_values(["date", "employee"]).copy()
            for col in ["worked_hours", "break_hours", "duration_hours"]:
                if col in shift_display.columns:
                    shift_display[col] = shift_display[col].apply(lambda x: fmt_hours_minutes(x) if pd.notna(x) else "")
            st.dataframe(shift_display, use_container_width=True)
        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Employee View (Work / Break / WFH by Day)</h3>', unsafe_allow_html=True)
        if f_blip.empty:
            st.info("No rows available for the selected date range.")
        else:
            emp_list = sorted([e for e in f_blip["employee"].dropna().unique() if str(e).strip() != ""])
            if not emp_list:
                st.info("No employees found in the selected date range.")
            else:
                sel_emp = st.selectbox("Select employee", options=emp_list, index=0, key="blip_emp")
                emp_all = f_blip[f_blip["employee"].eq(sel_emp)].copy()
                emp_all_valid = emp_all[emp_all["clockin_dt"].notna() & emp_all["clockout_dt"].notna()].copy()
                all_dates_emp = pd.date_range(start=pd.Timestamp(d1_blip), end=pd.Timestamp(d2_blip), freq="D")
                weekday_dates_emp = [d for d in all_dates_emp if getattr(d, "dayofweek", d.weekday()) < 5]
                rows_seg = []
                emp_all_notes = emp_all.get("Notes", pd.Series(index=emp_all.index, dtype=object)).fillna("").astype(str).str.upper()
                emp_all["_is_wfh_note"] = emp_all_notes.str.contains("WFH", na=False)
                wfh_dates_emp = set()
                if emp_all["_is_wfh_note"].any():
                    wfh_dates_emp = {pd.Timestamp(d).normalize() for d in emp_all.loc[emp_all["_is_wfh_note"], "date"].dt.date.unique()}
                daily_leave_blip = _blip_leave_daily_for_range(df, d1_blip, d2_blip)
                leave_dates_emp = set()
                sel_emp_norm = _normalize_employee(sel_emp)
                if not daily_leave_blip.empty and "employee" in daily_leave_blip.columns and "date" in daily_leave_blip.columns:
                    emp_match = daily_leave_blip["employee"].apply(_normalize_employee) == sel_emp_norm
                    leave_rows = daily_leave_blip.loc[emp_match]
                    if "absence_category" in leave_rows.columns:
                        leave_rows = leave_rows[leave_rows["absence_category"] != "WFH"]
                    if not leave_rows.empty:
                        leave_dates_emp = set(pd.to_datetime(leave_rows["date"]).dt.normalize().dt.date)
                if not emp_all_valid.empty:
                    emp_all_valid["day"] = emp_all_valid["clockin_dt"].dt.date
                    for day, day_df in emp_all_valid.groupby("day"):
                        d_ts = pd.Timestamp(day).normalize()
                        if getattr(d_ts, "dayofweek", d_ts.weekday()) >= 5: continue
                        if d_ts in wfh_dates_emp:
                            rows_seg.append({"date": pd.to_datetime(day), "Segment": "WFH", "Kind": "WFH", "Hours": WFH_ASSUMED_HOURS, "SegIndex": 0, "start": None, "end": None})
                        else:
                            segs = _blip_build_authentic_day_segments(day_df)
                            for idx, s in enumerate(segs, start=1):
                                hrs = (s["end"] - s["start"]).total_seconds() / 3600
                                if hrs <= 0: continue
                                rows_seg.append({"date": pd.to_datetime(day), "Segment": f"{idx:02d} {s['kind']}", "Kind": s["kind"], "Hours": hrs, "SegIndex": idx, "start": s["start"], "end": s["end"]})
                dates_with_segments = {pd.Timestamp(d).normalize() for d in emp_all_valid["clockin_dt"].dt.date.unique()} if not emp_all_valid.empty else set()
                for d in weekday_dates_emp:
                    d_ts = pd.Timestamp(d).normalize()
                    if d_ts in dates_with_segments or d_ts in wfh_dates_emp: continue
                    kind = "Leave" if d_ts.date() in leave_dates_emp else "WFH"
                    rows_seg.append({"date": d_ts, "Segment": kind, "Kind": kind, "Hours": WFH_ASSUMED_HOURS, "SegIndex": 0, "start": None, "end": None})
                seg_df = pd.DataFrame(rows_seg)
                if seg_df.empty:
                    st.warning("Could not construct Work/Break segments.")
                else:
                    seg_df["date"] = pd.to_datetime(seg_df["date"])
                    seg_df = seg_df[seg_df["date"].dt.dayofweek < 5].copy()
                    if leave_dates_emp:
                        mask_leave = (seg_df["Kind"] == "WFH") & (seg_df["date"].dt.normalize().dt.date.isin(leave_dates_emp))
                        seg_df.loc[mask_leave, "Kind"] = "Leave"
                        seg_df.loc[mask_leave, "Segment"] = "Leave"
                    seg_df["TimeLabel"] = seg_df["Hours"].apply(fmt_hours_minutes)
                    Y_MIN, Y_MAX = 8.0, 19.0
                    def row_base_and_duration(row):
                        if row.get("Kind") in ("WFH", "Leave"): return 9.0, 8.0
                        start_val, end_val = row.get("start"), row.get("end")
                        if pd.notna(start_val) and pd.notna(end_val):
                            start_h = _datetime_to_hour_of_day(start_val)
                            end_h = _datetime_to_hour_of_day(end_val)
                            if np.isnan(start_h) or np.isnan(end_h): return 9.0, 8.0
                            base = max(Y_MIN, min(start_h, Y_MAX))
                            end_disp = min(Y_MAX, max(end_h, Y_MIN))
                            return base, max(0.0, end_disp - base)
                        return 9.0, 8.0
                    seg_df["base"] = np.nan
                    seg_df["duration"] = np.nan
                    for i in seg_df.index:
                        b, d = row_base_and_duration(seg_df.loc[i])
                        seg_df.loc[i, "base"] = b
                        seg_df.loc[i, "duration"] = d
                    seg_df = seg_df[seg_df["duration"] > 0].copy()
                    seg_df = seg_df.sort_values(["date", "SegIndex"]).copy()
                    _kind_colors = {"Work": "#16a34a", "Break": "#f59e0b", "WFH": "#93c5fd", "Leave": "#94a3b8"}
                    fig_seg = go.Figure()
                    legend_added = {"Work": False, "Break": False, "WFH": False, "Leave": False}
                    for date in sorted(seg_df["date"].unique()):
                        date_segs = seg_df[seg_df["date"] == date].sort_values("SegIndex")
                        for _, row in date_segs.iterrows():
                            kind = row["Kind"]
                            show_legend = not legend_added.get(kind, False)
                            legend_added[kind] = True
                            fig_seg.add_trace(go.Bar(x=[row["date"]], y=[row["duration"]], base=[row["base"]], name=kind,
                                text=[row["TimeLabel"]], textposition="inside", marker_color=_kind_colors.get(kind, "#94a3b8"),
                                legendgroup=kind, showlegend=show_legend, width=86400000 * 0.7))
                    tickvals_s = list(range(8, 20))
                    ticktext_s = [f"{h:02d}:00" for h in range(8, 20)]
                    fig_seg.update_layout(barmode="overlay", yaxis=dict(tickvals=tickvals_s, ticktext=ticktext_s, range=[7.2, Y_MAX]),
                        showlegend=True, legend=dict(title="Segment Type", orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                    all_weekdays = [d for d in pd.date_range(start=pd.Timestamp(d1_blip), end=pd.Timestamp(d2_blip), freq="D") if d.dayofweek < 5]
                    if all_weekdays:
                        fig_seg.update_xaxes(tickvals=all_weekdays, ticktext=[d.strftime("%d/%m") for d in all_weekdays],
                            tickangle=-45, range=[min(all_weekdays) - pd.Timedelta(days=0.5), max(all_weekdays) + pd.Timedelta(days=0.5)])
                    fig_seg.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
                    st.plotly_chart(_blip_clean_plot(fig_seg, y_title="Time of day", x_title="Date", show_legend=True), use_container_width=True)

        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Exceptions Overview</h3>', unsafe_allow_html=True)
        short_shifts = (f_shift["worked_hours"] < short_shift_hours).sum()
        long_shifts = (f_shift["worked_hours"] > long_shift_hours).sum()
        location_mismatch = f_shift["location_mismatch"].sum()
        c1, c2, c3, c4 = st.columns(4)
        with c1: kpi_tile("Missing clock-outs", str(int(missing_clockouts)), "No clock-out time")
        with c2: kpi_tile(f"Short shifts (< {fmt_hours_minutes(short_shift_hours)})", str(int(short_shifts)), "Worked hours")
        with c3: kpi_tile(f"Long shifts (> {fmt_hours_minutes(long_shift_hours)})", str(int(long_shifts)), "Worked hours")
        with c4: kpi_tile("Location mismatches", str(int(location_mismatch)), "In vs out location")
        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Exports</h3>', unsafe_allow_html=True)
        show_cols = ["date", "employee", BLIP_COL_TEAM if BLIP_COL_TEAM in f_shift.columns else None, BLIP_COL_ROLE if BLIP_COL_ROLE in f_shift.columns else None, "worked_hours", "break_hours", "duration_hours", "has_clockout", "location_mismatch"]
        show_cols = [c for c in show_cols if c is not None]
        sort_cols = ["date", BLIP_COL_TEAM, "employee"] if BLIP_COL_TEAM in f_shift.columns else ["date", "employee"]
        shift_export = f_shift[show_cols].sort_values(sort_cols).copy()
        shift_export["generated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        st.download_button("Download Shift-level table (CSV)", data=shift_export.to_csv(index=False).encode("utf-8"), file_name="blip_shift_table.csv", mime="text/csv", key="blip_export_shift")
        st.markdown("---")
        st.markdown('<h3 class="eg-section-title">Assumptions</h3>', unsafe_allow_html=True)
        st.markdown("""
        1. **WFH = 8 hours** — Weekdays with no BLIP clock-in are treated as full WFH (8h). Leave Management distinguishes leave (gray) from WFH (blue).  
        2. **Weekdays only** — Analyses use Mon–Fri; weekends excluded.  
        3. **BLIP data handling** — Overnight and negative durations corrected. Missing clock-outs inferred (17:25–17:45). Missing/invalid breaks get synthetic 30–45 min lunch.  
        4. **Employee matching** — Names matched across Absence and BLIP by First + Last name; extra spaces ignored.
        """)

st.markdown("")
st.markdown('<div style="text-align:center; font-size:0.8rem; color:#6b7280; padding:0.5rem 0;">Leave Management & Time Utilisation - UnitedGreen (Simplified)</div>', unsafe_allow_html=True)
