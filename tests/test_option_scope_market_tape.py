"""Common Scope source clocks and explicit unsupported-consumer boundaries."""

import asyncio
from datetime import timedelta

import pytest
from test_option_market_tape import header_for
from test_option_replay import settings_for
from test_option_scope import AT
from test_option_scope_arming import refresh
from test_option_scope_contract import data
from test_option_scope_execution import policy

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_export import export_arm
from app.options.market_tape import (
    RecordedTape,
    TapeHeader,
    TapeRecorder,
    load_tape,
    replay_shortlist,
    validate_tape_series,
)
from app.options.models import UnderlyingQuote
from app.options.replay import run_replay
from app.options.scope_arbitration import ScopeCycleInput
from app.options.scope_context import scan_scope_context
from app.options.scope_market_tape import ScopeTapePolicy, replay_scope_context


def inputs(right="CALL"):
    f, context = data(right)
    old = header_for()
    h = TapeHeader.model_validate(
        old.model_dump()
        | {
            "limits": old.limits.model_dump()
            | {
                "allowed_underlyings": ("SPY", "SPX"),
                "provider": "fixture-provider",
                "option_source": "fixture-quote",
            },
            "scope": ScopeTapePolicy(watch=policy(), session=f.session),
        }
    )
    u = UnderlyingQuote(
        symbol="SPX",
        source=h.limits.underlying_source,
        source_at=AT,
        received_at=AT,
        complete=True,
        entitlement="REALTIME",
        bid="103",
        ask="103",
    )
    return h, DegenFrame(
        scope=ScopeCycleInput(
            play_key="first",
            frame=f,
            context=context,
            underlying=u,
        )
    )


def record(path, h, frames):
    path.parent.chmod(0o700)
    with TapeRecorder(path, h) as r:
        for at, kind, f in frames:
            r.append(f, recorded_at=at, kind=kind)
        digest = r.seal()
    tape = load_tape(path)
    assert tape.digest == digest
    return tape


@pytest.mark.parametrize("right", ["CALL", "PUT"])
def test_scope_roundtrip_prefix_and_original_diagnostic_clock(tmp_path, right):
    h, f = inputs(right)
    later = AT + timedelta(seconds=2)
    fresh, context = refresh(f.scope.frame, later)
    next_frame = DegenFrame(
        scope=f.scope.model_copy(
            update={
                "frame": fresh,
                "context": context,
                "underlying": f.scope.underlying.model_copy(
                    update={"source_at": later, "received_at": later}
                ),
            }
        )
    )
    tape = record(tmp_path / "scope.tape", h, [(AT, "CYCLE", f), (later, "SCOPE", next_frame)])
    before = (tmp_path / "scope.tape").read_bytes()
    assert len(tape.available(AT)) == 1
    with pytest.raises(ValueError, match="not available"):
        replay_scope_context(tape, 2, as_of=AT)
    out = replay_scope_context(tape, 1, as_of=later + timedelta(hours=1))
    assert out["scan"] == scan_scope_context(
        f.scope.frame,
        f.scope.context,
        h.scope.watch.context,
        now=AT,
    ).model_dump(mode="json")
    assert out["event_hash"] == fingerprint(tape.events[0])
    assert out["policy_hash"] == fingerprint(h.scope)
    assert not out["execution_authority"] and not out["live_enabled"]
    assert replay_scope_context(tape, 2, as_of=later)["input_hash"] != out["input_hash"]
    assert (tmp_path / "scope.tape").read_bytes() == before


def test_legacy_header_and_frame_serialization_unchanged():
    h = header_for()
    raw = h.model_dump(mode="json")
    assert "scope" not in raw
    assert TapeHeader.model_validate(raw).model_dump(mode="json") == raw
    # Independently reproduced from the pre-change installed wheel.
    assert fingerprint(h) == "1280e7bca861f0d14f4d9b5a893526a2e31989d46a4d050c07cf7f4904d966ca"
    f = DegenFrame()
    assert "scope" not in f.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["CYCLE", "MARKET", "SCOPE"])
def test_scope_never_silently_enters_an_unenrolled_tape(tmp_path, kind):
    _, f = inputs()
    tmp_path.chmod(0o700)
    with TapeRecorder(tmp_path / "old.tape", header_for()) as r:
        with pytest.raises(ValueError, match="Scope|quotes only"):
            r.append(f, recorded_at=AT, kind=kind)
        r.seal()
    assert load_tape(tmp_path / "old.tape").events == ()


