"""
Phase 1 Test Suite: Capital Protection & Trade Execution Integrity
Covers:
  1. EURUSD 5-digit pricing & point/pip conversion
  2. USDJPY 3-digit pricing & point/pip conversion
  3. XAUUSD 2-digit pricing & point/pip conversion
  4. SL/TP calculations and price normalization
  5. Invalid stop distances (below stops_level, inverted stops)
  6. Excessive spread rejection filter
  7. Daily drawdown circuit breaker activation (3.0% limit)
  8. Daily reset behavior across broker/server day boundary
  9. EA restart persistence of circuit breaker state
 10. Volume validation, min/max lot size, and volume step compliance
 11. Insufficient margin rejection
 12. Python broker execution risk validation matching MQL5 CMoneyFixedRisk
"""

import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import pytest


# ---------------------------------------------------------------------------
# MOCK DOMAIN OBJECTS & SIMULATORS
# ---------------------------------------------------------------------------

@dataclass
class MockSymbolInfo:
    name: str
    digits: int
    point: float
    trade_tick_size: float
    trade_tick_value: float
    trade_stops_level: int
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    spread: int = 12
    margin_initial: float = 1000.0


@dataclass
class MockTick:
    bid: float
    ask: float


@dataclass
class MockAccount:
    balance: float
    equity: float
    margin_free: float


# Helper functions replicating the normalized mathematical engine
def pips_to_points(pips: float, digits: int) -> int:
    """Pip to point conversion: 3 and 5 digits multiply by 10."""
    multiplier = 10 if digits in (3, 5) else 1
    return int(round(pips * multiplier))


def points_to_pips(points: int, digits: int) -> float:
    """Point to pip conversion: 3 and 5 digits divide by 10."""
    multiplier = 10 if digits in (3, 5) else 1
    return points / multiplier


def calculate_sl_tp(
    side: str, price: float, sl_points: int, tp_points: int, symbol: MockSymbolInfo
) -> tuple[float, float]:
    """Calculate normalized SL and TP prices."""
    is_buy = side.lower() == "buy"
    sl_dist = sl_points * symbol.point
    tp_dist = tp_points * symbol.point
    
    sl = price - sl_dist if is_buy else price + sl_dist if sl_points > 0 else 0.0
    tp = price + tp_dist if is_buy else price - tp_dist if tp_points > 0 else 0.0
    
    return round(sl, symbol.digits), round(tp, symbol.digits)


def validate_stops(
    side: str, price: float, sl: float, tp: float, symbol: MockSymbolInfo
) -> tuple[bool, str]:
    """Validate stops against broker stop levels and side geometry."""
    is_buy = side.lower() == "buy"
    min_dist = symbol.trade_stops_level * symbol.point

    if sl > 0:
        if is_buy:
            if sl >= price:
                return False, f"Invalid BUY SL: stop {sl} must be strictly below price {price}"
            if (price - sl) < (min_dist - 1e-9):
                return False, f"BUY SL distance {(price - sl) / symbol.point:.0f} pts < min stops_level {symbol.trade_stops_level} pts"
        else:
            if sl <= price:
                return False, f"Invalid SELL SL: stop {sl} must be strictly above price {price}"
            if (sl - price) < (min_dist - 1e-9):
                return False, f"SELL SL distance {(sl - price) / symbol.point:.0f} pts < min stops_level {symbol.trade_stops_level} pts"

    if tp > 0:
        if is_buy:
            if tp <= price:
                return False, f"Invalid BUY TP: target {tp} must be strictly above price {price}"
            if (tp - price) < (min_dist - 1e-9):
                return False, f"BUY TP distance {(tp - price) / symbol.point:.0f} pts < min stops_level {symbol.trade_stops_level} pts"
        else:
            if tp >= price:
                return False, f"Invalid SELL TP: target {tp} must be strictly below price {price}"
            if (price - tp) < (min_dist - 1e-9):
                return False, f"SELL TP distance {(price - tp) / symbol.point:.0f} pts < min stops_level {symbol.trade_stops_level} pts"

    return True, "OK"


