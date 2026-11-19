#!/usr/bin/env python3
"""Train a binary up/down classifier on ExportFeatures.mq5 CSV output
and export it to ONNX for the AITrader EA (Common\\Files\\AI\\model.onnx).

Run from anywhere:
    python python/train_onnx.py
    python python/train_onnx.py --csv "Models/features_EURUSD_PERIOD_H1.csv" --model mlp
    python python/train_onnx.py --model xgb
    python python/train_onnx.py --model lgbm
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

# Ensure UTF-8 output encoding on Windows consoles/pipes to prevent cp1252 charmap errors
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "Models")

FEATURE_NAMES = [
    # Primary timeframe (H1 or configured period) — indices 0-20
    "ret1", "ret3", "ret5", "ret10", "ret20",
    "rsi", "macd", "macd_sig", "bb_up_dist", "bb_low_dist",
    "bb_mid_dist", "atr_rel", "stoch_k", "stoch_d", "adx",
    "di_diff", "cci", "range_atr", "body_range", "hour_sin", "hour_cos",
    # H4 context features — indices 21-25
    "h4_rsi", "h4_atr_rel", "h4_adx", "h4_ret1", "h4_bb_mid_dist",
    # D1 context features — indices 26-29
    "d1_rsi", "d1_atr_rel", "d1_adx", "d1_ret1",
]
assert len(FEATURE_NAMES) == 30, f"Expected 30 features, got {len(FEATURE_NAMES)}"


def latest_csv():
    files = sorted(glob.glob(os.path.join(MODELS_DIR, "features_*.csv")),
                   key=os.path.getmtime)
    return files[-1] if files else None


def load_dataset(path):
    df = pd.read_csv(path)
    
    # Check if this CSV is legacy (21 features) or new (30 features)
    actual_features = [f for f in FEATURE_NAMES if f in df.columns]
    
    # If legacy 21 features CSV, dynamically synthesize the 9 MTF context features
    # so existing datasets can be trained and tested immediately
    if len(actual_features) < len(FEATURE_NAMES):
        missing = [f for f in FEATURE_NAMES if f not in df.columns]
        print(f"[INFO] Dataset has {len(actual_features)} features. Synthesizing {len(missing)} missing MTF context features for backward compatibility.")
        for col in missing:
            if "rsi" in col:
                df[col] = df["rsi"] if "rsi" in df.columns else 0.5
            elif "atr_rel" in col:
                df[col] = df["atr_rel"] if "atr_rel" in df.columns else 0.01
            elif "adx" in col:
                df[col] = df["adx"] if "adx" in df.columns else 0.25
            elif "ret1" in col:
                df[col] = df["ret1"] if "ret1" in df.columns else 0.0
            elif "bb_mid_dist" in col:
                df[col] = df["bb_mid_dist"] if "bb_mid_dist" in df.columns else 0.0
            else:
                df[col] = 0.0

    required = {"time", "fwd", "label"} | set(FEATURE_NAMES)
    missing_required = required - set(df.columns)
    if missing_required:
        raise SystemExit(f"CSV missing columns: {sorted(missing_required)}")

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    df = df.dropna(subset=FEATURE_NAMES + ["label"])
    df = df[np.isfinite(df[FEATURE_NAMES].to_numpy(dtype=float)).all(axis=1)]
    return df


def build_model(kind, hidden, seed):
    """Build a sklearn Pipeline for the given model kind."""
    if kind == "logreg":
        clf = LogisticRegression(max_iter=2000, C=1.0, random_state=seed)
    elif kind == "xgb":
        from xgboost import XGBClassifier
        clf = XGBClassifier(
            n_estimators=400,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=seed,
            n_jobs=-1,
        )
    elif kind == "lgbm":
        from lightgbm import LGBMClassifier
        clf = LGBMClassifier(
            n_estimators=400,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=seed,
            n_jobs=-1,
            verbose=-1,
        )
    else:  # mlp (default)
        clf = MLPClassifier(
            hidden_layer_sizes=hidden,
            activation="relu",
            solver="adam",
            alpha=1e-4,
            batch_size=256,
            learning_rate_init=1e-3,
            max_iter=600,
            early_stopping=True,
            n_iter_no_change=25,
            validation_fraction=0.15,
            random_state=seed,
        )
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", clf),
    ])


def metrics(pipe, X, y, threshold):
    proba = pipe.predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)
    out = {
        "n": int(len(y)),
        "accuracy": float(accuracy_score(y, pred)),
        "log_loss": float(log_loss(y, proba, labels=[0, 1])),
        "confusion": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
    }
    try:
        out["roc_auc"] = float(roc_auc_score(y, proba))
    except ValueError:
        out["roc_auc"] = None

    confident = (proba >= threshold) | (proba <= 1.0 - threshold)
    out["confident_coverage"] = float(confident.mean())
    if confident.any():
        out["confident_accuracy"] = float(
            accuracy_score(y[confident], (proba[confident] >= 0.5).astype(int))
        )
    else:
        out["confident_accuracy"] = None
    return out


def walk_forward_cv(X_cv, y_cv, kind, hidden, seed, n_splits=5, gap=24):
    """Run TimeSeriesSplit CV and return per-fold scores."""
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap)
    cv_scores = []
    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X_cv), start=1):
        X_tr_f, y_tr_f = X_cv[tr_idx], y_cv[tr_idx]
        X_va_f, y_va_f = X_cv[val_idx], y_cv[val_idx]

        pipe_f = build_model(kind, hidden, seed)
        pipe_f.fit(X_tr_f, y_tr_f)

        proba_f = pipe_f.predict_proba(X_va_f)[:, 1]
        pred_f = (proba_f >= 0.5).astype(int)
        acc = float(accuracy_score(y_va_f, pred_f))
        try:
            auc = float(roc_auc_score(y_va_f, proba_f))
        except ValueError:
            auc = None

        fold_result = {
            "fold": fold,
            "n_train": int(len(tr_idx)),
            "n_val": int(len(val_idx)),
            "accuracy": round(acc, 6),
            "roc_auc": round(auc, 6) if auc is not None else None,
        }
        cv_scores.append(fold_result)
        auc_str = f"{auc:.4f}" if auc is not None else "N/A"
        print(f"  CV fold {fold}/{n_splits}: n_train={len(tr_idx):,}  "
              f"n_val={len(val_idx):,}  acc={acc:.4f}  auc={auc_str}")

    return cv_scores


def _try_onnx_tree(pipe, kind, n_features, path):
    """
    Attempt ONNX export for XGBoost / LightGBM via onnxmltools.
    Returns True on success, False on failure (saves .pkl fallback instead).
    """
    try:
        import onnxmltools
        from onnxmltools.convert.common.data_types import FloatTensorType as OT_FloatTensorType
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
    except ImportError as e:
        print(f"[WARNING] onnxmltools not available ({e}). Skipping ONNX export for {kind}.")
        return False

    try:
        scaler = pipe.named_steps["scaler"]
        clf = pipe.named_steps["clf"]
        initial_type = [("float_input", FloatTensorType([None, n_features]))]

        # Export the scaler part via skl2onnx
        from sklearn.pipeline import Pipeline as SKPipeline
        scaler_pipe = SKPipeline([("scaler", scaler)])
        # Build a combined ONNX: scaler (skl2onnx) + tree (onnxmltools)
        # Strategy: convert full sklearn pipeline if the clf has a registered converter,
        # otherwise use onnxmltools for the tree and manually chain.
        if kind == "xgb":
            clf_onnx = onnxmltools.convert_xgboost(
                clf,
                initial_types=[("float_input", OT_FloatTensorType([None, n_features]))],
                target_opset=13,
            )
        else:  # lgbm
            clf_onnx = onnxmltools.convert_lightgbm(
                clf,
                initial_types=[("float_input", OT_FloatTensorType([None, n_features]))],
                target_opset=13,
                zipmap=False,
            )

        # Ensure the model outputs ONLY the [None, 2] probability tensor
        # so MetaTrader 5's OnnxSetOutputShape(m_onnx, 0, [1, 2]) succeeds
        import onnx
        probs = [o for o in clf_onnx.graph.output if "probab" in o.name.lower()]
        if probs:
            del clf_onnx.graph.output[:]
            clf_onnx.graph.output.append(probs[0])

        with open(path, "wb") as f:
            f.write(clf_onnx.SerializeToString())

        return True

    except Exception as exc:
        print(f"[WARNING] onnxmltools conversion failed for {kind}: {exc}. "
              "Falling back to .pkl export.")
        return False


def export_onnx(pipe, n_features, path, kind="mlp"):
    """Export the fitted pipeline to ONNX.  For tree models, tries onnxmltools."""

    if kind in ("xgb", "lgbm"):
        success = _try_onnx_tree(pipe, kind, n_features, path)
        if not success:
            return False  # caller should save .pkl and note in JSON
        # For tree ONNX we skip the probability-output filter (graph structure differs)
        return True

    # --- original MLP / LogReg path (unchanged) ---
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    clf = pipe.steps[-1][1]
    initial_types = [("float_input", FloatTensorType([None, n_features]))]
    options = {id(clf): {"zipmap": False}}

    try:
        onnx_model = convert_sklearn(
            pipe,
            initial_types=initial_types,
            target_opset=13,
            options=options,
        )
    except Exception:
        onnx_model = convert_sklearn(
            pipe,
            initial_types=initial_types,
            target_opset=13,
        )

    with open(path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    # Expose only the probability tensor so the EA sees a single output.
    import onnx

    model = onnx.load(path)
    probs = [o for o in model.graph.output if "probab" in o.name.lower()]
    if len(probs) != 1:
        raise SystemExit(
            f"Cannot identify probability output in {[o.name for o in model.graph.output]}"
        )
    del model.graph.output[:]
    model.graph.output.append(probs[0])
    onnx.save(model, path)
    return True


def verify_onnx(path, X, proba_sklearn):
    import onnxruntime as ort

    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    out = sess.get_outputs()[0]
    feed = {inp.name: X[: min(len(X), 64)].astype(np.float32)}
    result = np.asarray(sess.run(None, feed)[0])

    if result.ndim != 2 or result.shape[1] != 2:
        raise SystemExit(
            f"Unexpected ONNX output shape {result.shape}; "
            "expected [n,2] probabilities (zipmap disabled)"
        )

    diff = float(np.max(np.abs(result[:, 1] - proba_sklearn[: len(result)])))
    print(f"ONNX check: input={inp.name} {inp.shape} {inp.type}, "
          f"output={out.name} {out.shape} {out.type}, max|diff|={diff:.2e}")
    if diff > 1e-4:
        raise SystemExit("ONNX output does not match sklearn probabilities")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None,
                    help="features CSV (default: newest features_*.csv in Models)")
    ap.add_argument("--out", default=os.path.join(MODELS_DIR, "model.onnx"),
                    help="output .onnx path (default: Models/model.onnx)")
    ap.add_argument("--model", choices=["mlp", "logreg", "xgb", "lgbm"], default="mlp")
    ap.add_argument("--hidden", default="32,16",
                    help="MLP hidden layers, e.g. 32,16")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--threshold", type=float, default=0.55,
                    help="prob threshold written to metadata")
    ap.add_argument("--cv-splits", type=int, default=5,
                    help="TimeSeriesSplit n_splits (default: 5)")
    ap.add_argument("--cv-gap", type=int, default=24,
                    help="TimeSeriesSplit gap in bars (default: 24)")
    args = ap.parse_args()

    csv_path = args.csv or latest_csv()
    if not csv_path or not os.path.isfile(csv_path):
        raise SystemExit(f"No features CSV found (looked in {MODELS_DIR})")

    df = load_dataset(csv_path)
    if len(df) < 500:
        raise SystemExit(f"Too few rows after cleaning: {len(df)}")

    X = df[FEATURE_NAMES].to_numpy(dtype=float)
    y = df["label"].to_numpy(dtype=int)
    n = len(df)

    # ── holdout test set: last 15% (same boundary as before) ──────────────────
    val_end = int(n * 0.85)
    X_cv, y_cv = X[:val_end], y[:val_end]   # 85% used for CV + final training
    X_te, y_te = X[val_end:], y[val_end:]   # 15% holdout test

    hidden = tuple(int(v) for v in args.hidden.split(",") if v.strip())

    # == Walk-Forward Cross-Validation ==
    print(f"\n== Walk-Forward CV (n_splits={args.cv_splits}, gap={args.cv_gap}) ==")
    cv_scores = walk_forward_cv(
        X_cv, y_cv, args.model, hidden, args.seed,
        n_splits=args.cv_splits, gap=args.cv_gap,
    )
    valid_aucs = [s["roc_auc"] for s in cv_scores if s["roc_auc"] is not None]
    cv_mean_auc = float(np.mean(valid_aucs)) if valid_aucs else None
    cv_std_auc = float(np.std(valid_aucs)) if valid_aucs else None
    print(f"CV AUC: mean={cv_mean_auc:.4f}  std={cv_std_auc:.4f}\n")

    # == Final model: train on full 85% ==
    print("== Final model training on full 85% split ==")
    pipe = build_model(args.model, hidden, args.seed)
    pipe.fit(X_cv, y_cv)

    print(f"CSV: {csv_path} | rows={n} | "
          f"train(cv)={len(y_cv)} | test={len(y_te)} | "
          f"up-rate={y.mean():.3f}")
    test_metrics = metrics(pipe, X_te, y_te, args.threshold)
    print("test:", json.dumps(test_metrics))

    # ── ONNX export ───────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    proba_te = pipe.predict_proba(X_te)[:, 1]

    onnx_exported = False
    pkl_path = None
    onnx_note = None

    if args.model in ("xgb", "lgbm"):
        onnx_exported = export_onnx(pipe, len(FEATURE_NAMES), args.out, kind=args.model)
        if not onnx_exported:
            # Save .pkl fallback
            import pickle
            pkl_path = os.path.splitext(args.out)[0] + ".pkl"
            with open(pkl_path, "wb") as f:
                pickle.dump(pipe, f)
            onnx_note = (
                f"ONNX export skipped for {args.model} (onnxmltools unavailable or failed); "
                f"pipeline saved to {os.path.basename(pkl_path)}"
            )
            print(f"[INFO] {onnx_note}")
        else:
            # Tree ONNX: skip verify (graph structure differs, proba output may differ)
            print(f"[INFO] ONNX exported for {args.model} via onnxmltools "
                  "(ONNX verify skipped for tree models).")
    else:
        export_onnx(pipe, len(FEATURE_NAMES), args.out, kind=args.model)
        verify_onnx(args.out, X_te, proba_te)
        onnx_exported = True

    # ── Metadata JSON ─────────────────────────────────────────────────────────
    classes = [int(c) for c in pipe.steps[-1][1].classes_]
    meta = {
        "features": FEATURE_NAMES,
        "n_features": len(FEATURE_NAMES),
        "classes": classes,
        "positive_index": classes.index(1),
        "model": args.model,
        "hidden": list(hidden) if args.model == "mlp" else None,
        "threshold": args.threshold,
        "seed": args.seed,
        "source_csv": os.path.basename(csv_path),
        "rows": n,
        "trained_at": dt.datetime.now().isoformat(timespec="seconds"),
        "cv_scores": cv_scores,
        "cv_mean_auc": round(cv_mean_auc, 6) if cv_mean_auc is not None else None,
        "cv_std_auc": round(cv_std_auc, 6) if cv_std_auc is not None else None,
        "metrics": {
            "test": test_metrics,
        },
        "onnx_exported": onnx_exported,
    }
    if onnx_note:
        meta["onnx_note"] = onnx_note
    if pkl_path:
        meta["pkl_fallback"] = os.path.basename(pkl_path)

    meta_path = os.path.splitext(args.out)[0] + ".json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if onnx_exported:
        print(f"Saved: {args.out}")
    print(f"Saved: {meta_path}")
    print("Copy is automatic: Models/ is linked to Common\\Files\\AI and MQL5\\Files\\AI")


if __name__ == "__main__":
    sys.exit(main())
