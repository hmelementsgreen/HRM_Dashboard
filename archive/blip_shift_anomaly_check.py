"""Analyze BLIP shift data for anomalies."""
import pandas as pd
import re

df = pd.read_csv("blip_cumulative.csv")
shifts = df[df["Blip Type"].str.strip().str.lower() == "shift"].copy()
print(f"Total shift rows: {len(shifts)}")

def parse_timedelta(s):
    if pd.isna(s) or str(s).strip() == "":
        return None
    s = str(s).strip()
    m = re.search(r"(\d+)\s*days?\s*(\d+):(\d+):(\d+)", s, re.I)
    if m:
        d, h, mn, sec = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return d * 24 + h + mn / 60 + sec / 3600
    m = re.search(r"(\d+):(\d+):(\d+)", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60 + int(m.group(3)) / 3600
    return None

shifts["worked_hrs"] = shifts["Total Excluding Breaks"].apply(parse_timedelta)
shifts["date"] = pd.to_datetime(shifts["Clock In Date"], format="%d/%m/%Y", errors="coerce")
shifts["employee"] = (shifts["First Name"].fillna("").astype(str).str.strip() + " " + shifts["Last Name"].fillna("").astype(str).str.strip()).str.strip()

print("\n" + "=" * 60 + "\nANOMALIES\n" + "=" * 60)

short = shifts[shifts["worked_hrs"].notna() & (shifts["worked_hrs"] < 2)]
print(f"\n1. SHORT SHIFTS (< 2h): {len(short)}")
if len(short) > 0:
    for _, r in short.iterrows():
        print(f"   {r['employee']} | {r['Clock In Date']} | {r['worked_hrs']:.2f}h | {r.get('Notes', '')}")

long_shifts = shifts[shifts["worked_hrs"].notna() & (shifts["worked_hrs"] > 10)]
print(f"\n2. LONG SHIFTS (> 10h): {len(long_shifts)}")
if len(long_shifts) > 0:
    for _, r in long_shifts.iterrows():
        print(f"   {r['employee']} | {r['Clock In Date']} | {r['worked_hrs']:.2f}h")

no_out = shifts[(shifts["Clock Out Date"].isna()) | (shifts["Clock Out Date"].astype(str).str.strip() == "") | (shifts["Clock Out Time"].isna()) | (shifts["Clock Out Time"].astype(str).str.strip() == "")]
print(f"\n3. MISSING CLOCK OUT: {len(no_out)}")
if len(no_out) > 0:
    for _, r in no_out.head(15).iterrows():
        print(f"   {r['employee']} | {r['Clock In Date']} | Out: {r['Clock Out Date']} / {r['Clock Out Time']}")

loc_mismatch = shifts[(shifts["Clock In Location"].astype(str).str.strip() != shifts["Clock Out Location"].astype(str).str.strip()) & shifts["Clock Out Location"].notna()]
print(f"\n4. LOCATION MISMATCH: {len(loc_mismatch)}")
if len(loc_mismatch) > 0:
    for _, r in loc_mismatch.head(10).iterrows():
        print(f"   {r['employee']} | {r['Clock In Date']} | In: {r['Clock In Location']} -> Out: {r['Clock Out Location']}")

zero = shifts[(shifts["worked_hrs"].notna()) & (shifts["worked_hrs"] <= 0)]
print(f"\n5. ZERO/NEGATIVE worked: {len(zero)}")

shifts["_key"] = shifts["employee"] + "|" + shifts["Clock In Date"].astype(str)
multi = shifts.groupby("_key").size()
multi = multi[multi > 1]
print(f"\n6. MULTIPLE SHIFTS same person same day: {len(multi)}")
if len(multi) > 0:
    for k, cnt in multi.head(15).items():
        print(f"   {k}: {cnt} shifts")

bad_date = shifts[shifts["date"].isna()]
print(f"\n7. INVALID Clock In Date: {len(bad_date)}")

print("\n" + "=" * 60)
print(f"Date range: {shifts['date'].min()} to {shifts['date'].max()}")
print(f"Worked hrs: min={shifts['worked_hrs'].min():.2f} max={shifts['worked_hrs'].max():.2f} mean={shifts['worked_hrs'].mean():.2f}")
