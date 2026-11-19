import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  CloseAllResult,
  Quote,
  TradeDeal,
  TradePosition,
  TradeStatus,
  TradeSymbol,
} from "../types";
import { fixed, money, shortDate } from "../format";

type Tone = "ok" | "error" | "info";

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function px(v: number | null | undefined, digits: number): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function signedMoney(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = money(Math.abs(v));
  return v < 0 ? `-${s}` : `+${s}`;
}

export function TradeView() {
  const [status, setStatus] = useState<TradeStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [symbols, setSymbols] = useState<TradeSymbol[]>([]);
  const [symbol, setSymbol] = useState("EURUSD");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [positions, setPositions] = useState<TradePosition[]>([]);
  const [deals, setDeals] = useState<TradeDeal[]>([]);
  const [volume, setVolume] = useState("0.01");
  const [sl, setSl] = useState("0");
  const [tp, setTp] = useState("0");
  const [riskPct, setRiskPct] = useState("0");
  const [maxSpread, setMaxSpread] = useState("30");
  const [arm, setArm] = useState<"buy" | "sell" | null>(null);
  const [armAll, setArmAll] = useState(false);
  const [armRestart, setArmRestart] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: Tone; text: string } | null>(null);

  const armTimer = useRef<number | null>(null);
  const allTimer = useRef<number | null>(null);
  const restartTimer = useRef<number | null>(null);

  const connected = !!status?.connected;
  const tradeReady = !!status?.trade_allowed;
  const current = symbols.find((s) => s.name === symbol);
  const digits = quote?.digits ?? current?.digits ?? 5;
  const step = quote?.volume_step ?? current?.volume_step ?? 0.01;
  const vmin = quote?.volume_min ?? current?.volume_min ?? 0.01;
  const stops = quote?.stops_level ?? current?.stops_level ?? 0;
  const spread = quote?.spread_points ?? current?.spread_points ?? null;
  const canTrade = connected && tradeReady && quote?.tradable !== false;

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.tradeStatus());
    } catch (e) {
      setStatus({ connected: false, trade_allowed: false, error: errText(e) });
    }
  }, []);

  const refreshPositions = useCallback(async () => {
    try {
      setPositions(await api.tradePositions());
    } catch {
      /* keep previous snapshot */
    }
  }, []);

  const refreshDeals = useCallback(async () => {
    try {
      setDeals(await api.tradeHistory(12));
    } catch {
      /* keep previous snapshot */
    }
  }, []);

  const refreshQuote = useCallback(async (sym: string) => {
    try {
      setQuote(await api.tradeQuote(sym));
    } catch {
      setQuote(null);
    }
  }, []);

  const loadSymbols = useCallback(async () => {
    try {
      const list = await api.tradeSymbols();
      setSymbols(list);
      return list;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      setStarting(true);
      try {
        const s = await api.tradeConnect();
        if (!alive) return;
        setStatus(s);
        if (s.connected) {
          const list = await loadSymbols();
          if (alive && list.length && !list.some((x) => x.name === symbol)) {
            setSymbol(list[0].name);
          }
          if (alive) {
            await Promise.all([refreshPositions(), refreshDeals()]);
          }
        } else if (s.error) {
          setMsg({ tone: "error", text: s.error });
        }
      } catch (e) {
        if (alive) {
          setStatus({ connected: false, trade_allowed: false, error: errText(e) });
          setMsg({ tone: "error", text: `MT5 connect failed: ${errText(e)}` });
        }
      } finally {
        if (alive) setStarting(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!connected) return;
    void refreshPositions();
    void refreshDeals();
    const pos = window.setInterval(() => void refreshPositions(), 2000);
    const dealsId = window.setInterval(() => void refreshDeals(), 10000);
    const stat = window.setInterval(() => void refreshStatus(), 5000);
    return () => {
      window.clearInterval(pos);
      window.clearInterval(dealsId);
      window.clearInterval(stat);
    };
  }, [connected, refreshPositions, refreshDeals, refreshStatus]);

  useEffect(() => {
    if (!connected) return;
    void refreshQuote(symbol);
    const id = window.setInterval(() => void refreshQuote(symbol), 1500);
    return () => window.clearInterval(id);
  }, [connected, symbol, refreshQuote]);

  useEffect(() => () => {
    if (armTimer.current) window.clearTimeout(armTimer.current);
    if (allTimer.current) window.clearTimeout(allTimer.current);
    if (restartTimer.current) window.clearTimeout(restartTimer.current);
  }, []);

  function armButton(side: "buy" | "sell") {
    setArm(side);
    if (armTimer.current) window.clearTimeout(armTimer.current);
    armTimer.current = window.setTimeout(() => setArm(null), 5000);
  }

  function armCloseAll() {
    setArmAll(true);
    if (allTimer.current) window.clearTimeout(allTimer.current);
    allTimer.current = window.setTimeout(() => setArmAll(false), 5000);
  }

  function armRestartButton() {
    setArmRestart(true);
    if (restartTimer.current) window.clearTimeout(restartTimer.current);
    restartTimer.current = window.setTimeout(() => setArmRestart(false), 6000);
  }

  async function connect() {
    setStarting(true);
    setMsg({ tone: "info", text: "Connecting to MetaTrader 5…" });
    try {
      const s = await api.tradeConnect();
      setStatus(s);
      if (s.connected) {
        await loadSymbols();
        await Promise.all([refreshPositions(), refreshDeals(), refreshQuote(symbol)]);
        setMsg(s.trade_allowed
          ? { tone: "ok", text: `Connected to ${s.login} (${s.server})` }
          : { tone: "error", text: s.error ?? "Connected, but AutoTrading is disabled" });
      } else {
        setMsg({ tone: "error", text: s.error ?? "Could not connect to MT5" });
      }
    } catch (e) {
      setMsg({ tone: "error", text: `Connect failed: ${errText(e)}` });
    } finally {
      setStarting(false);
    }
  }

  async function restart() {
    if (!armRestart) {
      armRestartButton();
      setMsg({ tone: "info", text: "Click again to restart MT5 with AutoTrading enabled" });
      return;
    }
    setArmRestart(false);
    setBusy("restart");
    setMsg({ tone: "info", text: "Restarting MetaTrader 5…" });
    try {
      const s = await api.tradeRestart();
      setStatus(s);
      await loadSymbols();
      await Promise.all([refreshPositions(), refreshDeals(), refreshQuote(symbol)]);
      setMsg(s.trade_allowed
        ? { tone: "ok", text: "MT5 restarted with AutoTrading enabled" }
        : { tone: "error", text: s.error ?? "AutoTrading is still disabled" });
    } catch (e) {
      setMsg({ tone: "error", text: `Restart failed: ${errText(e)}` });
    } finally {
      setBusy(null);
    }
  }

  async function submit(side: "buy" | "sell") {
    if (!canTrade || busy) return;
    const vol = Number(volume);
    if (!Number.isFinite(vol) || vol <= 0) {
      setMsg({ tone: "error", text: "Enter a valid volume" });
      return;
    }
    if (arm !== side) {
      armButton(side);
      setMsg({ tone: "info", text: `Click ${side.toUpperCase()} again to confirm (5s)` });
      return;
    }
    setArm(null);
    setBusy(side);
    try {
      const rPct = Number(riskPct);
      const mSpread = Number(maxSpread);
      const res = await api.tradeOrder({
        symbol,
        side,
        volume: vol,
        sl_points: Math.max(0, Math.round(Number(sl) || 0)),
        tp_points: Math.max(0, Math.round(Number(tp) || 0)),
        risk_percent: rPct > 0 ? rPct : undefined,
        max_spread_pts: mSpread > 0 ? mSpread : 30,
      });
      if (res.ok) {
        setMsg({
          tone: "ok",
          text: `${side.toUpperCase()} ${fixed(res.volume ?? vol, 2)} ${symbol} @ ${px(res.price, digits)} · #${res.order ?? res.ticket ?? "—"}`,
        });
        await Promise.all([refreshPositions(), refreshStatus(), refreshDeals()]);
      } else {
        setMsg({
          tone: "error",
          text: `${res.description ?? res.error ?? "Order rejected"}${res.retcode ? ` (retcode ${res.retcode})` : ""}`,
        });
      }
    } catch (e) {
      setMsg({ tone: "error", text: `Order failed: ${errText(e)}` });
    } finally {
      setBusy(null);
    }
  }

  async function closeOne(ticket: number) {
    if (busy) return;
    setBusy(`close-${ticket}`);
    try {
      const res = await api.tradeClose(ticket);
      setMsg(res.ok
        ? { tone: "ok", text: `Closed position #${ticket}${res.price ? ` @ ${px(res.price, digits)}` : ""}` }
        : { tone: "error", text: `${res.description ?? res.error ?? "Close failed"}` });
      await Promise.all([refreshPositions(), refreshStatus(), refreshDeals()]);
    } catch (e) {
      setMsg({ tone: "error", text: `Close failed: ${errText(e)}` });
    } finally {
      setBusy(null);
    }
  }

  async function closeAll() {
    if (!positions.length || busy) return;
    if (!armAll) {
      armCloseAll();
      setMsg({ tone: "info", text: `Click again to close ${positions.length} position(s)` });
      return;
    }
    setArmAll(false);
    setBusy("close-all");
    try {
      const res: CloseAllResult = await api.tradeCloseAll();
      setMsg(res.ok
        ? { tone: "ok", text: `Closed ${res.count} position(s)` }
        : { tone: "error", text: `Closed ${res.count}, failed ${res.failed.length}` });
      await Promise.all([refreshPositions(), refreshStatus(), refreshDeals()]);
    } catch (e) {
      setMsg({ tone: "error", text: `Close all failed: ${errText(e)}` });
    } finally {
      setBusy(null);
    }
  }

  const totalProfit = positions.reduce((sum, p) => sum + p.profit, 0);

  return (
    <>
      <div className="grid trade-grid">
        <div className="card">
          <div className="card-head">
            <div>
              <h2>Market order</h2>
              <p className="muted small">Direct execution through the MT5 terminal · demo</p>
            </div>
            <span className={`badge ${status?.mode === "REAL" ? "down" : status?.mode === "DEMO" ? "accent" : ""}`}>
              {starting ? "starting…" : status?.mode ?? "offline"}
            </span>
          </div>

          <div className="trade-form">
            <label>
              Symbol
              <select
                value={symbol}
                onChange={(e) => {
                  setSymbol(e.target.value);
                  setArm(null);
                }}
              >
                {symbols.length === 0 && <option value={symbol}>{symbol}</option>}
                {symbols.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name} · {s.description}{s.tradable ? "" : " (close only)"}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="quote-board">
            <div className="quote-side sell">
              <span>SELL · bid</span>
              <b className="down">{px(quote?.bid, digits)}</b>
              <small>{quote?.ok === false ? quote.error : quote?.description ?? "—"}</small>
            </div>
            <div className="quote-mid">
              <span>spread</span>
              <b>{spread === null ? "—" : fixed(spread, 1)}</b>
              <small>points</small>
            </div>
            <div className="quote-side buy">
              <span>BUY · ask</span>
              <b className="up">{px(quote?.ask, digits)}</b>
              <small>{quote?.time ? quote.time.replace("T", " ") : "—"}</small>
            </div>
          </div>

          <div className="trade-inputs" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))" }}>
            <label>
              Volume {Number(riskPct) > 0 ? "(override)" : ""}
              <input
                type="number"
                min={vmin}
                step={step}
                value={volume}
                onChange={(e) => {
                  setVolume(e.target.value);
                  setArm(null);
                }}
              />
            </label>
            <label>
              Stop loss (pts)
              <input
                type="number"
                min={0}
                step={10}
                value={sl}
                onChange={(e) => {
                  setSl(e.target.value);
                  setArm(null);
                }}
              />
            </label>
            <label>
              Take profit (pts)
              <input
                type="number"
                min={0}
                step={10}
                value={tp}
                onChange={(e) => {
                  setTp(e.target.value);
                  setArm(null);
                }}
              />
            </label>
            <label>
              Risk % (auto-size)
              <input
                type="number"
                min={0}
                max={5}
                step={0.5}
                value={riskPct}
                placeholder="0 = manual"
                onChange={(e) => {
                  setRiskPct(e.target.value);
                  setArm(null);
                }}
              />
            </label>
            <label>
              Max spread (pts)
              <input
                type="number"
                min={5}
                max={200}
                step={5}
                value={maxSpread}
                onChange={(e) => {
                  setMaxSpread(e.target.value);
                  setArm(null);
                }}
              />
            </label>
          </div>

          <div className="trade-actions">
            <button
              className={`btn sell ${arm === "sell" ? "confirm" : ""}`}
              disabled={!canTrade || busy !== null}
              onClick={() => void submit("sell")}
            >
              {busy === "sell" ? "Sending…" : arm === "sell" ? `Confirm SELL ${volume}` : "Sell"}
            </button>
            <button
              className={`btn buy ${arm === "buy" ? "confirm" : ""}`}
              disabled={!canTrade || busy !== null}
              onClick={() => void submit("buy")}
            >
              {busy === "buy" ? "Sending…" : arm === "buy" ? `Confirm BUY ${volume}` : "Buy"}
            </button>
          </div>

          <p className="muted tiny note">
            min {vmin} · step {step} · stops ≥ {stops} pts · click twice to confirm.
            {!connected && " MT5 is not connected."}
            {connected && !tradeReady && " AutoTrading is disabled."}
          </p>

          {msg && <div className={`trade-msg ${msg.tone}`}>{msg.text}</div>}
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Account</h2>
            <button className="btn ghost sm" onClick={() => void connect()} disabled={starting || busy !== null}>
              {starting ? "Connecting…" : "Reconnect"}
            </button>
          </div>

          {!connected ? (
            <div className="empty">
              <p>{starting ? "Starting MetaTrader 5…" : "MetaTrader 5 is not connected."}</p>
              <p className="muted small">{status?.error ?? "The dashboard can start the terminal for you."}</p>
              <button className="btn primary" onClick={() => void connect()} disabled={starting}>
                {starting ? "Starting…" : "Connect MT5"}
              </button>
            </div>
          ) : (
            <>
              <div className="kv-grid six trade-account">
                <div><span>Balance</span><b>{money(status?.balance)}</b></div>
                <div><span>Equity</span><b>{money(status?.equity)}</b></div>
                <div><span>Free margin</span><b>{money(status?.margin_free)}</b></div>
                <div><span>Margin level</span><b>{status?.margin_level ? `${fixed(status.margin_level, 1)}%` : "—"}</b></div>
                <div><span>Open P/L</span><b className={totalProfit >= 0 ? "up" : "down"}>{signedMoney(totalProfit)}</b></div>
                <div><span>Leverage</span><b>1:{status?.leverage ?? "—"}</b></div>
              </div>
              <div className="account-foot">
                <span className="mono">#{status?.login} · {status?.server}</span>
                <span className={`badge ${tradeReady ? "up" : "down"}`}>
                  {tradeReady ? "AutoTrading on" : "AutoTrading off"}
                </span>
              </div>
              {!tradeReady && (
                <div className="banner warn">
                  MT5 is running with AutoTrading disabled, so orders are rejected.
                  <button className="btn ghost sm ml" onClick={() => void restart()} disabled={busy !== null}>
                    {armRestart ? "Confirm restart" : "Restart MT5"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Open positions</h2>
            <p className="muted small">
              {positions.length} position(s) · floating P/L {signedMoney(totalProfit)}
            </p>
          </div>
          <button
            className="btn ghost sm"
            onClick={() => void closeAll()}
            disabled={!positions.length || busy !== null}
          >
            {armAll ? `Confirm close ${positions.length}` : "Close all"}
          </button>
        </div>
        {positions.length === 0 ? (
          <div className="empty">No open positions.</div>
        ) : (
          <div className="table-wrap">
            <table className="trade-table">
              <thead>
                <tr>
                  <th>Ticket</th><th>Symbol</th><th>Side</th><th className="num">Volume</th>
                  <th className="num">Open</th><th className="num">Current</th>
                  <th className="num">SL</th><th className="num">TP</th>
                  <th className="num">P/L</th><th />
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.ticket}>
                    <td className="mono">{p.ticket}</td>
                    <td>{p.symbol}</td>
                    <td><span className={`badge ${p.side === "buy" ? "up" : "down"}`}>{p.side}</span></td>
                    <td className="num">{fixed(p.volume, 2)}</td>
                    <td className="num">{px(p.price_open, digits)}</td>
                    <td className="num">{px(p.price_current, digits)}</td>
                    <td className="num">{p.sl ? px(p.sl, digits) : "—"}</td>
                    <td className="num">{p.tp ? px(p.tp, digits) : "—"}</td>
                    <td className={`num ${p.profit >= 0 ? "up" : "down"}`}>{signedMoney(p.profit)}</td>
                    <td className="right">
                      <button
                        className="btn ghost sm"
                        onClick={() => void closeOne(p.ticket)}
                        disabled={busy !== null}
                      >
                        {busy === `close-${p.ticket}` ? "…" : "Close"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Recent deals</h2>
          <span className="muted small">last {deals.length}</span>
        </div>
        {deals.length === 0 ? (
          <div className="empty">No deals in the last 7 days.</div>
        ) : (
          <div className="table-wrap">
            <table className="trade-table">
              <thead>
                <tr>
                  <th>Time</th><th>Symbol</th><th>Entry</th><th>Side</th>
                  <th className="num">Volume</th><th className="num">Price</th>
                  <th className="num">Profit</th><th>Comment</th>
                </tr>
              </thead>
              <tbody>
                {deals.map((d) => (
                  <tr key={d.ticket}>
                    <td className="mono small">{shortDate(d.time)}</td>
                    <td>{d.symbol}</td>
                    <td><span className={`badge ${d.entry === "out" ? "accent" : ""}`}>{d.entry}</span></td>
                    <td>{d.side}</td>
                    <td className="num">{fixed(d.volume, 2)}</td>
                    <td className="num">{px(d.price, digits)}</td>
                    <td className={`num ${d.profit > 0 ? "up" : d.profit < 0 ? "down" : "muted"}`}>
                      {d.profit ? signedMoney(d.profit) : "—"}
                    </td>
                    <td className="muted small">{d.comment || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
