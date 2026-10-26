"""Cross-check one collector against its existing native simulation owner.

This reads configuration only. It never opens credentials, creates a population,
changes eligibility, or interprets a fresh quote as entitlement evidence.
"""

from pathlib import Path

from app.mixed.continuous_feed import FeedPolicy
from app.options.engine import clock
from app.options.read_mapping import SOURCE, reviewed_schemas
from app.options.runtime_models import RuntimeSettings


def connection_report(settings, feed, schemas, *, journal, directory, now):
    settings = RuntimeSettings.model_validate(settings.model_dump())
    feed = FeedPolicy.model_validate(feed.model_dump())
    reviewed_schemas(schemas)
    now = clock(now)
    journal, directory = Path(journal), Path(directory)
    errors, blockers = [], []
    if not journal.is_absolute() or not directory.is_absolute():
        raise ValueError("Absolute existing-owner and collector paths required")
    expected = directory / "feed.json"
    if Path(settings.runtime.feed_file).resolve() != expected.resolve():
        errors.append("RUNTIME_FEED_PATH_MISMATCH")
    if journal.name != "options.db":
        errors.append("NATIVE_OWNER_JOURNAL_REQUIRED")
    if directory.resolve() == journal.parent.resolve():
        errors.append("COLLECTOR_DIRECTORY_MUST_NOT_BE_OWNER_DIRECTORY")
    if feed.population_id != settings.limits.population_id:
        errors.append("POPULATION_MISMATCH")
    mixed = settings.execution.mixed_owner
    if mixed is None or mixed.portfolio is None or settings.stock_policy is None:
        errors.append("NATIVE_TWO_PLAY_OWNER_REQUIRED")
    else:
        if feed.stocks != settings.stock_policy.instruments:
            errors.append("STOCK_INSTRUMENTS_MISMATCH")
        if mixed.stocks.provider != "robinhood" or mixed.stocks.quote_source != SOURCE:
            errors.append("STOCK_SOURCE_MISMATCH")
        if not {s.symbol for s in feed.stocks} <= set(mixed.stocks.allowed_symbols):
            errors.append("STOCK_UNIVERSE_MISMATCH")
    if settings.runtime.simulated_fills != "mixed-quote-fills-v1":
        errors.append("QUOTE_DRIVEN_SIMULATED_FILLS_REQUIRED")
    if settings.limits.provider != "robinhood" or any(
        value != SOURCE
        for value in (
            settings.limits.option_source,
            settings.limits.underlying_source,
            settings.setup.history_source,
            settings.selection.metadata_source,
        )
    ):
        errors.append("OPTION_OR_HISTORY_SOURCE_MISMATCH")
    if tuple(s.symbol for s in feed.stocks) != settings.setup.symbols:
        errors.append("STRATEGY_UNIVERSE_MISMATCH")
    if not {s.symbol for s in feed.stocks} <= {"SPY", "QQQ"} or any(
        s.provider != "robinhood" for s in feed.stocks
    ):
        errors.append("UNSUPPORTED_STOCK_MAPPING")
    if feed.poll_seconds >= settings.runtime.feed_max_age_seconds:
        errors.append("POLL_INTERVAL_EXCEEDS_FEED_FRESHNESS")
    # These are facts about the current mapper, not declarations the operator
    # can bypass by editing a configuration flag.
    blockers.extend(("ENTITLEMENT_NOT_ESTABLISHED", "STOCK_EXECUTABLE_SIZES_UNAVAILABLE"))
    if settings.scope_policy is not None:
        blockers.append("SCOPE_CONTEXT_AND_SPX_MAPPING_UNAVAILABLE")
    if settings.swing_policy is not None or (
        settings.stock_policy is not None and settings.stock_policy.swing is not None
    ):
        blockers.append("SWING_DAILY_AND_HOURLY_FEED_UNAVAILABLE")
    candidates = []
    seen = set()
    for instrument in feed.candidates:
        reasons = []
        if instrument.instrument_id in seen:
            errors.append("DUPLICATE_OPTION_CANDIDATE")
        seen.add(instrument.instrument_id)
        if instrument.provider != "robinhood" or instrument.contract.underlying not in {
            s.symbol for s in feed.stocks
        }:
            reasons.append("UNSUPPORTED_OPTION_MAPPING")
        if instrument.contract.underlying not in settings.limits.allowed_underlyings:
            reasons.append("OPTION_OUTSIDE_OWNER_UNIVERSE")
        if not instrument.metadata_complete or not instrument.option_tradable:
            reasons.append("OPTION_METADATA_OR_TRADABILITY_UNREVIEWED")
        if now >= instrument.contract.last_trading_at:
            reasons.append("OPTION_LAST_TRADING_PASSED")
        candidates.append({"instrument_id": instrument.instrument_id, "blockers": reasons})
    if not candidates:
        blockers.append("NO_REVIEWED_OPTION_CANDIDATES")
    return {
        "version": "connected-simulation-check-v1",
        "status": "WIRING_INVALID" if errors else "WIRED_WITH_ENTRY_BLOCKERS",
        "population_id": settings.limits.population_id,
        "account_id": settings.limits.account_id,
        "wiring_errors": sorted(set(errors)),
        "entry_blockers": blockers,
        "option_candidates": candidates,
        "collector_can_start": not errors,
        "trading_ready": False,
        "provider_reads": False,
        "credentials_opened": False,
        "live_enabled": False,
    }


def main(argv=None):
    """Review configuration without opening journals, collector state or secrets."""
    import argparse
    import json

    from app.domain.models import utc_now
    from app.options.operator_inbox import read
    from app.options.read_gateway import ReadSchemas
    from app.options.runtime_cli import load

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime-file", "policy", "schemas", "journal", "directory"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    if any(not Path(value).is_absolute() for value in vars(args).values()):
        parser.error("Absolute configuration paths required")
    settings = load(args.runtime_file)
    feed = FeedPolicy.model_validate_json(read(args.policy, 256 * 1024))
    schemas = ReadSchemas.model_validate_json(read(args.schemas, 256 * 1024))
    result = connection_report(
        settings, feed, schemas, journal=args.journal, directory=args.directory, now=utc_now()
    )
    print(json.dumps(result, indent=2))
    return 2 if result["wiring_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
