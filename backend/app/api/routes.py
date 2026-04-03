from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.broker.base import PaperOrderTicket
from app.core.config import Settings
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import Alert
from app.models.entities import BrokerAccount
from app.models.entities import BrokerOrder
from app.models.entities import Company
from app.models.entities import Decision
from app.models.entities import Position
from app.schemas.api import AgentCashPointResponse
from app.schemas.api import AgentHoldingsPointResponse
from app.schemas.api import AgentPositionResponse
from app.schemas.api import AgentResponse
from app.schemas.api import AgentHistoryPointResponse
from app.schemas.api import AgentTradeResponse
from app.schemas.api import AlertResponse
from app.schemas.api import AutopilotCycleResponse
from app.schemas.api import AutopilotStatusResponse
from app.schemas.api import AutopilotToggleRequest
from app.schemas.api import BrokerAccountResponse
from app.schemas.api import BrokerHealthResponse
from app.schemas.api import BrokerOrderResponse
from app.schemas.api import CompanyResponse
from app.schemas.api import DashboardOverviewResponse
from app.schemas.api import DecisionResponse
from app.schemas.api import HealthResponse
from app.schemas.api import ModeUpdateRequest
from app.schemas.api import PaperOrderRequest
from app.schemas.api import PositionResponse
from app.schemas.api import QuoteResponse
from app.schemas.api import ResearchNoteResponse
from app.schemas.api import ResearchRefreshResponse
from app.schemas.api import SettingsResponse
from app.services.quotes import get_quote_record
from app.services.research import get_research_notes
from app.services.research import refresh_live_research
from app.services.trading import bootstrap_database
from app.services.trading import build_broker_adapter
from app.services.trading import get_active_mode
from app.services.trading import get_agent_cash_history
from app.services.trading import get_agent_history
from app.services.trading import get_agent_holdings_history
from app.services.trading import get_agent_positions
from app.services.trading import get_competition_benchmark_state
from app.services.trading import get_agent_trades
from app.services.trading import get_live_capped_agent_slug
from app.services.trading import get_runtime_settings
from app.services.trading import get_selected_account_id
from app.services.trading import get_strategy_agents
from app.services.trading import refresh_broker_state
from app.services.trading import refresh_strategy_game_state
from app.services.trading import set_setting_value
from app.services.trading import submit_paper_order
from app.services.trading import sync_broker_accounts
from app.services.trading import sync_orders
from app.services.trading import sync_positions
from app.strategy.engine import get_autopilot_status
from app.strategy.engine import run_agent_autopilot_cycle
from app.strategy.engine import set_autopilot_enabled

router = APIRouter()


def map_health(settings: Settings, db: Session) -> HealthResponse:
    return HealthResponse(
        app_name=settings.app_name,
        env=settings.app_env,
        mode=get_active_mode(db, settings),
        version=settings.api_version,
        server_time=datetime.utcnow(),
    )


def map_broker_health(settings: Settings, db: Session) -> BrokerHealthResponse:
    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    health = adapter.health_check()
    return BrokerHealthResponse(**asdict(health))


def map_dashboard_broker_health(settings: Settings, db: Session) -> BrokerHealthResponse:
    runtime_settings = get_runtime_settings(db, settings)
    if runtime_settings.broker_backend.lower() == 'mock':
        return map_broker_health(settings, db)

    accounts = db.scalars(select(BrokerAccount).order_by(BrokerAccount.updated_at.desc())).all()
    selected_acc_id = get_selected_account_id(db, settings)
    warnings = [
        'Dashboard uses cached broker state on initial load.',
        'Use Refresh Broker State to query OpenD live.',
    ]
    status = 'idle'
    message = 'No broker sync yet. Press Refresh Broker State after OpenD is running.'
    is_reachable = False
    is_authenticated = False

    if accounts:
        latest = accounts[0]
        status = 'cached'
        message = f'Showing last synced broker state from {latest.updated_at.isoformat()}.'
        is_reachable = True
        is_authenticated = True

    return BrokerHealthResponse(
        backend=settings.broker_backend,
        status=status,
        message=message,
        is_reachable=is_reachable,
        is_authenticated=is_authenticated,
        environment=runtime_settings.moomoo_trd_env,
        selected_acc_id=selected_acc_id,
        warnings=warnings,
        account_summary={},
        checked_at=datetime.utcnow(),
    )


