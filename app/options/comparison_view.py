"""Compact historical comparison evidence for the observer; no evaluation on page reads."""

import json
import os
import sqlite3
import stat
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import exact, fingerprint
from app.options.entry_reasoning import Digest
from app.options.evaluation_models import Arm, EvaluationBundle
from app.options.models import Money, Name, OptionRecord

MAX_VIEW_BYTES = 256 * 1024


class ComparisonPoint(OptionRecord):
    session: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: Literal["COMPLETE", "INCONCLUSIVE"]
    reasons: tuple[Name, ...] = Field(max_length=100)
    net_change: Money | None
    equity: Money | None
    deterministic_equity: Money | None
    spy_equity: Money | None
    venue_fees: Money | None
    entry_model_cost: Money | None
    management_model_cost: Money | None
    unknown_model_calls: int | None = Field(ge=0, le=100)
    data_cost: Money | None
    host_cost: Money | None


class StoredComparison(OptionRecord):
    version: Literal["stored-options-comparison-v1"] = "stored-options-comparison-v1"
    mode: Literal["OFFLINE_FIXTURE_EVALUATION"] = "OFFLINE_FIXTURE_EVALUATION"
    execution_authority: Literal[False] = False
    live_enabled: Literal[False] = False
    economic_conclusion: Literal["INCONCLUSIVE"] = "INCONCLUSIVE"
    experiment_id: Name
    population_id: Name
    account_id: Name
    arm: Arm
    manifest_hash: Digest
    evidence_hash: Digest
    strategy_hash: Digest
    configuration_hash: Digest
    event_hash: Digest
    revision: int = Field(ge=1, le=10000, strict=True)
    through: datetime
    initial_capital: Money = Field(gt=0)
    points: tuple[ComparisonPoint, ...] = Field(min_length=1, max_length=60)
    recorded_market_verified: bool

    @model_validator(mode="after")
    def historical(self):
        keys = [p.session for p in self.points]
        if keys != sorted(set(keys)) or keys[-1] != self.through.date().isoformat():
            raise ValueError("Ordered historical session boundaries required")
        broken = False
        for p in self.points:
            broken = broken or p.status != "COMPLETE"
            values = (p.equity, p.deterministic_equity, p.spy_equity)
            if broken and any(v is not None for v in values):
                raise ValueError("Incomplete paths cannot retain cumulative values")
            if not broken and any(v is None for v in values):
                raise ValueError("Complete prefix requires matched cumulative values")
        return self


def read_private_json(path, maximum):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Explicit absolute evidence path required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("Private bounded comparison evidence required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if len(raw) > maximum or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Comparison changed during read")
    return json.loads(raw)


@exact
def build_comparison(result, arm):
    """Explicit offline materialization, independently checking the reported arithmetic.

    This checks supplied native export content, not provider authenticity or host
    ownership. Market verification remains a claim from the stored export.
    """
    from app.options.evaluation import evaluate

    bundle = EvaluationBundle.model_validate(result["bundle"])
    report = result["report"]
    definition = next((a for a in bundle.manifest.arms if a.arm == arm), None)
    if (
        definition is None
        or report["manifest_hash"] != fingerprint(bundle.manifest)
        or report["evidence_hash"] != fingerprint(bundle)
        or report["mode"] != "OFFLINE_FIXTURE_EVALUATION"
        or report["economic_conclusion"] != "INCONCLUSIVE"
        or report["execution_authority"] is not False
        or report["live_enabled"] is not False
        or type(report["recorded_market_verified"]) is not bool
        or len(report["sessions"]) != len(bundle.manifest.sessions)
    ):
        raise ValueError("Exact authority-free native comparison required")
    # No sealed tapes are opened here. Compare arm accounting and SPY endpoints;
    # retain stricter incompleteness from the original tape-backed report.
    arithmetic = evaluate(bundle)
    equity = deterministic = spy = definition.policy.capital
    broken, points = False, []
    for saved, checked, session in zip(
        report["sessions"], arithmetic["sessions"], bundle.manifest.sessions, strict=True
    ):
        if (
            saved["session"] != session.key
            or saved["arms"] != checked["arms"]
            or saved["spy_price_return"] != checked["spy_price_return"]
            or saved["status"] not in {"COMPLETE", "INCONCLUSIVE"}
            or (
                saved["status"] == "COMPLETE"
                and (
                    saved["reasons"]
                    or any(a["status"] != "COMPLETE" for a in checked["arms"].values())
                    or checked["spy_price_return"] is None
                )
            )
        ):
            raise ValueError("Stored comparison arithmetic mismatch")
        row = saved["arms"][arm]
        broken = broken or saved["status"] != "COMPLETE"
        if not broken:
            equity += Decimal(row["net_change"])
            deterministic += Decimal(saved["arms"]["A"]["net_change"])
            spy *= 1 + Decimal(saved["spy_price_return"])
        roles = row["model_cost_by_role"]
        points.append(
            ComparisonPoint(
                session=session.key,
                status=saved["status"],
                reasons=tuple(dict.fromkeys([*saved["reasons"], *row["reasons"]])),
                net_change=row["net_change"],
                equity=None if broken else equity,
                deterministic_equity=None if broken else deterministic,
                spy_equity=None if broken else spy.quantize(Decimal(".000000000001")),
                venue_fees=row["venue_fees"],
                entry_model_cost=roles["ENTRY"]["known_cost"] if roles else None,
                management_model_cost=roles["MANAGEMENT"]["known_cost"] if roles else None,
                unknown_model_calls=row["unknown_model_calls"],
                data_cost=row["allocated_data_cost"],
                host_cost=row["allocated_host_cost"],
            )
        )
    final = next(
        (r for r in bundle.evidence if r.arm == arm and r.session_key == points[-1].session), None
    )
    proofs = [
        p
        for p in result["source_proof"]
        if p["arm"] == arm and p["session_key"] == points[-1].session
    ]
    if (
        final is None
        or len(proofs) != 1
        or proofs[0]["export_hash"] != fingerprint(final)
        or proofs[0]["execution_authority"] is not False
        or proofs[0]["source_kind"] != "READ_ONLY_NATIVE_FIXTURE_JOURNAL"
    ):
        raise ValueError("Native closing source proof required")
    proof = proofs[0]
    if proof["strategy_hash"] != definition.strategy_hash:
        raise ValueError("Frozen comparison strategy mismatch")
    return StoredComparison(
        experiment_id=bundle.manifest.experiment_id,
        population_id=definition.limits.population_id,
        account_id=definition.limits.account_id,
        arm=arm,
        manifest_hash=fingerprint(bundle.manifest),
        evidence_hash=fingerprint(bundle),
        strategy_hash=proof["strategy_hash"],
        configuration_hash=proof["configuration_hash"],
        event_hash=proof["event_hash"],
        revision=proof["revision"],
        through=bundle.manifest.sessions[-1].closes_at,
        initial_capital=definition.policy.capital,
        points=tuple(points),
        recorded_market_verified=report["recorded_market_verified"],
    )


