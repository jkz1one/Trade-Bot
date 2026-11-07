"""Explicit first connected simulation profile. No credentials, feeds or workers opened."""

import argparse
import json
from pathlib import Path

from app.domain.models import utc_now
from app.mixed.connected_check import connection_report
from app.mixed.continuous_feed import FeedPolicy
from app.options.engine import fingerprint
from app.options.operator_inbox import private_directory, save, sync_directory
from app.options.runtime_models import RuntimeSettings
from app.options.schema_artifact import load_reviewed_schemas
from app.options.scope import SCOPE_GROUPS
from app.options.swing_base_models import SWING_FAMILIES
from app.options.swing_level_models import LEVEL_FAMILIES

PROFILE = "connected-simulation-1000-v1"
MODEL_KEY = "/etc/trade-bot-connected/model_key"
SOURCE = "robinhood-mcp"


def configuration():
    """Simulation assumptions are visible in review, never inferred LIVE settings."""
    scope_preflight = {
        "sources": [
            {"kind": k, "source": "unavailable-" + k, "max_age_seconds": 30} for k in SCOPE_GROUPS
        ],
        "history_sources": [
            {"symbol": s, "source": "unavailable-scope-" + s} for s in ("SPX", "SPY", "QQQ")
        ],
        "session_source": "unavailable-spx-session",
        "provider": "robinhood",
        "metadata_source": SOURCE,
        "quote_source": SOURCE,
        "max_receive_lag_seconds": 2,
        "max_evidence_skew_seconds": 2,
        "max_history_age_seconds": 300,
        "max_contract_age_seconds": 10,
        "max_spread_fraction": ".10",
    }
    context = {
        "structure": {
            "preflight": scope_preflight,
            "first_target_r": "1.5",
            "second_target_r": "2.5",
            "pullback_touch_points": "2",
            "pullback_touch_fraction": ".0005",
            "compression_fraction": ".5",
            "confirmation_fraction": ".0001",
            "conflict_fraction": ".001",
        },
        "prior_source": "unavailable-spx-prior",
        "prior_max_age_seconds": 345600,
        "dealer_proximity_points": "2",
        "dealer_proximity_fraction": ".0005",
        "boundary_proximity_points": "2",
        "boundary_proximity_fraction": ".0005",
        "prior_proximity_points": "2",
        "prior_proximity_fraction": ".0005",
        "max_expected_move_consumed_fraction": ".8",
    }
    quality = {
        "context": context,
        "observe_score": 80,
        "watching_score": 90,
        "arm_score": 94,
        "convexity_score": 97,
        "minimum_first_target_r": "1.5",
        "structural_path": "completed-spx-plateaus-v2",
    }
    watch = {
        "context": context,
        "max_called_plays_per_session": 2,
        "quote_lifecycle": "scope-observed-quotes-v1",
        "direction_reset": {"cooldown_seconds": 600, "confirmation_bars": 2},
        "quality": quality,
        "arming": {"confirmation_hold_seconds": 60, "max_sample_gap_seconds": 10},
        "contract": {
            "quality": quality,
            "minimum_ask": ".20",
            "cheap_ceiling": "1.25",
            "medium_ceiling": "2.50",
            "maximum_ask": "5",
            "maximum_spread_fraction": ".10",
            "minimum_volume": 10,
            "minimum_open_interest": 100,
        },
        "admission": {"max_entry_debit": "250"},
        "management": {
            "version": "scope-management-plan-v2",
            "responsive_loss_fraction": ".35",
            "balanced_loss_fraction": ".45",
            "convexity_loss_fraction": ".50",
        },
        "native_execution": "scope-native-v1",
        "entry_binding": "scope-entry-binding-v1",
    }
    # Symbols are identities for this gateway. Incomplete catalog flags stay false.
    stocks = [
        {
            "provider": "robinhood",
            "instrument_id": s,
            "symbol": s,
            "kind": "ETF",
            "tick": ".01",
            "metadata_complete": False,
            "tradable": False,
        }
        for s in ("SPY", "QQQ")
    ]
    stock_limits = {
        "provider": "robinhood",
        "quote_source": SOURCE,
        "allowed_symbols": ["SPY", "QQQ"],
        "share_step": "1",
        "max_shares": "50",
        "max_entry_debit": "250",
        "max_account_exposure": "500",
        "minimum_price": "5",
        "max_spread_fraction": ".01",
        "slippage_bps": "5",
        "entry_fee_per_share": "0",
        "exit_fee_per_share": "0",
        "entry_fee_per_order": "1",
        "exit_fee_per_order": "1",
        "quote_max_age_seconds": 10,
        "max_receive_lag_seconds": 2,
        "approval_lifetime_seconds": 5,
    }
    settings = RuntimeSettings.model_validate(
        {
            "limits": {
                "account_id": "local-simulation",
                "population_id": PROFILE,
                "allowed_underlyings": ["SPY", "QQQ", "SPX"],
                "provider": "robinhood",
                "option_source": SOURCE,
                "underlying_source": SOURCE,
                "session_source": "XNYS_REGULAR_INTERSECTION_V1",
                "max_contracts": 4,
                "max_entry_debit": "250",
                "max_account_exposure": "500",
                "max_full_premium_loss": "250",
                "entry_fee_per_contract": ".65",
                "exit_fee_per_contract": ".65",
                "entry_fee_per_order": "1",
                "exit_fee_per_order": "1",
                "slippage_bps": "5",
                "max_spread_fraction": ".10",
                "minimum_underlying_price": "5",
                "quote_max_age_seconds": 10,
                "account_max_age_seconds": 20,
                "max_receive_lag_seconds": 2,
                "max_sync_seconds": 2,
                "approval_lifetime_seconds": 5,
            },
            "execution": {
                "capital": "1000",
                "daily_loss_limit": "250",
                "total_loss_limit": "500",
                "entry_cutoff_minutes": 30,
                "exit_cutoff_minutes": 15,
                "expiry_guard_seconds": 60,
                "premium_catastrophe_fraction": ".5",
                "supervisor_max_age_seconds": 20,
                "process_timeout_seconds": 5.0,
                "cost_policy": {
                    "model": "gpt-6-luna",
                    "input_per_million": ".10",
                    "output_per_million": ".50",
                    "daily_budget": "1",
                    "total_budget": "5",
                    "max_call_cost": ".01",
                },
                "mixed_owner": {
                    "reasoning": "mixed-paid-entry-v1",
                    "stocks": stock_limits,
                    "portfolio": {
                        "max_plays": 2,
                        "exposure_limit": "500",
                        "index_exposure_limit": "500",
                    },
                    "daily_data_cost": "0",
                    "daily_host_cost": "1",
                    "daily_operating_cost": "0",
                },
                "loss_control": {
                    "max_consecutive_losses": 2,
                    "cooldown_seconds": 1800,
                    "families": [
                        {"family": f, "max_consecutive_losses": 2, "cooldown_seconds": 1800}
                        for f in ("DEGEN", "SWING", "SCOPE")
                    ],
                },
                "partial_closes": "whole-contract-v1",
                "target_exits": "frozen-target-milestones-v2",
                "target_stops": "frozen-target-stops-v1",
                "target_entry_reference": "fill-weighted-underlying-v1",
                "trade_floor": "native-target-floor-v1",
                "premium_trail": "executable-premium-v1",
                "entry_time_protection": "tighten-only-v1",
                "entry_premium_protection": "tighten-only-v1",
                "scope_execution": "scope-native-v1",
                "scope_arbitration": "shared-scope-entry-v1",
            },
            "setup": {
                "symbols": ["SPY", "QQQ"],
                "history_source": SOURCE,
                "max_bar_age_seconds": 300,
                "max_receive_lag_seconds": 2,
                "volume_lookback": 3,
                "minimum_volume_ratio": "1.05",
                "stop_buffer_fraction": ".0001",
                "maximum_extension_fraction": ".0065",
                "vwap_separation_fraction": ".0022",
                "vwap_touch_fraction": ".0018",
            },
            "selection": {
                "metadata_source": SOURCE,
                "max_inventory_contracts": 6,
                "max_quote_contracts": 1,
                "max_metadata_age_seconds": 10,
                "minimum_abs_delta": ".25",
                "maximum_abs_delta": ".7",
                "target_abs_delta": ".45",
                "maximum_strike_distance_fraction": ".02",
                "minimum_volume": 10,
                "minimum_open_interest": 100,
            },
            "swing_policy": {
                "history_source": SOURCE,
                "catalyst_source": "unavailable-catalyst",
                "daily_lookback": 56,
                "daily_base": {"hourly_source": SOURCE, "hourly_lookback": 54},
                "ma_pullback": {
                    "periods": [8, 21, 50],
                    "hourly_source": SOURCE,
                    "hourly_lookback": 54,
                },
                "higher_levels": {"keys": list(LEVEL_FAMILIES)},
                "family_batch": "complete-family-batch-v1",
                "minimum_dte": 7,
                "maximum_dte": 45,
                "maximum_chase_fraction": ".0065",
                "stop_buffer_fraction": ".0001",
                "catalyst_max_age_seconds": 30,
                "family_priority": ["DEGEN", "SWING"],
                "target_derivation": "original-risk-ladder-v1",
                "unfilled_lifecycle": "observed-lifecycle-v3",
            },
            "scope_policy": {
                "version": "shared-scope-entry-v1",
                "watch": watch,
                "family_priority": ["DEGEN", "SWING", "SCOPE"],
            },
            "stock_policy": {
                "instruments": stocks,
                "paid_selection": "mixed-paid-entry-v1",
                "family_priority": ["DEGEN", "SWING", "SCOPE"],
                "asset_priority": ["OPTION", "STOCK"],
                "swing": {
                    "families": list(SWING_FAMILIES),
                    "history_source": SOURCE,
                    "daily_lookback": 56,
                    "hourly_source": SOURCE,
                    "hourly_lookback": 54,
                    "catalyst_source": "unavailable-catalyst",
                    "catalyst_max_age_seconds": 30,
                    "maximum_chase_fraction": ".0065",
                    "stop_buffer_fraction": ".0001",
                },
            },
            "runtime": {
                "feed_file": "/state/collector/feed.json",
                "mixed_inputs": "mixed-runtime-inputs-v1",
                "scope_inputs": "scope-runtime-inputs-v1",
                "simulated_fills": "mixed-quote-fills-v1",
                "tick_seconds": 1.0,
                "heartbeat_max_age_seconds": 20,
                "feed_max_age_seconds": 30,
            },
            "judgment_limits": {
                "max_input_tokens": 16000,
                "max_output_tokens": 1024,
                "process_timeout_seconds": 15.0,
                "request_timeout_seconds": 10.0,
            },
            "key_file": MODEL_KEY,
            "entry_policy": {
                "mixed_selection": "mixed-paid-entry-v1",
                "scope_selection": "scope-fixed-plan-v1",
                "max_horizon_seconds": 1800,
                "max_target_fraction": ".02",
                "max_trigger_fraction": ".005",
                "minimum_reward_risk": "1.5",
            },
            "position_policy": {
                "mixed_management": "mixed-stock-position-v1",
                "scope_management": "scope-fixed-position-v1",
                "max_lease_seconds": 20,
            },
        }
    )
    feed = FeedPolicy.model_validate(
        {
            "population_id": PROFILE,
            "stocks": stocks,
            "candidates": [],
            "poll_seconds": 10,
            "calls_per_minute": 24,
            "capture": {
                "oauth_file": "/var/lib/trade-bot-read-auth/robinhood-oauth.json",
                "timeout_seconds": 10.0,
            },
            "swing_history": {"daily_bars": 56, "hourly_bars": 54},
        }
    )
    return settings, feed


