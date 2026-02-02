import io
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px

# =========================================================
# BLIP Utilisation Dashboard (Revised for BLIP export format)

# 1) Excel has a note line first -> read with skiprows=1
# 2) Breaks are rows (Blip Type = Break), not a column
# 3) Utilisation should be computed on Shift rows only
# 4) Worked hours = Total Excluding Breaks (Shift rows)
# 5) Total Duration shown separately, Break hours inferred = Duration - Worked
# =========================================================

# ============================
# Page config + styling
# ============================
st.set_page_config(page_title="BLIP Utilisation Dashboard", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 1rem; padding-bottom: 2rem; }

      .eg-title { text-align: center; font-weight: 700; margin-bottom: 0.25rem; }
      .eg-subtitle { text-align: center; color: #6b7280; margin-bottom: 1rem; }

      div[data-testid="stMetric"] {
        text-align: center;
        border-radius: 14px;
        border: 1px solid #e5e7eb;
        padding: 0.6rem;
        
        background: white;
      }

      .eg-card {
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 0.9rem;
        background: white;
        margin-bottom: 1rem;
      }

      .eg-section-title { font-weight: 650; margin-bottom: 0.3rem; }

      .eg-hint {
        padding: 0.6rem 0.8rem;
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        background: #fafafa;
        margin-bottom: 1rem;
        color: #374151;
      }

      .js-plotly-plot { margin-top: -0.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================
# Column config (BLIP export)
# ============================
COL_FIRST = "First Name"
COL_LAST = "Last Name"
COL_TEAM = "Team(s)"
COL_ROLE = "Job Title"
COL_TYPE = "Blip Type"

COL_IN_DATE = "Clock In Date"
COL_IN_TIME = "Clock In Time"
COL_OUT_DATE = "Clock Out Date"
COL_OUT_TIME = "Clock Out Time"

COL_IN_LOC = "Clock In Location"
COL_OUT_LOC = "Clock Out Location"

COL_DURATION = "Total Duration"
COL_WORKED = "Total Excluding Breaks"

# ============================
# Helpers
# ============================
def to_timedelta_safe(s: pd.Series) -> pd.Series:
    x = s.astype(str).replace({"NaT": np.nan, "nan": np.nan, "": np.nan, "None": np.nan})
    return pd.to_timedelta(x, errors="coerce")

def combine_date_time(d, t):
    d = pd.to_datetime(d, errors="coerce")
    t = t.astype(str).replace({"NaT": np.nan, "nan": np.nan, "": np.nan, "None": np.nan})
    return pd.to_datetime(d.dt.strftime("%Y-%m-%d") + " " + t, errors="coerce")

def clean_plot(fig, y_title=None, x_title=None):
    fig.update_layout(
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=20, r=20, t=50, b=20),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, title=x_title)
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6", title=y_title)
    return fig

def safe_divide(n, d):
    return np.where(d > 0, n / d, np.nan)

# ============================
# Load data (IMPORTANT: skiprows=1)
# ============================
def _process_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """Apply BLIP column parsing and derived fields to a raw Excel DataFrame."""
    df.columns = [str(c).strip() for c in df.columns]

    df["employee"] = (
        df.get(COL_FIRST, pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
        + " "
        + df.get(COL_LAST, pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
    ).str.strip()

    df["date"] = pd.to_datetime(df.get(COL_IN_DATE), errors="coerce")
    df["week_start"] = df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")
    df["month"] = df["date"].dt.to_period("M").astype(str)

    df["duration_td"] = to_timedelta_safe(df.get(COL_DURATION, pd.Series(index=df.index, dtype="object")))
    df["worked_td"] = to_timedelta_safe(df.get(COL_WORKED, pd.Series(index=df.index, dtype="object")))
    df["duration_hours"] = df["duration_td"].dt.total_seconds() / 3600
    df["worked_hours"] = df["worked_td"].dt.total_seconds() / 3600
    df["break_hours"] = (df["duration_hours"] - df["worked_hours"]).clip(lower=0)

    if COL_IN_TIME in df.columns and COL_OUT_TIME in df.columns:
        df["clockin_dt"] = combine_date_time(df[COL_IN_DATE], df[COL_IN_TIME])
        df["clockout_dt"] = combine_date_time(df[COL_OUT_DATE], df[COL_OUT_TIME])
        df["has_clockout"] = df["clockout_dt"].notna() & df["clockin_dt"].notna()
    else:
        df["clockin_dt"] = pd.NaT
        df["clockout_dt"] = pd.NaT
        df["has_clockout"] = False

    if COL_IN_LOC in df.columns and COL_OUT_LOC in df.columns:
        df["location_mismatch"] = (
            df[COL_IN_LOC].astype(str) != df[COL_OUT_LOC].astype(str)
        ) & df["has_clockout"]
    else:
        df["location_mismatch"] = False

    df["blip_type_norm"] = df.get(COL_TYPE, "").astype(str).str.strip().str.lower()
    return df


@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    """Load and process BLIP export from a file path (cached)."""
    df = pd.read_excel(path, skiprows=1)
    return _process_raw_df(df)


def load_data_from_upload(uploaded_file) -> pd.DataFrame:
    """Load and process BLIP export from an uploaded file (not cached)."""
    df = pd.read_excel(io.BytesIO(uploaded_file.read()), skiprows=1)
    return _process_raw_df(df)

# ============================
# Header
# ============================
st.markdown('<h1 class="eg-title">BLIP Utilisation Dashboard</h1>', unsafe_allow_html=True)
st.markdown(
    '<div class="eg-subtitle">Executive overview of workforce utilisation and compliance</div>',
    unsafe_allow_html=True
)
st.markdown("---")

# ============================
# Controls
# ============================
uploaded_file = st.file_uploader("Upload BLIP export (Excel)", type=["xlsx", "xls"], help="Upload a file to use instead of a path.")

default_path = r"C:\Users\HarshMalhotra\OneDrive - United Green\Documents\Blip\Blip_27_28.xlsx"
xlsx_path = st.text_input("Or enter Excel file path", value=default_path, disabled=uploaded_file is not None)

expected_daily_hours = st.number_input("Expected daily hours", 0.0, 24.0, 7.5, 0.5)

include_weekends = st.checkbox("Include weekends (utilisation expected uses selected days)", value=False)

with st.expander("Exception thresholds"):
    short_shift_hours = st.number_input("Short shift threshold (hours)", 0.0, 24.0, 2.0, 0.5, help="Shifts with worked hours below this count as exceptions.")
    long_shift_hours = st.number_input("Long shift threshold (hours)", 0.0, 24.0, 10.0, 0.5, help="Shifts with worked hours above this count as exceptions.")

st.markdown(
    """
    <div class="eg-hint">
      <b>Important:</b> Utilisation is calculated on <b>Shift</b> rows only. Breaks in the export are separate rows.
      Worked hours = <b>Total Excluding Breaks</b>. Total Duration is shown separately.
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================
# Load
# ============================
try:
    if uploaded_file is not None:
        df = load_data_from_upload(uploaded_file)
    else:
        df = load_data(xlsx_path)
except Exception as e:
    st.error(f"Failed to load file: {e}")
    st.stop()

if df["date"].notna().sum() == 0:
    st.error("No valid dates found in 'Clock In Date'. Please check the export columns.")
    st.stop()

min_dt, max_dt = df["date"].min(), df["date"].max()

# Streamlit date_input needs python dates
d1, d2 = st.date_input("Date range", value=(min_dt.date(), max_dt.date()))

f = df[(df["date"].dt.date >= d1) & (df["date"].dt.date <= d2)].copy()

# Shift-only view for utilisation + worked hours
f_shift = f[f["blip_type_norm"].eq("shift")].copy()

# Optional: exclude weekends (on the shift data)
if not include_weekends:
    f_shift = f_shift[f_shift["date"].dt.weekday < 5].copy()

# ============================
# KPIs (Shift-only for utilisation metrics)
# ============================
entries_all = len(f)
entries_shift = len(f_shift)

employees = f_shift["employee"].nunique()
teams = f_shift[COL_TEAM].nunique() if COL_TEAM in f_shift.columns else 0

missing_clockouts = (~f_shift["has_clockout"]).sum()

worked_total = f_shift["worked_hours"].sum(skipna=True)
duration_total = f_shift["duration_hours"].sum(skipna=True)
break_total = f_shift["break_hours"].sum(skipna=True)

avg_worked_shift = f_shift["worked_hours"].mean(skipna=True)

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Entries (all)", f"{entries_all:,}")
k2.metric("Shift entries", f"{entries_shift:,}")
k3.metric("Employees", f"{employees:,}")
k4.metric("Missing clock-outs", f"{int(missing_clockouts):,}")
k5.metric("Worked hours", f"{worked_total:,.1f}")
k6.metric("Avg worked / shift", f"{avg_worked_shift:,.2f}")

st.markdown(
    f"""
    <div class="eg-hint">
      <b>Shift totals in selected range:</b>
      Total Duration = <b>{duration_total:,.1f}h</b> · Break = <b>{break_total:,.1f}h</b> · Worked (excl breaks) = <b>{worked_total:,.1f}h</b>
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown("---")

# ============================
# Daily utilisation (Shift-only)
# ============================
st.markdown('<h3 class="eg-section-title">Daily Utilisation (Shift rows only)</h3>', unsafe_allow_html=True)

daily = f_shift.groupby("date", as_index=False).agg(
    WorkedHours=("worked_hours", "sum"),
    Employees=("employee", "nunique"),
)
daily["Expected"] = daily["Employees"] * expected_daily_hours
daily["Utilisation"] = safe_divide(daily["WorkedHours"], daily["Expected"])

fig = px.bar(
    daily,
    x="date",
    y="Utilisation",
    color=daily["Utilisation"] >= 1.0,
    color_discrete_map={True: "green", False: "red"},
)
fig.add_hline(y=1.0, line_dash="dash")
fig.update_yaxes(tickformat=".0%")
st.plotly_chart(clean_plot(fig, "Utilisation"), use_container_width=True)

st.markdown("---")

# ============================
# Weekly utilisation (Shift-only)
# ============================
st.markdown('<h3 class="eg-section-title">Weekly Utilisation (Shift rows only)</h3>', unsafe_allow_html=True)

weekly = f_shift.groupby("week_start", as_index=False).agg(
    WorkedHours=("worked_hours", "sum"),
    Employees=("employee", "nunique"),
)

# Expected days per week based on weekend toggle
expected_days = 7 if include_weekends else 5
weekly["Expected"] = weekly["Employees"] * expected_daily_hours * expected_days
weekly["Utilisation"] = safe_divide(weekly["WorkedHours"], weekly["Expected"])

fig = px.line(weekly, x="week_start", y="Utilisation", markers=True)
fig.add_hline(y=1.0, line_dash="dash")
fig.update_yaxes(tickformat=".0%")
st.plotly_chart(clean_plot(fig, "Utilisation"), use_container_width=True)

st.markdown("---")

# ============================
# Monthly hours split (Shift-only)
# ============================
st.markdown('<h3 class="eg-section-title">Monthly Hours (Shift rows only)</h3>', unsafe_allow_html=True)

monthly = f_shift.groupby("month", as_index=False).agg(
    WorkedHours=("worked_hours", "sum"),
    BreakHours=("break_hours", "sum"),
    DurationHours=("duration_hours", "sum"),
)

# Stacked-like view using long form
m_long = monthly.melt(
    id_vars=["month"],
    value_vars=["WorkedHours", "BreakHours"],
    var_name="Type",
    value_name="Hours"
)

fig = px.bar(m_long, x="month", y="Hours", color="Type")
st.plotly_chart(clean_plot(fig, "Hours", "Month"), use_container_width=True)

st.markdown("---")

# ============================
# Exceptions summary (Shift-only)
# ============================
st.markdown('<h3 class="eg-section-title">Exceptions Overview (Shift rows only)</h3>', unsafe_allow_html=True)

short_shifts = (f_shift["worked_hours"] < short_shift_hours).sum()
long_shifts = (f_shift["worked_hours"] > long_shift_hours).sum()
location_mismatch = f_shift["location_mismatch"].sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Missing clock-outs", int(missing_clockouts))
c2.metric(f"Short shifts (worked < {short_shift_hours}h)", int(short_shifts))
c3.metric(f"Long shifts (worked > {long_shift_hours}h)", int(long_shifts))
c4.metric("Location mismatches", int(location_mismatch))

st.markdown("---")

# ============================
# Detail table (optional)
# ============================
with st.expander("View Shift-level table (selected range)"):
    show_cols = [
        "date",
        "employee",
        COL_TEAM if COL_TEAM in f_shift.columns else None,
        COL_ROLE if COL_ROLE in f_shift.columns else None,
        "worked_hours",
        "break_hours",
        "duration_hours",
        "has_clockout",
        "location_mismatch",
    ]
    show_cols = [c for c in show_cols if c is not None]
    out = f_shift[show_cols].sort_values(["date", "employee"])
    st.dataframe(out, use_container_width=True)

# ============================
# Employee-level: Authentic Work–Break–Work (from timestamps, robust)
# ============================
st.markdown('<h3 class="eg-section-title">Employee View (Authentic Work–Break–Work by Day)</h3>', unsafe_allow_html=True)

def _merge_consecutive(segments):
    """segments: list of dicts with {start, end, kind}. Merge consecutive same-kind."""
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

def build_authentic_day_segments(emp_df_day: pd.DataFrame):
    """
    Build ordered Work/Break segments for a single day using actual intervals.
    Break overrides shift when overlapping.
    Returns list of dicts: {start, end, kind} with kind in {"Work","Break"}.
    """
    d = emp_df_day.copy()
    d = d[d["clockin_dt"].notna() & d["clockout_dt"].notna()].copy()
    if d.empty:
        return []

    # Build intervals from raw rows
    intervals = []
    for _, r in d.iterrows():
        s = r["clockin_dt"]
        e = r["clockout_dt"]
        if pd.isna(s) or pd.isna(e) or e <= s:
            continue
        bt = str(r.get("blip_type_norm", "")).strip().lower()
        kind = "Break" if bt == "break" else ("Shift" if bt == "shift" else None)
        if kind is None:
            continue
        intervals.append({"start": s, "end": e, "kind": kind})

    if not intervals:
        return []

    # Cut points = all starts/ends
    cuts = sorted({x for it in intervals for x in (it["start"], it["end"])})
    if len(cuts) < 2:
        return []

    # Helper: does [a,b] lie inside any interval of a type?
    def covered_by(kind, a, b):
        for it in intervals:
            if it["kind"] != kind:
                continue
            # overlap check (segment fully within overlap region)
            if a >= it["start"] and b <= it["end"]:
                return True
        return False

    # Build tiny segments between cut points; assign Break over Shift
    segs = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b <= a:
            continue

        # Segment label: Break overrides Shift
        if covered_by("Break", a, b):
            segs.append({"start": a, "end": b, "kind": "Break"})
        elif covered_by("Shift", a, b):
            segs.append({"start": a, "end": b, "kind": "Work"})
        else:
            # outside any shift/break interval -> ignore
            pass

    # Merge consecutive
    segs = _merge_consecutive(segs)
    return segs

if f.empty:
    st.info("No rows available for the selected date range.")
else:
    emp_list = sorted([e for e in f["employee"].dropna().unique() if str(e).strip() != ""])
    if not emp_list:
        st.info("No employees found in the selected date range.")
    else:
        sel_emp = st.selectbox("Select employee", options=emp_list, index=0)

        emp_all = f[f["employee"].eq(sel_emp)].copy()

        # Use timestamp date for grouping (more reliable than Clock In Date column)
        emp_all = emp_all[emp_all["clockin_dt"].notna() & emp_all["clockout_dt"].notna()].copy()
        if emp_all.empty:
            st.warning("No valid clock-in/clock-out timestamps found for this employee in the selected range.")
        else:
            emp_all["day"] = emp_all["clockin_dt"].dt.date

            rows = []
            for day, day_df in emp_all.groupby("day"):
                segs = build_authentic_day_segments(day_df)

                # Build numbered segments so stacked bar preserves order
                for idx, s in enumerate(segs, start=1):
                    hrs = (s["end"] - s["start"]).total_seconds() / 3600
                    if hrs <= 0:
                        continue
                    rows.append({
                        "date": pd.to_datetime(day),
                        "Segment": f"{idx:02d} {s['kind']}",  # keeps order in legend/categories
                        "Kind": s["kind"],
                        "Hours": hrs,
                        "SegIndex": idx
                    })

            seg_df = pd.DataFrame(rows)

            if seg_df.empty:
                st.warning(
                    "Could not construct Work/Break segments from timestamps.\n\n"
                    "Common causes:\n"
                    "• Break rows do not have clock-in/out times\n"
                    "• Only Shift rows exist (no Break rows)\n"
                    "• Times overlap inconsistently"
                )
            else:
                # Ensure stacking order by segment index
                seg_order = (
                    seg_df.sort_values(["date", "SegIndex"])
                          .groupby("date")["Segment"]
                          .apply(list)
                          .explode()
                          .unique()
                          .tolist()
                )

                fig = px.bar(
                    seg_df,
                    x="date",
                    y="Hours",
                    color="Segment",
                    barmode="stack",
                    category_orders={"Segment": seg_order},
                    color_discrete_map={seg: ("red" if "Break" in seg else "green") for seg in seg_df["Segment"].unique()},
                )

                st.plotly_chart(clean_plot(fig, y_title="Hours", x_title="Date"), use_container_width=True)

                # Daily totals table
                daily_totals = seg_df.groupby(["date", "Kind"], as_index=False)["Hours"].sum()
                piv = daily_totals.pivot(index="date", columns="Kind", values="Hours").fillna(0).reset_index()
                piv["Total"] = piv.get("Work", 0) + piv.get("Break", 0)

                with st.expander("View daily totals (from timestamps)"):
                    st.dataframe(piv.sort_values("date"), use_container_width=True)
