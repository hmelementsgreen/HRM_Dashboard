# Power BI Replication – Step by Step

Follow these steps in order. Each step builds on the previous one.

---

## Step 1: Create a new Power BI file and load the Absence CSV

1. Open **Power BI Desktop**.
2. **Home** → **Get data** → **Text/CSV**.
3. Browse to:  
   `c:\Users\HarshMalhotra\OneDrive - United Green\Documents\BrightHRData\AbsenseReport_Cleaned_Final.csv`
4. In the preview:
   - Set **Data type detection** to "Based on entire dataset" (or leave default).
   - Ensure the first row is the header.
5. Click **Transform Data** (so we can add columns in the next step).  
   Do **not** click "Load" yet if you want to do Step 2 in the same query.

**Check:** You see columns like: First name, Last name, Team names, Leave entitlement, Entitlement unit, Absence type, Absence duration for period in days, Absence description, Start_Date, End_Date (or Absence start date / Absence end date – you can rename these to Start_Date and End_Date in Power Query).

---

## Step 2: Add basic columns to the Absence query (Power Query)

Stay in **Power Query Editor** on the Absence query.

### 2a. Employee (full name)

1. Select the **First name** column, then hold **Ctrl** and select **Last name**.
2. **Add Column** → **Merge Columns**.
3. Separator: **Space**. New column name: **Employee**. OK.

### 2b. Start and End dates

1. Click **Start_Date** → **Data type** → **Date** (or Date/Time if your source has time).
2. Click **End_Date** → **Data type** → **Date**.
3. If dates look wrong (e.g. US format), right‑click the column → **Change type** → **Using locale** → Date, and pick the correct locale (e.g. English (United Kingdom)).

### 2c. Month (for slicers)

1. **Add Column** → **Custom Column**.
2. New column name: **Month**.
3. Custom column formula:  
   `Date.ToText(Date.From([Start_Date]), "yyyy-MM")`  
   (If you use different column names, e.g. `Absence start date`, put that in brackets instead.)
4. OK.

### 2d. Absence Category (dashboard type)

1. **Add Column** → **Conditional Column**.
2. New column name: **Absence Category**.
3. Add rules (one by one):
   - If **Absence type** equals **Annual** → **Annual Leave**
   - Else if **Absence type** equals **Medical** → **Medical + Sickness**
   - Else if **Absence type** equals **Work from home** → **WFH**
   - Else if **Absence type** equals **Travel** → **Travel**
   - Else if **Absence type** equals **Others** → **Other (excl. WFH, Travel)**
   - Else → **Other (excl. WFH, Travel)**
4. OK.

### 2e. Country (if missing)

1. If your table already has a **Country** column, ensure it has no blanks (replace blank with "UK"):  
   Select **Country** → **Replace Values** → (leave “Value To Find” blank) → Replace With: **UK**.
2. If there is **no** Country column: **Add Column** → **Custom Column** → Name: **Country**, Formula: **"UK"** (we can refine later with team-based logic). OK.

### 2f. Leave entitlement in days only

1. **Add Column** → **Custom Column**.
2. New column name: **Leave Entitlement Days**.
3. Formula (only use entitlement when unit is days):  
   `if [Entitlement unit] = "days" or [Entitlement unit] = null then [Leave entitlement] else null`  
   (Adjust column names to match yours: e.g. `Leave entitlement` and `Entitlement unit`.)
4. Set the new column’s data type to **Decimal number**.

### 2g. Purpose (description)

1. If you have **Absence description**: rename it to **Purpose** (right‑click → Rename), or add **Custom Column** **Purpose** = `[Absence description]`.
2. Replace null with blank: select **Purpose** → **Replace Values** → null → **""**.

**Finish:** **Home** → **Close & Apply**. The Absence table is now in the model.

**Check:** In the Data pane you see **Absence** with columns: Employee, Start_Date, End_Date, Month, Absence Category, Country, Leave Entitlement Days, Purpose, and **Absence duration for period in days**.

---

## Step 3: Create a Date table

We need a calendar for month/week slicers and filtering.

1. **Home** → **Get data** → **Blank query**.
2. In the formula bar, replace the default with:

