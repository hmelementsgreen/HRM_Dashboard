import pandas as pd
import streamlit as st
import plotly.express as px
import os

# ==============================================================================
# 1. CONFIGURATION & CONSTANTS
# ==============================================================================
st.set_page_config(page_title="BrightHR Absence Dashboard", layout="wide", page_icon="📊")

# --- 🟢 HARDCODED PATH SETTING 🟢 ---
# Update this path if the file location changes
CSV_PATH = r"C:\Users\HarshMalhotra\Documents\BrightHRData\AbsenseReport_Cleaned_Final.csv"

# Column Mappings (Map your CSV headers to internal names here)
COLS = {
    "start_date": "Absence start date",
    "end_date": "Absence end date",
    "type": "Absence type",
    "duration": "Absence duration for period in days",
    "team": "Team names",
    "employee_first": "First name",
    "employee_last": "Last name",
    "details": ["Absence description", "Description", "Reason", "Notes", "Absence notes"]
}

# Categorization Keywords
KEYWORDS = {
    "WFH": ["wfh", "work from home", "remote", "home working"],
    "Travel": ["travel", "business trip", "offsite", "client visit"],
    "Annual Leave": ["annual", "holiday", "vacation", "pto"],
    "Medical": ["sick", "sickness", "medical", "ill", "doctor", "injury"]
}

TYPE_ORDER = ["Annual Leave", "Medical", "Other", "WFH", "Travel"]

