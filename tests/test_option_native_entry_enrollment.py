"""Native cost linkage cannot retrofit old owners or broaden replay contracts."""

import asyncio

import pytest
from test_option_scope_ai import ai_owner


def test_existing_owner_cannot_add_later_entry_enrollment(tmp_path, monkeypatch):
    from app.options.engine import OptionExecution
    from app.options.venue import DurableOptionVenue

    with ai_owner(tmp_path, monkeypatch) as (c, _, times, _, _):
        limits, policy, at = c.engine.limits, c.engine.policy, times[0]
    changed = policy.model_copy(
        update={
            "loss_control": policy.loss_control.model_copy(
                update={"entry_cost_attribution": "later-flat-entry-v1"}
            )
        }
    )
    with (
        pytest.raises(ValueError, match="configuration is immutable"),
        OptionExecution.open(
            tmp_path / "options.db",
            limits,
            changed,
            DurableOptionVenue(tmp_path / "venue.db"),
            now=at,
        ),
    ):
        pass


def test_native_attribution_marker_cannot_enter_scope_replay(tmp_path):
    from test_option_scope_model_replay import request

    from app.options.scope_model_replay import ScopeModelReplay

    original = request(tmp_path, arm="C")
    execution = original.execution.model_copy(
        update={
            "loss_control": original.execution.loss_control.model_copy(
                update={"entry_cost_attribution": "later-flat-entry-v1"}
            )
        }
    )
    with pytest.raises(ValueError):
        ScopeModelReplay.model_validate(original.model_dump() | {"execution": execution})


@pytest.mark.parametrize("cancel", [False, True])
def test_paid_refresh_cannot_cancel_or_accept_incomplete_protection(tmp_path, monkeypatch, cancel):
    from test_option_runtime import enable, policy

    from app.execution.engine import ExecutionBlocked
    from app.options.runtime import OptionRuntime

    with ai_owner(tmp_path, monkeypatch, later_entry=True) as (c, _, _, _, _):
        runtime = OptionRuntime(
            c, policy(tmp_path, scope_inputs="scope-runtime-inputs-v1"), create=True
        )
        enable(runtime)

        async def exercise():
            pending = asyncio.get_running_loop().create_future()
            runtime._scope_tick = pending
            task = asyncio.create_task(runtime.scope.fresh("first"))
            await asyncio.sleep(0)
            assert not task.done()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not pending.cancelled() and not pending.done()
            pending.set_result(False)
            with pytest.raises(ExecutionBlocked, match="PROTECTION_TICK_INCOMPLETE"):
                if cancel:
                    await runtime.scope.fresh("first")
                else:
                    await task

        asyncio.run(exercise())
