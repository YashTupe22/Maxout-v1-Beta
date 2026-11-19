"""Local dashboard API for the MaxOut AI trading project.

Serves dataset/model metadata, streams training runs and exposes the
live EA telemetry written by AITrader to Common\\Files\\AI\\live_status.json.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import broker

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "Models"
RUNS = MODELS / "runs"
TRAINER = ROOT / "python" / "train_onnx.py"
STATUS_FILE = MODELS / "live_status.json"
NEWS_PAUSE_FILE = MODELS / "news_pause.json"
DB_FILE = ROOT / "Models" / "jobs.db"
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

app = FastAPI(title="MaxOut AI Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_summary_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}

def _init_db() -> None:
    try:
        MODELS.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT,
                    created TEXT,
                    finished TEXT,
                    exit_code INTEGER,
                    csv TEXT,
                    model TEXT,
                    run TEXT,
                    command TEXT,
                    meta TEXT,
                    log TEXT
                )
            """)
            conn.commit()
    except Exception as exc:
        print(f"[warning] SQLite init failed: {exc}")

_init_db()

def _save_job_to_db(job: dict[str, Any]) -> None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs 
                (id, status, created, finished, exit_code, csv, model, run, command, meta, log)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job["id"],
                job["status"],
                job["created"],
                job["finished"],
                job["exit_code"],
                job["csv"],
                job["model"],
                job["run"],
                job["command"],
                json.dumps(job["meta"]) if job.get("meta") else None,
                json.dumps(job["log"]) if job.get("log") else None,
            ))
            conn.commit()
    except Exception as exc:
        print(f"[warning] SQLite save failed: {exc}")

def _load_job_from_db(job_id: str) -> dict[str, Any] | None:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, status, created, finished, exit_code, csv, model, run, command, meta, log FROM jobs WHERE id=?", (job_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "status": row[1],
                "created": row[2],
                "finished": row[3],
                "exit_code": row[4],
                "csv": row[5],
                "model": row[6],
                "run": row[7],
                "command": row[8],
                "meta": json.loads(row[9]) if row[9] else None,
                "log": json.loads(row[10]) if row[10] else [],
            }
    except Exception as exc:
        print(f"[warning] SQLite load failed: {exc}")
        return None

def _load_recent_jobs_from_db(limit: int = 20) -> list[dict[str, Any]]:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, status, created, finished, exit_code, csv, model, run, command, meta, log FROM jobs ORDER BY created DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row[0],
                    "status": row[1],
                    "created": row[2],
                    "finished": row[3],
                    "exit_code": row[4],
                    "csv": row[5],
                    "model": row[6],
                    "run": row[7],
                    "command": row[8],
                    "meta": json.loads(row[9]) if row[9] else None,
                    "log": json.loads(row[10]) if row[10] else [],
                })
            return results
    except Exception as exc:
        print(f"[warning] SQLite query failed: {exc}")
        return []

class TrainRequest(BaseModel):
    csv: str = Field(..., description="CSV file name inside Models/")
    model: str = Field("mlp", pattern="^(mlp|logreg|xgb|lgbm)$")
    hidden: str = "32,16"
    threshold: float = 0.55
    cv_splits: int = 5
    cv_gap: int = 24

class NewsPauseRequest(BaseModel):
    pause_minutes: int = Field(60, ge=1, le=1440)
    reason: str = Field("News Event", max_length=100)


class ActivateRequest(BaseModel):
    name: str


class TradeOrderRequest(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=32)
    side: str = Field(..., pattern="^(buy|sell)$")
    volume: float = Field(0.01, gt=0, le=500)
    sl_points: int = Field(0, ge=0, le=1_000_000)
    tp_points: int = Field(0, ge=0, le=1_000_000)
    risk_percent: float = Field(0.0, ge=0.0, le=10.0)
    max_spread_pts: int = Field(30, ge=1, le=1000)
    comment: str = Field("", max_length=31)


class TradeCloseRequest(BaseModel):
    ticket: int = Field(..., gt=0)
    volume: float | None = Field(None, gt=0, le=500)


class TradeCloseAllRequest(BaseModel):
    symbol: str | None = None


def _safe_model_path(name: str) -> Path:
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(400, "invalid path")
    path = (MODELS / rel).resolve()
    if MODELS.resolve() not in path.parents and path.parent != MODELS.resolve():
        raise HTTPException(400, "invalid path")
    return path


