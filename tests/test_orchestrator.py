from decimal import Decimal
from app.agent.trader import StubTraderAgent
from app.domain.models import Action, Horizon, TradeDecision
from app.engine.orchestrator import Orchestrator
from app.market.fixtures import FixtureMarketProvider


def test_complete_cycle_is_persisted(settings, repo, broker):
    o=Orchestrator(settings,repo,broker,FixtureMarketProvider(),StubTraderAgent())
    _,d,r,x=o.cycle()
    assert d.action == Action.HOLD
    assert not r.approved
    assert x.status == "SKIPPED"
    rows=repo.recent_cycles()
    assert len(rows)==1
    assert rows[0].decision_json and rows[0].risk_json and rows[0].execution_json and rows[0].packet_json

def test_agent_proposal_passes_governor_before_paper_fill(settings,repo,broker):
    d=TradeDecision(action=Action.OPEN_LONG,symbol="QQQ",confidence=.9,setup_quality=.9,horizon=Horizon.INTRADAY,desired_exposure_fraction=1,invalidation_price=Decimal("565"),thesis="Fixture momentum",invalidation_reason="Break below fixture structure",evidence=["above VWAP"],risks=["demo fixture"],why_now="fixture trigger")
    o=Orchestrator(settings,repo,broker,FixtureMarketProvider(),StubTraderAgent(d))
    _,_,r,x=o.cycle()
    assert r.approved
    assert r.approved_notional <= Decimal("9")
    assert x.status == "FILLED"
