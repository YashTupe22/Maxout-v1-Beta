"""MetaTrader 5 broker bridge for the MaxOut dashboard.

Talks to the locally running MT5 terminal through the official
``MetaTrader5`` Python package (Windows only). The terminal is started by
this module when needed, with AutoTrading forced on in the terminal config.

All calls are serialized: the MT5 Python API is a thin wrapper around the
terminal IPC and is not safe to hammer from multiple threads at once.
"""
from __future__ import annotations

import csv
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

MAGIC = 770001
COMMENT = "MaxOut dashboard"
INIT_TIMEOUT = 60.0

_PRIORITY = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD",
             "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "XAUUSD"]

_RETCODES = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request canceled by trader",
    10008: "Order placed",
    10009: "Request executed",
    10010: "Only part of the request was completed",
    10011: "Request processing error",
    10012: "Request canceled by timeout",
    10013: "Invalid request",
    10014: "Invalid volume",
    10015: "Invalid price",
    10016: "Invalid stops (SL/TP too close or wrong side)",
    10017: "Trading is disabled",
    10018: "Market is closed",
    10019: "Not enough money",
    10020: "Prices changed",
    10021: "No quotes to process the request",
    10022: "Invalid order expiration",
    10023: "Order state changed",
    10024: "Too many requests",
    10025: "No changes in request",
    10026: "AutoTrading disabled by server",
    10027: "AutoTrading disabled in the terminal",
    10028: "Request locked by the terminal",
    10029: "Order or position frozen",
    10030: "Unsupported filling mode",
    10031: "No connection to the trade server",
    10033: "Order/position limit reached",
    10034: "Volume limit reached",
    10035: "Invalid or prohibited order type",
    10036: "Position already closed",
}

_lock = threading.RLock()
_last_error: str | None = None
_symbols_cache: tuple[float, list[dict[str, Any]]] | None = None


# --------------------------------------------------------------------------
# Terminal discovery / lifecycle
# --------------------------------------------------------------------------
def _appdata() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))


def _data_dirs() -> list[Path]:
    base = _appdata() / "MetaQuotes" / "Terminal"
    if not base.exists():
        return []
    return [p for p in base.iterdir() if (p / "config" / "common.ini").exists()]


def _read_origin(path: Path) -> str:
    """origin.txt is UTF-16 on some installs, UTF-8 on others."""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16").strip()
        except UnicodeError:
            return ""
    try:
        return raw.decode("utf-8-sig").strip()
    except UnicodeError:
        return ""


def _discover() -> tuple[Path | None, Path | None]:
    env_exe = os.environ.get("MT5_TERMINAL")
    if env_exe and Path(env_exe).exists():
        exe = Path(env_exe)
        for data in _data_dirs():
            if str(exe).lower() in _read_origin(data / "origin.txt").lower():
                return exe, data
        return exe, None

    best: tuple[float, Path, Path] | None = None
    for data in _data_dirs():
        origin_path = _read_origin(data / "origin.txt")
        if not origin_path:
            continue
        exe = Path(origin_path) / "terminal64.exe"
        if not exe.exists():
            continue
        try:
            mtime = (data / "config" / "common.ini").stat().st_mtime
        except OSError:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, exe, data)

    if best:
        return best[1], best[2]

    fallback = Path(r"C:\Program Files\Skyriss Securities MT5 Terminal\terminal64.exe")
    return (fallback if fallback.exists() else None), None


TERMINAL_EXE, TERMINAL_DATA = _discover()


def _set_error(msg: str | None) -> None:
    global _last_error
    _last_error = msg


def _terminal_pids() -> list[int]:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for row in csv.reader(out.splitlines()):
        if len(row) >= 2 and row[0].lower() == "terminal64.exe":
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return pids


def _terminal_running() -> bool:
    return bool(_terminal_pids())


def _patch_config() -> None:
    """Force AutoTrading on and disable the account/profile guards."""
    if not TERMINAL_DATA:
        return
    path = TERMINAL_DATA / "config" / "common.ini"
    try:
        text = path.read_text(encoding="utf-16")
    except (OSError, UnicodeError):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return
    wanted = {"Enabled": "1", "Account": "0", "Profile": "0", "Chart": "0"}
    out: list[str] = []
    in_experts = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_experts = stripped.lower() == "[experts]"
        elif in_experts and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in wanted:
                line = f"{key}={wanted[key]}"
        out.append(line)
    try:
        path.write_text("\r\n".join(out) + "\r\n", encoding="utf-16")
    except OSError as exc:
        _set_error(f"could not update terminal config: {exc}")


def _start_terminal() -> bool:
    if not TERMINAL_EXE or not TERMINAL_EXE.exists():
        _set_error("terminal64.exe not found (set MT5_TERMINAL)")
        return False
    _patch_config()
    flags = 0
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            [str(TERMINAL_EXE)],
            cwd=str(TERMINAL_EXE.parent),
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        _set_error(f"could not start MT5: {exc}")
        return False
    return True


def _stop_terminal() -> None:
    try:
        mt5.shutdown()
    except Exception:
        pass
    for pid in _terminal_pids():
        try:
            subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
    deadline = time.time() + 15
    while time.time() < deadline and _terminal_running():
        time.sleep(0.25)
    for pid in _terminal_pids():
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass


def _ensure_connected(timeout: float = INIT_TIMEOUT) -> bool:
    if mt5.terminal_info() is not None:
        return True

    started = False
    if not _terminal_running():
        if not _start_terminal():
            return False
        started = True

    deadline = time.time() + timeout
    while time.time() < deadline:
        if mt5.initialize():
            _set_error(None)
            return True
        time.sleep(0.5)

    _set_error("could not connect to the MT5 terminal"
               + (" (it was just started — retry in a few seconds)" if started else ""))
    return False


def _ensure_attached() -> bool:
    """Attach to an already running terminal; never launch it.

    Terminal lifecycle is controlled only through connect()/restart(), so a
    user closing MT5 is not undone by background polling.
    """
    if mt5.terminal_info() is not None:
        return True
    if not _terminal_running():
        _set_error("MT5 terminal is not running")
        return False
    for _ in range(20):
        if mt5.initialize():
            _set_error(None)
            return True
        time.sleep(0.25)
    _set_error("could not attach to the running MT5 terminal")
    return False


def connect(restart: bool = False) -> dict[str, Any]:
    with _lock:
        if restart:
            _stop_terminal()
            time.sleep(1.5)
        _ensure_connected()
        return _status()


def restart() -> dict[str, Any]:
    return connect(restart=True)


def status(auto_start: bool = False) -> dict[str, Any]:
    with _lock:
        if auto_start:
            _ensure_connected()
        return _status()


# --------------------------------------------------------------------------
# Serialization helpers
# --------------------------------------------------------------------------
def _decimals(step: float) -> int:
    text = f"{step:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def normalize_price(price: float, digits: int) -> float:
    """Normalize a price to the broker's symbol precision."""
    return round(float(price), int(digits))


def _volume(symbol_info: Any, volume: float) -> tuple[float, str | None]:
    step = symbol_info.volume_step or 0.01
    vmin = symbol_info.volume_min or step
    vmax = symbol_info.volume_max or 100.0
    v = round(volume / step) * step
    v = round(v, _decimals(step))
    if v < vmin:
        return vmin, f"volume raised to minimum {vmin:g}"
    if v > vmax:
        return vmax, f"volume capped to maximum {vmax:g}"
    return v, None


def _filling(symbol_info: Any) -> int:
    mode = int(getattr(symbol_info, "filling_mode", 0))
    if mode & 2:
        return mt5.ORDER_FILLING_IOC
    if mode & 1:
        return mt5.ORDER_FILLING_FOK
    return mt5.ORDER_FILLING_RETURN


def _result(result: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if result is None:
        code, desc = mt5.last_error()
        return {"ok": False, "retcode": int(code), "description": desc,
                "error": str(mt5.last_error())}
    code = int(result.retcode)
    payload: dict[str, Any] = {
        "ok": code in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED),
        "retcode": code,
        "description": _RETCODES.get(code, result.comment or f"retcode {code}"),
        "order": int(result.order),
        "deal": int(result.deal),
        "price": float(result.price),
        "volume": float(result.volume),
        "comment": result.comment,
    }
    if extra:
        payload.update(extra)
    if not payload["ok"]:
        payload["error"] = _RETCODES.get(code, result.comment or "order failed")
    return payload


def _send(request: dict[str, Any], symbol_info: Any) -> dict[str, Any]:
    modes = [_filling(symbol_info)]
    for candidate in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        if candidate not in modes:
            modes.append(candidate)

    result = None
    for mode in modes:
        request["type_filling"] = mode
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
            break
    return _result(result)


def _account() -> Any:
    return mt5.account_info()


