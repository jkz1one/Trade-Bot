"""Tool-less choices, durable cost receipts and original candidate authority."""

import asyncio
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_degen_options import AT, frame, policies
from test_execution_judgment import response, sdk_client
from test_option_execution import configuration as execution_configuration
from test_option_execution import intent_for, ledger

from app.execution.economics import CostPolicy, UsageEvidence
from app.execution.engine import ExecutionBlocked
from app.execution.judgment import JudgmentLimits
from app.options import judgment
from app.options.coordinator import DegenCoordinator
from app.options.engine import OptionExecution, fingerprint
from app.options.judgment import CandidateChoice, CandidatePacket, CandidateRequest, result_for
from app.options.judgment_worker import perform
from app.options.selection import admit_candidates
from app.options.venue import DurableOptionVenue


@contextmanager
def owned_model(path, *, limits=None, right="CALL", loss_limit=None):
    data, option_limits, policy = execution_configuration(
        right, cost_policy=CostPolicy(total_budget="1", daily_budget=".1")
    )
    if loss_limit is not None:
        policy = policy.model_copy(update={"daily_loss_limit": Decimal(loss_limit)})
    venue = DurableOptionVenue(path / "venue.db", limits=option_limits, capital=policy.capital)
    key = path / "model.key"
    key.write_text("fixture-only\n")
    key.chmod(0o600)
    times = [AT]
    with OptionExecution.open(
        path / "options.db", option_limits, policy, venue, now=AT, create=True
    ) as engine:
        assert engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        engine.assess(None, None, now=AT)
        setup, selection = policies()
        c = DegenCoordinator(
            engine,
            setup,
            selection,
            create=True,
            clock=lambda: times[0],
            judgment_limits=limits or JudgmentLimits(),
            key_file=key,
        )
        yield c, venue, data, times


