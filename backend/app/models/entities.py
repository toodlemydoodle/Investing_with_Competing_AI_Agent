from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base, TimestampMixin):
    __tablename__ = 'app_settings'

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Theme(Base, TimestampMixin):
    __tablename__ = 'themes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)


class StrategyAgent(Base, TimestampMixin):
    __tablename__ = 'strategy_agents'

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    style: Mapped[str] = mapped_column(String(64), nullable=False)
    mandate: Mapped[str] = mapped_column(Text, nullable=False)
    benchmark: Mapped[str] = mapped_column(String(120), nullable=False)
    allowed_universe: Mapped[str] = mapped_column(String(120), default='US_STOCKS')
    starting_capital: Mapped[float] = mapped_column(Float, default=0)
    cash_buffer: Mapped[float] = mapped_column(Float, default=0)
    survival_floor: Mapped[float] = mapped_column(Float, default=0)
    baseline_weight: Mapped[float] = mapped_column(Float, default=0.5)
    min_weight: Mapped[float] = mapped_column(Float, default=0)
    max_weight: Mapped[float] = mapped_column(Float, default=1.0)
    target_weight: Mapped[float] = mapped_column(Float, default=0.5)
    allocated_capital: Mapped[float] = mapped_column(Float, default=0)
    current_value: Mapped[float] = mapped_column(Float, default=0)
    total_return_pct: Mapped[float] = mapped_column(Float, default=0)
    performance_score: Mapped[float] = mapped_column(Float, default=0)
    survival_score: Mapped[float] = mapped_column(Float, default=0)
    reward_multiplier: Mapped[float] = mapped_column(Float, default=1)
    competition_window_days: Mapped[int] = mapped_column(Integer, default=90)
    rolling_gains: Mapped[float] = mapped_column(Float, default=0)
    rolling_losses: Mapped[float] = mapped_column(Float, default=0)
    rolling_unrealized: Mapped[float] = mapped_column(Float, default=0)
    rolling_net_pnl: Mapped[float] = mapped_column(Float, default=0)
    is_eligible_for_elimination: Mapped[bool] = mapped_column(Boolean, default=False)
    elimination_ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_scored_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    death_round: Mapped[int | None] = mapped_column(Integer)
    death_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default='')


class Company(Base, TimestampMixin):
    __tablename__ = 'companies'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    theme_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sector: Mapped[str] = mapped_column(String(120), nullable=False)
    theme_linkage: Mapped[float] = mapped_column(Float, default=0)
    multi_winner_exposure: Mapped[float] = mapped_column(Float, default=0)
    bottleneck_or_differentiation: Mapped[float] = mapped_column(Float, default=0)
    growth_proof: Mapped[float] = mapped_column(Float, default=0)
    management_proof: Mapped[float] = mapped_column(Float, default=0)
    valuation_sanity: Mapped[float] = mapped_column(Float, default=0)
    total_score: Mapped[float] = mapped_column(Float, default=0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_source: Mapped[str] = mapped_column(String(32), default='baseline')
    approval_positive_streak: Mapped[int] = mapped_column(Integer, default=0)
    approval_negative_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_conviction_score: Mapped[float] = mapped_column(Float, default=0)
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime)


class Decision(Base, TimestampMixin):
    __tablename__ = 'decisions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    theme_name: Mapped[str] = mapped_column(String(120), nullable=False)
    strategy_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_weight: Mapped[float] = mapped_column(Float, nullable=False)
    max_notional: Mapped[float] = mapped_column(Float, nullable=False)
    conviction_score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default='draft')


class ResearchNote(Base, TimestampMixin):
    __tablename__ = 'research_notes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    note_score: Mapped[float] = mapped_column(Float, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_payload: Mapped[str] = mapped_column(Text, default='{}')


class BrokerAccount(Base, TimestampMixin):
    __tablename__ = 'broker_accounts'

    acc_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trd_env: Mapped[str] = mapped_column(String(32), nullable=False)
    acc_type: Mapped[str] = mapped_column(String(64), default='UNKNOWN')
    security_firm: Mapped[str] = mapped_column(String(64), default='UNKNOWN')
    card_num: Mapped[str | None] = mapped_column(String(64))
    uni_card_num: Mapped[str | None] = mapped_column(String(64))
    sim_acc_type: Mapped[str | None] = mapped_column(String(64))
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_payload: Mapped[str] = mapped_column(Text, default='{}')


class Position(Base, TimestampMixin):
    __tablename__ = 'positions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    can_sell_quantity: Mapped[float] = mapped_column(Float, default=0)
    market_price: Mapped[float] = mapped_column(Float, default=0)
    cost_price: Mapped[float] = mapped_column(Float, default=0)
    market_value: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pl: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(16), default='USD')
    raw_payload: Mapped[str] = mapped_column(Text, default='{}')


class BrokerOrder(Base, TimestampMixin):
    __tablename__ = 'broker_orders'

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_slug: Mapped[str | None] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    filled_quantity: Mapped[float] = mapped_column(Float, default=0)
    average_fill_price: Mapped[float] = mapped_column(Float, default=0)
    trading_env: Mapped[str] = mapped_column(String(32), nullable=False)
    remark: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[str] = mapped_column(Text, default='{}')

    @property
    def sleeve_slug(self) -> str | None:
        return self.agent_slug

    @sleeve_slug.setter
    def sleeve_slug(self, value: str | None) -> None:
        self.agent_slug = value


class BrokerFill(Base, TimestampMixin):
    __tablename__ = 'broker_fills'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    raw_payload: Mapped[str] = mapped_column(Text, default='{}')


class AgentTrade(Base, TimestampMixin):
    __tablename__ = 'agent_trades'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    price: Mapped[float] = mapped_column(Float, default=0)
    notional: Mapped[float] = mapped_column(Float, default=0)
    realized_pl: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default='')

    @property
    def sleeve_slug(self) -> str:
        return self.agent_slug

    @sleeve_slug.setter
    def sleeve_slug(self, value: str) -> None:
        self.agent_slug = value


class AgentPosition(Base, TimestampMixin):
    __tablename__ = 'agent_positions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    average_cost: Mapped[float] = mapped_column(Float, default=0)
    market_price: Mapped[float] = mapped_column(Float, default=0)
    market_value: Mapped[float] = mapped_column(Float, default=0)
    realized_pl: Mapped[float] = mapped_column(Float, default=0)
    unrealized_pl: Mapped[float] = mapped_column(Float, default=0)
    last_trade_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def sleeve_slug(self) -> str:
        return self.agent_slug

    @sleeve_slug.setter
    def sleeve_slug(self, value: str) -> None:
        self.agent_slug = value


class Alert(Base, TimestampMixin):
    __tablename__ = 'alerts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


StrategySleeve = StrategyAgent
SleeveTrade = AgentTrade
SleevePosition = AgentPosition
