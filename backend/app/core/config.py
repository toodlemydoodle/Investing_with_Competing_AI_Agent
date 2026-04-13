from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_ROOT / 'trader.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    app_name: str = 'moomoo AI Agent Arena'
    app_env: str = 'dev'
    app_mode: str = 'paper'
    api_title: str = 'moomoo Agent Arena API'
    api_version: str = '0.1.0'
    cors_origins: list[str] = Field(default_factory=lambda: ['http://localhost:5173'])
    database_url: str = DEFAULT_DATABASE_URL

    broker_backend: str = 'mock'
    quote_provider: str = 'broker'
    broker_connect_timeout_seconds: float = 2.0
    broker_query_timeout_seconds: float = 5.0
    moomoo_host: str = '127.0.0.1'
    moomoo_port: int = 11111
    moomoo_security_firm: str = 'FUTUINC'
    moomoo_market: str = 'US'
    moomoo_trd_env: str = 'SIMULATE'
    moomoo_acc_id: int | None = None
    moomoo_paper_trd_env: str = 'SIMULATE'
    moomoo_paper_acc_id: int | None = None
    moomoo_live_trd_env: str = 'REAL'
    moomoo_live_acc_id: int | None = None
    moomoo_unlock_password: str | None = None

    alpaca_data_api_key: str | None = None
    alpaca_data_secret: str | None = None
    alpaca_data_feed: str = 'iex'
    twelvedata_api_key: str | None = None
    dashboard_admin_token: str | None = None

    agent_autopilot_enabled: bool = False
    agent_autopilot_interval_seconds: int = 300
    agent_max_orders_per_cycle: int = 2
    agent_take_profit_pct: float = 12.0
    agent_stop_loss_pct: float = 8.0

    competition_benchmark_symbol: str = 'US.SPY'

    research_enabled: bool = True
    research_http_timeout_seconds: float = 8.0
    research_http_user_agent: str = 'moomoo-ai-agent-arena/0.1 (contact: local-research@example.com)'
    research_max_symbols_per_agent: int = 8
    research_max_generated_decisions_per_agent: int = 5
    research_news_items_per_symbol: int = 3
    research_filings_per_symbol: int = 3
    research_min_buy_score: float = 6.2
    research_min_hold_score: float = 5.4
    research_general_symbol_limit: int = 24
    research_specialist_symbol_limit: int = 64
    research_general_external_symbol_limit: int = 6
    research_specialist_external_symbol_limit: int = 14
    research_watchlist_limit: int = 3

    risk_bankroll_cap: float = 1000.0
    risk_max_order_notional: float = 150.0
    live_capped_max_order_notional: float = 25.0
    live_capped_agent_slug: str = 'pick-shovel-growth'
    risk_max_open_positions: int = 5
    risk_max_positions_per_theme: int = 2
    risk_daily_loss_limit: float = 75.0

    @field_validator('database_url', mode='before')
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if not raw:
            return DEFAULT_DATABASE_URL
        prefix = 'sqlite:///'
        if not raw.startswith(prefix):
            return raw
        db_path = Path(raw[len(prefix):])
        if db_path.is_absolute():
            return f"sqlite:///{db_path.as_posix()}"
        return f"sqlite:///{(BACKEND_ROOT / db_path).resolve().as_posix()}"

    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            if value.startswith('['):
                return json.loads(value)
            return [item.strip() for item in value.split(',') if item.strip()]
        return value

    @field_validator(
        'moomoo_acc_id',
        'moomoo_paper_acc_id',
        'moomoo_live_acc_id',
        'moomoo_unlock_password',
        'alpaca_data_api_key',
        'alpaca_data_secret',
        'twelvedata_api_key',
        'dashboard_admin_token',
        mode='before',
    )
    @classmethod
    def empty_strings_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
