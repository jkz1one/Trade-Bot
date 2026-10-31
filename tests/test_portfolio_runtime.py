"""Scope and mixed stored runtime evidence share the audited delivery sequence."""

import asyncio
from datetime import timedelta
from pathlib import Path

from test_option_runtime import enable, policy, step
from test_option_scope_arbitration import shared

from app.options.coordinator import DegenFrame
from app.options.runtime import OptionRuntime
from app.options.runtime_models import PortfolioRuntimePacket


def test_scope_portfolio_reconnect_gap_retains_both_delivery_contracts(tmp_path):
    with shared(tmp_path, portfolio=True) as (c, v, times, _frame):
        runtime = OptionRuntime(
            c,
            policy(
                tmp_path,
                mixed_inputs="mixed-runtime-inputs-v1",
                scope_inputs="scope-runtime-inputs-v1",
                simulated_fills="mixed-quote-fills-v1",
            ),
            create=True,
        )
        enable(runtime)
        for seq in (1, 3):
            packet = PortfolioRuntimePacket(
                population_id=c.engine.limits.population_id,
                sequence=seq,
                recorded_at=times[0],
                kind="MARKET",
                frame=DegenFrame(portfolio_version="portfolio-frame-v2"),
            )
            path = Path(runtime.policy.feed_file)
            path.write_text(packet.model_dump_json())
            path.chmod(0o600)
            asyncio.run(step(runtime))
            times[0] += timedelta(seconds=1)
        from app.mixed.runtime import stored_inputs
        from app.options.scope_runtime import stored_inputs as scope_inputs

        with c.engine.journal.read() as db:
            assert stored_inputs(db, times[0])["statuses"] == {"DELIVERED": 2}
            assert scope_inputs(db, times[0])["statuses"] == {"OBSERVED": 2}
        assert v.submit_count == 0
