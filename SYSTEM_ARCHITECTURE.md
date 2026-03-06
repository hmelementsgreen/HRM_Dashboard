# BrightHR Data Pipeline — System Architecture

## Overview

This pipeline takes two raw CSV exports from BrightHR (Absence Report + BLIP Timesheet), processes and cleans them, and produces a single Excel workbook (`Variance_Excel.xlsx`) with 9 dashboard sheets covering leave management and time utilisation.

---

## Input Files

| File | Source | Description |
|---|---|---|
| Absence Report CSV | BrightHR | Raw leave/absence data (sick, annual, WFH, etc.) |
| BLIP Timesheet CSV | BrightHR | Raw clock-in/clock-out time data |
| Holiday Summary CSV | BrightHR (optional) | Annual leave entitlement per employee (including carry-over) |

Place both raw files in a dated folder (e.g. `4th_March_2026/`).

---

## Pipeline Steps

### Step 1 — Ingestion (`run_ingestion.py`)

Auto-detects files inside the input folder by filename keywords (`absence`/`absense` and `blip`/`timesheet`).

#### Absence Cleanup (`absence_cleanup.py`)

- Parses the raw BrightHR absence export
- Normalises employee names
- Maps leave types to standard categories (Annual Leave, WFH, Medical + Sickness, External Assignments, Other)
- Calculates absence duration in days
- **Output:** `AbsenseReport_Cleaned_Final.csv` (full replace each run)

#### BLIP Cleanup (`archive/blip_cleanup.py`)

- Normalises column headers
- Groups multiple shift/break rows per person per day (earliest clock-in, latest clock-out)
- Fixes:
  - **Late clock-in (>10:30):** replaced with random time between 09:00–10:00
  - **Cross-day shifts:** clock-out capped to random 17:25–17:45 on the same day
  - **Missing clock-out:** random 17:25–17:45
  - **Missing/invalid breaks:** synthetic 30–45 minute lunch added
  - **Under minimum work (7h30):** clock-out extended
- Generates WFH rows for weekdays with no BLIP data (09:00–17:00, 8h)
- **Output:** `blip_cumulative.csv` (append mode — new data is added; duplicates are removed by person + date + type)

---

### Step 2 — Build Base Workbook (`build_dashboard_excel.py`)

Reads the cleaned CSVs and constructs an intermediate Excel workbook.

#### BLIP Preprocessing (`blip_preprocess.py`)

Applied when loading `blip_cumulative.csv`:

| Fix | Detail |
|---|---|
| Overnight shifts | Adds 1 day to clock-out if it's earlier than clock-in |
| Negative durations | Recalculates from corrected clock-in/out |
| Late clock-in (>10:30) | Replaced with random 09:00–10:00 |
| Cross-day or >12h shifts | Clock-out capped to random 17:25–17:45 same day |
| Fully remote employees | Excluded from all BLIP data |

#### Holiday Summary Loading (`holiday_summary_loader.py`)

- Loads "Holiday Entitlement (including Carry Over)" per employee
- Filters out metadata rows (Company, Report headers)
- Excludes specific non-employees (Dilara Kamphuis, Toby Roberts)

#### Employee Summary (`build_employee_summary()`)

- Merges employees from Absence + BLIP + Entitlement sources
- Deduplicates by **First + Last name** only (handles middle name variations)
- Maps Team, Country, Group per employee
- Calculates leave taken by type and total worked hours

#### Intermediate Sheets Written

| Sheet | Content |
|---|---|
| Absence | Cleaned absence rows (filtered to Jan 1, 2026+) |
| BLIP | Processed BLIP rows (remote employees excluded) |
| Employees | One row per employee with all metrics |
| By Department | Aggregated totals per department |
| By Country | Aggregated totals per country |
| By Group | Aggregated totals per group |

---

### Step 3 — Build 9 View Sheets (`build_dashboard_views.py`)

Reads the intermediate workbook and overwrites it with 9 formatted dashboard sheets.

#### Leave Sheets (4)

| # | Sheet | Content |
|---|---|---|
| 1 | Leave by Employee | Per-employee: Annual Leave (Allowance, Taken, % YTD, Remaining), WFH (Allowance, Taken, Variance), Medical/Sick, External, Other |
| 3 | Leave by Department | Same metrics aggregated by department |
| 5 | Leave by Country | Same metrics aggregated by country |
| 7 | Leave by Group | Same metrics aggregated by group |

#### WFH Allowance Overrides

| Category | Employees | Allowance |
|---|---|---|
| Fully remote (0) | Albano Limas, John Hetherton, Elizabeth Kinnear-Mellor, Jamie Rixton, Ryan Holland | 0 days |
| Special (2/week) | Otto Carlisle | 18 days (2 × 9 weeks) |
| Special (3/week) | Mark Turner, Elias, Fabian, William Betts | 27 days (3 × 9 weeks) |
| Default (1/week) | Everyone else | 9 days |

#### Time Sheets (4 + 1 summary)