def request_for(c, f=None):
    f = f or frame()
    plan = c.quote_plan(f.histories, f.inventories)
    with c.engine.journal.read() as db:
        account = c.engine._account(db, AT)
    candidates, _ = admit_candidates(
        plan["scans"][0],
        plan["plans"][0],
        f.quotes,
        f.underlyings[0],
        account,
        c.engine._effective_limits(),
        c.engine._session(f.quotes[0].instrument.contract, AT),
        now=AT,
    )
    return CandidateRequest(
        request_id="a" * 32,
        model=c.engine.policy.cost_policy.model,
        packet=CandidatePacket(
            cycle_key="degen:" + str(int(AT.timestamp()) // 300),
            as_of=AT,
            candidates=candidates,
            scans=plan["scans"],
            account=account,
            limits=c.engine._effective_limits(),
        ),
        limits=c.judgment_limits,
        configuration=judgment.configuration(c.engine.policy.cost_policy, c.judgment_limits),
        parent_pid=os.getpid(),
        deadline_monotonic=time.monotonic() + 30,
    )


def choice_for(request, action="SELECT", **changes):
    return CandidateChoice(
        action=action,
        candidate_id=request.packet.candidates[0].candidate_id if action == "SELECT" else None,
        thesis="Completed setup confirms the supplied candidate"
        if action == "SELECT"
        else "Preserve cash",
        **changes,
    )


def receipt_for(request, *, action="SELECT", **changes):
    return result_for(
        request,
        choice=choice_for(request, action),
        count=1000,
        usage=UsageEvidence(
            request_id="resp-options", model=request.model, input_tokens=1000, output_tokens=100
        ),
        **changes,
    )


def output_for(request, action="SELECT"):
    output = response()
    output["output"][0]["content"][0]["text"] = choice_for(request, action).model_dump_json()
    return output


@pytest.mark.parametrize(
    "damage",
    ["quantity", "price", "contract", "risk", "invalid_id", "hold_id", "missing_id", "blank"],
)
def test_choice_cannot_mutate_execution_authority(damage):
    value = {"action": "SELECT", "candidate_id": "a" * 64, "thesis": "Evidence"}
    if damage in {"quantity", "price", "contract", "risk"}:
        value[damage] = "1"
    elif damage == "invalid_id":
        value["candidate_id"] = "made-up"
    elif damage == "hold_id":
        value["action"] = "HOLD"
    elif damage == "missing_id":
        value["candidate_id"] = None
    else:
        value["thesis"] = " "
    with pytest.raises(ValidationError):
        CandidateChoice.model_validate(value)


@pytest.mark.parametrize("action", ["SELECT", "HOLD"])
def test_actual_sdk_counts_exact_toolless_payload_once(tmp_path, action):
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        client, calls = sdk_client(output=output_for(request, action))
        with client:
            result = perform(request, client)
        assert result.error is None and result.choice == choice_for(request, action)
        counted, generated = [body for _, body in calls]
        assert [path for path, _ in calls] == ["/v1/responses/input_tokens", "/v1/responses"]
        assert counted == {
            k: v
            for k, v in generated.items()
            if k not in {"max_output_tokens", "store", "background", "stream"}
        }
        assert counted == judgment.request_content(request)
        assert generated["tools"] == [] and generated["tool_choice"] == "none"
        assert generated["truncation"] == "disabled" and generated["text"]["format"]["strict"]
        assert generated["store"] is generated["background"] is generated["stream"] is False
        assert (
            result.diagnostics.input_count.completed == result.diagnostics.generation.completed == 1
        )


@pytest.mark.parametrize(
    "damage",
    ["refusal", "incomplete", "tool", "fragment", "schema", "unknown_id", "provider_error"],
)
def test_failed_output_preserves_returned_usage_as_hold(tmp_path, damage):
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        output = output_for(request)
        if damage == "refusal":
            output["output"][0]["content"] = [{"type": "refusal", "refusal": "secret"}]
        elif damage == "incomplete":
            output["status"] = "incomplete"
        elif damage == "tool":
            output["output"] = [
                {
                    "type": "function_call",
                    "id": "fc",
                    "name": "place_order",
                    "call_id": "call",
                    "arguments": "{}",
                    "status": "completed",
                }
            ]
        elif damage == "fragment":
            output["output"].append(output["output"][0].copy())
        elif damage == "schema":
            output["output"][0]["content"][0]["text"] = '{"action":"SELECT","quantity":100}'
        elif damage == "unknown_id":
            output["output"][0]["content"][0]["text"] = CandidateChoice(
                action="SELECT", candidate_id="f" * 64, thesis="unknown"
            ).model_dump_json()
        else:
            output["error"] = {"code": "server_error", "message": "secret"}
        client, calls = sdk_client(output=output)
        with client:
            result = perform(request, client)
        assert result.error and result.choice.action == "HOLD"
        assert result.usage.input_tokens == 1000 and result.usage.output_tokens == 100
        assert len(calls) == 2 and "secret" not in result.model_dump_json()


@pytest.mark.parametrize("count", [0, -1, True, "1000", 16001])
def test_input_count_failure_prevents_generation(tmp_path, count):
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        client, calls = sdk_client(count=count)
        with client:
            result = perform(request, client)
        assert result.error and result.usage is None and result.choice.action == "HOLD"
        assert len(calls) == 1


@pytest.mark.parametrize("damage", ["expired", "configuration", "quota"])
def test_invalid_request_or_provider_error_never_retries(tmp_path, damage):
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        if damage == "expired":
            request = request.model_copy(update={"deadline_monotonic": time.monotonic() - 1})
        elif damage == "configuration":
            request = request.model_copy(update={"configuration": {}})
        client, calls = sdk_client(failure=damage == "quota")
        with client:
            result = perform(request, client)
        assert result.error and result.usage is None
        assert len(calls) == (1 if damage == "quota" else 0)


@pytest.mark.anyio
@pytest.mark.parametrize("right", ["CALL", "PUT"])
async def test_selected_candidate_uses_native_paper_and_original_ceilings(
    tmp_path, monkeypatch, right
):
    requests = []

    async def run(request, key):
        assert key == "fixture-only"
        requests.append(request)
        return receipt_for(request)

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path, right=right) as (c, venue, _, _):
        f = frame(right)
        result = await c.cycle(f)
        assert result["status"] == "OPEN", result
        original = requests[0].packet.candidates[0]
        intent = intent_for(c.engine, result["client_id"])
        assert intent.instrument == original.instrument
        assert intent.quantity <= original.admission.quantity
        assert intent.limit_price == original.admission.limit_price
        assert intent.approved_entry_debit <= original.admission.entry_debit
        assert intent.approved_full_premium_loss <= original.admission.full_premium_loss
        assert intent.approval_expires_at == original.admission.valid_until
        assert intent.original_underlying_invalidation == original.proposal.underlying_invalidation
        assert ledger(c.engine).position is None  # Accepted orders are not fills.
        venue.fill(intent, intent.quantity, f.quotes[0], AT, fill_id="model-fill")
        assert c.engine.reconcile(venue.snapshot(AT), now=AT)["reconciled"]
        assert ledger(c.engine).position.contract.right == right
        economics = c.engine.journal.report(now=AT)["economics"]
        assert economics["known_cost"] == "0.00015" and economics["unknown_calls"] == 0
        with c.engine.journal.read() as db:
            approval = json.loads(
                db.execute("SELECT approval_json FROM execution_orders").fetchone()[0]
            )
            assert approval["origin"] == "MODEL" and approval[
                "ceiling"
            ] == original.admission.model_dump(mode="json")
            assert db.execute("SELECT packet_hash FROM execution_model_calls").fetchone()[
                0
            ] == fingerprint(judgment.request_content(requests[0]))
        assert await c.cycle(f) == result and len(requests) == 1
        assert len(venue.snapshot(AT).orders) == 1


