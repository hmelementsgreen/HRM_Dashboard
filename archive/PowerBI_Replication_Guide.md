# Power BI Replication Guide: Leave Management & Time Utilisation

This guide explains how to replicate the Python Streamlit app (`app.py`) in Power BI. It covers data sources, Power Query transformations, data model, DAX measures, and report pages.

---

## 1. Overview of the App

The app has two main areas:

| Area | Purpose |
|------|--------|
| **Leave Management** | BrightHR absence data: Individual, Department, Country, and ExCo views with KPIs, balances, and evidence tables |
| **Time Utilisation (BLIP)** | Timesheet data: daily utilisation %, employee work/break/WFH view, exceptions (short/long shifts, missing clock-outs) |

---

## 2. Data Sources

### 2.1 Absence (BrightHR) – CSV

**Source:** `AbsenseReport_Cleaned_Final.csv` (or equivalent BrightHR export).

**Expected columns (from app):**

- `First name`, `Last name`
- `Team names`
- `Leave entitlement`, `Entitlement unit`
- `Absence type`, `Absence duration total in days`, `Absence duration for period in days`
- `Absence description` (or `Description` / `Reason` / `Notes` / `Absence reason` / `Absence notes`)
- `Absence start date`, `Absence end date`
- `Organisation`, `Suborganisation` (optional)
- `Country` (optional; app infers from team if missing)

**Metric column used everywhere:** `Absence duration for period in days`

### 2.2 BLIP Timesheet – Excel

**Source:** Excel file (e.g. `blipTimesheet_27Jan_onwards_clean.xlsx`), typically with a header row to skip.

**Expected columns:**

- `First Name`, `Last Name`
- `Team(s)`, `Job Title`
- `Blip Type` (e.g. Shift, Break)
- `Clock In Date`, `Clock In Time`, `Clock Out Date`, `Clock Out Time`
- `Clock In Location`, `Clock Out Location`
- `Total Duration`, `Total Excluding Breaks`
- `Notes` (optional, for WFH detection)

---

## 3. Power Query: Absence Data

### 3.1 Load and basic columns

1. **Get Data** → Text/CSV → select your absence CSV.
2. Ensure **first row as header**; set data types (dates, number for duration and entitlement).

### 3.2 Add calculated columns (Absence table)

Create these in Power Query (or as calculated columns in the model):

| Column | Logic (conceptual) |
|--------|---------------------|
| **Employee** | `[First name] & " " & [Last name]` (trim as needed) |
| **Start Date** | Parse `Absence start date` (handle M/d/yyyy and dd/MM/yyyy; app uses two-pass parsing) |
| **End Date** | Parse `Absence end date` same way |
| **Month** | `Date.ToText(Date.From([Start Date]), "yyyy-MM")` or equivalent |
| **Start Date UK** | Format `Start Date` as dd/MM/yyyy |
| **End Date UK** | Format `End Date` as dd/MM/yyyy |
| **Absence Duration Days** | Use `Absence duration for period in days` (ensure number) |
| **Purpose** | From `Absence description` (or first available of Description, Reason, Notes, etc.) |
| **Country** | If column exists use it (replace blank/Unknown with "UK"); else infer from `Team names` (e.g. team containing "India" → India, else UK) |

### 3.3 Absence category (dashboard type)

Map raw `Absence type` to dashboard categories:

- **Annual** → "Annual Leave"
- **Medical** → "Medical + Sickness"
- **Work from home** → "WFH"
- **Travel** → "Travel"
- **Others** → "Other (excl. WFH, Travel)"

If your CSV already uses values like "Annual", "Medical", etc., a simple **Conditional Column** or **Replace** in Power Query is enough. If you have free text, you may need a more complex rule set (e.g. keyword search in description) – replicate the app’s `map_absence_type` logic (keywords for WFH, Travel, Annual, Sick).

### 3.4 Entitlement (days)

- Add **Leave Entitlement Days**: use `Leave entitlement` only when `Entitlement unit` is "days" (or blank); otherwise null/blank.
- Use this for “full-time” (entitlement > 0) vs “external consultants” (entitlement = 0).

### 3.5 Daily expansion (optional but useful)

The app expands each absence **case** into one row per day (for evidence and daily KPIs). In Power BI you can:

