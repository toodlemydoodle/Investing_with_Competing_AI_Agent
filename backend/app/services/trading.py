from __future__ import annotations

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from threading import Lock
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker.base import BrokerAdapter
from app.broker.base import PaperOrderTicket
from app.broker.mock import MockBrokerAdapter
from app.broker.moomoo_adapter import MoomooAdapter
from app.core.config import BACKEND_ROOT
from app.core.config import Settings
from app.models.entities import Alert
from app.models.entities import AppSetting
from app.models.entities import BrokerAccount
from app.models.entities import BrokerOrder
from app.models.entities import Decision
from app.models.entities import Position
from app.models.entities import StrategyAgent
from app.models.entities import AgentPosition
from app.models.entities import AgentTrade
from app.models.entities import Theme
from app.services.quotes import get_quote_record

US_STOCK_PREFIX = 'US.'
FILLED_ORDER_STATUSES = {'FILLED', 'FILLED_ALL', 'SUCCESS_ALL'}
EPSILON = 1e-9
BROKER_ORDER_TIMEZONE = ZoneInfo('America/New_York')
BROKER_ORDER_SYNC_CUTOFF_PATH = BACKEND_ROOT / '.broker-order-sync-cutoff.txt'
BROKER_RECONCILIATION_ALERT_TITLE = 'Broker ledger reconciliation warning'
BENCHMARK_HISTORY_KEY = 'competition_benchmark_history'
BENCHMARK_START_AT_KEY = 'competition_benchmark_start_at'
LEADER_BONUS_RECIPIENT_KEY = 'leader_bonus_recipient'
LEADER_BONUS_AMOUNT_KEY = 'leader_bonus_amount'
AGENT_BONUS_TOTAL_KEY_PREFIX = 'agent_bonus_total::'
AGENT_TWR_PERIODS_KEY_PREFIX = 'agent_twr_periods::'
AGENT_TWR_PERIOD_START_KEY_PREFIX = 'agent_twr_period_start::'
AGENT_BENCHMARK_CHECKPOINT_KEY_PREFIX = 'agent_benchmark_checkpoint::'
AGENT_CASH_ONLY_KEY_PREFIX = 'agent_cash_only::'
AGENT_CASH_ONLY_AT_KEY_PREFIX = 'agent_cash_only_at::'
AGENT_CASH_ONLY_REASON_KEY_PREFIX = 'agent_cash_only_reason::'
BENCHMARK_HISTORY_LIMIT = 288
BENCHMARK_HISTORY_MIN_INTERVAL_SECONDS = 240
BENCHMARK_CHECK_INTERVAL_DAYS = 30
AGENT_HISTORY_KEY_PREFIX = 'agent_history::'
AGENT_HISTORY_LIMIT = 432
AGENT_HISTORY_MIN_INTERVAL_SECONDS = 240
AGENT_CASH_HISTORY_LIMIT = 720
AGENT_HOLDINGS_HISTORY_LIMIT = 720
FINAL_ORDER_STATUS_FRAGMENTS = ('CANCEL', 'FAIL', 'REJECT', 'DELETE', 'DISABLE')
BROKER_CASH_ERROR_FRAGMENTS = (
    'insufficient',
    'not enough cash',
    'not enough buying power',
    'buying power',
    'available funds',
    'funds are insufficient',
    'cash is not enough',
    'exceed cash',
)
_ADAPTER_CACHE_LOCK = Lock()
_ADAPTER_CACHE: dict[tuple[object, ...], BrokerAdapter] = {}



def json_dump(value: object) -> str:
    return json.dumps(value, default=str)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def get_setting_value(db: Session, key: str, fallback: str) -> str:
    setting = db.get(AppSetting, key)
    return fallback if setting is None else setting.value


def set_setting_value(db: Session, key: str, value: str) -> None:
    setting = db.get(AppSetting, key)
    if setting is None:
        db.add(AppSetting(key=key, value=value))
    else:
        setting.value = value


def ensure_default_setting(db: Session, key: str, value: str) -> None:
    if db.get(AppSetting, key) is None:
        db.add(AppSetting(key=key, value=value))


def get_active_mode(db: Session, settings: Settings) -> str:
    return get_setting_value(db, 'app_mode', settings.app_mode)


def get_leader_bonus_award(db: Session) -> tuple[str, float]:
    recipient = get_setting_value(db, LEADER_BONUS_RECIPIENT_KEY, '').strip()
    amount = _parse_float_setting(get_setting_value(db, LEADER_BONUS_AMOUNT_KEY, ''))
    return recipient, round(max(float(amount or 0.0), 0.0), 2)


def _agent_bonus_total_key(agent_slug: str) -> str:
    return f'{AGENT_BONUS_TOTAL_KEY_PREFIX}{agent_slug}'


def get_agent_bonus_total(db: Session, agent_slug: str) -> float:
    amount = _parse_float_setting(get_setting_value(db, _agent_bonus_total_key(agent_slug), ''))
    if amount is not None:
        return round(max(float(amount), 0.0), 2)

    recipient, latest_amount = get_leader_bonus_award(db)
    if recipient == agent_slug:
        return latest_amount
    return 0.0


def _set_agent_bonus_total(db: Session, agent_slug: str, amount: float) -> float:
    normalized = round(max(float(amount or 0.0), 0.0), 2)
    set_setting_value(db, _agent_bonus_total_key(agent_slug), str(normalized))
    db.flush()
    return normalized


def award_agent_bonus(db: Session, agent_slug: str, amount: float) -> float:
    agent = db.get(StrategyAgent, agent_slug)
    if agent is None:
        raise ValueError(f'Unknown agent `{agent_slug}`.')
    if not agent.is_enabled:
        raise ValueError(f'Agent `{agent.name}` is disabled.')
    if not agent.is_alive:
        raise ValueError(f'Agent `{agent.name}` has already lost and cannot receive new capital.')

    normalized = round(float(amount or 0.0), 2)
    if normalized <= EPSILON:
        raise ValueError('Bonus amount must be greater than zero.')

    _snapshot_twr_period(db, agent, normalized)
    total_bonus = _set_agent_bonus_total(db, agent_slug, get_agent_bonus_total(db, agent_slug) + normalized)
    set_setting_value(db, LEADER_BONUS_RECIPIENT_KEY, agent_slug)
    set_setting_value(db, LEADER_BONUS_AMOUNT_KEY, str(normalized))
    return total_bonus


def get_agent_capital_bonus(db: Session, agent_slug: str) -> float:
    return get_agent_bonus_total(db, agent_slug)


def _agent_twr_periods_key(agent_slug: str) -> str:
    return f'{AGENT_TWR_PERIODS_KEY_PREFIX}{agent_slug}'


def _agent_twr_period_start_key(agent_slug: str) -> str:
    return f'{AGENT_TWR_PERIOD_START_KEY_PREFIX}{agent_slug}'


def _load_twr_periods(db: Session, agent_slug: str) -> list[dict[str, float]]:
    raw = get_setting_value(db, _agent_twr_periods_key(agent_slug), '[]')
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []


def _get_twr_period_start(db: Session, agent: StrategyAgent) -> float:
    raw = get_setting_value(db, _agent_twr_period_start_key(agent.slug), '')
    value = _parse_float_setting(raw)
    return value if value is not None else max(float(agent.starting_capital), EPSILON)


def _snapshot_twr_period(db: Session, agent: StrategyAgent, injected: float) -> None:
    period_start = _get_twr_period_start(db, agent)
    periods = _load_twr_periods(db, agent.slug)
    periods.append({'start': round(period_start, 2), 'end': round(float(agent.current_value), 2)})
    set_setting_value(db, _agent_twr_periods_key(agent.slug), json.dumps(periods))
    new_period_start = round(float(agent.current_value) + injected, 2)
    set_setting_value(db, _agent_twr_period_start_key(agent.slug), str(new_period_start))


def compute_agent_twr(db: Session, agent: StrategyAgent) -> float:
    periods = _load_twr_periods(db, agent.slug)
    chain = 1.0
    for p in periods:
        start = max(float(p['start']), EPSILON)
        chain *= float(p['end']) / start
    current_start = max(_get_twr_period_start(db, agent), EPSILON)
    current_end = max(float(agent.current_value), 0.0)
    chain *= current_end / current_start
    return round((chain - 1.0) * 100, 2)


