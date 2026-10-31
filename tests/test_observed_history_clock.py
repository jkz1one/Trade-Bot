"""Completed bar closes are not quote publication clocks in observed PAPER."""

from datetime import timedelta

import pytest
from test_degen_options import AT, history, policies

from app.mixed.history_clock_replay import replay_history
from app.mixed.observed_simulation import annotate
from app.options.degen import DegenHistory, scan_degen
from app.options.governor import _fresh
from app.robinhood.schedule import XNYSCalendar


def observed(delay=26, **changes):
    return annotate(DegenHistory.model_validate(history().model_dump() | {
        "source": "robinhood-mcp", "entitlement": "UNKNOWN",
        "received_at": AT + timedelta(seconds=delay), **changes,
    }))


def scan(value, now):
    policy = policies()[0].model_copy(update={"history_source": "robinhood-mcp"})
    return scan_degen(value, policy, XNYSCalendar().current_window(now), now=now)


def test_reproduces_old_clock_rejection_and_corrects_only_marked_observed_bar():
    original = observed()
    now = AT + timedelta(seconds=28)
    assert "HISTORY_UNAVAILABLE_DELAYED_OR_STALE" in scan(original, now).issues
    corrected = DegenHistory.model_validate(original.model_dump() | {"source_clock_basis": "COMPLETED_BAR_END"})
    result = scan(corrected, now)
    assert result.issues == ()
    assert any(o.status == "CONFIRMED" for o in result.observations)
    assert corrected.source_at == original.source_at and corrected.received_at == original.received_at
    assert corrected.bars == original.bars and corrected.entitlement == "UNKNOWN"
    assert not _fresh(AT, corrected.received_at, now, 300, 2)
    assert "source_clock_basis" not in original.model_dump()


@pytest.mark.parametrize("damage", ["incomplete", "delayed", "unknown_unapproved", "future_receipt", "aged", "gap", "interpolated"])
def test_observed_clock_does_not_admit_unavailable_or_bad_bars(damage):
    h = observed(source_clock_basis="COMPLETED_BAR_END")
    now = AT + timedelta(seconds=28)
    changes = {}
    if damage == "incomplete":
        changes["complete"] = False
    elif damage in ("delayed", "unknown_unapproved"):
        changes.update(entitlement="DELAYED" if damage == "delayed" else "UNKNOWN", simulation_basis=None)
    elif damage == "future_receipt":
        changes["received_at"] = now + timedelta(seconds=1)
    elif damage == "aged":
        now = AT + timedelta(seconds=300)
    elif damage == "gap":
        changes["bars"] = (h.bars[0], *h.bars[2:])
    else:
        changes["bars"] = (*h.bars[:-1], h.bars[-1].model_copy(update={"interpolated": True}))
    h = DegenHistory.model_validate(h.model_dump() | changes)
    assert scan(h, now).issues


def test_source_clock_tag_requires_original_exact_completed_end():
    with pytest.raises(ValueError, match="exact original"):
        observed(source_clock_basis="COMPLETED_BAR_END", source_at=AT + timedelta(seconds=1))


def test_offline_replay_keeps_original_evidence_and_reveals_clock_difference():
    h = observed()
    before = h.model_dump_json()
    p = policies()[0].model_copy(update={"history_source": "robinhood-mcp"})
    report = replay_history(h, p, AT + timedelta(seconds=28), XNYSCalendar())
    assert report["bar_close_to_receipt_seconds"] == 26
    assert report["replayed_issues"] == []
    assert report["original_history_unchanged"] and h.model_dump_json() == before


def test_saved_opportunity_replay_verifies_fingerprint_and_does_not_write(tmp_path):
    import json
    import sqlite3
    from app.mixed.history_clock_replay import report
    from app.mixed.simulation_profile import configuration
    from app.options.coordinator import DegenFrame
    from app.options.engine import fingerprint

    settings, _ = configuration()
    settings_file = tmp_path / 'runtime.json'
    settings_file.write_text(settings.model_dump_json())
    settings_file.chmod(0o600)
    frame = DegenFrame(histories=(observed(),))
    at = AT + timedelta(seconds=28)
    original = scan(frame.histories[0], at)
    path = tmp_path / 'options.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE execution_option_opportunities(cycle_key,fingerprint,inputs_json,result_json,started_at)')
        db.execute('INSERT INTO execution_option_opportunities VALUES(?,?,?,?,?)',
                   ('saved', fingerprint(frame), frame.model_dump_json(),
                    json.dumps({'scans': [original.model_dump(mode='json')]}), at.isoformat()))
    before = path.read_bytes(), settings_file.read_bytes()
    result = report(tmp_path, AT, at + timedelta(seconds=1))
    h = result['cycles'][0]['histories'][0]
    assert h['original_issues'] == ['HISTORY_UNAVAILABLE_DELAYED_OR_STALE']
    assert h['replayed_issues'] == []
    assert before == (path.read_bytes(), settings_file.read_bytes())
    with sqlite3.connect(path) as db:
        db.execute("UPDATE execution_option_opportunities SET fingerprint='changed'")
    with pytest.raises(ValueError, match='fingerprint mismatch'):
        report(tmp_path, AT, at + timedelta(seconds=1))
