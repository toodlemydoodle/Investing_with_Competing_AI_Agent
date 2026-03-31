from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from app.broker.base import BrokerAccountRecord
from app.broker.base import BrokerAdapter
from app.broker.base import BrokerHealth
from app.broker.base import BrokerOrderRecord
from app.broker.base import PaperOrderTicket
from app.broker.base import PositionRecord
from app.broker.base import QuoteRecord
from app.core.config import Settings


MOCK_QUOTES = {
    'US.NVDA': ('NVIDIA', 180.25),
    'US.ANET': ('Arista Networks', 95.50),
    'US.VRT': ('Vertiv', 112.40),
    'US.AVGO': ('Broadcom', 210.10),
    'US.MSFT': ('Microsoft', 428.30),
    'US.META': ('Meta Platforms', 612.75),
    'US.AMZN': ('Amazon.com', 204.15),
    'US.GOOGL': ('Alphabet', 186.40),
    'US.SNOW': ('Snowflake', 198.35),
    'US.SPY': ('SPDR S&P 500 ETF', 575.10),
}


class MockBrokerAdapter(BrokerAdapter):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def health_check(self) -> BrokerHealth:
        return BrokerHealth(
            backend='mock',
            status='ok',
            message='Mock broker backend is active. Switch BROKER_BACKEND=moomoo to connect OpenD.',
            is_reachable=True,
            is_authenticated=True,
            environment=self.settings.moomoo_trd_env,
            selected_acc_id=self.settings.moomoo_acc_id or 90000001,
            warnings=[
                'Using mock broker data. No real moomoo session is attached.',
                'Mock fills are synthetic and only for app plumbing, not realistic execution quality.',
            ],
            account_summary={
                'currency': 'USD',
                'cash': self.settings.risk_bankroll_cap,
                'market_value': 0.0,
                'total_assets': self.settings.risk_bankroll_cap,
                'available_funds': self.settings.risk_bankroll_cap,
            },
            checked_at=datetime.utcnow(),
        )

    def list_accounts(self) -> list[BrokerAccountRecord]:
        return [
            BrokerAccountRecord(
                acc_id=self.settings.moomoo_acc_id or 90000001,
                trd_env='SIMULATE',
                acc_type='SECURITIES',
                security_firm=self.settings.moomoo_security_firm,
                sim_acc_type='STOCK',
                uni_card_num='MOCK-UNIVERSAL',
                card_num='MOCK-PAPER',
                is_selected=True,
                raw_payload={'backend': 'mock'},
            )
        ]

    def list_positions(self) -> list[PositionRecord]:
        return []

    def list_open_orders(self) -> list[BrokerOrderRecord]:
        return []

    def list_recent_orders(self) -> list[BrokerOrderRecord]:
        return []

    def get_quote(self, symbol: str) -> QuoteRecord:
        normalized = symbol.strip().upper()
        name, last_price = MOCK_QUOTES.get(normalized, (normalized, 100.0))
        return QuoteRecord(
            symbol=normalized,
            name=name,
            last_price=last_price,
            bid_price=round(last_price - 0.05, 2),
            ask_price=round(last_price + 0.05, 2),
            prev_close_price=round(last_price * 0.99, 2),
            update_time=datetime.utcnow().isoformat(),
            raw_payload={'backend': 'mock'},
        )

    def submit_paper_order(self, ticket: PaperOrderTicket) -> BrokerOrderRecord:
        quote = self.get_quote(ticket.symbol)
        return BrokerOrderRecord(
            order_id=f'mock-{uuid4().hex[:12]}',
            symbol=ticket.symbol.upper(),
            side=ticket.side.upper(),
            order_type='LIMIT',
            status='FILLED',
            quantity=ticket.quantity,
            price=ticket.limit_price,
            filled_quantity=ticket.quantity,
            average_fill_price=ticket.limit_price,
            trading_env='SIMULATE',
            remark=ticket.remark,
            raw_payload={
                'backend': 'mock',
                'submitted_at': datetime.utcnow().isoformat(),
                'virtual_fill': True,
                'reference_last_price': quote.last_price,
                'agent_slug': ticket.agent_slug,
                'sleeve_slug': ticket.agent_slug,
            },
        )

    def cancel_order(self, order_id: str) -> None:
        return None