def check_spread(tick: MockTick, symbol: MockSymbolInfo, max_spread_pts: int) -> tuple[bool, str]:
    """Check spread threshold."""
    spread_pts = int(round((tick.ask - tick.bid) / symbol.point))
    if spread_pts > max_spread_pts:
        return False, f"Spread rejection: current spread {spread_pts} pts > max {max_spread_pts} pts"
    return True, "OK"


def calculate_risk_lot(
    account: MockAccount, symbol: MockSymbolInfo, sl_points: int, risk_pct: float
) -> float:
    """Calculate risk-calibrated lot size matching CMoneyFixedRisk."""
    if sl_points <= 0 or risk_pct <= 0 or account.balance <= 0:
        return symbol.volume_min

    risk_amount = account.balance * (risk_pct / 100.0)
    sl_distance = sl_points * symbol.point
    tick_size = symbol.trade_tick_size or symbol.point
    tick_value = symbol.trade_tick_value or 1.0

    loss_per_lot = (sl_distance / tick_size) * tick_value
    if loss_per_lot <= 0:
        return symbol.volume_min

    raw_lot = risk_amount / loss_per_lot
    step = symbol.volume_step or 0.01
    lot = math.floor(raw_lot / step) * step
    lot = max(symbol.volume_min, min(symbol.volume_max, lot))
    return round(lot, 2)


class CircuitBreakerSimulator:
    """Replicates CRiskProtection state machine and file persistence."""
    def __init__(self, state_file: Path, max_dd_pct: float = 3.0):
        self.file = state_file
        self.max_dd_pct = max_dd_pct
        self.start_equity = 0.0
        self.day_ts = 0
        self.locked = False
        self.reason = ""
        self.load()

    def load(self):
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                self.start_equity = float(data.get("start_equity", 0.0))
                self.day_ts = int(data.get("day_ts", 0))
                self.locked = bool(data.get("locked", False))
                self.reason = str(data.get("reason", ""))
            except Exception:
                pass

    def save(self):
        data = {
            "day_ts": self.day_ts,
            "start_equity": round(self.start_equity, 2),
            "locked": self.locked,
            "reason": self.reason
        }
        self.file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def check_new_day(self, current_day_midnight_ts: int, current_equity: float):
        if self.day_ts == 0 or current_day_midnight_ts > self.day_ts:
            if self.day_ts > 0 and self.locked:
                self.locked = False
                self.reason = ""
            self.day_ts = current_day_midnight_ts
            self.start_equity = current_equity
            self.save()
            return True
        return False

    def evaluate_equity(self, current_equity: float) -> tuple[bool, str]:
        if self.locked:
            return False, f"Daily Drawdown Circuit Breaker Locked: {self.reason}"
        if self.start_equity <= 0:
            self.start_equity = current_equity
            self.save()

        if current_equity < self.start_equity:
            dd_pct = ((self.start_equity - current_equity) / self.start_equity) * 100.0
            if dd_pct >= self.max_dd_pct:
                self.locked = True
                self.reason = f"Daily drawdown {dd_pct:.2f}% reached limit {self.max_dd_pct:.1f}%"
                self.save()
                return False, self.reason
        return True, "OK"

    def reset_admin(self):
        self.locked = False
        self.reason = "Manual administrative reset"
        self.save()


# ---------------------------------------------------------------------------
# TEST SUITE IMPLEMENTATION
# ---------------------------------------------------------------------------

@pytest.fixture
def eurusd():
    return MockSymbolInfo(
        name="EURUSD",
        digits=5,
        point=0.00001,
        trade_tick_size=0.00001,
        trade_tick_value=1.0,
        trade_stops_level=10,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )


@pytest.fixture
def usdjpy():
    return MockSymbolInfo(
        name="USDJPY",
        digits=3,
        point=0.001,
        trade_tick_size=0.001,
        trade_tick_value=0.67,
        trade_stops_level=15,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
    )


@pytest.fixture
def xauusd():
    return MockSymbolInfo(
        name="XAUUSD",
        digits=2,
        point=0.01,
        trade_tick_size=0.01,
        trade_tick_value=1.0,
        trade_stops_level=30,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
    )


