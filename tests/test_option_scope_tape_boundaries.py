"""Additional acceptance checks for the published common Scope tape contract."""

import asyncio
from datetime import timedelta

import pytest
from test_option_evaluation import bundle_for
from test_option_market_tape import header_for, record_bundle
from test_option_replay import settings_for
from test_option_scope import AT
from test_option_scope_market_tape import inputs, record

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_export import export_arm, export_comparison, export_series
from app.options.market_tape import TapeRecorder
from app.options.replay import run_replay, run_replay_series


@pytest.mark.parametrize(
    "part",
    [
        "evidence",
        "history",
        "metadata",
        "quote",
        "underlying",
        "dealer",
        "moves",
        "flow",
        "news",
        "events",
        "prior",
    ],
)
@pytest.mark.parametrize("damage", ["future", "reversed", "source"])
def test_every_nested_scope_source_and_clock_is_checked_before_append(tmp_path, part, damage):
    h, f = inputs()
    raw = f.model_dump()
    item = raw["scope"]
    target = (
        item["frame"]["evidence"][0]
        if part == "evidence"
        else item["frame"]["histories"][0]
        if part == "history"
        else item["frame"][part]
        if part in {"metadata", "quote"}
        else item[part]
        if part == "underlying"
        else item["context"][part]
    )
    if damage == "future":
        target["received_at"] = AT + timedelta(seconds=1)
    elif damage == "reversed":
        target["source_at"] = target["received_at"] + timedelta(seconds=1)
    else:
        target["source"] = "foreign"
    path = tmp_path / "scope.tape"
    with TapeRecorder(path, h) as recorder:
        before = path.read_bytes()
        with pytest.raises(ValueError, match="Scope"):
            recorder.append(DegenFrame.model_validate(raw), recorded_at=AT)
        assert path.read_bytes() == before


def test_parent_wheel_golden_shared_header_and_complete_tape_are_unchanged(tmp_path):
    from test_option_shared_strategy import swing_policy

    h = header_for()
    # Independently captured from the installed parent wheel at 33106efa.
    assert fingerprint(h) == "1280e7bca861f0d14f4d9b5a893526a2e31989d46a4d050c07cf7f4904d966ca"
    assert fingerprint(h.model_copy(update={"swing": swing_policy()})) == (
        "209913e00e32796b1d9db5f97ca1640da11e338d98674809878ded0effbe0df1"
    )
    _, tape, _ = record_bundle(tmp_path)
    assert tape.digest == "7b1948c40d957e3382f14eb62163e3fcfe9c232776245aa3fac060e0593e64e6"


@pytest.mark.parametrize("damage", ["source", "future", "reversed"])
def test_nested_greeks_must_be_available_at_quote_receipt(tmp_path, damage):
    from test_option_greek_health import observed

    h, f = inputs()
    changes = {
        "source": {"source": "foreign"},
        "future": {"received_at": AT + timedelta(seconds=1)},
        "reversed": {"source_at": AT + timedelta(seconds=1)},
    }[damage]
    q = observed(f.scope.frame.quote, **changes)
    f = f.model_copy(
        update={
            "scope": f.scope.model_copy(
                update={"frame": f.scope.frame.model_copy(update={"quote": q})}
            )
        }
    )
    with pytest.raises(ValueError, match="Scope"):
        record(tmp_path / "scope.tape", h, [(AT, "CYCLE", f)])


def test_nested_quote_counts_toward_common_capacity_but_identical_copy_does_not(tmp_path):
    h, f = inputs()
    q = f.scope.frame.quote
    quotes = tuple(
        q.model_copy(
            update={"instrument": q.instrument.model_copy(update={"instrument_id": f"other-{n}"})}
        )
        for n in range(8)
    )
    with pytest.raises(ValueError, match="eight-contract"):
        record(tmp_path / "over.tape", h, [(AT, "CYCLE", f.model_copy(update={"quotes": quotes}))])
    accepted = record(
        tmp_path / "exact.tape",
        h,
        [(AT, "CYCLE", f.model_copy(update={"quotes": (*quotes[:7], q)}))],
    )
    assert len(accepted.events[0].frame.quotes) == 8


@pytest.mark.parametrize(
    "consumer", ["run", "run_series", "evaluate", "export", "export_series", "export_arm"]
)
@pytest.mark.parametrize("with_input", [True, False])
def test_all_account_consumers_withhold_scope_before_account_io(tmp_path, consumer, with_input):
    h, f = inputs()
    tape = record(tmp_path / "scope.tape", h, [(AT, "CYCLE", f if with_input else DegenFrame())])
    settings = settings_for(tape)
    manifest = settings.manifest
    destination = tmp_path / "must-not-exist"
    sources = {
        a.arm: {"journal": destination, "data_cost": "0", "host_cost": "0"} for a in manifest.arms
    }
    if consumer == "evaluate":
        out = evaluate(bundle_for(), tapes=(tape,))
        assert "SCOPE_TAPE_COMPARISON_NOT_SUPPORTED" in out["sessions"][0]["reasons"]
        assert all(v["net_change"] is None for v in out["totals"].values())
    else:
        with pytest.raises(ValueError, match="Scope-aware"):
            if consumer == "run":
                asyncio.run(run_replay(settings, tape, destination))
            elif consumer == "run_series":
                asyncio.run(run_replay_series(settings, (tape,), destination))
            elif consumer == "export":
                export_comparison(manifest, tape, sources)
            elif consumer == "export_series":
                export_series(manifest, (tape,), {h.session_key: sources})
            else:
                export_arm(destination, manifest.arms[0], manifest.sessions[0], tape)
    assert not destination.exists()


@pytest.mark.parametrize("arm", ["C", "D"])
def test_scope_tape_does_not_relax_the_old_ai_replay_adapter_boundary(tmp_path, arm):
    from test_option_entry_reasoning import packet_for
    from test_option_scope_arbitration import shared

    from app.execution.judgment import JudgmentLimits
    from app.options.replay_model import ReplayModel, ReplayScript

    async def refresh(_play):
        raise AssertionError("No refresh before explicit replay enrollment")

    with (
        pytest.raises(ValueError, match="Shared Scope AI requires full entry configuration"),
        shared(
            tmp_path,
            costs=True,
            ai=True,
            coordinator_options={
                "entry_policy": packet_for().policy.model_copy(
                    update={"scope_selection": "scope-fixed-plan-v1"}
                ),
                "judgment_limits": JudgmentLimits(),
                "key_file": tmp_path / "unused-private-key",
                "scope_refresh": refresh,
                "replay_model": ReplayModel(ReplayScript(arm=arm, decisions=())),
            },
        ),
    ):
        pytest.fail("Legacy replay adapter was admitted")
