from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker.base import PaperOrderTicket
from app.core.config import Settings
from app.models.entities import AgentPosition
from app.models.entities import BrokerOrder
from app.models.entities import Decision
from app.models.entities import StrategyAgent
from app.services.quotes import get_quote_record
from app.services.research import refresh_live_research
from app.services.trading import bootstrap_database
from app.services.trading import build_broker_adapter
from app.services.trading import get_active_mode
from app.services.trading import get_agent_cash
from app.services.trading import get_live_capped_agent_slug
from app.services.trading import get_runtime_settings
from app.services.trading import get_setting_value
from app.services.trading import refresh_broker_state
from app.services.trading import set_setting_value
from app.services.trading import submit_paper_order

FINAL_STATUS_FRAGMENTS = ('CANCEL', 'FAIL', 'REJECT', 'DELETE', 'DISABLE')


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def get_autopilot_enabled(db: Session, settings: Settings) -> bool:
    raw = get_setting_value(db, 'agent_autopilot_enabled', 'true' if settings.agent_autopilot_enabled else 'false')
    return _parse_bool(raw)


def set_autopilot_enabled(db: Session, enabled: bool) -> None:
    set_setting_value(db, 'agent_autopilot_enabled', 'true' if enabled else 'false')
    db.commit()


def get_autopilot_status(db: Session, settings: Settings) -> dict[str, object]:
    last_cycle_raw = get_setting_value(db, 'agent_autopilot_last_cycle_at', '')
    last_summary = get_setting_value(db, 'agent_autopilot_last_summary', '') or None
    last_cycle_at = None
    if last_cycle_raw:
        try:
            last_cycle_at = datetime.fromisoformat(last_cycle_raw)
        except ValueError:
            last_cycle_at = None
    return {
        'enabled': get_autopilot_enabled(db, settings),
        'interval_seconds': settings.agent_autopilot_interval_seconds,
        'max_orders_per_cycle': settings.agent_max_orders_per_cycle,
        'take_profit_pct': settings.agent_take_profit_pct,
        'stop_loss_pct': settings.agent_stop_loss_pct,
        'last_cycle_at': last_cycle_at,
        'last_summary': last_summary,
    }


def _has_pending_order(order: BrokerOrder) -> bool:
    status = (order.status or '').upper()
    if any(fragment in status for fragment in FINAL_STATUS_FRAGMENTS):
        return False
    if order.quantity > 0 and order.filled_quantity >= order.quantity:
        return False
    return True


def _position_pnl_pct(position: AgentPosition, mark_price: float) -> float:
    if position.average_cost <= 0:
        return 0.0
    return ((mark_price - position.average_cost) / position.average_cost) * 100.0


def _agent_slot_limit(settings: Settings, agent: StrategyAgent) -> int:
    specialist_limit = 2
    liberated_limit = min(4, settings.risk_max_open_positions)
    if agent.slug == 'pick-shovel-growth':
        return specialist_limit
    return liberated_limit


def _research_decisions_by_agent(db: Session) -> dict[str, list[Decision]]:
    rows = db.scalars(
        select(Decision)
        .where(Decision.status.in_(['research-buy', 'research-hold']))
        .order_by(Decision.strategy_slug, Decision.conviction_score.desc())
    ).all()
    grouped: dict[str, list[Decision]] = {}
    for row in rows:
        grouped.setdefault(row.strategy_slug, []).append(row)
    return grouped


def _sell_position(
    db: Session,
    adapter,
    settings: Settings,
    agent: StrategyAgent,
    position: AgentPosition,
    remark: str,
) -> BrokerOrder:
    sell_price = round(position.market_price, 2)
    return submit_paper_order(
        db,
        adapter,
        settings,
        PaperOrderTicket(
            symbol=position.symbol,
            agent_slug=agent.slug,
            quantity=position.quantity,
            limit_price=max(sell_price, 0.01),
            side='SELL',
            remark=remark,
        ),
    )


