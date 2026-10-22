"""Build immutable pre-open Swing objectives from supplied completed daily evidence."""

import argparse
import json
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.options.degen import _metric
from app.options.engine import exact, fingerprint
from app.options.models import OptionInstrument, OptionRecord, Symbol
from app.options.swing import (
    SwingBaseHistory,
    SwingHistory,
    SwingHourlyHistory,
    SwingMAHistory,
    SwingPolicy,
    SwingSeed,
    seed_issues,
)
from app.options.swing_ma_models import MA_FAMILIES, MAPeriod
from app.options.swing_target_models import SwingTargetGeometry
from app.robinhood.schedule import XNYSCalendar

MAX_BYTES = 2 * 1024 * 1024


class SwingSeedBuildRequest(OptionRecord):
    version: Literal["swing-derived-seed-request-v1"] = "swing-derived-seed-request-v1"
    policy: SwingPolicy
    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=2)
    created_at: datetime
    target_session: date
    history: SwingMAHistory | SwingBaseHistory | SwingHistory
    ma_period: MAPeriod | None = Field(default=None, exclude_if=lambda v: v is None)
    hourly_history: SwingHourlyHistory | None = Field(default=None, exclude_if=lambda v: v is None)
    instrument: OptionInstrument
    carry_exit_session: date | None = None

    @model_validator(mode="after")
    def enrollment(self):
        if self.policy.target_derivation is None or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Explicit target derivation and unique allowed symbols required")
        return self


@exact
def derive_geometry(seed, policy):
    """Use original native stop rounding and fixed 1/2/3R; no current quote or model."""
    seed = SwingSeed.model_validate(seed.model_dump(warnings=False))
    policy = SwingPolicy.model_validate(policy.model_dump(warnings=False))
    if policy.target_derivation != "original-risk-ladder-v1":
        raise ValueError("Explicit original Swing risk ladder required")
    call = seed.instrument.contract.right == "CALL"
    bar = seed.history.bars[-1]
    reference = bar.high if call else bar.low
    stop = _metric(
        bar.low * (1 - policy.stop_buffer_fraction)
        if call
        else bar.high * (1 + policy.stop_buffer_fraction),
        ROUND_CEILING if call else ROUND_FLOOR,
    )
    if policy.ma_pullback is not None:
        from app.options.swing_ma import evaluate_ma

        ma = evaluate_ma(seed)
        reference, stop = ma.reference, ma.invalidation
    elif policy.daily_base is not None:
        from app.options.swing_base import evaluate_base

        base = evaluate_base(seed)
        reference, stop = base.reference, base.invalidation
    sign = 1 if call else -1
    risk = (reference - stop) * sign
    targets = tuple(reference + sign * risk * n for n in (1, 2, 3))
    if risk <= 0 or any(v <= 0 for v in targets):
        raise ValueError("Positive directional original risk and all three objectives required")
    return SwingTargetGeometry(
        policy_hash=fingerprint(policy),
        inputs_hash=fingerprint(seed.model_dump(exclude={"first_target", "target_geometry"})),
        reference=reference,
        invalidation=stop,
        risk=risk,
        targets=targets,
    )


def target_issues(seed, policy):
    from app.options.swing_base import input_issues

    # Family input is never accepted under an unrelated legacy enrollment.
    issues = input_issues(
        seed,
        policy,
        XNYSCalendar() if policy.daily_base is not None or policy.ma_pullback is not None else None,
    )
    if issues:
        return issues
    if policy.target_derivation is None:
        return ("SWING_DERIVED_TARGET_POLICY_REQUIRED",) if seed.target_geometry is not None else ()
    try:
        expected = derive_geometry(seed, policy)
    except (ValueError, ArithmeticError):
        return ("SWING_DERIVED_TARGET_GEOMETRY_INVALID",)
    if seed.target_geometry != expected or seed.first_target != expected.targets[0]:
        return ("SWING_ORIGINAL_DERIVED_TARGETS_REQUIRED",)
    return ()


def verify_stored_targets(db, scan, policy):
    """Rebuild new-enrollment objectives from the retained native seed and selected scan."""
    row = db.execute(
        "SELECT seed_hash,seed_json FROM execution_option_swing_seeds WHERE session=? AND symbol=?",
        (scan.seed.target_session.isoformat(), scan.symbol),
    ).fetchone()
    seed = SwingSeed.model_validate_json(row[1]) if row else None
    if (
        seed is None
        or seed != scan.seed
        or row[0] != fingerprint(seed)
        or target_issues(seed, policy)
        or scan.observations[0].reference != seed.target_geometry.reference
        or scan.observations[0].invalidation != seed.target_geometry.invalidation
    ):
        raise ValueError("SWING_STORED_ORIGINAL_TARGETS_CHANGED")
    verify_family_scan(scan, policy)


def verify_family_scan(scan, policy):
    from app.options.swing_base import evaluate_base
    from app.options.swing_ma import evaluate_ma

    ma = evaluate_ma(scan.seed) if policy.ma_pullback is not None else None
    base = evaluate_base(scan.seed) if policy.daily_base is not None else None
    family = (
        MA_FAMILIES[ma.period]
        if ma is not None
        else "SWING_DAILY_BASE"
        if base is not None
        else "SWING_DAILY_BREAKOUT"
    )
    if (
        scan.ma_evidence != ma
        or (ma is not None and ma.reasons)
        or scan.base_evidence != base
        or scan.observations[0].family != family
        or (base is not None and base.reasons)
    ):
        raise ValueError("SWING_ORIGINAL_FAMILY_EVIDENCE_REQUIRED")


def build_swing_seed(request):
    """Generate before locking. Native admission still independently checks the owner."""
    request = SwingSeedBuildRequest.model_validate(request.model_dump(warnings=False))
    seed = SwingSeed(**request.model_dump(exclude={"version", "policy", "symbols"}))
    geometry = derive_geometry(seed, request.policy)
    seed = SwingSeed.model_validate(
        seed.model_dump() | {"first_target": geometry.targets[0], "target_geometry": geometry}
    )
    issues = seed_issues(seed, request.policy, XNYSCalendar(), request.symbols)
    if issues:
        raise ValueError("Invalid original Swing seed: " + ", ".join(issues))
    return seed


def build_seed_bundle(request):
    seed = build_swing_seed(request)
    request = SwingSeedBuildRequest.model_validate(request.model_dump(warnings=False))
    result = {
        "version": "swing-derived-seed-bundle-v1",
        "authority": False,
        "request": request.model_dump(mode="json"),
        "seed": seed.model_dump(mode="json"),
    }
    return result | {"bundle_hash": fingerprint(result)}


def verify_seed_bundle(bundle, expected_hash):
    if set(bundle) != {"version", "authority", "request", "seed", "bundle_hash"} or (
        len(json.dumps(bundle, allow_nan=False).encode()) > MAX_BYTES
    ):
        raise ValueError("Bounded exact Swing seed envelope required")
    rebuilt = build_seed_bundle(SwingSeedBuildRequest.model_validate(bundle["request"]))
    if rebuilt != bundle or rebuilt["bundle_hash"] != expected_hash:
        raise ValueError("Original Swing seed differs from retained source and hash")
    return SwingSeed.model_validate(rebuilt["seed"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.request.is_absolute() or not args.output.is_absolute():
        parser.error("Absolute request and new output paths required")
    with args.request.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        parser.error("Bounded Swing seed request required")
    result = build_seed_bundle(SwingSeedBuildRequest.model_validate_json(raw))
    with args.output.open("x") as output:
        output.write(json.dumps(result, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
