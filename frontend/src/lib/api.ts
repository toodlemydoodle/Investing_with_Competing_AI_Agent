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

export type Agent = {
  slug: string;
  name: string;
  style: string;
  mandate: string;
  benchmark: string;
  baseline_weight: number;
  min_weight: number;
  max_weight: number;
  target_weight: number;
  allocated_capital: number;
  current_value: number;
  total_return_pct: number;
  performance_score: number;
  reward_multiplier: number;
  is_winner: boolean;
  is_enabled: boolean;
  notes: string;
  updated_at: string;
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

export type Settings = {
  app_mode: string;
  broker_backend: string;
  broker_environment: string;
  selected_acc_id: number | null;
  risk_bankroll_cap: number;
  risk_max_order_notional: number;
  risk_max_open_positions: number;
  risk_max_positions_per_theme: number;
  risk_daily_loss_limit: number;
};

export type DashboardOverview = {
  health: Health;
  broker_health: BrokerHealth;
  accounts: BrokerAccount[];
  agents: Agent[];
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


