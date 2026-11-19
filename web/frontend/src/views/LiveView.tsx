import { useEffect, useState } from "react";
import type { HistoryPoint, LiveStatus, RiskStatus } from "../types";
import { fixed, money, pct, timeAgo } from "../format";
import { ProbGauge } from "../components/ProbGauge";
import { Sparkline } from "../components/Sparkline";
import { api } from "../api";

interface Props {
  status: LiveStatus;
  history: HistoryPoint[];
}

export function LiveView({ status, history }: Props) {
  const [news, setNews] = useState<{ paused: boolean; no_trade_until?: number; seconds_remaining?: number; reason?: string }>({ paused: false });
  const [pauseMinutes, setPauseMinutes] = useState(60);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [resettingRisk, setResettingRisk] = useState(false);

  useEffect(() => {
    let alive = true;
    const fetchNews = () => {
      api.newsStatus().then((res) => { if (alive) setNews(res); }).catch(() => {});
    };
    const fetchRisk = () => {
      api.riskStatus().then((res) => { if (alive) setRisk(res); }).catch(() => {});
    };
    fetchNews();
    fetchRisk();
    const id = setInterval(() => {
      fetchNews();
      fetchRisk();
    }, 4000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  async function handlePause() {
    await api.newsPause(pauseMinutes, "Manual News Pause");
    const updated = await api.newsStatus();
    setNews(updated);
  }

  async function handleResume() {
    await api.newsResume();
    const updated = await api.newsStatus();
    setNews(updated);
  }

  async function handleResetBreaker() {
    setResettingRisk(true);
    try {
      await api.resetCircuitBreaker();
      const updated = await api.riskStatus();
      setRisk(updated);
    } catch {
      /* ignore */
    } finally {
      setResettingRisk(false);
    }
  }

  if (!status.available) {
    return (
      <div className="card">
        <div className="card-head"><h2>Live EA</h2></div>
        <div className="empty tall">
          <p>No telemetry file yet.</p>
          <p className="muted">
            Attach <code>AITrader</code> to a chart with <code>Inp_AI_Telemetry = true</code>.
            The EA writes <code>Common\Files\AI\live_status.json</code> once per closed bar;
            this dashboard reads it through the <code>D:\maxout\model V1\Models</code> junction.
          </p>
        </div>
      </div>
    );
  }

  const signal = status.signal ?? "—";
  const tone = signal === "BUY" ? "up" : signal === "SELL" ? "down" : "muted";

  const dailyStart = risk?.daily_start_equity ?? status.daily_start_equity ?? status.equity ?? 0;
  const currentEq = risk?.current_equity ?? status.equity ?? 0;
  const dailyDD = risk?.daily_drawdown_pct ?? status.daily_drawdown_pct ?? 0;
  const maxDD = risk?.max_daily_drawdown_pct ?? 3.0;
  const curSpread = risk?.current_spread_points ?? status.spread_pts ?? 0;
  const maxSpread = risk?.max_spread_points ?? status.max_spread_pts ?? 30;
  const breakerLocked = risk?.circuit_breaker_active ?? status.circuit_breaker ?? false;
  const tradingAllowed = risk?.trading_allowed ?? (!breakerLocked && curSpread <= maxSpread);

  return (
    <div className="grid live-grid">
      <div className="card live-hero">
        <div className="card-head">
          <div>
            <h2>Live EA</h2>
            <p className="muted small">
              {status.symbol} · {status.period?.replace("PERIOD_", "")} · {status.model}
            </p>
          </div>
          <span className={`badge ${status.fresh ? "up" : "down"}`}>
            {status.fresh ? "fresh" : "stale"} · {timeAgo(status.file_mtime ?? status.updated)}
          </span>
        </div>
        <div className="hero-body">
          <ProbGauge prob={status.prob_up} threshold={status.threshold ?? 0.55} />
          <div className="hero-signal">
            <div className={`signal ${tone}`}>{signal}</div>
            <div className="muted small">threshold {status.threshold?.toFixed(2) ?? "—"}</div>
            <div className="muted tiny">bar {status.bar_time ?? "—"}</div>
          </div>
        </div>
        <div className="sparkline-wrap">
          <div className="sparkline-label">P(up) per closed bar</div>
          <Sparkline data={history.map((h) => h.p)} height={70} />
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Position & account</h2></div>
        <div className="kv-grid">
          <div><span>Position</span><b className={tone}>{status.position ?? "—"}</b></div>
          <div><span>Lots</span><b>{fixed(status.lots, 2)}</b></div>
          <div><span>Close</span><b>{fixed(status.close, 5)}</b></div>
          <div><span>P(up)</span><b>{pct(status.prob_up, 2)}</b></div>
          <div><span>Balance</span><b>{money(status.balance)}</b></div>
          <div><span>Equity</span><b>{money(status.equity)}</b></div>
          <div><span>Free margin</span><b>{money(status.margin_free)}</b></div>
          <div><span>Updated</span><b>{status.updated ?? "—"}</b></div>
        </div>
        <p className="muted small note">
          Telemetry is written on new bars only. In the Strategy Tester it is disabled by design.
        </p>
      </div>

      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-head">
          <div>
            <h2>Risk & Protection</h2>
            <p className="muted small">Phase 1 Capital Protection & Real-time Execution Guardrails</p>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span className={`badge ${tradingAllowed ? "up" : "down"}`}>
              {tradingAllowed ? "TRADING PERMITTED" : "TRADING BLOCKED"}
            </span>
            <span className={`badge ${breakerLocked ? "down" : "up"}`}>
              CIRCUIT BREAKER: {breakerLocked ? "TRIGGERED (LOCKED)" : "NORMAL"}
            </span>
            {breakerLocked && (
              <button
                className="btn sm warn"
                onClick={handleResetBreaker}
                disabled={resettingRisk}
              >
                {resettingRisk ? "Resetting…" : "Reset Breaker"}
              </button>
            )}
          </div>
        </div>
        <div className="kv-grid six" style={{ marginTop: "12px" }}>
          <div>
            <span>Daily Start Equity</span>
            <b>{money(dailyStart)}</b>
          </div>
          <div>
            <span>Current Equity</span>
            <b>{money(currentEq)}</b>
          </div>
          <div>
            <span>Daily Drawdown</span>
            <b className={dailyDD >= maxDD ? "down" : dailyDD > 1.5 ? "warn" : "up"}>
              {dailyDD.toFixed(2)}%
            </b>
          </div>
          <div>
            <span>Daily Loss Limit</span>
            <b>{maxDD.toFixed(1)}%</b>
          </div>
          <div>
            <span>Current Spread</span>
            <b className={curSpread > maxSpread ? "down" : "up"}>
              {curSpread.toFixed(1)} pts
            </b>
          </div>
          <div>
            <span>Max Permitted Spread</span>
            <b>{maxSpread} pts</b>
          </div>
        </div>
        {breakerLocked && risk?.circuit_breaker_reason && (
          <p className="small down" style={{ marginTop: "10px", marginBottom: 0 }}>
            Circuit Breaker Note: {risk.circuit_breaker_reason}
          </p>
        )}
      </div>

      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-head">
          <h2>News & Macro Event Filter</h2>
          <span className={`badge ${news.paused ? "down" : "up"}`}>
            {news.paused ? `PAUSED (${Math.round((news.seconds_remaining ?? 0) / 60)}m left)` : "NORMAL TRADING"}
          </span>
        </div>
        <div style={{ display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap", marginTop: "8px" }}>
          <p className="muted small" style={{ margin: 0 }}>
            {news.paused
              ? `Trading signals are blocked until ${new Date((news.no_trade_until ?? 0) * 1000).toLocaleTimeString()} (${news.reason}).`
              : "No active news pause. You can pause the EA around high-impact economic releases."}
          </p>
          <div style={{ display: "flex", gap: "8px", marginLeft: "auto" }}>
            {!news.paused ? (
              <>
                <select
                  value={pauseMinutes}
                  onChange={(e) => setPauseMinutes(Number(e.target.value))}
                  style={{ width: "130px" }}
                >
                  <option value={15}>Pause 15 min</option>
                  <option value={30}>Pause 30 min</option>
                  <option value={60}>Pause 1 hour</option>
                  <option value={120}>Pause 2 hours</option>
                </select>
                <button className="btn sm warn" onClick={handlePause}>
                  Activate Pause
                </button>
              </>
            ) : (
              <button className="btn sm primary" onClick={handleResume}>
                Resume Trading Now
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
