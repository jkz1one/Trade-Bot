"""Frozen shared-family tapes and independent native A/B/C/D replay accounting."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest
from test_degen_options import AT
from test_option_managed_replay import DKEY, managed_settings, managed_tape
from test_option_market_tape import header_for
from test_option_replay import KEY
from test_option_replay_series import SHIFT, later_tape
from test_option_shared_strategy import shared_frame, swing_input, swing_policy

from app.options.engine import fingerprint
from app.options.evaluation_export import export_series
from app.options.evaluation_models import EvaluationManifest, EvaluationSession
from app.options.judgment import CandidatePacket, CandidateRequest, SharedCandidatePacket
from app.options.market_tape import TapeHeader, TapeRecorder, load_tape, replay_shortlist
from app.options.replay import ReplaySettings, run_replay, run_replay_series
from app.options.replay_model import ReplayScript


def shared_tape(root, *, full=False, later=False, lifecycle=None):
    original = managed_tape(root, full=full)
    if later:
        original = later_tape(original, root)
    shift = SHIFT if later else timedelta()
    item = swing_input(target=(AT + shift).date())
    header = original.header.model_copy(
        update={"swing": swing_policy(unfilled_lifecycle=lifecycle)}
    )
    with TapeRecorder(root / "shared.tape", header) as recorder:
        for e in original.events:
            f = e.frame
            if e.kind == "CYCLE":
                current = item.model_copy(
                    update={
                        "metadata": item.metadata.model_copy(
                            update={"source_at": e.recorded_at, "received_at": e.recorded_at}
                        ),
                        "catalyst": item.catalyst.model_copy(
                            update={"source_at": e.recorded_at, "received_at": e.recorded_at}
                        ),
                    }
                )
                f = f.model_copy(update={"swing": (current,)})
            if f.quotes:
                f = f.model_copy(
                    update={
                        "quotes": f.quotes
                        + (f.quotes[0].model_copy(update={"instrument": item.seed.instrument}),),
                    }
                )
            recorder.append(f, recorded_at=e.recorded_at, kind=e.kind)
        recorder.seal()
    return load_tape(root / "shared.tape")


@pytest.fixture(scope="module")
def shared_series(tmp_path_factory):
    root = tmp_path_factory.mktemp("shared-series")
    later = root / "later"
    later.mkdir(mode=0o700)
    tapes = (shared_tape(root, full=True), shared_tape(later, full=True, later=True))
    settings = managed_settings(tapes[0])
    h = tapes[1].header
    manifest = settings.manifest.model_copy(
        update={
            "sessions": (
                settings.manifest.sessions[0],
                EvaluationSession(
                    key=h.session_key,
                    opens_at=h.opens_at,
                    closes_at=h.closes_at,
                    tape_hash=tapes[1].digest,
                ),
            )
        }
    )
    scripts = {}
    for name in ("narrow", "broad", "managed"):
        script = getattr(settings, name)
        scripts[name] = ReplayScript(
            arm=script.arm,
            decisions=(
                *script.decisions,
                *(
                    d.model_copy(
                        update={
                            "cycle_key": d.cycle_key.split(":")[0]
                            + ":"
                            + str(
                                int(d.cycle_key.split(":")[1]) + int(SHIFT.total_seconds()) // 300
                            )
                        }
                    )
                    for d in script.decisions
                ),
            ),
        )
    settings = ReplaySettings.model_validate(
        settings.model_dump()
        | {
            "manifest": manifest,
            **scripts,
        }
    )
    result = asyncio.run(run_replay_series(settings, tapes, root / "run"))
    return root, tapes, settings, result


def test_native_shared_accounts_costs_management_and_continuity(shared_series):
    root, tapes, _, result = shared_series
    report = result["report"]
    assert report["status"] == "COMPLETE_ARITHMETIC", report
    assert report["economic_conclusion"] == "INCONCLUSIVE"
    assert not result["live_enabled"]
    rows = result["bundle"]["evidence"]
    assert len(rows) == 8
    for first, later in zip(rows[:4], rows[4:], strict=True):
        assert first["arm"] == later["arm"]
        assert later["initial"] == first["closing"]
        assert later["initial"]["settled_cash"] == first["closing"]["settled_cash"]
        assert len(first["cycles"]) == len(later["cycles"]) == 78
        assert (
            first["orders"][0]["intent"]["instrument"]["instrument_id"] == "swing-locked-contract"
        )
        assert (
            later["orders"][0]["intent"]["instrument"]["contract"]["expiration"]
            != first["orders"][0]["intent"]["instrument"]["contract"]["expiration"]
        )
        assert first["closing"]["position"] is None and later["closing"]["position"] is None
        assert Decimal(first["closing"]["fees_paid"]) > 0
        expected = (
            []
            if first["arm"] == "A"
            else ["ENTRY", "MANAGEMENT"]
            if first["arm"] == "D"
            else ["ENTRY"]
        )
        assert [c["role"] for c in first["calls"]] == expected
        assert all(c["usage"] is not None for c in first["calls"])
        assert first["data_cost"] == later["data_cost"] == "0.01"
        assert first["host_cost"] == later["host_cost"] == "0.02"
    d = rows[3]
    attr = next(c["attribution"] for c in d["cycles"] if c["key"] == DKEY)
    assert attr["proposal_action"] == "EXIT_ALL" and attr["order_status"] == "FILLED"
    assert attr["filled_quantity"] == attr["approved_quantity"] > 0
    definitions = result["bundle"]["manifest"]["arms"]
    # Historical fixtures reuse a provider account label. Population ledgers and
    # order identities, not that display label, define independent simulated owners.
    assert len({r["orders"][0]["intent"]["client_id"] for r in rows[:4]}) == 4
    assert len({a["limits"]["population_id"] for a in definitions}) == 4
    for session, session_rows in zip(report["sessions"], (rows[:4], rows[4:]), strict=True):
        costs = session["arms"]
        assert Decimal(costs["D"]["known_model_cost"]) == 2 * Decimal(
            costs["C"]["known_model_cost"]
        )
        assert (
            costs["D"]["model_cost_by_role"]["ENTRY"]
            == costs["D"]["model_cost_by_role"]["MANAGEMENT"]
        )
        for r in session_rows:
            a = costs[r["arm"]]
            assert Decimal(a["net_change"]) == Decimal(r["closing"]["cash"]) - Decimal(
                r["initial"]["cash"]
            ) - Decimal(a["known_model_cost"]) - Decimal(".03")
    for arm in "ABCD":
        with sqlite3.connect(root / "run" / arm / "journal.db") as db:
            assert (
                db.execute("SELECT count(*) FROM execution_option_swing_seeds").fetchone()[0] == 2
            )
            strategy = json.loads(
                db.execute("SELECT policy_json FROM execution_option_strategy").fetchone()[0]
            )
            assert strategy["swing"] == tapes[0].header.swing.model_dump(mode="json")


def test_narrow_comparison_uses_explicit_shared_packet_and_preserves_limits(shared_series):
    root, _, settings, _ = shared_series
    with sqlite3.connect(root / "run/B/journal.db") as db:
        value = json.loads(
            db.execute(
                "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (KEY,)
            ).fetchone()[0]
        )
    request = CandidateRequest.model_validate(value["model_request"])
    assert isinstance(request.packet, SharedCandidatePacket)
    assert request.configuration["prompt_version"] == "shared-candidate-choice-v1"
    assert request.limits == settings.judgment_limits
    assert {c.family for c in request.packet.candidates} >= {
        "SWING_DAILY_BREAKOUT",
        "ORB_CONTINUATION",
    }
    assert len(request.packet.scans) == 2
    with pytest.raises(ValueError):
        CandidatePacket.model_validate(request.packet.model_dump())
    with pytest.raises(ValueError, match="family evidence"):
        SharedCandidatePacket.model_validate(
            request.packet.model_dump() | {"scans": request.packet.scans[1:]}
        )


def test_shared_comparison_prompt_is_bound_before_provider_work(shared_series):
    import time

    from test_execution_judgment import sdk_client
    from test_option_judgment import output_for

    from app.options.judgment import request_content
    from app.options.judgment_worker import perform

    root, _, _, _ = shared_series
    with sqlite3.connect(root / "run/B/journal.db") as db:
        value = json.loads(
            db.execute(
                "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (KEY,)
            ).fetchone()[0]
        )
    request = CandidateRequest.model_validate(value["model_request"]).model_copy(
        update={"deadline_monotonic": time.monotonic() + 30}
    )
    assert "Degen or Swing" in request_content(request)["instructions"]
    client, calls = sdk_client(output=output_for(request))
    with client:
        result = perform(request, client)
        assert result.error is None and result.choice.action == "SELECT"
        assert len(calls) == 2
    request = request.model_copy(
        update={
            "configuration": request.configuration | {"prompt_version": "degen-candidate-choice-v1"}
        }
    )
    client, calls = sdk_client(output=output_for(request))
    with client:
        assert perform(request, client).error == "ValueError"
        assert calls == []


def test_shared_export_requires_matching_frozen_family_policy(shared_series):
    root, tapes, _, result = shared_series
    manifest = EvaluationManifest.model_validate(result["bundle"]["manifest"])
    sources = {
        s.key: {
            arm: {
                "journal": str(root / "run" / arm / "sessions" / (s.key + ".db")),
                "data_cost": ".01",
                "host_cost": ".02",
            }
            for arm in "ABCD"
        }
        for s in manifest.sessions
    }
    exported = export_series(manifest, tapes, sources)
    assert exported["bundle"].model_dump(mode="json") == result["bundle"]
    # Change both the sealed header and declared digest: native frozen policy still disagrees.
    h = tapes[0].header.model_copy(update={"swing": None})
    from app.options.market_tape import RecordedTape, TapeEvent, TapeSeal

    previous = fingerprint(h)
    events = []
    for e in tapes[0].events:
        f = e.frame.model_copy(update={"swing": ()})
        e = TapeEvent.model_validate(e.model_dump() | {"frame": f, "previous_hash": previous})
        events.append(e)
        previous = fingerprint(e)
    changed = RecordedTape(
        header=h,
        events=tuple(events),
        seal=TapeSeal(
            header_hash=fingerprint(h),
            event_count=len(events),
            last_hash=previous,
        ),
    )
    manifest = manifest.model_copy(
        update={
            "sessions": (
                manifest.sessions[0].model_copy(update={"tape_hash": changed.digest}),
                manifest.sessions[1],
            )
        }
    )
    with pytest.raises(ValueError, match="strategy binding"):
        export_series(manifest, (changed, tapes[1]), sources)


@pytest.mark.parametrize(
    "damage",
    [
        "unenrolled",
        "future_seed",
        "future_metadata",
        "future_catalyst",
        "future_history",
        "unfinished_daily",
        "foreign_source",
        "foreign_contract",
        "duplicate",
        "market",
    ],
)
def test_shared_tape_rejects_unavailable_or_foreign_inputs(tmp_path, damage):
    h = header_for().model_copy(update={"swing": swing_policy()})
    f = shared_frame()
    item = f.swing[0]
    if damage == "unenrolled":
        h = h.model_copy(update={"swing": None})
    elif damage == "future_seed":
        item = item.model_copy(
            update={"seed": item.seed.model_copy(update={"created_at": AT + timedelta(seconds=1)})}
        )
    elif damage in {"future_metadata", "future_catalyst"}:
        name = damage.removeprefix("future_")
        item = item.model_copy(
            update={
                name: getattr(item, name).model_copy(
                    update={"received_at": AT + timedelta(seconds=1)}
                )
            }
        )
    elif damage in {"future_history", "unfinished_daily"}:
        history = item.seed.history
        if damage == "future_history":
            history = history.model_copy(update={"received_at": AT + timedelta(seconds=1)})
        else:
            history = history.model_copy(
                update={
                    "bars": (
                        *history.bars[:-1],
                        history.bars[-1].model_copy(
                            update={"closes_at": AT + timedelta(seconds=1)}
                        ),
                    )
                }
            )
        item = item.model_copy(update={"seed": item.seed.model_copy(update={"history": history})})
    elif damage == "foreign_source":
        item = item.model_copy(
            update={"catalyst": item.catalyst.model_copy(update={"source": "other-source"})}
        )
    elif damage == "foreign_contract":
        item = item.model_copy(
            update={
                "metadata": item.metadata.model_copy(update={"instrument": f.quotes[0].instrument})
            }
        )
    f = f.model_copy(update={"swing": (item, item) if damage == "duplicate" else (item,)})
    with TapeRecorder(tmp_path / "bad.tape", h) as writer, pytest.raises(ValueError):
        writer.append(f, recorded_at=AT, kind="MARKET" if damage == "market" else "CYCLE")


def test_shortlist_is_point_in_time_and_retains_family_priority(tmp_path):
    tape = shared_tape(tmp_path)
    with pytest.raises(ValueError, match="not available"):
        replay_shortlist(tape, KEY, as_of=AT - timedelta(seconds=1))
    result = replay_shortlist(tape, KEY, as_of=AT)
    assert not result["missing"] and not result["execution_authority"]
    assert result["scans"][0]["version"] == "swing-next-session-v1"
    assert result["plans"][0]["instruments"][0]["instrument_id"] == "swing-locked-contract"
    assert len(result["plans"]) == 2


def test_missing_shared_seed_blocks_both_shortlist_families(tmp_path):
    h = header_for().model_copy(update={"swing": swing_policy()})
    with TapeRecorder(tmp_path / "missing.tape", h) as writer:
        writer.append(shared_frame().model_copy(update={"swing": ()}), recorded_at=AT)
        writer.seal()
    result = replay_shortlist(load_tape(tmp_path / "missing.tape"), KEY, as_of=AT)
    assert result["plans"] == []
    assert result["missing"] == ["SPY:EXACT_SWING_SEED_COVERAGE_REQUIRED"]


def test_shortlist_never_replaces_an_earlier_valid_seed(tmp_path):
    h = header_for().model_copy(update={"swing": swing_policy()})
    f = shared_frame()
    item = f.swing[0]
    changed = item.seed.instrument.model_copy(update={"instrument_id": "replacement"})
    item = item.model_copy(
        update={
            "seed": item.seed.model_copy(update={"instrument": changed}),
            "metadata": item.metadata.model_copy(update={"instrument": changed}),
        }
    )
    later = AT + timedelta(minutes=5)
    with TapeRecorder(tmp_path / "conflict.tape", h) as writer:
        writer.append(f, recorded_at=AT)
        writer.append(f.model_copy(update={"swing": (item,)}), recorded_at=later)
        writer.seal()
    tape = load_tape(tmp_path / "conflict.tape")
    first = replay_shortlist(tape, KEY, as_of=AT)
    assert first["plans"][0]["instruments"][0]["instrument_id"] == "swing-locked-contract"
    next_key = "degen:" + str(int(later.timestamp()) // 300)
    result = replay_shortlist(tape, next_key, as_of=later)
    assert result["plans"] == [] and result["missing"] == ["SPY:SWING_SEED_LOCK_CONFLICT"]


def test_quote_budget_counts_both_families_and_legacy_hash_is_unchanged():
    h = header_for()
    assert "swing" not in h.model_dump()
    assert fingerprint(h) == fingerprint(h.model_dump())
    with pytest.raises(ValueError, match="bounded universe"):
        TapeHeader.model_validate(
            h.model_dump()
            | {
                "swing": swing_policy(),
                "selection": h.selection.model_copy(update={"max_quote_contracts": 8}),
            }
        )


def test_shared_narrow_unknown_cost_fences_its_account_only(tmp_path):
    tape = shared_tape(tmp_path)
    settings = managed_settings(tape)
    settings = settings.model_copy(
        update={
            "narrow": settings.narrow.model_copy(
                update={
                    "decisions": (
                        settings.narrow.decisions[0].model_copy(update={"action": "UNKNOWN"}),
                    ),
                }
            )
        }
    )
    result = asyncio.run(run_replay(settings, tape, tmp_path / "unknown"))
    rows = {r["arm"]: r for r in result["bundle"]["evidence"]}
    assert len(rows["B"]["calls"]) == 1 and rows["B"]["calls"][0]["usage"] is None
    assert rows["B"]["orders"] == []
    assert all(rows[a]["orders"] for a in "ACD")
    assert result["report"]["economic_conclusion"] == "INCONCLUSIVE"
    with sqlite3.connect(tmp_path / "unknown/B/journal.db") as db:
        row = db.execute("SELECT halted,halt_reason FROM execution_control").fetchone()
        assert row[0] and row[1] == "OPTION_MODEL_COST_UNKNOWN"