- **Option A:** Do this in Power Query: for each row, create a list of dates from Start Date to End Date, then expand to rows. Add columns: `Date`, `Week Start`, `ISO Week`, `Date UK`, and a stable **Case ID** (e.g. hash of employee + start + end + type + team + country).
- **Option B:** Keep only case-level data and use DAX to compute “daily” metrics where needed (e.g. count of days in period), or use a **Date** table and measures.

For full parity with the app’s “daily evidence” and “daily rows in scope”, Option A is preferable.

### 3.6 Case ID (for evidence)

If you expand to daily, still keep a **Case ID** on the case-level table (and carry it to daily if you expand). Formula similar to app: hash or concatenate `Employee & Start Date & End Date & Absence type & Team names & Country`.

---

## 4. Power Query: BLIP Data

### 4.1 Load Excel

1. **Get Data** → Excel → select workbook, pick the timesheet sheet.
2. Skip one row if the first row is a title (e.g. “Blip Timesheet”).
3. Promote headers; set types: dates, time, duration text.

### 4.2 Core columns

| New column | Logic |
|------------|--------|
| **Employee** | `[First Name] & " " & [Last Name]` |
| **Date** | From `Clock In Date` (date only) |
| **Is Weekend** | `Date.DayOfWeek([Date], Day.Monday) >= 5` (Sat/Sun) |
| **Week Start** | Start of week (e.g. `Date.AddDays([Date], -Date.DayOfWeek([Date], Day.Monday))`) |
| **Month** | `Date.ToText([Date], "yyyy-MM")` |
| **Blip Type Norm** | Lowercase trim of `Blip Type` (e.g. "shift", "break") |

### 4.3 Duration and worked hours

- Parse **Total Duration** and **Total Excluding Breaks** from text (e.g. "7:30" or "7h 30m") into a duration or decimal hours.
- Add **Duration Hours** and **Worked Hours** (decimal).
- **Break Hours** = Duration Hours − Worked Hours (clip at 0).

### 4.4 Clock-in / clock-out

- **Clock In DateTime** = combine `Clock In Date` and `Clock In Time`.
- **Clock Out DateTime** = combine `Clock Out Date` and `Clock Out Time`.
- **Has Clockout** = both are not null and Clock Out > Clock In.
- **Location Mismatch** = (Clock In Location <> Clock Out Location) and Has Clockout (only for shift rows if you filter later).

### 4.5 WFH detection

- If you have a **Notes** column: add **Is WFH Note** = Text.Contains(Text.Upper([Notes]), "WFH").
- Use this to mark WFH days for utilisation (e.g. count as 8h when no clock-in exists).

---

## 5. Data Model in Power BI

### 5.1 Tables

- **Absence** (or **AbsenceCases**): one row per absence case; columns above.
- **AbsenceDaily** (optional): one row per day per case; link to **Date** and **Absence** (or Case ID).
- **Date**: calendar table (required for slicers and time intelligence).
- **BLIP**: one row per timesheet row (clock-in/out record); optional link to **Date**.
- **Teams** / **Countries** (optional): dimension tables if you want cleaner slicers.

### 5.2 Relationships

- **Date** (Date) → **Absence** (Start Date or similar): filter absences by selected period (or use a role-playing relationship and filter context).
- **Date** (Date) → **AbsenceDaily** (Date): for daily-level visuals.
- **Date** (Date) → **BLIP** (Date): for BLIP by date.
- If you have **Team names** / **Country** only on Absence, you can keep them as columns and use them in slicers; no need for separate dimension tables unless you want a star schema.

### 5.3 Date table

Create a **Date** table (one row per day) covering all absence and BLIP dates. Add:

- **Date**, **Month** (e.g. "yyyy-MM"), **Week Start**, **ISO Week**, **Year**, **Is Weekday** (Mon–Fri).

Use this for:
- Month/week slicers.
- Filtering “weeks in period” (for WFH allowance).
- BLIP “weekdays only” (exclude weekends).

---

## 6. DAX: Leave Management

### 6.1 Parameters (slicers)

- **Selected Month(s)**: one or two months (e.g. "2025-11", "2025-12").
- **Departments** (Team names), **Countries**, **Absence types**: multiselect slicers.
- **Employee search**: use a text filter or a filter pane with “contains” (Power BI has search in slicers).
- **Custom date range**: optional; use for evidence/export only; implement via a separate Date range slicer or relative date filter.

