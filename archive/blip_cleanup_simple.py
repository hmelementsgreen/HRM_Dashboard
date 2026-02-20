#!/usr/bin/env python
"""
BLIP pre-processing CLI: apply anomaly fixes and write cleaned CSV/Excel.
Usage: python blip_cleanup.py input.csv output.csv
       python blip_cleanup.py raw_blip.xlsx blip_cumulative.csv
"""
import argparse
import sys
import pandas as pd
from blip_preprocess import process_blip_df

def main():
    p = argparse.ArgumentParser(description='Apply BLIP anomaly fixes and output cleaned file')
    p.add_argument('input', help='Raw BLIP export (CSV or Excel)')
    p.add_argument('output', help='Output file path (CSV or Excel)')
    args = p.parse_args()
    path = args.input.strip().lower()
    if path.endswith('.csv'):
        peek = pd.read_csv(args.input, nrows=1)
        skip = 1 if 'First Name' not in peek.columns and 'Clock In Date' not in peek.columns else 0
        raw = pd.read_csv(args.input, skiprows=skip)
    else:
        raw = pd.read_excel(args.input, skiprows=1, engine='openpyxl')
    df = process_blip_df(raw, update_source_for_export=True)
    export_cols = [c for c in raw.columns if c in df.columns]
    out_df = df[export_cols].copy()
    out_path = args.output.strip().lower()
    if out_path.endswith('.csv'):
        out_df.to_csv(args.output, index=False)
    else:
        out_df.to_excel(args.output, index=False, engine='openpyxl')
    print(f'Wrote {args.output} ({len(out_df)} rows)')
    return 0

if __name__ == '__main__':
    sys.exit(main() or 0)
