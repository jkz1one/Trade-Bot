"""Independent eligible long-share cash, tape fills, costs and continuity."""

import json
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal as D
from decimal import localcontext

import pytest
from test_option_evaluation import bundle_for, change_arm, round_trip
from test_option_market_tape import header_for

from app.options.coordinator import DegenFrame
from app.options.engine import fingerprint
from app.options.evaluation import evaluate
from app.options.evaluation_models import UnderlyingBaselinePolicy, UnderlyingSettlement
from app.options.market_tape import TapeRecorder, load_tape
from app.options.underlying_baseline import _Account


def policy():
    return UnderlyingBaselinePolicy(
        account_id="underlying-account",
        population_id="underlying-population",
        tick_size=".01",
        max_shares=100,
        entry_fee_per_share=".01",
        exit_fee_per_share=".02",
        entry_fee_per_order=".10",
        exit_fee_per_order=".20",
        data_cost_per_session=".01",
        host_cost_per_session=".02",
    )


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    start, end, orders = round_trip(tmp_path_factory.mktemp("underlying-native") / "owner")
    buy = orders[0].model_copy(
        update={
            "intent": orders[0].intent.model_copy(
                update={"original_underlying_invalidation": D(99)}
            )
        }
    )
    return start, end, (buy, orders[1])


def evidence(tmp_path, native, *, damage=None):
    start, end, orders = native
    b = change_arm(bundle_for(), 0, initial=start, closing=end, orders=orders)
    b = b.model_copy(
        update={"manifest": b.manifest.model_copy(update={"underlying_baseline": policy()})}
    )
    at = orders[0].intent.prepared_at
    q = b.benchmarks[0].start
    updates = []
    for n in range(4):
        when = at + timedelta(seconds=n)
        price = D(100) if n < 2 else D("97.99")
        value = q.model_copy(
            update={
                "source_at": when,
                "received_at": when,
                "bid": price,
                "ask": price + D(".01"),
                "bid_size": 20,
                "ask_size": 20,
            }
        )
        if damage == "size":
            value = value.model_copy(update={"bid_size": None, "ask_size": None})
        if damage == "entry_stale" and n == 1:
            value = value.model_copy(update={"source_at": at})
        if damage == "zero_size" and n == 1:
            value = value.model_copy(update={"ask_size": 0})
        if damage == "unfilled_limit" and n >= 1:
            value = value.model_copy(update={"bid": D(101), "ask": D("101.01")})
        if damage == "exit_size" and n >= 2:
            value = value.model_copy(update={"bid_size": None})
        if damage == "partial" and n >= 2:
            value = value.model_copy(update={"bid_size": 2})
        updates.append((when, "MARKET", DegenFrame(underlyings=(value,))))
        if damage == "repeat" and n == 3:
            updates.append((when, "MARKET", DegenFrame(underlyings=(value,))))
    if damage == "partial":
        when = at + timedelta(seconds=4)
        updates.append(
            (
                when,
                "MARKET",
                DegenFrame(
                    underlyings=(value.model_copy(update={"source_at": when, "received_at": when}),)
                ),
            )
        )
    events = list(updates)
    for c in b.evidence[0].cycles:
        when = at.fromtimestamp(int(c.key.split(":")[1]) * 300, tz=at.tzinfo)
        events.append((when, "CYCLE", DegenFrame()))
    for a in b.evidence:
        for o in a.orders:
            for f in o.observation.fills if o.observation else ():
                events.append((f.occurred_at, "MARKET", DegenFrame(quotes=(f.quote,))))
    for value in (b.benchmarks[0].start, b.benchmarks[0].end):
        # Boundary observations are price benchmarks, not fabricated executable sizes.
        events.append((value.received_at, "MARKET", DegenFrame(underlyings=(value,))))
    tmp_path.chmod(0o700)
    with TapeRecorder(tmp_path / "baseline.tape", header_for(b)) as recorder:
        for when, kind, frame in sorted(events, key=lambda e: e[0]):
            recorder.append(frame, recorded_at=when, kind=kind)
        digest = recorder.seal()
    tape = load_tape(tmp_path / "baseline.tape")
    frames = {e.cycle_key: fingerprint(e.frame) for e in tape.events if e.kind == "CYCLE"}
    b = b.model_copy(
        update={
            "manifest": b.manifest.model_copy(
                update={
                    "sessions": (b.manifest.sessions[0].model_copy(update={"tape_hash": digest}),)
                }
            ),
            "evidence": tuple(
                a.model_copy(
                    update={
                        "tape_hash": digest,
                        "cycles": tuple(
                            c.model_copy(update={"frame_hash": frames[c.key]}) for c in a.cycles
                        ),
                    }
                )
                for a in b.evidence
            ),
        }
    )
    return b, tape


