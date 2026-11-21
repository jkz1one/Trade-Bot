"""Complete original Swing source batches, deterministic variants and atomic native locks."""

import json
from datetime import date, datetime
from functools import lru_cache
from typing import Literal

from pydantic import model_validator

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.models import OptionInstrument, OptionRecord
from app.options.selection import ContractMetadata
from app.options.swing import (
    CatalystEvidence,
    SwingHourlyHistory,
    SwingInput,
    SwingMAHistory,
    SwingPolicy,
    SwingSeed,
    seed_issues,
)


class SwingBatchHistory(SwingMAHistory):
    version: Literal["swing-batch-daily-v1"] = "swing-batch-daily-v1"


class SwingBatchSeed(OptionRecord):
    version: Literal["swing-family-batch-v1"] = "swing-family-batch-v1"
    created_at: datetime
    target_session: date
    history: SwingBatchHistory
    hourly_history: SwingHourlyHistory | None = None
    instruments: tuple[OptionInstrument, OptionInstrument]
    carry_exit_session: date | None = None

    @model_validator(mode="after")
    def complete_contracts(self):
        if (
            tuple(i.contract.right for i in self.instruments) != ("CALL", "PUT")
            or len({i.instrument_id for i in self.instruments}) != 2
            or any(i.contract.underlying != self.history.symbol for i in self.instruments)
        ):
            raise ValueError("One exact original CALL and PUT contract, in that order, required")
        return self


class SwingBatchInput(OptionRecord):
    seed: SwingBatchSeed
    metadata: tuple[ContractMetadata, ContractMetadata]
    catalyst: CatalystEvidence | None

    @model_validator(mode="after")
    def exact_metadata(self):
        if tuple(m.instrument for m in self.metadata) != self.seed.instruments or (
            self.catalyst is not None and self.catalyst.symbol != self.seed.history.symbol
        ):
            raise ValueError("Exact batch contracts and symbol-specific catalyst required")
        return self


def family_policy(seed, policy):
    """Select enrolled rule implementations; never use this view as a cohort hash."""
    if policy.family_batch is None:
        return policy
    version = getattr(seed.history, "version", None)
    return policy.model_copy(
        update={
            "higher_levels": policy.higher_levels if version == "swing-level-daily-v1" else None,
            "ma_pullback": policy.ma_pullback if version == "swing-ma-daily-v1" else None,
            "daily_base": policy.daily_base if version == "swing-base-daily-v1" else None,
        }
    )


def batch_seeds(original, policy, calendar, symbols):
    from app.robinhood.schedule import XNYSCalendar

    original = SwingBatchSeed.model_validate(original.model_dump(warnings=False))
    policy = SwingPolicy.model_validate(policy.model_dump(warnings=False))
    if type(calendar) is XNYSCalendar:
        return _original_children(
            original.model_dump_json(), policy.model_dump_json(), tuple(symbols)
        )
    return _batch_seeds(original, policy, calendar, symbols)


@lru_cache(maxsize=16)
def _original_children(original_json, policy_json, symbols):
    # Pure immutable source derivation only. No account, metadata, approval, terminal,
    # database read or present-time result is cached. Any original byte change misses.
    from app.robinhood.schedule import XNYSCalendar

    return _batch_seeds(
        SwingBatchSeed.model_validate_json(original_json),
        SwingPolicy.model_validate_json(policy_json),
        XNYSCalendar(),
        symbols,
    )