def map_settings(settings: Settings, db: Session) -> SettingsResponse:
    runtime_settings = get_runtime_settings(db, settings)
    autopilot = get_autopilot_status(db, settings)
    benchmark = get_competition_benchmark_state(db, settings, refresh=False)
    return SettingsResponse(
        app_mode=get_active_mode(db, settings),
        broker_backend=settings.broker_backend,
        quote_provider=settings.quote_provider,
        broker_environment=runtime_settings.moomoo_trd_env,
        selected_acc_id=get_selected_account_id(db, settings),
        agent_autopilot_enabled=bool(autopilot['enabled']),
        agent_autopilot_interval_seconds=settings.agent_autopilot_interval_seconds,
        agent_max_orders_per_cycle=settings.agent_max_orders_per_cycle,
        agent_take_profit_pct=settings.agent_take_profit_pct,
        agent_stop_loss_pct=settings.agent_stop_loss_pct,
        agent_autopilot_last_cycle_at=autopilot['last_cycle_at'],
        agent_autopilot_last_summary=autopilot['last_summary'],
        competition_benchmark_symbol=str(benchmark['symbol']),
        competition_benchmark_start_price=benchmark['start_price'],
        competition_benchmark_current_price=benchmark['current_price'],
        competition_benchmark_return_pct=benchmark['return_pct'],
        competition_benchmark_last_updated_at=benchmark['last_updated_at'],
        competition_benchmark_history=benchmark['history'],
        research_enabled=settings.research_enabled,
        research_max_symbols_per_agent=settings.research_max_symbols_per_agent,
        research_max_generated_decisions_per_agent=settings.research_max_generated_decisions_per_agent,
        research_min_buy_score=settings.research_min_buy_score,
        research_min_hold_score=settings.research_min_hold_score,
        risk_bankroll_cap=settings.risk_bankroll_cap,
        risk_max_order_notional=runtime_settings.risk_max_order_notional,
        risk_max_open_positions=settings.risk_max_open_positions,
        risk_max_positions_per_theme=settings.risk_max_positions_per_theme,
        risk_daily_loss_limit=settings.risk_daily_loss_limit,
    )


def map_agent(agent, db: Session) -> AgentResponse:
    base = AgentResponse.model_validate(agent, from_attributes=True)
    history = [AgentHistoryPointResponse.model_validate(point) for point in get_agent_history(db, agent.slug)]
    cash_history = [AgentCashPointResponse.model_validate(point) for point in get_agent_cash_history(db, agent)]
    holdings_history = [AgentHoldingsPointResponse.model_validate(point) for point in get_agent_holdings_history(db, agent)]
    return base.model_copy(update={'history': history, 'cash_history': cash_history, 'holdings_history': holdings_history})


@router.get('/health', response_model=HealthResponse)
def get_health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> HealthResponse:
    bootstrap_database(db, settings)
    return map_health(settings, db)


