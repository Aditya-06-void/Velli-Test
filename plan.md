# Velli Worker Eligibility Tool — Build Plan

## Context
Velli's ops team needs one answer: **"How much can this worker draw today?"** (`d:\Test\TASK_BRIEF.pdf`).
Inputs: worker + date (+ optional requested amount). Outputs: cycle dates, paid days, earned so far,
PF+ESI, already drawn, eligible amount, and for a request: Approved/Rejected + reason, 2% fee, total repayable.
The data (`attendance_register.csv`, `draws.csv`) is deliberately messy, and they test with their own cases,
so **correct numbers come first** and we must report what we found in the data.

Stack (user's choice): **HTML + CSS + vanilla JS** frontend, **Python FastAPI** backend.
Stdlib only for the logic (`csv`, `datetime`, `fractions`, `difflib`), so no pandas. Deps: `fastapi`, `uvicorn`.

## File layout (d:\Test)
```
PLAN.md               # copy of this plan
eligibility.py        # all business logic + data cleaning (pure functions, no FastAPI)
app.py                # FastAPI: loads data once, 4 GET endpoints, serves /static
static/index.html     # form, result card, WhatsApp box, summary table, data-notes
static/style.css
static/app.js         # fetch() calls + render
test_eligibility.py   # assert-based checks against the hand-computed examples below
requirements.txt      # fastapi, uvicorn
README.md             # how to run + data findings + open questions for Velli
```

## Backend: `eligibility.py`

### Loading and cleaning (runs once at startup, collects a `notes` list for the findings panel)
| Mess | Handling |
|---|---|
| `per_day_rate` = `₹989`, `850.00` | strip `₹`, `,`, spaces, then `Fraction(str)` |
| Marks `p`, `"P "` | `mark.strip().upper()`; paid iff `== "P"` |
| `WO`, `A`, blank | not paid (see open question 1) |
| Date columns `10-Oct-2026` | parse header with `%d-%b-%Y`; dates with no column count as blank |
| Draw dates `dd/mm/yyyy` | parse with `%d/%m/%Y` |
| `Bikas Oraon` vs `Bikash Oraon` | match each draw to a worker on **(normalised name, contractor)**. If there's no exact hit, use `difflib.get_close_matches` among workers **of the same contractor** (cutoff 0.85). Log every fuzzy match as a note. Draws still unmatched are logged, never silently dropped. |
| Two `Rahul Kumar` (W102 MMG, W103 SE) | the contractor is part of the key, so the draw (MMG) goes to W102 only |
| `paid_to_name` ≠ worker (family UPI) | still counts against the worker. Log it as a note (e.g. Selvi K → `Kannan S`, a different surname) |
| Inactive Santosh Nayak got a draw on 16/10 | count it. Log it as an anomaly ("paid to an inactive worker") |
| Murugan R: blanks 10–25 Oct (joined mid-cycle?) | blanks are unpaid, and PF+ESI still uses calendar days per rule 3. Log a note |

Draws are re-keyed to `emp_code` at load, so all later logic works on emp_code only.

### Core functions
- `cycle_for(d)` → `(start, end)`: if `d.day >= 10` the cycle runs from the 10th of this month to the 9th of next month, otherwise from the 10th of last month to the 9th of this month. It handles Dec→Jan.
- `find_worker(query)`: exact emp_code (case-insensitive), else exact normalised name. If a name matches 2+ workers, raise `Ambiguous` with the candidates so the API returns 400 and lists them. The UI dropdown sends emp_code, so this only matters for typed or API input.
- `compute(emp_code, d, amount=None)` → dict:
  - `paid_days` = count of `P` in `[start, d]`
  - `earned = rate × paid_days`
  - `pf_esi = 2000 × days_so_far / total_days` (exact `Fraction`, shown to 2 dp)
  - `net = earned − pf_esi`
  - `drawn` = sum of draws for this emp_code with `start ≤ draw_date ≤ d` (this drops past-cycle draws, future draws and the 10/11 payday draw)
  - `eligible = 0` if inactive, else `min(5000, max(0, floor((net/2 − drawn)/100)×100))`. Exact fractions avoid float errors at ₹100 boundaries.
  - If `amount` is given: `fee = amount × 2%`, `repayable = amount + fee` (2 dp). Status rules, checked in order:
    1. `amount ≤ 0` → Rejected: invalid amount
    2. worker inactive → Rejected: inactive worker
    3. `amount > 5000` → Rejected: over the ₹5,000 per-draw max
    4. `amount > eligible` → Rejected: exceeds eligible ₹X
    5. otherwise → Approved

    Fee and repayable are shown even when the request is rejected, labelled "if approved".
- `summary(d)` → `compute()` for every worker (bonus b).

## Backend: `app.py`
- Loads data once at startup. Paths are relative to the file.
- `GET /api/workers` → `[{emp_code, name, contractor, status}]` for the dropdown
- `GET /api/eligibility?worker=W101&date=2026-10-16&amount=2000` → compute result. Errors: unknown worker → 404, ambiguous name → 400 with candidates, bad date/amount → 422 via FastAPI typing (`date`, `float | None`).
- `GET /api/summary?date=…` → list (bonus b)
- `GET /api/notes` → data-cleaning findings
- `app.mount("/", StaticFiles(directory="static", html=True))` serves the frontend from the same origin, so no CORS setup is needed.

## Frontend (`static/`)
- **Form:** worker `<select>` filled from `/api/workers`, with each option labelled `W102 · Rahul Kumar (MMG)` so duplicate names are unambiguous; `<input type="date">` defaulting to today; optional amount `<input type="number" min="0">`; a Check button.
- **Result card:** cycle `DD/MM/YYYY to DD/MM/YYYY`, paid days, earned, PF+ESI, net, already drawn, **eligible (large)**. If an amount was entered, an Approved/Rejected badge with reason, the fee, and the total repayable. Rupees are formatted with `toLocaleString('en-IN')`.
- **WhatsApp box (bonus a):** English + Tamil text filled in from the result, with a Copy button (`navigator.clipboard`). The template lives in JS:
  - EN: `Hello {name}, as of {date} you can draw up to ₹{eligible} from Velli. A 2% fee is recovered on payday (10th).`
  - TA: `வணக்கம் {name}, {date} நிலவரப்படி நீங்கள் Velli-யிலிருந்து ₹{eligible} வரை முன்பணம் பெறலாம். 2% கட்டணம் சம்பள நாளில் (10ஆம் தேதி) பிடிக்கப்படும்.`
- **Workforce table (bonus b):** a "Show all workers" button that calls `/api/summary` for the chosen date. Columns: code, name, contractor, status, paid days, net earned, drawn, eligible.
- **Data notes panel:** a collapsible list from `/api/notes`.
- Plain CSS with a responsive single column. Errors from the API are shown inline, never with `alert()`.

## Expected numbers (for 16-Oct-2026: cycle 10/10–09/11, 31 days, 7 days so far, PF+ESI = ₹451.61)
| Worker | Paid | Earned | Drawn | Eligible | Notes |
|---|---|---|---|---|---|
| W101 Bikash (850) | 6 | 5,100 | 2,000 (Bikas draw on 15/10) | **300** | ₹2,000 request → Rejected |
| W102 Rahul MMG (850) | 5 | 4,250 | 1,500 | **300** | |
| W103 Rahul SE (989) | 6 | 5,934 | 0 | **2,700** | not given W102's draw |
| W104 Dipak (989) | 5 | 4,945 | 0 (Sep/3-Oct draws excluded) | **2,200** | ₹2,000 → Approved, fee 40, repay 2,040 |
| W105 Sunil (750) | 6 | 4,500 | 3,000 | **0** | negative clamped |
| W107 Hemanta (850) | 3 | 2,550 | 0 | **1,000** | lowercase `p` on 15-Oct counted |
| W108 Murugan (750) | 0 | 0 | 0 | **0** | |
| W109 Santosh | — | — | 2,000 | **0** | inactive → Rejected |

These go into `test_eligibility.py`, along with:
- `cycle_for` for 9-Oct (→ 10-Sep to 9-Oct), 10-Nov (→ 10-Nov to 9-Dec) and Dec→Jan
- the 10/11 payday draw being excluded on 9-Nov and included on 10-Nov

## Open questions to raise with Velli (brief says "don't guess silently")
1. **Is WO (weekly off) paid?** **Answered by Velli: yes, WO is paid; only A and blank are unpaid.** Implemented as `PAID_MARKS = {"P", "WO"}`. The "Expected numbers" table above was written before this answer. The current figures live in `test_eligibility.py`: W101 → 700, W104 → 2,700, W107 → 1,400.
2. Is ₹5,000 a cap per draw or per cycle? We follow the text: **per draw**.
3. Should a draw paid to an inactive worker (Santosh, 16/10) or to an unrelated UPI name (Selvi → Kannan S) be flagged to ops? We count it and surface it in the notes.
4. Murugan R: blanks before 26-Oct. Should a mid-cycle joiner's PF+ESI start from the joining date? We follow rule 3 literally (from cycle start).

## Build order (fits the 75 min)
1. `eligibility.py` + `test_eligibility.py`, then run the tests until the table above matches (core, ~30 min)
2. `app.py` endpoints (~10 min)
3. `index.html`/`app.js`/`style.css`: form + result card (~15 min)
4. Bonus a (WhatsApp), then bonus b (summary table), then the notes panel (~15 min)
5. README with findings + open questions

## Verification
- `python test_eligibility.py` → all asserts pass
- `pip install fastapi uvicorn` then `uvicorn app:app --reload`, and open http://127.0.0.1:8000
- Manual checks in the UI: W101/16-Oct/2000 → Rejected (eligible 300); W104/16-Oct/2000 → Approved, fee 40, repay 2,040; W109 → Rejected (inactive); Rahul Kumar typed by name via `/api/eligibility?worker=Rahul Kumar` → 400 listing W102/W103; summary table for 16-Oct shows 16 rows matching the table above.
- Edge dates: 9-Oct (previous cycle, no attendance → 0), 10-Nov (new cycle, payday draw counted), 20-Nov (missing columns treated as blank).

Skipped on purpose: auth, a database, editing data from the UI, CSV upload. None of these were asked for.