| # | Sheet | Content |
|---|---|---|
| 2 | Time by Employee | Continuous calendar with In/Out/Break/Var per employee per day |
| 4 | Time by Department | Aggregated time metrics by department |
| 6 | Time by Country | Aggregated time metrics by country |
| 8 | Time by Group | Aggregated time metrics by group |
| 9 | Time Summary | Per employee: Current Week hrs/%, MTD hrs/%, YTD hrs/% |

#### Time by Employee — Special Rules

| Scenario | In | Out | Break | Var |
|---|---|---|---|---|
| Normal working day | Clock-in time | Clock-out time | Break hours | (Out − In − Break) − 7.5h |
| Weekend / Bank Holiday | Blank | Blank | Blank | Blank |
| Sick Leave (Medical + Sickness) | "no show" | "no show" | Blank | Blank (not in sums) |
| Annual Leave / Holiday | Blank | Blank | Blank | 0 (included in sums) |

#### Subtotal Rows

- **Weekly Cumulative** — inserted after every Sunday
- **Monthly Cumulative** — inserted after last day of each month (January, February, etc.)
- **YTD Cumulative Variation** — final row summing the entire period

#### Conditional Formatting

4-step green/red gradient on all Var cells (including subtotals): positive = green, negative = red, zero = neutral grey.

---

## Output

**`Variance_Excel.xlsx`** — 9-sheet workbook ready for review.

---

## Running the Pipeline

### Full run (with new raw files)

```bash
python run_excel_pipeline.py -i "4th_March_2026" --time-from 2026-01-01 --time-to 2026-03-04
```

### Rebuild only (no new raw files)

```bash
python run_excel_pipeline.py --time-from 2026-01-01 --time-to 2026-03-04
```

### Key CLI Arguments

| Argument | Description | Default |
|---|---|---|
| `-i` / `--input-folder` | Folder with raw CSVs; triggers ingestion | None (skip ingestion) |
| `-o` / `--out` | Output Excel path | `Variance_Excel.xlsx` |
| `-e` / `--entitlement` | Holiday Summary CSV/Excel for entitlement | Auto-detect in Downloads |
| `--time-from` | Start date for Time by Employee calendar | Derived from data |
| `--time-to` | End date for Time by Employee calendar | Derived from data |
| `--wfh-allowance` | Default WFH allowance days | 9 |

---

## SOP — When New Data Arrives

1. Download the 2 raw files from BrightHR (Absence Report + BLIP Timesheet)
2. Create a new dated folder in the project root (e.g. `20th_March_2026/`)
3. Place both CSVs in that folder
4. Run:
   ```bash
   python run_excel_pipeline.py -i "20th_March_2026" --time-from 2026-01-01 --time-to 2026-03-20
   ```
5. Open `Variance_Excel.xlsx` to review
6. Move the raw input folder to `archive/raw_input_folders/` when done

---

## File Structure

```
BrightHRData/
├── absence_cleanup.py          # Absence data preprocessor
├── absence_daily.py            # Absence daily expansion + helpers
├── AbsenseReport_Cleaned_Final.csv  # Current cleaned absence data
├── blip_cumulative.csv         # Cumulative BLIP time data
├── blip_preprocess.py          # BLIP preprocessor (runtime fixes)
├── build_dashboard_excel.py    # Builds base Excel workbook
├── build_dashboard_views.py    # Builds 9-sheet dashboard views
├── holiday_summary_loader.py   # Holiday entitlement loader
├── run_excel_pipeline.py       # Main pipeline entry point
├── run_ingestion.py            # Data ingestion orchestrator
├── ingestion_config.example.json
├── requirements.txt
├── README.md
├── Variance_Excel.xlsx         # Latest output
└── archive/                    # Old files, raw inputs, misc
    ├── blip_cleanup.py         # BLIP ingestion-time cleaner
    ├── old_excel_outputs/
    ├── old_apps/
    ├── raw_input_folders/
    └── misc/
```

---

## Data Corrections Summary

| Stage | Fix | Script |
|---|---|---|
| Ingestion | Late clock-in >10:30 → random 09:00–10:00 | `blip_cleanup.py` |
| Ingestion | Cross-day shift → cap to 17:25–17:45 | `blip_cleanup.py` |
| Ingestion | Missing clock-out → random 17:25–17:45 | `blip_cleanup.py` |
| Ingestion | Missing/bad breaks → synthetic 30–45 min | `blip_cleanup.py` |
| Ingestion | Under min work (7h30) → extend clock-out | `blip_cleanup.py` |
| Build | Overnight shifts → add 1 day to clock-out | `blip_preprocess.py` |
| Build | Late clock-in >10:30 → random 09:00–10:00 | `blip_preprocess.py` |
| Build | Cross-day / >12h duration → cap at 17:25–17:45 | `blip_preprocess.py` |
| Build | Exclude remote employees from BLIP | `build_dashboard_excel.py` |
| Build | Exclude non-employees & specific people | `holiday_summary_loader.py` |
| Build | Deduplicate by First+Last name | `build_dashboard_excel.py` |
| Views | Absence status rules (sick/holiday/weekend) | `build_dashboard_views.py` |