```powerquery
let
  StartDate = #date(2024, 1, 1),
  EndDate = #date(2026, 12, 31),
  NumDays = Duration.Days(EndDate - StartDate) + 1,
  DateList = List.Dates(StartDate, NumDays, #duration(1, 0, 0, 0)),
  ToTable = Table.FromList(DateList, Splitter.SplitByNothing(), {"Date"}, null, ExtraValues.Error),
  Typed = Table.TransformColumnTypes(ToTable, {{"Date", type date}}),
  AddMonth = Table.AddColumn(Typed, "Month", each Date.ToText([Date], "yyyy-MM"), type text),
  AddWeekStart = Table.AddColumn(AddMonth, "Week Start", each Date.StartOfWeek([Date], Day.Monday), type date),
  AddISOWeek = Table.AddColumn(AddWeekStart, "ISO Week", each Date.WeekOfYear([Date], Day.Monday), Int64.Type),
  AddYear = Table.AddColumn(AddISOWeek, "Year", each Date.Year([Date]), Int64.Type),
  AddIsWeekday = Table.AddColumn(AddYear, "Is Weekday", each Date.DayOfWeek([Date], Day.Monday) < 5, type logical)
in
  AddIsWeekday
```

3. **Rename** the query to **Date**.
4. **Home** → **Close & Apply**.

**Check:** You have a **Date** table with columns: Date, Month, Week Start, ISO Week, Year, Is Weekday.

---

## Step 4: Relate Absence to Date and add a Month slicer

1. Go to **Model** view (left icon).
2. Create a relationship:
   - **From:** Absence **Start_Date** (or **Month** if you prefer – then you need a matching **Month** on Date).
   - **To:** Date **Date**.
   - **Cardinality:** Many to one (*).  
   - **Cross filter:** Single (from Date to Absence).
   - If you used **Month** on Absence, add a **Month** column to Date (you already have it) and relate Absence[Month] to Date[Month].

**Easier option:** Relate **Absence[Month]** to **Date[Month]** (both text "yyyy-MM"). Drag **Absence start date** → **Date** only if you need date-level filtering; for “month” filtering, Month-to-Month is enough.

3. **Report** view: add a **Slicer**, drag **Date[Month]** (or **Absence[Month]**) into it.  
   You now have “Select month” on the canvas.

**Check:** Selecting a month in the slicer filters the Absence table (you can confirm in Data view or by adding a simple table showing Absence rows).

---

## Step 5: Add first DAX measures (Absence)

1. **Table** view → select the **Absence** table.
2. **Table tools** → **New measure**.

Create these one by one:

**Absence Days Total**
```dax
Absence Days Total = SUM( Absence[Absence duration for period in days] )
```

**Full-Time Count** (entitlement > 0)
```dax
Full-Time Count = 
VAR EmployeesWithEntitlement =
    SUMMARIZE(
        FILTER( Absence, Absence[Leave Entitlement Days] > 0 ),
        Absence[Employee]
    )
RETURN COUNTROWS( EmployeesWithEntitlement )
```

**External Consultants Count**
```dax
External Consultants Count = 
VAR EmployeesNoEntitlement =
    SUMMARIZE(
        FILTER( Absence, Absence[Leave Entitlement Days] = 0 ),
        Absence[Employee]
    )
RETURN COUNTROWS( EmployeesNoEntitlement )
```

**Check:** Put a **Card** on the report; add **Absence Days Total**. Select a month; the card updates. Add **Full-Time Count** and **External Consultants Count** to cards.

---

## Step 6: Add more slicers (Department, Country, Absence type)

1. **Slicer** → drag **Absence[Team names]** → label it “Department”. Set to **Multi-select** (dropdown or list).
2. **Slicer** → drag **Absence[Country]** → “Country”. Multi-select.
3. **Slicer** → drag **Absence[Absence Category]** → “Absence type”. Multi-select.

**Check:** Choosing a department (and/or country, type) filters the report; the **Absence Days Total** card updates.

---

## Step 7: Build the “Individual” KPI area (Leave Management)

On the same page (or a new one named “Individual”):

1. **Cards:**  
   - Full-Time Count  
   - External Consultants Count  
   - Absence Days Total  
   (Arrange in a row.)
2. **Clustered bar chart:**  
   - Axis: **Absence[Absence Category]**  
   - Value: **Absence Days Total**  
   - Title: “Absence days by type”.
3. **Donut chart:**  
   - Legend: **Absence[Absence Category]**  
   - Values: **Absence Days Total**  
   - Title: “Leave mix”.

