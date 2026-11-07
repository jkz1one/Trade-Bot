"""Explicit session assumptions and bounded native flat recovery."""
from datetime import UTC, date, datetime, timedelta

import pytest
from test_contract_catalog import captures as captures
from test_robinhood_read_mapping import schemas as schemas
from test_portfolio_controls import owned

from app.mixed.simulation_catalog import proposal
from app.mixed.simulation_profile import configuration
from app.mixed.feed_rollover import validate_policy
from app.mixed.connected_runtime import resume_flat
from app.options.models import OptionInstrument


def test_original_capture_becomes_labeled_simulation_not_verified_terms(captures):
    _, base = configuration()
    target = date(2026, 10, 28)
    policy, report = proposal(base, captures[0], captures[1:], target)
    assert len(policy.candidates) == 4
    assert policy.observed_simulation == "robinhood-observed-v1"
    assert report["entitlement"] == "UNKNOWN" and not report["broker_terms_verified"]
    assert all(i.simulation_terms == "STANDARD_ETF_INTRADAY_V1" for i in policy.candidates)
    assert not base.candidates
    before = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert validate_policy(base, policy, target, before).hour == 13
    with pytest.raises(ValueError, match="before its market close"):
        validate_policy(base, policy, target, before.replace(hour=20))
    with pytest.raises(ValueError, match="Same-day"):
        proposal(base, captures[0], captures[1:], date(2026, 10, 29))
    altered = policy.candidates[0].model_dump()
    altered["contract"]["underlying"] = "SPX"
    with pytest.raises(ValueError, match="Standard ETF"):
        OptionInstrument.model_validate(altered)


def test_flat_recovery_retains_native_guards(tmp_path):
    from test_mixed_native_owner import NOW
    with owned(tmp_path, at=NOW) as (e, v):
        with e.journal.write() as db:
            e._halt(db, "OPTION_RUNTIME_STOPPED", NOW)
        resume_flat(e, NOW)
        with e.journal.read() as db:
            assert not e._control(db)["halted"]
        with e.journal.write() as db:
            e._halt(db, "MANUAL_OPERATOR_HALT", NOW)
        with pytest.raises(ValueError, match="reviewed runtime"):
            resume_flat(e, NOW)


def test_reviewed_restart_resumes_only_after_native_ready(tmp_path, schemas, monkeypatch):
    import asyncio
    from test_connected_runtime import enrolled, state
    from test_robinhood_read_mapping import AT
    from app.mixed.connected_runtime import check, run
    from app.options.runtime_cli import existing_runtime
    from app.mixed.continuous_feed import ContinuousFeed
    args, _, _ = enrolled(tmp_path, schemas)
    with existing_runtime(args[0], clock=lambda: AT) as (runtime, _):
        with runtime.c.engine.journal.write() as db:
            runtime.c.engine._halt(db, "OPTION_RUNTIME_STOPPED", AT)
    revision = check(*args, clock_source=lambda: AT)[0]["owner_state"]["owner_revision"]
    observed = []
    times = [AT]

    async def capture(self, stop, **kwargs):
        import sqlite3
        from test_portfolio_feed import reader
        result = await self.tick(now=AT, held=(), reader=reader(AT, []))
        assert result["status"] == "DELIVERED"
        times[0] = AT + timedelta(seconds=2)
        for _ in range(100):
            with sqlite3.connect(args[0] / "options.db") as db:
                halted = db.execute("SELECT halted FROM execution_control WHERE id=1").fetchone()[0]
            if not halted:
                observed.append(halted)
                stop.set()
                return
            await asyncio.sleep(.1)
        raise AssertionError("Reviewed startup did not resume after fresh native feed")

    monkeypatch.setattr(ContinuousFeed, "run", capture)
    result = asyncio.run(run(*args, asyncio.Event(), clock_source=lambda: times[0],
                    resume_flat_reviewed_revision=revision))
    assert result["session_activity"]["reviewed_entry_resumes"] == 1
    assert result["session_activity"]["delivered_packets"] >= 1
    assert observed == [0]
    assert state(args[0])[0]["status"] == "STOPPED"


