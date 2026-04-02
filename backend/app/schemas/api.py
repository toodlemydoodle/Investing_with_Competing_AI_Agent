from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import Field


class HealthResponse(BaseModel):
    app_name: str
    env: str
    mode: str
    version: str
    server_time: datetime


class BrokerHealthResponse(BaseModel):
    backend: str
    status: str
    message: str
    is_reachable: bool
    is_authenticated: bool
    environment: str
    selected_acc_id: int | None = None
    warnings: list[str] = Field(default_factory=list)
    account_summary: dict[str, float | str | bool | None] = Field(default_factory=dict)
    checked_at: datetime


class BrokerAccountResponse(BaseModel):
    acc_id: int
    trd_env: str
    acc_type: str
    security_firm: str
    sim_acc_type: str | None = None
    uni_card_num: str | None = None
    card_num: str | None = None
    is_selected: bool = False


class QuoteResponse(BaseModel):
    symbol: str
    name: str
    last_price: float
    bid_price: float
    ask_price: float
    prev_close_price: float
    update_time: str | None = None


class AgentResponse(BaseModel):
    slug: str
    name: str
    style: str
    mandate: str
    benchmark: str
    allowed_universe: str
    starting_capital: float
    cash_buffer: float
    survival_floor: float
    baseline_weight: float
    min_weight: float
    max_weight: float
    target_weight: float
    allocated_capital: float
    current_value: float
    total_return_pct: float
    performance_score: float
    survival_score: float
    reward_multiplier: float
    competition_window_days: int
    rolling_gains: float
    rolling_losses: float
    rolling_unrealized: float
    rolling_net_pnl: float
    is_eligible_for_elimination: bool
    elimination_ready_at: datetime | None = None
    last_scored_at: datetime | None = None
    is_winner: bool
    is_alive: bool
    is_enabled: bool
    death_round: int | None = None
    death_reason: str | None = None
    notes: str
    updated_at: datetime


class AgentPositionResponse(BaseModel):
    agent_slug: str
    symbol: str
    quantity: float
    average_cost: float
    market_price: float
    market_value: float
    realized_pl: float
    unrealized_pl: float
    last_trade_at: datetime | None = None
    updated_at: datetime


class AgentTradeResponse(BaseModel):
    id: int
    agent_slug: str
    order_id: str | None = None
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    realized_pl: float
    notes: str
    created_at: datetime


class ResearchNoteResponse(BaseModel):
    id: int
    agent_slug: str
    symbol: str
    source_type: str
    source_title: str
    source_url: str | None = None
    note_text: str
    note_score: float
    published_at: datetime | None = None
    created_at: datetime


class PositionResponse(BaseModel):
    symbol: str
    name: str
    quantity: float
    can_sell_quantity: float
    market_price: float
    cost_price: float
    market_value: float
    unrealized_pl: float
    currency: str
    updated_at: datetime


class BrokerOrderResponse(BaseModel):
    order_id: str
    symbol: str
    agent_slug: str | None
    side: str
    order_type: str
    status: str
    quantity: float
    price: float
    filled_quantity: float
    average_fill_price: float
    trading_env: str
    remark: str | None
    updated_at: datetime


class DecisionResponse(BaseModel):
    symbol: str
    side: str
    theme_name: str
    strategy_slug: str
    strategy_name: str
    target_weight: float
    max_notional: float
    conviction_score: float
    rationale: str
    status: str


class CompanyResponse(BaseModel):
    symbol: str
    name: str
    theme_name: str
    sector: str
    total_score: float
    rationale: str
    is_approved: bool


class AlertResponse(BaseModel):
    severity: str
    title: str
    message: str
    created_at: datetime


class BenchmarkPointResponse(BaseModel):
    price: float
    recorded_at: datetime


class SettingsResponse(BaseModel):
    app_mode: str
    broker_backend: str
    quote_provider: str
    broker_environment: str
    selected_acc_id: int | None
    agent_autopilot_enabled: bool
    agent_autopilot_interval_seconds: int
    agent_max_orders_per_cycle: int
    agent_take_profit_pct: float
    agent_stop_loss_pct: float
    agent_autopilot_last_cycle_at: datetime | None = None
    agent_autopilot_last_summary: str | None = None
    competition_benchmark_symbol: str
    competition_benchmark_start_price: float | None = None
    competition_benchmark_current_price: float | None = None
    competition_benchmark_return_pct: float | None = None
    competition_benchmark_last_updated_at: datetime | None = None
    competition_benchmark_history: list[BenchmarkPointResponse] = Field(default_factory=list)
    research_enabled: bool
    research_max_symbols_per_agent: int
    research_max_generated_decisions_per_agent: int
    research_min_buy_score: float
    research_min_hold_score: float
    risk_bankroll_cap: float
    risk_max_order_notional: float
    risk_max_open_positions: int
    risk_max_positions_per_theme: int
    risk_daily_loss_limit: float


class ModeUpdateRequest(BaseModel):
    mode: str


class AutopilotToggleRequest(BaseModel):
    enabled: bool


class AutopilotStatusResponse(BaseModel):
    enabled: bool
    interval_seconds: int
    max_orders_per_cycle: int
    take_profit_pct: float
    stop_loss_pct: float
    last_cycle_at: datetime | None = None
    last_summary: str | None = None


class AutopilotCycleResponse(BaseModel):
    enabled: bool
    executed_orders: int
    events: list[str]
    last_cycle_at: datetime


class ResearchRefreshResponse(BaseModel):
    generated_agents: int
    generated_decisions: int
    generated_notes: int
    refreshed_at: datetime


class PaperOrderRequest(BaseModel):
    symbol: str
    agent_slug: str = Field(validation_alias=AliasChoices('agent_slug', 'sleeve_slug'))
    quantity: float = Field(gt=0)
    limit_price: float = Field(gt=0)
    side: str = 'BUY'
    remark: str | None = None


class DashboardOverviewResponse(BaseModel):
    health: HealthResponse
    broker_health: BrokerHealthResponse
    accounts: list[BrokerAccountResponse]
    agents: list[AgentResponse]
    agent_positions: list[AgentPositionResponse]
    agent_trades: list[AgentTradeResponse]
    research_notes: list[ResearchNoteResponse]
    positions: list[PositionResponse]
    orders: list[BrokerOrderResponse]
    decisions: list[DecisionResponse]
    companies: list[CompanyResponse]
    alerts: list[AlertResponse]
    settings: SettingsResponse


SleeveResponse = AgentResponse
SleevePositionResponse = AgentPositionResponse
SleeveTradeResponse = AgentTradeResponse