def test_independent_long_shares_include_spread_slippage_fees_and_allocations(tmp_path, native):
    b, tape = evidence(tmp_path, native)
    before = b.model_dump_json(), tape.model_dump_json()
    report = evaluate(b, tapes=(tape,))
    assert report["status"] == "COMPLETE_ARITHMETIC"
    baseline = report["eligible_underlying"]
    row = baseline["sessions"][0]
    assert [f["side"] for f in row["fills"]] == ["BUY", "SELL"]
    assert [f["quantity"] for f in row["fills"]] == [4, 4]
    assert [D(f["price"]) for f in row["fills"]] == [D("100.07"), D("97.94")]
    assert D(row["venue_fees"]) == D(".42")
    assert D(row["net_change"]) == D("-8.97")
    assert D(row["closing_settled_cash"]) == D("599.58")
    assert row["known_model_cost"] == "0"
    assert (
        row["fills"][1]["occurred_at"]
        > (native[2][0].intent.prepared_at + timedelta(seconds=2)).isoformat()
    )
    assert baseline["economic_conclusion"] == "INCONCLUSIVE"
    assert not baseline["execution_authority"] and not baseline["live_enabled"]
    assert before == (b.model_dump_json(), tape.model_dump_json())
    json.dumps(report)
    for arm in b.manifest.arms:
        assert D(row["paired_net_difference"][arm.arm]) == D(
            report["sessions"][0]["arms"][arm.arm]["net_change"]
        ) + D("8.97")


@pytest.mark.parametrize(
    "damage,reason",
    [
        ("size", "UNDERLYING_ENTRY_QUOTE_EVIDENCE_MISSING"),
        ("exit_size", "UNDERLYING_OPEN_BOUNDARY_POSITION_UNVALUED"),
    ],
)
def test_unknown_size_or_open_exposure_withholds_all_declared_totals(
    tmp_path, native, damage, reason
):
    b, tape = evidence(tmp_path, native, damage=damage)
    report = evaluate(b, tapes=(tape,))
    row = report["eligible_underlying"]["sessions"][0]
    assert reason in row["reasons"]
    assert report["status"] == "INCONCLUSIVE"
    assert report["eligible_underlying"]["net_change"] is None
    assert all(t["net_change"] is None for t in report["totals"].values())
    json.dumps(report)


@pytest.mark.parametrize("damage", ["zero_size", "entry_stale", "unfilled_limit"])
def test_nonexecutable_entries_never_become_fills(tmp_path, native, damage):
    b, tape = evidence(tmp_path, native, damage=damage)
    row = evaluate(b, tapes=(tape,))["eligible_underlying"]["sessions"][0]
    assert not row["fills"]
    assert row["closing_cash"] == "1000"
    assert row["decisions"][0]["status"] in {"UNFILLED", "CASH_STOP_BEFORE_FILL"}


@pytest.mark.parametrize("damage", ["partial", "repeat"])
def test_partial_exits_charge_order_fee_once_and_never_reuse_size(tmp_path, native, damage):
    b, tape = evidence(tmp_path, native, damage=damage)
    row = evaluate(b, tapes=(tape,))["eligible_underlying"]["sessions"][0]
    assert sum(f["quantity"] for f in row["fills"] if f["side"] == "SELL") == 4
    assert len(row["fills"]) == (3 if damage == "partial" else 2)
    assert D(row["venue_fees"]) == D(".42")


