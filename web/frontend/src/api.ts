import type {
  CloseAllResult,
  DatasetSummary,
  Health,
  LiveStatus,
  ModelInfo,
  Overview,
  Quote,
  TradeDeal,
  TradePosition,
  TradeResult,
  TradeStatus,
  TradeSymbol,
  TrainJob,
} from "./types";

const BASE = "/api";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { cache: "no-store" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${text}`.trim());
  }
  return (await res.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${text}`.trim());
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => get<Health>("/health"),
  overview: () => get<Overview>("/overview"),
  datasets: () => get<DatasetSummary[]>("/datasets"),
  models: () => get<ModelInfo[]>("/models"),
  status: () => get<LiveStatus>("/status"),
  jobs: () => get<TrainJob[]>("/jobs"),
  job: (id: string) => get<TrainJob>(`/jobs/${id}`),
  train: (body: {
    csv: string;
    model: string;
    hidden: string;
    threshold: number;
    cv_splits?: number;
    cv_gap?: number;
  }) => post<TrainJob>("/train", body),
  newsStatus: () => get<{ paused: boolean; no_trade_until?: number; seconds_remaining?: number; reason?: string }>("/news/status"),
  newsPause: (pause_minutes: number, reason: string = "News Event") => post<{ ok: boolean; no_trade_until: number; paused: boolean }>("/news/pause", { pause_minutes, reason }),
  newsResume: () => post<{ ok: boolean; paused: boolean }>("/news/resume", {}),
  activate: (name: string) => post<{ ok: boolean; active: string }>(
    "/models/activate",
    { name },
  ),
  tradeConnect: () => post<TradeStatus>("/trade/connect", {}),
  tradeRestart: () => post<TradeStatus>("/trade/restart", {}),
  tradeStatus: () => get<TradeStatus>("/trade/status"),
  tradeSymbols: () => get<TradeSymbol[]>("/trade/symbols"),
  tradeQuote: (symbol: string) =>
    get<Quote>(`/trade/quote?symbol=${encodeURIComponent(symbol)}`),
  tradePositions: () => get<TradePosition[]>("/trade/positions"),
  tradeHistory: (limit = 20) => get<TradeDeal[]>(`/trade/history?limit=${limit}`),
  tradeOrder: (body: {
    symbol: string;
    side: "buy" | "sell";
    volume: number;
    sl_points: number;
    tp_points: number;
  }) => post<TradeResult>("/trade/order", body),
  tradeClose: (ticket: number, volume?: number) =>
    post<TradeResult>("/trade/close", { ticket, volume }),
  tradeCloseAll: (symbol?: string) =>
    post<CloseAllResult>("/trade/close_all", { symbol }),
  riskStatus: () => get<import("./types").RiskStatus>("/risk/status"),
  resetCircuitBreaker: () => post<{ ok: boolean; circuit_breaker_active: boolean }>("/risk/reset_breaker", {}),
};
