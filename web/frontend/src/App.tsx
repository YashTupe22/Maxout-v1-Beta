import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Health, HistoryPoint, LiveStatus, Overview, TradeStatus } from "./types";
import { money } from "./format";
import { OverviewView } from "./views/OverviewView";
import { TradeView } from "./views/TradeView";
import { DataView } from "./views/DataView";
import { TrainView } from "./views/TrainView";
import { ModelsView } from "./views/ModelsView";
import { LiveView } from "./views/LiveView";

type Tab = "overview" | "trade" | "data" | "train" | "models" | "live";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "trade", label: "Trade" },
  { id: "data", label: "Datasets" },
  { id: "train", label: "Train" },
  { id: "models", label: "Models" },
  { id: "live", label: "Live EA" },
];

const TITLES: Record<Tab, string> = {
  overview: "Overview",
  trade: "Trade desk",
  data: "Datasets",
  train: "Training",
  models: "Models",
  live: "Live EA",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [status, setStatus] = useState<LiveStatus>({ available: false });
  const [health, setHealth] = useState<Health | null>(null);
  const [account, setAccount] = useState<TradeStatus | null>(null);
  const [clock, setClock] = useState<Date>(new Date());
  const serverTimeRef = useRef<{ serverEpoch: number; localFetchMs: number } | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [pendingCsv, setPendingCsv] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const load = useCallback(async () => {
    try {
      const [h, o, s, acc] = await Promise.all([
        api.health(),
        api.overview(),
        api.status(),
        api.tradeStatus().catch(() => null),
      ]);
      setHealth(h);
      setOverview(o);
      setStatus(s);
      if (acc) {
        setAccount(acc);
        if (typeof acc.server_time === "number" && acc.server_time > 0) {
          serverTimeRef.current = {
            serverEpoch: acc.server_time,
            localFetchMs: Date.now(),
          };
        }
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 2500);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const bar = status.bar_time;
    const p = status.prob_up;
    if (!status.available || !bar || typeof p !== "number") return;
    setHistory((prev) => {
      if (prev.length > 0 && prev[prev.length - 1].t === bar) return prev;
      return [...prev.slice(-179), { t: bar, p }];
    });
  }, [status]);

  const activeModel = overview?.active_model;
  const eaLive = status.available && status.fresh;

  const getTerminalTime = () => {
    if (serverTimeRef.current) {
      const elapsedSec = Math.floor((Date.now() - serverTimeRef.current.localFetchMs) / 1000);
      const currentServerSec = serverTimeRef.current.serverEpoch + elapsedSec;
      const d = new Date(currentServerSec * 1000);
      return {
        timeStr: d.toISOString().substring(11, 19),
        dateStr: d.toLocaleDateString("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" }),
        isServer: true,
      };
    }
    return {
      timeStr: clock.toLocaleTimeString("en-GB", { hour12: false }),
      dateStr: clock.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }),
      isServer: false,
    };
  };

  const term = getTerminalTime();

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">M</div>
          <div>
            <div className="brand-name">MAXOUT</div>
            <div className="brand-sub">AI Trading Console</div>
          </div>
        </div>

        <nav>
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "active" : undefined}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="side-foot">
          {/* MT5 Terminal Clock Card */}
          <div className="side-clock-card">
            <div className="side-clock-header">
              <span className="side-clock-time">
                {term.timeStr}
              </span>
              <span className="side-clock-tag">
                {term.isServer ? "MT5 SERVER" : "LOCAL"}
              </span>
            </div>
            <div className="side-clock-sub">
              <span>{term.dateStr}</span>
              <span className="side-clock-local">
                Local: {clock.toLocaleTimeString("en-GB", { hour12: false })}
              </span>
            </div>
          </div>

          {/* Account Details Card */}
          <div className="side-acc-card">
            <div className="side-acc-header">
              <div className="side-acc-title">
                <span className={`dot ${account?.connected ? "ok" : "warn"}`} style={{ margin: 0 }} />
                <span className="side-acc-login">
                  {account?.login ? `#${account.login}` : "MT5 Terminal"}
                </span>
              </div>
              <span className="side-acc-tag">
                {account?.mode ?? "DEMO"}
              </span>
            </div>

            <div className="side-acc-server" title={account?.server ?? "SkyrissSecurities-Trade"}>
              {account?.server ?? "SkyrissSecurities-Trade"}
              {account?.name ? ` · ${account.name}` : ""}
            </div>

            <div className="side-acc-metrics">
              <div>
                <span>Balance</span>
                <b>{money(account?.balance ?? status.balance ?? 0)}</b>
              </div>
              <div>
                <span>Equity</span>
                <b>{money(account?.equity ?? status.equity ?? 0)}</b>
              </div>
              <div>
                <span>Free Margin</span>
                <b>{money(account?.margin_free ?? status.margin_free ?? 0)}</b>
              </div>
              <div>
                <span>Leverage</span>
                <b>{account?.leverage ? `1:${account.leverage}` : "1:100"}</b>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0 2px" }}>
            <div>
              <span className={health?.ok ? "dot ok" : "dot warn"} />
              {health?.ok ? "API online" : "API offline"}
            </div>
            <div className="tiny" style={{ opacity: 0.75 }}>
              {account?.trade_allowed ? "AutoTrading ON" : "AutoTrading OFF"}
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">workspace</div>
            <h1>{TITLES[tab]}</h1>
          </div>
          <div className="top-meta">
            <span className="chip mono">{activeModel?.file ?? "no active model"}</span>
            <span className="chip">
              <span className={eaLive ? "dot ok" : "dot warn"} />
              {status.available ? (status.fresh ? "EA live" : "EA stale") : "EA offline"}
            </span>
            <span className="chip mono">
              {status.symbol ?? "—"} {status.period?.replace("PERIOD_", "") ?? ""}
            </span>
            <span className="chip">
              <span className={health?.ok ? "dot ok" : "dot warn"} />
              {error ? "disconnected" : "connected"}
            </span>
          </div>
        </header>

        {error && (
          <div className="banner error">
            Backend unreachable — is <code>uvicorn</code> running on port 8787? {error}
          </div>
        )}

        <section className="content" key={tab}>
          {tab === "overview" && (
            <OverviewView
              overview={overview}
              history={history}
              go={(next) => setTab(next)}
            />
          )}
          {tab === "trade" && <TradeView />}
          {tab === "data" && (
            <DataView
              onTrain={(name) => {
                setPendingCsv(name);
                setTab("train");
              }}
            />
          )}
          {tab === "train" && (
            <TrainView
              initialCsv={pendingCsv}
              onFinished={() => {
                setPendingCsv(null);
                void load();
              }}
            />
          )}
          {tab === "models" && <ModelsView onChanged={() => void load()} />}
          {tab === "live" && <LiveView status={status} history={history} />}
        </section>
      </main>
    </div>
  );
}