def review(schemas, *, now=None):
    settings, feed = configuration()
    result = connection_report(
        settings,
        feed,
        schemas,
        journal=Path("/state/owner/options.db"),
        directory=Path("/state/collector"),
        now=now or utc_now(),
    )
    if not result["collector_can_start"]:
        raise ValueError("Simulation profile wiring invalid")
    binding = {
        "version": PROFILE,
        "settings_sha256": fingerprint(settings),
        "policy_sha256": fingerprint(feed),
        "schemas_sha256": fingerprint(schemas),
    }
    return result | {
        "binding": binding,
        "review_sha256": fingerprint(binding),
        "virtual_capital": "1000",
        "ai_daily_budget": "1",
        "ai_total_budget": "5",
        "maximum_plays": 2,
        "families": list(settings.stock_policy.family_priority),
        "simulation_assumptions": {
            "max_entry_debit": "250",
            "aggregate_exposure": "500",
            "daily_loss_limit": "250",
            "total_loss_limit": "500",
            "option_fee_per_contract_per_side": ".65",
            "fee_per_order": "1",
            "slippage_bps": "5",
            "overnight_carry": False,
            "daily_host_allowance": "1",
            "daily_additional_data_allowance": "0",
            "daily_other_operating_allowance": "0",
            "cost_basis": "SIMULATION_ASSUMPTIONS_NOT_ACTUAL_BILLS",
        },
        "entry_blockers": result["entry_blockers"],
        "workers_started": False,
        "credentials_opened": False,
    }