### 6.2 Full-time vs consultants

- **Full-time count** = COUNTROWS( FILTER( VALUES(Absence[Employee]), [Leave Entitlement Days] > 0 ) )  
  (or from a dedicated Employee/Entitlement table if you build one.)
- **External consultants** = same but `[Leave Entitlement Days] = 0`.

### 6.3 Absence days in scope

- **Absence days (count)** = COUNTROWS( AbsenceDaily ) with filters (month, department, country, type, employee, date range).
- **Absence days (sum)** = SUM( Absence[Absence duration for period in days] ) with same filters (case-level).

Use “count of daily rows” when you need “daily rows in scope” (e.g. WFH taken = count of daily rows where category = WFH). Use “sum of days” when you want total days (e.g. for ExCo).

### 6.4 WFH utilisation

- **Weeks in period** = number of distinct **Week Start** in selected month(s) (from Date table).
- **WFH allowed** = Weeks in period × Full-time count (1 WFH day per week per full-time employee).
- **WFH taken** = COUNTROWS of AbsenceDaily where Category = "WFH" and filters applied.
- **WFH utilisation %** = DIVIDE( WFH taken, WFH allowed, 0 ) × 100.

### 6.5 Annual leave

- **Annual entitled** = SUM of **Leave Entitlement Days** for full-time only (or from balance table).
- **Annual taken** = COUNTROWS( AbsenceDaily where Category = "Annual Leave" ) or SUM of days for Annual Leave.
- **Annual remaining** = by employee: Entitlement − Taken (then sum for firmwide). You may need an **Employee balance** table (one row per employee with Entitlement, Used, Remaining) refreshed from the same source; the app computes this from case-level + daily data.

### 6.6 Rollups

- **Department rollup**: GROUPBY or SUMMARIZE by Team names: Headcount, Entitlement sum, Used sum, Remaining sum (full-time only).
- **Country rollup**: same by Country.
- **Monthly by type**: SUM( Absence duration for period in days ) by Month and Absence category; use for stacked bars and donuts.

---

## 7. Report Pages (Leave Management)

### 7.1 Individual (Daily Log)

- **KPIs:** Full-time employees, External consultants, Absence days (count), Weeks in period.
- **WFH:** WFH utilisation % (gauge or big number), WFH allowed vs taken.
- **Annual:** Annual entitled, taken, remaining (cards).
- **Other leave:** Sick, Travel, Other (cards).
- **Leave mix:** Donut/pie by Absence category (use same colour map: Annual=blue, Medical=red, Other=gray, WFH=green, Travel=amber).
- **Table:** Individual leave table – one row per employee (Team, Country, WFH allowed/taken, Annual entitled/taken/remaining, Sick/Travel/Other taken). Use a table visual with measures or a calculated table/summary table.
- **Evidence:** Collapsible section = table of daily rows (date, employee, team, country, category, days, purpose, start/end). Filter by same slicers + optional evidence-only filters.

### 7.2 Department

- **Department rollup table:** Team names, headcount, entitlement, used, remaining.
- **Drilldown:** Slicer “Select department” → table of employees in that department with balance columns.
- **Chart:** Stacked bar – X = Team names, Y = Absence duration for period in days, Legend = Absence category (order: Annual Leave, Medical, Other, WFH, Travel). Optionally two charts side-by-side for two months.

### 7.3 Country

- **Country rollup table** and **drilldown** (employees by selected country).
- **Country selector:** Buttons or slicer (UK, India, etc.).
- **Metrics:** Total days (month 1), total days (month 2), change %; department count; employee count.
- **Pie(s):** By absence category for selected country (one per month if comparing).
- **Evidence:** Daily log filtered by selected country.

### 7.4 Group / ExCo

- **KPIs:** Absence days (month 1), Absence days (month 2), Change (value and %).
- **Leave-type KPI row:** One card per category (Annual, Medical, Other, WFH, Travel) with value and delta vs previous month.
- **Donuts:** Absence by type per month (hole chart, same colours).

---

## 8. Time Utilisation (BLIP) in Power BI

### 8.1 Filters