Optional: set **Sort by** Absence Category to a custom order (Annual Leave, Medical + Sickness, Other…, WFH, Travel) using a sort column or “Sort by column” in the model.

**Check:** Month and other slicers filter the cards and charts.

---

## Step 8: Add an Individual Leave table (by employee)

We need a table that shows one row per employee with entitlement and days taken by type.

**Option A – Simple (no daily expansion):**  
Use a **Table** visual:

- Rows: **Absence[Employee]** (or a distinct list of employees from Absence).
- Add columns that we’ll define as measures: **Annual Taken**, **Sick Taken**, **WFH Taken**, **Travel Taken**, **Other Taken**, and optionally **Entitlement**, **Remaining**.

**Measures for “taken” (example for Annual):**
```dax
Annual Taken = 
CALCULATE(
    [Absence Days Total],
    Absence[Absence Category] = "Annual Leave"
)
```

Create similar measures: **Sick Taken** (Medical + Sickness), **WFH Taken** (WFH), **Travel Taken** (Travel), **Other Taken** (Other (excl. WFH, Travel)).

**Entitlement (for display):**  
Use a measure that returns the entitlement for the current employee in context (e.g. from Absence, take MAX(Leave Entitlement Days) per employee – one value per employee):

```dax
Entitlement Days = 
VAR CurrentEmployee = SELECTEDVALUE( Absence[Employee] )
RETURN
    CALCULATE(
        MAX( Absence[Leave Entitlement Days] ),
        Absence[Employee] = CurrentEmployee,
        ALLSELECTED()
    )
```

**Remaining:**  
```dax
Remaining Days = [Entitlement Days] - [Annual Taken]
```
(Use in a table where each row is one employee; then Remaining = Entitlement − Annual Taken for that employee.)

**Table visual:**  
Add **Employee**, **Team names**, **Country**, **Entitlement Days**, **Annual Taken**, **Remaining Days**, **WFH Taken**, **Sick Taken**, **Travel Taken**, **Other Taken**.  
Sort by Employee.

**Check:** You see one row per employee (in current filter context), with totals by type and remaining days.

---

## Step 9: Load BLIP Excel (Time Utilisation data)

1. **Home** → **Get data** → **Excel**.
2. Browse to your BLIP file (e.g. the path in the app:  
   `C:\Users\HarshMalhotra\OneDrive - United Green\Documents\Blip\blipTimesheet_27Jan_onwards_clean.xlsx`  
   or from your archive).
3. Select the sheet that has the timesheet (e.g. first sheet). If the first row is a title, in the preview use **Transform Data** and we’ll skip a row in the next step.
4. Click **Transform Data**.

In **Power Query**:

- If row 1 is not the header: **Home** → **Use First Row as Headers** (or remove top row then promote headers).
- Ensure column names match what we need: First Name, Last Name, Team(s), Blip Type, Clock In Date, Clock In Time, Clock Out Date, Clock Out Time, Total Duration, Total Excluding Breaks (or similar).

### 9a. Add Employee
- Merge **First Name** and **Last Name** with a space → new column **Employee**.

### 9b. Add Date
- Add column **Date** = `Date.From([Clock In Date])` (adjust name if different). Type **Date**.

### 9c. Add Blip Type Norm
- **Add Column** → **Custom Column** → Name: **Blip Type Norm**, Formula:  
  `Text.Lower(Text.Trim([Blip Type]))`  
  (Replace `[Blip Type]` with your actual column name.)

### 9d. Duration and Worked hours
- If **Total Duration** / **Total Excluding Breaks** are already numbers (or duration), add **Duration Hours** and **Worked Hours** (e.g. convert duration to decimal hours).
- If they are text (e.g. "7:30"):
  - **Add Column** → **Custom Column** → **Duration Hours**:  
    `let t = [Total Duration] in Duration.TotalHours(Value.From(t))`  
    may not work for text; if so, use a custom parser (e.g. split by ":" and compute hours + minutes/60).
- Add **Break Hours** = **Duration Hours** − **Worked Hours**; ensure no negative (use `List.Max({0, ...})`).

### 9e. Has Clockout (optional but useful)
- If you have Clock Out Date/Time: **Add Column** → **Custom Column** → **Has Clockout** =  
  `[Clock Out Date] <> null and [Clock Out Time] <> null`  
  (adjust to your column names and types).

Then **Close & Apply**.

