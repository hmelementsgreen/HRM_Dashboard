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