- **Date range** for BLIP (separate from Leave; use a dedicated BLIP date range or slicer on BLIP table).
- **Expected daily hours** (e.g. 8): use a parameter or typed value in measures.
- **Short shift threshold** (e.g. 2h), **Long shift threshold** (e.g. 10h): for exception counts.

### 8.2 BLIP base measures

- **BLIP rows (all)** = COUNTROWS( BLIP ) in date range.
- **Shift rows** = COUNTROWS( FILTER( BLIP, BLIP[Blip Type Norm] = "shift" ) ) and **weekdays only** (filter by Date[Is Weekday] or BLIP date not weekend).
- **Employees (BLIP)** = DISTINCTCOUNT( BLIP[Employee] ).
- **Worked hours** = SUM( BLIP[Worked Hours] ).
- **Duration hours** = SUM( BLIP[Duration Hours] ).
- **Break hours** = SUM( BLIP[Break Hours] ).
- **Missing clock-outs** = COUNTROWS( FILTER( BLIP, NOT BLIP[Has Clockout] ) ) (for shift rows).
- **Short shifts** = COUNTROWS( FILTER( BLIP, BLIP[Worked Hours] < Short threshold ) ).
- **Long shifts** = COUNTROWS( FILTER( BLIP, BLIP[Worked Hours] > Long threshold ) ).
- **Location mismatches** = SUM( BLIP[Location Mismatch] ) or COUNTROWS where true.

### 8.3 WFH and daily utilisation

- For **weekdays** in range: build a daily table (one row per weekday date).
- **Expected (day)** = Distinct employees that day × Expected daily hours (parameter).
- **Worked (day)** = SUM( BLIP[Worked Hours] ) for that date (shift rows).
- For dates with **no BLIP rows** but marked as WFH (e.g. from Notes): treat Worked = Expected (e.g. 8h) and Utilisation = 100%.
- **Utilisation (day)** = DIVIDE( Worked, Expected, BLANK() ).
- **Daily utilisation chart:** Line chart – X = Date, Y = Utilisation % (weekdays only). Add a reference line at 100%.

### 8.4 Employee view (Work / Break / WFH by day)

- **Slicer:** Select employee.
- For each **weekday** in range:
  - If BLIP has Shift/Break segments: compute Work and Break hours from Clock In/Out (you may need a computed table or Power Query that expands segments).
  - If WFH day (Notes): one block “WFH / On leave” = 8h.
  - If no data and weekday: “WFH / On leave” = 8h (assumed).
- Visual: **Stacked bar** or **Gantt-style** – X = Date, Y = time of day (e.g. 8–19), bars for Work (green), Break (amber), WFH (blue). Power BI doesn’t have native “time of day” bars; use a **bar chart** with **Base** and **Height** (e.g. base = start hour, height = duration) or a **custom visual** (e.g. Gantt) if available.
- **Deviation vs 8h:** Per day (worked − 8), and overall total; show as annotation or card.

### 8.5 Exceptions and exports

- **Cards:** Missing clock-outs, Short shifts, Long shifts, Location mismatches.
- **Table:** Shift-level table (date, employee, team, role, worked hours, break, duration, has clockout, location mismatch). Use “Export data” from visual or a paginated report for CSV export.

---

## 9. Colours and ordering (parity with app)

Use these for consistency:

- **Annual Leave:** #2563eb  
- **Medical + Sickness:** #dc2626  
- **Other (excl. WFH, Travel):** #6b7280  
- **WFH:** #16a34a  
- **Travel:** #ca8a04  

**Absence category order:** Annual Leave → Medical + Sickness → Other → WFH → Travel (use sort order or “Category” column 1–5 in the model).

---

## 10. Limitations and differences

| Aspect | Python app | Power BI |
|--------|------------|----------|
| **File upload** | User uploads CSV/Excel at runtime | Data loaded in PBI; refresh from folder/OneDrive or gateway |
| **Two months** | Side-by-side charts | Use two month slicers or “Compare” bookmark / two copies of same visual |
| **Evidence filters** | Separate evidence-only filters | Use same slicers or a duplicate page with different filter pane |
| **Exports** | Buttons for CSV (filtered) | Export from table visual or Paginated Reports |
| **BLIP “authentic day”** | Merges overlapping Shift/Break intervals | Replicate in PQ or DAX; or simplify to one Work + one Break per day |
| **WFH 8h assumption** | Applied when no clock-in for weekday | Same logic in DAX/PQ for daily utilisation and employee view |

