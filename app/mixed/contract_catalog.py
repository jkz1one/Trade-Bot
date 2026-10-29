"""Prepare an evidence-bound option catalog offline; never enroll or resume it."""

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from jsonschema.exceptions import ValidationError as SchemaError

from app.domain.models import utc_now
from app.options.models import OptionInstrument
from app.options.read_capture import CaptureResult
from app.options.read_gateway import encoded
from app.options.read_mapping import instant, option_metadata, quote_rows, response


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def capture(artifact, tool):
    if (
        artifact.get("status") != "COMPLETE"
        or artifact.get("operation") != "capture"
        or artifact.get("execution_authority") is not False
    ):
        raise ValueError("Completed read-only capture required")
    result = CaptureResult.model_validate(artifact["result"])
    if (
        result.operation != "CAPTURE"
        or result.status != "COMPLETE"
        or result.schemas is None
        or result.plan is None
        or result.started_at > result.collected_at
        or len(result.plan.calls) != len(result.observations)
    ):
        raise ValueError("Complete original plan, schemas and receipts required")
    payloads = []
    for call, receipt in zip(result.plan.calls, result.observations, strict=True):
        if (
            call.tool != tool
            or receipt.get("tool") != tool
            or receipt.get("label") != call.label
            or receipt.get("completed") is not True
        ):
            raise ValueError("Exact completed receipt required")
        payloads.append(response(result.schemas, call, receipt["raw"], tool)[1])
    return result, payloads


def review(contracts, samples):
    """Validate captured identities and historical quote quality, without term inference."""
    original, payloads = capture(contracts, "get_option_instruments")
    if not 1 <= len(samples) <= 8:
        raise ValueError("One to eight original quote captures required")
    catalog = {}
    chains = {}
    for call, data in zip(original.plan.calls, payloads, strict=True):
        args = call.arguments
        if not (args.get("chain_id") or args.get("chain_symbol")) or args.get("ids"):
            raise ValueError("Explicit chain ID or symbol discovery required")
        if data.get("next"):
            raise ValueError("Unfinished contract pagination")
        for row in data.get("instruments") or ():
            if (
                row is None
                or row["id"] in catalog
                or row["chain_symbol"] not in original.plan.symbols
                or not row["chain_id"]
                or (args.get("chain_id") and row["chain_id"] != args["chain_id"])
                or (args.get("chain_symbol") and row["chain_symbol"] != args["chain_symbol"])
                or (row["chain_symbol"] in chains and chains[row["chain_symbol"]] != row["chain_id"])
                or row["expiration_date"] != args.get("expiration_dates")
                or Decimal(row["strike_price"]) != Decimal(args["strike_price"])
                or row["state"] != "active"
                or row["tradability"] != "tradable"
                or row["type"] not in ("call", "put")
                or row["underlying_type"] != "equity"
                or Decimal(row["trade_value_multiplier"]) <= 0
            ):
                raise ValueError("Exact active equity-option discovery subjects required")
            catalog[row["id"]] = row
            chains[row["chain_symbol"]] = row["chain_id"]
    if not 1 <= len(catalog) <= 8:
        raise ValueError("Bounded nonempty contract discovery required")
    observations = {key: [] for key in catalog}
    previous = original.collected_at
    requests = {original.request_id}
    for artifact in samples:
        result, payloads = capture(artifact, "get_option_quotes")
        if (
            result.request_id in requests
            or result.started_at < previous
            or result.policy_sha256 != original.policy_sha256
            or result.schemas.sha256 != original.schemas.sha256
            or set(result.plan.symbols) != set(original.plan.symbols)
            or set(result.plan.instrument_ids) != set(catalog)
        ):
            raise ValueError(
                "Ordered distinct captures with identical source and subjects required"
            )
        requests.add(result.request_id)
        previous = result.collected_at
        seen = set()
        for call, data in zip(result.plan.calls, payloads, strict=True):
            for row in quote_rows(data, call.arguments["instrument_ids"], "instrument_id"):
                key = row["instrument_id"]
                if key not in catalog or key in seen:
                    raise ValueError("Duplicate or unexpected quote subject")
                seen.add(key)
                source = instant(row["updated_at"])
                age = (result.collected_at - source).total_seconds()
                bid, ask = Decimal(row["bid_price"]), Decimal(row["ask_price"])
                history = observations[key]
                if age < 0 or (history and source < instant(history[-1]["source_at"])):
                    raise ValueError("Future or regressing quote clock")
                row_hash = digest(row)
                if (
                    history
                    and source == instant(history[-1]["source_at"])
                    and row_hash != history[-1]["quote_sha256"]
                ):
                    raise ValueError("Quote changed at the same source clock")
                history.append(
                    {
                        "source_at": source.isoformat(),
                        "received_at": result.collected_at.isoformat(),
                        "age_seconds_at_capture": age,
                        "bid": str(bid),
                        "ask": str(ask),
                        "bid_size": row["bid_size"],
                        "ask_size": row["ask_size"],
                        "fresh_book_at_capture": (
                            age <= 30
                            and bid.is_finite()
                            and ask.is_finite()
                            and 0 < bid <= ask
                            and row["bid_size"] > 0
                            and row["ask_size"] > 0
                        ),
                        "quote_sha256": row_hash,
                    }
                )
        if seen != set(catalog):
            raise ValueError("Complete quote subject coverage required")
    return {
        "version": "captured-option-catalog-v1",
        "status": "REVIEWED_TERMS_REQUIRED",
        "captured_at": previous.isoformat(),
        "contracts": [
            {
                "provider_record": row,
                "samples": observations[key],
                "all_fresh_at_capture": all(q["fresh_book_at_capture"] for q in observations[key]),
                "source_clock_advanced": (
                    instant(observations[key][-1]["source_at"])
                    > instant(observations[key][0]["source_at"])
                ),
            }
            for key, row in catalog.items()
        ],
        "capture_hashes": [digest(a) for a in [contracts, *samples]],
        "missing_terms": [
            "underlying_kind",
            "underlying_market",
            "root",
            "deliverable_kind",
            "deliverable_units",
            "currency",
            "exercise_style",
            "settlement",
            "settlement_session",
            "last_trading_at",
            "expires_at",
            "settles_at",
            "adjusted",
        ],
        "entitlement": "UNKNOWN",
        "trading_ready": False,
        "live_enabled": False,
        "provider_calls": False,
        "state_modified": False,
    }


