"""Prepare explicit intraday ETF simulation assumptions from original RH captures.

No contract is declared broker-verified. No host state, credentials or workers
are touched. Native metadata_complete means the simulated model is populated.
"""
import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.mixed.contract_catalog import review
from app.mixed.continuous_feed import FeedPolicy
from app.options.models import OptionInstrument
from app.options.operator_inbox import read, save
from app.robinhood.schedule import XNYSCalendar


def proposal(policy, contracts, samples, target, *, earnings_probe=None, observed_swing_history=False,
             swing_contracts=None, swing_samples=None, scope_binding=None):
    policy = FeedPolicy.model_validate(policy.model_dump())
    from app.options.earnings_context import from_probe

    earnings = from_probe(earnings_probe, target) if earnings_probe is not None else None
    reviewed = review(contracts, samples)
    cal = XNYSCalendar().calendar
    if not cal.is_session(target.isoformat()):
        raise ValueError("Exchange trading session required")
    close = cal.session_close(target.isoformat()).to_pydatetime()
    settle = cal.session_open(cal.next_session(target.isoformat())).to_pydatetime()
    selected = instruments(policy, reviewed, target, cal)
    if not 1 <= len(selected) <= 6:
        raise ValueError("One to six captured simulation contracts required")
    swing_review = None
    if (swing_contracts is None) != (swing_samples is None):
        raise ValueError("Swing discovery and original quote samples must be supplied together")
    if swing_contracts is not None:
        if not observed_swing_history:
            raise ValueError("Swing catalog requires explicit observed history enrollment")
        swing_review = review(swing_contracts, swing_samples)
        swing_selected = instruments(policy, swing_review, target, cal, swing=True)
        if sorted((i.contract.underlying, i.contract.right) for i in swing_selected) != sorted(
            (s.symbol, right) for s in policy.stocks for right in ("CALL", "PUT")
        ):
            raise ValueError("One exact Swing CALL and PUT for every enrolled symbol required")
        selected += swing_selected
        if len(selected) > 8 or len({i.instrument_id for i in selected}) != len(selected):
            raise ValueError("At most eight distinct DEGEN plus Swing candidates required")
    if scope_binding is not None:
        from app.mixed.scope_feed import ScopeFeedBinding
        scope_binding = ScopeFeedBinding.model_validate(scope_binding)
        if scope_binding.session.session_date != target:
            raise ValueError("Scope terms/calendar must name the exact session")
    proposed = FeedPolicy.model_validate(policy.model_dump() | {
        "candidates": tuple(selected), "observed_simulation": "robinhood-observed-v1",
        "company_earnings": earnings,
        "scope_binding": scope_binding,
        **({"swing_observed_simulation": "robinhood-observed-v1", "swing_history": {
            **policy.swing_history.model_dump(), "bar_mapping": "utc-day-halfhour-v1",
        }} if observed_swing_history and policy.swing_history is not None else {}),
    })
    if observed_swing_history and policy.swing_history is None:
        raise ValueError("Observed Swing requires an existing history enrollment")
    return proposed, {
        "version": "intraday-simulation-catalog-v1", "target_session": target.isoformat(),
        **({"company_earnings": earnings.observation().model_dump(mode="json")} if earnings else {}),
        "simulation_terms": "STANDARD_ETF_INTRADAY_V1",
        "observed": ["provider IDs", "symbol", "right", "strike", "expiration", "multiplier", "ticks", "tradability"],
        "assumed": ["unadjusted standard 100-share deliverable", "American physical ETF terms", "USD", "root equals symbol"],
        "simulator_clocks": {"close": close.isoformat(), "settlement": settle.isoformat()},
        "clock_note": "Conservative regular-session simulation cutoffs, not verified contract expiry or settlement timestamps. Broker sellout is not used as exchange close.",
        "broker_terms_verified": False, "entitlement": "UNKNOWN",
        "capture_hashes": reviewed["capture_hashes"],
        "historical_quote_evidence": [{
            "instrument_id": item["provider_record"]["id"],
            "all_fresh_at_capture": item["all_fresh_at_capture"],
            "source_clock_advanced": item["source_clock_advanced"],
            "analytic_changes_at_same_quote_time": sorted({
                field for sample in item["samples"]
                for field in sample["analytic_changes_at_same_quote_time"]
            }),
        } for item in reviewed["contracts"]],
        "option_candidates": [i.instrument_id for i in selected],
        **({"swing_catalog": {
            "capture_hashes": swing_review["capture_hashes"],
            "contracts": [{"instrument_id": i.instrument_id,
                           "expiration": i.contract.expiration.isoformat(),
                           "last_trading_at": i.contract.last_trading_at.isoformat()}
                          for i in swing_selected],
            "broker_terms_verified": False, "overnight_carry": False,
        }} if swing_review is not None else {}),
        **({"swing_history_basis": "robinhood-observed-v1",
            "swing_bar_mapping": "utc-day-halfhour-v1",
            "swing_remaining": ["Completed original pre-open histories", *([] if swing_review else ["Reviewed 7-45 DTE contracts"]), "Reviewed price/options-only owner policy or complete legacy catalyst evidence"]}
           if observed_swing_history else {}),
        "live_enabled": False, "trading_ready": False, "state_modified": False,
        "remaining": ["Enroll reviewed session policy", "Fresh native input acceptance", "Reviewed native entry recovery", "Bounded connected run"],
    }


