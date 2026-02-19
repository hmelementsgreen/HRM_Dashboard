"""
BLIP timesheet anomaly correction and preprocessing.
Fixes overnight shifts, negative duration/worked, and duration vs adjusted inconsistency.
"""
import numpy as np
import pandas as pd

BLIP_COL_FIRST = "First Name"
BLIP_COL_LAST = "Last Name"
BLIP_COL_TEAM = "Team(s)"
BLIP_COL_ROLE = "Job Title"
BLIP_COL_TYPE = "Blip Type"
BLIP_COL_IN_DATE = "Clock In Date"
BLIP_COL_IN_TIME = "Clock In Time"
BLIP_COL_OUT_DATE = "Clock Out Date"
BLIP_COL_OUT_TIME = "Clock Out Time"
BLIP_COL_IN_LOC = "Clock In Location"
BLIP_COL_OUT_LOC = "Clock Out Location"
BLIP_COL_DURATION = "Total Duration"
BLIP_COL_WORKED = "Total Excluding Breaks"

def _to_timedelta_safe(s):
    x = s.astype(str).replace({'NaT': np.nan, 'nan': np.nan, '': np.nan, 'None': np.nan})
    return pd.to_timedelta(x, errors='coerce')

def _parse_date_flexible(s):
    """Parse dates in DD/MM/YYYY or YYYY-MM-DD format."""
    s = pd.Series(s) if not isinstance(s, pd.Series) else s
    out = pd.to_datetime(s, format='%Y-%m-%d', errors='coerce')
    still_na = out.isna() & s.notna() & (s.astype(str).str.strip() != '')
    if still_na.any():
        out.loc[still_na] = pd.to_datetime(s.loc[still_na], format='%d/%m/%Y', dayfirst=True, errors='coerce')
    return out

def _combine_date_time(d, t):
    d = _parse_date_flexible(d)
    t = t.astype(str).replace({'NaT': np.nan, 'nan': np.nan, '': np.nan, 'None': np.nan})
    return pd.to_datetime(d.dt.strftime('%Y-%m-%d') + ' ' + t, errors='coerce')

def _format_timedelta_for_blip(td):
    if pd.isna(td): return ''
    total_sec = int(td.total_seconds())
    if total_sec < 0: return ''
    days = total_sec // 86400
    rem = total_sec % 86400
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f'{days} days {h:02d}:{m:02d}:{s:02d}'

def fix_blip_anomalies(df, update_source_for_export=False):
    if BLIP_COL_IN_TIME not in df.columns or BLIP_COL_OUT_TIME not in df.columns:
        return df
    overnight_mask = df['has_clockout'] & (df['clockout_dt'] <= df['clockin_dt'])
    df.loc[overnight_mask, 'clockout_dt'] = df.loc[overnight_mask, 'clockout_dt'] + pd.Timedelta(days=1)
    bad_dur = df['duration_td'].dt.total_seconds() < 0
    bad_worked = df['worked_td'].dt.total_seconds() < 0
    bad_duration_worked = (df['duration_td'].dt.total_seconds() >= 0) & (df['worked_td'].dt.total_seconds() < 0)
    fix_mask = overnight_mask | bad_dur | bad_worked | bad_duration_worked
    if fix_mask.any():
        recalc_dur = df.loc[fix_mask, 'clockout_dt'] - df.loc[fix_mask, 'clockin_dt']
        df.loc[fix_mask, 'duration_td'] = recalc_dur
        dur_sec = recalc_dur.dt.total_seconds()
        worked_sec = np.where(dur_sec < 3600, dur_sec, np.maximum(0, dur_sec - 30 * 60))
        df.loc[fix_mask, 'worked_td'] = pd.to_timedelta(worked_sec, unit='s')
    if update_source_for_export and fix_mask.any():
        df.loc[fix_mask, BLIP_COL_DURATION] = df.loc[fix_mask, 'duration_td'].apply(_format_timedelta_for_blip)
        df.loc[fix_mask, BLIP_COL_WORKED] = df.loc[fix_mask, 'worked_td'].apply(_format_timedelta_for_blip)
        if overnight_mask.any():
            df.loc[overnight_mask, BLIP_COL_OUT_DATE] = df.loc[overnight_mask, 'clockout_dt'].dt.strftime('%d/%m/%Y')
    df['duration_hours'] = df['duration_td'].dt.total_seconds() / 3600
    df['worked_hours'] = df['worked_td'].dt.total_seconds() / 3600
    df['break_hours'] = (df['duration_hours'] - df['worked_hours']).clip(lower=0)
    return df

def process_blip_df(df, update_source_for_export=False):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df['employee'] = (df.get(BLIP_COL_FIRST, pd.Series(index=df.index, dtype='object')).fillna('').astype(str).str.strip() + ' ' + df.get(BLIP_COL_LAST, pd.Series(index=df.index, dtype='object')).fillna('').astype(str).str.strip()).str.strip()
    df['date'] = _parse_date_flexible(df.get(BLIP_COL_IN_DATE))
    df['is_weekend'] = df['date'].dt.weekday >= 5
    df['week_start'] = df['date'] - pd.to_timedelta(df['date'].dt.weekday, unit='D')
    df['month'] = df['date'].dt.to_period('M').astype(str)
    df['duration_td'] = _to_timedelta_safe(df.get(BLIP_COL_DURATION, pd.Series(index=df.index, dtype='object')))
    df['worked_td'] = _to_timedelta_safe(df.get(BLIP_COL_WORKED, pd.Series(index=df.index, dtype='object')))
    if BLIP_COL_IN_TIME in df.columns and BLIP_COL_OUT_TIME in df.columns:
        df['clockin_dt'] = _combine_date_time(df[BLIP_COL_IN_DATE], df[BLIP_COL_IN_TIME])
        df['clockout_dt'] = _combine_date_time(df[BLIP_COL_OUT_DATE], df[BLIP_COL_OUT_TIME])
        df['has_clockout'] = df['clockout_dt'].notna() & df['clockin_dt'].notna()
    else:
        df['clockin_dt'] = pd.NaT
        df['clockout_dt'] = pd.NaT
        df['has_clockout'] = False
    df = fix_blip_anomalies(df, update_source_for_export=update_source_for_export)
    if BLIP_COL_IN_LOC in df.columns and BLIP_COL_OUT_LOC in df.columns:
        df['location_mismatch'] = (df[BLIP_COL_IN_LOC].astype(str) != df[BLIP_COL_OUT_LOC].astype(str)) & df['has_clockout']
    else:
        df['location_mismatch'] = False
    df['blip_type_norm'] = df.get(BLIP_COL_TYPE, '').astype(str).str.strip().str.lower()
    return df
