import type { HistoryPoint, Overview } from "../types";
import { money, pct, shortDate, timeAgo } from "../format";
import { StatCard } from "../components/StatCard";
import { Sparkline } from "../components/Sparkline";
import { ProbGauge } from "../components/ProbGauge";

interface Props {
  overview: Overview | null;
  history: HistoryPoint[];
  go: (tab: "data" | "train" | "models" | "live") => void;
}

export function OverviewView({ overview, history, go }: Props) {
  const status = overview?.status;
  const model = overview?.active_model;
  const meta = model?.meta;
  const dataset = overview?.latest_dataset;
  const test = meta?.metrics?.test;
  const val = meta?.metrics?.val;
  const signal = status?.signal ?? "—";
  const signalTone =
    signal === "BUY" ? "up" : signal === "SELL" ? "down" : "muted";

  const steps = [
    {
      done: overview?.checklist.exported ?? false,
      title: "Export features",
      hint: "Run Scripts\\AI\\ExportFeatures in MT5",
      tab: "data" as const,
    },
    {
      done: overview?.checklist.trained ?? false,
      title: "Train model",
      hint: "Train on the newest CSV from the dashboard",
      tab: "train" as const,
    },
    {
      done: overview?.checklist.live ?? false,
      title: "Attach AITrader",
      hint: "Telemetry appears once the EA is on a chart",
      tab: "live" as const,
    },
  ];

  return (
    <>
      <div className="grid stat-grid">
        <StatCard
          label="Active model · test accuracy"
          value={pct(test?.accuracy)}
          sub={test?.roc_auc != null ? `AUC ${test.roc_auc.toFixed(3)}` : "no model yet"}
          tone="accent"
        />
        <StatCard
          label="Latest dataset"
          value={dataset ? dataset.rows.toLocaleString() : "—"}
          sub={dataset ? `${dataset.name} · ${pct(dataset.up_rate)} up` : "export a CSV first"}
        />
        <StatCard
          label="EA signal"
          value={signal}
          sub={
            status?.available
              ? `${pct(status.prob_up)} P(up) · ${status.position ?? "FLAT"}`
              : "EA offline"
          }
          tone={signalTone}
        />
        <StatCard
          label="Account equity"
          value={money(status?.equity)}
          sub={status?.available ? `${timeAgo(status.updated)}` : "telemetry inactive"}
        />
      </div>

      <div className="grid two-col">
        <div className="card">
          <div className="card-head">
            <h2>Active model</h2>
            <button className="btn ghost sm" onClick={() => go("models")}>All models</button>
          </div>
          {model ? (
            <>
              <div className="model-title">{model.file}</div>
              <div className="meta-row">
                <span className="badge accent">{meta?.model ?? "?"}</span>
                <span className="badge">{meta?.rows?.toLocaleString() ?? "—"} rows</span>
                <span className="badge">thr {meta?.threshold ?? "—"}</span>
                <span className="badge">{meta?.trained_at ? timeAgo(meta.trained_at) : "unknown"}</span>
              </div>
              <div className="kv-grid">
                <div><span>Val accuracy</span><b>{pct(val?.accuracy)}</b></div>
                <div><span>Test accuracy</span><b>{pct(test?.accuracy)}</b></div>
                <div><span>Val AUC</span><b>{val?.roc_auc?.toFixed(3) ?? "—"}</b></div>
                <div><span>Test AUC</span><b>{test?.roc_auc?.toFixed(3) ?? "—"}</b></div>
                <div><span>Confident acc.</span><b>{pct(test?.confident_accuracy)}</b></div>
                <div><span>Trained</span><b>{shortDate(meta?.trained_at)}</b></div>
              </div>
            </>
          ) : (
            <div className="empty">
              No model yet — export features, then train one.
              <button className="btn primary sm" onClick={() => go("train")}>Go to training</button>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Live EA</h2>
            <button className="btn ghost sm" onClick={() => go("live")}>Open live</button>
          </div>
          <div className="live-row">
            <ProbGauge prob={status?.prob_up} threshold={status?.threshold ?? 0.55} />
            <div className="live-facts">
              <div><span>Symbol</span><b>{status?.symbol ?? "—"} {status?.period?.replace("PERIOD_", "") ?? ""}</b></div>
              <div><span>Signal</span><b className={signalTone}>{signal}</b></div>
              <div><span>Position</span><b>{status?.position ?? "—"}{status?.lots ? ` · ${status.lots}` : ""}</b></div>
              <div><span>Balance</span><b>{money(status?.balance)}</b></div>
              <div><span>Telemetry</span><b>{status?.available ? timeAgo(status.updated) : "offline"}</b></div>
            </div>
          </div>
          <div className="sparkline-wrap">
            <div className="sparkline-label">P(up) per bar</div>
            <Sparkline data={history.map((h) => h.p)} />
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Setup checklist</h2></div>
        <div className="steps">
          {steps.map((s, i) => (
            <button
              key={s.title}
              className={`step ${s.done ? "done" : ""}`}
              onClick={() => go(s.tab)}
            >
              <span className="step-index">{s.done ? "✓" : i + 1}</span>
              <span className="step-body">
                <b>{s.title}</b>
                <small>{s.hint}</small>
              </span>
              <span className="step-action">{s.done ? "done" : "open"}</span>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
