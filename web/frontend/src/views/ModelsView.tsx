import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ModelInfo } from "../types";
import { bytes, pct, shortDate } from "../format";

interface Props {
  onChanged: () => void;
}

export function ModelsView({ onChanged }: Props) {
  const [rows, setRows] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setRows(await api.models());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function activate(name: string) {
    setBusy(name);
    setError(null);
    try {
      await api.activate(name);
      await load();
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Models</h2>
          <p className="muted small">
            The EA always loads <code>AI\model.onnx</code>. Activating a run copies it
            to the active slot (previous model is archived to <code>runs\prev_*.onnx</code>).
          </p>
        </div>
        <button className="btn ghost sm" onClick={() => void load()}>Refresh</button>
      </div>

      {error && <div className="banner error">{error}</div>}
      {loading ? (
        <div className="empty">loading models…</div>
      ) : rows.length === 0 ? (
        <div className="empty">No models yet — train one from the Train tab.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Type</th>
                <th className="num">Rows</th>
                <th className="num">CV Mean AUC</th>
                <th className="num">Test AUC</th>
                <th className="num">Test acc.</th>
                <th className="num">Threshold</th>
                <th className="num">Size</th>
                <th className="num">Trained</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.name} className={m.active ? "active-row" : undefined}>
                  <td className="mono">
                    {m.name}
                    {m.active && <span className="badge up ml">active</span>}
                  </td>
                  <td><span className="badge accent">{m.meta?.model ?? "?"}</span></td>
                  <td className="num">{m.meta?.rows?.toLocaleString() ?? "—"}</td>
                  <td className="num">
                    {m.meta?.cv_mean_auc != null ? (
                      <span title={m.meta.cv_std_auc != null ? `±${m.meta.cv_std_auc.toFixed(3)}` : ""}>
                        {m.meta.cv_mean_auc.toFixed(3)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="num">{m.meta?.metrics?.test?.roc_auc?.toFixed(3) ?? "—"}</td>
                  <td className="num">{pct(m.meta?.metrics?.test?.accuracy)}</td>
                  <td className="num">{m.meta?.threshold ?? "—"}</td>
                  <td className="num">{bytes(m.size)}</td>
                  <td className="num small">{shortDate(m.meta?.trained_at ?? m.modified)}</td>
                  <td className="right">
                    {!m.active && (
                      <button
                        className="btn ghost sm"
                        disabled={busy === m.name}
                        onClick={() => void activate(m.name)}
                      >
                        {busy === m.name ? "Activating…" : "Activate"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
