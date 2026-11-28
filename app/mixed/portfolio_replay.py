"""Create-only native portfolio replay of explicit normalized packets; no external calls."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import OptionExecution, fingerprint
from app.options.models import OptionRecord
from app.options.runtime import OptionRuntime
from app.options.runtime_cli import _coordinator, _save, initialize
from app.options.runtime_models import PortfolioRuntimePacket, RuntimeSettings
from app.options.venue import DurableOptionVenue


class PortfolioReplay(OptionRecord):
    version: Literal["portfolio-native-replay-v2"] = "portfolio-native-replay-v2"
    settings: RuntimeSettings
    packets: tuple[PortfolioRuntimePacket, ...] = Field(min_length=1, max_length=2500)

    @model_validator(mode="after")
    def explicit(self):
        s = self.settings
        if (
            s.execution.mixed_owner is None
            or s.execution.mixed_owner.portfolio is None
            or s.execution.cost_policy is not None
            or s.judgment_limits is not None
            or s.key_file is not None
            or s.runtime.operator_key_file is not None
            or s.runtime.simulated_fills is None
        ):
            raise ValueError("Explicit credential-free deterministic portfolio replay required")
        last = None
        for p in self.packets:
            if p.population_id != s.limits.population_id or (
                last and (p.sequence <= last.sequence or p.recorded_at < last.recorded_at)
            ):
                raise ValueError("Original ordered portfolio delivery required")
            last = p
        return self


async def replay(directory, request):
    """Preserve source clocks and native receipts, including unavailable data and gaps."""
    request = PortfolioReplay.model_validate(request.model_dump())
    directory = Path(directory)
    if not directory.is_absolute() or directory.exists():
        raise ValueError("Explicit new absolute replay directory required")
    at = [request.packets[0].recorded_at]
    settings = request.settings.model_copy(
        update={
            "runtime": request.settings.runtime.model_copy(
                update={"feed_file": str(directory / "feed.json")}
            )
        }
    )
    initialize(directory, settings, clock=lambda: at[0])
    _save(directory / "request.json", request)
    venue = DurableOptionVenue(directory / "venue.db")
    with OptionExecution.open(
        directory / "options.db", settings.limits, settings.execution, venue, now=at[0]
    ) as engine:
        c = _coordinator(engine, settings, False, lambda: at[0])
        runtime = OptionRuntime(c, settings.runtime)
        runtime.running = True
        with engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_runtime SET status='RUNNING',heartbeat_at=?,generation=generation+1 WHERE id=1",
                (at[0].isoformat(),),
            )
            engine.journal.event(
                db,
                at[0],
                "PORTFOLIO_REPLAY_STARTED",
                {"request_hash": fingerprint(request), "original_source_clocks": True},
            )
        for packet in request.packets:
            at[0] = packet.recorded_at
            path = directory / "delivery.tmp"
            _save(path, packet)
            os.replace(path, directory / "feed.json")
            await runtime.tick()
            if runtime.task:
                await runtime.task
        with engine.journal.write() as db:
            db.execute(
                "UPDATE execution_option_runtime SET status='STOPPED',reason='FROZEN_OFFLINE_REPLAY' WHERE id=1"
            )
            engine._halt(db, "FROZEN_OFFLINE_REPLAY", at[0])
        report = engine.journal.report(now=at[0])
    from app.mixed.observer import MixedObserver

    view = MixedObserver(
        directory / "options.db", settings.limits.population_id, clock=lambda: at[0]
    ).report()
    result = {
        "version": "portfolio-replay-result-v2",
        "request_hash": fingerprint(request),
        "as_of": at[0].isoformat(),
        "population_id": settings.limits.population_id,
        "status": view["status"],
        "cash": view.get("cash"),
        "equity": view.get("equity"),
        "held_plays": len(view.get("positions", [])),
        "fills": view.get("fill_count"),
        "revision": report["revision"],
        "network_calls": False,
        "model_calls": False,
        "live_enabled": False,
        "market_acceptance": False,
    }
    fd = os.open(directory / "result.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, sort_keys=True)
    return result
