"""FastAPI server for the Velli eligibility tool. Run: uvicorn app:app --reload"""
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from eligibility import Ambiguous, Register, WorkerNotFound

HERE = Path(__file__).parent
reg = Register(HERE / "attendance_register.csv", HERE / "draws.csv")

app = FastAPI(title="Velli Eligibility")


@app.get("/api/workers")
def workers():
    return reg.worker_list()


@app.get("/api/eligibility")
def eligibility(worker: str, date: date, amount: Optional[float] = None):
    try:
        w = reg.find_worker(worker)
    except WorkerNotFound as e:
        raise HTTPException(404, str(e))
    except Ambiguous as e:
        raise HTTPException(400, {"message": f"{e} — pick one by emp_code", "candidates": e.candidates})
    return reg.compute(w["emp_code"], date, amount)


@app.get("/api/summary")
def summary(date: date):
    return reg.summary(date)


@app.get("/api/notes")
def notes():
    return reg.notes


app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