def test_baseline_requires_tape_and_explicit_costs(tmp_path, native):
    b, tape = evidence(tmp_path, native)
    assert evaluate(b)["eligible_underlying"]["status"] == "INCONCLUSIVE"
    b = b.model_copy(
        update={
            "manifest": b.manifest.model_copy(
                update={
                    "underlying_baseline": policy().model_copy(
                        update={"host_cost_per_session": None}
                    )
                }
            )
        }
    )
    row = evaluate(b, tapes=(tape,))["eligible_underlying"]["sessions"][0]
    assert "UNDERLYING_ALLOCATED_COST_UNKNOWN" in row["reasons"]
    assert row["net_change"] is None


def test_legacy_quote_and_manifest_hashes_are_unchanged():
    b = bundle_for()
    assert "underlying_baseline" not in b.manifest.model_dump()
    assert "underlying_settlements" not in b.model_dump()
    assert "bid_size" not in b.benchmarks[0].start.model_dump()
    assert "ask_size" not in b.benchmarks[0].start.model_dump()
    assert evaluate(b)["eligible_underlying"]["status"] == "NOT_ENROLLED"


def test_own_account_population_and_settlement_enrollment_required():
    b = bundle_for()
    for field, value in (
        ("account_id", b.manifest.arms[0].limits.account_id),
        ("population_id", b.manifest.arms[0].limits.population_id),
    ):
        m = b.manifest.model_copy(
            update={"underlying_baseline": policy().model_copy(update={field: value})}
        )
        with pytest.raises(ValueError, match="own account"):
            type(m).model_validate(m.model_dump())
    r = UnderlyingSettlement(
        receipt_id="one", occurred_at=b.manifest.sessions[0].opens_at, amount="1"
    )
    with pytest.raises(ValueError, match="enrolled baseline"):
        evaluate(b.model_copy(update={"underlying_settlements": (r,)}))


def test_put_opportunity_stays_cash_and_does_not_short(tmp_path, native):
    b, tape = evidence(tmp_path, native)
    account = _Account(b.manifest.arms[0], policy())
    source = b.evidence[0]
    order = source.orders[0]
    instrument = order.intent.instrument.model_copy(
        update={"contract": order.intent.instrument.contract.model_copy(update={"right": "PUT"})}
    )
    source = source.model_copy(
        update={
            "orders": (
                order.model_copy(
                    update={"intent": order.intent.model_copy(update={"instrument": instrument})}
                ),
            )
        }
    )
    row = account.session(b.manifest.sessions[0], source, tape, (), True)
    assert not row["fills"]
    assert row["decisions"][0]["status"] == "CASH_INELIGIBLE_DIRECTION_OR_INSTRUMENT"
    assert D(row["net_change"]) == D("-.03")


def test_continuous_cash_explicit_own_settlement_and_no_reset(tmp_path, native):
    b, tape = evidence(tmp_path, native)
    account = _Account(b.manifest.arms[0], policy())
    s = b.manifest.sessions[0]
    one = account.session(s, b.evidence[0], tape, (), True)
    assert D(one["closing_cash"]) == D("991.06")
    receipt = UnderlyingSettlement(
        receipt_id="baseline-proceeds", occurred_at=s.closes_at, amount="391.48"
    )
    two = account.session(s, b.evidence[0], tape, (receipt,), True)
    assert D(two["opening_cash"]) == D(one["closing_cash"])
    assert D(two["opening_settled_cash"]) == D(one["closing_cash"])
    assert D(two["closing_cash"]) == D("982.12")
    bad = account.session(
        s, b.evidence[0], tape, (receipt.model_copy(update={"amount": D(999)}),), True
    )
    assert "UNDERLYING_SETTLEMENT_EXCEEDS_UNSETTLED_CASH" in bad["reasons"]
    after = account.session(s, b.evidence[0], tape, (), True)
    assert "UNDERLYING_PRIOR_SESSION_INCOMPLETE" in after["reasons"]
    assert not after["fills"]


def test_installed_cli_reports_baseline_without_writing_source(tmp_path, native):
    b, _ = evidence(tmp_path, native)
    path = tmp_path / "bundle.json"
    path.write_text(b.model_dump_json())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "app.options.evaluation_cli",
            "--bundle",
            str(path),
            "--tape",
            str(tmp_path / "baseline.tape"),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert D(json.loads(run.stdout)["eligible_underlying"]["net_change"]) == D("-8.97")
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_private_decimal_context(tmp_path, native):
    b, tape = evidence(tmp_path, native)
    expected = evaluate(b, tapes=(tape,))
    with localcontext() as ctx:
        ctx.prec = 2
        assert evaluate(b, tapes=(tape,)) == expected


