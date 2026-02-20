import pandas as pd
import streamlit as st
import plotly.express as px

# ----------------------------
# Page config + global styling
# ----------------------------
st.set_page_config(page_title="BrightHR Absence Dashboard", layout="wide")

st.markdown(
    """
    <style>
      /* Center the main title + reduce top whitespace a bit */
      .eg-title {
        text-align: center;
        margin-top: 0.25rem;
        margin-bottom: 0.25rem;
      }
      .eg-subtitle {
        text-align: center;
        color: #6b7280;
        margin-top: 0rem;
        margin-bottom: 1rem;
        font-size: 0.95rem;
      }

      /* Center Streamlit metric blocks */
      div[data-testid="stMetric"] { text-align: center; }
      div[data-testid="stMetricLabel"],
      div[data-testid="stMetricValue"],
      div[data-testid="stMetricDelta"] { justify-content: center; }

      /* Give sections a bit more breathing room */
      .eg-section-title {
        margin-top: 0.25rem;
        margin-bottom: 0.25rem;
      }

      /* Vertical dividers (explicit heights so they always show) */
      .eg-vertical-divider-kpi{
        border-left: 2px solid #e5e7eb;
        height: 230px;
        margin: 0 auto;
      }
      .eg-vertical-divider-donut{
        border-left: 2px solid #e5e7eb;
        height: 520px;
        margin: 0 auto;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# Constants
# ----------------------------
CSV_PATH_DEFAULT = r"C:\Users\HarshMalhotra\Documents\BrightHRData\AbsenseReport_Cleaned_Final.csv"
METRIC_COL = "Absence duration for period in days"

TYPE_ORDER = [
    "Annual Leave",
    "Medical + Sickness",
    "Other (excl. WFH, Travel)",
    "WFH",
    "Travel",
]

WFH_KEYWORDS = ["wfh", "work from home", "work-from-home", "remote", "home working", "telework", "tele-working"]
TRAVEL_KEYWORDS = ["travel", "business trip", "offsite", "onsite", "client visit", "site visit"]
ANNUAL_KEYWORDS = ["annual", "holiday", "vacation", "pto"]
SICK_KEYWORDS = ["sick", "sickness", "medical", "ill", "flu", "gp", "doctor", "hospital", "injury"]

DETAIL_COL_CANDIDATES = [
    "Absence description",
    "Description", "Reason", "Notes", "Comment", "Absence reason", "Absence notes"
]

# ----------------------------
# Helpers
# ----------------------------
def _has_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)

def map_absence_type(abs_type: str, details: str = "") -> str:
    t = "" if pd.isna(abs_type) else str(abs_type).lower().strip()
    d = "" if pd.isna(details) else str(details).lower().strip()
    combined = f"{t} {d}".strip()

    if _has_any(combined, WFH_KEYWORDS):
        return "WFH"
    if _has_any(combined, TRAVEL_KEYWORDS):
        return "Travel"
    if _has_any(combined, ANNUAL_KEYWORDS):
        return "Annual Leave"
    if _has_any(combined, SICK_KEYWORDS):
        return "Medical + Sickness"
    return "Other (excl. WFH, Travel)"

@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    df["Absence start date"] = pd.to_datetime(df.get("Absence start date"), errors="coerce")
    df["month"] = df["Absence start date"].dt.to_period("M").astype(str)

    detail_col = next((c for c in DETAIL_COL_CANDIDATES if c in df.columns), None)
    if detail_col:
        df["absence_category"] = df.apply(
            lambda r: map_absence_type(r.get("Absence type", ""), r.get(detail_col, "")),
            axis=1
        )
    else:
        df["absence_category"] = df.get("Absence type", "").apply(lambda x: map_absence_type(x, ""))

    fn = df.get("First name", "").astype(str).str.strip()
    ln = df.get("Last name", "").astype(str).str.strip()
    df["employee"] = (fn + " " + ln).str.strip()

    df[METRIC_COL] = pd.to_numeric(df.get(METRIC_COL), errors="coerce").fillna(0)
    return df

def fmt_num(x: float) -> str:
    return f"{x:,.1f}"

# ----------------------------
# Centered heading
# ----------------------------
st.markdown('<h1 class="eg-title">Absence Dashboard</h1>', unsafe_allow_html=True)
st.markdown(
    '<div class="eg-subtitle">BrightHR Absence Overview • KPI + Leave Mix • Org/Dept/Employee Drilldown</div>',
    unsafe_allow_html=True
)

# ----------------------------
# Sidebar controls
# ----------------------------
with st.sidebar:
    st.header("Controls")
    csv_path = st.text_input("CSV path", value=CSV_PATH_DEFAULT)
    df = load_data(csv_path)

    months_available = sorted([m for m in df["month"].dropna().unique().tolist() if m != "NaT"])
    if not months_available:
        st.error("No valid months found.")
        st.stop()

    default_m1_index = max(len(months_available) - 2, 0)
    month_1 = st.selectbox("Select month", options=months_available, index=default_m1_index)

    add_second_month = st.checkbox("Add another month for comparison", value=True)
    if add_second_month:
        month_2_options = [m for m in months_available if m != month_1]
        month_2 = (
            st.selectbox(
                "Select comparison month",
                options=month_2_options,
                index=(len(month_2_options) - 1) if month_2_options else 0
            )
            if month_2_options else None
        )
    else:
        month_2 = None

    selected_cats = st.multiselect("Absence types (optional)", options=TYPE_ORDER, default=[])

months_in_scope = [month_1] + ([month_2] if month_2 else [])

# ----------------------------
# Scope data: month + absence type filter
# (Used for Overview + Org/Dept tabs; Employee tab uses df directly to keep full bifurcation)
# ----------------------------
df_scope = df[df["month"].isin(months_in_scope)].copy()
if selected_cats:
    df_scope = df_scope[df_scope["absence_category"].isin(selected_cats)]

# ----------------------------
# Tabs
# ----------------------------
tab_overview, tab_org_dept, tab_employee = st.tabs(
    ["Overview", "Organisation & Department", "Employee View"]
)

# =========================================================
# TAB 1: OVERVIEW (KPIs + Donuts)
# =========================================================
with tab_overview:
    st.markdown('<h3 class="eg-section-title">KPIs</h3>', unsafe_allow_html=True)

    monthly_days = df_scope.groupby("month")[METRIC_COL].sum()
    days_m1 = float(monthly_days.get(month_1, 0))

    if month_2:
        days_m2 = float(monthly_days.get(month_2, 0))
        diff = days_m2 - days_m1
        if days_m1 == 0:
            delta_str = "N/A (baseline 0)" if days_m2 != 0 else "0.0%"
        else:
            delta_str = f"{(diff / days_m1 * 100):.1f}%"

        sp_l, c1, c2, c3, sp_r = st.columns([1, 2, 2, 2, 1])
        with c1:
            st.metric(f"Absence days ({month_1})", fmt_num(days_m1))
        with c2:
            st.metric(f"Absence days ({month_2})", fmt_num(days_m2))
        with c3:
            st.metric("Change", fmt_num(diff), delta_str)
    else:
        sp_l, c1, sp_r = st.columns([2, 3, 2])
        with c1:
            st.metric(f"Absence days ({month_1})", fmt_num(days_m1))

    st.markdown("---")

    st.markdown('<h3 class="eg-section-title">Leave-type KPI breakdown</h3>', unsafe_allow_html=True)

    type_month = (
        df_scope.groupby(["month", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )
    grid = pd.MultiIndex.from_product(
        [months_in_scope, TYPE_ORDER],
        names=["month", "absence_category"]
    ).to_frame(index=False)
    type_month = grid.merge(type_month, on=["month", "absence_category"], how="left")
    type_month[METRIC_COL] = type_month[METRIC_COL].fillna(0)

    def render_type_kpis_for_month(m: str, show_delta: bool):
        st.markdown(f"**{m}**")

        m_series = (
            type_month[type_month["month"] == m]
            .set_index("absence_category")[METRIC_COL]
            .reindex(TYPE_ORDER)
            .fillna(0)
        )
        baseline = (
            type_month[type_month["month"] == month_1]
            .set_index("absence_category")[METRIC_COL]
            .reindex(TYPE_ORDER)
            .fillna(0)
        )

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
        with left:
            render_type_kpis_for_month(month_1, show_delta=False)
        with sep:
            st.markdown('<div class="eg-vertical-divider-kpi">&nbsp;</div>', unsafe_allow_html=True)
        with right:
            render_type_kpis_for_month(month_2, show_delta=True)
    else:
        render_type_kpis_for_month(month_1, show_delta=False)

    st.markdown("---")

    st.markdown('<h3 class="eg-section-title">Absence by Type</h3>', unsafe_allow_html=True)

    pie_df = (
        df_scope.groupby(["month", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )
    grid = pd.MultiIndex.from_product(
        [months_in_scope, TYPE_ORDER],
        names=["month", "absence_category"]
    ).to_frame(index=False)
    pie_df = grid.merge(pie_df, on=["month", "absence_category"], how="left")
    pie_df[METRIC_COL] = pie_df[METRIC_COL].fillna(0)

    def donut_for_month(m: str):
        d = pie_df[pie_df["month"] == m].copy()
        d = d[d[METRIC_COL] > 0]
        if d.empty:
            st.info(f"No absence days for {m}.")
            return

        fig = px.pie(
            d,
            names="absence_category",
            values=METRIC_COL,
            hole=0.55,
            category_orders={"absence_category": TYPE_ORDER},
        )
        fig.update_traces(
            textinfo="percent+value",
            texttemplate="%{percent} (%{value:.1f}d)",
            textposition="inside",
            sort=False
        )
        fig.update_layout(
            showlegend=True,
            legend_title_text="Absence type",
            margin=dict(l=10, r=10, t=40, b=10),
            title=dict(text=m, x=0.5, xanchor="center"),
        )
        st.plotly_chart(fig, use_container_width=True)

    if month_2:
        c1, sep2, c2 = st.columns([5, 0.25, 5])
        with c1:
            donut_for_month(month_1)
        with sep2:
            st.markdown('<div class="eg-vertical-divider-donut">&nbsp;</div>', unsafe_allow_html=True)
        with c2:
            donut_for_month(month_2)
    else:
        donut_for_month(month_1)

# =========================================================
# TAB 2: ORG + DEPT
# =========================================================
with tab_org_dept:
    st.markdown('<h3 class="eg-section-title">Organisation Filters</h3>', unsafe_allow_html=True)

    c_org, c_sub = st.columns(2)

    org_options = sorted(df_scope["Organisation"].dropna().unique().tolist()) if "Organisation" in df_scope.columns else []
    with c_org:
        selected_orgs = st.multiselect("Filter by organisation", options=org_options, default=[])

    df_org = df_scope.copy()
    if selected_orgs and "Organisation" in df_org.columns:
        df_org = df_org[df_org["Organisation"].isin(selected_orgs)]

    suborg_options = sorted(df_org["Suborganisation"].dropna().unique().tolist()) if "Suborganisation" in df_org.columns else []
    with c_sub:
        selected_suborgs = st.multiselect("Filter by suborganisation", options=suborg_options, default=[])

    df_orgsub = df_org.copy()
    if selected_suborgs and "Suborganisation" in df_orgsub.columns:
        df_orgsub = df_orgsub[df_orgsub["Suborganisation"].isin(selected_suborgs)]

    st.markdown("---")

    st.markdown('<h3 class="eg-section-title">Department Level Analysis</h3>', unsafe_allow_html=True)

    all_depts = sorted(df_orgsub["Team names"].dropna().unique().tolist()) if "Team names" in df_orgsub.columns else []
    selected_depts = st.multiselect("Filter by department", options=all_depts, default=[])

    df_dept = df_orgsub.copy()
    if selected_depts and "Team names" in df_dept.columns:
        df_dept = df_dept[df_dept["Team names"].isin(selected_depts)]

    dept_type = (
        df_dept.groupby(["month", "Team names", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )

    dept_list = sorted(df_dept["Team names"].dropna().unique().tolist())
    dept_grid = pd.MultiIndex.from_product(
        [months_in_scope, dept_list, TYPE_ORDER],
        names=["month", "Team names", "absence_category"]
    ).to_frame(index=False)

    dept_type = dept_grid.merge(dept_type, on=["month", "Team names", "absence_category"], how="left")
    dept_type[METRIC_COL] = dept_type[METRIC_COL].fillna(0)

    dept_totals = dept_type.groupby("Team names")[METRIC_COL].sum().sort_values(ascending=False)
    dept_type["Team names"] = pd.Categorical(dept_type["Team names"], categories=dept_totals.index, ordered=True)

    # Two charts + divider when comparing months
    if month_2:
        left, sep3, right = st.columns([5, 0.25, 5])

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
                legend_title_text="Absence type",
                title=dict(text=month_1, x=0.5),
                margin=dict(t=60),
            )
            fig_m1.update_xaxes(tickangle=-35)
            st.plotly_chart(fig_m1, use_container_width=True)

        with sep3:
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
                legend_title_text="Absence type",
                title=dict(text=month_2, x=0.5),
                margin=dict(t=60),
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
            legend_title_text="Absence type",
            title=dict(text=month_1, x=0.5),
            margin=dict(t=60),
        )
        fig_dept.update_xaxes(tickangle=-35)
        st.plotly_chart(fig_dept, use_container_width=True)


        
# =========================================================
# TAB 3: EMPLOYEE VIEW (Excel-style: Month -> Type subcolumns)
# - No slider
# - Totals are inside each month group (Total first)
# - Totals bold + shaded
# - Top header row (Month) prominent: bold, centered, colored
# - Vertical separators between month groups (Excel-like)
# - Dept/Name subtly shaded to "freeze" visually
# =========================================================
with tab_employee:
    st.markdown('<h3 class="eg-section-title">Employee View</h3>', unsafe_allow_html=True)
    st.caption("Excel-style view: Dept + Name, then Month columns with leave-type subcolumns.")

    # Build from df (NOT df_scope) so this view always includes ALL categories
    df_emp_base = df[df["month"].isin(months_in_scope)].copy()

    # ----------------------------
    # Filters inside Employee tab
    # ----------------------------
    org_options = sorted(df_emp_base["Organisation"].dropna().unique().tolist()) if "Organisation" in df_emp_base.columns else []
    selected_orgs_emp = st.multiselect("Filter by organisation", options=org_options, default=[], key="emp_org")
    if selected_orgs_emp and "Organisation" in df_emp_base.columns:
        df_emp_base = df_emp_base[df_emp_base["Organisation"].isin(selected_orgs_emp)]

    suborg_options = sorted(df_emp_base["Suborganisation"].dropna().unique().tolist()) if "Suborganisation" in df_emp_base.columns else []
    selected_suborgs_emp = st.multiselect("Filter by suborganisation", options=suborg_options, default=[], key="emp_suborg")
    if selected_suborgs_emp and "Suborganisation" in df_emp_base.columns:
        df_emp_base = df_emp_base[df_emp_base["Suborganisation"].isin(selected_suborgs_emp)]

    dept_options = sorted(df_emp_base["Team names"].dropna().unique().tolist()) if "Team names" in df_emp_base.columns else []
    selected_depts_emp = st.multiselect("Filter by department", options=dept_options, default=[], key="emp_dept")
    if selected_depts_emp and "Team names" in df_emp_base.columns:
        df_emp_base = df_emp_base[df_emp_base["Team names"].isin(selected_depts_emp)]

    if df_emp_base.empty:
        st.info("No employee records match the selected filters.")
        st.stop()

    show_totals = st.checkbox("Show totals", value=True)

    # ----------------------------
    # Create Excel-like table
    # Rows: Dept, Name
    # Columns: Month (top) -> Type (subcolumns)
    # ----------------------------
    emp_long = (
        df_emp_base.groupby(["Team names", "employee", "month", "absence_category"], dropna=False)[METRIC_COL]
        .sum()
        .reset_index()
    )

    emp_wide = emp_long.pivot_table(
        index=["Team names", "employee"],
        columns=["month", "absence_category"],
        values=METRIC_COL,
        fill_value=0,
        aggfunc="sum"
    )

    # Ensure consistent month/type ordering
    base_cols = pd.MultiIndex.from_product([months_in_scope, TYPE_ORDER], names=["month", "type"])
    emp_wide = emp_wide.reindex(columns=base_cols, fill_value=0)

    # Add totals and reorder so Total is FIRST under each month (Excel-like)
    if show_totals:
        month_total_cols = []
        for m in months_in_scope:
            emp_wide[(m, "Total")] = emp_wide.loc[:, (m, slice(None))].sum(axis=1)
            month_total_cols.append((m, "Total"))

        emp_wide[("All months", "Total")] = emp_wide.loc[:, month_total_cols].sum(axis=1)

        reordered = []
        for m in months_in_scope:
            reordered.append((m, "Total"))
            reordered.extend([(m, t) for t in TYPE_ORDER])
        reordered.append(("All months", "Total"))

        emp_wide = emp_wide.reindex(columns=pd.MultiIndex.from_tuples(reordered), fill_value=0)

    # Sort by overall total if present, else by sum of all visible numeric cells
    if show_totals and ("All months", "Total") in emp_wide.columns:
        emp_wide = emp_wide.sort_values(("All months", "Total"), ascending=False)
    else:
        emp_wide = emp_wide.assign(_tmp_total=emp_wide.sum(axis=1)).sort_values("_tmp_total", ascending=False).drop(columns=["_tmp_total"])

    # Reset index to get Dept/Name as columns
    emp_wide = emp_wide.reset_index()

    # Put Dept/Name under an "Employee" top header so the multi-header is consistent
    left_cols = pd.MultiIndex.from_tuples([("Employee", "Dept"), ("Employee", "Name")])
    right_cols = emp_wide.columns[2:]  # already MultiIndex
    emp_wide.columns = left_cols.append(right_cols)

    # Round numeric for readability
    numeric_cols = [c for c in emp_wide.columns if c not in list(left_cols)]
    emp_wide.loc[:, numeric_cols] = emp_wide.loc[:, numeric_cols].round(1)

    # ----------------------------
    # Styling
    # - Totals bold + shaded
    # - Prominent top header row (Month / Employee / All months)
    # - Vertical separators between month groups
    # - Shade Dept/Name columns lightly
    # ----------------------------
    months_sorted = months_in_scope[:]  # preserve chosen order
    total_cols = []
    if show_totals:
        total_cols = [(m, "Total") for m in months_sorted] + [("All months", "Total")]

    # Build month-boundary columns (add a right border after each month group)
    month_end_cols = []
    for m in months_sorted:
        # after the last subcolumn of the month group (Travel), or "Travel" if totals off
        if show_totals:
            month_end_cols.append((m, "Travel"))  # last type col
        else:
            month_end_cols.append((m, "Travel"))

    def style_cells(df_style: pd.DataFrame) -> pd.DataFrame:
        styles = pd.DataFrame("", index=df_style.index, columns=df_style.columns)

        # Shade Dept/Name columns (visual "freeze")
        if ("Employee", "Dept") in styles.columns:
            styles[("Employee", "Dept")] = "background-color: rgba(243,244,246,0.85); font-weight: 600;"
        if ("Employee", "Name") in styles.columns:
            styles[("Employee", "Name")] = "background-color: rgba(243,244,246,0.85); font-weight: 600;"

        # Bold + shade Total columns
        for col in total_cols:
            if col in styles.columns:
                styles[col] = "font-weight: 800; background-color: rgba(229,231,235,0.75);"

        # Vertical separators between month groups
        for col in month_end_cols:
            if col in styles.columns:
                # add a right border to visually separate months
                existing = styles[col]
                border = "border-right: 2px solid #e5e7eb;"
                styles[col] = (existing + " " + border).strip()

        # Also separate the identifier block from the months
        if ("Employee", "Name") in styles.columns:
            styles[("Employee", "Name")] = (styles[("Employee", "Name")] + " border-right: 2px solid #e5e7eb;").strip()

        return styles

    styled = (
        emp_wide.style
        .format(precision=1)
        .apply(style_cells, axis=None)
        .set_table_styles([
            # Top header row (Month / Employee / All months)
            {
                "selector": "th.col_heading.level0",
                "props": [
                    ("font-weight", "800"),
                    ("text-align", "center"),
                    ("background-color", "#eef2ff"),
                    ("border-bottom", "2px solid #c7d2fe"),
                    ("font-size", "13px"),
                ],
            },
            # Second header row (Type)
            {
                "selector": "th.col_heading.level1",
                "props": [
                    ("font-weight", "600"),
                    ("text-align", "center"),
                    ("background-color", "#f8fafc"),
                    ("font-size", "12px"),
                ],
            },
            # Body cells centered (numbers)
            {
                "selector": "td",
                "props": [
                    ("text-align", "center"),
                    ("white-space", "nowrap"),
                ],
            },
            # Slightly stronger borders for the whole table
            {
                "selector": "table",
                "props": [
                    ("border-collapse", "collapse"),
                ],
            },
        ])
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True
    )
