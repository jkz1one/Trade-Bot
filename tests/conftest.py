from __future__ import annotations
from decimal import Decimal
import pytest
from app.config import Settings
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.broker.paper import PaperBroker

@pytest.fixture
def settings(tmp_path):
    return Settings(db_url=f"sqlite:///{tmp_path/'test.db'}", starting_capital=Decimal("10"), mode="PAPER")

@pytest.fixture
def repo(settings):
    engine = make_engine(settings.db_url); init_db(engine)
    return Repository(make_session_factory(engine))

@pytest.fixture
def broker(repo, settings):
    return PaperBroker(repo, settings.starting_capital)