def _status() -> dict[str, Any]:
    info = mt5.terminal_info()
    if info is None and _terminal_running():
        # attach passively: the terminal is up, the Python bridge just isn't
        if mt5.initialize():
            info = mt5.terminal_info()
    account = _account()
    if info is None:
        return {
            "connected": False,
            "trade_allowed": False,
            "error": _last_error or "MT5 terminal is not running",
            "terminal_path": str(TERMINAL_EXE) if TERMINAL_EXE else None,
            "data_dir": str(TERMINAL_DATA) if TERMINAL_DATA else None,
        }

    trade_allowed = bool(info.trade_allowed) and bool(account.trade_expert if account else False)
    payload: dict[str, Any] = {
        "connected": bool(info.connected),
        "trade_allowed": trade_allowed,
        "terminal_allowed": bool(info.trade_allowed),
        "account_allowed": bool(account.trade_expert) if account else False,
        "build": int(info.build),
        "terminal_path": str(TERMINAL_EXE) if TERMINAL_EXE else None,
        "data_dir": str(TERMINAL_DATA) if TERMINAL_DATA else None,
    }
    if account is None:
        payload["error"] = _last_error or "account info unavailable (terminal still syncing?)"
        return payload

    mode = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(account.trade_mode, str(account.trade_mode))

    server_time = None
    server_time_str = None
    server_offset_sec = 0
    try:
        tick = mt5.symbol_info_tick("EURUSD")
        if tick and tick.time > 0:
            server_time = int(tick.time)
            server_offset_sec = int(round(tick.time - time.time()))
            server_time_str = datetime.fromtimestamp(tick.time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    payload.update({
        "login": int(account.login),
        "name": account.name,
        "server": account.server,
        "company": account.company,
        "currency": account.currency,
        "mode": mode,
        "leverage": int(account.leverage),
        "balance": float(account.balance),
        "equity": float(account.equity),
        "margin": float(account.margin),
        "margin_free": float(account.margin_free),
        "margin_level": float(account.margin_level),
        "profit": float(account.profit),
        "server_time": server_time,
        "server_time_str": server_time_str,
        "server_offset_sec": server_offset_sec,
    })
    return payload


# --------------------------------------------------------------------------
# Public data
# --------------------------------------------------------------------------
def _symbol_dict(symbol_info: Any) -> dict[str, Any] | None:
    tick = mt5.symbol_info_tick(symbol_info.name)
    point = float(symbol_info.point or 0.0)
    bid = float(tick.bid) if tick else None
    ask = float(tick.ask) if tick else None
    spread = round((ask - bid) / point, 1) if (bid and ask and point) else None
    return {
        "name": symbol_info.name,
        "description": symbol_info.description,
        "digits": int(symbol_info.digits),
        "point": point,
        "bid": bid,
        "ask": ask,
        "spread_points": spread,
        "volume_min": float(symbol_info.volume_min),
        "volume_max": float(symbol_info.volume_max),
        "volume_step": float(symbol_info.volume_step),
        "stops_level": int(symbol_info.trade_stops_level),
        "trade_mode": int(symbol_info.trade_mode),
        "tradable": int(symbol_info.trade_mode) == mt5.SYMBOL_TRADE_MODE_FULL,
        "visible": bool(symbol_info.visible),
    }


def symbols() -> list[dict[str, Any]]:
    global _symbols_cache
    with _lock:
        if not _ensure_attached():
            return []
        now = time.time()
        if _symbols_cache and now - _symbols_cache[0] < 3.0:
            return _symbols_cache[1]
        raw = mt5.symbols_get() or []
        items = []
        for info in raw:
            if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
                continue
            item = _symbol_dict(info)
            if item:
                items.append(item)
        items.sort(key=lambda s: (
            _PRIORITY.index(s["name"]) if s["name"] in _PRIORITY else len(_PRIORITY),
            not s["tradable"],
            s["name"],
        ))
        _symbols_cache = (now, items)
        return items


def quote(symbol: str) -> dict[str, Any]:
    with _lock:
        if not _ensure_attached():
            return {"ok": False, "error": _last_error or "not connected"}
        info = mt5.symbol_info(symbol)
        if info is None:
            return {"ok": False, "error": f"unknown symbol {symbol}"}
        if not info.visible:
            mt5.symbol_select(symbol, True)
        item = _symbol_dict(info)
        if not item:
            return {"ok": False, "error": f"no quote for {symbol}"}
        item["ok"] = True
        item["time"] = datetime.now().isoformat(timespec="seconds")
        return item


def positions(symbol: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        if not _ensure_attached():
            return []
        raw = (mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()) or []
        items = []
        for p in raw:
            items.append({
                "ticket": int(p.ticket),
                "symbol": p.symbol,
                "side": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "price_current": float(p.price_current),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
                "swap": float(p.swap),
                "magic": int(p.magic),
                "comment": p.comment,
                "time": datetime.fromtimestamp(p.time).isoformat(timespec="seconds"),
            })
        items.sort(key=lambda p: p["time"], reverse=True)
        return items


def history(days: int = 7, limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        if not _ensure_attached():
            return []
        # Broker server time can differ from the local clock by hours; anchor the
        # query on a live tick so recent deals are never outside the range.
        anchor = None
        probe = mt5.symbol_info_tick(symbol or "EURUSD")
        if probe is not None and probe.time:
            anchor = datetime.fromtimestamp(probe.time)
        if anchor is None:
            anchor = datetime.now()
        raw = mt5.history_deals_get(
            anchor - timedelta(days=days), anchor + timedelta(minutes=10)
        ) or []
        items = []
        for d in raw:
            if symbol and d.symbol != symbol:
                continue
            items.append({
                "ticket": int(d.ticket),
                "order": int(d.order),
                "position": int(d.position_id),
                "symbol": d.symbol,
                "side": "buy" if d.type == mt5.DEAL_TYPE_BUY else "sell",
                "entry": {0: "in", 1: "out", 2: "inout", 3: "out_by"}.get(int(d.entry), str(d.entry)),
                "volume": float(d.volume),
                "price": float(d.price),
                "profit": float(d.profit),
                "commission": float(d.commission),
                "swap": float(d.swap),
                "fee": float(d.fee),
                "comment": d.comment,
                "magic": int(d.magic),
                "time": datetime.fromtimestamp(d.time).isoformat(timespec="seconds"),
            })
        items.sort(key=lambda d: d["time"], reverse=True)
        return items[:limit]


# --------------------------------------------------------------------------
# Trading & Risk Validation
# --------------------------------------------------------------------------
CB_FILE = Path(__file__).resolve().parents[2] / "Models" / "circuit_breaker.json"

def check_risk_protection(info: Any, tick: Any, max_spread_pts: int = 30, max_dd_pct: float = 3.0) -> tuple[bool, str]:
    """Check spread limit and daily drawdown circuit breaker."""
    # 1. Spread Check
    spread_pts = round((tick.ask - tick.bid) / info.point)
    if spread_pts > max_spread_pts:
        return False, f"Spread rejection: current spread {spread_pts} pts > max {max_spread_pts} pts"

    # 2. Circuit Breaker Check
    if CB_FILE.exists():
        try:
            import json
            data = json.loads(CB_FILE.read_text(encoding="utf-8"))
            if data.get("locked"):
                return False, f"Circuit Breaker ACTIVE: {data.get('reason', 'Daily loss limit reached')}"
            
            # Real-time equity drawdown check
            start_eq = float(data.get("start_equity", 0.0))
            if start_eq > 0.0:
                acc = mt5.account_info()
                if acc and acc.equity < start_eq:
                    dd = ((start_eq - acc.equity) / start_eq) * 100.0
                    if dd >= max_dd_pct:
                        data["locked"] = True
                        data["reason"] = f"Daily drawdown reached {dd:.2f}% (limit: {max_dd_pct:.2f}%)"
                        CB_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        return False, f"Circuit Breaker TRIGGERED: {data['reason']}"
        except Exception:
            pass

    return True, ""


def calculate_risk_volume(symbol: str, sl_points: int, risk_pct: float = 1.0) -> float:
    """Calculate risk-calibrated volume matching CMoneyFixedRisk."""
    info = mt5.symbol_info(symbol)
    acc = mt5.account_info()
    if not info or not acc or sl_points <= 0 or risk_pct <= 0:
        return float(info.volume_min) if info else 0.01

    risk_capital = acc.balance * (risk_pct / 100.0)
    # 1 pip / point loss calculation per 1.0 lot
    # loss = volume * (sl_distance / trade_tick_size) * trade_tick_value
    sl_distance = sl_points * info.point
    loss_per_lot = (sl_distance / (info.trade_tick_size or info.point)) * (info.trade_tick_value or 1.0)
    if loss_per_lot <= 0:
        return float(info.volume_min)

    calc_vol = risk_capital / loss_per_lot
    # Step clamp
    step = info.volume_step or 0.01
    vol = math.floor(calc_vol / step) * step
    vol = max(float(info.volume_min), min(float(info.volume_max), vol))
    return round(vol, 2)


def place_order(symbol: str, side: str, volume: float,
                sl_points: int = 0, tp_points: int = 0,
                comment: str = "", risk_percent: float = 0.0,
                max_spread_pts: int = 30) -> dict[str, Any]:
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}

    with _lock:
        if not _ensure_attached():
            return {"ok": False, "error": _last_error or "not connected"}
        status = _status()
        if not status.get("trade_allowed"):
            return {"ok": False, "error": "AutoTrading is disabled — enable it in MT5",
                    "retcode": 10027}

        info = mt5.symbol_info(symbol)
        if info is None:
            return {"ok": False, "error": f"unknown symbol {symbol}"}
        if not info.visible:
            mt5.symbol_select(symbol, True)
        if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            return {"ok": False, "error": f"{symbol} is not fully tradable right now"}

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or (tick.ask <= 0 and tick.bid <= 0):
            return {"ok": False, "error": f"no quote for {symbol}"}

        # Step 2 & 3: Risk Protection validation (Spread & Circuit Breaker)
        allowed, reason = check_risk_protection(info, tick, max_spread_pts=max_spread_pts)
        if not allowed:
            return {"ok": False, "error": reason}

        # Step 4: Unified Risk-Based Position Sizing
        if risk_percent > 0 and sl_points > 0:
            raw_vol = calculate_risk_volume(symbol, sl_points, risk_percent)
        else:
            raw_vol = float(volume)

        vol, note = _volume(info, raw_vol)
        point = float(info.point)
        digits = int(info.digits)
        stops_min = int(info.trade_stops_level)
        if sl_points and sl_points < stops_min:
            return {"ok": False, "error": f"SL must be at least {stops_min} points ({stops_min / (10 if digits in (3,5) else 1):.1f} pips)"}
        if tp_points and tp_points < stops_min:
            return {"ok": False, "error": f"TP must be at least {stops_min} points ({stops_min / (10 if digits in (3,5) else 1):.1f} pips)"}

        is_buy = side == "buy"
        price = float(tick.ask if is_buy else tick.bid)
        sl = 0.0
        tp = 0.0
        if sl_points:
            sl = round(price - sl_points * point if is_buy else price + sl_points * point, digits)
        if tp_points:
            tp = round(price + tp_points * point if is_buy else price - tp_points * point, digits)

        # Margin check
        margin_needed = mt5.order_calc_margin(
            mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            symbol, vol, price
        )
        acc = mt5.account_info()
        if acc and margin_needed is not None and margin_needed > acc.margin_free:
            return {"ok": False, "error": f"Insufficient margin: required ${margin_needed:.2f}, free ${acc.margin_free:.2f}"}

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": vol,
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 30,
            "magic": MAGIC,
            "comment": (comment or COMMENT)[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = _send(request, info)
        result.update({
            "symbol": symbol,
            "side": side,
            "requested_volume": float(volume),
            "executed_volume": vol,
            "sl_points": sl_points,
            "tp_points": tp_points,
            "sl": sl,
            "tp": tp,
            "note": note,
        })
        return result


def close_position(ticket: int, volume: float | None = None) -> dict[str, Any]:
    with _lock:
        if not _ensure_attached():
            return {"ok": False, "error": _last_error or "not connected"}
        found = mt5.positions_get(ticket=int(ticket))
        if not found:
            return {"ok": False, "error": f"position {ticket} not found"}
        pos = found[0]
        info = mt5.symbol_info(pos.symbol)
        tick = mt5.symbol_info_tick(pos.symbol)
        if info is None or tick is None:
            return {"ok": False, "error": f"no quote for {pos.symbol}"}

        vol, note = _volume(info, float(volume) if volume else float(pos.volume))
        if vol > pos.volume:
            vol = float(pos.volume)
        closing_buy = pos.type == mt5.POSITION_TYPE_BUY
        price = float(tick.bid if closing_buy else tick.ask)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": vol,
            "type": mt5.ORDER_TYPE_SELL if closing_buy else mt5.ORDER_TYPE_BUY,
            "position": int(pos.ticket),
            "price": price,
            "deviation": 30,
            "magic": MAGIC,
            "comment": "dashboard close"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = _send(request, info)
        result.update({
            "symbol": pos.symbol,
            "ticket": int(pos.ticket),
            "volume": vol,
            "note": note,
            "partial": vol < float(pos.volume),
        })
        return result


def close_all(symbol: str | None = None) -> dict[str, Any]:
    with _lock:
        items = positions(symbol)
        closed, failed = [], []
        for p in items:
            res = close_position(p["ticket"])
            (closed if res.get("ok") else failed).append({
                "ticket": p["ticket"], "symbol": p["symbol"],
                "volume": p["volume"], "result": res,
            })
        return {"ok": not failed and bool(items), "closed": closed,
                "failed": failed, "count": len(closed)}
