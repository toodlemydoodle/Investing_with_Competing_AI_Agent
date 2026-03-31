from sqlalchemy import select

from app.broker.base import PaperOrderTicket
from app.broker.mock import MockBrokerAdapter
from app.core.config import Settings
from app.db.session import Base
from app.db.session import SessionLocal
from app.db.session import engine
from app.models.entities import AgentPosition
from app.models.entities import AgentTrade
from app.models.entities import Company
from app.models.entities import Decision
from app.models.entities import StrategyAgent
from app.services.research import refresh_live_research
from app.services.trading import bootstrap_database
from app.services.trading import submit_paper_order
from app.strategy.engine import run_agent_autopilot_cycle


def reset_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)



def test_bootstrap_inserts_seed_data() -> None:
    reset_schema()
    with SessionLocal() as db:
        bootstrap_database(db, Settings(broker_backend='mock', quote_provider='mock'))
        assert db.scalar(select(Company.id).limit(1)) is not None
        assert db.scalar(select(StrategyAgent.slug).limit(1)) is not None



def test_agent_order_creates_ledger_entries() -> None:
    reset_schema()
    settings = Settings(broker_backend='mock', quote_provider='mock')
    adapter = MockBrokerAdapter(settings)

    with SessionLocal() as db:
        bootstrap_database(db, settings)
        order = submit_paper_order(
            db,
            adapter,
            settings,
            PaperOrderTicket(
                symbol='US.NVDA',
                agent_slug='pick-shovel-growth',
                quantity=1,
                limit_price=100,
                side='BUY',
                remark='test buy',
            ),
        )

        agent = db.get(StrategyAgent, 'pick-shovel-growth')
        trade = db.scalar(select(AgentTrade).where(AgentTrade.order_id == order.order_id))
        position = db.scalar(
            select(AgentPosition).where(
                AgentPosition.agent_slug == 'pick-shovel-growth',
                AgentPosition.symbol == 'US.NVDA',
            )
        )

        assert order.status == 'FILLED'
        assert trade is not None
        assert position is not None
        assert position.quantity == 1
        assert agent is not None
        assert agent.cash_buffer == 400.0
        assert agent.current_value == 500.0



def test_research_refresh_generates_live_research_decisions() -> None:
    reset_schema()
    settings = Settings(broker_backend='mock', quote_provider='mock')

    with SessionLocal() as db:
        bootstrap_database(db, settings)
        generated = refresh_live_research(db, settings)
        decisions = db.scalars(select(Decision).order_by(Decision.strategy_slug, Decision.conviction_score.desc())).all()

        assert 'liberated-us-stocks' in generated
        assert 'pick-shovel-growth' in generated
        assert decisions
        assert all(decision.status.startswith('research-') for decision in decisions)
        assert any(decision.strategy_slug == 'liberated-us-stocks' for decision in decisions)
        assert any(decision.strategy_slug == 'pick-shovel-growth' for decision in decisions)



def test_agent_autopilot_cycle_uses_research_generated_queue() -> None:
    reset_schema()
    settings = Settings(broker_backend='mock', quote_provider='mock')

    with SessionLocal() as db:
        bootstrap_database(db, settings)
        result = run_agent_autopilot_cycle(db, settings, force=True)
        decisions = db.scalars(select(Decision)).all()
        trades = db.scalars(select(AgentTrade)).all()

        assert result['executed_orders'] >= 1
        assert decisions
        assert all(decision.status.startswith('research-') for decision in decisions)
        assert trades