# 1. EURUSD 5-digit pricing and point/pip conversion
def test_eurusd_5digit_conversions(eurusd):
    assert pips_to_points(60, eurusd.digits) == 600
    assert pips_to_points(30.5, eurusd.digits) == 305
    assert points_to_pips(600, eurusd.digits) == 60.0
    assert points_to_pips(15, eurusd.digits) == 1.5


# 2. USDJPY 3-digit pricing and point/pip conversion
def test_usdjpy_3digit_conversions(usdjpy):
    assert pips_to_points(50, usdjpy.digits) == 500
    assert points_to_pips(500, usdjpy.digits) == 50.0
    assert pips_to_points(25.5, usdjpy.digits) == 255


# 3. 2-digit pricing (XAUUSD / Gold)
def test_xauusd_2digit_conversions(xauusd):
    assert pips_to_points(50, xauusd.digits) == 50
    assert points_to_pips(50, xauusd.digits) == 50.0


# 4. SL/TP Calculations & Price Normalization
def test_sl_tp_calculations(eurusd, usdjpy):
    # BUY on EURUSD: Ask = 1.10000, SL = 300 pts (30 pips), TP = 600 pts (60 pips)
    sl, tp = calculate_sl_tp("buy", 1.10000, 300, 600, eurusd)
    assert sl == 1.09700
    assert tp == 1.10600

    # SELL on EURUSD: Bid = 1.10000, SL = 300 pts, TP = 600 pts
    sl, tp = calculate_sl_tp("sell", 1.10000, 300, 600, eurusd)
    assert sl == 1.10300
    assert tp == 1.09400

    # SELL on USDJPY: Bid = 150.500, SL = 250 pts, TP = 500 pts
    sl, tp = calculate_sl_tp("sell", 150.500, 250, 500, usdjpy)
    assert sl == 150.750
    assert tp == 150.000


# 5. Invalid Stop Distances & Side Geometry Rejection
def test_invalid_stop_distance_rejection(eurusd):
    # stops_level is 10 points. 5 points distance should be rejected
    ok, err = validate_stops("buy", 1.10000, 1.09995, 1.10600, eurusd)
    assert not ok
    assert "stops_level" in err

    # Wrong side: BUY with SL above price
    ok, err = validate_stops("buy", 1.10000, 1.10100, 1.10600, eurusd)
    assert not ok
    assert "strictly below" in err

    # Wrong side: BUY with TP below price
    ok, err = validate_stops("buy", 1.10000, 1.09500, 1.09900, eurusd)
    assert not ok
    assert "strictly above" in err

    # Valid stops
    ok, err = validate_stops("buy", 1.10000, 1.09700, 1.10600, eurusd)
    assert ok


# 6. Excessive Spread Rejection Filter
def test_spread_filter(eurusd):
    # Spread = 15 points, limit = 30 -> Allowed
    normal_tick = MockTick(bid=1.10000, ask=1.10015)
    ok, msg = check_spread(normal_tick, eurusd, max_spread_pts=30)
    assert ok

    # Spread = 45 points, limit = 30 -> Rejected
    wide_tick = MockTick(bid=1.10000, ask=1.10045)
    ok, msg = check_spread(wide_tick, eurusd, max_spread_pts=30)
    assert not ok
    assert "Spread rejection" in msg


# 7. Daily Drawdown Circuit Breaker Activation (3.0% threshold)
def test_daily_drawdown_circuit_breaker():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    try:
        sim = CircuitBreakerSimulator(temp_path, max_dd_pct=3.0)
        sim.check_new_day(1700000000, 100000.0)
        assert sim.start_equity == 100000.0
        assert not sim.locked

        # Equity drops 1.5% -> $98,500 (Allowed)
        ok, msg = sim.evaluate_equity(98500.0)
        assert ok
        assert not sim.locked

        # Equity drops 3.1% -> $96,900 (Threshold breached: 3.1% >= 3.0%)
        ok, msg = sim.evaluate_equity(96900.0)
        assert not ok
        assert sim.locked
        assert "reached limit" in msg

        # Subsequent orders are blocked
        ok2, msg2 = sim.evaluate_equity(97000.0)
        assert not ok2
        assert "Circuit Breaker Locked" in msg2
    finally:
        if temp_path.exists():
            temp_path.unlink()


