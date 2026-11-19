export interface Metrics {
  n?: number;
  accuracy?: number;
  log_loss?: number;
  roc_auc?: number | null;
  confident_coverage?: number | null;
  confident_accuracy?: number | null;
  confusion?: number[][];
}

export interface CVFoldScore {
  fold: number;
  n_train: number;
  n_val: number;
  accuracy: number;
  roc_auc: number | null;
}

export interface ModelMeta {
  features?: string[];
  n_features?: number;
  classes?: number[];
  model?: string;
  hidden?: number[] | null;
  threshold?: number;
  rows?: number;
  trained_at?: string;
  source_csv?: string;
  /** Walk-forward CV scores, one entry per fold */
  cv_scores?: CVFoldScore[];
  cv_mean_auc?: number | null;
  cv_std_auc?: number | null;
  onnx_exported?: boolean;
  onnx_note?: string;
  pkl_fallback?: string;
  metrics?: { val?: Metrics; test?: Metrics };
}

export interface DatasetSummary {
  name: string;
  size: number;
  modified: string;
  rows: number;
  features: number;
  up_rate: number;
  first_row: string | null;
  last_row: string | null;
}

export interface ModelInfo {
  name: string;
  file: string;
  active: boolean;
  size: number;
  modified: string;
  meta: ModelMeta | null;
}

export interface RiskStatus {
  daily_start_equity: number;
  current_equity: number;
  daily_drawdown_pct: number;
  max_daily_drawdown_pct: number;
  daily_loss_limit_enabled: boolean;
  max_spread_points: number;
  current_spread_points: number;
  circuit_breaker_active: boolean;
  circuit_breaker_reason: string;
  trading_allowed: boolean;
}

export interface LiveStatus {
  available: boolean;
  error?: string;
  updated?: string;
  file_mtime?: string;
  symbol?: string;
  period?: string;
  model?: string;
  threshold?: number;
  prob_up?: number;
  signal?: string;
  bar_time?: string;
  close?: number;
  position?: string;
  lots?: number;
  balance?: number;
  equity?: number;
  margin_free?: number;
  age_seconds?: number;
  fresh?: boolean;
  spread_pts?: number;
  max_spread_pts?: number;
  circuit_breaker?: boolean;
  daily_drawdown_pct?: number;
  daily_start_equity?: number;
}

export interface Checklist {
  exported: boolean;
  trained: boolean;
  live: boolean;
}

export interface Overview {
  datasets: number;
  models: number;
  latest_dataset: DatasetSummary | null;
  active_model: ModelInfo | null;
  status: LiveStatus;
  checklist: Checklist;
}

export interface TrainJob {
  id: string;
  status: "running" | "succeeded" | "failed";
  created: string;
  finished: string | null;
  exit_code: number | null;
  csv: string;
  model: string;
  run: string | null;
  command: string;
  meta?: ModelMeta | null;
  log_lines?: number;
  log?: string[];
}

export interface Health {
  ok: boolean;
  root: string;
  models_dir: string;
  python: string;
  executable: string;
  trainer: boolean;
}

export interface HistoryPoint {
  t: string;
  p: number;
}

export interface TradeStatus {
  connected: boolean;
  trade_allowed: boolean;
  terminal_allowed?: boolean;
  account_allowed?: boolean;
  error?: string;
  login?: number;
  name?: string;
  server?: string;
  company?: string;
  currency?: string;
  mode?: string;
  leverage?: number;
  balance?: number;
  equity?: number;
  margin?: number;
  margin_free?: number;
  margin_level?: number;
  profit?: number;
  build?: number;
  terminal_path?: string;
  data_dir?: string;
  server_time?: number;
  server_time_str?: string;
  server_offset_sec?: number;
}

export interface TradeSymbol {
  name: string;
  description: string;
  digits: number;
  point: number;
  bid: number | null;
  ask: number | null;
  spread_points: number | null;
  volume_min: number;
  volume_max: number;
  volume_step: number;
  stops_level: number;
  trade_mode: number;
  tradable: boolean;
  visible: boolean;
}

export type Quote = Partial<TradeSymbol> & {
  ok: boolean;
  error?: string;
  time?: string;
};

export interface TradePosition {
  ticket: number;
  symbol: string;
  side: "buy" | "sell";
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  swap: number;
  magic: number;
  comment: string;
  time: string;
}

export interface TradeResult {
  ok: boolean;
  retcode?: number;
  description?: string;
  error?: string;
  order?: number;
  deal?: number;
  price?: number;
  volume?: number;
  comment?: string;
  symbol?: string;
  side?: "buy" | "sell";
  ticket?: number;
  note?: string | null;
  requested_volume?: number;
  sl?: number;
  tp?: number;
  partial?: boolean;
}

export interface TradeDeal {
  ticket: number;
  order: number;
  position: number;
  symbol: string;
  side: "buy" | "sell";
  entry: string;
  volume: number;
  price: number;
  profit: number;
  commission: number;
  swap: number;
  fee: number;
  comment: string;
  magic: number;
  time: string;
}

export interface CloseAllResult {
  ok: boolean;
  count: number;
  closed: { ticket: number; symbol: string; volume: number; result: TradeResult }[];
  failed: { ticket: number; symbol: string; volume: number; result: TradeResult }[];
  error?: string;
}
