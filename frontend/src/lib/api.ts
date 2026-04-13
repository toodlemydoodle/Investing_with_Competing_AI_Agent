export type Health = {
  app_name: string;
  env: string;
  mode: string;
  version: string;
  server_time: string;
};

export type BrokerHealth = {
  backend: string;
  status: string;
  message: string;
  is_reachable: boolean;
  is_authenticated: boolean;
  environment: string;
  selected_acc_id: number | null;
  warnings: string[];
  account_summary: Record<string, string | number | boolean | null>;
  checked_at: string;
};

export type BrokerAccount = {
  acc_id: number;
  trd_env: string;
  acc_type: string;
  security_firm: string;
  sim_acc_type: string | null;
  uni_card_num: string | null;
  card_num: string | null;
  is_selected: boolean;
};

export type AgentHistoryPoint = {
  equity: number;
  cash: number;
  return_pct: number;
  recorded_at: string;
};

export type AgentCashPoint = {
  cash: number;
  recorded_at: string;
};

export type AgentHoldingsPoint = {
  holdings: number;
  recorded_at: string;
};

export type Agent = {
  slug: string;
  name: string;
  style: string;
  mandate: string;
  benchmark: string;
  allowed_universe: string;
  starting_capital: number;
  cash_buffer: number;
  survival_floor: number;
  baseline_weight: number;
  min_weight: number;
  max_weight: number;
  target_weight: number;
  allocated_capital: number;
  current_value: number;
  total_return_pct: number;
  performance_score: number;
  survival_score: number;
  reward_multiplier: number;
  competition_window_days: number;
  rolling_gains: number;
  rolling_losses: number;
  rolling_unrealized: number;
  rolling_net_pnl: number;
  is_eligible_for_elimination: boolean;
  elimination_ready_at: string | null;
  benchmark_warmup_ends_at: string | null;
  next_benchmark_check_at: string | null;
  benchmark_check_due: boolean;
  is_cash_only: boolean;
  cash_only_reason: string | null;
  cash_only_at: string | null;
  last_scored_at: string | null;
  is_winner: boolean;
  is_alive: boolean;
  is_enabled: boolean;
  death_round: number | null;
  death_reason: string | null;
  notes: string;
  history: AgentHistoryPoint[];
  cash_history: AgentCashPoint[];
  holdings_history: AgentHoldingsPoint[];
  updated_at: string;
};

export type AgentPosition = {
  agent_slug: string;
  symbol: string;
  quantity: number;
  average_cost: number;
  market_price: number;
  market_value: number;
  realized_pl: number;
  unrealized_pl: number;
  last_trade_at: string | null;
  updated_at: string;
};

export type AgentTrade = {
  id: number;
  agent_slug: string;
  order_id: string | null;
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  notional: number;
  realized_pl: number;
  notes: string;
  created_at: string;
};

export type ResearchNote = {
  id: number;
  agent_slug: string;
  symbol: string;
  source_type: string;
  source_title: string;
  source_url: string | null;
  note_text: string;
  note_score: number;
  published_at: string | null;
  created_at: string;
};

export type BenchmarkPoint = {
  price: number;
  recorded_at: string;
};

export type Settings = {
  app_mode: string;
  admin_controls_protected: boolean;
  is_admin: boolean;
  broker_backend: string;
  quote_provider: string;
  broker_environment: string;
  selected_acc_id: number | null;
  agent_autopilot_enabled: boolean;
  agent_autopilot_interval_seconds: number;
  agent_autopilot_last_cycle_at: string | null;
  agent_autopilot_last_summary: string | null;
  competition_benchmark_symbol: string;
  competition_benchmark_start_price: number | null;
  competition_benchmark_current_price: number | null;
  competition_benchmark_return_pct: number | null;
  competition_benchmark_last_updated_at: string | null;
  competition_benchmark_history: BenchmarkPoint[];
  research_enabled: boolean;
  risk_bankroll_cap: number;
};

export type Position = {
  symbol: string;
  name: string;
  quantity: number;
  can_sell_quantity: number;
  market_price: number;
  cost_price: number;
  market_value: number;
  unrealized_pl: number;
  currency: string;
  updated_at: string;
};

export type BrokerOrder = {
  order_id: string;
  symbol: string;
  agent_slug: string | null;
  side: string;
  order_type: string;
  status: string;
  quantity: number;
  price: number;
  filled_quantity: number;
  average_fill_price: number;
  trading_env: string;
  remark: string | null;
  updated_at: string;
};

export type Decision = {
  symbol: string;
  side: string;
  theme_name: string;
  strategy_slug: string;
  strategy_name: string;
  target_weight: number;
  max_notional: number;
  conviction_score: number;
  rationale: string;
  status: string;
};

export type Company = {
  symbol: string;
  name: string;
  theme_name: string;
  sector: string;
  total_score: number;
  rationale: string;
  is_approved: boolean;
};

export type Alert = {
  severity: string;
  title: string;
  message: string;
  created_at: string;
};

export type DashboardOverview = {
  health: Health;
  broker_health: BrokerHealth;
  accounts: BrokerAccount[];
  agents: Agent[];
  agent_positions: AgentPosition[];
  agent_trades: AgentTrade[];
  research_notes: ResearchNote[];
  positions: Position[];
  orders: BrokerOrder[];
  decisions: Decision[];
  companies: Company[];
  alerts: Alert[];
  settings: Settings;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getOverview(): Promise<DashboardOverview> {
  return request<DashboardOverview>('/dashboard/overview');
}

export async function testBroker(): Promise<DashboardOverview> {
  return request<DashboardOverview>('/broker/test', { method: 'POST' });
}

export async function updateMode(mode: string): Promise<Settings> {
  return request<Settings>('/mode', {
    method: 'POST',
    body: JSON.stringify({ mode }),
  });
}

export async function submitPaperOrder(payload: {
  symbol: string;
  agent_slug?: string | null;
  quantity: number;
  limit_price: number;
  side: string;
  remark?: string;
}): Promise<BrokerOrder> {
  return request<BrokerOrder>('/orders/paper', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function toggleAutopilot(enabled: boolean): Promise<void> {
  await request('/agents/autopilot', {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });
}

export async function runAutopilotCycle(): Promise<{ executed_orders: number; events: string[] }> {
  return request('/agents/cycle', { method: 'POST' });
}

export async function runResearch(): Promise<{ generated_decisions: number; generated_notes: number }> {
  return request('/research/run', { method: 'POST' });
}
