#!/usr/bin/env python3
"""Direct feature extractor connecting to MetaTrader 5 terminal.
Extracts native bars (M15, H1, H4, D1) and computes the exact 30-feature vector
matching Features.mqh and FEATURE_LAYOUT.md.
"""
import argparse
from datetime import datetime
import math
import os
import sys
import numpy as np
import pandas as pd
import MetaTrader5 as mt5

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "Models")

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

def rsi_series(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))

def atr_series(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()

def adx_series(high, low, close, period=14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    tr = atr_series(high, low, close, period=period)
    plus_di = 100.0 * pd.Series(plus_dm, index=high.index).ewm(com=period - 1, min_periods=period).mean() / (tr + 1e-12)
    minus_di = 100.0 * pd.Series(minus_dm, index=high.index).ewm(com=period - 1, min_periods=period).mean() / (tr + 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    adx = dx.ewm(com=period - 1, min_periods=period).mean()
    return adx, plus_di, minus_di

def macd_series(close, fast=12, slow=26, signal=9):
    fast_ema = close.ewm(span=fast, adjust=False).mean()
    slow_ema = close.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    sig_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, sig_line

def stoch_series(high, low, close, k_period=14, d_period=3, slowing=3):
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    raw_k = 100.0 * (close - lowest_low) / (highest_high - lowest_low + 1e-12)
    stoch_k = raw_k.rolling(window=slowing).mean()
    stoch_d = stoch_k.rolling(window=d_period).mean()
    return stoch_k, stoch_d

def bollinger_series(close, period=20, dev=2.0):
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    up = mid + (std * dev)
    low = mid - (std * dev)
    return mid, up, low

def cci_series(high, low, close, period=20):
    tp = (high + low + close) / 3.0
    sma = tp.rolling(window=period).mean()
    mad = tp.rolling(window=period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    return (tp - sma) / (0.015 * mad + 1e-12)

def extract_features(symbol="EURUSD", period_str="M15", bars=20000, horizon=5):
    print(f"Connecting to MT5 to export {symbol} {period_str} ({bars} bars, horizon={horizon})...")
    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    
    tf = TIMEFRAMES.get(period_str.upper())
    if tf is None:
        raise SystemExit(f"Unknown timeframe: {period_str}")
        
    rates_prim = mt5.copy_rates_from(symbol, tf, datetime.now(), bars)
    rates_h4 = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_H4, datetime.now(), max(300, bars // 8))
    rates_d1 = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_D1, datetime.now(), max(150, bars // 40))
    mt5.shutdown()
    
    if rates_prim is None or len(rates_prim) < 500:
        raise SystemExit("Not enough primary timeframe bars returned from MT5.")
        
    df_p = pd.DataFrame(rates_prim)
    df_p["time"] = pd.to_datetime(df_p["time"], unit="s")
    df_p = df_p.sort_values("time").reset_index(drop=True)
    
    df_h4 = pd.DataFrame(rates_h4)
    df_h4["time"] = pd.to_datetime(df_h4["time"], unit="s")
    df_h4 = df_h4.sort_values("time").reset_index(drop=True)
    
    df_d1 = pd.DataFrame(rates_d1)
    df_d1["time"] = pd.to_datetime(df_d1["time"], unit="s")
    df_d1 = df_d1.sort_values("time").reset_index(drop=True)

    # --- Compute Primary Timeframe Features (0..20) ---
    c = df_p["close"]
    h = df_p["high"]
    l = df_p["low"]
    o = df_p["open"]
    
    df_p["ret1"] = np.log(c / c.shift(1))
    df_p["ret3"] = np.log(c / c.shift(3))
    df_p["ret5"] = np.log(c / c.shift(5))
    df_p["ret10"] = np.log(c / c.shift(10))
    df_p["ret20"] = np.log(c / c.shift(20))
    
    df_p["atr"] = atr_series(h, l, c, period=14)
    df_p["rsi"] = rsi_series(c, period=14) / 100.0
    
    macd_val, macd_sig = macd_series(c, 12, 26, 9)
    df_p["macd"] = macd_val / (df_p["atr"] + 1e-12)
    df_p["macd_sig"] = macd_sig / (df_p["atr"] + 1e-12)
    
    bb_mid, bb_up, bb_low = bollinger_series(c, 20, 2.0)
    df_p["bb_up_dist"] = (bb_up - c) / (df_p["atr"] + 1e-12)
    df_p["bb_low_dist"] = (c - bb_low) / (df_p["atr"] + 1e-12)
    df_p["bb_mid_dist"] = (c - bb_mid) / (df_p["atr"] + 1e-12)
    df_p["atr_rel"] = df_p["atr"] / c
    
    stoch_k, stoch_d = stoch_series(h, l, c, 14, 3, 3)
    df_p["stoch_k"] = stoch_k / 100.0
    df_p["stoch_d"] = stoch_d / 100.0
    
    adx_val, plus_di, minus_di = adx_series(h, l, c, period=14)
    df_p["adx"] = adx_val / 100.0
    df_p["di_diff"] = (plus_di - minus_di) / 100.0
    df_p["cci"] = cci_series(h, l, c, period=20) / 100.0
    
    candle_range = (h - l).replace(0, np.nan).fillna(df_p["atr"])
    df_p["range_atr"] = candle_range / (df_p["atr"] + 1e-12)
    df_p["body_range"] = (c - o) / candle_range
    
    hours = df_p["time"].dt.hour
    angle = 2.0 * math.pi * hours / 24.0
    df_p["hour_sin"] = np.sin(angle)
    df_p["hour_cos"] = np.cos(angle)
    
    # --- Compute H4 Context Features (21..25) ---
    df_h4["h4_rsi"] = rsi_series(df_h4["close"], 14) / 100.0
    df_h4["h4_atr"] = atr_series(df_h4["high"], df_h4["low"], df_h4["close"], 14)
    df_h4["h4_atr_rel"] = df_h4["h4_atr"] / df_h4["close"]
    h4_adx, _, _ = adx_series(df_h4["high"], df_h4["low"], df_h4["close"], 14)
    df_h4["h4_adx"] = h4_adx / 100.0
    df_h4["h4_ret1"] = np.log(df_h4["close"] / df_h4["close"].shift(1))
    h4_mid, _, _ = bollinger_series(df_h4["close"], 20, 2.0)
    df_h4["h4_bb_mid_dist"] = (df_h4["close"] - h4_mid) / (df_h4["h4_atr"] + 1e-12)
    
    # Merge H4 to primary timeframe using asof (completed H4 bar close)
    df_p = pd.merge_asof(
        df_p,
        df_h4[["time", "h4_rsi", "h4_atr_rel", "h4_adx", "h4_ret1", "h4_bb_mid_dist"]],
        on="time",
        direction="backward",
    )
    
    # --- Compute D1 Context Features (26..29) ---
    df_d1["d1_rsi"] = rsi_series(df_d1["close"], 14) / 100.0
    df_d1["d1_atr"] = atr_series(df_d1["high"], df_d1["low"], df_d1["close"], 14)
    df_d1["d1_atr_rel"] = df_d1["d1_atr"] / df_d1["close"]
    d1_adx, _, _ = adx_series(df_d1["high"], df_d1["low"], df_d1["close"], 14)
    df_d1["d1_adx"] = d1_adx / 100.0
    df_d1["d1_ret1"] = np.log(df_d1["close"] / df_d1["close"].shift(1))
    
    # Merge D1 to primary timeframe
    df_p = pd.merge_asof(
        df_p,
        df_d1[["time", "d1_rsi", "d1_atr_rel", "d1_adx", "d1_ret1"]],
        on="time",
        direction="backward",
    )
    
    # --- Target Forward Label ---
    fwd_return = np.log(df_p["close"].shift(-horizon) / df_p["close"])
    df_p["fwd"] = fwd_return
    df_p["label"] = (fwd_return > 0.0).astype(int)
    
    feature_cols = [
        "ret1", "ret3", "ret5", "ret10", "ret20",
        "rsi", "macd", "macd_sig", "bb_up_dist", "bb_low_dist",
        "bb_mid_dist", "atr_rel", "stoch_k", "stoch_d", "adx",
        "di_diff", "cci", "range_atr", "body_range", "hour_sin", "hour_cos",
        "h4_rsi", "h4_atr_rel", "h4_adx", "h4_ret1", "h4_bb_mid_dist",
        "d1_rsi", "d1_atr_rel", "d1_adx", "d1_ret1",
    ]
    assert len(feature_cols) == 30
    
    # Clamp features to [-5.0, 5.0]
    for col in feature_cols:
        df_p[col] = df_p[col].clip(lower=-5.0, upper=5.0)
        
    df_clean = df_p.dropna(subset=feature_cols + ["fwd", "label"]).copy()
    
    # Format time string to MQL5 standard
    df_clean["time_str"] = df_clean["time"].dt.strftime("%Y.%m.%d %H:%M")
    
    out_cols = ["time_str"] + feature_cols + ["fwd", "label"]
    df_out = df_clean[out_cols].rename(columns={"time_str": "time"})
    
    out_name = f"features_{symbol}_PERIOD_{period_str.upper()}.csv"
    out_path = os.path.join(MODELS_DIR, out_name)
    df_out.to_csv(out_path, index=False)
    
    print(f"Export complete: {len(df_out):,} rows (30 features + label) saved to:")
    print(f"  -> {out_path}")
    return out_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--period", default="M15")
    parser.add_argument("--bars", type=int, default=20000)
    parser.add_argument("--horizon", type=int, default=5)
    args = parser.parse_args()
    
    extract_features(args.symbol, args.period, args.bars, args.horizon)
