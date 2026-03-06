"""
Single entry point: run ingestion (optional) then Excel build then views.
Produces one workbook with exactly 8 sheets (Leave and Time by Employee, Department, Country, Group).

Usage:
  python run_excel_pipeline.py [--input-folder PATH] [--out PATH]

  With --input-folder: run absence + BLIP cleanup from that folder, then build Excel from the refined outputs.
  Without: use default AbsenseReport_Cleaned_Final.csv and blip_cumulative.csv, then build Excel.

Output: Variance_Excel.xlsx (or --out path) with 8 sheets.
"""
import os
import sys
import subprocess

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(_PROJECT_ROOT, "Variance_Excel.xlsx")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Run ingestion (optional) then Excel build then views. Output: 8-sheet workbook."
    )
    parser.add_argument("--input-folder", "-i", help="Folder with raw absence + BLIP CSVs; run ingestion first")
    parser.add_argument("--out", "-o", default=DEFAULT_OUT, help=f"Output Excel path (default: {os.path.basename(DEFAULT_OUT)})")
    parser.add_argument("--entitlement", "-e", default=None, help="Holiday Summary Report (Excel/CSV) for leave entitlement")
    parser.add_argument("--wfh-allowance", type=float, default=9, help="WFH allowance days (default: 9)")
    parser.add_argument("--time-from", default=None, help="Time by Employee: first date YYYY-MM-DD (default: from data)")
    parser.add_argument("--time-to", default=None, help="Time by Employee: last date YYYY-MM-DD (default: from data)")
    args = parser.parse_args()

    # Default entitlement: annualLeave in Downloads if exists
    default_entitlement = os.path.expanduser(os.path.join("~", "Downloads", "annualLeave_Feb 26.csv"))
    entitlement_path = args.entitlement or (default_entitlement if os.path.isfile(default_entitlement) else None)

    absence_csv = os.path.join(_PROJECT_ROOT, "AbsenseReport_Cleaned_Final.csv")
    blip_path = os.path.join(_PROJECT_ROOT, "blip_cumulative.csv")

    if args.input_folder:
        sys.path.insert(0, _PROJECT_ROOT)
        from run_ingestion import _find_absence_and_blip_in_folder, run_absence, run_blip

        folder = os.path.abspath(args.input_folder)
        absence_in, blip_in, err = _find_absence_and_blip_in_folder(folder)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
        input_folder_norm = os.path.normpath(folder).rstrip(os.sep)
        base_name = os.path.basename(input_folder_norm)
        parent = os.path.dirname(input_folder_norm)
        output_folder = os.path.join(parent, base_name + "_output")
        os.makedirs(output_folder, exist_ok=True)
        absence_stem = os.path.splitext(os.path.basename(absence_in))[0]
        blip_stem = os.path.splitext(os.path.basename(blip_in))[0]
        absence_csv = os.path.join(output_folder, absence_stem + "_output.csv")
        blip_path = os.path.join(_PROJECT_ROOT, "blip_cumulative.csv")
        print("[1/3] Ingestion (absence + BLIP)...")
        if run_absence(absence_in, absence_csv) != 0:
            print("Absence cleanup failed.", file=sys.stderr)
            return 1
        if run_blip(blip_in, blip_path, append=True) != 0:
            print("BLIP cleanup failed.", file=sys.stderr)
            return 1
        print("Ingestion OK.")
        print()
    else:
        print("Using default refined CSVs (no ingestion).")
        print()

    out_path = os.path.abspath(args.out)
    if not out_path.lower().endswith(".xlsx"):
        out_path = out_path.rstrip(".xls") + ".xlsx"

    # Intermediate 6-sheet workbook: write to same path (views will overwrite with 8 sheets)
    build_cmd = [sys.executable, os.path.join(_PROJECT_ROOT, "build_dashboard_excel.py"), "--absence-csv", absence_csv, "--blip", blip_path, "--out", out_path, "--filter-from", "2026-01-01"]
    if entitlement_path:
        build_cmd.extend(["--entitlement", os.path.abspath(entitlement_path)])
    print("[2/3] Building Excel (Absence, BLIP, Employees, roll-ups)...")
    code = subprocess.run(build_cmd, cwd=_PROJECT_ROOT).returncode
    if code != 0:
        print("build_dashboard_excel failed.", file=sys.stderr)
        return code

    print("[3/3] Building 8-sheet views (Leave + Time by Employee, Department, Country, Group)...")
    views_cmd = [sys.executable, os.path.join(_PROJECT_ROOT, "build_dashboard_views.py"), "--input", out_path, "--output", out_path, "--wfh-allowance", str(args.wfh_allowance)]
    if args.time_from:
        views_cmd.extend(["--time-from", args.time_from])
    if args.time_to:
        views_cmd.extend(["--time-to", args.time_to])
    code = subprocess.run(views_cmd, cwd=_PROJECT_ROOT).returncode
    if code != 0:
        print("build_dashboard_views failed.", file=sys.stderr)
        return code

    print("-" * 40)
    print(f"Done. Workbook: {out_path} (8 sheets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