@pytest.mark.parametrize("kind", ["TIME", "LOW_PRICE", "REPEATED_SIZE", "RECEIPT_ONLY_CHANGE"])
def test_independent_exit_triggers_and_source_size_identity(tmp_path, native, kind):
    b, tape = evidence(tmp_path, native)
    source = b.evidence[0]
    at = source.orders[0].intent.prepared_at
    buy = source.orders[0]
    events = []
    for e in tape.events:
        underlyings = []
        for q in e.frame.underlyings:
            if at + timedelta(seconds=2) <= q.source_at <= at + timedelta(seconds=3):
                if kind == "TIME":
                    q = q.model_copy(update={"bid": D(101), "ask": D("101.01")})
                elif kind == "LOW_PRICE":
                    q = q.model_copy(update={"bid": D(1), "ask": D("1.01")})
                else:
                    q = q.model_copy(update={"bid_size": 2})
            underlyings.append(q)
        events.append(
            e.model_copy(
                update={"frame": e.frame.model_copy(update={"underlyings": tuple(underlyings)})}
            )
        )
        if (
            kind in {"REPEATED_SIZE", "RECEIPT_ONLY_CHANGE"}
            and e.recorded_at == at + timedelta(seconds=3)
            and underlyings
        ):
            q = underlyings[0]
            later = e.recorded_at + timedelta(milliseconds=100)
            if kind == "RECEIPT_ONLY_CHANGE":
                q = q.model_copy(update={"received_at": later})
            events.append(
                e.model_copy(update={"recorded_at": later, "frame": DegenFrame(underlyings=(q,))})
            )
    if kind == "TIME":
        source = source.model_copy(
            update={
                "orders": (
                    buy.model_copy(
                        update={
                            "intent": buy.intent.model_copy(
                                update={"exit_at": at + timedelta(seconds=2)}
                            )
                        }
                    ),
                )
            }
        )
    # The private accounting unit accepts already validated evidence; public tape validation
    # is exercised separately by evaluate and the installed CLI.
    tape = tape.model_copy(update={"events": tuple(events)})
    row = _Account(b.manifest.arms[0], policy()).session(
        b.manifest.sessions[0], source, tape, (), True
    )
    sales = [f for f in row["fills"] if f["side"] == "SELL"]
    if kind.startswith("REPEATED") or kind == "RECEIPT_ONLY_CHANGE":
        assert sum(f["quantity"] for f in sales) == 2
        assert row["closing_position"]["quantity"] == 2
        assert row["status"] == "INCONCLUSIVE"
    else:
        assert len(sales) == 1 and sales[0]["reason"] == ("TIME" if kind == "TIME" else "STOP")
        assert row["status"] == "COMPLETE"
        if kind == "LOW_PRICE":
            assert D(sales[0]["price"]) == D(".99")


@pytest.mark.parametrize("change", ["settled", "risk", "fee", "shares", "source"])
def test_independent_entry_budget_and_evidence_blockers(tmp_path, native, change):
    b, tape = evidence(tmp_path, native)
    p = policy()
    definition = b.manifest.arms[0]
    if change == "risk":
        definition = definition.model_copy(
            update={"policy": definition.policy.model_copy(update={"daily_loss_limit": D(99)})}
        )
    elif change == "fee":
        p = p.model_copy(update={"exit_fee_per_order": D(500)})
    elif change == "shares":
        p = p.model_copy(update={"max_shares": 1})
    account = _Account(definition, p)
    if change == "settled":
        account.settled = D(99)
    row = account.session(b.manifest.sessions[0], b.evidence[0], tape, (), change != "source")
    if change == "shares":
        assert row["fills"][0]["quantity"] == 1
    else:
        assert not row["fills"]
    if change == "source":
        assert row["status"] == "INCONCLUSIVE"