---

## 11. Quick start checklist

1. [ ] Create **Date** table and connect to Absence/BLIP dates.  
2. [ ] Load **Absence** CSV; add Employee, Month, Start/End, Category, Country, Entitlement days.  
3. [ ] Optionally create **AbsenceDaily** (expand cases to days) and Case ID.  
4. [ ] Load **BLIP** Excel; add Employee, Date, Worked/Duration/Break, Blip Type Norm, Has Clockout, Location Mismatch, Is WFH Note.  
5. [ ] Build **relationships** (Date → Absence, Date → BLIP; optional Absence → AbsenceDaily).  
6. [ ] Add **slicers**: Month(s), Team names, Country, Absence type, Employee search, BLIP date range.  
7. [ ] Implement **DAX**: full-time count, WFH allowed/taken/utilisation %, annual entitled/taken/remaining, rollups.  
8. [ ] Build **Leave** report: Individual, Department, Country, ExCo pages with KPIs, tables, and charts.  
9. [ ] Build **BLIP** report: KPIs, daily utilisation line, shift table, employee Work/Break/WFH view, exceptions.  
10. [ ] Apply **colours** and **sort order** for absence types.  
11. [ ] Set up **refresh** (scheduled or manual) for CSV/Excel sources.

Using this guide you can replicate the Leave Management and Time Utilisation behaviour of `app.py` in Power BI; adjust table and column names to match your actual PBI model.

---

## Appendix A: Sample Power Query (Absence – Category)

Example **Conditional Column** in Power Query for **Absence Category** when source has clean types:

```powerquery
// Add column: Absence Category
if [Absence type] = "Annual" then "Annual Leave"
else if [Absence type] = "Medical" then "Medical + Sickness"
else if [Absence type] = "Work from home" then "WFH"
else if [Absence type] = "Travel" then "Travel"
else if [Absence type] = "Others" then "Other (excl. WFH, Travel)"
else "Other (excl. WFH, Travel)"
```

If you need keyword-based mapping (like the app), add a custom column that checks `Absence description` for keywords (e.g. "WFH", "travel", "sick") and then falls back to type.

---

## Appendix B: Sample DAX measures

**Full-time employee count (by entitlement):**

```dax
Full-Time Count = 
VAR Entitled = 
    SUMMARIZE(
        FILTER( Absence, Absence[Leave Entitlement Days] > 0 ),
        Absence[Employee]
    )
RETURN COUNTROWS( Entitled )
```

**Absence days (sum) for current filters:**

```dax
Absence Days Total = SUM( Absence[Absence duration for period in days] )
```

**WFH taken (if you have AbsenceDaily with Category):**

```dax
WFH Taken = 
CALCULATE(
    COUNTROWS( AbsenceDaily ),
    AbsenceDaily[Absence Category] = "WFH"
)
```

**Utilisation % (BLIP – at day level, use in a table with Date):**

```dax
Worked Hours Day = SUM( BLIP[Worked Hours] )
Expected Hours Day = DISTINCTCOUNT( BLIP[Employee] ) * [Expected Daily Hours Param]
Utilisation Pct = DIVIDE( [Worked Hours Day], [Expected Hours Day], BLANK() )
```

Use a **Parameter** (Model → New parameter) for **Expected Daily Hours Param** (e.g. 8).

---

## Appendix C: BLIP duration from text

If BLIP Excel has duration as "7:30" or "7h 30m", in Power Query:

```powerquery
// Example: "7:30" or "7.5" -> 7.5
let
  toHours = (t as text) as number =>
    let
      t2 = Text.Trim(Text.Lower(t)),
      hasColon = Text.Contains(t2, ":"),
      parts = if hasColon then Text.Split(t2, ":") else Text.Split(t2, "h ")
    in
      if hasColon then
        Number.From(parts{0}) + Number.From(parts{1}) / 60
      else if Text.Contains(t2, "h") then
        Number.From(Text.Remove(parts{0}, "h")) + (if List.Count(parts) > 1 then Number.From(Text.Remove(parts{1}, "m")) / 60 else 0)
      else
        Number.From(t2)
in
  toHours
```

Apply this as a custom function to the Duration and Worked columns, then add **Duration Hours** and **Worked Hours**.
