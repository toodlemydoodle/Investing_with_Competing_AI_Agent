from __future__ import annotations

import importlib
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta

from app.broker.base import BrokerAccountRecord
from app.broker.base import BrokerAdapter
from app.broker.base import BrokerHealth
from app.broker.base import BrokerOrderRecord
from app.broker.base import PaperOrderTicket
from app.broker.base import PositionRecord
from app.broker.base import QuoteRecord
from app.core.config import Settings

RESET_CONTEXT_FRAGMENTS = (
    'connection failed',
    'disconnected',
    'not connected',
    'socket',
    'timed out',
    'timeout',
    'logged out',
    'unlock_trade failed',
    'login devices has exceeded the limit',
)


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == 'N/A':
        return None
    return text


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.upper() == 'N/A' or cleaned == '--':
            return default
        value = cleaned.replace(',', '')
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_not_ready_error(value: object) -> bool:
    return isinstance(value, str) and 'not ready yet' in value.lower()


class MoomooAdapter(BrokerAdapter):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._module = None
        self._module_error: str | None = None
        self._trade_context_instance = None
        self._quote_context_instance = None
        self._trade_lock = threading.RLock()
        self._quote_lock = threading.RLock()
        self._load_module()

    def _load_module(self) -> None:
        try:
            self._module = importlib.import_module('moomoo')
            self._module_error = None
        except Exception as exc:
            self._module = None
            self._module_error = str(exc)

    def _enum(self, enum_name: str, member_name: str):
        enum_cls = getattr(self._module, enum_name)
        return getattr(enum_cls, member_name)

    def _configure_context(self, context):
        if hasattr(context, 'set_sync_query_connect_timeout'):
            context.set_sync_query_connect_timeout(self.settings.broker_connect_timeout_seconds)
        if hasattr(context, '_query_timeout'):
            context._query_timeout = self.settings.broker_query_timeout_seconds
        return context

    def _should_reset_context(self, value: object) -> bool:
        lowered = str(value).lower()
        return any(fragment in lowered for fragment in RESET_CONTEXT_FRAGMENTS)

    def _close_context_instance(self, context) -> None:
        if context is None:
            return
        try:
            context.close()
        except Exception:
            pass

    def _reset_trade_context(self) -> None:
        context = self._trade_context_instance
        self._trade_context_instance = None
        self._close_context_instance(context)

    def _reset_quote_context(self) -> None:
        context = self._quote_context_instance
        self._quote_context_instance = None
        self._close_context_instance(context)

    def _maybe_reset_trade_context(self, value: object) -> None:
        if self._should_reset_context(value):
            self._reset_trade_context()

    def _maybe_reset_quote_context(self, value: object) -> None:
        if self._should_reset_context(value):
            self._reset_quote_context()

    def _get_trade_context(self):
        if self._module is None:
            detail = self._module_error or 'unknown import error'
            raise RuntimeError(f'moomoo package is unavailable: {detail}')
        if self._trade_context_instance is None:
            context = self._module.OpenSecTradeContext(
                filter_trdmarket=self._enum('TrdMarket', self.settings.moomoo_market),
                host=self.settings.moomoo_host,
                port=self.settings.moomoo_port,
                security_firm=self._enum('SecurityFirm', self.settings.moomoo_security_firm),
            )
            self._trade_context_instance = self._configure_context(context)
        return self._trade_context_instance

    def _get_quote_context(self):
        if self._module is None:
            detail = self._module_error or 'unknown import error'
            raise RuntimeError(f'moomoo package is unavailable: {detail}')
        if self._quote_context_instance is None:
            context = self._module.OpenQuoteContext(
                host=self.settings.moomoo_host,
                port=self.settings.moomoo_port,
            )
            self._quote_context_instance = self._configure_context(context)
        return self._quote_context_instance

    def _run_trade_query(self, operation_name: str, callback, *, allow_empty_on_not_ready: bool = False):
        last_data = None
        for attempt in range(3):
            ret, data = callback(attempt)
            if ret == self._module.RET_OK:
                return data
            last_data = data
            if not _is_not_ready_error(data):
                self._maybe_reset_trade_context(data)
                raise RuntimeError(f'{operation_name} failed: {data}')
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
        if allow_empty_on_not_ready:
            return None
        raise RuntimeError(f'{operation_name} failed: {last_data}')

    @contextmanager
    def _trade_context(self):
        with self._trade_lock:
            context = self._get_trade_context()
            try:
                yield context
            except Exception as exc:
                self._maybe_reset_trade_context(exc)
                raise

    @contextmanager
    def _quote_context(self):
        with self._quote_lock:
            context = self._get_quote_context()
            try:
                yield context
            except Exception as exc:
                self._maybe_reset_quote_context(exc)
                raise

    def close(self) -> None:
        with self._trade_lock:
            self._reset_trade_context()
        with self._quote_lock:
            self._reset_quote_context()

    def _selected_account(self, accounts: list[BrokerAccountRecord]) -> int | None:
        if self.settings.moomoo_acc_id is not None:
            return self.settings.moomoo_acc_id
        for account in accounts:
            if account.trd_env == self.settings.moomoo_trd_env:
                return account.acc_id
        return accounts[0].acc_id if accounts else None

    def _order_record_from_row(self, row) -> BrokerOrderRecord:
        return BrokerOrderRecord(
            order_id=str(row.get('order_id', '')),
            symbol=str(row.get('code', '')),
            side=str(row.get('trd_side', '')),
            order_type=str(row.get('order_type', '')),
            status=str(row.get('order_status', '')),
            quantity=_to_float(row.get('qty', 0.0)),
            price=_to_float(row.get('price', 0.0)),
            filled_quantity=_to_float(row.get('dealt_qty', 0.0)),
            average_fill_price=_to_float(row.get('dealt_avg_price', 0.0)),
            trading_env=str(row.get('trd_env', self.settings.moomoo_trd_env)),
            remark=_clean_text(row.get('remark', '')),
            raw_payload=row.to_dict(),
        )

    def health_check(self) -> BrokerHealth:
        if self._module is None:
            detail = self._module_error or 'moomoo package could not be imported.'
            return BrokerHealth(
                backend='moomoo',
                status='error',
                message=f'moomoo package is unavailable: {detail}',
                is_reachable=False,
                is_authenticated=False,
                environment=self.settings.moomoo_trd_env,
                selected_acc_id=self.settings.moomoo_acc_id,
                warnings=['Fix the local moomoo/OpenD installation before using the broker backend.'],
                account_summary={},
                checked_at=datetime.utcnow(),
            )

        warnings: list[str] = []
        try:
            accounts = self.list_accounts()
            selected_acc_id = self._selected_account(accounts)
            account_summary: dict[str, float | str | bool | None] = {}
            if selected_acc_id is not None:
                with self._trade_context() as context:
                    ret, data = context.accinfo_query(
                        trd_env=self._enum('TrdEnv', self.settings.moomoo_trd_env),
                        acc_id=selected_acc_id,
                        currency=self._enum('Currency', 'USD'),
                    )
                if ret == self._module.RET_OK and getattr(data, 'empty', False) is False:
                    row = data.iloc[0]
                    account_summary = {
                        'currency': _clean_text(row.get('currency', 'USD')) or 'USD',
                        'cash': _to_float(row.get('cash', 0.0)),
                        'market_value': _to_float(row.get('market_val', 0.0)),
                        'total_assets': _to_float(row.get('total_assets', 0.0)),
                        'available_funds': _to_float(row.get('available_funds', 0.0)),
                    }
                else:
                    warnings.append(f'Account summary unavailable: {data}')

            if self.settings.moomoo_trd_env == 'REAL':
                warnings.append('Live trading requires unlock_trade() and moomoo token must be disabled.')
            if self.settings.moomoo_trd_env == 'SIMULATE':
                warnings.append('Paper fills are tracked from order history because moomoo paper does not expose deal history.')
            if self.settings.moomoo_acc_id is None:
                warnings.append('MOOMOO_ACC_ID is blank, so the first matching account for the selected environment will be used.')

            return BrokerHealth(
                backend='moomoo',
                status='ok',
                message='Connected to OpenD.',
                is_reachable=True,
                is_authenticated=True,
                environment=self.settings.moomoo_trd_env,
                selected_acc_id=selected_acc_id,
                warnings=warnings,
                account_summary=account_summary,
                checked_at=datetime.utcnow(),
            )
        except Exception as exc:
            return BrokerHealth(
                backend='moomoo',
                status='error',
                message=f'OpenD connection failed: {exc}',
                is_reachable=False,
                is_authenticated=False,
                environment=self.settings.moomoo_trd_env,
                selected_acc_id=self.settings.moomoo_acc_id,
                warnings=[
                    'Confirm OpenD is running.',
                    'Confirm the moomoo account is logged in.',
                    f'Current timeouts are connect={self.settings.broker_connect_timeout_seconds}s and query={self.settings.broker_query_timeout_seconds}s.',
                ],
                account_summary={},
                checked_at=datetime.utcnow(),
            )

    def list_accounts(self) -> list[BrokerAccountRecord]:
        with self._trade_context() as context:
            ret, data = context.get_acc_list()
        if ret != self._module.RET_OK:
            self._maybe_reset_trade_context(data)
            raise RuntimeError(f'get_acc_list failed: {data}')
        selected = self._selected_account(
            [
                BrokerAccountRecord(
                    acc_id=int(row['acc_id']),
                    trd_env=str(row.get('trd_env', '')),
                    acc_type=str(row.get('acc_type', '')),
                    security_firm=_clean_text(row.get('security_firm', '')) or 'N/A',
                )
                for _, row in data.iterrows()
            ]
        )
        accounts: list[BrokerAccountRecord] = []
        for _, row in data.iterrows():
            acc_id = int(row['acc_id'])
            accounts.append(
                BrokerAccountRecord(
                    acc_id=acc_id,
                    trd_env=str(row.get('trd_env', '')),
                    acc_type=str(row.get('acc_type', '')),
                    security_firm=_clean_text(row.get('security_firm', '')) or 'N/A',
                    sim_acc_type=_clean_text(row.get('sim_acc_type', '')),
                    uni_card_num=_clean_text(row.get('uni_card_num', '')),
                    card_num=_clean_text(row.get('card_num', '')),
                    is_selected=acc_id == selected,
                    raw_payload=row.to_dict(),
                )
            )
        return accounts

    def list_positions(self) -> list[PositionRecord]:
        acc_id = self._selected_account(self.list_accounts())
        if acc_id is None:
            return []
        with self._trade_context() as context:
            data = self._run_trade_query(
                'position_list_query',
                lambda attempt: context.position_list_query(
                    trd_env=self._enum('TrdEnv', self.settings.moomoo_trd_env),
                    acc_id=acc_id,
                    refresh_cache=attempt > 0,
                ),
                allow_empty_on_not_ready=True,
            )
        if data is None or getattr(data, 'empty', False):
            return []
        positions: list[PositionRecord] = []
        for _, row in data.iterrows():
            positions.append(
                PositionRecord(
                    symbol=str(row.get('code', '')),
                    name=str(row.get('stock_name', row.get('name', ''))),
                    quantity=_to_float(row.get('qty', 0.0)),
                    can_sell_quantity=_to_float(row.get('can_sell_qty', 0.0)),
                    market_price=_to_float(row.get('nominal_price', row.get('price', 0.0))),
                    cost_price=_to_float(row.get('cost_price', 0.0)),
                    market_value=_to_float(row.get('market_val', row.get('val', 0.0))),
                    unrealized_pl=_to_float(row.get('unrealized_pl', row.get('pl_val', 0.0))),
                    currency=_clean_text(row.get('currency', 'USD')) or 'USD',
                    raw_payload=row.to_dict(),
                )
            )
        return positions

    def list_open_orders(self) -> list[BrokerOrderRecord]:
        acc_id = self._selected_account(self.list_accounts())
        if acc_id is None:
            return []
        with self._trade_context() as context:
            data = self._run_trade_query(
                'order_list_query',
                lambda attempt: context.order_list_query(
                    trd_env=self._enum('TrdEnv', self.settings.moomoo_trd_env),
                    acc_id=acc_id,
                    refresh_cache=attempt > 0,
                ),
                allow_empty_on_not_ready=True,
            )
        if data is None or getattr(data, 'empty', False):
            return []
        return [self._order_record_from_row(row) for _, row in data.iterrows()]

    def list_recent_orders(self) -> list[BrokerOrderRecord]:
        acc_id = self._selected_account(self.list_accounts())
        if acc_id is None:
            return []
        start = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
        with self._trade_context() as context:
            data = self._run_trade_query(
                'history_order_list_query',
                lambda _: context.history_order_list_query(
                    start=start,
                    trd_env=self._enum('TrdEnv', self.settings.moomoo_trd_env),
                    acc_id=acc_id,
                ),
                allow_empty_on_not_ready=True,
            )
        orders_by_id: dict[str, BrokerOrderRecord] = {}
        if data is not None and getattr(data, 'empty', False) is False:
            for _, row in data.iterrows():
                record = self._order_record_from_row(row)
                orders_by_id[record.order_id] = record
        for order in self.list_open_orders():
            orders_by_id[order.order_id] = order
        return sorted(orders_by_id.values(), key=lambda order: order.order_id, reverse=True)

    def _quote_record_from_row(self, row, normalized: str) -> QuoteRecord:
        last_price = _to_float(row.get('last_price', 0.0))
        bid_price = _to_float(row.get('bid_price', last_price))
        ask_price = _to_float(row.get('ask_price', last_price))
        prev_close_price = _to_float(row.get('prev_close_price', 0.0))
        name = _clean_text(row.get('name', '')) or normalized
        update_time = _clean_text(row.get('update_time', ''))
        if update_time is None:
            data_date = _clean_text(row.get('data_date', ''))
            data_time = _clean_text(row.get('data_time', ''))
            if data_date and data_time:
                update_time = f'{data_date} {data_time}'
            else:
                update_time = data_date or data_time
        return QuoteRecord(
            symbol=str(row.get('code', normalized)),
            name=str(name),
            last_price=last_price,
            bid_price=bid_price or last_price,
            ask_price=ask_price or last_price,
            prev_close_price=prev_close_price,
            update_time=update_time,
            raw_payload=row.to_dict(),
        )

    def get_quote(self, symbol: str) -> QuoteRecord:
        normalized = symbol.strip().upper()
        errors: list[str] = []
        with self._quote_context() as context:
            ret, data = context.get_market_snapshot([normalized])
            if ret == self._module.RET_OK and getattr(data, 'empty', False) is False:
                return self._quote_record_from_row(data.iloc[0], normalized)
            errors.append(f'get_market_snapshot failed: {data}')

            subscribe_ret, subscribe_data = context.subscribe(
                [normalized],
                [self._enum('SubType', 'QUOTE')],
                subscribe_push=False,
            )
            if subscribe_ret != self._module.RET_OK:
                errors.append(f'subscribe failed: {subscribe_data}')
            else:
                quote_ret, quote_data = context.get_stock_quote([normalized])
                if quote_ret == self._module.RET_OK and getattr(quote_data, 'empty', False) is False:
                    return self._quote_record_from_row(quote_data.iloc[0], normalized)
                errors.append(f'get_stock_quote failed: {quote_data}')

        self._maybe_reset_quote_context(' | '.join(errors))
        raise RuntimeError(f'Quote lookup failed for {normalized}: ' + ' | '.join(errors))

    def _unlock_if_needed(self, context) -> None:
        if self.settings.moomoo_trd_env != 'REAL':
            return
        if not self.settings.moomoo_unlock_password:
            raise RuntimeError('MOOMOO_UNLOCK_PASSWORD is required for live trading.')
        ret, data = context.unlock_trade(self.settings.moomoo_unlock_password)
        if ret != self._module.RET_OK:
            self._maybe_reset_trade_context(data)
            raise RuntimeError(f'unlock_trade failed: {data}')

    def submit_paper_order(self, ticket: PaperOrderTicket) -> BrokerOrderRecord:
        acc_id = self._selected_account(self.list_accounts())
        if acc_id is None:
            raise RuntimeError('No moomoo account is configured.')
        with self._trade_context() as context:
            self._unlock_if_needed(context)
            ret, data = context.place_order(
                price=ticket.limit_price,
                qty=ticket.quantity,
                code=ticket.symbol.upper(),
                trd_side=self._enum('TrdSide', ticket.side.upper()),
                order_type=self._enum('OrderType', 'NORMAL'),
                trd_env=self._enum('TrdEnv', self.settings.moomoo_trd_env),
                acc_id=acc_id,
                remark=ticket.remark,
                time_in_force=self._enum('TimeInForce', 'DAY'),
                fill_outside_rth=False,
                session=self._enum('Session', 'NONE'),
            )
        if ret != self._module.RET_OK:
            self._maybe_reset_trade_context(data)
            raise RuntimeError(f'place_order failed: {data}')
        row = data.iloc[0]
        return self._order_record_from_row(row)

    def cancel_order(self, order_id: str) -> None:
        acc_id = self._selected_account(self.list_accounts())
        if acc_id is None:
            raise RuntimeError('No moomoo account is configured.')
        with self._trade_context() as context:
            self._unlock_if_needed(context)
            ret, data = context.modify_order(
                self._enum('ModifyOrderOp', 'CANCEL'),
                order_id,
                0,
                0,
                trd_env=self._enum('TrdEnv', self.settings.moomoo_trd_env),
                acc_id=acc_id,
            )
        if ret != self._module.RET_OK:
            self._maybe_reset_trade_context(data)
            raise RuntimeError(f'modify_order cancel failed: {data}')