**Check:** You have a **BLIP** table with at least: Employee, Date, Blip Type Norm, Duration Hours, Worked Hours, Break Hours.

---

## Step 10: Connect BLIP to Date and add a BLIP date range

1. **Model** view: create a relationship **BLIP[Date]** → **Date[Date]** (many to one).
2. On the report: duplicate the **Month** slicer (or add a **Date** slicer) and put it in a “BLIP” area, or use a **relative date filter** on **Date** for “last 30 days” etc.

For a dedicated “BLIP date range” you can:
- Use a **slicer** on **Date[Date]** (range or list), or
- Use **Relative date filter** on the Date table (e.g. “is in the last 60 days”) and use that for BLIP visuals only by placing them in a separate section that uses the same Date table.

**Check:** BLIP table is related to Date; selecting a date range affects BLIP.

---

## Step 11: Add BLIP measures and a simple Time Utilisation page

**Measures** (on BLIP table or a dedicated “Measures” table):

```dax
BLIP Shift Rows = 
CALCULATE(
    COUNTROWS( BLIP ),
    BLIP[Blip Type Norm] = "shift",
    Date[Is Weekday] = TRUE
)
```

```dax
BLIP Employees = DISTINCTCOUNT( BLIP[Employee] )
```

```dax
Worked Hours Total = SUM( BLIP[Worked Hours] )
```

**New page:** “Time Utilisation”.

1. **Cards:** BLIP Shift Rows, BLIP Employees, Worked Hours Total.
2. **Table:** **BLIP** columns: Date, Employee, Team(s), Worked Hours, Break Hours, Blip Type Norm.  
   This is your “shift-level table”.

**Check:** Selecting a date range (via Date slicer) updates BLIP cards and table.

---

## Step 12: Department and Country pages (optional)

**Department page**
- **Slicer:** Month (and Department if you want to focus on one).
- **Table:** Group by **Team names** – e.g. **Headcount** = DISTINCTCOUNT(Employee), **Absence Days** = [Absence Days Total].  
  Use a **Matrix** or **Table** with **Team names** as rows and measures as values.
- **Stacked bar chart:** Axis = **Team names**, Value = **Absence Days Total**, Legend = **Absence Category**.  
  Title: “Absence by department and type”.

**Country page**
- **Slicer:** **Country** (and Month).
- **Cards:** [Absence Days Total], Count of employees, Count of departments.
- **Pie:** Legend = **Absence Category**, Values = **Absence Days Total**.  
  Title: “Leave mix by country”.

---

## What we did (summary)

| Step | What you did |
|------|------------------|
| 1 | New PBI file, load Absence CSV |
| 2 | Power Query: Employee, dates, Month, Absence Category, Country, Leave Entitlement Days, Purpose |
| 3 | Date table (Date, Month, Week Start, Is Weekday) |
| 4 | Relationship Absence ↔ Date, Month slicer |
| 5 | DAX: Absence Days Total, Full-Time Count, External Consultants Count |
| 6 | Slicers: Department, Country, Absence type |
| 7 | Individual: KPI cards, bar by type, donut “Leave mix” |
| 8 | Individual table: by employee with entitlement, taken, remaining, WFH/Sick/Travel/Other |
| 9 | Load BLIP Excel, add Employee, Date, Blip Type Norm, Duration/Worked/Break, Has Clockout |
| 10 | BLIP ↔ Date relationship, date range for BLIP |
| 11 | BLIP measures and Time Utilisation page (cards + shift table) |
| 12 | Department and Country pages (rollup + charts) |

---

## Next steps (when you’re ready)

- **WFH utilisation %:** Measures for “WFH allowed” (weeks in period × full-time count) and “WFH taken” (count or sum where category = WFH); then WFH % = WFH taken / WFH allowed. This may require an **AbsenceDaily** table (one row per day per absence) for accurate “days” counts.
- **Daily utilisation (BLIP):** A table or chart with one row per weekday: **Worked Hours** and **Expected Hours** (employees × 8), then **Utilisation %** = Worked / Expected; line chart over date.
- **ExCo page:** Same as Individual but firm-level only: KPIs and donuts by month, no employee table.
- **Exports:** Use “Export data” from table visuals, or **Paginated Reports** for CSV export with filters.

If you tell me which step you’re on (e.g. “Step 5” or “Step 9”), I can give the exact clicks and formulas for your column names and fix any errors you hit.
