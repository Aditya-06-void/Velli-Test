"""Velli wage-advance eligibility: data cleaning + business rules (TASK_BRIEF.pdf)."""
import csv
import difflib
import re
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

PAID_MARKS = {"P", "WO"}    # confirmed by Velli: weekly off is paid; only A and blank are unpaid
KNOWN_MARKS = {"P", "A", "WO", ""}
PF_ESI_PER_CYCLE = Fraction(2000)
MAX_PER_DRAW = 5000
FEE_RATE = Fraction(2, 100)
FUZZY_CUTOFF = 0.85


class WorkerNotFound(Exception):
    pass


class Ambiguous(Exception):
    def __init__(self, query, candidates):
        super().__init__(f"'{query}' matches {len(candidates)} workers")
        self.candidates = candidates


def norm_name(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def parse_rate(raw):
    return Fraction(re.sub(r"[₹,\s]", "", raw or "0"))


def cycle_for(d):
    """Wage cycle: 10th of one month to the 9th of the next."""
    y, m = d.year, d.month
    if d.day < 10:
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(y, m, 10), date(ny, nm, 9)


def money(x):
    return round(float(x), 2)


class Register:
    def __init__(self, attendance_csv, draws_csv):
        self.notes = []
        self.workers = {}   # emp_code -> worker dict
        self.dates = []     # dates that have a column in the register
        self._load_attendance(Path(attendance_csv))
        self.draws = []     # draws matched to an emp_code
        self._load_draws(Path(draws_csv))

    # ---------- loading / cleaning ----------
    def _load_attendance(self, path):
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
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
                self.notes.append(f"{label}: could not be matched to exactly one worker; NOT counted")
                continue
            w = hits[0]
            paid_to = r["paid_to_name"].strip()
            if norm_name(paid_to) != norm_name(name):
                self.notes.append(f"{label}: paid to UPI of '{paid_to}', not the worker; still counted against {w['emp_code']}")
            if not w["active"]:
                self.notes.append(f"{label}: paid out although {w['emp_code']} is {w['status']}")
            self.draws.append({"emp_code": w["emp_code"], "date": d, "amount": amount,
                               "paid_to": paid_to, "upi_ref": r["upi_ref"].strip()})

    # ---------- lookup ----------
    def find_worker(self, query):
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
        return [{k: w[k] for k in ("emp_code", "name", "contractor", "status")} for w in self.workers.values()]

    # ---------- rules ----------
    def compute(self, emp_code, d, amount=None):
        w = self.workers[emp_code]
        start, end = cycle_for(d)
        total_days = (end - start).days + 1
        days_so_far = (d - start).days + 1

        paid_days = sum(1 for day, m in w["marks"].items() if start <= day <= d and m in PAID_MARKS)
        earned = w["rate"] * paid_days
        pf_esi = PF_ESI_PER_CYCLE * days_so_far / total_days
        net = earned - pf_esi
        counted = [x for x in self.draws if x["emp_code"] == emp_code and start <= x["date"] <= d]
        drawn = sum((x["amount"] for x in counted), Fraction(0))

        if w["active"]:
            eligible = min(MAX_PER_DRAW, max(0, int((net / 2 - drawn) // 100) * 100))
        else:
            eligible = 0

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
        }

        if amount is not None:
            amt = Fraction(str(amount))
            fee = amt * FEE_RATE
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
        return [self.compute(code, d) for code in self.workers]