def create(directory, schemas, expected_review):
    report = review(schemas)
    if report["review_sha256"] != expected_review:
        raise ValueError("Simulation profile review changed")
    directory = Path(directory)
    if not directory.is_absolute() or directory.resolve() != directory:
        raise ValueError("Canonical new profile directory required")
    private_directory(directory.parent)
    directory.mkdir(mode=0o700)
    settings, feed = configuration()
    for name, value in (("runtime.json", settings), ("policy.json", feed)):
        save(directory / name, value.model_dump(mode="json"))
    save(directory / "review.json", report)
    sync_directory(directory)
    sync_directory(directory.parent)
    return report | {"status": "SIMULATION_PROFILE_CREATED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("review", "create"))
    parser.add_argument("--schemas", required=True)
    parser.add_argument("--directory")
    parser.add_argument("--expected-review")
    args = parser.parse_args(argv)
    if (args.operation == "create") != bool(args.directory and args.expected_review):
        parser.error("Create requires a new directory and exact review hash")
    if args.operation == "review" and (args.directory or args.expected_review):
        parser.error("Review accepts schemas only")
    try:
        schemas = load_reviewed_schemas(Path(args.schemas))
        result = (
            review(schemas)
            if args.operation == "review"
            else create(args.directory, schemas, args.expected_review)
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, RuntimeError):
        print(json.dumps({"status": "SIMULATION_PROFILE_UNAVAILABLE"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