def _dataset_summary(path: Path) -> dict[str, Any]:
    stat = path.stat()
    key = str(path)
    cached = _summary_cache.get(key)
    if cached and cached[0] == (int(stat.st_mtime), stat.st_size):
        return cached[1]

    with path.open("r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {"rows": 0, "features": 0, "up_rate": 0.0}

        i_label = header.index("label") if "label" in header else -1
        i_time = header.index("time") if "time" in header else -1
        rows = ups = 0
        first = last = None
        for row in reader:
            if not row:
                continue
            rows += 1
            if i_label >= 0 and row[i_label] == "1":
                ups += 1
            if i_time >= 0:
                t = row[i_time]
                if first is None:
                    first = t
                last = t

    features = len([c for c in header if c not in ("time", "fwd", "label")])
    summary = {
        "name": path.name,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "rows": rows,
        "features": features,
        "up_rate": (ups / rows) if rows else 0.0,
        "first_row": first,
        "last_row": last,
    }
    _summary_cache[key] = ((int(stat.st_mtime), stat.st_size), summary)
    return summary


def _datasets() -> list[dict[str, Any]]:
    if not MODELS.exists():
        return []
    items = []
    for path in sorted(MODELS.glob("features_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            items.append(_dataset_summary(path))
        except OSError:
            continue
    return items


def _read_meta(onnx_path: Path) -> dict[str, Any] | None:
    meta_path = onnx_path.with_suffix(".json")
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _models() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not MODELS.exists():
        return items

    candidates = list(MODELS.glob("*.onnx")) + (list(RUNS.glob("*.onnx")) if RUNS.exists() else [])
    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        meta = _read_meta(path)
        rel = path.relative_to(MODELS).as_posix()
        items.append(
            {
                "name": rel,
                "file": path.name,
                "active": rel == "model.onnx",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "meta": meta,
            }
        )
    items.sort(key=lambda m: m["modified"], reverse=True)
    items.sort(key=lambda m: m["active"], reverse=True)
    return items


_PERIOD_SECONDS = {
    "PERIOD_M1": 60, "PERIOD_M2": 120, "PERIOD_M3": 180, "PERIOD_M4": 240,
    "PERIOD_M5": 300, "PERIOD_M6": 360, "PERIOD_M10": 600, "PERIOD_M12": 720,
    "PERIOD_M15": 900, "PERIOD_M20": 1200, "PERIOD_M30": 1800,
    "PERIOD_H1": 3600, "PERIOD_H2": 7200, "PERIOD_H3": 10800, "PERIOD_H4": 14400,
    "PERIOD_H6": 21600, "PERIOD_H8": 28800, "PERIOD_H12": 43200,
    "PERIOD_D1": 86400, "PERIOD_W1": 604800, "PERIOD_MN1": 2592000,
}


def _read_status() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {"available": False}
    try:
        raw = STATUS_FILE.read_text(encoding="utf-8", errors="replace")
        raw = raw.strip().lstrip("\ufeff").strip()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {"available": False, "error": "unreadable"}
    age = max(0.0, time.time() - STATUS_FILE.stat().st_mtime)
    period = _PERIOD_SECONDS.get(str(data.get("period", "")), 3600)
    data["available"] = True
    data["age_seconds"] = round(age, 1)
    data["fresh"] = age <= max(180.0, period * 1.5 + 60.0)
    # Pass local ISO modified time so frontend timeAgo calculation matches local clock
    data["file_mtime"] = datetime.fromtimestamp(STATUS_FILE.stat().st_mtime).isoformat(timespec="seconds")
    return data


def _job_public(job: dict[str, Any], include_log: bool = False) -> dict[str, Any]:
    out = {k: job[k] for k in ("id", "status", "created", "finished", "exit_code",
                               "csv", "model", "run", "command", "meta")}
    out["log_lines"] = len(job["log"])
    if include_log:
        out["log"] = list(job["log"])
    return out


def _archive_success(job: dict[str, Any]) -> None:
    onnx = MODELS / "model.onnx"
    meta = MODELS / "model.json"
    if not onnx.exists():
        return
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"model_{stamp}.onnx"
    try:
        shutil.copy2(onnx, RUNS / run_name)
        if meta.exists():
            shutil.copy2(meta, RUNS / f"model_{stamp}.json")
        job["run"] = f"runs/{run_name}"
        job["meta"] = _read_meta(onnx)
    except OSError as exc:
        job["log"].append(f"[dashboard] archive failed: {exc}")


def _reader(proc: subprocess.Popen[str], job: dict[str, Any]) -> None:
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        text = line.rstrip("\r\n")
        if text:
            job["log"].append(text)
    code = proc.wait()
    job["exit_code"] = code
    job["status"] = "succeeded" if code == 0 else "failed"
    job["finished"] = datetime.now().isoformat(timespec="seconds")
    if code == 0:
        _archive_success(job)
    job["log"].append(f"[dashboard] training {job['status']} (exit {code})")
    with _jobs_lock:
        _jobs[job["id"]] = job
    _save_job_to_db(job)


def _start_job(req: TrainRequest) -> dict[str, Any]:
    csv_path = _safe_model_path(req.csv)
    if not csv_path.exists() or csv_path.suffix.lower() != ".csv":
        raise HTTPException(404, f"dataset not found: {req.csv}")
    if not TRAINER.exists():
        raise HTTPException(500, "train_onnx.py missing")

    job_id = uuid.uuid4().hex[:12]
    out_path = MODELS / "model.onnx"
    command = [
        sys.executable,
        str(TRAINER),
        "--csv",
        str(csv_path),
        "--out",
        str(out_path),
        "--model",
        req.model,
        "--hidden",
        req.hidden,
        "--threshold",
        str(req.threshold),
        "--cv-splits",
        str(req.cv_splits),
        "--cv-gap",
        str(req.cv_gap),
    ]
    job: dict[str, Any] = {
        "id": job_id,
        "status": "running",
        "created": datetime.now().isoformat(timespec="seconds"),
        "finished": None,
        "exit_code": None,
        "csv": req.csv,
        "model": req.model,
        "run": None,
        "meta": None,
        "command": "python train_onnx.py " + " ".join(command[2:]),
        "log": [],
    }

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    with _jobs_lock:
        _jobs[job_id] = job
    _save_job_to_db(job)
    threading.Thread(target=_reader, args=(proc, job), daemon=True).start()
    return job


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "root": str(ROOT),
        "models_dir": str(MODELS),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "trainer": TRAINER.exists(),
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    datasets = _datasets()
    models = _models()
    active = next((m for m in models if m["active"]), None)
    status = _read_status()
    return {
        "datasets": len(datasets),
        "models": len(models),
        "latest_dataset": datasets[0] if datasets else None,
        "active_model": active,
        "status": status,
        "checklist": {
            "exported": bool(datasets),
            "trained": bool(active),
            "live": bool(status.get("fresh")),
        },
    }


@app.get("/api/datasets")
def datasets() -> list[dict[str, Any]]:
    return _datasets()


@app.get("/api/models")
def models() -> list[dict[str, Any]]:
    return _models()


@app.post("/api/models/activate")
def activate(req: ActivateRequest) -> dict[str, Any]:
    src = _safe_model_path(req.name)
    if not src.exists() or src.suffix.lower() != ".onnx":
        raise HTTPException(404, f"model not found: {req.name}")

    target = MODELS / "model.onnx"
    if target.exists() and src != target:
        RUNS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(target, RUNS / f"prev_{stamp}.onnx")
        if (MODELS / "model.json").exists():
            shutil.copy2(MODELS / "model.json", RUNS / f"prev_{stamp}.json")

    if src != target:
        shutil.copy2(src, target)
        src_meta = src.with_suffix(".json")
        if src_meta.exists():
            shutil.copy2(src_meta, MODELS / "model.json")
    return {"ok": True, "active": "model.onnx"}


@app.post("/api/train")
def train(req: TrainRequest) -> dict[str, Any]:
    job = _start_job(req)
    return _job_public(job)


@app.get("/api/jobs")
def jobs() -> list[dict[str, Any]]:
    # Merge memory and persistent DB
    db_jobs = _load_recent_jobs_from_db(30)
    with _jobs_lock:
        mem_jobs = list(_jobs.values())
    
    combined: dict[str, dict[str, Any]] = {}
    for j in db_jobs:
        combined[j["id"]] = j
    for j in mem_jobs:
        combined[j["id"]] = j  # mem_jobs are fresher (e.g. running state)
        
    items = sorted(combined.values(), key=lambda j: j["created"], reverse=True)
    return [_job_public(j) for j in items[:30]]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        job = _load_job_from_db(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _job_public(job, include_log=True)


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str) -> StreamingResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        job = _load_job_from_db(job_id)
    if not job:
        raise HTTPException(404, "job not found")

    def stream():
        idx = 0
        while True:
            lines = job["log"]
            while idx < len(lines):
                payload = json.dumps(lines[idx], ensure_ascii=False)
                yield f"event: log\ndata: {payload}\n\n"
                idx += 1
            if job["status"] != "running":
                yield f"event: done\ndata: {json.dumps(_job_public(job, True), ensure_ascii=False)}\n\n"
                return
            time.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status")
def status() -> dict[str, Any]:
    return _read_status()


@app.get("/api/news/status")
def news_status() -> dict[str, Any]:
    if not NEWS_PAUSE_FILE.exists():
        return {"paused": False}
    try:
        data = json.loads(NEWS_PAUSE_FILE.read_text(encoding="utf-8"))
        until = data.get("no_trade_until", 0)
        now_ts = int(time.time())
        active = until > now_ts
        return {
            "paused": active,
            "no_trade_until": until,
            "seconds_remaining": max(0, until - now_ts) if active else 0,
            "reason": data.get("reason", "News Event")
        }
    except Exception:
        return {"paused": False}


@app.post("/api/news/pause")
def news_pause(req: NewsPauseRequest) -> dict[str, Any]:
    until = int(time.time()) + (req.pause_minutes * 60)
    data = {
        "no_trade_until": until,
        "pause_minutes": req.pause_minutes,
        "reason": req.reason,
        "updated": datetime.now().isoformat(timespec="seconds")
    }
    NEWS_PAUSE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "no_trade_until": until, "paused": True}


@app.post("/api/news/resume")
def news_resume() -> dict[str, Any]:
    if NEWS_PAUSE_FILE.exists():
        try:
            NEWS_PAUSE_FILE.unlink()
        except OSError:
            pass
    return {"ok": True, "paused": False}


@app.get("/api/risk/status")
def risk_status() -> dict[str, Any]:
    cb_data = {}
    if broker.CB_FILE.exists():
        try:
            cb_data = json.loads(broker.CB_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Read live status if available
    ls = _read_status()
    acc = None
    try:
        if broker._ensure_attached():
            acc = mt5.account_info()
    except Exception:
        pass

    start_equity = float(cb_data.get("start_equity", 0.0))
    current_equity = float(acc.equity if acc else ls.get("equity", 0.0))
    if start_equity <= 0.0 and current_equity > 0.0:
        start_equity = current_equity

    dd_pct = 0.0
    if start_equity > 0.0 and current_equity < start_equity:
        dd_pct = round(((start_equity - current_equity) / start_equity) * 100.0, 2)

    return {
        "daily_start_equity": round(start_equity, 2),
        "current_equity": round(current_equity, 2),
        "daily_drawdown_pct": dd_pct,
        "max_daily_drawdown_pct": 3.0,
        "daily_loss_limit_enabled": True,
        "max_spread_points": ls.get("max_spread_pts", 30),
        "current_spread_points": ls.get("spread_pts", 10),
        "circuit_breaker_active": bool(cb_data.get("locked", False)),
        "circuit_breaker_reason": cb_data.get("reason", ""),
        "trading_allowed": not bool(cb_data.get("locked", False))
    }


@app.post("/api/risk/reset_breaker")
def risk_reset_breaker() -> dict[str, Any]:
    if broker.CB_FILE.exists():
        try:
            data = json.loads(broker.CB_FILE.read_text(encoding="utf-8"))
            data["locked"] = False
            data["reason"] = "Manual administrative reset from dashboard"
            broker.CB_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return {"ok": True, "circuit_breaker_active": False}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True, "circuit_breaker_active": False}


@app.post("/api/trade/connect")
def trade_connect() -> dict[str, Any]:
    return broker.connect()


@app.post("/api/trade/restart")
def trade_restart() -> dict[str, Any]:
    return broker.restart()


@app.get("/api/trade/status")
def trade_status(auto_start: bool = False) -> dict[str, Any]:
    return broker.status(auto_start=auto_start)


@app.get("/api/trade/symbols")
def trade_symbols() -> list[dict[str, Any]]:
    return broker.symbols()


@app.get("/api/trade/quote")
def trade_quote(symbol: str = "EURUSD") -> dict[str, Any]:
    return broker.quote(symbol.upper())


@app.get("/api/trade/positions")
def trade_positions(symbol: str | None = None) -> list[dict[str, Any]]:
    return broker.positions(symbol.upper() if symbol else None)


@app.get("/api/trade/history")
def trade_history(days: int = 7, limit: int = 50,
                  symbol: str | None = None) -> list[dict[str, Any]]:
    return broker.history(days=max(1, min(days, 90)), limit=max(1, min(limit, 500)),
                          symbol=symbol.upper() if symbol else None)


@app.post("/api/trade/order")
def trade_order(req: TradeOrderRequest) -> dict[str, Any]:
    try:
        return broker.place_order(
            req.symbol.upper(), req.side, req.volume,
            req.sl_points, req.tp_points, req.comment,
            risk_percent=req.risk_percent,
            max_spread_pts=req.max_spread_pts
        )
    except Exception as exc:  # noqa: BLE001 - surface broker failures to the UI
        return {"ok": False, "error": f"order failed: {exc}"}


@app.post("/api/trade/close")
def trade_close(req: TradeCloseRequest) -> dict[str, Any]:
    try:
        return broker.close_position(req.ticket, req.volume)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"close failed: {exc}"}


@app.post("/api/trade/close_all")
def trade_close_all(req: TradeCloseAllRequest) -> dict[str, Any]:
    try:
        return broker.close_all(req.symbol.upper() if req.symbol else None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"close all failed: {exc}"}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="ui")
else:
    @app.get("/")
    def index_hint() -> dict[str, str]:
        return {"message": "Frontend not built. Run `npm run dev` in web/frontend."}
