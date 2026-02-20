# BrightHR & BLIP Dashboard

Streamlit app for Absence (BrightHR) and BLIP Utilisation dashboards in one place.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Tabs

- **Absence**: Individual (Daily Log), Department, Country, Group / ExCo — data and filters in the sidebar under **Controls**.
- **BLIP Utilisation**: Fifth tab — data source and date range in the sidebar under **BLIP Utilisation**.

## Data ingestion pipeline

No hardcoded paths — point to a folder each week; outputs go to `{foldername}_output` with files named `{inputsheet}_output`.

**Folder mode (recommended)**

Put both raw CSVs (absence + BLIP) in one folder, then run:

```bash
python run_ingestion.py --input-folder "path/to/week_12_feb"
```

- **Output folder:** `week_12_feb_output` (same parent as the input folder).
- **Absence:** `AbsenseReportRaw_output.csv` in that folder (full replace each run).
- **BLIP:** by default **appends** to the **cumulative sheet** `blip_cumulative.csv` in the project root (no overlap; missing data can be added). The app loads this same file by default.
- The script auto-detects which file is absence (filename contains "absence"/"absense") and which is BLIP ("blip"/"timesheet"). Override with `--absence-name` and `--blip-name` if needed.

Point the app (sidebar) to:
- **Absence CSV:** `path/to/week_12_feb_output/AbsenseReportRaw_output.csv`
- **BLIP:** `blip_cumulative.csv` in the project folder (default; no need to change if using folder mode).

**One-time: existing BLIP Excel**

If you already have a BLIP Excel file (e.g. from before), copy or convert it to `blip_cumulative.csv` in the project folder once. After that, every folder run will append new data to it (dedupe by person/date/type).

**BLIP: append vs replace**

- **Default (folder mode):** BLIP appends to `blip_cumulative.csv`; no overlap; missing rows can be added. Leave (absence) is always full replace per run.
- **Opt out of append:** use `--no-blip-append` or set `blip_append: false` in config; BLIP will be written to `{output_folder}/{blip_stem}_output.xlsx` instead.
- **Custom cumulative path:** set `blip_cumulative_path` in config or `--blip-cumulative-path`.

**Other options**

- Config file: set `input_folder` (or individual paths) in `ingestion_config.json`, then `python run_ingestion.py`.
- Individual paths: `--absence-in`, `--absence-out`, `--blip-in`, `--blip-out` (or via config).
- Run only one step: `--absence-only` or `--blip-only` (with folder or paths).

---

## Data

### Absence (BrightHR)

CSV with columns such as:

- Absence start date, Absence end date  
- First name, Last name  
- Team names  
- Absence type  
- Absence duration for period in days  
- Optional: Leave entitlement, Absence description (or Description, Reason, Notes)

Defaults to `AbsenseReport_Cleaned_Final.csv` in the project folder if present.

### BLIP Utilisation

Cumulative CSV (or Excel) with:

- Columns including: Clock In/Out Date, Clock In/Out Time, Blip Type (Shift / Break), Total Duration, Total Excluding Breaks

Defaults to `blip_cumulative.csv` in the project folder (same file preprocessing appends to). The app accepts Excel or CSV.

## Defaults

- **Absence CSV**: `AbsenseReport_Cleaned_Final.csv` in the project directory (or use **Upload Absence CSV** in the sidebar).
- **BLIP**: `blip_cumulative.csv` in the project directory (cumulative sheet; or use **Upload BLIP export** in the sidebar).