def test_public_multisession_cost_continuity_and_invalid_credit(tmp_path):
    from test_option_evaluation import two_sessions

    b = two_sessions()
    b = b.model_copy(
        update={"manifest": b.manifest.model_copy(update={"underlying_baseline": policy()})}
    )
    tapes, sessions, arms = [], [], []
    tmp_path.chmod(0o700)
    for s in b.manifest.sessions:
        single = b.model_copy(update={"manifest": b.manifest.model_copy(update={"sessions": (s,)})})
        benchmark = next(v for v in b.benchmarks if v.session_key == s.key)
        events = [
            (q.received_at, "MARKET", DegenFrame(underlyings=(q,)))
            for q in (benchmark.start, benchmark.end)
        ]
        for t in range(int(s.opens_at.timestamp()), int(s.closes_at.timestamp()), 300):
            events.append(
                (s.opens_at.fromtimestamp(t, tz=s.opens_at.tzinfo), "CYCLE", DegenFrame())
            )
        path = tmp_path / (s.key + ".tape")
        with TapeRecorder(path, header_for(single)) as recorder:
            for at, kind, frame in sorted(events, key=lambda e: e[0]):
                recorder.append(frame, recorded_at=at, kind=kind)
            digest = recorder.seal()
        tapes.append(load_tape(path))
        sessions.append(s.model_copy(update={"tape_hash": digest}))
        arms.extend(
            a.model_copy(
                update={
                    "tape_hash": digest,
                    "cycles": tuple(
                        c.model_copy(update={"frame_hash": fingerprint(DegenFrame())})
                        for c in a.cycles
                    ),
                }
            )
            for a in b.evidence
            if a.session_key == s.key
        )
    b = b.model_copy(
        update={
            "manifest": b.manifest.model_copy(update={"sessions": tuple(sessions)}),
            "evidence": tuple(arms),
        }
    )
    report = evaluate(b, tapes=tuple(tapes))
    assert report["status"] == "COMPLETE_ARITHMETIC", report
    assert D(report["eligible_underlying"]["net_change"]) == D("-.06")
    assert [r["opening_cash"] for r in report["eligible_underlying"]["sessions"]] == [
        "1000",
        "1000",
    ]
    receipt = UnderlyingSettlement(
        receipt_id="not-proceeds", occurred_at=sessions[1].opens_at, amount="1"
    )
    bad = evaluate(b.model_copy(update={"underlying_settlements": (receipt,)}), tapes=tuple(tapes))
    assert bad["status"] == "INCONCLUSIVE"
    assert bad["eligible_underlying"]["net_change"] is None
    assert bad["eligible_underlying"]["sessions"][1]["settlements"] == []
    with pytest.raises(ValueError, match="Unique between-session"):
        evaluate(
            b.model_copy(update={"underlying_settlements": (receipt, receipt)}), tapes=tuple(tapes)
        )


def test_native_replay_and_export_keep_baseline_opt_in(tmp_path):
    import asyncio

    from test_option_replay import settings_for, tape_for

    from app.options.evaluation_export import export_comparison
    from app.options.replay import run_replay

    tmp_path.chmod(0o700)
    tape = tape_for(tmp_path, full=True)
    settings = settings_for(tape)
    settings = settings.model_copy(
        update={"manifest": settings.manifest.model_copy(update={"underlying_baseline": policy()})}
    )
    result = asyncio.run(run_replay(settings, tape, tmp_path / "run"))
    baseline = result["report"]["eligible_underlying"]
    # The frozen $500 notional ceiling cannot buy one $600 share. No fraction or
    # hidden leverage is introduced merely to force the comparator to participate.
    assert baseline["status"] == "COMPLETE_ARITHMETIC"
    assert not baseline["sessions"][0]["fills"]
    assert baseline["sessions"][0]["decisions"][0]["status"] == "CASH_INSUFFICIENT_SETTLED_FUNDS"
    manifest = type(settings.manifest).model_validate(result["bundle"]["manifest"])
    sources = {
        arm: {
            "journal": str(tmp_path / "run" / arm / "sessions" / (tape.header.session_key + ".db")),
            "data_cost": ".01",
            "host_cost": ".02",
        }
        for arm in ("A", "B", "C")
    }
    exported = export_comparison(manifest, tape, sources)
    assert exported["report"]["eligible_underlying"] == baseline
