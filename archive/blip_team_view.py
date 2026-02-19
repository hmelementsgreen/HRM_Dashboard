"""
Standalone BLIP Team-Level Utilisation View
Run: streamlit run blip_team_view.py
"""
import io
import os
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="BLIP Team Utilisation", layout="wide")

st.markdown(
    """
    <style>
      :root {
        --eg-text: #111827;
        --eg-muted: #6b7280;
        --eg-border: #e5e7eb;
        --eg-radius: 12px;
        --eg-accent: #0d9488;
        --eg-shadow: 0 2px 8px rgba(0,0,0,0.06);
      }
      .eg-title { font-size: 1.75rem; font-weight: 800; color: var(--eg-text); margin-bottom: 0.25rem; }
      .eg-subtitle { color: var(--eg-muted); font-size: 0.95rem; margin-bottom: 1rem; }
      .eg-section-title { margin-top: 0.5rem; margin-bottom: 0.35rem; font-weight: 700; color: var(--eg-text); }
      .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# BLIP constants
# ----------------------------
BLIP_COL_FIRST = "First Name"
BLIP_COL_LAST = "Last Name"
BLIP_COL_TEAM = "Team(s)"
BLIP_COL_TYPE = "Blip Type"
BLIP_COL_IN_DATE = "Clock In Date"
BLIP_COL_IN_TIME = "Clock In Time"
BLIP_COL_OUT_DATE = "Clock Out Date"
BLIP_COL_OUT_TIME = "Clock Out Time"
BLIP_COL_IN_LOC = "Clock In Location"
BLIP_COL_OUT_LOC = "Clock Out Location"
BLIP_COL_DURATION = "Total Duration"
BLIP_COL_WORKED = "Total Excluding Breaks"
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
BLIP_XLSX_DEFAULT = os.path.join(_APP_DIR, "blipTimesheet_27Jan_onwards_.xlsx")
if not os.path.isfile(BLIP_XLSX_DEFAULT):
    BLIP_XLSX_DEFAULT = r"C:\Users\HarshMalhotra\OneDrive - United Green\Documents\Blip\blipTimesheet_27Jan_onwards_clean.xlsx"

def _blip_to_timedelta_safe(s: pd.Series) -> pd.Series:
    x = s.astype(str).replace({"NaT": np.nan, "nan": np.nan, "": np.nan, "None": np.nan})
    return pd.to_timedelta(x, errors="coerce")

def _blip_combine_date_time(d, t):
    d = pd.to_datetime(d, errors="coerce")
    t = t.astype(str).replace({"NaT": np.nan, "nan": np.nan, "": np.nan, "None": np.nan})
    return pd.to_datetime(d.dt.strftime("%Y-%m-%d") + " " + t, errors="coerce")

def _blip_clean_plot(fig, y_title=None, x_title=None, show_legend=None):
    layout_updates = {
        "plot_bgcolor": "white",
        "paper_bgcolor": "white",
        "margin": dict(l=20, r=20, t=50, b=20),
        "font": dict(family="Inter, system-ui, sans-serif", size=12),
    }
    if show_legend is not None:
        layout_updates["showlegend"] = show_legend
    fig.update_layout(**layout_updates)
    fig.update_xaxes(showgrid=False, title=x_title)
    fig.update_yaxes(showgrid=True, gridcolor="#f3f4f6", title=y_title)
    return fig

def _blip_safe_divide(n, d):
    return np.where(d > 0, n / d, np.nan)

def _blip_process_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    df["employee"] = (
        df.get(BLIP_COL_FIRST, pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
        + " "
        + df.get(BLIP_COL_LAST, pd.Series(index=df.index, dtype="object")).fillna("").astype(str).str.strip()
    ).str.strip()
    df["date"] = pd.to_datetime(df.get(BLIP_COL_IN_DATE), errors="coerce")
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
        df["has_clockout"] = False
    df["blip_type_norm"] = df.get(BLIP_COL_TYPE, "").astype(str).str.strip().str.lower()
    return df

@st.cache_data(show_spinner=False)
def _blip_load_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, skiprows=1, engine="openpyxl")
    return _blip_process_raw_df(df)

def _blip_load_data_from_upload(uploaded_file) -> pd.DataFrame:
    df = pd.read_excel(io.BytesIO(uploaded_file.read()), skiprows=1, engine="openpyxl")
    return _blip_process_raw_df(df)

def fmt_hours_minutes(h: float) -> str:
    if pd.isna(h):
        return ""
    h = float(h)
    hours = int(h)
    minutes = int(round((h - hours) * 60))
    if minutes >= 60:
        hours += 1
        minutes = 0
    return f"{hours}h {minutes}m"

def kpi_tile(title: str, value: str, subtitle: str = ""):
    st.markdown(
        f"""
        <div style="border-radius:var(--eg-radius); padding:14px 16px; background:linear-gradient(180deg,#fff 0%,#fbfbfb 100%); box-shadow:var(--eg-shadow);">
          <div style="font-size:0.85rem; color:var(--eg-muted); font-weight:600;">{title}</div>
          <div style="font-size:2rem; font-weight:800; color:var(--eg-text); margin-top:6px;">{value}</div>
          <div style="font-size:0.8rem; color:var(--eg-muted); margin-top:4px;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------
# Sidebar: data source & params
# ----------------------------
with st.sidebar:
    st.header("BLIP data")
    blip_uploaded = st.file_uploader("Upload BLIP export (Excel)", type=["xlsx", "xls"], key="blip_upload")
    blip_xlsx_path = st.text_input("Or enter file path", value=BLIP_XLSX_DEFAULT, disabled=blip_uploaded is not None, key="blip_path")
    if st.button("Clear cache & reload", key="blip_reload"):
        _blip_load_data.clear()
        st.rerun()
    st.markdown("---")
    expected_daily_hours = st.number_input("Expected daily hours", 0.0, 24.0, 7.5, 0.5, key="expected_hours")

df_blip = None
f_shift = None
d1_blip = d2_blip = None

if blip_uploaded is not None or (blip_xlsx_path and str(blip_xlsx_path).strip()):
    try:
        if blip_uploaded is not None:
            df_blip = _blip_load_data_from_upload(blip_uploaded)
        else:
            df_blip = _blip_load_data(blip_xlsx_path)
        if df_blip["date"].notna().sum() == 0:
            st.sidebar.warning("No valid dates in BLIP 'Clock In Date'.")
        else:
            min_dt, max_dt = df_blip["date"].min(), df_blip["date"].max()
            d1_blip, d2_blip = st.sidebar.date_input("Date range", value=(min_dt.date(), max_dt.date()), key="blip_daterange")
            f_all = df_blip[(df_blip["date"].dt.date >= d1_blip) & (df_blip["date"].dt.date <= d2_blip)].copy()
            f_shift = f_all[f_all["blip_type_norm"].eq("shift")].copy()
            f_shift = f_shift[f_shift["date"].dt.dayofweek < 5].copy()  # weekdays only
            team_col = BLIP_COL_TEAM if BLIP_COL_TEAM in f_shift.columns else None
            if team_col is not None:
                f_shift["team"] = f_shift[team_col].fillna("(Unassigned)").astype(str).str.strip()
                f_shift.loc[f_shift["team"] == "", "team"] = "(Unassigned)"
            else:
                f_shift["team"] = "(No team column)"
    except Exception as e:
        st.sidebar.warning(f"Failed to load BLIP: {e}")
        f_shift = None

# ----------------------------
# Main content
# ----------------------------
st.markdown('<p class="eg-title">BLIP Team-Level Utilisation</p>', unsafe_allow_html=True)
st.markdown('<p class="eg-subtitle">Day-by-day and summary views by Team(s). Weekdays only; recorded hours (no WFH imputation).</p>', unsafe_allow_html=True)

if f_shift is None or f_shift.empty:
    st.info("Load BLIP data in the sidebar (upload Excel or set file path) and choose a date range.")
    st.stop()

team_col = "team"
expected_hours = expected_daily_hours

# Daily aggregation by (date, team)
daily_team = f_shift.groupby(["date", team_col], as_index=False).agg(
    WorkedHours=("worked_hours", "sum"),
    Employees=("employee", "nunique"),
)
daily_team["date"] = pd.to_datetime(daily_team["date"]).dt.normalize()
daily_team["Expected"] = daily_team["Employees"] * expected_hours
daily_team["Utilisation"] = _blip_safe_divide(daily_team["WorkedHours"].values, daily_team["Expected"].values)

# Period summary by team: sum of daily worked and daily expected (correct)
team_summary = daily_team.groupby(team_col, as_index=False).agg(
    WorkedHours=("WorkedHours", "sum"),
    Expected=("Expected", "sum"),
)
emp_count = f_shift.groupby(team_col)["employee"].nunique().reset_index().rename(columns={"employee": "Employees"})
team_summary = team_summary.merge(emp_count, on=team_col)
team_summary["Utilisation"] = _blip_safe_divide(team_summary["WorkedHours"].values, team_summary["Expected"].values)
team_summary = team_summary.sort_values("Utilisation", ascending=False).reset_index(drop=True)

# KPIs
teams_count = f_shift[team_col].nunique()
employees_count = f_shift["employee"].nunique()
total_worked = f_shift["worked_hours"].sum()
total_expected = daily_team.groupby("date").agg(Expected=("Expected", "sum")).reset_index()["Expected"].sum()
overall_util = _blip_safe_divide(np.array([total_worked]), np.array([total_expected]))[0] if total_expected and total_expected > 0 else np.nan
overall_util_pct = (float(overall_util) * 100) if pd.notna(overall_util) else 0.0

c1, c2, c3, c4 = st.columns(4)
with c1:
    kpi_tile("Teams", str(teams_count), "In selected range")
with c2:
    kpi_tile("Employees", str(employees_count), "With shift data")
with c3:
    kpi_tile("Total worked", fmt_hours_minutes(total_worked), "Weekdays only")
with c4:
    kpi_tile("Overall utilisation", f"{overall_util_pct:.1f}%" if pd.notna(overall_util) else "—", "Period summary")

st.markdown("---")
# ----------------------------
# 1. Team × day heatmap (utilisation)
# ----------------------------
st.markdown('<h3 class="eg-section-title">1. Team × day utilisation (heatmap)</h3>', unsafe_allow_html=True)
st.caption("Rows = teams (worst average at top), columns = dates. Colour: red &lt; 90%, amber 90–100%, green ≥ 100%. Hover for details.")

# Pivot: rows = teams (ordered by avg utilisation ascending), columns = dates, values = utilisation
team_avg = daily_team.groupby(team_col)["Utilisation"].mean().sort_values(ascending=True)
team_order = team_avg.index.tolist()
pivot_util = daily_team.pivot(index=team_col, columns="date", values="Utilisation").reindex(team_order)
# Build matrices for Plotly (y = teams, x = dates)
heat_teams = pivot_util.index.tolist()
heat_dates = [pd.Timestamp(d).strftime("%d %b") for d in pivot_util.columns]
z_vals = pivot_util.values
# Customdata: same shape as z; each cell = "Worked Xh / Expected Yh" for hover
pivot_worked = daily_team.pivot(index=team_col, columns="date", values="WorkedHours").reindex(team_order)
pivot_expected = daily_team.pivot(index=team_col, columns="date", values="Expected").reindex(team_order)
hover_lines = []
for i in range(z_vals.shape[0]):
    row = []
    for j in range(z_vals.shape[1]):
        u = z_vals[i, j]
        w = pivot_worked.iloc[i, j] if not pd.isna(pivot_worked.iloc[i, j]) else 0
        e = pivot_expected.iloc[i, j] if not pd.isna(pivot_expected.iloc[i, j]) else 0
        pct = f"{u * 100:.1f}%" if pd.notna(u) else "—"
        row.append(f"{heat_teams[i]}<br>{heat_dates[j]}<br>Utilisation: {pct}<br>Worked: {fmt_hours_minutes(w)} / Expected: {fmt_hours_minutes(e)}")
    hover_lines.append(row)
customdata = np.array(hover_lines, dtype=object)
fig_heat = go.Figure(data=go.Heatmap(
    x=heat_dates,
    y=heat_teams,
    z=z_vals,
    customdata=customdata,
    hovertemplate="%{customdata}<extra></extra>",
    colorscale=[
        [0, "#dc2626"],
        [0.75, "#dc2626"],
        [0.75, "#f59e0b"],
        [0.833, "#f59e0b"],
        [0.833, "#15803d"],
        [1, "#15803d"],
    ],
    zmin=0,
    zmax=1.2,
    colorbar=dict(title="Utilisation", tickformat=".0%", thickness=14),
))
fig_heat.update_layout(
    xaxis_title="Date",
    yaxis_title="Team",
    plot_bgcolor="white",
    paper_bgcolor="white",
    margin=dict(l=20, r=20, t=40, b=20),
    font=dict(family="Inter, system-ui, sans-serif", size=12),
    xaxis=dict(tickangle=-45),
    yaxis=dict(autorange="reversed"),
)
st.plotly_chart(_blip_clean_plot(fig_heat, "Team", "Date"), use_container_width=True)

st.markdown("---")
st.markdown('<h3 class="eg-section-title">2. Utilisation by team (period summary)</h3>', unsafe_allow_html=True)
st.caption("One bar per team: total worked / total expected over the selected date range.")

team_summary["UtilPct"] = (team_summary["Utilisation"] * 100).round(1)
team_summary["BarColor"] = team_summary["Utilisation"].apply(
    lambda u: "#dc2626" if pd.isna(u) or u < 0.9 else "#15803d" if u >= 1.0 else "#22c55e"
)
fig_team_bar = go.Figure(data=[
    go.Bar(
        x=team_summary[team_col],
        y=team_summary["Utilisation"],
        marker_color=team_summary["BarColor"],
        text=team_summary["UtilPct"].apply(lambda x: f"{x:.1f}%"),
        textposition="outside",
        hovertemplate="%{x}<br>Utilisation: %{y:.1%}<extra></extra>",
    )
])
fig_team_bar.add_hline(y=0.9, line_dash="dash", line_color="#f59e0b", annotation_text="90%")
fig_team_bar.add_hline(y=1.0, line_dash="dash", line_color="#6b7280")
fig_team_bar.update_yaxes(tickformat=".0%")
fig_team_bar.update_layout(xaxis_title="Team", yaxis_title="Utilisation", showlegend=False, hovermode="x")
st.plotly_chart(_blip_clean_plot(fig_team_bar, "Utilisation", "Team"), use_container_width=True)

st.markdown("**Summary table**")
display_table = team_summary[[team_col, "WorkedHours", "Expected", "Utilisation", "Employees"]].copy()
display_table["WorkedHours"] = display_table["WorkedHours"].round(2)
display_table["Expected"] = display_table["Expected"].round(2)
display_table["Utilisation %"] = (display_table["Utilisation"] * 100).round(1)
display_table = display_table.rename(columns={team_col: "Team", "WorkedHours": "Worked (hrs)", "Expected": "Expected (hrs)", "Employees": "Employees"})
st.dataframe(display_table[["Team", "Worked (hrs)", "Expected (hrs)", "Utilisation %", "Employees"]], use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown('<h3 class="eg-section-title">3. Daily utilisation over time by team</h3>', unsafe_allow_html=True)
st.caption("Pick teams to compare day-by-day utilisation (one line per team).")

team_options = sorted(daily_team[team_col].unique().tolist())
selected_teams = st.multiselect("Select teams", options=team_options, default=team_options[: min(5, len(team_options))], key="teams_line")
daily_team_sel = daily_team[daily_team[team_col].isin(selected_teams)] if selected_teams else daily_team

if not daily_team_sel.empty:
    fig_daily_team = px.line(
        daily_team_sel,
        x="date",
        y="Utilisation",
        color=team_col,
        markers=True,
    )
    fig_daily_team.add_hline(y=0.9, line_dash="dash", line_color="#f59e0b")
    fig_daily_team.add_hline(y=1.0, line_dash="dash", line_color="#6b7280")
    fig_daily_team.update_yaxes(tickformat=".0%")
    fig_daily_team.update_xaxes(dtick=86400000, tickformat="%d %b")
    fig_daily_team.update_layout(hovermode="x unified", legend_title="Team")
    st.plotly_chart(_blip_clean_plot(fig_daily_team, "Utilisation", "Date", show_legend=True), use_container_width=True)
else:
    st.caption("Select at least one team.")

st.markdown("---")
st.markdown('<h3 class="eg-section-title">4. Single-team daily breakdown</h3>', unsafe_allow_html=True)
st.caption("Select one team to see its day-by-day utilisation (same style as main dashboard).")

sel_team = st.selectbox("Select team", options=[""] + team_options, key="team_drill")
if sel_team:
    daily_one = daily_team[daily_team[team_col] == sel_team].copy()
    daily_one = daily_one[daily_one["date"].dt.dayofweek < 5].copy()  # weekdays only, exclude weekends
    daily_one = daily_one.sort_values("date").reset_index(drop=True)
    if not daily_one.empty:
        daily_one["UtilPct"] = (daily_one["Utilisation"] * 100).round(1)
        daily_one["BarColor"] = daily_one["Utilisation"].apply(
            lambda u: "#dc2626" if pd.isna(u) or u < 0.9 else "#15803d" if u >= 1.0 else "#22c55e"
        )
        fig_one = go.Figure(data=[
            go.Bar(
                x=daily_one["date"],
                y=daily_one["Utilisation"],
                marker_color=daily_one["BarColor"],
                text=daily_one["UtilPct"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside",
                hovertemplate="Date: %{x}<br>Utilisation: %{y:.1%}<extra></extra>",
            )
        ])
        fig_one.add_hline(y=0.9, line_dash="dash", line_color="#f59e0b", annotation_text="90%")
        fig_one.add_hline(y=1.0, line_dash="dash", line_color="#6b7280")
        fig_one.update_yaxes(tickformat=".0%")
        fig_one.update_xaxes(dtick=86400000, tickformat="%d %b", rangebreaks=[dict(bounds=["sat", "mon"])])
        fig_one.update_layout(xaxis_title="Date", yaxis_title="Utilisation", showlegend=False, hovermode="x")
        st.plotly_chart(_blip_clean_plot(fig_one, "Utilisation", "Date"), use_container_width=True)
    else:
        st.caption("No data for this team in the selected range.")
else:
    st.caption("Select a team above.")
