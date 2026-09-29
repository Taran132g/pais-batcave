"""PAIS API on Oracle: authenticator login + the snapshot the Mac publishes every 15 minutes.

Read-only by design: agents never run from the site.
"""
import json
import time

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from datetime import date, datetime

from . import coinbase_view, config, daily_goal, intraday, live
from .canvas import TZ
from .portfolio import portfolio as _portfolio
from .auth import COOKIE, Authenticator, _read_env_value

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _temp_expiry() -> float | None:
    raw = _read_env_value(config.LOCAL_ENV_FILE, "TEMP_PASSCODE_EXPIRES")
    return float(raw) if raw else None


auth = Authenticator(temp_passcode_sha256=_read_env_value(config.LOCAL_ENV_FILE, "TEMP_PASSCODE_SHA256"),
                     temp_passcode_expires=_temp_expiry())


class LoginBody(BaseModel):
    code: str


class MarkBody(BaseModel):
    date: date
    url: str
    done: bool


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/bg/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.post("/login")
def login(body: LoginBody, response: Response):
    wait = auth.locked_for()
    if wait:
        raise HTTPException(status_code=429, detail=f"Lockdown engaged. Try again in {wait}s.")
    if not auth.verify_code(body.code):
        raise HTTPException(status_code=401, detail="Access denied.")
    response.set_cookie(COOKIE, auth.issue(), max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=True, samesite="strict", path=config.COOKIE_PATH)
    return {"ok": True}


@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path=config.COOKIE_PATH)
    return {"ok": True}


@app.get("/session")
def session(request: Request):
    return {"authenticated": auth.valid(request.cookies.get(COOKIE))}


@app.get("/snapshot")
def snapshot(request: Request):
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="Identify yourself.")
    try:
        data = json.loads(config.SNAPSHOT_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="The Batcomputer hasn't reported in yet.") from None
    age = int(time.time() - config.SNAPSHOT_FILE.stat().st_mtime)
    job_file = config.ROOT / "data/job.json"
    if job_file.exists():  # Job tab is computed on Oracle from Gmail, independent of the Mac
        try:
            data["job"] = json.loads(job_file.read_text())
        except json.JSONDecodeError:
            pass
    academics = config.ROOT / "data/academics.json"
    if academics.exists():  # Canvas pull, also on Oracle
        try:
            data["academics"] = json.loads(academics.read_text())
        except json.JSONDecodeError:
            pass
    data["daily"] = daily_goal.for_day(datetime.now(TZ).date())
    data["portfolio"] = _portfolio(data.get("roi") or {})
    return {**data, "age_s": age, "stale": age > config.STALE_AFTER_S}


@app.post("/daily/mark")
def daily_mark(body: MarkBody, request: Request):
    """Tick/untick one of the day's applications by hand (Gmail confirmations tick themselves)."""
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="Identify yourself.")
    try:
        return daily_goal.set_mark(body.date, body.url, body.done)
    except KeyError:
        raise HTTPException(status_code=404, detail="That job isn't on that day's list.") from None


BACKGROUNDS = {"bunker": config.ROOT / "assets/bunker.webp"}


@app.get("/bg/{name}")
def background(name: str, request: Request):
    """Signed-in background art. Behind the session so film stills aren't publicly downloadable."""
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="Identify yourself.")
    path = BACKGROUNDS.get(name)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="No such background.")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/coinbase")
def coinbase(request: Request):
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="Identify yourself.")
    if not config.COINBASE_KEY_FILE.exists():
        raise HTTPException(status_code=503, detail="Coinbase key not installed.")
    try:
        return coinbase_view.summary()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - upstream API errors shown on the tab
        raise HTTPException(status_code=502, detail=f"Coinbase: {type(exc).__name__}") from exc


@app.on_event("startup")
def _start_sampler():
    intraday.start()


@app.get("/candles")
def equity_candles(request: Request, tf: str = "15m"):
    """Whole-portfolio equity candles (1m, 5m, 15m, 1h, 4h, 1d) for the Trading chart."""
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="Identify yourself.")
    try:
        return {"tf": tf, "candles": intraday.candles(tf)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="No snapshot yet.") from None


@app.get("/live")
def live_marks(request: Request):
    """Positions re-marked at live prices; the site polls this every ~20s on the Trading tab."""
    if not auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="Identify yourself.")
    try:
        trading = json.loads(config.SNAPSHOT_FILE.read_text()).get("roi") or {}
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="No snapshot yet.") from None
    if trading.get("balance") is None:
        raise HTTPException(status_code=503, detail="Snapshot has no balance to mark.")
    return live.mark(trading)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