def _agent_display_name(agent_slug: str) -> str:
    labels = {
        'liberated-us-stocks': 'Liberated US Stocks',
        'pick-shovel-growth': 'Pick-and-Shovel Growth',
    }
    return labels.get(agent_slug, agent_slug.replace('-', ' ').title())


def _format_bonus_amount(amount: float) -> str:
    normalized = round(float(amount), 2)
    if abs(normalized - round(normalized)) < EPSILON:
        return f'${normalized:.0f}'
    return f'${normalized:.2f}'


def _backfill_agent_bonus_totals(db: Session) -> None:
    recipient, latest_amount = get_leader_bonus_award(db)
    if not recipient or latest_amount <= EPSILON:
        return

    existing_total = _parse_float_setting(get_setting_value(db, _agent_bonus_total_key(recipient), ''))
    if existing_total is None:
        _set_agent_bonus_total(db, recipient, latest_amount)


def get_agent_note(agent_slug: str, benchmark_symbol: str, *, bonus_recipient: str = '', bonus_amount: float = 0.0) -> str:
    base_notes = {
        'pick-shovel-growth': f'Specialist agent. The first 90 days are a warm-up, then trailing {benchmark_symbol} at a monthly checkpoint triggers the benchmark penalty.',
        'liberated-us-stocks': f'Flexible agent. The first 90 days are a warm-up, then trailing {benchmark_symbol} at a monthly checkpoint triggers the benchmark penalty.',
    }
    note = base_notes.get(agent_slug, f'After day 90, trailing {benchmark_symbol} at a monthly checkpoint triggers the benchmark penalty.')
    if bonus_amount <= EPSILON or not bonus_recipient:
        return note

    formatted_bonus = _format_bonus_amount(bonus_amount)
    if agent_slug == bonus_recipient:
        return f'{note} This agent received an extra {formatted_bonus} because it was ahead when the latest capital award was made.'
    return (
        f'{note} This agent was behind when the latest capital award was made, '
        f'so the extra {formatted_bonus} went to {_agent_display_name(bonus_recipient)} instead.'
    )


def get_agent_performance_value(db: Session, agent: StrategyAgent) -> float:
    return max(float(agent.current_value) - get_agent_capital_bonus(db, agent.slug), 0.0)


def get_runtime_settings(db: Session, settings: Settings) -> Settings:
    mode = get_active_mode(db, settings)
    updates: dict[str, object] = {}

    if settings.broker_backend.lower() == 'moomoo':
        if mode == 'live_capped':
            updates['moomoo_trd_env'] = settings.moomoo_live_trd_env
            updates['moomoo_acc_id'] = settings.moomoo_live_acc_id
        else:
            updates['moomoo_trd_env'] = settings.moomoo_paper_trd_env
            updates['moomoo_acc_id'] = settings.moomoo_paper_acc_id if settings.moomoo_paper_acc_id is not None else settings.moomoo_acc_id

    if mode == 'live_capped':
        updates['quote_provider'] = 'broker'

    return settings.model_copy(update=updates) if updates else settings


def get_live_capped_agent_slug(settings: Settings) -> str:
    slug = str(settings.live_capped_agent_slug or '').strip()
    return slug or 'pick-shovel-growth'


def get_selected_account_id(db: Session, settings: Settings) -> int | None:
    runtime_settings = get_runtime_settings(db, settings)
    if runtime_settings.moomoo_acc_id is not None:
        return int(runtime_settings.moomoo_acc_id)
    raw = get_setting_value(db, 'selected_acc_id', '')
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _broker_adapter_cache_key(settings: Settings) -> tuple[object, ...]:
    return (
        settings.broker_backend.lower(),
        settings.moomoo_host,
        settings.moomoo_port,
        settings.moomoo_market,
        settings.moomoo_security_firm,
        settings.moomoo_trd_env,
        settings.moomoo_acc_id,
        settings.broker_connect_timeout_seconds,
        settings.broker_query_timeout_seconds,
    )


def build_broker_adapter(settings: Settings) -> BrokerAdapter:
    if settings.broker_backend.lower() != 'moomoo':
        return MockBrokerAdapter(settings)

    cache_key = _broker_adapter_cache_key(settings)
    with _ADAPTER_CACHE_LOCK:
        adapter = _ADAPTER_CACHE.get(cache_key)
        if adapter is None:
            adapter = MoomooAdapter(settings)
            _ADAPTER_CACHE[cache_key] = adapter
        return adapter


def close_broker_adapters() -> None:
    with _ADAPTER_CACHE_LOCK:
        adapters = list(_ADAPTER_CACHE.values())
        _ADAPTER_CACHE.clear()
    for adapter in adapters:
        adapter.close()