@pytest.mark.parametrize("kind", ["MARKET", "SCOPE"])
def test_event_kind_cannot_hide_other_input_families(tmp_path, kind):
    h, f = inputs()
    if kind == "SCOPE":
        f = f.model_copy(update={"quotes": (f.scope.frame.quote,)})
    with pytest.raises(ValueError, match="quotes only|only the nested"):
        record(tmp_path / "bad.tape", h, [(AT, kind, f)])


@pytest.mark.parametrize(
    "damage",
    [
        "coverage_clock",
        "coverage_source",
        "history_clock",
        "history_source",
        "unfinished_bar",
        "metadata_clock",
        "metadata_source",
        "quote_clock",
        "quote_source",
        "wrong_contract",
        "context_clock",
        "context_source",
        "prior_close",
        "previous_session",
        "moves_expiry",
        "underlying_clock",
        "underlying_source",
        "underlying_symbol",
        "duplicate_history",
        "duplicate_coverage",
        "session_deadline",
        "session_hash",
        "instrument_mismatch",
    ],
)
def test_recording_rejects_foreign_future_and_ambiguous_scope_inputs(tmp_path, damage):
    h, f = inputs()
    raw = f.model_dump()
    s, frame = raw["scope"], raw["scope"]["frame"]
    context = s["context"]
    future = AT + timedelta(seconds=1)
    if damage.startswith("coverage_"):
        frame["evidence"][0]["received_at" if damage.endswith("clock") else "source"] = (
            future if damage.endswith("clock") else "foreign"
        )
    elif damage.startswith("history_"):
        frame["histories"][0]["received_at" if damage.endswith("clock") else "source"] = (
            future if damage.endswith("clock") else "foreign"
        )
    elif damage == "unfinished_bar":
        frame["histories"][0]["source_at"] = AT - timedelta(seconds=2)
    elif damage.startswith(("metadata_", "quote_")):
        name, kind = damage.split("_")
        frame[name]["received_at" if kind == "clock" else "source"] = (
            future if kind == "clock" else "foreign"
        )
    elif damage == "wrong_contract":
        frame["quote"]["instrument"]["contract"]["root"] = "SPX"
    elif damage.startswith("context_"):
        context["flow"]["received_at" if damage.endswith("clock") else "source"] = (
            future if damage.endswith("clock") else "foreign"
        )
    elif damage == "prior_close":
        context["prior"]["closed_at"] = future
    elif damage == "previous_session":
        context["previous_session"] = AT.date()
    elif damage == "moves_expiry":
        context["moves"]["expiration"] = AT.date() + timedelta(days=1)
    elif damage.startswith("underlying_"):
        key = {"clock": "received_at", "source": "source", "symbol": "symbol"}[damage.split("_")[1]]
        s["underlying"][key] = {"received_at": future, "source": "foreign", "symbol": "SPY"}[key]
    elif damage == "duplicate_history":
        frame["histories"] = (*frame["histories"], frame["histories"][0])
    elif damage == "duplicate_coverage":
        frame["evidence"] = (*frame["evidence"], frame["evidence"][0])
    elif damage == "session_deadline":
        frame["session"]["protect_at"] += timedelta(minutes=1)
    elif damage == "session_hash":
        frame["session"]["evidence_hash"] = "f" * 64
    elif damage == "instrument_mismatch":
        frame["quote"]["instrument"]["instrument_id"] = "different"
    changed = DegenFrame.model_validate(raw)
    with pytest.raises(ValueError):
        record(tmp_path / "bad.tape", h, [(AT, "CYCLE", changed)])