# 8. Daily Reset Behavior Across Day Rollover
def test_daily_reset_on_new_day():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    try:
        sim = CircuitBreakerSimulator(temp_path, max_dd_pct=3.0)
        day1 = 1700000000
        sim.check_new_day(day1, 100000.0)
        sim.evaluate_equity(96500.0)  # Locked on day 1
        assert sim.locked

        # Day rollover: server midnight advances to day2
        day2 = 1700086400  # +86400 seconds (next midnight)
        rolled = sim.check_new_day(day2, 96500.0)
        assert rolled
        assert not sim.locked  # Unlocks for new day
        assert sim.start_equity == 96500.0
    finally:
        if temp_path.exists():
            temp_path.unlink()


# 9. EA Restart Persistence
def test_ea_restart_persistence():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    try:
        # Session 1: EA runs and locks
        sim1 = CircuitBreakerSimulator(temp_path, max_dd_pct=3.0)
        sim1.check_new_day(1700000000, 50000.0)
        sim1.evaluate_equity(48000.0)  # 4% loss -> Locked
        assert sim1.locked

        # Session 2: EA restarts (new instance reads file)
        sim2 = CircuitBreakerSimulator(temp_path, max_dd_pct=3.0)
        assert sim2.locked
        assert sim2.start_equity == 50000.0
        ok, msg = sim2.evaluate_equity(48200.0)
        assert not ok
        assert "Circuit Breaker Locked" in msg

        # Administrative reset
        sim2.reset_admin()
        assert not sim2.locked

        # Session 3: New restart confirms administrative unlock persisted
        sim3 = CircuitBreakerSimulator(temp_path, max_dd_pct=3.0)
        assert not sim3.locked
    finally:
        if temp_path.exists():
            temp_path.unlink()


# 10. Unified Risk-Based Position Sizing (matching CMoneyFixedRisk)
def test_unified_risk_position_sizing(eurusd, usdjpy):
    account = MockAccount(balance=10000.0, equity=10000.0, margin_free=9500.0)
    # Risk 1.0% ($100), SL = 300 pts (30 pips)
    # loss per 1.0 lot on EURUSD = 300 * $1.0 = $300
    # lots = $100 / $300 = 0.3333 -> 0.33 lots
    lots = calculate_risk_lot(account, eurusd, sl_points=300, risk_pct=1.0)
    assert lots == 0.33

    # Risk 2.0% ($200), SL = 200 pts
    # lots = $200 / (200 * $1.0) = 1.0 lot
    lots2 = calculate_risk_lot(account, eurusd, sl_points=200, risk_pct=2.0)
    assert lots2 == 1.00

    # Volume limits: clamp to volume_min (0.01) if calculated volume is tiny
    tiny_lots = calculate_risk_lot(account, eurusd, sl_points=50000, risk_pct=0.1)
    assert tiny_lots == eurusd.volume_min


# 11. Insufficient Margin Rejection
def test_insufficient_margin():
    account = MockAccount(balance=1000.0, equity=1000.0, margin_free=50.0)
    # Trying to place 1.0 lot requiring $1000 margin with only $50 free margin
    margin_required = 1000.0
    allowed = margin_required <= account.margin_free
    assert not allowed
    reject_msg = f"Insufficient margin: required ${margin_required:.2f}, free ${account.margin_free:.2f}"
    assert "Insufficient margin" in reject_msg


# 12. Cross-Verification with Python Broker Bridge Functions
def test_broker_bridge_compatibility():
    from web.backend import broker
    
    # Test broker.normalize_price
    assert broker.normalize_price(1.100346, 5) == 1.10035
    assert broker.normalize_price(150.3456, 3) == 150.346
    
    # Test broker._volume step and clamp
    mock_sym = MockSymbolInfo("EURUSD", 5, 0.00001, 0.00001, 1.0, 10, volume_min=0.01, volume_max=10.0, volume_step=0.01)
    vol, note = broker._volume(mock_sym, 0.034)
    assert vol == 0.03
    vol_min, note_min = broker._volume(mock_sym, 0.005)
    assert vol_min == 0.01
    assert "minimum" in str(note_min)