@pytest.mark.anyio
async def test_hold_is_costed_durable_and_deduplicated(tmp_path, monkeypatch):
    calls = []

    async def run(request, key):
        calls.append(request)
        return receipt_for(request, action="HOLD")

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path) as (c, venue, _, _):
        result = await c.cycle(frame())
        assert result["status"] == "HOLD" and result["model_result"]["choice"]["action"] == "HOLD"
        assert not venue.snapshot(AT).orders
        assert c.engine.journal.report(now=AT)["economics"]["known_cost"] == "0.00015"
        with c.engine.journal.read() as db:
            decision = json.loads(
                db.execute("SELECT inputs_json FROM execution_option_decisions").fetchone()[0]
            )
            assert decision["origin"] == "MODEL" and decision["proposal"]["action"] == "HOLD"
        assert await c.cycle(frame()) == result and len(calls) == 1
        assert c.report()["cycles"][0]["result"] == result


@pytest.mark.anyio
@pytest.mark.parametrize(
    "damage",
    [
        "count",
        "input_ceiling",
        "output_ceiling",
        "unknown_id",
        "refusal",
        "expired_lease",
        "slot_advance",
        "deadline",
    ],
)
async def test_rejected_known_usage_is_charged_without_order(tmp_path, monkeypatch, damage):
    model_limits = (
        JudgmentLimits(process_timeout_seconds=0.02, request_timeout_seconds=0.01)
        if damage == "deadline"
        else None
    )
    with owned_model(tmp_path, limits=model_limits) as (c, venue, _, times):

        async def run(request, key):
            result = receipt_for(request)
            if damage == "count":
                result = result.model_copy(update={"counted_input_tokens": 999})
            elif damage in {"input_ceiling", "output_ceiling"}:
                usage = result.usage.model_copy(
                    update={"input_tokens": 16001}
                    if damage == "input_ceiling"
                    else {"output_tokens": 1025}
                )
                result = result.model_copy(update={"usage": usage})
            elif damage == "unknown_id":
                result = result.model_copy(
                    update={
                        "choice": CandidateChoice(
                            action="SELECT", candidate_id="f" * 64, thesis="Unknown"
                        )
                    }
                )
            elif damage == "refusal":
                result = result_for(request, usage=result.usage, count=1000, error="ValueError")
            elif damage == "expired_lease":
                times[0] = request.packet.candidates[0].admission.valid_until
            elif damage == "slot_advance":
                times[0] += timedelta(minutes=5)
            else:
                await asyncio.sleep(max(0, request.deadline_monotonic - time.monotonic()) + 0.01)
            return result

        monkeypatch.setattr(judgment, "run_candidate_process", run)
        result = await c.cycle(frame())
        assert result["status"] == "HOLD", result
        assert not venue.snapshot(times[0]).orders
        economics = c.engine.journal.report(now=times[0])["economics"]
        assert Decimal(economics["known_cost"]) > 0 and economics["unknown_calls"] == 0
        assert result["model_result"]["usage"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "damage",
    ["timeout", "protocol", "wrong_model", "no_usage", "clock_regression", "duplicate_receipt"],
)
async def test_unknown_attempt_retains_evidence_halts_and_never_replays(
    tmp_path, monkeypatch, damage
):
    with owned_model(tmp_path) as (c, venue, _, times):
        calls = []

        async def run(request, key):
            calls.append(request)
            if damage == "timeout":
                raise TimeoutError("secret")
            result = receipt_for(request)
            if damage == "protocol":
                return result.model_copy(update={"request_id": "b" * 32})
            if damage == "wrong_model":
                return result.model_copy(
                    update={"usage": result.usage.model_copy(update={"model": "wrong-model"})}
                )
            if damage == "no_usage":
                return result_for(request, error="APIError")
            if damage == "clock_regression":
                times[0] -= timedelta(seconds=1)
            if damage == "duplicate_receipt":
                # Provider IDs cannot settle two distinct durable calls.
                with c.engine.journal.write() as db:
                    db.execute(
                        "INSERT INTO execution_model_calls VALUES('other',?, ?, ?, 'resp-options', ?, '0.00015')",
                        ("a" * 64, AT.isoformat(), result.usage.model_dump_json(), "b" * 64),
                    )
            return result

        monkeypatch.setattr(judgment, "run_candidate_process", run)
        result = await c.cycle(frame())
        assert result["status"] == "HOLD" and not venue.snapshot(times[0]).orders
        report = c.engine.journal.report(now=times[0])
        assert report["economics"]["unknown_calls"] == 1 and report["halted"]
        assert "secret" not in json.dumps(result)
        times[0] = AT
        assert await c.cycle(frame()) == result and len(calls) == 1
        if damage in {"wrong_model", "no_usage", "clock_regression", "duplicate_receipt"}:
            assert result["model_result"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "damage", ["missing", "public", "symlink", "stale_history", "bad_coverage", "no_setup"]
)
async def test_no_model_attempt_without_eligible_data_and_private_key(
    tmp_path, monkeypatch, damage
):
    async def forbidden(*args):
        pytest.fail("No model attempt permitted")

    monkeypatch.setattr(judgment, "run_candidate_process", forbidden)
    with owned_model(tmp_path) as (c, venue, _, _):
        f = frame()
        if damage == "missing":
            c.key_file.unlink()
        elif damage == "public":
            c.key_file.chmod(0o644)
        elif damage == "symlink":
            target = c.key_file.with_suffix(".actual")
            c.key_file.rename(target)
            c.key_file.symlink_to(target)
        elif damage == "stale_history":
            h = f.histories[0].model_copy(update={"source_at": AT - timedelta(minutes=10)})
            f = f.model_copy(update={"histories": (h,)})
        elif damage == "bad_coverage":
            f = f.model_copy(update={"quotes": ()})
        else:
            f = f.model_copy(update={"inventories": ()})
        result = await c.cycle(f)
        assert result["status"] == "HOLD" and not venue.snapshot(AT).orders
        assert c.engine.journal.report(now=AT)["economics"]["unknown_calls"] == 0
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_model_calls").fetchone()[0] == 0