def test_catalog_proposal_reports_stale_analytic_drift_without_promoting_it(captures):
    import copy
    first = captures[1]['result']['observations'][0]['raw']['structuredContent']['data']['results'][0]['quote']
    first = copy.deepcopy(first)
    first['updated_at'] = '2026-10-27T19:00:00Z'
    for index, artifact in enumerate(captures[1:]):
        q = copy.deepcopy(first)
        q['delta'] = str(.2 + index / 100)
        artifact['result']['observations'][0]['raw']['structuredContent']['data']['results'][0]['quote'] = q
    _, base = configuration()
    policy, report = proposal(base, captures[0], captures[1:], date(2026, 10, 28))
    evidence = next(r for r in report['historical_quote_evidence'] if r['instrument_id'] == first['instrument_id'])
    assert evidence['analytic_changes_at_same_quote_time'] == ['delta']
    assert not evidence['all_fresh_at_capture'] and not evidence['source_clock_advanced']
    assert not report['trading_ready'] and report['entitlement'] == 'UNKNOWN'
    assert len(policy.candidates) == 4


def test_observed_swing_history_is_an_explicit_rollover_change(captures):
    from app.options.engine import fingerprint
    _, base = configuration()
    original = fingerprint(base)
    target = date(2026, 10, 28)
    default, _ = proposal(base, captures[0], captures[1:], target)
    proposed, report = proposal(base, captures[0], captures[1:], target, observed_swing_history=True)
    assert default.swing_observed_simulation is None
    assert proposed.swing_observed_simulation == 'robinhood-observed-v1'
    assert proposed.swing_history.bar_mapping == 'utc-day-halfhour-v1'
    assert not report['trading_ready'] and 'Reviewed price/options-only owner policy or complete legacy catalyst evidence' in report['swing_remaining']
    assert fingerprint(base) == original
    assert validate_policy(base, proposed, target, datetime(2026, 10, 28, 12, tzinfo=UTC))


def future_catalog(captures, expiration='2026-11-06'):
    # Deliberately synthetic future-contract evidence; never market acceptance.
    import json
    from uuid import NAMESPACE_URL, uuid5
    from app.mixed.contract_catalog import review
    value = json.dumps(captures).replace('2026-10-28', expiration)
    for row in review(captures[0], captures[1:])['contracts']:
        identity = row['provider_record']['id']
        value = value.replace(identity, str(uuid5(NAMESPACE_URL, 'synthetic-swing:' + identity)))
    return json.loads(value)


def test_reviewed_future_swing_and_same_day_degen_share_session(captures):
    _, base = configuration()
    target = date(2026, 10, 28)
    swing = future_catalog(captures)
    policy, report = proposal(base, captures[0], captures[1:], target,
        observed_swing_history=True, swing_contracts=swing[0], swing_samples=swing[1:])
    assert len(policy.candidates) == 8
    assert sum(i.contract.expiration == target for i in policy.candidates) == 4
    assert len(report['swing_catalog']['contracts']) == 4
    assert all(i.contract.last_trading_at.date() == i.contract.expiration for i in policy.candidates)
    assert not report['swing_catalog']['overnight_carry'] and not report['trading_ready']
    assert validate_policy(base, policy, target, datetime(2026, 10, 28, 12, tzinfo=UTC))
    with pytest.raises(ValueError, match='explicit observed history'):
        proposal(base, captures[0], captures[1:], target, swing_contracts=swing[0], swing_samples=swing[1:])
    bad = future_catalog(captures, '2026-10-30')
    with pytest.raises(ValueError, match='7-45 DTE'):
        proposal(base, captures[0], captures[1:], target, observed_swing_history=True,
                 swing_contracts=bad[0], swing_samples=bad[1:])