def bind(contracts, samples, instruments):
    """Cross-check explicit reviewed native terms; broker sellout is not exchange close."""
    report = review(contracts, samples)
    records = {r["provider_record"]["id"]: r["provider_record"] for r in report["contracts"]}
    selected = tuple(OptionInstrument.model_validate(i) for i in instruments)
    if not 1 <= len(selected) <= 6 or len({i.instrument_id for i in selected}) != len(selected):
        raise ValueError("One to six unique explicitly selected native instruments required")
    for item in selected:
        row, c = records.get(item.instrument_id), item.contract
        if row is None:
            raise ValueError("Selected contract absent from original discovery")
        ticks = row["min_ticks"]
        cutoff = Decimal(ticks["cutoff_price"])
        below, above = Decimal(ticks["below_tick"]), Decimal(ticks["above_tick"])
        # Native terms encode only the $3 breakpoint. Other unequal schedules cannot map.
        if cutoff not in (Decimal(0), Decimal(3)) and below != above:
            raise ValueError("Unsupported tick schedule")
        expected_below = above if cutoff == 0 else below
        if (
            item.provider != "robinhood"
            or not item.metadata_complete
            or not item.option_tradable
            or c.underlying != row["chain_symbol"]
            or c.right.lower() != row["type"]
            or c.strike != Decimal(row["strike_price"])
            or c.expiration.isoformat() != row["expiration_date"]
            or c.multiplier != Decimal(row["trade_value_multiplier"])
            or c.underlying_kind not in ("EQUITY", "ETF")
            or c.tick_below_three != expected_below
            or c.tick_at_or_above_three != above
        ):
            raise ValueError("Reviewed terms conflict with provider contract evidence")
    # Exercise the actual quote/Greek/metadata mapper against supplied native identities.
    all_by_id = {i.instrument_id: i for i in selected}
    for artifact in samples:
        result, _ = capture(artifact, "get_option_quotes")
        for call, receipt in zip(result.plan.calls, result.observations, strict=True):
            # Mapping requires exact call coverage, including unselected diagnostic peers.
            # Validate each selected row through a schema-valid one-subject envelope.
            _, data = response(result.schemas, call, receipt["raw"], call.tool)
            for row in quote_rows(data, call.arguments["instrument_ids"], "instrument_id"):
                if row["instrument_id"] in all_by_id:
                    item = all_by_id[row["instrument_id"]]
                    one = call.model_copy(
                        update={"arguments": {"instrument_ids": [item.instrument_id]}}
                    )
                    raw = {
                        "isError": False,
                        "structuredContent": {
                            "data": {"results": [{"quote": row}]},
                            "guide": "",
                        },
                    }
                    option_metadata(
                        result.schemas,
                        one,
                        raw,
                        received_at=result.collected_at,
                        instruments=(item,),
                    )
    report.update(
        status="CATALOG_PROPOSAL_READY",
        missing_terms=[],
        candidates=[i.model_dump(mode="json") for i in selected],
    )
    report["review_sha256"] = digest(report)
    return report


def propose(base, contracts, samples, instruments, target, now):
    from app.mixed.continuous_feed import FeedPolicy
    from app.mixed.feed_rollover import identities, validate_policy

    base = FeedPolicy.model_validate(base)
    report = bind(contracts, samples, instruments)
    if instant(report["captured_at"]) > instant(now):
        raise ValueError("Captured evidence is in the future")
    value = base.model_dump(mode="json")
    value["candidates"] = report["candidates"]
    value["carry_intents"] = [
        i for i in value.get("carry_intents", []) if i["target_session"] == target.isoformat()
    ]
    proposed = FeedPolicy.model_validate(value)
    validate_policy(base, proposed, target, now)
    identities((base, proposed))
    return report, proposed


def main(argv=None):
    from app.options.operator_inbox import save
    from app.options.read_cli import private_json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts", required=True)
    parser.add_argument("--quotes", required=True, nargs="+")
    parser.add_argument("--terms")
    parser.add_argument("--base-policy")
    parser.add_argument("--target-session", type=date.fromisoformat)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if not 1 <= len(args.quotes) <= 8:
        parser.error("One to eight quote captures required")
    if any((args.base_policy, args.target_session, args.output)) and not all(
        (args.terms, args.base_policy, args.target_session, args.output)
    ):
        parser.error("Policy proposal requires terms, base-policy, target-session and output")

    def load(path):
        return private_json(path)

    try:
        contracts, samples = load(args.contracts), [load(p) for p in args.quotes]
        if args.output:
            report, policy = propose(
                load(args.base_policy),
                contracts,
                samples,
                load(args.terms),
                args.target_session,
                utc_now(),
            )
            save(Path(args.output), policy.model_dump(mode="json"))
            report["proposed_policy_sha256"] = digest(policy.model_dump(mode="json"))
        else:
            report = (
                bind(contracts, samples, load(args.terms))
                if args.terms
                else review(contracts, samples)
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError, SchemaError):
        print(json.dumps({"status": "UNAVAILABLE", "live_enabled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
