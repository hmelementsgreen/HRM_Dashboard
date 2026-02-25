"""
Absence (leave) processing and daily expansion. No Streamlit dependency.
Used by build_combined_daily.py and can be imported by app_simplified.
"""
import re
import hashlib
import pandas as pd

METRIC_COL = "Absence duration for period in days"
CLEANED_FINAL_TYPES = {"Annual", "Medical", "Work from home", "External & additional assignments", "Others"}
CLEANED_TO_DASH = {
    "Annual": "Annual Leave",
    "Medical": "Medical + Sickness",
    "Work from home": "WFH",
    "External & additional assignments": "External & additional assignments",
    "Others": "Other (excl. WFH, Travel)",
}
DETAIL_COL_CANDIDATES = ["Absence description", "Description", "Reason", "Notes", "Comment", "Absence reason", "Absence notes"]
ENTITLEMENT_COL = "Leave entitlement"
ENTITLEMENT_UNIT_COL = "Entitlement unit"
ENTITLEMENT_DAYS_COL = "leave_entitlement_days"

TEAMS_EG = {"HR", "UK BDM", "DE BDM", "Engineering", "Operations", "Investment", "Investments"}
TEAMS_AG = {"Agri"}
TEAMS_UG = {"Executive", "UG Business Support", "Group Finance", "Finance", "Property", "Group Legal", "Management"}


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


def process_absence_df(df_raw):
    """Process raw absence CSV to standard columns and categories."""
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
    for src_col in [ENTITLEMENT_COL, "Leave allowance"]:
        if src_col in df.columns:
            df[src_col] = pd.to_numeric(df[src_col], errors="coerce")
    unit = df[ENTITLEMENT_UNIT_COL].fillna("").astype(str).str.strip().str.lower() if ENTITLEMENT_UNIT_COL in df.columns else pd.Series([""] * len(df), index=df.index)
    unit_ok = unit.str.contains("day") | unit.eq("") if ENTITLEMENT_UNIT_COL in df.columns else pd.Series([True] * len(df), index=df.index)
    if ENTITLEMENT_COL in df.columns:
        df[ENTITLEMENT_DAYS_COL] = df[ENTITLEMENT_COL].fillna(df.get("Leave allowance", pd.NA))
    elif "Leave allowance" in df.columns:
        df[ENTITLEMENT_DAYS_COL] = df["Leave allowance"]
    else:
        df[ENTITLEMENT_DAYS_COL] = pd.NA
    if ENTITLEMENT_UNIT_COL in df.columns:
        df.loc[~unit_ok, ENTITLEMENT_DAYS_COL] = pd.NA
    return df


def expand_to_daily(df_in):
    """Expand absence cases to one row per calendar day. Preserves employee, date, absence_category, Team names, Country, Organisation, case_id, purpose, etc."""
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


def load_absence_and_expand_daily(csv_path, months_tuple=None):
    """Load absence CSV, process, optionally filter by months, expand to daily. Returns one row per employee per date (may be multiple rows per employee-date if multiple leave types)."""
    df_all = process_absence_df(pd.read_csv(csv_path))
    if months_tuple:
        df_all = df_all[df_all["month"].isin(list(months_tuple))].copy()
    return expand_to_daily(df_all)
