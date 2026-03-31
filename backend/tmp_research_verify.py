from sqlalchemy import select
from app.core.config import Settings
from app.db.session import Base, SessionLocal, engine
from app.models.entities import AgentTrade, Decision, ResearchNote
from app.services.research import refresh_live_research
from app.services.trading import bootstrap_database
from app.strategy.engine import run_agent_autopilot_cycle

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
settings = Settings(quote_provider='mock')
with SessionLocal() as db:
    bootstrap_database(db, settings)
    generated = refresh_live_research(db, settings)
    decisions = db.scalars(select(Decision).order_by(Decision.strategy_slug, Decision.conviction_score.desc())).all()
    notes = db.scalars(select(ResearchNote)).all()
    result = run_agent_autopilot_cycle(db, settings, force=True)
    trades = db.scalars(select(AgentTrade)).all()
    print({'generated_agents': sorted(generated.keys()), 'decision_count': len(decisions), 'note_count': len(notes), 'autopilot_orders': result['executed_orders'], 'trade_count': len(trades), 'first_event': result['events'][0] if result['events'] else None})