@router.get('/broker/health', response_model=BrokerHealthResponse)
def get_broker_health(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> BrokerHealthResponse:
    bootstrap_database(db, settings)
    return map_broker_health(settings, db)


@router.get('/broker/accounts', response_model=list[BrokerAccountResponse])
def get_broker_accounts(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[BrokerAccountResponse]:
    bootstrap_database(db, settings)
    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    try:
        accounts = sync_broker_accounts(db, adapter)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [BrokerAccountResponse.model_validate(account, from_attributes=True) for account in accounts]


@router.get('/quotes/{symbol}', response_model=QuoteResponse)
def get_quote(symbol: str, settings: Settings = Depends(get_settings)) -> QuoteResponse:
    try:
        quote = get_quote_record(settings, symbol)
    except Exception as exc:
        message = str(exc)
        if 'No right to get the quote' in message or 'No right to subscribe the quote' in message:
            raise HTTPException(
                status_code=403,
                detail=(
                    'moomoo OpenAPI denied US quote access for this account. '
                    'Switch QUOTE_PROVIDER to twelvedata or enter the limit price manually.'
                ),
            ) from exc
        if 'ALPACA_DATA_API_KEY / ALPACA_DATA_SECRET are missing' in message:
            raise HTTPException(status_code=400, detail=message) from exc
        if 'TWELVEDATA_API_KEY is missing' in message:
            raise HTTPException(status_code=400, detail=message) from exc
        if 'Alpaca quote request failed: HTTP 401' in message or 'Alpaca quote request failed: HTTP 403' in message:
            raise HTTPException(status_code=403, detail='Alpaca market-data credentials were rejected.') from exc
        if 'Twelve Data quote request failed: HTTP 401' in message or 'Twelve Data quote request failed: HTTP 403' in message:
            raise HTTPException(status_code=403, detail='Twelve Data credentials were rejected or the plan lacks access.') from exc
        raise HTTPException(status_code=502, detail=message) from exc
    return QuoteResponse.model_validate(quote, from_attributes=True)


@router.get('/agents', response_model=list[AgentResponse])
def get_agents(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[AgentResponse]:
    bootstrap_database(db, settings)
    agents = get_strategy_agents(db, settings)
    return [map_agent(agent, db) for agent in agents]


@router.get('/sleeves', response_model=list[AgentResponse])
def get_sleeves(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[AgentResponse]:
    return get_agents(db, settings)


@router.get('/agent/positions', response_model=list[AgentPositionResponse])
def get_agent_positions_view(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[AgentPositionResponse]:
    bootstrap_database(db, settings)
    refresh_strategy_game_state(db, settings)
    positions = get_agent_positions(db)
    return [AgentPositionResponse.model_validate(position, from_attributes=True) for position in positions]


@router.get('/sleeve/positions', response_model=list[AgentPositionResponse])
def get_sleeve_positions_view(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[AgentPositionResponse]:
    return get_agent_positions_view(db, settings)


@router.get('/agent/trades', response_model=list[AgentTradeResponse])
def get_agent_trades_view(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[AgentTradeResponse]:
    bootstrap_database(db, settings)
    trades = get_agent_trades(db)
    return [AgentTradeResponse.model_validate(trade, from_attributes=True) for trade in trades]


@router.get('/sleeve/trades', response_model=list[AgentTradeResponse])
def get_sleeve_trades_view(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[AgentTradeResponse]:
    return get_agent_trades_view(db, settings)


@router.get('/research/notes', response_model=list[ResearchNoteResponse])
def get_research_notes_view(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[ResearchNoteResponse]:
    bootstrap_database(db, settings)
    notes = get_research_notes(db)
    return [ResearchNoteResponse.model_validate(note, from_attributes=True) for note in notes]


@router.post('/research/run', response_model=ResearchRefreshResponse)
def post_research_run(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ResearchRefreshResponse:
    bootstrap_database(db, settings)
    runtime_settings = get_runtime_settings(db, settings)
    agents = get_strategy_agents(db, settings)
    if get_active_mode(db, settings) == 'live_capped':
        allowed_slug = get_live_capped_agent_slug(runtime_settings)
        agents = [agent for agent in agents if agent.slug == allowed_slug]
    generated = refresh_live_research(db, runtime_settings, agents=agents)
    decisions = db.scalars(select(Decision)).all()
    notes = get_research_notes(db, limit=500)
    return ResearchRefreshResponse(
        generated_agents=len(generated),
        generated_decisions=len(decisions),
        generated_notes=len(notes),
        refreshed_at=datetime.utcnow(),
    )


@router.post('/broker/test', response_model=DashboardOverviewResponse)
def post_broker_test(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> DashboardOverviewResponse:
    bootstrap_database(db, settings)
    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    try:
        refresh_broker_state(db, adapter, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return get_dashboard_overview(db, settings)


@router.get('/agents/autopilot', response_model=AutopilotStatusResponse)
def get_agents_autopilot(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AutopilotStatusResponse:
    bootstrap_database(db, settings)
    return AutopilotStatusResponse(**get_autopilot_status(db, settings))


@router.post('/agents/autopilot', response_model=AutopilotStatusResponse)
def post_agents_autopilot(
    payload: AutopilotToggleRequest,
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AutopilotStatusResponse:
    bootstrap_database(db, settings)
    set_autopilot_enabled(db, payload.enabled)
    return AutopilotStatusResponse(**get_autopilot_status(db, settings))


@router.post('/agents/cycle', response_model=AutopilotCycleResponse)
def post_agents_cycle(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AutopilotCycleResponse:
    try:
        result = run_agent_autopilot_cycle(db, settings, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AutopilotCycleResponse(**result)


@router.get('/positions', response_model=list[PositionResponse])
def get_positions(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[PositionResponse]:
    bootstrap_database(db, settings)
    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    try:
        positions = sync_positions(db, adapter)
        refresh_strategy_game_state(db, settings)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [PositionResponse.model_validate(position, from_attributes=True) for position in positions]


@router.get('/orders', response_model=list[BrokerOrderResponse])
def get_orders(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> list[BrokerOrderResponse]:
    bootstrap_database(db, settings)
    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    try:
        orders = sync_orders(db, adapter)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [BrokerOrderResponse.model_validate(order, from_attributes=True) for order in orders]


@router.post('/orders/paper', response_model=BrokerOrderResponse)
def post_paper_order(
    payload: PaperOrderRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BrokerOrderResponse:
    bootstrap_database(db, settings)
    runtime_settings = get_runtime_settings(db, settings)
    adapter = build_broker_adapter(runtime_settings)
    ticket = PaperOrderTicket(
        symbol=payload.symbol.strip().upper(),
        agent_slug=payload.agent_slug,
        quantity=payload.quantity,
        limit_price=payload.limit_price,
        side=payload.side.strip().upper(),
        remark=payload.remark,
    )
    try:
        order = submit_paper_order(db, adapter, runtime_settings, ticket)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BrokerOrderResponse.model_validate(order, from_attributes=True)


@router.get('/decisions', response_model=list[DecisionResponse])
def get_decisions(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[DecisionResponse]:
    bootstrap_database(db, settings)
    decisions = db.scalars(
        select(Decision).order_by(Decision.strategy_name.asc(), Decision.conviction_score.desc())
    ).all()
    return [DecisionResponse.model_validate(decision, from_attributes=True) for decision in decisions]


@router.get('/themes', response_model=list[CompanyResponse])
def get_themes(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[CompanyResponse]:
    bootstrap_database(db, settings)
    companies = db.scalars(select(Company).order_by(Company.total_score.desc())).all()
    return [CompanyResponse.model_validate(company, from_attributes=True) for company in companies]


@router.get('/settings', response_model=SettingsResponse)
def get_settings_view(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SettingsResponse:
    bootstrap_database(db, settings)
    return map_settings(settings, db)


@router.post('/mode', response_model=SettingsResponse)
def post_mode(
    payload: ModeUpdateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SettingsResponse:
    bootstrap_database(db, settings)
    valid_modes = {'paused', 'paper', 'live_capped'}
    if payload.mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f'Mode must be one of {sorted(valid_modes)}')
    set_setting_value(db, 'app_mode', payload.mode)
    db.commit()
    return map_settings(settings, db)


@router.get('/dashboard/overview', response_model=DashboardOverviewResponse)
def get_dashboard_overview(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> DashboardOverviewResponse:
    bootstrap_database(db, settings)
    refresh_strategy_game_state(db, settings)

    agents = get_strategy_agents(db, settings)
    agent_positions = get_agent_positions(db)
    agent_trades = get_agent_trades(db, limit=10)
    research_notes = get_research_notes(db)
    accounts = db.scalars(select(BrokerAccount).order_by(BrokerAccount.acc_id)).all()
    positions = db.scalars(select(Position).order_by(Position.market_value.desc())).all()
    orders = db.scalars(select(BrokerOrder).order_by(BrokerOrder.updated_at.desc()).limit(10)).all()
    decisions = db.scalars(
        select(Decision).order_by(Decision.strategy_name.asc(), Decision.conviction_score.desc())
    ).all()
    companies = db.scalars(select(Company).order_by(Company.total_score.desc())).all()
    alerts = db.scalars(select(Alert).where(Alert.is_active.is_(True)).order_by(Alert.created_at.desc())).all()
    return DashboardOverviewResponse(
        health=map_health(settings, db),
        broker_health=map_dashboard_broker_health(settings, db),
        accounts=[BrokerAccountResponse.model_validate(account, from_attributes=True) for account in accounts],
        agents=[map_agent(agent, db) for agent in agents],
        agent_positions=[AgentPositionResponse.model_validate(position, from_attributes=True) for position in agent_positions],
        agent_trades=[AgentTradeResponse.model_validate(trade, from_attributes=True) for trade in agent_trades],
        research_notes=[ResearchNoteResponse.model_validate(note, from_attributes=True) for note in research_notes],
        positions=[PositionResponse.model_validate(position, from_attributes=True) for position in positions],
        orders=[BrokerOrderResponse.model_validate(order, from_attributes=True) for order in orders],
        decisions=[DecisionResponse.model_validate(decision, from_attributes=True) for decision in decisions],
        companies=[CompanyResponse.model_validate(company, from_attributes=True) for company in companies],
        alerts=[AlertResponse.model_validate(alert, from_attributes=True) for alert in alerts],
        settings=map_settings(settings, db),
    )
