# archive

Archived/redundant files. The main project only needs: app, data ingestion pipeline, and cumulative sheet.

## Required by pipeline (do not remove)

- **blip_cleanup.py** — Called by `run_ingestion.py` for BLIP data cleanup and append to `blip_cumulative.csv`.

## Archived (reference only)

- **blip_cleanup_simple.py** — Simpler BLIP preprocessor (root had a duplicate; pipeline uses this folder's blip_cleanup.py).
- **blip_shift_anomaly_check.py** — Standalone anomaly check script.
- **misc/** — Old notebooks, Power BI docs, alternative app versions, sample data.
