from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class BrokerHealth:
    backend: str
    status: str
    message: str
    is_reachable: bool
    is_authenticated: bool
    environment: str
    selected_acc_id: int | None
    warnings: list[str]
    account_summary: dict[str, float | str | bool | None]
    checked_at: datetime


@dataclass(slots=True)
class BrokerAccountRecord:
    acc_id: int
    trd_env: str
    acc_type: str
    security_firm: str
    sim_acc_type: str | None = None
    uni_card_num: str | None = None
    card_num: str | None = None
    is_selected: bool = False
    raw_payload: dict[str, object] | None = None


@dataclass(slots=True)
class PositionRecord:
    symbol: str
    name: str
    quantity: float
    can_sell_quantity: float
    market_price: float
    cost_price: float
    market_value: float
    unrealized_pl: float
    currency: str = 'USD'
    raw_payload: dict[str, object] | None = None


@dataclass(slots=True)
class BrokerOrderRecord:
    order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    price: float
    filled_quantity: float
    average_fill_price: float
    trading_env: str
    remark: str | None = None
    raw_payload: dict[str, object] | None = None


@dataclass(slots=True)
class QuoteRecord:
    symbol: str
    name: str
    last_price: float
    bid_price: float
    ask_price: float
    prev_close_price: float
    update_time: str | None = None
    raw_payload: dict[str, object] | None = None


@dataclass(slots=True)
class PaperOrderTicket:
    symbol: str
    agent_slug: str | None
    quantity: float
    limit_price: float
    side: str
    remark: str | None = None

    @property
    def sleeve_slug(self) -> str | None:
        return self.agent_slug

    @sleeve_slug.setter
    def sleeve_slug(self, value: str | None) -> None:
        self.agent_slug = value


class BrokerAdapter(ABC):
    def close(self) -> None:
        return None

    @abstractmethod
    def health_check(self) -> BrokerHealth:
        raise NotImplementedError

    @abstractmethod
    def list_accounts(self) -> list[BrokerAccountRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_positions(self) -> list[PositionRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_open_orders(self) -> list[BrokerOrderRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_orders(self) -> list[BrokerOrderRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_quote(self, symbol: str) -> QuoteRecord:
        raise NotImplementedError

    @abstractmethod
    def submit_paper_order(self, ticket: PaperOrderTicket) -> BrokerOrderRecord:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError
