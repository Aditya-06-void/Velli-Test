# Velli Draw Check

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
| `app.py` | FastAPI: `/api/workers`, `/api/eligibility`, `/api/summary`, `/api/notes`, plus the static UI |
| `static/` | HTML/CSS/JS UI: result card, WhatsApp message (EN + Tamil), all-workers table, data notes |

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
- **Inactive worker paid:** Santosh Nayak (W109, Inactive) received ₹2,000 on 16/10. It is counted, and his eligibility is ₹0. He has no attendance entries after 31-Oct.
- **Paid to someone else's UPI:** Pema Tamang, Sumitra Hansda, Rina Oraon and Laxmi Munda look like family members. **Selvi K → `Kannan S`** has a different surname and is worth checking. All are still counted against the worker.
- **Mid-cycle joiner?** Murugan R (W108) is blank from 10–25 Oct. Blanks are unpaid, so his early-cycle eligibility is ₹0.
- The register only covers 10-Oct to 15-Nov-2026. For dates outside it, the UI shows a warning.

The same list is generated live from the CSVs under "Data notes" in the UI.

## Open questions for Velli
1. ~~Is WO (weekly off) paid?~~ **Answered: yes.** Only A and blank are unpaid. Set by `PAID_MARKS = {"P", "WO"}` in `eligibility.py`.
2. Is ₹5,000 a cap per draw or per cycle? We cap **per draw**, as written.
3. Should draws to an inactive worker or to an unrelated UPI name be blocked or flagged? We count them and flag them in the notes.
4. Should a mid-cycle joiner's PF+ESI be prorated from the joining date? We follow rule 3 literally and prorate from the cycle start.
