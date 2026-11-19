import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { DatasetSummary, TrainJob } from "../types";
import { LogConsole } from "../components/LogConsole";
import { pct } from "../format";

interface Props {
  initialCsv: string | null;
  onFinished: () => void;
}

export function TrainView({ initialCsv, onFinished }: Props) {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [csv, setCsv] = useState("");
  const [model, setModel] = useState<"mlp" | "logreg" | "xgb" | "lgbm">("mlp");
  const [hidden, setHidden] = useState("32,16");
  const [threshold, setThreshold] = useState(0.55);
  const [cvSplits, setCvSplits] = useState(5);
  const [cvGap, setCvGap] = useState(24);
  const [job, setJob] = useState<TrainJob | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .datasets()
      .then((list) => {
        if (!alive) return;
        setDatasets(list);
        const preferred = list.find((d) => d.name === initialCsv) ?? list[0];
        if (preferred) setCsv(preferred.name);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
      esRef.current?.close();
    };
  }, [initialCsv]);

  function start() {
    if (!csv || running) return;
    setError(null);
    setRunning(true);
    setJob(null);
    setLogs([]);
    esRef.current?.close();

    api
      .train({ csv, model, hidden, threshold, cv_splits: cvSplits, cv_gap: cvGap })
      .then((started) => {
        setJob(started);
        const es = new EventSource(`/api/jobs/${started.id}/events`);
        esRef.current = es;
        es.addEventListener("log", (ev) => {
          try {
            setLogs((prev) => [...prev, JSON.parse((ev as MessageEvent).data)]);
          } catch {
            /* ignore malformed frame */
          }
        });
        es.addEventListener("done", (ev) => {
          try {
            const finished = JSON.parse((ev as MessageEvent).data) as TrainJob;
            setJob(finished);
            setLogs(finished.log ?? []);
          } catch {
            /* ignore malformed frame */
          }
          es.close();
          esRef.current = null;
          setRunning(false);
          onFinished();
        });
        es.onerror = () => {
          es.close();
          esRef.current = null;
          setRunning(false);
          void api.job(started.id).then(setJob).catch(() => undefined);
        };
      })
      .catch((e) => {
        setError(String(e));
        setRunning(false);
      });
  }

  const test = job?.meta?.metrics?.test;
  const val = job?.meta?.metrics?.val;

  return (
    <div className="grid train-grid">
      <div className="card">
        <div className="card-head"><h2>Train model</h2></div>
        {datasets.length === 0 ? (
          <div className="empty">
            No datasets. Run <code>ExportFeatures</code> in MT5 first.
            <button className="btn ghost sm" onClick={() => api.datasets().then(setDatasets)}>
              Recheck
            </button>
          </div>
        ) : (
          <div className="form">
            <label>
              <span>Dataset</span>
              <select value={csv} onChange={(e) => setCsv(e.target.value)} disabled={running}>
                {datasets.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.name} · {d.rows.toLocaleString()} rows
                  </option>
                ))}
              </select>
            </label>

            <div className="form-row">
              <label>
                <span>Model</span>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value as "mlp" | "logreg" | "xgb" | "lgbm")}
                  disabled={running}
                >
                  <option value="mlp">MLP neural net</option>
                  <option value="logreg">Logistic regression</option>
                  <option value="xgb">XGBoost (GBDT)</option>
                  <option value="lgbm">LightGBM (GBDT)</option>
                </select>
              </label>
              <label>
                <span>Hidden layers</span>
                <input
                  value={hidden}
                  onChange={(e) => setHidden(e.target.value)}
                  disabled={running || model !== "mlp"}
                  placeholder="32,16"
                />
              </label>
            </div>

            {model === "mlp" && (
              <div className="preset-row" style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
                <span className="muted small" style={{ alignSelf: "center" }}>Presets:</span>
                {[
                  { name: "nano", val: "16,8" },
                  { name: "small", val: "32,16" },
                  { name: "medium", val: "64,32,16" },
                  { name: "large", val: "128,64,32" },
                ].map((p) => (
                  <button
                    key={p.name}
                    type="button"
                    className={`btn sm ${hidden === p.val ? "primary" : "ghost"}`}
                    onClick={() => setHidden(p.val)}
                    disabled={running}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            )}

            <div className="form-row">
              <label>
                <span>Walk-Forward Splits (CV)</span>
                <input
                  type="number"
                  min={2}
                  max={10}
                  value={cvSplits}
                  onChange={(e) => setCvSplits(Math.max(2, Number(e.target.value)))}
                  disabled={running}
                />
              </label>
              <label>
                <span>CV Leakage Gap (bars)</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={cvGap}
                  onChange={(e) => setCvGap(Math.max(0, Number(e.target.value)))}
                  disabled={running}
                />
              </label>
            </div>

            <label>
              <span>Signal threshold · {threshold.toFixed(2)}</span>
              <input
                type="range"
                min={0.5}
                max={0.9}
                step={0.01}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                disabled={running}
              />
            </label>

            <button className="btn primary" onClick={start} disabled={running || !csv}>
              {running ? "Training…" : "Start training"}
            </button>
            <p className="muted small">
              Output overwrites <code>Models\model.onnx</code> and is archived to
              <code> Models\runs</code> on success.
            </p>
          </div>
        )}
        {error && <div className="banner error">{error}</div>}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Run console</h2>
          {job && (
            <span className={`badge ${job.status === "succeeded" ? "up" : job.status === "failed" ? "down" : "accent"}`}>
              {job.status}
            </span>
          )}
        </div>
        {job && <div className="mono small muted cmd">{job.command}</div>}
        <LogConsole lines={logs} height={380} />
      </div>

      {job?.status === "succeeded" && test && (
        <div className="card">
          <div className="card-head">
            <h2>Result</h2>
            <span className="badge up">{job.run ?? "model.onnx"}</span>
          </div>
          <div className="kv-grid six">
            <div><span>Test accuracy</span><b>{pct(test.accuracy)}</b></div>
            <div><span>Test AUC</span><b>{test.roc_auc?.toFixed(3) ?? "—"}</b></div>
            <div><span>Confident acc.</span><b>{pct(test.confident_accuracy)}</b></div>
            <div><span>CV Mean AUC</span><b>{job.meta?.cv_mean_auc != null ? job.meta.cv_mean_auc.toFixed(3) : "—"}</b></div>
            <div><span>CV Std AUC</span><b>{job.meta?.cv_std_auc != null ? `±${job.meta.cv_std_auc.toFixed(3)}` : "—"}</b></div>
            <div><span>Rows</span><b>{job.meta?.rows?.toLocaleString() ?? "—"}</b></div>
          </div>
          {job.meta?.cv_scores && job.meta.cv_scores.length > 0 && (
            <div style={{ marginTop: "16px" }}>
              <div className="muted small" style={{ marginBottom: "8px" }}>Walk-Forward CV Folds:</div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {job.meta.cv_scores.map((s) => (
                  <div key={s.fold} style={{ background: "rgba(255,255,255,0.05)", padding: "6px 10px", borderRadius: "4px", fontSize: "12px" }}>
                    <b>Fold {s.fold}:</b> AUC {s.roc_auc != null ? s.roc_auc.toFixed(3) : "N/A"} · Acc {pct(s.accuracy)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {job?.status === "failed" && (
        <div className="card">
          <div className="banner error">
            Training failed with exit code {job.exit_code}. Check the console output above.
          </div>
        </div>
      )}
    </div>
  );
}
