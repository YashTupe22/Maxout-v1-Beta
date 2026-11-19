# Feature Layout — AITrader Model V1

> [!IMPORTANT]
> This file is the **single source of truth** for the feature vector layout.
> `Features.mqh` (MQL5) and `python/train_onnx.py` **must** match this layout exactly.
> Any change here requires a coordinated update to both files and a model retrain.

**Total features:** 30  
**`AI_FEATURE_COUNT` define:** `30`  
**Array indexing:** 0-based, row-major (one flat `double[30]` per bar)

---

## Primary Timeframe Features (indices 0–20)

Computed on the EA's configured timeframe (`m_period`).  
ATR normalization uses the primary-TF ATR(14) of the same bar.

| Index | Name | Formula | Notes |
|------:|------|---------|-------|
| 0 | `ret1` | `log(close[0] / close[1])` | 1-bar log-return |
| 1 | `ret3` | `log(close[0] / close[3])` | 3-bar log-return |
| 2 | `ret5` | `log(close[0] / close[5])` | 5-bar log-return |
| 3 | `ret10` | `log(close[0] / close[10])` | 10-bar log-return |
| 4 | `ret20` | `log(close[0] / close[20])` | 20-bar log-return |
| 5 | `rsi` | `RSI(14) / 100.0` | Bounded [0, 1] |
| 6 | `macd` | `MACD_main / ATR` | MACD(12,26,9), ATR-normalised |
| 7 | `macd_sig` | `MACD_signal / ATR` | Signal line, ATR-normalised |
| 8 | `bb_up_dist` | `(BB_upper - close) / ATR` | BB(20, 2σ) upper band distance |
| 9 | `bb_low_dist` | `(close - BB_lower) / ATR` | BB lower band distance |
| 10 | `bb_mid_dist` | `(close - BB_mid) / ATR` | BB midline distance |
| 11 | `atr_rel` | `ATR / close` | Relative volatility |
| 12 | `stoch_k` | `Stoch_K(14,3,3) / 100.0` | Stochastic %K |
| 13 | `stoch_d` | `Stoch_D(14,3,3) / 100.0` | Stochastic %D |
| 14 | `adx` | `ADX(14) / 100.0` | Trend strength |
| 15 | `di_diff` | `(+DI − −DI) / 100.0` | Directional bias; negative = downtrend |
| 16 | `cci` | `CCI(20) / 100.0` | Commodity Channel Index |
| 17 | `range_atr` | `(high − low) / ATR` | Candle range relative to ATR |
| 18 | `body_range` | `(close − open) / (high − low)` | Body fraction; ±1 = full candle |
| 19 | `hour_sin` | `sin(2π × hour / 24)` | Cyclic hour encoding |
| 20 | `hour_cos` | `cos(2π × hour / 24)` | Cyclic hour encoding |

---

## H4 Context Features (indices 21–25)

Computed on **PERIOD_H4**, always using the **last completed H4 bar** (`[1]` in MQL5 buffer, most-recent-first ordering).  
ATR normalization uses H4 ATR(14).

| Index | Name | Formula | Notes |
|------:|------|---------|-------|
| 21 | `h4_rsi` | `RSI_H4(14)[1] / 100.0` | H4 momentum |
| 22 | `h4_atr_rel` | `ATR_H4(14)[1] / H4_close[1]` | H4 relative volatility |
| 23 | `h4_adx` | `ADX_H4(14)[1] / 100.0` | H4 trend strength |
| 24 | `h4_ret1` | `log(H4_close[1] / H4_close[2])` | H4 1-bar log-return |
| 25 | `h4_bb_mid_dist` | `(H4_close[1] − H4_BB_mid[1]) / H4_ATR[1]` | H4 Bollinger midline distance, BB(20, 2σ) |

---

## D1 Context Features (indices 26–29)

Computed on **PERIOD_D1**, always using the **last completed D1 bar** (`[1]` in MQL5 buffer).  
ATR normalization uses D1 ATR(14).

| Index | Name | Formula | Notes |
|------:|------|---------|-------|
| 26 | `d1_rsi` | `RSI_D1(14)[1] / 100.0` | Daily momentum |
| 27 | `d1_atr_rel` | `ATR_D1(14)[1] / D1_close[1]` | Daily relative volatility |
| 28 | `d1_adx` | `ADX_D1(14)[1] / 100.0` | Daily trend strength |
| 29 | `d1_ret1` | `log(D1_close[1] / D1_close[2])` | Daily 1-bar log-return |

---

## Global Constraints

| Property | Value |
|----------|-------|
| Clamp range | `[-5.0, +5.0]` applied to **all 30 features** after computation |
| NaN guard | If any feature is non-finite, `Compute()` returns `false` and the bar is skipped |
| `AI_FEATURE_COUNT` | `30` |
| `AI_MIN_BARS` | `AI_FEATURE_COUNT + 120 = 150` bars minimum on the primary TF |
| H4 buffer size | At least `30` bars loaded unconditionally |
| D1 buffer size | At least `30` bars loaded unconditionally |

---

## Python Training Column Order

In `python/train_onnx.py`, the feature columns must appear in exactly this order:

```python
FEATURE_COLS = [
    # Primary TF
    "ret1", "ret3", "ret5", "ret10", "ret20",
    "rsi", "macd", "macd_sig", "bb_up_dist", "bb_low_dist",
    "bb_mid_dist", "atr_rel", "stoch_k", "stoch_d", "adx",
    "di_diff", "cci", "range_atr", "body_range", "hour_sin", "hour_cos",
    # H4 context
    "h4_rsi", "h4_atr_rel", "h4_adx", "h4_ret1", "h4_bb_mid_dist",
    # D1 context
    "d1_rsi", "d1_atr_rel", "d1_adx", "d1_ret1",
]
assert len(FEATURE_COLS) == 30
```

---

## Indicator Parameters Summary

| Indicator | Period | Params | Used for |
|-----------|--------|--------|----------|
| ATR | primary, H4, D1 | period=14 | Normalisation |
| RSI | primary, H4, D1 | period=14, price=CLOSE | Momentum |
| MACD | primary | fast=12, slow=26, signal=9, price=CLOSE | Trend/momentum |
| Bollinger Bands | primary, H4 | period=20, shift=0, dev=2.0, price=CLOSE | Volatility range |
| Stochastic | primary | K=14, D=3, slowing=3, method=SMA, price=LOWHIGH | Oscillator |
| ADX | primary, H4, D1 | period=14 | Trend strength |
| CCI | primary | period=20, price=TYPICAL | Cycle indicator |

---

*Last updated: 2026-11-19 — feature count bumped 21 → 30 (H4 + D1 MTF context added)*