def _batch_seeds(original, policy, calendar, symbols):
    """Enumerate every enrolled variant on both applicable sides from one original source.

    Unusable risk geometry remains a blocked seed, not a silently omitted family.
    Source defects reject the entire batch before any lock or candidate planning.
    """
    from app.options.swing_targets import derive_geometry

    original = SwingBatchSeed.model_validate(original.model_dump(warnings=False))
    policy = SwingPolicy.model_validate(policy.model_dump(warnings=False))
    if policy.family_batch is None:
        raise ValueError("Complete Swing batch enrollment required")
    hourly = policy.daily_base or policy.ma_pullback
    if (hourly is not None) != (original.hourly_history is not None):
        raise ValueError("Exact enrolled original hourly coverage required")
    variants = []
    if policy.daily_base:
        variants.append(("swing-base-daily-v1", None, None, ("CALL", "PUT")))
    if policy.ma_pullback:
        variants.extend(
            ("swing-ma-daily-v1", p, None, ("CALL", "PUT")) for p in policy.ma_pullback.periods
        )
    if policy.higher_levels:
        for key in policy.higher_levels.keys:
            rights = (
                ("CALL", "PUT")
                if key == "weekly_open"
                else ("CALL",)
                if key.endswith("high")
                else ("PUT",)
            )
            variants.append(("swing-level-daily-v1", None, key, rights))
    result = []
    digest = fingerprint(original)
    for version, period, key, rights in variants:
        for right in rights:
            seed = SwingSeed.model_validate(
                {
                    "created_at": original.created_at,
                    "target_session": original.target_session,
                    "history": original.history.model_dump() | {"version": version},
                    "hourly_history": original.hourly_history
                    if version != "swing-level-daily-v1"
                    else None,
                    "ma_period": period,
                    "level_key": key,
                    "instrument": original.instruments[0 if right == "CALL" else 1],
                    "carry_exit_session": original.carry_exit_session,
                    "batch_hash": digest,
                }
            )
            # Source checks run before geometry. Missing geometry/first target are the
            # only expected omissions in this pre-builder state.
            issues = set(seed_issues(seed, policy, calendar, symbols)) - {
                "SWING_ORIGINAL_FIRST_TARGET_REQUIRED",
                "SWING_ORIGINAL_DERIVED_TARGETS_REQUIRED",
                "SWING_DERIVED_TARGET_GEOMETRY_INVALID",
            }
            if issues:
                raise ValueError("Invalid complete Swing batch: " + ", ".join(sorted(issues)))
            try:
                geometry = derive_geometry(seed, policy)
            except ValueError as exc:
                # All evidence defects were checked above. Only nonpositive original
                # directional risk/targets are an ordinary blocked setup.
                if (
                    str(exc)
                    != "Positive directional original risk and all three objectives required"
                ):
                    raise
            else:
                seed = seed.model_copy(
                    update={"target_geometry": geometry, "first_target": geometry.targets[0]}
                )
            result.append(seed)
    return tuple(result)


def expand_batches(supplied, policy, calendar, symbols, at):
    batches = tuple(SwingBatchInput.model_validate(x.model_dump(warnings=False)) for x in supplied)
    if len({b.seed.history.symbol for b in batches}) != len(batches) or (
        {b.seed.history.symbol for b in batches} != set(symbols)
    ):
        raise ExecutionBlocked("EXACT_SWING_BATCH_COVERAGE_REQUIRED")
    result = []
    for symbol in symbols:
        batch = next(b for b in batches if b.seed.history.symbol == symbol)
        if batch.seed.created_at > at:
            raise ExecutionBlocked("SWING_BATCH_FROM_FUTURE")
        for seed in batch_seeds(batch.seed, policy, calendar, symbols):
            metadata = batch.metadata[0 if seed.instrument.contract.right == "CALL" else 1]
            result.append(SwingInput(seed=seed, metadata=metadata, catalyst=batch.catalyst))
    return tuple(result)


def frame_items(frame, policy, calendar, symbols, at):
    if frame.swing_unavailable:
        return ()
    if policy is not None and policy.family_batch is not None:
        if frame.swing:
            raise ValueError("Joint Swing requires only complete original batches")
        return expand_batches(frame.swing_batches, policy, calendar, symbols, at)
    if frame.swing_batches:
        raise ValueError("Swing batches require explicit frozen enrollment")
    return frame.swing


def create_tables(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS execution_option_swing_batches(session TEXT NOT NULL,symbol TEXT NOT NULL,batch_hash TEXT NOT NULL,batch_json TEXT NOT NULL,PRIMARY KEY(session,symbol))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS execution_option_swing_batch_seeds(seed_hash TEXT PRIMARY KEY,batch_hash TEXT NOT NULL,seed_json TEXT NOT NULL)"
    )


