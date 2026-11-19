import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { DatasetSummary } from "../types";
import { bytes, pct, shortDate } from "../format";

interface Props {
  onTrain: (name: string) => void;
}

export function DataView({ onTrain }: Props) {
  const [rows, setRows] = useState<DatasetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setRows(await api.datasets());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 10000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Datasets</h2>
          <p className="muted small">
            Export with <code>Scripts\AI\ExportFeatures</code> in MT5 — files land in
            <code> D:\maxout\model V1\Models</code>.
          </p>
        </div>
        <button className="btn ghost sm" onClick={() => void load()}>Refresh</button>
      </div>

      {error && <div className="banner error">{error}</div>}
      {loading ? (
        <div className="empty">loading datasets…</div>
      ) : rows.length === 0 ? (
        <div className="empty">
          No CSVs yet. Open a chart, run <code>ExportFeatures</code>, then refresh.
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Dataset</th>
                <th className="num">Rows</th>
                <th className="num">Feat.</th>
                <th>Up share</th>
                <th>Range</th>
                <th className="num">Size</th>
                <th className="num">Modified</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.name}>
                  <td className="mono">{d.name}</td>
                  <td className="num">{d.rows.toLocaleString()}</td>
                  <td className="num">{d.features}</td>
                  <td>
                    <div className="rate">
                      <div className="rate-bar">
                        <span style={{ width: `${Math.round(d.up_rate * 100)}%` }} />
                      </div>
                      <span className="rate-label">{pct(d.up_rate)}</span>
                    </div>
                  </td>
                  <td className="mono small">{d.first_row ?? "—"} → {d.last_row ?? "—"}</td>
                  <td className="num">{bytes(d.size)}</td>
                  <td className="num small">{shortDate(d.modified)}</td>
                  <td className="right">
                    <button className="btn primary sm" onClick={() => onTrain(d.name)}>
                      Train
                    </button>
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
