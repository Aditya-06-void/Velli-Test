"""Velli wage-advance eligibility: data cleaning + business rules (TASK_BRIEF.pdf).

Loads attendance_register.csv and draws.csv once, cleans the messy values, and answers
"how much can this worker draw on date D?". Rule numbers in comments refer to the brief.
All money maths uses Fraction so rounding down to the nearest Rs 100 is exact (no float drift);
values are converted to 2-dp floats only for output.
"""
import csv
import difflib
import re
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

PAID_MARKS = {"P", "WO"}    # confirmed by Velli: weekly off is paid; only A and blank are unpaid
KNOWN_MARKS = {"P", "A", "WO", ""}
PF_ESI_PER_CYCLE = Fraction(2000)   # rule 3
MAX_PER_DRAW = 5000                 # rule 5
FEE_RATE = Fraction(2, 100)         # rule 7
FUZZY_CUTOFF = 0.85                 # "Bikas Oraon" vs "Bikash Oraon" scores ~0.96; unrelated names score far lower


class WorkerNotFound(Exception):
    """No worker matches the emp_code or name typed in."""


class Ambiguous(Exception):
    """A name matches more than one worker (e.g. two 'Rahul Kumar'); carries the candidates."""

    def __init__(self, query, candidates):
        super().__init__(f"'{query}' matches {len(candidates)} workers")
        self.candidates = candidates