def lock_batches(c, supplied):
    # Validate complete coverage and every source before opening the write transaction.
    items = expand_batches(supplied, c.swing_policy, c.engine.calendar, c.policy.symbols, c.now())
    with c.engine.journal.write() as db:
        c._bound(db)
        for batch in supplied:
            original = batch.seed
            identity = (original.target_session.isoformat(), original.history.symbol)
            digest = fingerprint(original)
            row = db.execute(
                "SELECT batch_hash,batch_json FROM execution_option_swing_batches WHERE session=? AND symbol=?",
                identity,
            ).fetchone()
            if row and (row[0] != digest or row[1] != original.model_dump_json()):
                raise ExecutionBlocked("SWING_BATCH_LOCK_CONFLICT")
            if row is None:
                db.execute(
                    "INSERT INTO execution_option_swing_batches VALUES(?,?,?,?)",
                    (*identity, digest, original.model_dump_json()),
                )
                for item in items:
                    if item.seed.batch_hash == digest:
                        db.execute(
                            "INSERT INTO execution_option_swing_batch_seeds VALUES(?,?,?)",
                            (fingerprint(item.seed), digest, item.seed.model_dump_json()),
                        )
                c.engine.journal.event(
                    db,
                    c.now(),
                    "SWING_BATCH_LOCKED",
                    {"session": identity[0], "symbol": identity[1], "batch_hash": digest},
                )
        for item in items:
            if item.seed.target_geometry is not None:
                from app.options.swing_lifecycle import retire_expired

                retire_expired(c, db, item.seed)


def seed_lock(db, seed):
    """Return the original lock; batch children are rederived from the frozen root."""
    if seed.batch_hash is None:
        return db.execute(
            "SELECT seed_hash,seed_json FROM execution_option_swing_seeds WHERE session=? AND symbol=?",
            (seed.target_session.isoformat(), seed.history.symbol),
        ).fetchone()
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_swing_batches'"
    ).fetchone():
        return None
    row = db.execute(
        "SELECT batch_hash,batch_json FROM execution_option_swing_batches WHERE session=? AND symbol=?",
        (seed.target_session.isoformat(), seed.history.symbol),
    ).fetchone()
    if row is None:
        return None
    config = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    policy = SwingPolicy.model_validate(config["swing"])
    original = SwingBatchSeed.model_validate_json(row[1])
    from app.robinhood.schedule import XNYSCalendar

    expected = batch_seeds(original, policy, XNYSCalendar(), config["setup"]["symbols"])
    children = db.execute(
        "SELECT seed_hash,seed_json FROM execution_option_swing_batch_seeds WHERE batch_hash=?",
        (row[0],),
    ).fetchall()
    if (
        row[0] != fingerprint(original)
        or seed.batch_hash != row[0]
        or {r[0]: json.loads(r[1]) for r in children}
        != {fingerprint(s): s.model_dump(mode="json") for s in expected}
    ):
        raise ValueError("SWING_ORIGINAL_BATCH_CHANGED")
    return next((r for r in children if r[0] == fingerprint(seed)), None)


def unique_instruments(plans):
    result = {}
    for plan in plans:
        for instrument in plan.instruments:
            key = instrument.instrument_id
            if key in result and result[key] != instrument:
                raise ValueError("Conflicting shared quote instrument identity")
            result[key] = instrument
    if len(result) > 8:
        raise ValueError("Shared quote capacity exceeded")
    return tuple(result.values())


def scan_matches(scan, candidate):
    from app.options.selection import SwingCandidate
    from app.options.swing import SwingScan

    return (
        isinstance(scan, SwingScan) == isinstance(candidate, SwingCandidate)
        and scan.symbol == candidate.symbol
        and (not isinstance(scan, SwingScan) or scan.seed.instrument == candidate.instrument)
        and any(
            o.family == candidate.family and o.right == candidate.instrument.contract.right
            for o in scan.observations
        )
    )


