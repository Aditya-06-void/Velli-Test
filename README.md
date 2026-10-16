# Velli Draw Check.

Answers one question for the operations team: **how much can this worker draw today?**

## Run
```
pip install -r requirements.txt
uvicorn app:app --reload
```
Open http://127.0.0.1:8000. Pick a worker and a date, and optionally enter a requested amount.

Self-checks: `python test_eligibility.py`

| File | What |
|---|---|
| `eligibility.py` | data cleaning + the 8 rules (stdlib only, exact `Fraction` maths) |
| `app.py` | FastAPI: `/api/workers`, `/api/eligibility`, `/api/summary`, `/api/flags`, `/api/notes`, plus the static UI |
| `static/` | HTML/CSS/JS UI: flags panel, result card, WhatsApp message (EN + Tamil), all-workers table, data notes |

API example: `/api/eligibility?worker=W104&date=2026-10-16&amount=2000`. `worker` can be an emp_code or a name. A duplicate name returns 400 with the candidates.

## Rules as implemented
- Cycle runs from the 10th to the 9th of the next month. On 16-Oct-2026 that is 10/10/2026–09/11/2026 (31 days).
- Paid days = `P` and `WO` marks from cycle start to the chosen date, inclusive (Velli confirmed weekly off is paid). `A` and blank are unpaid.
- PF+ESI = 2000 × days so far ÷ cycle days.
- Eligible = 50% × (earned − PF+ESI) − drawn this cycle, rounded down to ₹100, then clamped to 0–5,000. It is 0 for inactive workers.
- Request decision, checked in this order: invalid amount (≤ 0) → inactive → over ₹5,000 → over eligible → Approved. Fee = 2%. Repayable = amount + fee.
- Attendance and draws dated after the chosen date are ignored. Draws before the cycle start belong to the previous cycle.

## What we found in the data
- **Dirty rates:** W106 `₹989` and W107 `850.00` are cleaned to numbers.
- **Messy marks:** W107 has `p` on 15-Oct and 20-Oct and `P ` (trailing space) on 27-Oct. All are read as `P`.
- **Spelling:** the draws file has `Bikas Oraon` while the register has `Bikash Oraon` (W101). They are matched by fuzzy name *within the same contractor* and logged.
- **Duplicate name:** `Rahul Kumar` is both W102 (MMG) and W103 (SE). Draws are matched on name + contractor, so the MMG draws go to W102 only.
- **Out-of-cycle draws:** Dipak Tamang's 25/09 and 03/10 draws fall in the previous cycle. Bijay Hansda's 10/11 draw is on payday and starts the next cycle.
- **Inactive worker paid (FLAGGED):** Santosh Nayak (W109, Inactive) received ₹2,000 on 16/10. It is counted, and his eligibility is ₹0. He has no attendance entries after 31-Oct.
- **Paid to someone else's UPI:** Pema Tamang, Sumitra Hansda, Rina Oraon and Laxmi Munda share the worker's surname, so they are treated as family and noted. **Selvi K → `Kannan S` (FLAGGED)** has a different surname. All of these draws are still counted against the worker.
- **Mid-cycle joiner?** Murugan R (W108) is blank from 10–25 Oct. Blanks are unpaid, so his early-cycle eligibility is ₹0.
- The register only covers 10-Oct to 15-Nov-2026. For dates outside it, the UI shows a warning.

The same list is generated live from the CSVs and shown in the UI.

## Flags raised at import
Velli asked us to **flag suspicious draws when the CSVs are imported**. Everything the importer finds goes into one of two levels:

| Level | Meaning | Examples |
|---|---|---|
| **Note** | Messy value cleaned automatically. Info only. | `₹989` rate, lowercase `p`, `Bikas` → `Bikash`, family UPI payee |
| **Flag** | Money problem that ops must review | see the table below |

| Flag type | Raised when | Found in this data |
|---|---|---|
| `inactive_paid` | a draw was paid to a worker whose status is not Active | Santosh Nayak (W109), ₹2,000 on 16/10 |
| `unrelated_payee` | `paid_to_name` is not the worker and has a different surname | Selvi K (W112) → Kannan S, ₹2,500 on 27/10 |
| `unmatched_draw` | a draw can't be tied to exactly one worker (name + contractor). It is **not** counted. | none |

**Where flags appear:**
1. **Server console at import.** One `WARNING: FLAG [type] …` line per flag, printed when the server starts.
2. **Red "Flags for ops" panel** at the top of the page. It is hidden when there are no flags.
3. **The affected worker's result card,** so whoever checks W112 or W109 sees the flag right next to the numbers.
4. **`GET /api/flags`,** which returns JSON `[{type, emp_code, date, message}]` for other tools.

**Design choices:**
- **Flags don't change the numbers.** The money was really paid out, so a flagged draw still counts against the worker's limit. A flag asks a person to check the draw; it doesn't undo it.
- **The family check is a shortcut:** a shared surname means family. Many South Indian names end in an initial (Selvi K, Kannan S), so a real relative can still be flagged. That is the safe direction to be wrong in. If ops want fewer false alarms, the next step is a list of approved payees per worker.
- **Flags are kept separate from notes,** so the handful of items that need a person don't get lost among routine cleaning messages.

## Open questions for Velli
1. ~~Is WO (weekly off) paid?~~ **Answered: yes.** Only A and blank are unpaid. Set by `PAID_MARKS = {"P", "WO"}` in `eligibility.py`.
2. Is ₹5,000 a cap per draw or per cycle? We cap **per draw**, as written.
3. ~~Should draws to an inactive worker or to an unrelated UPI name be flagged?~~ **Answered: yes, flag them at import.** See "Flags raised at import" above.
4. Should a mid-cycle joiner's PF+ESI be prorated from the joining date? We follow rule 3 literally and prorate from the cycle start.