# Custom CSS for polished look
st.markdown("""
    <style>
        .block-container { padding-top: 2rem; }
        div[data-testid="stMetricValue"] { font-size: 1.6rem; }
        .stTabs [data-baseweb="tab-list"] { gap: 8px; }
        .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 4px; }
        .stTabs [aria-selected="true"] { background-color: #ffffff; border-bottom: 2px solid #ff4b4b; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. DATA LAYER (The Model)
# ==============================================================================

@st.cache_data(show_spinner="Loading data from local path...")
def load_and_clean_data(path) -> pd.DataFrame:
    """
    Reads the hardcoded CSV, handles parsing errors, and creates standard columns.
    """
    if not os.path.exists(path):
        st.error(f"❌ File not found at: {path}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception as e:
        st.error(f"❌ Error reading CSV: {e}")
        return pd.DataFrame()

    # 1. Find valid detail column
    detail_col = next((c for c in COLS["details"] if c in df.columns), None)
    
    # 2. Robust Date Parsing
    def parse_dt(s):
        s = s.astype(str).str.strip()
        # BrightHR usually uses UK format (Day/Month), fallback to others if needed
        return pd.to_datetime(s, dayfirst=True, errors='coerce')

    df["start_dt"] = parse_dt(df.get(COLS["start_date"], ""))
    df["end_dt"] = parse_dt(df.get(COLS["end_date"], ""))
    
    # Drop invalid rows
    df = df.dropna(subset=["start_dt"])
    
    # 3. Text cleaning
    df["month"] = df["start_dt"].dt.to_period("M").astype(str)
    
    # Employee Name
    fn = df.get(COLS["employee_first"], "").astype(str)
    ln = df.get(COLS["employee_last"], "").astype(str)
    df["employee"] = (fn + " " + ln).str.strip().str.title()
    
    # 4. Categorization Logic
    def classify_absence(row):
        raw_type = str(row.get(COLS["type"], "")).lower()
        details = str(row.get(detail_col, "")).lower() if detail_col else ""
        text = f"{raw_type} {details}"
        
        for category, tags in KEYWORDS.items():
            if any(tag in text for tag in tags):
                return category
        return "Other"

    df["absence_category"] = df.apply(classify_absence, axis=1)
    
    # 5. Country Inference
    def get_country(team_name):
        team_name = str(team_name).upper()
        if "DE" in team_name or "GERMANY" in team_name or "BERLIN" in team_name:
            return "Germany"
        return "UK" # Default
        
    if "Country" not in df.columns:
        df["Country"] = df[COLS["team"]].apply(get_country)
    else:
        df["Country"] = df["Country"].fillna("UK")

    return df

@st.cache_data
def expand_to_daily_filtered(df: pd.DataFrame, months: list) -> pd.DataFrame:
    """
    Optimization: Only expands rows relevant to the selected months.
    """
    if df.empty: return df
    
    # Pre-filter to reduce loop size
    df_subset = df[df["month"].isin(months)].copy()
    
    rows = []
    for _, row in df_subset.iterrows():
        s = row["start_dt"]
        e = row["end_dt"]
        if pd.isna(e) or e < s: e = s
        
        # Create a row for every day
        for day in pd.date_range(s, e):
            new_row = row.copy()
            new_row["date_daily"] = day
            new_row["month_daily"] = day.strftime("%Y-%m")
            rows.append(new_row)
            
    return pd.DataFrame(rows)

# ==============================================================================
# 3. THE CONTROLLER (Sidebar & Inputs)
# ==============================================================================

# Load Data Immediately
df_raw = load_and_clean_data(CSV_PATH)

if df_raw.empty:
    st.warning("No data loaded. Please check the file path in the code.")
    st.stop()

st.title("📊 Absence Analytics Dashboard")
st.markdown("---")

with st.sidebar:
    st.header("Filters")
    available_months = sorted(df_raw["month"].unique().tolist(), reverse=True)
    
    # Default to latest month
    default_idx = 0 if available_months else 0
    selected_month = st.selectbox("Primary Month", available_months, index=default_idx)
    
    # Optional Comparison
    compare_month = st.selectbox("Compare with (Optional)", ["None"] + available_months, index=0)
    
    # Filter Logic
    months_in_scope = [selected_month]
    if compare_month != "None" and compare_month != selected_month:
        months_in_scope.append(compare_month)
        
    # Department Filter
    all_depts = sorted(df_raw[COLS["team"]].dropna().unique().tolist())
    selected_depts = st.multiselect("Filter Departments", all_depts)
    
    # Apply Filters to Main DataFrame
    df_scope = df_raw[df_raw["month"].isin(months_in_scope)]
    if selected_depts:
        df_scope = df_scope[df_scope[COLS["team"]].isin(selected_depts)]

# ==============================================================================
# 4. THE VIEW (Visualization)
# ==============================================================================

# Create tabs
tab1, tab2, tab3 = st.tabs(["📈 Executive Overview", "🏢 Department Breakdown", "📅 Daily Logs"])

# --- TAB 1: EXECUTIVE OVERVIEW ---
with tab1:
    st.subheader("High-Level KPIs")
    
    # Calculate Metrics
    current_days = df_scope[df_scope["month"] == selected_month][COLS["duration"]].sum()
    
    delta = None
    if compare_month != "None":
        prev_days = df_scope[df_scope["month"] == compare_month][COLS["duration"]].sum()
        diff = current_days - prev_days
        delta = f"{diff:+.1f} days vs {compare_month}"

    # KPI Cards
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(f"Total Absence Days ({selected_month})", f"{current_days:,.1f}", delta=delta)
    k2.metric("Total Employees Affected", df_scope[df_scope["month"] == selected_month]["employee"].nunique())
    
    if not df_scope.empty:
        mode_val = df_scope[df_scope["month"] == selected_month]["absence_category"].mode()
        top_reason = mode_val[0] if not mode_val.empty else "N/A"
    else:
        top_reason = "N/A"
        
    k3.metric("Most Common Reason", top_reason)
    k4.metric("Active Departments", df_scope[df_scope["month"] == selected_month][COLS["team"]].nunique())

    st.markdown("### Absence Mix")
    c1, c2 = st.columns([1, 1])
    
    with c1:
        # Donut Chart
        fig_donut = px.pie(
            df_scope[df_scope["month"] == selected_month], 
            values=COLS["duration"], 
            names="absence_category",
            hole=0.4,
            title=f"Leave Distribution - {selected_month}",
            category_orders={"absence_category": TYPE_ORDER}
        )
        st.plotly_chart(fig_donut, use_container_width=True)
        
    with c2:
        # Trend / Comparison Bar
        if compare_month != "None":
            comp_data = df_scope.groupby(["month", "absence_category"])[COLS["duration"]].sum().reset_index()
            fig_bar = px.bar(
                comp_data, 
                x="absence_category", 
                y=COLS["duration"], 
                color="month", 
                barmode="group",
                title=f"Comparison: {selected_month} vs {compare_month}"
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Select a comparison month in the sidebar to see trend analysis.")

# --- TAB 2: DEPARTMENT BREAKDOWN ---
with tab2:
    st.subheader("Departmental Analysis")
    
    if df_scope.empty:
        st.info("No data available for the selected filters.")
    else:
        # Prepare Pivot Data
        dept_pivot = df_scope[df_scope["month"] == selected_month].groupby(
            [COLS["team"], "absence_category"]
        )[COLS["duration"]].sum().reset_index()
        
        if dept_pivot.empty:
             st.info("No data to plot.")
        else:
            # Stacked Bar Chart
            fig_dept = px.bar(
                dept_pivot,
                x=COLS["team"],
                y=COLS["duration"],
                color="absence_category",
                title=f"Days Lost by Department ({selected_month})",
                category_orders={"absence_category": TYPE_ORDER},
                height=500
            )
            st.plotly_chart(fig_dept, use_container_width=True)
            
            # Heatmap Table
            st.markdown("#### Detailed View")
            st.dataframe(
                dept_pivot.pivot(index=COLS["team"], columns="absence_category", values=COLS["duration"])
                .fillna(0)
                .style.background_gradient(cmap="Reds", axis=None)
                .format("{:.1f}"),
                use_container_width=True
            )

# --- TAB 3: DAILY LOGS (Drill-Down) ---
with tab3:
    st.subheader("Daily Evidence Log")
    st.caption("Detailed view of every absence expanded by day.")
    
    # Only run the expensive expansion here
    daily_df = expand_to_daily_filtered(df_scope, months_in_scope)
    
    # Search box
    search_term = st.text_input("Search Employee or Reason", "")
    
    if not daily_df.empty:
        if search_term:
            daily_df = daily_df[
                daily_df["employee"].str.contains(search_term, case=False) | 
                daily_df["absence_category"].str.contains(search_term, case=False)
            ]
            
        display_cols = ["date_daily", "employee", COLS["team"], "absence_category", "Country", COLS["duration"]]
        
        # Ensure only existing columns are displayed
        valid_cols = [c for c in display_cols if c in daily_df.columns]
        
        st.dataframe(daily_df[valid_cols].sort_values("date_daily"), use_container_width=True, hide_index=True)
        
        st.download_button(
            "📥 Download Filtered Data",
            daily_df.to_csv(index=False).encode('utf-8'),
            "absence_data.csv",
            "text/csv"
        )
    else:
        st.warning("No data found for the selected filters.")