@pytest.mark.parametrize("damage", ["source", "provider", "session", "universe", "capacity"])
def test_enrollment_is_bound_before_creating_a_file(tmp_path, damage):
    h, _ = inputs()
    raw = h.model_dump()
    if damage == "source":
        raw["limits"]["option_source"] = "foreign"
    elif damage == "provider":
        raw["limits"]["provider"] = "foreign"
    elif damage == "session":
        raw["scope"]["session"]["closes_at"] -= timedelta(minutes=1)
        raw["scope"]["session"]["protect_at"] -= timedelta(minutes=1)
    elif damage == "universe":
        raw["limits"]["allowed_underlyings"] = ("SPY",)
    else:
        raw["setup"]["symbols"] = ("SPY", "QQQ")
        raw["limits"]["allowed_underlyings"] = ("SPY", "QQQ", "SPX")
        raw["selection"]["max_quote_contracts"] = 4
    with pytest.raises(ValueError):
        invalid = h.model_copy(update=raw)
        TapeRecorder(tmp_path / "bad.tape", invalid)
    assert not (tmp_path / "bad.tape").exists()


@pytest.mark.parametrize("missing", [False, True])
def test_unavailable_stale_inputs_remain_explicit_diagnostics(tmp_path, missing):
    h, f = inputs()
    if missing:
        item = f.scope.model_copy(
            update={
                "frame": f.scope.frame.model_copy(
                    update={"histories": (), "metadata": None, "quote": None}
                ),
                "context": f.scope.context.model_copy(update={"flow": None}),
            }
        )
        f = DegenFrame(scope=item)
    at = AT + timedelta(minutes=2)
    tape = record(tmp_path / "tape", h, [(at, "SCOPE", f)])
    out = replay_scope_context(tape, 1, as_of=at)
    assert out["scan"]["structure"]["preflight"]["status"] == "BLOCKED"
    assert not out["execution_authority"]


@pytest.mark.parametrize("conflict", ["quote", "underlying"])
def test_common_and_nested_scope_truth_must_agree(tmp_path, conflict):
    h, f = inputs()
    update = (
        {"quotes": (f.scope.frame.quote.model_copy(update={"bid_size": 77}),)}
        if conflict == "quote"
        else {"underlyings": (f.scope.underlying.model_copy(update={"bid": "102"}),)}
    )
    with pytest.raises(ValueError, match="Conflicting"):
        record(tmp_path / "bad.tape", h, [(AT, "CYCLE", f.model_copy(update=update))])


def test_scope_quotes_allowed_after_entry_window_without_new_cycle(tmp_path):
    h, f = inputs()
    at = h.scope.session.protect_at + timedelta(seconds=1)
    clocks = {"source_at": at, "received_at": at}
    q, u = (
        f.scope.frame.quote.model_copy(update=clocks),
        f.scope.underlying.model_copy(update=clocks),
    )
    tape = record(tmp_path / "tape", h, [(at, "MARKET", DegenFrame(quotes=(q,), underlyings=(u,)))])
    assert tape.events[0].frame.quotes == (q,)
    with pytest.raises(ValueError, match="not available"):
        replay_scope_context(tape, 1, as_of=at)


def test_scope_consumers_fail_explicitly_before_native_state_or_export_reads(tmp_path):
    h, f = inputs()
    tape = record(tmp_path / "tape", h, [(AT, "CYCLE", f)])
    settings = settings_for(tape)
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="Scope-aware"):
        asyncio.run(run_replay(settings, tape, output))
    assert not output.exists()
    with pytest.raises(ValueError, match="Scope-aware"):
        replay_shortlist(tape, tape.events[0].cycle_key, as_of=AT)
    with pytest.raises(ValueError, match="Scope-aware"):
        export_arm(
            tmp_path / "missing.db", settings.manifest.arms[0], settings.manifest.sessions[0], tape
        )
    assert not (tmp_path / "missing.db").exists()
    from test_option_evaluation import bundle_for

    out = evaluate(bundle_for(), tapes=(tape,))
    assert "SCOPE_TAPE_COMPARISON_NOT_SUPPORTED" in out["sessions"][0]["reasons"]
    assert all(v["net_change"] is None for v in out["totals"].values())


def test_hash_chain_and_series_cannot_strip_scope_enrollment(tmp_path):
    h, f = inputs()
    tape = record(tmp_path / "tape", h, [(AT, "CYCLE", f)])
    raw = tape.model_dump()
    raw["header"].pop("scope")
    with pytest.raises(ValueError):
        RecordedTape.model_validate(raw)
    empty = record(tmp_path / "empty", header_for(), [])
    with pytest.raises(ValueError, match="unchanged"):
        validate_tape_series((tape, empty))
    with pytest.raises(ValueError, match="unchanged"):
        validate_tape_series((empty, tape))