def stored_comparison(path, db, population_id, now):
    """Bound one compact view to this journal's immutable historical audit prefix."""
    if path is None:
        return {"status": "NOT_CONFIGURED"}
    try:
        from app.options.evaluation_export import strategy_hash

        envelope = read_private_json(path, MAX_VIEW_BYTES)
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"view", "digest"}
            or fingerprint(envelope["view"]) != envelope["digest"]
        ):
            raise ValueError("Sealed comparison content required")
        view = StoredComparison.model_validate(envelope["view"])
        control = db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()
        strategy = db.execute(
            "SELECT policy_json FROM execution_option_strategy WHERE id=1"
        ).fetchone()
        config = json.loads(control[0])
        if (
            view.population_id != population_id
            or view.account_id != config["limits"]["account_id"]
            or fingerprint(config) != view.configuration_hash
            or strategy is None
            or strategy_hash(json.loads(strategy[0])) != view.strategy_hash
            or view.through > now
        ):
            raise ValueError("Comparison population or boundary mismatch")
        events = db.execute(
            "SELECT * FROM execution_events WHERE sequence<=? ORDER BY sequence LIMIT 10001",
            (view.revision,),
        ).fetchall()
        if (
            len(events) != view.revision
            or fingerprint([dict(e) for e in events]) != view.event_hash
        ):
            raise ValueError("Historical comparison audit prefix mismatch")
        return {"status": "AVAILABLE", **view.model_dump(mode="json")}
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, ArithmeticError):
        return {"status": "UNAVAILABLE", "reason": "STORED_COMPARISON_UNAVAILABLE"}


def write_comparison(path, view):
    """Create and sync one private immutable-by-API view in an existing private directory."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Absolute new comparison path required")
    value = StoredComparison.model_validate(view.model_dump()).model_dump(mode="json")
    raw = json.dumps({"view": value, "digest": fingerprint(value)}, sort_keys=True).encode()
    if len(raw) > MAX_VIEW_BYTES:
        raise ValueError("Comparison projection exceeds bound")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("Private owned comparison directory required")
        fd = os.open(
            path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)


@exact
def chart_data(view):
    """Bounded SVG coordinates only; no prices, trades or account values are inferred."""
    if view["status"] != "AVAILABLE" or not any(p["equity"] is not None for p in view["points"]):
        return None
    capital = Decimal(view["initial_capital"])
    columns = (
        ("equity", "Selected account"),
        ("deterministic_equity", "Model-off A"),
        ("spy_equity", "SPY session price"),
    )
    values = [
        capital,
        *(Decimal(p[k]) for p in view["points"] for k, _ in columns if p[k] is not None),
    ]
    lower, upper = min(values), max(values)
    margin = max((upper - lower) / 10, Decimal(".01"))
    lower, upper = lower - margin, upper + margin
    y = lambda value: format(Decimal(190) - (value - lower) / (upper - lower) * 160, ".2f")
    count = len(view["points"])
    lines = []
    for key, label in columns:
        points = ["60," + y(capital)]
        for n, p in enumerate(view["points"], 1):
            if p[key] is None:
                break
            x = Decimal(60) + Decimal(620) * n / count
            points.append(format(x, ".2f") + "," + y(Decimal(p[key])))
        lines.append({"key": key, "label": label, "points": " ".join(points)})
    return {
        "lines": lines,
        "cash_y": y(capital),
        "ticks": [
            {"y": y(v), "label": format(v, ".2f")} for v in (upper, (upper + lower) / 2, lower)
        ],
        "first": view["points"][0]["session"],
        "first_x": format(Decimal(60) + Decimal(620) / count, ".2f"),
        "last": view["points"][-1]["session"],
    }
