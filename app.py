"""FastAPI server for the Velli eligibility tool. Run: uvicorn app:app --reload"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from eligibility import Ambiguous, Register, WorkerNotFound

HERE = Path(__file__).parent
# Load and clean the CSVs once at start-up; restart the server after editing them
reg = Register(HERE / "attendance_register.csv", HERE / "draws.csv")

# Flag problems for ops as soon as the CSVs are imported
log = logging.getLogger("uvicorn.error")
for f in reg.flags:
    log.warning("FLAG [%s] %s", f["type"], f["message"])

app = FastAPI(title="Velli Eligibility")


class VercelPathMiddleware:
    """Corrects ASGI scope['path'] if Vercel URL rewrite or serverless routing alters it."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            # Vercel passes the original incoming URI in x-matched-path or x-forwarded-uri
            forwarded = headers.get(b"x-matched-path") or headers.get(b"x-forwarded-uri")
            if forwarded:
                orig_path = forwarded.decode("latin-1").split("?")[0]
                if scope.get("path", "").startswith("/api/index") and not orig_path.startswith("/api/index"):
                    scope["path"] = orig_path
        await self.app(scope, receive, send)


app.add_middleware(VercelPathMiddleware)

api_router = APIRouter()


@api_router.get("/debug")
def debug(request: Request):
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in request.scope.get("headers", [])}
    return {
        "scope_path": request.scope.get("path"),
        "headers": headers,
    }


@api_router.get("/workers")
def workers():
    """All workers (code, name, contractor, status) for the dropdown."""
    return reg.worker_list()


@api_router.get("/eligibility")
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


@api_router.get("/summary")
def summary(date: date):
    """Bonus (b): every worker's limit on the chosen date."""
    return reg.summary(date)


@api_router.get("/flags")
def flags():
    """Import flags that need ops review (inactive worker paid, unrelated UPI payee, unmatched draw)."""
    return reg.flags


@api_router.get("/notes")
def notes():
    """Data problems found while cleaning the CSVs."""
    return reg.notes


# Mount router both with '/api' prefix and without prefix so it works regardless of whether
# the platform (e.g. Vercel) strips '/api' or preserves it, as well as local uvicorn.
app.include_router(api_router, prefix="/api")
app.include_router(api_router)

# Mounted last so /api/* routes win; serves the UI from the same origin (no CORS needed)
app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
