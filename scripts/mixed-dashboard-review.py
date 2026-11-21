"""Create one historical UI fixture through the installed native PAPER engine.

No credentials, model, collector or daemon. Never adopt or overwrite a population.
"""

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import app
from app.mixed.models import StockProposal
from app.mixed.observer import MixedObserver
from app.mixed.stock_models import StockIntent, StockQuote
from app.options.engine import OptionExecution
from app.options.lifecycle import OptionExecutionPolicy
from app.options.models import OptionLimits
from app.options.venue import DurableOptionVenue


def create(output):
    if "site-packages" not in Path(app.__file__).parts:
        raise ValueError("An isolated noneditable installed application is required")
    seed_path = Path(__file__).resolve().parent.parent / "examples/mixed-dashboard-review.json"
    seed = json.loads(seed_path.read_text())
    limits = OptionLimits.model_validate(seed["limits"])
    policy = OptionExecutionPolicy.model_validate(seed["execution"])
    if (
        seed["version"] != "mixed-dashboard-review-v1"
        or limits.provider != "fixture"
        or limits.population_id != "ui-review-stock-20261009"
        or policy.cost_policy is not None
        or policy.mixed_owner is None
        or policy.mixed_owner.reasoning is not None
    ):
        raise ValueError("Explicit model-off UI fixture configuration required")
    if not output.is_absolute():
        raise ValueError("Absolute new output directory required")
    output.mkdir(mode=0o700)  # Exclusive; a partial or completed run cannot be reused.
    os.umask(0o077)
    at = datetime.fromisoformat(seed["start_at"])
    proposal = StockProposal.model_validate(seed["proposal"])
    base_quote = StockQuote.model_validate(seed["quote"])

    def quote(when, bid=None):
        values = base_quote.model_dump() | {"source_at": when, "received_at": when}
        if bid is not None:
            values.update(bid=Decimal(bid), ask=Decimal(bid) + Decimal(".01"))
        return StockQuote.model_validate(values)

    venue = DurableOptionVenue(
        output / "venue.db",
        limits=limits,
        stock_limits=policy.mixed_owner.stocks,
        capital=policy.capital,
    )
    with OptionExecution.open(
        output / "options.db", limits, policy, venue, now=at, create=True
    ) as engine:

        def reconcile(when):
            result = engine.reconcile(venue.snapshot(when), now=when)
            if not result["reconciled"]:
                raise ValueError("Fixture reconciliation failed")

        def execute(key, plan, when, bid=None):
            q = quote(when, bid)
            result = engine.prepare_stock(key, plan, q, now=when)
            if result["status"] != "PREPARED":
                raise ValueError("Fixture native approval failed: " + result["status"])
            with engine.journal.read() as db:
                raw = db.execute(
                    "SELECT intent_json FROM execution_stock_orders WHERE client_id=?",
                    (result["client_id"],),
                ).fetchone()[0]
            intent = StockIntent.model_validate_json(raw)
            if asyncio.run(engine.dispatch_stock(intent.client_id, q, now=when)) != "OPEN":
                raise ValueError("Fixture native attempt failed")
            filled_at = when + timedelta(seconds=1)
            venue.fill_stock(
                intent, intent.quantity, quote(filled_at, bid), filled_at, fill_id=key + "-fill"
            )
            reconcile(filled_at)
            engine.assess_stock(quote(filled_at, bid), now=filled_at)

        reconcile(at)
        engine.assess_stock(None, now=at)
        execute("review-first-entry", proposal, at)
        close = StockProposal(
            action="CLOSE",
            instrument=proposal.instrument,
            thesis="Offline fixture close; actual simulated receipt, not model advice.",
        )
        execute("review-first-close", close, at + timedelta(seconds=2), bid="102")
        execute("review-open-entry", proposal, at + timedelta(seconds=5))
        end = at + timedelta(seconds=6)
        engine.tighten_stock_invalidation("95", quote(end), now=end)

    report = MixedObserver(output / "options.db", limits.population_id, clock=lambda: end).report()
    if report["status"] != "OK" or report["accounting"] != "VERIFIED" or report["fill_count"] != 3:
        raise ValueError("Final native review evidence unavailable")
    manifest = {
        "version": "mixed-dashboard-review-v1",
        "purpose": seed["purpose"],
        "population_id": limits.population_id,
        "as_of": end.isoformat(),
        "initial_virtual_capital": str(policy.capital),
        "worker_running": False,
        "model_calls": 0,
        "network_calls": False,
        "live_enabled": False,
        "native_fill_receipts": report["fill_count"],
        "cash": report["cash"],
        "equity_at_fixture_time": report["equity"],
        "seed_sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        "journal_sha256": hashlib.sha256((output / "options.db").read_bytes()).hexdigest(),
    }
    with (output / "review.json").open("x") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create(args.output)))


if __name__ == "__main__":
    main()