def test_model_configuration_freezes_new_cohort_and_keeps_legacy_default(tmp_path):
    from test_degen_options import owned_strategy

    with owned_strategy(tmp_path / "legacy") as (c, _, _, _, _, _):
        assert "model" not in c.report()["strategy"]
        c.engine._degen_owner = None
        with pytest.raises(ValueError, match="frozen cost policy"):
            DegenCoordinator(
                c.engine,
                c.policy,
                c.selection,
                judgment_limits=JudgmentLimits(),
                key_file=tmp_path / "key",
            )
    with owned_model(tmp_path / "model") as (c, _, _, _):
        c.engine._degen_owner = None
        with pytest.raises(ExecutionBlocked, match="FROZEN_DEGEN"):
            DegenCoordinator(c.engine, c.policy, c.selection)
        reopened = DegenCoordinator(
            c.engine, c.policy, c.selection, judgment_limits=c.judgment_limits, key_file=c.key_file
        )
        assert "model" in reopened.report()["strategy"]
        reopened.key_file = tmp_path / "different"
        with pytest.raises(ExecutionBlocked, match="FROZEN_DEGEN_STRATEGY_CHANGED"):
            reopened.report()


def test_token_ceiling_must_fit_frozen_reservation(tmp_path):
    with owned_model(tmp_path) as (c, _, _, _):
        costs = c.engine.policy.cost_policy.model_copy(update={"max_call_cost": Decimal(".001")})
        with pytest.raises(ValueError, match="reservation"):
            judgment.configuration(costs, c.judgment_limits)