def replay_batches(tape, event, histories, scans):
    """Account-free prefix replay of atomic roots and each original child lifecycle."""
    from app.options.degen import scan_degen
    from app.options.swing import plan_swing_reads, scan_swing
    from app.options.swing_lifecycle import apply_terminal, quote_terminal
    from app.robinhood.schedule import XNYSCalendar

    h, calendar = tape.header, XNYSCalendar()
    roots, locked, terminals = {}, {}, {}
    output_scans, output_plans, missing = [], [], []
    for previous in tape.available(event.recorded_at):
        if previous.sequence > event.sequence:
            break
        items = ()
        conflict = False
        if previous.kind == "CYCLE":
            items = frame_items(
                previous.frame, h.swing, calendar, h.setup.symbols, previous.recorded_at
            )
            identities = {
                (b.seed.target_session, b.seed.history.symbol): fingerprint(b.seed)
                for b in previous.frame.swing_batches
            }
            conflict = any(k in roots and roots[k] != digest for k, digest in identities.items())
            if not conflict:
                roots.update(identities)
                locked.update({fingerprint(item.seed): item.seed for item in items})
        for digest, seed in locked.items():
            quotes = [q for q in previous.frame.underlyings if q.symbol == seed.history.symbol]
            if len(quotes) == 1:
                terminal = quote_terminal(
                    seed, h.swing, h.limits, calendar, quotes[0], previous.recorded_at
                )
                if terminal is not None:
                    terminals.setdefault(digest, terminal)
        if previous.kind != "CYCLE":
            continue
        if conflict:
            if previous.sequence == event.sequence:
                missing.append("SWING_BATCH_LOCK_CONFLICT")
            continue
        prior_histories = {x.symbol: x for x in previous.frame.histories}
        intradays = {
            symbol: scan_degen(
                history,
                h.setup,
                calendar.current_window(previous.recorded_at),
                now=previous.recorded_at,
            )
            for symbol, history in prior_histories.items()
        }
        for item in items:
            symbol = item.seed.history.symbol
            if symbol not in intradays:
                if previous.sequence == event.sequence:
                    missing.append(symbol + ":HISTORY_MISSING")
                continue
            scan = scan_swing(
                item,
                h.swing,
                intradays[symbol],
                prior_histories[symbol],
                calendar,
                h.setup.symbols,
                now=previous.recorded_at,
                receive_lag=h.limits.max_receive_lag_seconds,
            )
            if scan.terminal is not None:
                terminals.setdefault(fingerprint(item.seed), scan.terminal)
            if previous.sequence == event.sequence:
                scan = apply_terminal(scan, terminals.get(fingerprint(item.seed)))
                output_scans.append(scan)
                output_plans.append(
                    plan_swing_reads(scan, item, h.selection, h.limits, now=previous.recorded_at)
                )
    return output_scans, [] if missing else output_plans, missing


def stored_result(raw):
    """Bound the new expanded journal record separately from unchanged wire/model limits."""
    if not isinstance(raw, str) or len(raw.encode()) > 4 * 1024 * 1024:
        raise ValueError("Bounded joint Swing journal required")
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or value.get("swing_batch_version") != "complete-family-batch-v1"
    ):
        raise ValueError("Explicit joint Swing journal contract required")
    for key, limit in (("scans", 30), ("read_plans", 30), ("candidates", 24)):
        if not isinstance(value.get(key, []), list) or len(value.get(key, [])) > limit:
            raise ValueError("Bounded joint Swing journal collections required")
    from app.options.swing import SwingScan

    for scan in value.get("scans", []):
        if scan.get("version") == "swing-next-session-v1":
            parsed = SwingScan.model_validate(scan)
            if parsed.seed.batch_hash is None:
                raise ValueError("Original batch child required")
    return value


def verify_batch_tables(db):
    """Reconstruct the complete original set, including untraded and blocked children."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    names = {"execution_option_swing_batches", "execution_option_swing_batch_seeds"}
    if not tables & names:
        return
    if not names <= tables:
        raise ValueError("Complete original Swing batch tables required")
    strategy = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    config = json.loads(strategy[0]) if strategy else {}
    policy = SwingPolicy.model_validate(config["swing"])
    if policy.family_batch is None:
        raise ValueError("Original Swing batch enrollment required")
    rows = db.execute(
        "SELECT session,symbol,batch_hash,batch_json FROM execution_option_swing_batches"
    ).fetchall()
    expected = set()
    from app.robinhood.schedule import XNYSCalendar

    for row in rows:
        original = SwingBatchSeed.model_validate_json(row[3])
        if (row[0], row[1], row[2]) != (
            original.target_session.isoformat(),
            original.history.symbol,
            fingerprint(original),
        ):
            raise ValueError("Original Swing batch identity changed")
        children = batch_seeds(original, policy, XNYSCalendar(), config["setup"]["symbols"])
        if not seed_lock(db, children[0]):
            raise ValueError("Complete original Swing batch children required")
        expected.update(fingerprint(s) for s in children)
    if {
        r[0] for r in db.execute("SELECT seed_hash FROM execution_option_swing_batch_seeds")
    } != expected:
        raise ValueError("Orphaned or missing original Swing batch children")
