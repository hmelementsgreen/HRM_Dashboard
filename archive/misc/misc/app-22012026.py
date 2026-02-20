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

# --- keyword-based classification (Absence type + free-text details) ---
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

    # rule priority: WFH overrides everything if mentioned
    if _has_any(combined, WFH_KEYWORDS):
        return "WFH"
    if _has_any(combined, TRAVEL_KEYWORDS):
        return "Travel"
    if _has_any(combined, ANNUAL_KEYWORDS):
        return "Annual Leave"
    if _has_any(combined, SICK_KEYWORDS):
        return "Medical + Sickness"
    return "Other (excl. WFH, Travel)"

def parse_bright_hr_dt(s: pd.Series) -> pd.Series:
    """Parse BrightHR dates robustly (usually month-first)."""
    s = s.astype(str).str.strip().replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return pd.to_datetime(s, errors="coerce", dayfirst=False)

def expand_to_daily(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Expand each absence row into daily rows between start_dt and end_dt (inclusive).
    Keeps original duration column as recorded (audit trail).
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
            rows.append(rr)

    if not rows:
        return df_in.iloc[0:0].copy()

    return pd.DataFrame(rows)

def infer_country_from_team(team_series: pd.Series) -> pd.Series:
    """
    Country heuristic based on Team names.
    Default: UK (head office), unless explicitly tagged as DE/Germany.
    """
    t = team_series.fillna("").astype(str).str.upper()

    # Default to UK
    out = pd.Series(["UK"] * len(t), index=t.index)

    # Override when Germany is explicitly indicated
    out[t.str.contains(r"\bDE\b") | t.str.contains("GERM")] = "Germany"

    return out

@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # Dates
    df["start_dt"] = parse_bright_hr_dt(df.get("Absence start date", ""))
    df["end_dt"] = parse_bright_hr_dt(df.get("Absence end date", ""))

    df["start_date_uk"] = df["start_dt"].dt.strftime("%d/%m/%Y").fillna("")
    df["end_date_uk"] = df["end_dt"].dt.strftime("%d/%m/%Y").fillna("")
    df["month"] = df["start_dt"].dt.to_period("M").astype(str)

    # Ensure Team names exists (some exports might not have it)
    if "Team names" not in df.columns:
        df["Team names"] = ""

    # Absence category classification
    detail_col = next((c for c in DETAIL_COL_CANDIDATES if c in df.columns), None)
    if detail_col:
        df["absence_category"] = df.apply(
            lambda r: map_absence_type(r.get("Absence type", ""), r.get(detail_col, "")),
            axis=1
        )
    else:
        df["absence_category"] = df.get("Absence type", "").apply(lambda x: map_absence_type(x, ""))

    # Purpose / description for evidence trail
    df["purpose"] = df[detail_col].astype(str).str.strip() if detail_col else ""

    # Employee
    fn = df.get("First name", "").astype(str).str.strip()
    ln = df.get("Last name", "").astype(str).str.strip()
    df["employee"] = (fn + " " + ln).str.strip()

    # Metric
    df[METRIC_COL] = pd.to_numeric(df.get(METRIC_COL), errors="coerce").fillna(0)

    # Country
    if "Country" not in df.columns:
        df["Country"] = infer_country_from_team(df["Team names"])
    else:
        df["Country"] = df["Country"].fillna("").astype(str).str.strip()
        df["Country"] = df["Country"].replace({"Unknown": "UK", "": "UK"}).fillna("UK")

    # Final safety: anything still Unknown -> UK
    df["Country"] = df["Country"].replace({"Unknown": "UK"}).fillna("UK")

    return df

def fmt_num(x: float) -> str:
    return f"{x:,.1f}"

# ----------------------------
# Centered heading
# ----------------------------
st.markdown('<h1 class="eg-title">Absence Dashboard</h1>', unsafe_allow_html=True)
st.markdown(
    '<div class="eg-subtitle">Bottom-up flow: Individual → Department → Country → Group / ExCo</div>',
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

    # Default to Nov 2025 vs Dec 2025 (if both exist)
    preferred_m1 = "2025-11"
    preferred_m2 = "2025-12"

    if preferred_m1 in months_available:
        default_m1_index = months_available.index(preferred_m1)
    else:
        default_m1_index = max(len(months_available) - 2, 0)

    month_1 = st.selectbox("Select month", options=months_available, index=default_m1_index)

    add_second_month = st.checkbox("Add another month for comparison", value=True)
    if add_second_month:
        month_2_options = [m for m in months_available if m != month_1]
        if not month_2_options:
            month_2 = None
        else:
            if month_1 == preferred_m1 and preferred_m2 in month_2_options:
                default_m2_index = month_2_options.index(preferred_m2)
            else:
                default_m2_index = max(len(month_2_options) - 1, 0)

            month_2 = st.selectbox(
                "Select comparison month",
                options=month_2_options,
                index=default_m2_index
            )
    else:
        month_2 = None

    selected_cats = st.multiselect("Absence types (optional)", options=TYPE_ORDER, default=[])

months_in_scope = [month_1] + ([month_2] if month_2 else [])

# ----------------------------
# Scope data: month + (optional) absence type filter
# ----------------------------
df_scope = df[df["month"].isin(months_in_scope)].copy()
if selected_cats:
    df_scope = df_scope[df_scope["absence_category"].isin(selected_cats)]

# ----------------------------
# Tabs (bottom-up flow)
# ----------------------------
tab_individual, tab_department, tab_country, tab_group = st.tabs(
    ["Individual (Daily Log)", "Department", "Country", "Group / ExCo"]
)

# =========================================================
# TAB 1: INDIVIDUAL (DAILY LOG - evidence view)
# =========================================================
with tab_individual:
    st.markdown('<h3 class="eg-section-title">Individual Daily Log</h3>', unsafe_allow_html=True)
    st.caption("Evidence view: who, which day, what type, and the recorded purpose/description.")

    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        employee_search = st.text_input("Search employee (optional)", value="")
    with c2:
        reason_search = st.text_input("Search purpose/description (optional)", value="")
    with c3:
        min_dt = df_scope["start_dt"].min()
        max_dt = df_scope["start_dt"].max()
        if pd.isna(min_dt) or pd.isna(max_dt):
            date_range = None
            st.info("No valid dates found in the current scope.")
        else:
            date_range = st.date_input(
                "Filter date range (optional)",
                value=(min_dt.date(), max_dt.date())
            )

    daily = expand_to_daily(df_scope)

    # Apply date range
    if date_range and "date" in daily.columns:
        d1, d2 = date_range
        daily = daily[(daily["date"].dt.date >= d1) & (daily["date"].dt.date <= d2)]

    # Apply searches
    if employee_search.strip():
        daily = daily[daily["employee"].str.contains(employee_search.strip(), case=False, na=False)]
    if reason_search.strip():
        daily = daily[daily["purpose"].str.contains(reason_search.strip(), case=False, na=False)]

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
    cols_to_show = [c for c in cols_to_show if c in daily.columns]

    if daily.empty:
        st.info("No daily records match the selected filters.")
    else:
        daily_sorted = daily.sort_values(["date", "Team names", "employee"], ascending=[True, True, True])
        st.dataframe(daily_sorted[cols_to_show], use_container_width=True, hide_index=True)

        st.download_button(
            "Download daily log (CSV)",
            data=daily_sorted[cols_to_show].to_csv(index=False).encode("utf-8"),
            file_name="absence_daily_log.csv",
            mime="text/csv"
        )

# =========================================================
# TAB 2: DEPARTMENT (org/dept analysis + employee pivot as sub-tabs)
# =========================================================
with tab_department:
    st.markdown('<h3 class="eg-section-title">Department Views</h3>', unsafe_allow_html=True)

    subtab_dept, subtab_employee = st.tabs(["Department Summary", "Employee View"])

    # -------------------------
    # Department Summary (existing Org/Dept logic)
    # -------------------------
    with subtab_dept:
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

    # -------------------------
    # Employee View (existing Excel-style pivot)
    # -------------------------
    with subtab_employee:
        st.markdown('<h3 class="eg-section-title">Employee View</h3>', unsafe_allow_html=True)
        st.caption("Excel-style view: Dept + Name, then Month columns with leave-type subcolumns.")

        df_emp_base = df[df["month"].isin(months_in_scope)].copy()

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

        c1, c2, c3 = st.columns(3)
        with c1:
            show_totals = st.checkbox("Show totals", value=True, key="emp_totals")
        with c2:
            hide_zero_cols = st.checkbox("Hide all-zero columns", value=True, key="emp_hide_zero")
        with c3:
            heatmap = st.checkbox("Heatmap shading", value=True, key="emp_heatmap")

        emp_long = (
            df_emp_base
            .groupby(["Team names", "employee", "month", "absence_category"], dropna=False)[METRIC_COL]
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

        base_cols = pd.MultiIndex.from_product([months_in_scope, TYPE_ORDER], names=["month", "type"])
        emp_wide = emp_wide.reindex(columns=base_cols, fill_value=0)

        if show_totals:
            reordered = []
            for m in months_in_scope:
                emp_wide[(m, "Total")] = emp_wide.loc[:, (m, slice(None))].sum(axis=1)
                reordered.append((m, "Total"))
                reordered.extend([(m, t) for t in TYPE_ORDER])
            emp_wide = emp_wide.reindex(columns=pd.MultiIndex.from_tuples(reordered), fill_value=0)

        emp_wide = emp_wide.assign(_sort=emp_wide.sum(axis=1)).sort_values("_sort", ascending=False).drop(columns="_sort")

        emp_wide = emp_wide.reset_index()
        left_cols = pd.MultiIndex.from_tuples([("Employee", "Dept"), ("Employee", "Name")])
        emp_wide.columns = left_cols.append(emp_wide.columns[2:])

        num_cols = [c for c in emp_wide.columns if c not in left_cols]
        emp_wide[num_cols] = emp_wide[num_cols].round(1)

        if hide_zero_cols:
            keep = list(left_cols)
            non_zero = [c for c in emp_wide.columns if c not in keep and emp_wide[c].sum() != 0]
            emp_wide = emp_wide[keep + non_zero]

        months_sorted = months_in_scope[:]
        total_cols = [(m, "Total") for m in months_sorted if (m, "Total") in emp_wide.columns]

        month_end_cols = []
        for m in months_sorted:
            for candidate in ["Travel", "WFH", "Other (excl. WFH, Travel)", "Medical + Sickness", "Annual Leave", "Total"]:
                if (m, candidate) in emp_wide.columns:
                    month_end_cols.append((m, candidate))
                    break

        def style_cells(_):
            styles = pd.DataFrame("", index=emp_wide.index, columns=emp_wide.columns)

            for c in total_cols:
                styles[c] = "font-weight: 900; background-color: rgba(229,231,235,0.65);"

            for c in month_end_cols:
                styles[c] += " border-right: 2px solid #e5e7eb;"

            styles[("Employee", "Name")] += " border-right: 2px solid #e5e7eb;"
            return styles

        header_styles = [
            {
                "selector": "th.col_heading.level0",
                "props": [
                    ("font-weight", "900"),
                    ("text-align", "center"),
                    ("background-color", "#1f2937"),
                    ("color", "white"),
                    ("border-bottom", "2px solid #111827"),
                    ("font-size", "15px"),
                ],
            },
            {
                "selector": "th.col_heading.level1",
                "props": [
                    ("font-weight", "650"),
                    ("text-align", "center"),
                    ("background-color", "#f3f4f6"),
                    ("font-size", "12px"),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("text-align", "center"),
                    ("white-space", "nowrap"),
                ],
            },
            {
                "selector": "table",
                "props": [("border-collapse", "collapse")],
            },
        ]

        def style_level0_headers(v):
            out = []
            for label in v:
                if str(label) == "Employee":
                    out.append("background-color: #0f766e; color: white; font-weight: 900; text-align: center;")
                else:
                    out.append("background-color: #1f2937; color: white; font-weight: 900; text-align: center;")
            return out

        styled = (
            emp_wide.style
            .format(precision=1)
            .apply(style_cells, axis=None)
            .set_table_styles(header_styles)
            .apply_index(style_level0_headers, axis="columns", level=0)
        )

        if heatmap:
            exclude = set(left_cols) | set(total_cols)
            heat_cols = [c for c in emp_wide.columns if c not in exclude]
            if heat_cols:
                styled = styled.background_gradient(subset=heat_cols, axis=None)

        st.dataframe(styled, use_container_width=True, hide_index=True)

# =========================================================
# TAB 3: COUNTRY (KPIs + PIE + OPTIONAL COMPARISON + DRILLDOWN)
# =========================================================
with tab_country:
    st.markdown('<h3 class="eg-section-title">Country View</h3>', unsafe_allow_html=True)
    st.caption(
        "Country-level rollup with leave mix, a selected-country drilldown, "
        "and an optional country-to-country comparison."
    )

    if "Country" not in df_scope.columns:
        st.info("No Country field found in the dataset.")
        st.stop()

    # -------------------------------------------------
    # Primary country selector (BUTTONS)
    # -------------------------------------------------
    country_options = sorted(df_scope["Country"].dropna().unique().tolist())
    if not country_options:
        st.info("No country values found for the current scope.")
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
    df_country = df_scope[df_scope["Country"] == selected_country].copy()

    st.markdown("---")

    # -------------------------------------------------
    # Top KPIs (selected country)
    # -------------------------------------------------
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
            st.metric(
                f"{selected_country} days ({month_2})",
                fmt_num(total_days_m2),
                f"{diff:+.1f}d ({delta_str})"
            )
        else:
            st.metric("Departments", str(df_country["Team names"].nunique()))
    with k3:
        st.metric("Employees", str(df_country["employee"].nunique()))

    st.markdown("---")

    # -------------------------------------------------
    # PIE CHART: Leave mix (selected country)
    # -------------------------------------------------
    pie_country = (
        df_country.groupby(["month", "absence_category"])[METRIC_COL]
        .sum()
        .reset_index()
    )

    # Ensure consistent category order even when some are missing
    grid = pd.MultiIndex.from_product(
        [months_in_scope, TYPE_ORDER],
        names=["month", "absence_category"]
    ).to_frame(index=False)

    pie_country = grid.merge(
        pie_country,
        on=["month", "absence_category"],
        how="left"
    )
    pie_country[METRIC_COL] = pie_country[METRIC_COL].fillna(0)

    def pie_for_month(m: str):
        d = pie_country[pie_country["month"] == m].copy()
        d = d[d[METRIC_COL] > 0]

        if d.empty:
            st.info(f"No absence data for {selected_country} in {m}.")
            return

        fig = px.pie(
            d,
            names="absence_category",
            values=METRIC_COL,
            category_orders={"absence_category": TYPE_ORDER},
        )
        fig.update_traces(
            textinfo="percent+value",
            texttemplate="%{value:.1f}d (%{percent})",
            textposition="inside",
            sort=False
        )
        fig.update_layout(
            title=dict(text=f"{selected_country} • {m}", x=0.5),
            legend_title_text="Absence type",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    if month_2:
        c1, c2 = st.columns(2)
        with c1:
            pie_for_month(month_1)
        with c2:
            pie_for_month(month_2)
    else:
        pie_for_month(month_1)

    st.markdown("---")

    # -------------------------------------------------
    # OPTIONAL CROSS-COUNTRY COMPARISON (toggle + dropdown)
    # -------------------------------------------------
    st.markdown("**Cross-country comparison (optional)**")

    show_compare = st.checkbox("Enable cross-country comparison", value=False)

    if show_compare:
        compare_options = [c for c in country_options if c != selected_country]
        if not compare_options:
            st.info("No other countries available for comparison.")
        else:
            compare_country = st.selectbox(
                "Compare selected country with",
                options=compare_options
            )

            compare_df = df_scope[df_scope["Country"].isin([selected_country, compare_country])].copy()

            comp = (
                compare_df.groupby(["month", "Country", "absence_category"])[METRIC_COL]
                .sum()
                .reset_index()
            )

            fig = px.bar(
                comp[comp["month"] == month_1],
                x="Country",
                y=METRIC_COL,
                color="absence_category",
                category_orders={"absence_category": TYPE_ORDER},
            )
            fig.update_layout(
                barmode="stack",
                legend_title_text="Absence type",
                title=dict(text=f"{month_1} • {selected_country} vs {compare_country}", x=0.5),
                margin=dict(t=60),
            )
            st.plotly_chart(fig, use_container_width=True)

            if month_2:
                fig2 = px.bar(
                    comp[comp["month"] == month_2],
                    x="Country",
                    y=METRIC_COL,
                    color="absence_category",
                    category_orders={"absence_category": TYPE_ORDER},
                )
                fig2.update_layout(
                    barmode="stack",
                    legend_title_text="Absence type",
                    title=dict(text=f"{month_2} • {selected_country} vs {compare_country}", x=0.5),
                    margin=dict(t=60),
                )
                st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # -------------------------------------------------
    # DAILY DRILLDOWN (EVIDENCE VIEW) — selected country
    # -------------------------------------------------
    st.markdown("**Country drilldown (daily log)**")

    daily_country = expand_to_daily(df_country)

    drill_cols = [
        "date_uk",
        "Country",
        "Team names",
        "employee",
        "absence_category",
        METRIC_COL,
        "purpose",
    ]
    drill_cols = [c for c in drill_cols if c in daily_country.columns]

    if daily_country.empty:
        st.info("No daily records found for the selected country.")
    else:
        daily_country = daily_country.sort_values(["date", "Team names", "employee"])
        st.dataframe(daily_country[drill_cols], use_container_width=True, hide_index=True)

        st.download_button(
            "Download country drilldown (CSV)",
            data=daily_country[drill_cols].to_csv(index=False).encode("utf-8"),
            file_name=f"absence_daily_log_{selected_country}.csv",
            mime="text/csv"
        )

# =========================================================
# TAB 4: GROUP / EXCO (KPIs + Donuts)
# =========================================================
with tab_group:
    st.markdown('<h3 class="eg-section-title">Group / ExCo View</h3>', unsafe_allow_html=True)
    st.caption("Monthly KPIs and leave mix, suitable for senior leadership.")

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