def _parse_float_setting(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_datetime_setting(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_broker_order_time(raw: object) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for pattern in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BROKER_ORDER_TIMEZONE)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _get_broker_order_timestamp(order) -> datetime | None:
    payload = order.raw_payload or {}
    if not isinstance(payload, dict):
        return None
    for key in ('updated_time', 'create_time'):
        parsed = _parse_broker_order_time(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _get_broker_order_sync_cutoff() -> datetime | None:
    try:
        raw = BROKER_ORDER_SYNC_CUTOFF_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    if not raw:
        return None
    normalized = raw[:-1] + '+00:00' if raw.endswith('Z') else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _load_competition_benchmark_history(db: Session) -> list[dict[str, object]]:
    raw = get_setting_value(db, BENCHMARK_HISTORY_KEY, '[]')
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    points: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        recorded_at = _parse_datetime_setting(str(item.get('recorded_at') or ''))
        try:
            price = round(float(item.get('price')), 4)
        except (TypeError, ValueError):
            continue
        if recorded_at is None or price <= 0:
            continue
        points.append({'price': price, 'recorded_at': recorded_at})

    points.sort(key=lambda point: point['recorded_at'])
    return points[-BENCHMARK_HISTORY_LIMIT:]


def _store_competition_benchmark_history(db: Session, points: list[dict[str, object]]) -> None:
    payload = [
        {
            'price': round(float(point['price']), 4),
            'recorded_at': point['recorded_at'].isoformat(),
        }
        for point in points[-BENCHMARK_HISTORY_LIMIT:]
        if isinstance(point.get('recorded_at'), datetime)
    ]
    set_setting_value(db, BENCHMARK_HISTORY_KEY, json.dumps(payload))


def _build_competition_benchmark_history_fallback(
    start_price: float | None,
    start_at: datetime | None,
    current_price: float | None,
    last_updated_at: datetime | None,
) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    if start_price is not None and start_price > 0:
        points.append(
            {
                'price': round(float(start_price), 4),
                'recorded_at': start_at or last_updated_at or datetime.utcnow(),
            }
        )
    if current_price is not None and current_price > 0:
        current_point = {
            'price': round(float(current_price), 4),
            'recorded_at': last_updated_at or start_at or datetime.utcnow(),
        }
        if not points:
            points.append(current_point)
        else:
            first = points[0]
            if abs(float(first['price']) - current_point['price']) >= EPSILON or first['recorded_at'] != current_point['recorded_at']:
                points.append(current_point)
    points.sort(key=lambda point: point['recorded_at'])
    return points


def _append_competition_benchmark_history(db: Session, price: float, recorded_at: datetime) -> list[dict[str, object]]:
    if price <= 0:
        return _load_competition_benchmark_history(db)

    point = {'price': round(float(price), 4), 'recorded_at': recorded_at}
    history = _load_competition_benchmark_history(db)
    if not history:
        history = [point]
    else:
        last = history[-1]
        age_seconds = (recorded_at - last['recorded_at']).total_seconds()
        last_price = float(last['price'])
        if age_seconds <= 0 or age_seconds < BENCHMARK_HISTORY_MIN_INTERVAL_SECONDS:
            history[-1] = point
        elif abs(last_price - point['price']) < EPSILON:
            return history
        else:
            history.append(point)

    history.sort(key=lambda item: item['recorded_at'])
    history = history[-BENCHMARK_HISTORY_LIMIT:]
    _store_competition_benchmark_history(db, history)
    return history


def _agent_history_key(agent_slug: str) -> str:
    return f'{AGENT_HISTORY_KEY_PREFIX}{agent_slug}'


def _load_agent_history(db: Session, agent_slug: str) -> list[dict[str, object]]:
    raw = get_setting_value(db, _agent_history_key(agent_slug), '[]')
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    points: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        recorded_at = _parse_datetime_setting(str(item.get('recorded_at') or ''))
        if recorded_at is None:
            continue
        try:
            equity = round(float(item.get('equity')), 2)
            cash = round(float(item.get('cash')), 2)
            return_pct = round(float(item.get('return_pct')), 2)
        except (TypeError, ValueError):
            continue
        points.append({
            'equity': equity,
            'cash': cash,
            'return_pct': return_pct,
            'recorded_at': recorded_at,
        })

    points.sort(key=lambda point: point['recorded_at'])
    return points[-AGENT_HISTORY_LIMIT:]


def _store_agent_history(db: Session, agent_slug: str, points: list[dict[str, object]]) -> None:
    payload = [
        {
            'equity': round(float(point['equity']), 2),
            'cash': round(float(point['cash']), 2),
            'return_pct': round(float(point['return_pct']), 2),
            'recorded_at': point['recorded_at'].isoformat(),
        }
        for point in points[-AGENT_HISTORY_LIMIT:]
        if isinstance(point.get('recorded_at'), datetime)
    ]
    set_setting_value(db, _agent_history_key(agent_slug), json.dumps(payload))


def _append_agent_history_point(db: Session, agent: StrategyAgent, recorded_at: datetime) -> list[dict[str, object]]:
    point = {
        'equity': round(float(agent.current_value), 2),
        'cash': round(float(agent.cash_buffer), 2),
        'return_pct': round(float(agent.total_return_pct), 2),
        'recorded_at': recorded_at,
    }
    history = _load_agent_history(db, agent.slug)
    if not history:
        history = [point]
    else:
        last = history[-1]
        age_seconds = (recorded_at - last['recorded_at']).total_seconds()
        same_values = (
            abs(float(last['equity']) - point['equity']) < EPSILON
            and abs(float(last['cash']) - point['cash']) < EPSILON
            and abs(float(last['return_pct']) - point['return_pct']) < EPSILON
        )
        if age_seconds <= 0 or age_seconds < AGENT_HISTORY_MIN_INTERVAL_SECONDS:
            history[-1] = point
        elif same_values:
            return history
        else:
            history.append(point)

    history.sort(key=lambda item: item['recorded_at'])
    history = history[-AGENT_HISTORY_LIMIT:]
    _store_agent_history(db, agent.slug, history)
    return history


def get_agent_history(db: Session, agent_slug: str) -> list[dict[str, object]]:
    return _load_agent_history(db, agent_slug)


def get_competition_benchmark_state(
    db: Session,
    settings: Settings,
    *,
    refresh: bool = False,
) -> dict[str, object]:
    symbol = (settings.competition_benchmark_symbol or 'US.SPY').strip().upper() or 'US.SPY'
    stored_symbol = get_setting_value(db, 'competition_benchmark_symbol', symbol).strip().upper() or symbol
    if stored_symbol != symbol:
        set_setting_value(db, 'competition_benchmark_symbol', symbol)
        set_setting_value(db, 'competition_benchmark_start_price', '')
        set_setting_value(db, 'competition_benchmark_last_updated_at', '')
        set_setting_value(db, 'competition_benchmark_current_price', '')
        set_setting_value(db, BENCHMARK_START_AT_KEY, '')
        set_setting_value(db, BENCHMARK_HISTORY_KEY, '[]')

    start_price = _parse_float_setting(get_setting_value(db, 'competition_benchmark_start_price', ''))
    current_price = _parse_float_setting(get_setting_value(db, 'competition_benchmark_current_price', ''))
    start_at = _parse_datetime_setting(get_setting_value(db, BENCHMARK_START_AT_KEY, ''))
    last_updated_at = _parse_datetime_setting(get_setting_value(db, 'competition_benchmark_last_updated_at', ''))
    history = _load_competition_benchmark_history(db)

    if refresh:
        try:
            quote = get_quote_record(settings, symbol)
            current_price = round(float(quote.last_price), 4)
            last_updated_at = datetime.utcnow()
            set_setting_value(db, 'competition_benchmark_current_price', str(current_price))
            set_setting_value(db, 'competition_benchmark_last_updated_at', last_updated_at.isoformat())
            if start_price is None or start_price <= 0:
                start_price = current_price
                start_at = last_updated_at
                set_setting_value(db, 'competition_benchmark_start_price', str(start_price))
                set_setting_value(db, BENCHMARK_START_AT_KEY, start_at.isoformat())
            elif start_at is None:
                start_at = last_updated_at
                set_setting_value(db, BENCHMARK_START_AT_KEY, start_at.isoformat())
            history = _append_competition_benchmark_history(db, current_price, last_updated_at)
        except Exception:
            pass

    if not history:
        history = _build_competition_benchmark_history_fallback(start_price, start_at, current_price, last_updated_at)

    return_pct = None
    if start_price is not None and start_price > 0 and current_price is not None and current_price > 0:
        return_pct = round(((current_price - start_price) / start_price) * 100.0, 2)

    return {
        'symbol': symbol,
        'start_price': start_price,
        'current_price': current_price,
        'return_pct': return_pct,
        'last_updated_at': last_updated_at,
        'history': history,
    }


def agent_excess_return_pct(agent: StrategyAgent, benchmark_return_pct: float | None) -> float:
    if benchmark_return_pct is None:
        return round(agent.total_return_pct, 2)
    return round(agent.total_return_pct - benchmark_return_pct, 2)


def _agent_benchmark_checkpoint_key(agent_slug: str) -> str:
    return f'{AGENT_BENCHMARK_CHECKPOINT_KEY_PREFIX}{agent_slug}'


def _agent_cash_only_key(agent_slug: str) -> str:
    return f'{AGENT_CASH_ONLY_KEY_PREFIX}{agent_slug}'


def _agent_cash_only_at_key(agent_slug: str) -> str:
    return f'{AGENT_CASH_ONLY_AT_KEY_PREFIX}{agent_slug}'


def _agent_cash_only_reason_key(agent_slug: str) -> str:
    return f'{AGENT_CASH_ONLY_REASON_KEY_PREFIX}{agent_slug}'


def get_benchmark_warmup_end_at(agent: StrategyAgent) -> datetime:
    return agent.created_at + timedelta(days=max(agent.competition_window_days, 1))


def get_agent_window_cutoff(agent: StrategyAgent, now: datetime) -> datetime:
    return now - timedelta(days=max(agent.competition_window_days, 1))


def get_elimination_ready_at(agent: StrategyAgent) -> datetime:
    return get_benchmark_warmup_end_at(agent)


def get_agent_last_benchmark_checkpoint_at(db: Session, agent_slug: str) -> datetime | None:
    return _parse_datetime_setting(get_setting_value(db, _agent_benchmark_checkpoint_key(agent_slug), ''))


def set_agent_last_benchmark_checkpoint_at(db: Session, agent_slug: str, checkpoint_at: datetime) -> None:
    set_setting_value(db, _agent_benchmark_checkpoint_key(agent_slug), checkpoint_at.isoformat())
    db.flush()


def is_agent_cash_only(db: Session, agent_slug: str) -> bool:
    raw = get_setting_value(db, _agent_cash_only_key(agent_slug), '')
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def get_agent_cash_only_at(db: Session, agent_slug: str) -> datetime | None:
    return _parse_datetime_setting(get_setting_value(db, _agent_cash_only_at_key(agent_slug), ''))


def get_agent_cash_only_reason(db: Session, agent_slug: str) -> str | None:
    raw = get_setting_value(db, _agent_cash_only_reason_key(agent_slug), '').strip()
    return raw or None


def set_agent_cash_only_state(
    db: Session,
    agent_slug: str,
    enabled: bool,
    *,
    reason: str | None = None,
    triggered_at: datetime | None = None,
) -> None:
    set_setting_value(db, _agent_cash_only_key(agent_slug), 'true' if enabled else 'false')
    set_setting_value(db, _agent_cash_only_reason_key(agent_slug), (reason or '').strip())
    set_setting_value(db, _agent_cash_only_at_key(agent_slug), triggered_at.isoformat() if enabled and triggered_at else '')
    db.flush()


def get_agent_latest_benchmark_checkpoint_at(agent: StrategyAgent, now: datetime) -> datetime | None:
    warmup_end_at = get_benchmark_warmup_end_at(agent)
    if now < warmup_end_at:
        return None

    elapsed_seconds = max((now - warmup_end_at).total_seconds(), 0.0)
    interval_seconds = BENCHMARK_CHECK_INTERVAL_DAYS * 86400
    completed_intervals = int(elapsed_seconds // interval_seconds)
    return warmup_end_at + timedelta(days=completed_intervals * BENCHMARK_CHECK_INTERVAL_DAYS)


def get_agent_due_benchmark_checkpoint_at(db: Session, agent: StrategyAgent, now: datetime) -> datetime | None:
    latest_checkpoint_at = get_agent_latest_benchmark_checkpoint_at(agent, now)
    if latest_checkpoint_at is None:
        return None

    last_checkpoint_at = get_agent_last_benchmark_checkpoint_at(db, agent.slug)
    if last_checkpoint_at is not None and last_checkpoint_at >= latest_checkpoint_at:
        return None
    return latest_checkpoint_at


def is_agent_benchmark_check_due(db: Session, agent: StrategyAgent, now: datetime) -> bool:
    return get_agent_due_benchmark_checkpoint_at(db, agent, now) is not None


def get_agent_next_benchmark_check_at(db: Session, agent: StrategyAgent, now: datetime) -> datetime:
    warmup_end_at = get_benchmark_warmup_end_at(agent)
    due_checkpoint_at = get_agent_due_benchmark_checkpoint_at(db, agent, now)
    if due_checkpoint_at is not None:
        return due_checkpoint_at
    if now < warmup_end_at:
        return warmup_end_at

    latest_checkpoint_at = get_agent_latest_benchmark_checkpoint_at(agent, now)
    if latest_checkpoint_at is None:
        return warmup_end_at
    return latest_checkpoint_at + timedelta(days=BENCHMARK_CHECK_INTERVAL_DAYS)


def mark_agent_dead(agent: StrategyAgent, reason: str, death_round: int) -> None:
    agent.is_alive = False
    agent.is_winner = False
    agent.target_weight = 0.0
    agent.allocated_capital = 0.0
    agent.reward_multiplier = 0.0
    agent.death_reason = reason
    agent.death_round = death_round


def revive_agent(agent: StrategyAgent) -> None:
    agent.is_alive = True
    agent.death_reason = None
    agent.death_round = None


def update_agent_survival_state(db: Session, agent: StrategyAgent) -> None:
    allocated_capital = max(float(agent.starting_capital) + get_agent_capital_bonus(db, agent.slug), 1.0)
    current_value = max(agent.current_value, 0.0)
    agent.current_value = current_value
    agent.total_return_pct = compute_agent_twr(db, agent)
    agent.cash_buffer = round(agent.cash_buffer, 2)
    agent.performance_score = round(
        clamp(5.0 + ((agent.rolling_net_pnl / allocated_capital) * 25.0), 0.0, 10.0),
        2,
    )
    agent.survival_score = round(
        clamp(5.0 + ((current_value / allocated_capital) - 1.0) * 20.0, 0.0, 10.0),
        2,
    )


def agent_competition_score(db: Session, agent: StrategyAgent, benchmark_return_pct: float | None = None) -> float:
    allocated_capital = max(float(agent.starting_capital) + get_agent_capital_bonus(db, agent.slug), 1.0)
    excess_return_pct = agent_excess_return_pct(agent, benchmark_return_pct)
    rolling_pct = (agent.rolling_net_pnl / allocated_capital) * 100.0
    return (excess_return_pct * 0.55) + (rolling_pct * 0.25) + (agent.performance_score * 0.20)


def get_agent_positions(db: Session) -> list[AgentPosition]:
    return db.scalars(
        select(AgentPosition).where(AgentPosition.quantity > 0).order_by(AgentPosition.agent_slug, AgentPosition.symbol)
    ).all()


def get_agent_trades(db: Session, limit: int = 50) -> list[AgentTrade]:
    return db.scalars(select(AgentTrade).order_by(AgentTrade.created_at.desc()).limit(limit)).all()


def get_agent_cash(db: Session, agent: StrategyAgent) -> float:
    trades = db.scalars(select(AgentTrade).where(AgentTrade.agent_slug == agent.slug)).all()
    cash = float(agent.starting_capital) + get_agent_capital_bonus(db, agent.slug)
    for trade in trades:
        if trade.side == 'BUY':
            cash -= trade.notional
        elif trade.side == 'SELL':
            cash += trade.notional
    return round(cash, 2)


def get_agent_cash_history(db: Session, agent: StrategyAgent) -> list[dict[str, object]]:
    trades = db.scalars(
        select(AgentTrade)
        .where(AgentTrade.agent_slug == agent.slug)
        .order_by(AgentTrade.created_at.asc(), AgentTrade.id.asc())
    ).all()
    cash = float(agent.starting_capital) + get_agent_capital_bonus(db, agent.slug)
    points: list[dict[str, object]] = []

    for trade in trades:
        if trade.side == 'BUY':
            cash -= trade.notional
        elif trade.side == 'SELL':
            cash += trade.notional
        points.append({
            'cash': round(cash, 2),
            'recorded_at': trade.created_at,
        })

    current_cash = round(float(agent.cash_buffer), 2)
    current_at = agent.updated_at or (points[-1]['recorded_at'] if points else datetime.utcnow())

    if not points:
        return [{
            'cash': current_cash,
            'recorded_at': current_at,
        }]

    last = points[-1]
    if abs(float(last['cash']) - current_cash) > EPSILON or current_at > last['recorded_at']:
        points.append({
            'cash': current_cash,
            'recorded_at': current_at,
        })

    return points[-AGENT_CASH_HISTORY_LIMIT:]


def get_agent_holdings_history(db: Session, agent: StrategyAgent) -> list[dict[str, object]]:
    trades = db.scalars(
        select(AgentTrade)
        .where(AgentTrade.agent_slug == agent.slug)
        .order_by(AgentTrade.created_at.asc(), AgentTrade.id.asc())
    ).all()
    positions: dict[str, dict[str, float]] = {}
    points: list[dict[str, object]] = []

    for trade in trades:
        symbol = trade.symbol
        quantity = round(float(trade.quantity), 6)
        price = round(float(trade.price), 4)
        position = positions.setdefault(symbol, {'quantity': 0.0, 'average_cost': 0.0})

        if trade.side == 'BUY':
            new_quantity = position['quantity'] + quantity
            total_cost = (position['quantity'] * position['average_cost']) + (quantity * price)
            position['quantity'] = new_quantity
            position['average_cost'] = total_cost / new_quantity if new_quantity > EPSILON else 0.0
        elif trade.side == 'SELL':
            remaining_quantity = max(position['quantity'] - quantity, 0.0)
            position['quantity'] = remaining_quantity
            if remaining_quantity <= EPSILON:
                position['average_cost'] = 0.0

        holdings_value = round(
            sum(
                item['quantity'] * item['average_cost']
                for item in positions.values()
                if item['quantity'] > EPSILON
            ),
            2,
        )
        points.append({
            'holdings': holdings_value,
            'recorded_at': trade.created_at,
        })

    current_holdings = round(max(float(agent.current_value) - float(agent.cash_buffer), 0.0), 2)
    current_at = agent.updated_at or (points[-1]['recorded_at'] if points else datetime.utcnow())

    if not points:
        return [{
            'holdings': current_holdings,
            'recorded_at': current_at,
        }]

    last = points[-1]
    if abs(float(last['holdings']) - current_holdings) > EPSILON or current_at > last['recorded_at']:
        points.append({
            'holdings': current_holdings,
            'recorded_at': current_at,
        })

    return points[-AGENT_HOLDINGS_HISTORY_LIMIT:]


def get_latest_symbol_price(db: Session, symbol: str, fallback: float) -> float:
    broker_position = db.scalar(select(Position).where(Position.symbol == symbol))
    if broker_position is not None and broker_position.market_price > 0:
        return float(broker_position.market_price)

    latest_trade = db.scalars(
        select(AgentTrade).where(AgentTrade.symbol == symbol).order_by(AgentTrade.created_at.desc())
    ).first()
    if latest_trade is not None and latest_trade.price > 0:
        return float(latest_trade.price)
    return float(fallback)


def calculate_agent_window_metrics(
    db: Session,
    agent: StrategyAgent,
    holdings: list[AgentPosition],
    now: datetime,
) -> tuple[float, float, float, float]:
    cutoff = get_agent_window_cutoff(agent, now)
    trades = db.scalars(
        select(AgentTrade).where(AgentTrade.agent_slug == agent.slug, AgentTrade.created_at >= cutoff)
    ).all()
    realized_gains = sum(max(trade.realized_pl, 0.0) for trade in trades)
    realized_losses = sum(abs(min(trade.realized_pl, 0.0)) for trade in trades)
    unrealized_gain = sum(max(position.unrealized_pl, 0.0) for position in holdings)
    unrealized_loss = sum(abs(min(position.unrealized_pl, 0.0)) for position in holdings)
    rolling_gains = round(realized_gains + unrealized_gain, 2)
    rolling_losses = round(realized_losses + unrealized_loss, 2)
    rolling_unrealized = round(sum(position.unrealized_pl for position in holdings), 2)
    rolling_net_pnl = round(rolling_gains - rolling_losses, 2)
    return rolling_gains, rolling_losses, rolling_unrealized, rolling_net_pnl


def apply_trade_to_agent(
    db: Session,
    agent: StrategyAgent,
    *,
    order_id: str | None,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    notes: str = '',
    enforce_cash_limits: bool = True,
) -> AgentTrade:
    normalized_side = side.strip().upper()
    if normalized_side not in {'BUY', 'SELL'}:
        raise ValueError('Agent trade side must be BUY or SELL.')

    quantity = round(float(quantity), 6)
    price = round(float(price), 4)
    notional = round(quantity * price, 2)
    position = db.scalar(
        select(AgentPosition).where(
            AgentPosition.agent_slug == agent.slug,
            AgentPosition.symbol == symbol,
        )
    )
    available_cash = get_agent_cash(db, agent)
    realized_pl = 0.0

    if normalized_side == 'BUY':
        if enforce_cash_limits and notional > available_cash + EPSILON:
            raise ValueError(
                f'Agent `{agent.name}` only has {available_cash:.2f} in cash. Reduce size or wait for more capital.'
            )
        if position is None:
            position = AgentPosition(
                agent_slug=agent.slug,
                symbol=symbol,
                quantity=0.0,
                average_cost=0.0,
                market_price=price,
                market_value=0.0,
                realized_pl=0.0,
                unrealized_pl=0.0,
            )
            db.add(position)
            db.flush()

        existing_cost = position.quantity * position.average_cost
        new_quantity = position.quantity + quantity
        position.average_cost = round((existing_cost + notional) / new_quantity, 4)
        position.quantity = round(new_quantity, 6)
    else:
        if position is None or position.quantity + EPSILON < quantity:
            raise ValueError(
                f'Agent `{agent.name}` does not have enough {symbol} to sell {quantity:g} shares.'
            )
        realized_pl = round((price - position.average_cost) * quantity, 2)
        remaining_quantity = round(position.quantity - quantity, 6)
        position.quantity = remaining_quantity
        position.realized_pl = round(position.realized_pl + realized_pl, 2)
        if remaining_quantity <= EPSILON:
            db.delete(position)
            position = None

    trade = AgentTrade(
        agent_slug=agent.slug,
        order_id=order_id,
        symbol=symbol,
        side=normalized_side,
        quantity=quantity,
        price=price,
        notional=notional,
        realized_pl=realized_pl,
        notes=notes,
    )
    db.add(trade)
    db.flush()

    if position is not None:
        mark_price = get_latest_symbol_price(db, symbol, price)
        position.market_price = round(mark_price, 4)
        position.market_value = round(position.quantity * position.market_price, 2)
        position.unrealized_pl = round((position.market_price - position.average_cost) * position.quantity, 2)
        position.last_trade_at = datetime.utcnow()
        position.updated_at = datetime.utcnow()

    return trade


def _upsert_broker_reconciliation_alert(db: Session, failures: list[str]) -> None:
    alert = db.scalar(select(Alert).where(Alert.title == BROKER_RECONCILIATION_ALERT_TITLE))
    if not failures:
        if alert is not None and alert.is_active:
            alert.is_active = False
            alert.updated_at = datetime.utcnow()
        return

    message = 'Some filled broker orders could not be applied to the local agent ledger. '
    message += ' | '.join(failures[:3])
    if len(failures) > 3:
        message += f' | and {len(failures) - 3} more.'

    if alert is None:
        db.add(
            Alert(
                severity='warning',
                title=BROKER_RECONCILIATION_ALERT_TITLE,
                message=message,
                is_active=True,
            )
        )
        return

    alert.severity = 'warning'
    alert.message = message
    alert.is_active = True
    alert.updated_at = datetime.utcnow()

def sync_agent_trades_from_orders(db: Session, settings: Settings) -> list[AgentTrade]:
    filled_orders = db.scalars(
        select(BrokerOrder).where(
            BrokerOrder.agent_slug.is_not(None),
            BrokerOrder.filled_quantity > 0,
        ).order_by(BrokerOrder.created_at.asc(), BrokerOrder.updated_at.asc(), BrokerOrder.order_id.asc())
    ).all()
    created: list[AgentTrade] = []
    failures: list[str] = []
    for order in filled_orders:
        existing_trade = db.scalar(select(AgentTrade).where(AgentTrade.order_id == order.order_id))
        if existing_trade is not None:
            continue
        agent = db.get(StrategyAgent, order.agent_slug)
        if agent is None:
            continue
        fill_price = order.average_fill_price or order.price
        try:
            trade = apply_trade_to_agent(
                db,
                agent,
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.filled_quantity,
                price=fill_price,
                notes=order.remark or 'Broker-synced agent fill.',
                enforce_cash_limits=False,
            )
        except ValueError as exc:
            failures.append(f'{order.order_id} {order.side} {order.symbol}: {exc}')
            continue
        created.append(trade)
    _upsert_broker_reconciliation_alert(db, failures)
    if created or failures:
        refresh_strategy_game_state(db, settings, commit=False)
    return created


def refresh_strategy_game_state(db: Session, settings: Settings, *, commit: bool = True) -> list[StrategyAgent]:
    now = datetime.utcnow()
    broker_prices = {
        position.symbol: position.market_price
        for position in db.scalars(select(Position)).all()
        if position.market_price > 0
    }
    agent_positions = db.scalars(select(AgentPosition).order_by(AgentPosition.agent_slug, AgentPosition.symbol)).all()
    positions_by_agent: dict[str, list[AgentPosition]] = {}
    for agent_position in agent_positions:
        if agent_position.quantity <= EPSILON:
            db.delete(agent_position)
            continue
        mark_price = float(broker_prices.get(agent_position.symbol, agent_position.market_price or agent_position.average_cost))
        agent_position.market_price = round(mark_price, 4)
        agent_position.market_value = round(agent_position.quantity * agent_position.market_price, 2)
        agent_position.unrealized_pl = round(
            (agent_position.market_price - agent_position.average_cost) * agent_position.quantity,
            2,
        )
        agent_position.updated_at = now
        positions_by_agent.setdefault(agent_position.agent_slug, []).append(agent_position)

    agents = db.scalars(
        select(StrategyAgent).where(StrategyAgent.is_enabled.is_(True)).order_by(StrategyAgent.slug)
    ).all()
    if not agents:
        if commit:
            db.commit()
        return []

    trade_counts: dict[str, int] = {}
    for trade in db.scalars(select(AgentTrade)).all():
        trade_counts[trade.agent_slug] = trade_counts.get(trade.agent_slug, 0) + 1

    for agent in agents:
        holdings = positions_by_agent.get(agent.slug, [])
        cash_value = get_agent_cash(db, agent)
        market_value = round(sum(position.market_value for position in holdings), 2)
        agent.cash_buffer = round(cash_value, 2)
        agent.current_value = round(cash_value + market_value, 2)
        agent.rolling_gains, agent.rolling_losses, agent.rolling_unrealized, agent.rolling_net_pnl = calculate_agent_window_metrics(
            db,
            agent,
            holdings,
            now,
        )
        warmup_end_at = get_benchmark_warmup_end_at(agent)
        agent.elimination_ready_at = warmup_end_at
        agent.is_eligible_for_elimination = now >= warmup_end_at
        agent.last_scored_at = now
        update_agent_survival_state(db, agent)
        agent.updated_at = now

        if agent.current_value <= EPSILON:
            mark_agent_dead(
                agent,
                'Agent ran out of capital and can no longer trade.',
                trade_counts.get(agent.slug, 0),
            )
            continue

        revive_agent(agent)

    agents = rebalance_strategy_agents(db, settings, commit=False)
    for agent in agents:
        _append_agent_history_point(db, agent, now)
    if commit:
        db.commit()
    return agents


def rebalance_strategy_agents(db: Session, settings: Settings, *, commit: bool = True) -> list[StrategyAgent]:
    agents = db.scalars(
        select(StrategyAgent).where(StrategyAgent.is_enabled.is_(True)).order_by(StrategyAgent.slug)
    ).all()
    if not agents:
        return []

    benchmark_state = get_competition_benchmark_state(db, settings, refresh=False)
    benchmark_return_pct = benchmark_state['return_pct']
    alive = [agent for agent in agents if agent.is_alive]
    dead = [agent for agent in agents if not agent.is_alive]

    for agent in dead:
        agent.target_weight = 0.0
        agent.allocated_capital = 0.0
        agent.reward_multiplier = 0.0
        agent.is_winner = False
        agent.updated_at = datetime.utcnow()

    if not alive:
        if commit:
            db.commit()
        return sorted(agents, key=lambda agent: agent.slug)

    if len(alive) == 1:
        sole = alive[0]
        sole.is_winner = True
        sole.target_weight = round(sole.baseline_weight, 4)
        sole.allocated_capital = round(float(sole.starting_capital) + get_agent_capital_bonus(db, sole.slug), 2)
        sole.reward_multiplier = round(sole.allocated_capital / max(sole.starting_capital, 0.01), 2)
        sole.updated_at = datetime.utcnow()
        if commit:
            db.commit()
        return sorted(agents, key=lambda agent: (not agent.is_alive, not agent.is_winner, agent.slug))

    ranked = sorted(
        alive,
        key=lambda agent: (
            agent_competition_score(db, agent, benchmark_return_pct),
            agent_excess_return_pct(agent, benchmark_return_pct),
            agent.current_value,
        ),
        reverse=True,
    )
    winner = ranked[0]
    now = datetime.utcnow()

    for agent in alive:
        agent.is_winner = agent.slug == winner.slug
        agent.target_weight = round(agent.baseline_weight, 4)
        agent.allocated_capital = round(float(agent.starting_capital) + get_agent_capital_bonus(db, agent.slug), 2)
        agent.reward_multiplier = round(agent.allocated_capital / max(agent.starting_capital, 0.01), 2)
        agent.updated_at = now

    if commit:
        db.commit()
    return sorted(agents, key=lambda agent: (not agent.is_alive, not agent.is_winner, agent.slug))


def bootstrap_database(db: Session, settings: Settings) -> None:
    ensure_default_setting(db, 'app_mode', settings.app_mode)
    ensure_default_setting(db, 'agent_autopilot_enabled', 'true' if settings.agent_autopilot_enabled else 'false')
    ensure_default_setting(db, 'agent_autopilot_last_cycle_at', '')
    ensure_default_setting(db, 'agent_autopilot_last_summary', '')
    ensure_default_setting(db, LEADER_BONUS_RECIPIENT_KEY, '')
    ensure_default_setting(db, LEADER_BONUS_AMOUNT_KEY, '')
    _backfill_agent_bonus_totals(db)
    ensure_default_setting(db, 'competition_benchmark_symbol', settings.competition_benchmark_symbol)
    ensure_default_setting(db, 'competition_benchmark_start_price', '')
    ensure_default_setting(db, 'competition_benchmark_current_price', '')
    ensure_default_setting(db, 'competition_benchmark_last_updated_at', '')
    ensure_default_setting(db, BENCHMARK_START_AT_KEY, '')
    ensure_default_setting(db, BENCHMARK_HISTORY_KEY, '[]')
    benchmark_symbol = settings.competition_benchmark_symbol
    benchmark_rule_message = (
        f'Both agents compete for capital. The first 90 days are a warm-up. '
        f'After that, a monthly check against {benchmark_symbol} enforces the benchmark rule for each agent.'
    )
    bonus_recipient, bonus_amount = get_leader_bonus_award(db)
    if settings.moomoo_acc_id is not None and db.get(AppSetting, 'selected_acc_id') is None:
        db.add(AppSetting(key='selected_acc_id', value=str(settings.moomoo_acc_id)))

    themes = {
        'Pick-and-Shovel Growth': 'High-conviction US-listed bottleneck suppliers to AI, compute, networking, power, and infrastructure buildouts.',
        'Liberated US Stocks': 'Flexible US-stock agent allowed to own any compelling US-listed name as long as it beats the S&P 500 benchmark after the warm-up window.',
    }
    for name, thesis in themes.items():
        theme = db.scalar(select(Theme).where(Theme.name == name))
        if theme is None:
            db.add(Theme(name=name, thesis=thesis))

    if db.scalar(select(StrategyAgent).limit(1)) is None:
        half_bankroll = round(settings.risk_bankroll_cap * 0.5, 2)
        agent_rows = [
            {
                'slug': 'liberated-us-stocks',
                'name': 'Liberated US Stocks',
                'style': 'liberated',
                'mandate': 'Can buy any US-listed stock that offers better expected compounding than the specialist, with no thematic restriction beyond US equities.',
                'benchmark': settings.competition_benchmark_symbol,
                'allowed_universe': 'US_STOCKS',
                'starting_capital': half_bankroll,
                'cash_buffer': half_bankroll,
                'survival_floor': 0.0,
                'baseline_weight': 0.5,
                'min_weight': 0.0,
                'max_weight': 1.0,
                'target_weight': 0.5,
                'allocated_capital': half_bankroll,
                'current_value': half_bankroll,
                'total_return_pct': 0.0,
                'performance_score': 5.0,
                'survival_score': 5.0,
                'reward_multiplier': 1.0,
                'competition_window_days': 90,
                'rolling_gains': 0.0,
                'rolling_losses': 0.0,
                'rolling_unrealized': 0.0,
                'rolling_net_pnl': 0.0,
                'is_eligible_for_elimination': False,
                'is_winner': False,
                'is_alive': True,
                'notes': get_agent_note(
                    'liberated-us-stocks',
                    benchmark_symbol,
                    bonus_recipient=bonus_recipient,
                    bonus_amount=bonus_amount,
                ),
            },
            {
                'slug': 'pick-shovel-growth',
                'name': 'Pick-and-Shovel Growth',
                'style': 'specialist',
                'mandate': 'Own real bottlenecks inside the US stock market: compute, networking, power, cooling, and infrastructure chokepoints with durable pricing power.',
                'benchmark': settings.competition_benchmark_symbol,
                'allowed_universe': 'US_STOCKS',
                'starting_capital': half_bankroll,
                'cash_buffer': half_bankroll,
                'survival_floor': 0.0,
                'baseline_weight': 0.5,
                'min_weight': 0.0,
                'max_weight': 1.0,
                'target_weight': 0.5,
                'allocated_capital': half_bankroll,
                'current_value': half_bankroll,
                'total_return_pct': 0.0,
                'performance_score': 5.0,
                'survival_score': 5.0,
                'reward_multiplier': 1.0,
                'competition_window_days': 90,
                'rolling_gains': 0.0,
                'rolling_losses': 0.0,
                'rolling_unrealized': 0.0,
                'rolling_net_pnl': 0.0,
                'is_eligible_for_elimination': False,
                'is_winner': True,
                'is_alive': True,
                'notes': get_agent_note(
                    'pick-shovel-growth',
                    benchmark_symbol,
                    bonus_recipient=bonus_recipient,
                    bonus_amount=bonus_amount,
                ),
            },
        ]
        for row in agent_rows:
            db.add(StrategyAgent(is_enabled=True, **row))


    if db.scalar(select(Alert).limit(1)) is None:
        db.add(
            Alert(
                severity='info',
                title='90-day arena active',
                message=benchmark_rule_message,
            )
        )
        db.add(
            Alert(
                severity='warning',
                title='One account, two virtual agents',
                message='Agent-tagged orders now feed a local agent ledger, but custody and broker positions are still commingled in one moomoo account.',
            )
        )
        db.add(
            Alert(
                severity='warning',
                title='Regular-hours only',
                message='US paper trading on moomoo OpenAPI does not support irregular trading hours, so the app keeps fill_outside_rth disabled.',
            )
        )

    agent_overrides = {
        'pick-shovel-growth': {
            'style': 'specialist',
            'mandate': 'Own real bottlenecks inside the US stock market: compute, networking, power, cooling, and infrastructure chokepoints with durable pricing power.',
            'benchmark': settings.competition_benchmark_symbol,
            'allowed_universe': 'US_STOCKS',
            'competition_window_days': 90,
            'notes': get_agent_note(
                'pick-shovel-growth',
                benchmark_symbol,
                bonus_recipient=bonus_recipient,
                bonus_amount=bonus_amount,
            ),
        },
        'liberated-us-stocks': {
            'style': 'liberated',
            'mandate': 'Can buy any US-listed stock that offers better expected compounding than the specialist, with no thematic restriction beyond US equities.',
            'benchmark': settings.competition_benchmark_symbol,
            'allowed_universe': 'US_STOCKS',
            'competition_window_days': 90,
            'notes': get_agent_note(
                'liberated-us-stocks',
                benchmark_symbol,
                bonus_recipient=bonus_recipient,
                bonus_amount=bonus_amount,
            ),
        },
    }
    for slug, overrides in agent_overrides.items():
        existing_agent = db.get(StrategyAgent, slug)
        if existing_agent is None:
            continue
        for key, value in overrides.items():
            setattr(existing_agent, key, value)

    alert_overrides = {
        'Survival game active': ('90-day arena active', benchmark_rule_message),
        '90-day arena active': ('90-day arena active', benchmark_rule_message),
        'One account, two virtual players': ('One account, two virtual agents', 'Agent-tagged orders feed a local competition ledger, but custody and broker positions are still commingled in one moomoo account.'),
        'One account, two virtual agents': ('One account, two virtual agents', 'Agent-tagged orders feed a local competition ledger, but custody and broker positions are still commingled in one moomoo account.'),
    }
    for alert in db.scalars(select(Alert)).all():
        override = alert_overrides.get(alert.title)
        if override is None:
            continue
        alert.title = override[0]
        alert.message = override[1]

    db.commit()
    refresh_strategy_game_state(db, settings)


def get_strategy_agents(db: Session, settings: Settings) -> list[StrategyAgent]:
    refresh_strategy_game_state(db, settings)
    return db.scalars(
        select(StrategyAgent).order_by(StrategyAgent.is_alive.desc(), StrategyAgent.is_winner.desc(), StrategyAgent.slug)
    ).all()


def sync_broker_accounts(db: Session, adapter: BrokerAdapter) -> list[BrokerAccount]:
    accounts = adapter.list_accounts()
    selected_acc_id = None
    current_ids = {account.acc_id for account in accounts}

    for existing in db.scalars(select(BrokerAccount)).all():
        if existing.acc_id not in current_ids:
            db.delete(existing)

    for account in accounts:
        if account.is_selected:
            selected_acc_id = account.acc_id
        existing = db.get(BrokerAccount, account.acc_id)
        if existing is None:
            existing = BrokerAccount(
                acc_id=account.acc_id,
                trd_env=account.trd_env,
                acc_type=account.acc_type,
                security_firm=account.security_firm,
                sim_acc_type=account.sim_acc_type,
                uni_card_num=account.uni_card_num,
                card_num=account.card_num,
                is_selected=account.is_selected,
                raw_payload=json_dump(account.raw_payload or {}),
            )
            db.add(existing)
        else:
            existing.trd_env = account.trd_env
            existing.acc_type = account.acc_type
            existing.security_firm = account.security_firm
            existing.sim_acc_type = account.sim_acc_type
            existing.uni_card_num = account.uni_card_num
            existing.card_num = account.card_num
            existing.is_selected = account.is_selected
            existing.raw_payload = json_dump(account.raw_payload or {})

    if selected_acc_id is not None:
        set_setting_value(db, 'selected_acc_id', str(selected_acc_id))
    db.commit()
    return db.scalars(select(BrokerAccount).order_by(BrokerAccount.acc_id)).all()

def sync_positions(db: Session, adapter: BrokerAdapter) -> list[Position]:
    positions = adapter.list_positions()
    current_symbols = {position.symbol for position in positions}
    existing_positions = db.scalars(select(Position)).all()
    for existing in existing_positions:
        if existing.symbol not in current_symbols:
            db.delete(existing)
    for position in positions:
        existing = db.scalar(select(Position).where(Position.symbol == position.symbol))
        if existing is None:
            existing = Position(
                symbol=position.symbol,
                name=position.name,
                quantity=position.quantity,
                can_sell_quantity=position.can_sell_quantity,
                market_price=position.market_price,
                cost_price=position.cost_price,
                market_value=position.market_value,
                unrealized_pl=position.unrealized_pl,
                currency=position.currency,
                raw_payload=json_dump(position.raw_payload or {}),
            )
            db.add(existing)
        else:
            existing.name = position.name
            existing.quantity = position.quantity
            existing.can_sell_quantity = position.can_sell_quantity
            existing.market_price = position.market_price
            existing.cost_price = position.cost_price
            existing.market_value = position.market_value
            existing.unrealized_pl = position.unrealized_pl
            existing.currency = position.currency
            existing.raw_payload = json_dump(position.raw_payload or {})
            existing.updated_at = datetime.utcnow()
    db.commit()
    return db.scalars(select(Position).order_by(Position.market_value.desc())).all()


def sync_orders(db: Session, adapter: BrokerAdapter) -> list[BrokerOrder]:
    orders = adapter.list_recent_orders()
    cutoff = _get_broker_order_sync_cutoff()
    for order in orders:
        existing = db.get(BrokerOrder, order.order_id)
        recorded_at = _get_broker_order_timestamp(order) or datetime.utcnow()
        if cutoff is not None and recorded_at < cutoff:
            if existing is not None:
                db.delete(existing)
            continue
        if existing is None:
            db.add(
                BrokerOrder(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    agent_slug=None,
                    side=order.side,
                    order_type=order.order_type,
                    status=order.status,
                    quantity=order.quantity,
                    price=order.price,
                    filled_quantity=order.filled_quantity,
                    average_fill_price=order.average_fill_price,
                    trading_env=order.trading_env,
                    remark=order.remark,
                    raw_payload=json_dump(order.raw_payload or {}),
                    created_at=recorded_at,
                    updated_at=recorded_at,
                )
            )
        else:
            existing.symbol = order.symbol
            existing.side = order.side
            existing.order_type = order.order_type
            existing.status = order.status
            existing.quantity = order.quantity
            existing.price = order.price
            existing.filled_quantity = order.filled_quantity
            existing.average_fill_price = order.average_fill_price
            existing.trading_env = order.trading_env
            existing.remark = order.remark
            existing.raw_payload = json_dump(order.raw_payload or {})
            existing.updated_at = recorded_at
    db.commit()
    return db.scalars(select(BrokerOrder).order_by(BrokerOrder.updated_at.desc(), BrokerOrder.order_id.desc())).all()


def refresh_broker_state(db: Session, adapter: BrokerAdapter, settings: Settings) -> None:
    runtime_settings = get_runtime_settings(db, settings)
    sync_broker_accounts(db, adapter)
    sync_positions(db, adapter)
    sync_orders(db, adapter)
    sync_agent_trades_from_orders(db, settings)
    get_competition_benchmark_state(db, runtime_settings, refresh=True)
    refresh_strategy_game_state(db, settings)


def _broker_order_is_pending(order: BrokerOrder) -> bool:
    status = (order.status or '').upper()
    if any(fragment in status for fragment in FINAL_ORDER_STATUS_FRAGMENTS):
        return False
    if order.quantity > 0 and order.filled_quantity >= order.quantity:
        return False
    return True


def _preferred_execution_price(adapter: BrokerAdapter, symbol: str, side: str, fallback: float) -> float:
    try:
        quote = adapter.get_quote(symbol)
    except Exception:
        return round(max(float(fallback), 0.01), 2)

    normalized_side = side.strip().upper()
    if normalized_side == 'BUY':
        preferred = quote.ask_price or quote.last_price or quote.bid_price
    else:
        preferred = quote.bid_price or quote.last_price or quote.ask_price
    return round(max(float(preferred or fallback), 0.01), 2)


def _looks_like_broker_cash_error(message: str) -> bool:
    normalized = message.lower()
    return any(fragment in normalized for fragment in BROKER_CASH_ERROR_FRAGMENTS)


def _persist_broker_order_record(
    db: Session,
    *,
    agent: StrategyAgent,
    broker_order,
) -> BrokerOrder:
    order = BrokerOrder(
        order_id=broker_order.order_id,
        symbol=broker_order.symbol,
        agent_slug=agent.slug,
        side=broker_order.side,
        order_type=broker_order.order_type,
        status=broker_order.status,
        quantity=broker_order.quantity,
        price=broker_order.price,
        filled_quantity=broker_order.filled_quantity,
        average_fill_price=broker_order.average_fill_price,
        trading_env=broker_order.trading_env,
        remark=broker_order.remark,
        raw_payload=json_dump(broker_order.raw_payload or {}),
    )
    db.merge(order)
    db.flush()

    if (
        order.filled_quantity > 0
        and order.status.strip().upper() in FILLED_ORDER_STATUSES
        and db.scalar(select(AgentTrade).where(AgentTrade.order_id == order.order_id)) is None
    ):
        apply_trade_to_agent(
            db,
            agent,
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.filled_quantity,
            price=order.average_fill_price or order.price,
            notes=order.remark or 'Paper order fill recorded in agent ledger.',
            enforce_cash_limits=False,
        )

    return db.get(BrokerOrder, broker_order.order_id)


def _submit_agent_order(
    db: Session,
    adapter: BrokerAdapter,
    settings: Settings,
    ticket: PaperOrderTicket,
    *,
    refresh_state: bool,
) -> BrokerOrder:
    mode = get_active_mode(db, settings)
    if mode == 'paused':
        raise ValueError('App mode is paused. Switch to paper or live capped before submitting orders.')
    if mode not in {'paper', 'live_capped'}:
        raise ValueError(f'Unsupported app mode `{mode}` for order submission.')

    symbol = ticket.symbol.strip().upper()
    if not symbol.startswith(US_STOCK_PREFIX):
        raise ValueError('Both agents are limited to US-listed stocks. Use symbols like `US.NVDA`.')

    agent = db.get(StrategyAgent, ticket.agent_slug) if ticket.agent_slug else None
    if not ticket.agent_slug:
        raise ValueError('Agent-tagged orders are required so the competition ledger can track survival and bankroll allocation.')
    if agent is None:
        raise ValueError(f'Unknown agent `{ticket.agent_slug}`.')
    if not agent.is_alive:
        raise ValueError(f'Agent `{agent.name}` has already lost and can no longer trade.')
    if mode == 'live_capped':
        if settings.broker_backend.lower() == 'moomoo' and settings.moomoo_trd_env != 'REAL':
            raise ValueError('Live capped mode requires MOOMOO_LIVE_TRD_ENV=REAL.')
        if ticket.side.strip().upper() == 'BUY' and is_agent_cash_only(db, agent.slug):
            raise ValueError(f'Agent `{agent.name}` is locked to cash after trailing SPY at a monthly checkpoint.')

    execution_price = float(ticket.limit_price)
    if mode == 'live_capped':
        execution_price = _preferred_execution_price(adapter, symbol, ticket.side, execution_price)

    execution_ticket = PaperOrderTicket(
        symbol=symbol,
        agent_slug=agent.slug,
        quantity=ticket.quantity,
        limit_price=execution_price,
        side=ticket.side.strip().upper(),
        remark=ticket.remark,
    )

    if execution_ticket.side == 'BUY':
        available_cash = get_agent_cash(db, agent)
        order_cost = execution_ticket.quantity * execution_ticket.limit_price
        cash_tolerance = 0.0 if mode == 'live_capped' else EPSILON
        if order_cost > available_cash + cash_tolerance:
            raise ValueError(
                f'Agent `{agent.name}` does not have enough allocated cash for this order '
                f'(${order_cost:.2f} > ${available_cash:.2f}).'
            )

    try:
        broker_order = adapter.submit_paper_order(execution_ticket)
    except Exception as exc:
        if execution_ticket.side == 'BUY' and _looks_like_broker_cash_error(str(exc)):
            raise ValueError(
                'Broker account does not have enough cash or buying power to execute this buy order.'
            ) from exc
        raise
    order = _persist_broker_order_record(db, agent=agent, broker_order=broker_order)

    if refresh_state:
        get_competition_benchmark_state(db, settings, refresh=True)
        refresh_strategy_game_state(db, settings, commit=False)
        db.commit()
    return order


def _enforce_cash_only_agent(db: Session, adapter: BrokerAdapter, settings: Settings, agent: StrategyAgent) -> None:
    pending_sell_symbols: set[str] = set()
    pending_orders = db.scalars(select(BrokerOrder).where(BrokerOrder.agent_slug == agent.slug)).all()
    for order in pending_orders:
        if not _broker_order_is_pending(order):
            continue
        side = (order.side or '').upper()
        if side == 'SELL':
            pending_sell_symbols.add(order.symbol)
            continue
        if side == 'BUY':
            try:
                adapter.cancel_order(order.order_id)
            except Exception:
                continue
            order.status = 'CANCELLED'
            order.updated_at = datetime.utcnow()

    holdings = db.scalars(
        select(AgentPosition).where(AgentPosition.agent_slug == agent.slug, AgentPosition.quantity > EPSILON)
    ).all()
    for position in holdings:
        if position.symbol in pending_sell_symbols:
            continue
        try:
            _submit_agent_order(
                db,
                adapter,
                settings,
                PaperOrderTicket(
                    symbol=position.symbol,
                    agent_slug=agent.slug,
                    quantity=position.quantity,
                    limit_price=max(position.market_price, position.average_cost, 0.01),
                    side='SELL',
                    remark='Monthly SPY checkpoint forced this agent to hold cash only.',
                ),
                refresh_state=False,
            )
        except Exception:
            continue


def submit_paper_order(db: Session, adapter: BrokerAdapter, settings: Settings, ticket: PaperOrderTicket) -> BrokerOrder:
    return _submit_agent_order(db, adapter, settings, ticket, refresh_state=True)


StrategySleeve = StrategyAgent
SleevePosition = AgentPosition
SleeveTrade = AgentTrade
update_sleeve_survival_state = update_agent_survival_state
sleeve_competition_score = agent_competition_score
get_sleeve_positions = get_agent_positions
get_sleeve_trades = get_agent_trades
get_sleeve_cash = get_agent_cash
apply_trade_to_sleeve = apply_trade_to_agent
sync_sleeve_trades_from_orders = sync_agent_trades_from_orders
rebalance_strategy_sleeves = rebalance_strategy_agents
get_strategy_sleeves = get_strategy_agents