@pytest.mark.anyio
async def test_model_wait_does_not_lock_fast_supervision_or_same_slot(tmp_path, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def run(request, key):
        entered.set()
        await release.wait()
        return receipt_for(request, action="HOLD")

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path) as (c, _, _, _):
        task = asyncio.create_task(c.cycle(frame()))
        await asyncio.wait_for(entered.wait(), 3)
        assert (await c.cycle(frame()))["status"] == "IN_PROGRESS"
        async with asyncio.timeout(2):
            supervised = await c.supervise()
        assert supervised["status"] == "HEALTHY", supervised
        release.set()
        assert (await task)["status"] == "HOLD"


@pytest.mark.anyio
async def test_protective_exit_never_waits_for_model_or_key(tmp_path, monkeypatch):
    calls = []

    async def run(request, key):
        calls.append(request)
        return receipt_for(request)

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path) as (c, venue, _, times):
        result = await c.cycle(frame())
        assert result["status"] == "OPEN", result
        buy = intent_for(c.engine, result["client_id"])
        venue.fill(buy, buy.quantity, frame().quotes[0], AT, fill_id="protective-fill")
        c.key_file.unlink()
        times[0] += timedelta(seconds=1)
        f = frame()
        underlying = f.underlyings[0].model_copy(
            update={
                "bid": Decimal(590),
                "ask": Decimal("590.01"),
                "source_at": times[0],
                "received_at": times[0],
            }
        )
        quote = f.quotes[0].model_copy(update={"source_at": times[0], "received_at": times[0]})
        supervised = await c.supervise((quote,), (underlying,))
        assert (
            supervised["status"] == "OPEN"
            and supervised["exit_reason"] == "UNDERLYING_INVALIDATION"
        ), supervised
        assert intent_for(c.engine, supervised["client_id"]).side == "SELL"
        assert venue.submit_count == 2 and len(calls) == 1


@pytest.mark.parametrize(
    "damage", ["price", "quantity", "debit", "premium", "expired", "wrong_contract"]
)
def test_prepare_cannot_increase_original_admission_or_renew_lease(tmp_path, damage):
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        candidate = request.packet.candidates[0]
        original = candidate.admission
        changes = {
            "price": {"limit_price": original.limit_price - Decimal(".01")},
            "quantity": {"quantity": original.quantity - 1},
            "debit": {"entry_debit": original.entry_debit - Decimal(".01")},
            "premium": {"full_premium_loss": original.full_premium_loss - Decimal(".01")},
            "expired": {"valid_until": AT},
            "wrong_contract": {"contract_id": "wrong"},
        }[damage]
        ceiling = original.model_copy(update=changes)
        f = frame()
        prepared = c.engine.prepare(
            "bounded", candidate.proposal, f.quotes[0], f.underlyings[0], now=AT, ceiling=ceiling
        )
        assert prepared["status"] == "REJECTED", prepared
        with c.engine.journal.read() as db:
            assert db.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 0


def test_prepare_keeps_original_deadline_and_identity_after_wait(tmp_path):
    with owned_model(tmp_path) as (c, _, _, _):
        candidate = request_for(c).packet.candidates[0]
        at = AT + timedelta(seconds=1)
        f = frame()
        result = c.engine.prepare(
            "bounded",
            candidate.proposal,
            f.quotes[0],
            f.underlyings[0],
            now=at,
            ceiling=candidate.admission,
        )
        assert result["status"] == "PREPARED", result
        assert (
            intent_for(c.engine, result["client_id"]).approval_expires_at
            == candidate.admission.valid_until
        )
        assert (
            c.engine.prepare(
                "bounded",
                candidate.proposal,
                f.quotes[0],
                f.underlyings[0],
                now=at,
                ceiling=candidate.admission,
            )
            == result
        )
        with pytest.raises(ExecutionBlocked, match="IDENTITY_CONFLICT"):
            c.engine.prepare("bounded", candidate.proposal, f.quotes[0], f.underlyings[0], now=at)


