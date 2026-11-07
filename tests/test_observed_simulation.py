"""Observed simulation preserves provenance and native fill constraints."""
import asyncio
from datetime import timedelta

import pytest
from test_option_execution import configuration, enter, ledger
from test_option_admission import NOW
from test_robinhood_read_mapping import schemas as schemas
from test_continuous_strategy_delivery import prepared, capture_for, normalized

from app.mixed.observed_simulation import annotate
from app.options.engine import OptionExecution
from app.options.models import OptionQuote, paper_market_evidence
from app.options.venue import DurableOptionVenue


def observed(value):
    return annotate(type(value).model_validate(value.model_dump() | {
        "source": "robinhood-mcp", "entitlement": "UNKNOWN",
    }))


def test_opt_in_preserves_unknown_and_never_labels_delayed_as_usable():
    data, _, _ = configuration()
    q = data["quote"]
    for entitlement in ("UNKNOWN", "DELAYED", "INDICATIVE"):
        raw = OptionQuote.model_validate(q.model_dump() | {
            "source": "robinhood-mcp", "entitlement": entitlement,
        })
        assert not paper_market_evidence(raw)
        marked = annotate(raw)
        assert marked.entitlement == entitlement
        assert paper_market_evidence(marked) is (entitlement == "UNKNOWN")
    with pytest.raises(ValueError, match="supported original Robinhood"):
        OptionQuote.model_validate(q.model_dump() | {"simulation_basis": "ROBINHOOD_OBSERVED_V1"})
    assert "simulation_basis" not in q.model_dump()


def test_native_observed_quote_fill_and_reconciliation(tmp_path):
    data, limits, policy = configuration()
    instrument = data["quote"].instrument.model_copy(update={"provider": "robinhood"})
    data["quote"] = observed(data["quote"].model_copy(update={"instrument": instrument}))
    data["underlying"] = observed(data["underlying"])
    limits = limits.model_copy(update={
        "provider": "robinhood", "option_source": "robinhood-mcp",
        "underlying_source": "robinhood-mcp",
    })
    venue = DurableOptionVenue(tmp_path / "venue.db", limits=limits, capital=policy.capital)
    with OptionExecution.open(tmp_path / "options.db", limits, policy, venue, now=NOW, create=True) as engine:
        assert engine.reconcile(venue.snapshot(NOW), now=NOW)["reconciled"]
        engine.assess(None, None, now=NOW)
        entry = enter(engine, venue, data, quantity=1)
        assert ledger(engine).position.quantity == 1
        assert data["quote"].entitlement == "UNKNOWN"
        assert venue.submit_count == 1
        with pytest.raises(ValueError):
            venue.fill(entry, 100, data["quote"], NOW, fill_id="over-size")


def test_collector_opt_in_retains_exact_data(tmp_path, schemas):
    settings, feed, bound, evidence, now = prepared(tmp_path)
    captured, catalog = capture_for(feed, schemas, now)
    base = normalized(feed, schemas, captured, catalog, settings, bound, evidence, 1)
    chosen = feed.model_copy(update={"observed_simulation": "robinhood-observed-v1"})
    packet = normalized(chosen, schemas, captured, catalog, settings, bound, evidence, 1)
    assert packet.frame.quotes[0].entitlement == "UNKNOWN"
    assert paper_market_evidence(packet.frame.quotes[0])
    assert not paper_market_evidence(base.frame.quotes[0])
    assert packet.frame.quotes[0].bid == base.frame.quotes[0].bid
    assert packet.frame.quotes[0].ask_size == base.frame.quotes[0].ask_size
    assert packet.frame.histories[0].bars == base.frame.histories[0].bars
    assert packet.frame.stocks[0].quote.bid_size == base.frame.stocks[0].quote.bid_size
