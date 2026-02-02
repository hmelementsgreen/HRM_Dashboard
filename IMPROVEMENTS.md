# App structure and areas of improvement

## What was done

- **BLIP integration**: BLIP Utilisation is integrated as the **fifth tab** in `app.py`. One app, one flow, no mode selector. Entry point: `streamlit run app.py`.
- **Unified styling**: Shared CSS (e.g. `.eg-title`, `.eg-subtitle`, `.eg-hint`, `.eg-card`) and page title **BrightHR & BLIP Dashboard**.
- **Portable defaults**: Absence CSV defaults to `AbsenseReport_Cleaned_Final.csv` in the project directory; BLIP Excel defaults to `blip_integration/Blip_27_28.xlsx` (via `_APP_DIR`). Both work on any machine.
- **Absence load**: Try/except around Absence CSV load with user-friendly error message.
- **Absence file upload**: Sidebar supports **Upload Absence CSV** or CSV path; behaviour unchanged otherwise.
- **BLIP exports**: BLIP tab has CSV downloads (shift-level table, weekly utilisation, monthly hours).
- **BLIP sidebar**: BLIP Utilisation section in the sidebar is in an expander (collapsed by default).
- **Dependencies**: `requirements.txt` (pandas, streamlit, plotly, openpyxl). **README.md** with run instructions and data formats.

---

## Overall structure (current)

```
app.py
├── Imports + page config + shared CSS
├── Absence constants + BLIP constants + BLIP helpers/load/segment logic
├── Absence helpers (_process_absence_df, load_data, load_data_from_upload, expand_to_daily, filters, balance, rollup, etc.)
├── Shared heading (BrightHR & BLIP Dashboard)
├── Sidebar: Controls (Absence: upload or path, months, filters, Export Center) + BLIP Utilisation (expander: upload/path, date range, thresholds)
└── Five tabs: Individual (Daily Log), Department, Country, Group / ExCo, BLIP Utilisation
```

---

## Areas of improvement

### 1. **Modularity (optional refactor)**

- **app.py** is large (~1,900+ lines). Consider splitting into modules, e.g.:
  - `absence_data.py` – load_data, expand_to_daily, parse dates, map_absence_type, make_case_id, infer_country
  - `absence_balance.py` – compute_annual_employee_balance, rollup_balance, weekly_summary
  - `blip_data.py` – BLIP load/process, segment building
  - `blip_ui.py` – BLIP KPIs and charts (or keep in app.py behind `if dashboard_mode == "BLIP"`)
- Keep **app.py** as the single Streamlit script that imports these and renders sidebar + tabs.

### 2. **Config**

- **Paths**: CSV and BLIP Excel paths are hardcoded/defaulted. Options:
  - Environment variables (e.g. `ABSENCE_CSV_PATH`, `BLIP_XLSX_PATH`).
  - A small `config.py` or `config.toml` read at startup.
- **Expected hours / thresholds**: BLIP expected daily hours and short/long shift thresholds could also come from config or env.

### 3. **Error handling and validation**

- Absence: validate CSV path and required columns before running the rest of the pipeline.
- BLIP: validate Excel structure (e.g. expected columns after `skiprows=1`) and show a clear message if the file is not a BLIP export.
- Wrap file load in try/except and show user-friendly errors (already partly done for BLIP).

### 4. **Data sources**

- **Absence**: File upload and CSV path both supported in the sidebar.
- **BLIP**: Upload and path supported; default path is `blip_integration/Blip_27_28.xlsx` (portable).

### 5. **Caching**

- Absence: `@st.cache_data` on `load_data` and `build_daily_for_months` is good; consider cache TTL or a “Reload data” button when the CSV changes.
- BLIP: `_blip_load_data` is cached by path; uploads are not cached (intended). If you add a “last used path” memory, consider clearing cache when path changes.

### 6. **UI/UX**

- **Absence**: Optional “dark mode” or theme switch; already using consistent `.eg-*` classes.
- **BLIP**: Date range is in the sidebar; consider a short hint in the main area that “Date range is in the sidebar” on first visit.
- **Accessibility**: Ensure contrast and labels for charts/tables meet your org’s standards.

### 7. **Exports**

- **Absence**: Export Center provides filtered daily log, weekly summaries, weekly drilldown, monthly ExCo CSV.
- **BLIP**: Exports added (shift-level table, weekly utilisation, monthly hours CSVs).

### 8. **Testing**

- Add unit tests for:
  - `map_absence_type`, `parse_bright_hr_dt_two_pass`, `infer_country_from_team`, `make_case_id`
  - `expand_to_daily` (e.g. single-day and multi-day absence)
  - `_blip_process_raw_df` with a minimal Excel/DataFrame
  - `compute_annual_employee_balance` and `rollup_balance` with small fixtures
- Run with sample CSV and BLIP Excel in CI or a “test mode” to avoid regressions.

### 9. **blip_integration folder**

- **Blip_27_28.xlsx**: Keep in `blip_integration/`; app defaults to it.
- **BlipAppNew.py**: Moved to `archive/blip_integration/` (logic is in app.py; kept for reference).
### 10. **Documentation**

- **README.md**: Added (run instructions, tabs, data formats, defaults).
- **IMPROVEMENTS.md**: This file; update as you implement items above.

---

## Quick wins (done)

1. **File upload for Absence CSV** in the sidebar.
2. **BLIP exports** (shift table, weekly utilisation, monthly hours CSVs).
3. **README.md** with run instructions and data format notes.
4. **Portable defaults** for Absence CSV and BLIP Excel.
5. **BLIP sidebar** in expander (collapsed by default).

## Quick wins (optional next)

- ~~Move **BlipAppNew.py** to `archive/blip_integration/`~~ Done: now in `archive/blip_integration/`.