def instruments(policy, reviewed, target, cal, *, swing=False):
    selected = []
    for item in reviewed["contracts"]:
        row = item["provider_record"]
        if (row["chain_symbol"] not in {s.symbol for s in policy.stocks}
                or row["chain_symbol"] not in {"SPY", "QQQ"}
                or (not 7 <= (date.fromisoformat(row["expiration_date"]) - target).days <= 45
                    if swing else date.fromisoformat(row["expiration_date"]) != target)
                or Decimal(row["trade_value_multiplier"]) != 100):
            raise ValueError("Reviewed 7-45 DTE Swing contracts required" if swing else
                             "Same-day SPY/QQQ contracts with observed multiplier 100 required")
        expiration = date.fromisoformat(row["expiration_date"])
        if not cal.is_session(expiration.isoformat()):
            raise ValueError("Contract expiration requires an exchange session")
        close = cal.session_close(expiration.isoformat()).to_pydatetime()
        settle = cal.session_open(cal.next_session(expiration.isoformat())).to_pydatetime()
        ticks = row["min_ticks"]
        below, above = Decimal(ticks["below_tick"]), Decimal(ticks["above_tick"])
        cutoff = Decimal(ticks["cutoff_price"])
        if cutoff not in (0, 3) and below != above:
            raise ValueError("Unsupported tick schedule")
        selected.append(OptionInstrument.model_validate({
            "provider": "robinhood", "instrument_id": row["id"],
            "simulation_terms": "STANDARD_ETF_INTRADAY_V1",
            "metadata_complete": True, "option_tradable": True,
            "contract": {
                "underlying": row["chain_symbol"], "underlying_kind": "ETF",
                "underlying_market": "US_LISTED", "root": row["chain_symbol"],
                "right": row["type"].upper(), "strike": row["strike_price"],
                "expiration": expiration, "multiplier": 100, "deliverable_kind": "SHARES",
                "deliverable_units": 100, "currency": "USD", "exercise_style": "AMERICAN",
                "settlement": "PHYSICAL", "settlement_session": "PM",
                "last_trading_at": close, "expires_at": close, "settles_at": settle,
                "adjusted": False, "tick_below_three": above if cutoff == 0 else below,
                "tick_at_or_above_three": above,
            },
        }))
    return selected


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("policy", "contracts", "target-session", "output", "report"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--sample", action="append", required=True)
    p.add_argument("--earnings-probe", help="Original input probe; company calendar observation only")
    p.add_argument("--observed-swing-history", action="store_true", help="Review original RH day/half-hour histories for PAPER Swing; does not supply catalysts")
    p.add_argument("--scope-binding", help="Explicit reviewed ScopeFeedBinding: SPXW terms, index session and watch choice")
    p.add_argument("--swing-capture-directory", help="Separate original 7-45 DTE ETF catalog and three quote samples")
    a = p.parse_args(argv)
    load = lambda path: json.loads(read(Path(path), 8 * 1024 * 1024))
    proposed, report = proposal(FeedPolicy.model_validate(load(a.policy)), load(a.contracts),
                                [load(path) for path in a.sample], date.fromisoformat(a.target_session),
                                earnings_probe=json.loads(read(Path(a.earnings_probe), 1024 * 1024)) if a.earnings_probe else None,
                                observed_swing_history=a.observed_swing_history,
                                scope_binding=load(a.scope_binding) if a.scope_binding else None,
                                swing_contracts=load(Path(a.swing_capture_directory) / "contracts.json") if a.swing_capture_directory else None,
                                swing_samples=[load(Path(a.swing_capture_directory) / f"quotes-{n}.json") for n in (1, 2, 3)] if a.swing_capture_directory else None)
    if len(proposed.model_dump_json().encode()) > 256 * 1024:
        raise ValueError("Proposed session policy exceeds existing capacity")
    save(Path(a.output), proposed.model_dump(mode="json"))
    save(Path(a.report), report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