def norm_name(s):
    """Lower-case and collapse whitespace so ' Selvi  K' and 'selvi k' compare equal."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def parse_rate(raw):
    """Turn messy money text ('₹989', '850.00', '1,500') into an exact Fraction."""
    return Fraction(re.sub(r"[₹,\s]", "", raw or "0"))


def cycle_for(d):
    """Rule 1: return (start, end) of the wage cycle containing d — 10th of one month to the 9th of the next.

    e.g. 16-Oct -> (10-Oct, 09-Nov); 09-Oct -> (10-Sep, 09-Oct); 15-Dec -> (10-Dec, 09-Jan next year).
    """
    y, m = d.year, d.month
    if d.day < 10:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(y, m, 10), date(ny, nm, 9)


def surname(name):
    """Last word of a name, used to tell family UPI accounts ('Pema Tamang' for 'Dipak Tamang') from unrelated ones."""
    parts = norm_name(name).split(" ")
    return parts[-1] if parts else ""


def money(x):
    """Fraction -> float rounded to paise, for JSON output only."""
    return round(float(x), 2)


class Register:
    """The cleaned data set plus the eligibility rules. Built once at server start-up.

    Import findings are kept at two levels:
      - `notes`: messy values cleaned automatically (info only), shown under "Data notes".
      - `flags`: money problems ops must review (inactive worker paid, unrelated UPI payee,
        unmatched draw). Logged at start-up and shown prominently in the UI. Flags never change
        the numbers: a flagged draw still counts against the worker.
    """

    def __init__(self, attendance_csv, draws_csv):
        self.notes = []
        self.flags = []     # {"type", "emp_code", "date", "message"}
        self.workers = {}   # emp_code -> worker dict
        self.dates = []     # dates that have a column in the register
        self._load_attendance(Path(attendance_csv))
        self.draws = []     # draws matched to an emp_code
        self._load_draws(Path(draws_csv))

    def _flag(self, kind, emp_code, d, message):
        self.flags.append({"type": kind, "emp_code": emp_code, "date": d.isoformat(), "message": message})

    # ---------- loading / cleaning ----------
    def _load_attendance(self, path):
        """Read the register: clean rates and marks, and note anything unusual."""
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        # Any header that parses as dd-Mon-yyyy is a day column; the rest are worker fields
        date_cols = {}
        for col in rows[0].keys():
            try:
                date_cols[col] = datetime.strptime(col.strip(), "%d-%b-%Y").date()
            except ValueError:
                pass
        self.dates = sorted(date_cols.values())

        for r in rows:
            code = r["emp_code"].strip().upper()
            raw_rate = r["per_day_rate"]
            rate = parse_rate(raw_rate)
            if raw_rate.strip() != str(rate):
                self.notes.append(f"{code} {r['worker_name'].strip()}: per-day rate '{raw_rate}' cleaned to ₹{rate}")
            marks = {}
            for col, d in date_cols.items():
                raw = r.get(col) or ""
                mark = raw.strip().upper()
                if raw != mark:
                    self.notes.append(f"{code}: mark '{raw}' on {d:%d-%b-%Y} read as '{mark}'")
                if mark not in KNOWN_MARKS:
                    self.notes.append(f"{code}: unknown mark '{raw}' on {d:%d-%b-%Y} treated as unpaid")
                marks[d] = mark
            status = r["status"].strip()
            self.workers[code] = {
                "emp_code": code,
                "name": r["worker_name"].strip(),
                "contractor": r["contractor"].strip().upper(),
                "grade": r["grade"].strip(),
                "rate": rate,
                "status": status,
                "active": status.lower() == "active",
                "marks": marks,
            }

        # Blank days that only some workers have (e.g. a mid-cycle joiner, or no entries after going inactive)
        blanks = {c: {d for d, m in w["marks"].items() if m == ""} for c, w in self.workers.items()}
        common = set.intersection(*blanks.values()) if blanks else set()
        for code, b in blanks.items():
            extra = sorted(b - common)
            if extra:
                w = self.workers[code]
                self.notes.append(f"{code} {w['name']}: {len(extra)} blank day(s) between {extra[0]:%d-%b} and "
                                  f"{extra[-1]:%d-%b} (status {w['status']}); counted as unpaid")

        names = {}
        for w in self.workers.values():
            names.setdefault(norm_name(w["name"]), []).append(w)
        for same in names.values():
            if len(same) > 1:
                self.notes.append("Duplicate name '" + same[0]["name"] + "': " +
                                  ", ".join(f"{w['emp_code']} ({w['contractor']})" for w in same) +
                                  "; draws are matched on name + contractor")

    def _load_draws(self, path):
        """Read past advances and tie each one to a single emp_code.

        Match on (name, contractor) because names alone are not unique. If the spelling differs,
        fall back to the closest name under the same contractor. Unmatched draws are flagged, never dropped silently.
        """
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            name, contractor = r["worker_name"].strip(), r["contractor"].strip().upper()
            d = datetime.strptime(r["draw_date"].strip(), "%d/%m/%Y").date()
            amount = parse_rate(r["amount_rs"])
            label = f"Draw {d:%d/%m/%Y} ₹{amount} '{name}' ({contractor})"
            same_contractor = [w for w in self.workers.values() if w["contractor"] == contractor]
            hits = [w for w in same_contractor if norm_name(w["name"]) == norm_name(name)]
            if not hits:
                close = difflib.get_close_matches(norm_name(name), [norm_name(w["name"]) for w in same_contractor],
                                                  n=1, cutoff=FUZZY_CUTOFF)
                hits = [w for w in same_contractor if close and norm_name(w["name"]) == close[0]]
                if hits:
                    self.notes.append(f"{label}: name spelt differently, matched to {hits[0]['emp_code']} {hits[0]['name']}")
            if len(hits) != 1:
                self._flag("unmatched_draw", None, d, f"{label}: could not be matched to exactly one worker; NOT counted")
                continue
            w = hits[0]
            paid_to = r["paid_to_name"].strip()
            if norm_name(paid_to) not in (norm_name(w["name"]), norm_name(name)):
                # shortcut: a shared surname = family. South Indian names often end in an initial
                # (Selvi K, Kannan S), so a relative can still be flagged; upgrade to a payee whitelist if ops want one.
                if surname(paid_to) == surname(w["name"]):
                    self.notes.append(f"{label}: paid to family UPI '{paid_to}' (same surname); counted against {w['emp_code']}")
                else:
                    self._flag("unrelated_payee", w["emp_code"], d,
                               f"{label}: paid to UPI of '{paid_to}', a different surname from {w['name']}; "
                               f"still counted against {w['emp_code']}, please verify")
            if not w["active"]:
                self._flag("inactive_paid", w["emp_code"], d,
                           f"{label}: paid out although {w['emp_code']} {w['name']} is {w['status']}")
            self.draws.append({"emp_code": w["emp_code"], "date": d, "amount": amount,
                               "paid_to": paid_to, "upi_ref": r["upi_ref"].strip()})

    # ---------- lookup ----------
    def find_worker(self, query):
        """Look up by emp_code (any case) or exact name; raise Ambiguous if a name is shared."""
        q = (query or "").strip()
        if q.upper() in self.workers:
            return self.workers[q.upper()]
        hits = [w for w in self.workers.values() if norm_name(w["name"]) == norm_name(q)]
        if not hits:
            raise WorkerNotFound(f"No worker matches '{q}'")
        if len(hits) > 1:
            raise Ambiguous(q, [{"emp_code": w["emp_code"], "name": w["name"], "contractor": w["contractor"]}
                                for w in hits])
        return hits[0]

    def worker_list(self):
        """Minimal worker info for the UI dropdown."""
        return [{k: w[k] for k in ("emp_code", "name", "contractor", "status")} for w in self.workers.values()]

    # ---------- rules ----------
    def compute(self, emp_code, d, amount=None):
        """Everything ops needs for one worker on date d, plus a decision if an amount is requested.

        Only attendance and draws from cycle start up to d are used (rule 8).
        """
        w = self.workers[emp_code]
        start, end = cycle_for(d)                      # rule 1
        total_days = (end - start).days + 1
        days_so_far = (d - start).days + 1             # inclusive of d

        # Rule 2: P and WO are paid; A and blank are not. Days with no register column count as blank.
        paid_days = sum(1 for day, m in w["marks"].items() if start <= day <= d and m in PAID_MARKS)
        earned = w["rate"] * paid_days
        pf_esi = PF_ESI_PER_CYCLE * days_so_far / total_days   # rule 3: prorated by calendar days
        net = earned - pf_esi                                   # rule 4
        # Draws before cycle start belong to the previous cycle; draws after d haven't happened yet
        counted = [x for x in self.draws if x["emp_code"] == emp_code and start <= x["date"] <= d]
        drawn = sum((x["amount"] for x in counted), Fraction(0))

        # Rule 5: 50% of net minus this cycle's draws, floored to Rs 100, kept between 0 and 5,000. Rule 6: inactive -> 0.
        if w["active"]:
            eligible = min(MAX_PER_DRAW, max(0, int((net / 2 - drawn) // 100) * 100))
        else:
            eligible = 0

        # Warn ops when the register can't support the answer (date outside the data we have)
        warnings = []
        if not any(start <= day <= d for day in self.dates):
            warnings.append("No attendance recorded in the register for this cycle up to this date.")
        elif self.dates and d > self.dates[-1]:
            warnings.append(f"Register only has attendance up to {self.dates[-1]:%d-%b-%Y}.")

        result = {
            "emp_code": w["emp_code"], "name": w["name"], "contractor": w["contractor"],
            "status": w["status"], "rate": money(w["rate"]),
            "date": d.isoformat(), "cycle_start": start.isoformat(), "cycle_end": end.isoformat(),
            "total_cycle_days": total_days, "days_so_far": days_so_far,
            "paid_days": paid_days, "earned": money(earned), "pf_esi": money(pf_esi),
            "net_earned": money(net), "already_drawn": money(drawn),
            "draws": [{"date": x["date"].isoformat(), "amount": money(x["amount"]), "paid_to": x["paid_to"],
                       "upi_ref": x["upi_ref"]} for x in counted],
            "eligible": eligible, "warnings": warnings, "request": None,
            # All import flags for this worker, regardless of date: they are review items, not calculation inputs
            "flags": [f for f in self.flags if f["emp_code"] == emp_code],
        }

        if amount is not None:
            amt = Fraction(str(amount))     # via str so 1999.99 stays exact
            fee = amt * FEE_RATE            # rule 7: fee is on top; worker gets the full amount
            # First failing check gives the rejection reason
            if amt <= 0:
                status, reason = "Rejected", "Requested amount must be more than ₹0"
            elif not w["active"]:
                status, reason = "Rejected", f"Worker is {w['status']}; inactive workers can't draw"
            elif amt > MAX_PER_DRAW:
                status, reason = "Rejected", f"Exceeds the ₹{MAX_PER_DRAW:,} maximum per draw"
            elif amt > eligible:
                status, reason = "Rejected", f"Exceeds eligible amount of ₹{eligible:,}"
            else:
                status, reason = "Approved", ""
            result["request"] = {"amount": money(amt), "status": status, "reason": reason,
                                 "fee": money(fee), "repayable": money(amt + fee)}
        return result

    def summary(self, d):
        """Bonus (b): every worker's numbers on date d."""
        return [self.compute(code, d) for code in self.workers]
