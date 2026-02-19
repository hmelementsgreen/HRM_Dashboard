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
- **Output files:** `AbsenseReportRaw_output.csv`, `blipTimesheet_output.xlsx` (input filename stem + `_output`).
- The script auto-detects which file is absence (filename contains "absence"/"absense") and which is BLIP ("blip"/"timesheet"). Override with `--absence-name` and `--blip-name` if needed.

Then point the app (sidebar) to the output folder:
- **Absence CSV:** `path/to/week_12_feb_output/AbsenseReportRaw_output.csv`
- **BLIP Excel:** `path/to/week_12_feb_output/blipTimesheet_output.xlsx`

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

Excel export with:

- First row as a note (app reads with `skiprows=1`)
- Columns including: Clock In/Out Date, Clock In/Out Time, Blip Type (Shift / Break), Total Duration, Total Excluding Breaks

Defaults to `blip_integration/Blip_27_28.xlsx` in the project folder if present.

## Defaults

- **Absence CSV**: `AbsenseReport_Cleaned_Final.csv` in the project directory (or use **Upload Absence CSV** in the sidebar).
- **BLIP Excel**: `blip_integration/Blip_27_28.xlsx` in the project directory (or use **Upload BLIP export** in the sidebar).
