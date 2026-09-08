from __future__ import annotations

from fastapi import FastAPI

from app.agent.trader import StubTraderAgent
from app.broker.paper import PaperBroker
from app.config import get_settings
from app.engine.orchestrator import Orchestrator
from app.market.fixtures import FixtureMarketProvider
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.web.routes import router


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.normalized_mode != "PAPER":
        raise RuntimeError("Slice 1 supports PAPER mode only; SHADOW and LIVE are intentionally unavailable")
    engine = make_engine(settings.db_url)
    init_db(engine)
    repo = Repository(make_session_factory(engine))
    broker = PaperBroker(repo, settings.starting_capital)
    market = FixtureMarketProvider()
    agent = StubTraderAgent()
    orchestrator = Orchestrator(settings, repo, broker, market, agent)
    app = FastAPI(title="Autonomous Compounding Trader")
    app.state.runtime = {"settings": settings, "repo": repo, "broker": broker, "market": market, "agent": agent, "orchestrator": orchestrator}
    app.include_router(router)
    return app


app = create_app()