def run_agent_autopilot_cycle(db: Session, settings: Settings, *, force: bool = False) -> dict[str, object]:
    bootstrap_database(db, settings)
    enabled = get_autopilot_enabled(db, settings)
    now = datetime.utcnow()

    if not enabled and not force:
        result = {
            'enabled': False,
            'executed_orders': 0,
            'events': ['Autopilot is disabled.'],
            'last_cycle_at': now,
        }
        set_setting_value(db, 'agent_autopilot_last_cycle_at', now.isoformat())
        set_setting_value(db, 'agent_autopilot_last_summary', result['events'][0])
        db.commit()
        return result

    mode = get_active_mode(db, settings)
    if mode not in {'paper', 'live_capped'}:
        result = {
            'enabled': True,
            'executed_orders': 0,
            'events': [f'Autopilot only runs in paper or live capped mode. Current mode is {mode}.'],
            'last_cycle_at': now,
        }
        set_setting_value(db, 'agent_autopilot_last_cycle_at', now.isoformat())
        set_setting_value(db, 'agent_autopilot_last_summary', result['events'][0])
        db.commit()
        return result

    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    refresh_broker_state(db, adapter, settings)

    alive_agents = db.scalars(
        select(StrategyAgent)
        .where(StrategyAgent.is_enabled.is_(True), StrategyAgent.is_alive.is_(True))
        .order_by(StrategyAgent.is_winner.desc(), StrategyAgent.slug.asc())
    ).all()
    if mode == 'live_capped':
        allowed_slug = get_live_capped_agent_slug(runtime_settings)
        alive_agents = [agent for agent in alive_agents if agent.slug == allowed_slug]
        if not alive_agents:
            result = {
                'enabled': True,
                'executed_orders': 0,
                'events': ['Live capped mode only trades Pick-and-Shovel, but that agent is not currently eligible.'],
                'last_cycle_at': now,
            }
            set_setting_value(db, 'agent_autopilot_last_cycle_at', now.isoformat())
            set_setting_value(db, 'agent_autopilot_last_summary', result['events'][0])
            db.commit()
            return result

    refresh_live_research(db, runtime_settings, agents=alive_agents)
    research_by_agent = _research_decisions_by_agent(db)

    positions = db.scalars(
        select(AgentPosition).where(AgentPosition.quantity > 0).order_by(AgentPosition.agent_slug, AgentPosition.symbol)
    ).all()
    positions_by_agent: dict[str, list[AgentPosition]] = {}
    for position in positions:
        positions_by_agent.setdefault(position.agent_slug, []).append(position)

    pending_symbols_by_agent: dict[str, set[str]] = {}
    for order in db.scalars(select(BrokerOrder).where(BrokerOrder.agent_slug.is_not(None))).all():
        if not _has_pending_order(order):
            continue
        pending_symbols_by_agent.setdefault(order.agent_slug or '', set()).add(order.symbol)

    events: list[str] = []
    executed_orders = 0
    max_orders = max(1, settings.agent_max_orders_per_cycle)

    for agent in alive_agents:
        if executed_orders >= max_orders:
            break

        agent_positions = positions_by_agent.get(agent.slug, [])
        pending_symbols = pending_symbols_by_agent.setdefault(agent.slug, set())
        decisions = research_by_agent.get(agent.slug, [])
        decision_by_symbol = {decision.symbol: decision for decision in decisions}

        exited = False
        for position in sorted(agent_positions, key=lambda item: item.unrealized_pl):
            if position.symbol in pending_symbols:
                continue

            if agent.slug == 'liberated-us-stocks':
                hold_decision = decision_by_symbol.get(position.symbol)
                should_exit = hold_decision is None or hold_decision.status not in {'research-buy', 'research-hold'}
                if should_exit:
                    order = _sell_position(
                        db,
                        adapter,
                        runtime_settings,
                        agent,
                        position,
                        'liberated-agent thesis exit',
                    )
                    executed_orders += 1
                    pending_symbols.add(position.symbol)
                    events.append(
                        f'{agent.name} sold {position.symbol} because current research no longer supports the position at {order.price:.2f}.'
                    )
                    exited = True
                    break
                continue

            pnl_pct = _position_pnl_pct(position, position.market_price)
            should_take_profit = pnl_pct >= settings.agent_take_profit_pct
            should_stop_loss = pnl_pct <= -abs(settings.agent_stop_loss_pct)
            if not should_take_profit and not should_stop_loss:
                continue
            order = _sell_position(
                db,
                adapter,
                runtime_settings,
                agent,
                position,
                'pick-shovel constrained exit',
            )
            executed_orders += 1
            pending_symbols.add(position.symbol)
            trigger = 'take-profit' if should_take_profit else 'stop-loss'
            events.append(f'{agent.name} sold {position.symbol} via {trigger} at {order.price:.2f}.')
            exited = True
            break

        if exited or executed_orders >= max_orders:
            continue

        slot_limit = _agent_slot_limit(runtime_settings, agent)
        if len(agent_positions) >= slot_limit:
            continue

        cash = get_agent_cash(db, agent)
        held_symbols = {position.symbol for position in agent_positions}
        buy_candidates = [decision for decision in decisions if decision.status == 'research-buy']

        for decision in buy_candidates:
            if executed_orders >= max_orders:
                break
            if decision.symbol in held_symbols or decision.symbol in pending_symbols:
                continue
            if decision.max_notional <= 0 or cash <= 0:
                continue
            try:
                quote = get_quote_record(runtime_settings, decision.symbol)
                price_hint = round(quote.ask_price or quote.last_price, 2)
            except Exception:
                continue
            if price_hint <= 0:
                continue
            target_budget = min(
                decision.max_notional,
                cash,
                max(agent.allocated_capital * decision.target_weight, price_hint),
            )
            quantity = int(target_budget // price_hint)
            if quantity < 1:
                continue
            order = submit_paper_order(
                db,
                adapter,
                runtime_settings,
                PaperOrderTicket(
                    symbol=decision.symbol,
                    agent_slug=agent.slug,
                    quantity=float(quantity),
                    limit_price=price_hint,
                    side='BUY',
                    remark=f'{agent.slug} research-driven entry',
                ),
            )
            executed_orders += 1
            pending_symbols.add(decision.symbol)
            events.append(f'{agent.name} bought {decision.symbol} x{quantity} from fresh research at {order.price:.2f}.')
            break

    if not events:
        events.append('Autopilot refreshed research for both agents and found no safe trades this cycle.')

    set_setting_value(db, 'agent_autopilot_last_cycle_at', now.isoformat())
    set_setting_value(db, 'agent_autopilot_last_summary', ' | '.join(events[:3]))
    db.commit()
    return {
        'enabled': True,
        'executed_orders': executed_orders,
        'events': events,
        'last_cycle_at': now,
    }
