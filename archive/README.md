# Archive

These files are **not required** to run the BrightHR & BLIP Dashboard. They are kept for reference or historical analysis.

| Contents | Description |
|----------|-------------|
| **CSVs** | Raw/alternate absence data, org mapping tables |
| **Excel** | BrightHR absence report (Nov–Dec) |
| **Power BI** | `PowerBI_Step_by_Step.md`, `PowerBI_Replication_Guide.md`, `PowerBI_Cleanup.ipynb` — archived; Power BI integration is not in active use |
| **Notebooks** | Analysis and cleaning (Jupyter) |
| **blip_integration/BlipAppNew.py** | Standalone BLIP script; logic is now in `app.py` |

To run the dashboard you only need, in the project root (or paths set in the app sidebar):

- `AbsenseReport_Cleaned_Final.csv` (Absence tab)
- BLIP Excel from the ingestion pipeline output
