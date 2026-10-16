"""FastAPI server for the Velli eligibility tool. Run: uvicorn app:app --reload"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from eligibility import Ambiguous, Register, WorkerNotFound

HERE = Path(__file__).parent
# Load and clean the CSVs once at start-up; restart the server after editing them
reg = Register(HERE / "attendance_register.csv", HERE / "draws.csv")

# Flag problems for ops as soon as the CSVs are imported
log = logging.getLogger("uvicorn.error")
for f in reg.flags:
    log.warning("FLAG [%s] %s", f["type"], f["message"])

app = FastAPI(title="Velli Eligibility")


@app.get("/api/workers")
def workers():
    """All workers (code, name, contractor, status) for the dropdown."""
    return reg.worker_list()


@app.get("/api/eligibility")
def eligibility(worker: str, date: date, amount: Optional[float] = None):
    """Eligibility for one worker on a date; with `amount`, also approve/reject, fee and repayable.

    `worker` is an emp_code (W101) or a name. FastAPI rejects a bad date or amount with 422.
    """
    try:
        w = reg.find_worker(worker)
    except WorkerNotFound as e:
        raise HTTPException(404, str(e))
    except Ambiguous as e:
        raise HTTPException(400, {"message": f"{e} — pick one by emp_code", "candidates": e.candidates})
    return reg.compute(w["emp_code"], date, amount)


@app.get("/api/summary")
def summary(date: date):
    """Bonus (b): every worker's limit on the chosen date."""
    return reg.summary(date)


@app.get("/api/flags")
def flags():
    """Import flags that need ops review (inactive worker paid, unrelated UPI payee, unmatched draw)."""
    return reg.flags


@app.get("/api/notes")
def notes():
    """Data problems found while cleaning the CSVs."""
    return reg.notes


# Mounted last so /api/* routes win; serves the UI from the same origin (no CORS needed)
app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
