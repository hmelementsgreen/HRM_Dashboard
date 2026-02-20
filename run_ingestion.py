"""
Data ingestion pipeline: run both preprocessing scripts in order.

Folder mode (recommended for weekly runs):
  Point to a folder containing both raw CSVs (absence + BLIP).

  python run_ingestion.py --input-folder "path/to/week_12_feb"

  - Absence: full replace -> {foldername}_output/{absence_stem}_output.csv
  - BLIP: by default appends to blip_cumulative.csv in project root (no overlap; missing data can be added).
    The app loads this same file. Use --no-blip-append to write BLIP to output folder instead.
  - Input folder must contain two CSVs: one absence, one BLIP (auto-detected by name). Override with --absence-name, --blip-name.

Alternative: pass individual paths or use ingestion_config.json (see --help).
"""
import sys
import os
import json
import subprocess
import argparse

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "ingestion_config.json")


def _find_absence_and_blip_in_folder(folder: str, absence_name: str = None, blip_name: str = None):
    """
    Find one absence CSV and one BLIP CSV in folder.
    Returns (absence_path, blip_path) or (None, None) with error message.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return None, None, f"Not a directory: {folder}"

    all_files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    csv_files = [f for f in all_files if f.lower().endswith(".csv")]

    if absence_name:
        ap = os.path.join(folder, absence_name)
        if not os.path.isfile(ap):
            return None, None, f"Absence file not found: {ap}"
        absence_path = ap
    else:
        absence_candidates = [f for f in csv_files if "absence" in f.lower() or "absense" in f.lower()]
        if len(absence_candidates) == 0:
            return None, None, f"No absence CSV found in {folder} (expected filename containing 'absence' or 'absense'). Use --absence-name."
        if len(absence_candidates) > 1:
            return None, None, f"Multiple absence CSVs found: {absence_candidates}. Use --absence-name to pick one."
        absence_path = os.path.join(folder, absence_candidates[0])

    if blip_name:
        bp = os.path.join(folder, blip_name)
        if not os.path.isfile(bp):
            return None, None, f"BLIP file not found: {bp}"
        blip_path = bp
    else:
        blip_candidates = [f for f in csv_files if "blip" in f.lower() or "timesheet" in f.lower()]
        if len(blip_candidates) == 0:
            return None, None, f"No BLIP CSV found in {folder} (expected filename containing 'blip' or 'timesheet'). Use --blip-name."
        if len(blip_candidates) > 1:
            return None, None, f"Multiple BLIP CSVs found: {blip_candidates}. Use --blip-name to pick one."
        blip_path = os.path.join(folder, blip_candidates[0])

    return absence_path, blip_path, None


def run_absence(absence_in: str, absence_out: str) -> int:
    """Run absence cleanup."""
    sys.path.insert(0, _PROJECT_ROOT)
    import absence_cleanup
    return absence_cleanup.run(absence_in, absence_out)


def run_blip(blip_in: str, blip_out: str, append: bool = False) -> int:
    """Run BLIP cleanup. If append=True, new data is appended to blip_out (must be .csv)."""
    blip_script = os.path.join(_PROJECT_ROOT, "archive", "blip_cleanup.py")
    if not os.path.exists(blip_script):
        print(f"Error: BLIP script not found: {blip_script}", file=sys.stderr)
        return 1
    cmd = [sys.executable, blip_script, "--input", blip_in, "--output", blip_out]
    if append:
        cmd.append("--append")
    result = subprocess.run(cmd, cwd=_PROJECT_ROOT)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Run data ingestion: absence + BLIP preprocessing. Use --input-folder for weekly folder, or pass individual paths."
    )
    parser.add_argument("--input-folder", "-i", help="Folder containing both raw CSVs (absence + BLIP). Outputs go to {foldername}_output with files {inputstem}_output.csv / .xlsx")
    parser.add_argument("--absence-name", help="Exact filename for absence CSV inside --input-folder (if not auto-detected)")
    parser.add_argument("--blip-name", help="Exact filename for BLIP CSV inside --input-folder (if not auto-detected)")
    parser.add_argument("--absence-only", action="store_true", help="Run only absence cleanup")
    parser.add_argument("--blip-only", action="store_true", help="Run only BLIP cleanup")
    parser.add_argument("--absence-in", help="Input path for absence (raw BrightHR CSV)")
    parser.add_argument("--absence-out", help="Output path for absence (cleaned CSV)")
    parser.add_argument("--blip-in", help="Input path for BLIP (raw timesheet CSV)")
    parser.add_argument("--blip-out", help="Output path for BLIP (Excel or CSV; use CSV with --blip-append for cumulative)")
    parser.add_argument("--blip-append", action="store_true", help="Append BLIP to cumulative CSV (default in folder mode)")
    parser.add_argument("--no-blip-append", action="store_true", help="Do not append BLIP; write to output folder instead (folder mode)")
    parser.add_argument("--blip-cumulative-path", help="Path to cumulative BLIP CSV (default: project blip_cumulative.csv); must be .csv")
    parser.add_argument("--config", default=_CONFIG_PATH, help=f"Path to JSON config (default: {os.path.basename(_CONFIG_PATH)})")
    args = parser.parse_args()

    # ---- Folder mode: derive all paths from --input-folder (CLI or config) ----
    config = {}
    if os.path.exists(args.config):
        try:
            with open(args.config, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read config: {e}", file=sys.stderr)

    input_folder = args.input_folder or config.get("input_folder")
    if input_folder:
        args.input_folder = input_folder
    if args.input_folder:
        absence_in, blip_in, err = _find_absence_and_blip_in_folder(
            args.input_folder, args.absence_name, args.blip_name
        )
        if err:
            print(f"Error: {err}", file=sys.stderr)
            return 1

        # Output folder = foldername_output (same parent)
        input_folder_norm = os.path.normpath(args.input_folder).rstrip(os.sep)
        base_name = os.path.basename(input_folder_norm)
        parent = os.path.dirname(input_folder_norm)
        output_folder = os.path.join(parent, base_name + "_output")

        # Output files: absence = full replace; BLIP = append to cumulative CSV by default (same file app loads)
        absence_stem = os.path.splitext(os.path.basename(absence_in))[0]
        blip_stem = os.path.splitext(os.path.basename(blip_in))[0]
        absence_out = os.path.join(output_folder, absence_stem + "_output.csv")
        default_cumulative = os.path.join(_PROJECT_ROOT, "blip_cumulative.csv")
        blip_append = config.get("blip_append", True) if "blip_append" not in config else config.get("blip_append")
        blip_append = (blip_append and not args.no_blip_append) or args.blip_append
        blip_cumulative_path = config.get("blip_cumulative_path") or args.blip_cumulative_path or default_cumulative
        if blip_append:
            blip_out = blip_cumulative_path if blip_cumulative_path.lower().endswith(".csv") else (blip_cumulative_path.rstrip("/\\") + ".csv")
        else:
            blip_out = os.path.join(output_folder, blip_stem + "_output.xlsx")

        os.makedirs(output_folder, exist_ok=True)

        print("Data ingestion pipeline (folder mode)")
        print("-" * 40)
        print(f"Input folder:  {args.input_folder}")
        print(f"Output folder: {output_folder}")
        print(f"Absence: {os.path.basename(absence_in)} -> {os.path.basename(absence_out)} (full replace)")
        print(f"BLIP:    {os.path.basename(blip_in)} -> {os.path.basename(blip_out)}" + (" (append)" if blip_append else " (replace)"))
        print("-" * 40)

        if not args.blip_only:
            print("\n[1/2] Absence cleanup...")
            exit_absence = run_absence(absence_in, absence_out)
            if exit_absence != 0:
                print("Absence cleanup failed.", file=sys.stderr)
                return exit_absence
            print("Absence cleanup OK.")

        if not args.absence_only:
            print("\n[2/2] BLIP cleanup...")
            exit_blip = run_blip(blip_in, blip_out, append=blip_append)
            if exit_blip != 0:
                print("BLIP cleanup failed.", file=sys.stderr)
                return exit_blip
            print("BLIP cleanup OK.")

        print("-" * 40)
        print("Pipeline finished successfully.")
        print("Point the app to:")
        print(f"  Absence CSV: {absence_out}")
        print(f"  BLIP:        {blip_out}" + (" (cumulative; app default)" if blip_append else ""))
        return 0

    # ---- Individual paths / config mode ----
    config = {}
    if os.path.exists(args.config):
        try:
            with open(args.config, encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Warning: Could not read config: {e}", file=sys.stderr)

    def get_absence_in():
        return args.absence_in or config.get("absence_input")

    def get_absence_out():
        return args.absence_out or config.get("absence_output")

    def get_blip_in():
        return args.blip_in or config.get("blip_input")

    def get_blip_out():
        return args.blip_out or config.get("blip_output")

    run_both = not (args.absence_only or args.blip_only)

    print("Data ingestion pipeline")
    print("-" * 40)

    if run_both or args.absence_only:
        absence_in = get_absence_in()
        absence_out = get_absence_out()
        if not absence_in or not absence_out:
            print("Error: Absence paths required. Use --input-folder, or --absence-in and --absence-out, or set in ingestion_config.json.", file=sys.stderr)
            return 1
        print("\n[1/2] Absence cleanup...")
        exit_absence = run_absence(absence_in, absence_out)
        if exit_absence != 0:
            print("Absence cleanup failed.", file=sys.stderr)
            if run_both:
                print("Skipping BLIP.", file=sys.stderr)
            return exit_absence
        print("Absence cleanup OK.")
    else:
        print("\n[1/2] Absence: skipped (--blip-only)")

    if run_both or args.blip_only:
        blip_in = get_blip_in()
        blip_out = get_blip_out() or (config.get("blip_cumulative_path") if (config.get("blip_append") or args.blip_append) else None)
        if not blip_in or not blip_out:
            print("Error: BLIP paths required. Use --input-folder, or --blip-in and --blip-out, or set in ingestion_config.json.", file=sys.stderr)
            return 1
        blip_append = config.get("blip_append", False) or args.blip_append
        if blip_append and not blip_out.lower().endswith(".csv"):
            print("Error: BLIP append mode requires output path to be .csv (cumulative file).", file=sys.stderr)
            return 1
        print("\n[2/2] BLIP cleanup..." + (" (append to cumulative CSV)" if blip_append else ""))
        exit_blip = run_blip(blip_in, blip_out, append=blip_append)
        if exit_blip != 0:
            print("BLIP cleanup failed.", file=sys.stderr)
            return exit_blip
        print("BLIP cleanup OK.")
    else:
        print("\n[2/2] BLIP: skipped (--absence-only)")

    print("-" * 40)
    print("Pipeline finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