@pytest.mark.anyio
async def test_native_protocol_has_fixed_entrypoint_and_no_broker_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ROBINHOOD_TOKEN", "broker-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.invalid")
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        expected = receipt_for(request)
        real_spawn = asyncio.create_subprocess_exec
        source = (
            "import json,sys,os\nr=json.load(sys.stdin)\nassert os.environ['OPENAI_API_KEY']=='fixture-only'\nassert 'ROBINHOOD_TOKEN' not in os.environ\nassert 'OPENAI_BASE_URL' not in os.environ\nassert r['parent_pid']==os.getppid()\n"
            + f"sys.stdout.write({expected.model_dump_json()!r})"
        )

        async def spawn(*args, **kwargs):
            assert args == (sys.executable, "-I", "-m", "app.options.judgment_worker")
            assert set(kwargs["env"]) <= {"PATH", "LANG", "LC_ALL", "OPENAI_API_KEY"}
            return await real_spawn(sys.executable, "-I", "-c", source, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        assert await judgment.run_candidate_process(request, "fixture-only") == expected


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["stall", "overflow", "invalid", "lineage", "exit"])
async def test_native_failure_is_bounded_reaped_and_unknown(tmp_path, monkeypatch, failure):
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    real_spawn = asyncio.create_subprocess_exec
    children = []
    with owned_model(
        tmp_path, limits=JudgmentLimits(process_timeout_seconds=0.5, request_timeout_seconds=0.2)
    ) as (c, venue, _, _):
        source = "import sys,time,signal\nsys.stdin.read()\n"
        if failure == "stall":
            source += "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)"
        elif failure == "overflow":
            source += f"sys.stdout.write('x'*{judgment.MAX_RESPONSE_BYTES * 2})"
        elif failure == "invalid":
            source += "sys.stdout.write('{}')"
        elif failure == "lineage":
            result = receipt_for(request_for(c)).model_copy(update={"request_id": "b" * 32})
            source += f"sys.stdout.write({result.model_dump_json()!r})"
        else:
            source += "sys.exit(8)"

        async def spawn(*args, **kwargs):
            if args[-1] != "app.options.judgment_worker":
                return await real_spawn(*args, **kwargs)
            child = await real_spawn(sys.executable, "-I", "-c", source, **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        result = await c.cycle(frame())
        assert result["status"] == "HOLD" and result["reason"] == "OPTION_MODEL_COST_UNKNOWN"
        assert not venue.snapshot(AT).orders
        assert c.engine.journal.report(now=AT)["economics"]["unknown_calls"] == 1
        assert children[0].returncode is not None


@pytest.mark.anyio
async def test_repeated_cancellation_reaps_child_and_does_not_replay(tmp_path, monkeypatch):
    from app.execution import process

    monkeypatch.setattr(process, "TERMINATION_GRACE_SECONDS", 0.05)
    real_spawn = asyncio.create_subprocess_exec
    children = []
    pid_file = tmp_path / "pid"
    source = f"import pathlib,os,sys,signal,time\nsys.stdin.read()\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\npathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(60)"

    async def spawn(*args, **kwargs):
        if args[-1] != "app.options.judgment_worker":
            return await real_spawn(*args, **kwargs)
        child = await real_spawn(sys.executable, "-I", "-c", source, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with owned_model(tmp_path) as (c, _, _, _):
        task = asyncio.create_task(c.cycle(frame()))
        async with asyncio.timeout(3):
            while not pid_file.exists():
                await asyncio.sleep(0.005)
        pid = int(pid_file.read_text())
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert children[0].returncode is not None
        result = await c.cycle(frame())
        assert result["reason"] == "DEGEN_CYCLE_INTERRUPTED" and result["model_request"]
        assert c.engine.journal.report(now=AT)["economics"]["unknown_calls"] == 1
        assert len(children) == 1


@pytest.mark.anyio
async def test_model_cost_can_reduce_fresh_software_quantity(tmp_path, monkeypatch):
    # Exactly four full-premium reservations fit before a nonzero model charge.
    with owned_model(tmp_path) as (c, _, _, _):
        original = request_for(c).packet.candidates[0].admission
        exact_loss = str(original.full_premium_loss)
    separate = tmp_path / "reduced"
    with owned_model(separate, loss_limit=exact_loss) as (c, _, _, _):
        requests = []

        async def run(request, key):
            requests.append(request)
            return receipt_for(request)

        monkeypatch.setattr(judgment, "run_candidate_process", run)
        result = await c.cycle(frame())
        assert result["status"] == "OPEN", result
        assert requests[0].packet.candidates[0].admission.quantity == 4
        assert intent_for(c.engine, result["client_id"]).quantity == 3


@pytest.mark.anyio
async def test_admission_storage_failure_prevents_model_launch(tmp_path, monkeypatch):
    async def forbidden(*args):
        pytest.fail("Durable attempt must commit before launching")

    monkeypatch.setattr(judgment, "run_candidate_process", forbidden)
    with owned_model(tmp_path) as (c, _, _, _):
        with c.engine.journal.write() as db:
            db.execute(
                "CREATE TRIGGER execution_fail_option_model BEFORE INSERT ON execution_model_calls BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
            )
        result = await c.cycle(frame())
        assert result["status"] == "HOLD" and result["error_class"] == "IntegrityError"
        assert c.engine.journal.report(now=AT)["economics"]["unknown_calls"] == 0


@pytest.mark.anyio
async def test_receipt_storage_failure_retains_returned_evidence_without_order(
    tmp_path, monkeypatch
):
    async def run(request, key):
        return receipt_for(request)

    monkeypatch.setattr(judgment, "run_candidate_process", run)
    with owned_model(tmp_path) as (c, venue, _, _):
        with c.engine.journal.write() as db:
            db.execute(
                "CREATE TRIGGER execution_fail_option_usage BEFORE UPDATE OF cost ON execution_model_calls BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
            )
        result = await c.cycle(frame())
        assert (
            result["status"] == "HOLD"
            and result["model_result"]["usage"]["request_id"] == "resp-options"
        )
        assert c.engine.journal.report(now=AT)["economics"]["unknown_calls"] == 1
        assert not venue.snapshot(AT).orders


@pytest.mark.anyio
async def test_actual_native_worker_main_with_mocked_sdk_transport(tmp_path, monkeypatch):
    with owned_model(tmp_path) as (c, _, _, _):
        request = request_for(c)
        output = output_for(request)
        source = f"""import json,os,httpx2
from openai import OpenAI
from app.options import judgment_worker as worker
output=json.loads({json.dumps(output)!r})
calls=[]
def transport(request):
 body=json.loads(request.content)
 calls.append(body)
 if request.url.path.endswith("input_tokens"):
  return httpx2.Response(200,json={{"object":"response.input_tokens","input_tokens":1000}})
 assert calls[0]=={{k:v for k,v in body.items() if k not in {{"max_output_tokens","store","background","stream"}}}}
 assert body['tools']==[] and body['tool_choice']=='none'
 return httpx2.Response(200,json=output)
def client(**kwargs):
 assert kwargs['base_url']=='https://api.openai.com/v1' and kwargs['max_retries']==0
 assert kwargs['api_key']=='fixture-only'
 return OpenAI(**kwargs,http_client=httpx2.Client(transport=httpx2.MockTransport(transport)))
worker.OpenAI=client
raise SystemExit(worker.main())
"""
        real_spawn = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            assert args == (sys.executable, "-I", "-m", "app.options.judgment_worker")
            return await real_spawn(sys.executable, "-I", "-c", source, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        result = await judgment.run_candidate_process(request, "fixture-only")
        assert result.choice == choice_for(request) and result.usage.request_id == "resp-test"
        assert (
            result.diagnostics.input_count.completed == result.diagnostics.generation.completed == 1
        )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper owns orphan cleanup")
def test_actual_parent_sigkill_keeps_unknown_attempt_and_ends_native_worker(tmp_path):
    import ctypes
    import subprocess

    with owned_model(tmp_path) as (c, venue, _, _):
        option_limits, policy = c.engine.limits, c.engine.policy
        setup, selection = c.policy, c.selection
        model_limits, key = c.judgment_limits, c.key_file
        journal_path, venue_path = c.engine.journal.path, venue.path
    marker = tmp_path / "child.pid"
    worker_source = f"""import os,time,signal
from pathlib import Path
from app.options import judgment_worker as worker
class Blocked:
 def __enter__(self):
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  Path({str(marker)!r}).write_text(str(os.getpid()))
  time.sleep(60)
 def __exit__(self,*args): pass
worker.OpenAI=lambda **kwargs: Blocked()
raise SystemExit(worker.main())
"""
    parent_source = f"""import asyncio,sys
from datetime import datetime
from app.options.engine import OptionExecution
from app.options.models import OptionLimits
from app.options.lifecycle import OptionExecutionPolicy
from app.options.venue import DurableOptionVenue
from app.options.coordinator import DegenCoordinator,DegenFrame
from app.options.degen import DegenPolicy
from app.options.selection import ContractSelectionPolicy
from app.execution.judgment import JudgmentLimits
real_spawn=asyncio.create_subprocess_exec
async def spawn(*args,**kwargs):
 if args[-1]=='app.options.judgment_worker':
  return await real_spawn(sys.executable,'-I','-c',{worker_source!r},**kwargs)
 return await real_spawn(*args,**kwargs)
asyncio.create_subprocess_exec=spawn
at=datetime.fromisoformat({AT.isoformat()!r})
venue=DurableOptionVenue({str(venue_path)!r})
with OptionExecution.open({str(journal_path)!r},OptionLimits.model_validate_json({option_limits.model_dump_json()!r}),OptionExecutionPolicy.model_validate_json({policy.model_dump_json()!r}),venue,now=at) as engine:
 c=DegenCoordinator(engine,DegenPolicy.model_validate_json({setup.model_dump_json()!r}),ContractSelectionPolicy.model_validate_json({selection.model_dump_json()!r}),clock=lambda:at,judgment_limits=JudgmentLimits.model_validate_json({model_limits.model_dump_json()!r}),key_file={str(key)!r})
 asyncio.run(c.cycle(DegenFrame.model_validate_json({frame().model_dump_json()!r})))
"""
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    parent = subprocess.Popen(
        [sys.executable, "-I", "-c", parent_source],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid, reaped = None, False
    try:
        deadline = time.monotonic() + 10
        while not marker.exists():
            assert parent.poll() is None and time.monotonic() < deadline
            time.sleep(0.025)
        pid = int(marker.read_text())
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            got, status = os.waitpid(pid, os.WNOHANG)
            if got:
                reaped = True
                assert os.waitstatus_to_exitcode(status) == 99
                break
            time.sleep(0.025)
        assert reaped, "Parent-death watcher left model child alive"
        with OptionExecution.open(
            journal_path, option_limits, policy, DurableOptionVenue(venue_path), now=AT
        ) as engine:
            reopened = DegenCoordinator(
                engine,
                setup,
                selection,
                clock=lambda: AT,
                judgment_limits=model_limits,
                key_file=key,
            )
            result = reopened.report()["cycles"][0]["result"]
            assert result["status"] == "INTERRUPTED" and result["model_request"]
            assert engine.journal.report(now=AT)["economics"]["unknown_calls"] == 1
            assert asyncio.run(reopened.cycle(frame())) == result
            assert not DurableOptionVenue(venue_path).snapshot(AT).orders
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if pid and not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0


@pytest.mark.anyio
async def test_valid_selection_cannot_override_concurrent_entry_halt(tmp_path, monkeypatch):
    with owned_model(tmp_path) as (c, venue, _, _):

        async def run(request, key):
            with c.engine.journal.write() as db:
                c.engine._halt(db, "REVIEW_REQUIRED", AT)
            return receipt_for(request)

        monkeypatch.setattr(judgment, "run_candidate_process", run)
        result = await c.cycle(frame())
        assert result["status"] == "HOLD"
        assert result["reason"] == "FRESH_EXECUTION_ADMISSION_REJECTED", result
        assert result["prepared"]["status"] == "REJECTED"
        assert not venue.snapshot(AT).orders
        assert c.engine.journal.report(now=AT)["economics"]["known_cost"] == "0.00015"
