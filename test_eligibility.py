"""Assert-based checks against hand-computed examples. Run: python test_eligibility.py"""
from datetime import date
from pathlib import Path

from eligibility import Ambiguous, Register, cycle_for

HERE = Path(__file__).parent
reg = Register(HERE / "attendance_register.csv", HERE / "draws.csv")
D = date(2026, 10, 16)

# cycle boundaries
assert cycle_for(D) == (date(2026, 10, 10), date(2026, 11, 9))
assert cycle_for(date(2026, 10, 9)) == (date(2026, 9, 10), date(2026, 10, 9))
assert cycle_for(date(2026, 11, 10)) == (date(2026, 11, 10), date(2026, 12, 9))
assert cycle_for(date(2026, 12, 15)) == (date(2026, 12, 10), date(2027, 1, 9))
assert cycle_for(date(2027, 1, 3)) == (date(2026, 12, 10), date(2027, 1, 9))

# code: (paid_days, earned, drawn, eligible) -- P and WO are paid, A and blank are not
expected = {
    "W101": (7, 5950, 2000, 700),   # 'Bikas Oraon' draw matched
    "W102": (6, 5100, 1500, 800),   # Rahul Kumar MMG gets the draw
    "W103": (7, 6923, 0, 3200),     # Rahul Kumar SE does not
    "W104": (6, 5934, 0, 2700),     # Sep / 3-Oct draws are previous cycle; 16-Oct is A
    "W105": (7, 5250, 3000, 0),     # negative clamped to 0
    "W106": (7, 6923, 0, 3200),     # '₹989' rate
    "W107": (4, 3400, 0, 1400),     # lowercase 'p' counted, '850.00' rate
    "W108": (0, 0, 0, 0),           # blanks unpaid (11-Oct WO slot is blank too)
    "W109": (7, 5950, 2000, 0),     # inactive
}
for code, (paid, earned, drawn, elig) in expected.items():
    r = reg.compute(code, D)
    got = (r["paid_days"], r["earned"], r["already_drawn"], r["eligible"])
    assert got == (paid, earned, drawn, elig), (code, got)
    assert r["pf_esi"] == 451.61 and r["cycle_end"] == "2026-11-09", code

# requests
r = reg.compute("W101", D, 2000)["request"]
assert r["status"] == "Rejected" and "700" in r["reason"], r
r = reg.compute("W104", D, 2000)["request"]
assert r == {"amount": 2000, "status": "Approved", "reason": "", "fee": 40, "repayable": 2040}, r
assert reg.compute("W109", D, 1000)["request"]["status"] == "Rejected"
assert reg.compute("W104", D, 0)["request"]["status"] == "Rejected"
assert reg.compute("W114", date(2026, 11, 9), 6000)["request"]["reason"].startswith("Exceeds the")

# 'P ' with trailing space on 27-Oct counts for W107
assert reg.compute("W107", date(2026, 10, 27))["paid_days"] - reg.compute("W107", date(2026, 10, 26))["paid_days"] == 1

# payday draw on 10/11 belongs to the next cycle; future draws ignored
assert reg.compute("W113", date(2026, 11, 9))["already_drawn"] == 3000
assert reg.compute("W113", date(2026, 11, 10))["already_drawn"] == 1000
assert reg.compute("W105", D)["already_drawn"] == 3000   # 24/10 and 05/11 draws are after D

# eligible never exceeds 5000
assert all(x["eligible"] <= 5000 for x in reg.summary(date(2026, 11, 9)))

# lookup
assert reg.find_worker("w104")["name"] == "Dipak Tamang"
assert reg.find_worker("selvi k")["emp_code"] == "W112"
try:
    reg.find_worker("Rahul Kumar")
    raise AssertionError("expected Ambiguous")
except Ambiguous as e:
    assert {c["emp_code"] for c in e.candidates} == {"W102", "W103"}

assert len(reg.draws) == 19, len(reg.draws)   # every draw matched

# import flags: inactive worker paid, unrelated UPI payee; family payees (same surname) are notes, not flags
kinds = sorted((f["type"], f["emp_code"], f["date"]) for f in reg.flags)
assert kinds == [("inactive_paid", "W109", "2026-10-16"), ("unrelated_payee", "W112", "2026-10-27")], kinds
assert any("Pema Tamang" in n for n in reg.notes)
assert len(reg.compute("W112", D)["flags"]) == 1 and reg.compute("W104", D)["flags"] == []
assert reg.compute("W112", date(2026, 10, 27))["already_drawn"] == 4500   # flagged draw still counted
print("All checks passed.")
for f in reg.flags:
    print(" FLAG", f["message"])
for n in reg.notes:
    print(" -", n)
