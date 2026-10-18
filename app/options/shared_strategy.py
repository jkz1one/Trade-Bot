"""Family arbitration inside one existing journal, lease, cash ledger and model slot."""

import json

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.swing import SwingInput, plan_swing_reads, scan_swing, seed_issues


def swing_plans(c, supplied, histories, scans, at):
    items = tuple(SwingInput.model_validate(x.model_dump(warnings=False)) for x in supplied)
    by_symbol = {x.seed.history.symbol: x for x in items}
    if len(by_symbol) != len(items) or not set(by_symbol) <= set(c.policy.symbols):
        raise ValueError("Unique scoped Swing seeds required")
    added_scans, added_plans = [], []
    for intraday in scans:
        item = by_symbol.get(intraday.symbol)
        if item is None:
            raise ExecutionBlocked("EXACT_SWING_SEED_COVERAGE_REQUIRED")
        scan = scan_swing(
            item,
            c.swing_policy,
            intraday,
            histories[intraday.symbol],
            c.engine.calendar,
            c.policy.symbols,
            now=at,
            receive_lag=c.engine.limits.max_receive_lag_seconds,
        )
        with c.engine.journal.read() as db:
            c._bound(db)
            row = db.execute(
                "SELECT seed_hash FROM execution_option_swing_seeds WHERE session=? AND symbol=?",
                (item.seed.target_session.isoformat(), intraday.symbol),
            ).fetchone()
            if c.swing_policy.unfilled_lifecycle is not None:
                from app.options.swing_lifecycle import apply_terminal, load_terminal

                scan = apply_terminal(scan, load_terminal(db, item.seed))
        if row and row[0] != fingerprint(item.seed):
            raise ExecutionBlocked("SWING_SEED_LOCK_CONFLICT")
        added_scans.append(scan)
        added_plans.append(plan_swing_reads(scan, item, c.selection, c.engine.limits, now=at))
    return tuple(added_scans), tuple(added_plans)


def lock_seeds(c, items):
    with c.engine.journal.write() as db:
        c._bound(db)
        for item in items:
            seed = item.seed
            # Invalid/foreign history never establishes a candidate identity.
            if seed.created_at > c.now() or seed_issues(
                seed, c.swing_policy, c.engine.calendar, c.policy.symbols
            ):
                continue
            identity = (seed.target_session.isoformat(), seed.history.symbol)
            digest = fingerprint(seed)
            row = db.execute(
                "SELECT seed_hash FROM execution_option_swing_seeds WHERE session=? AND symbol=?",
                identity,
            ).fetchone()
            if row and row[0] != digest:
                raise ExecutionBlocked("SWING_SEED_LOCK_CONFLICT")
            if row is None:
                db.execute(
                    "INSERT INTO execution_option_swing_seeds VALUES(?,?,?,?)",
                    (*identity, digest, seed.model_dump_json()),
                )
                c.engine.journal.event(
                    db,
                    c.now(),
                    "SWING_SEED_LOCKED",
                    {"session": identity[0], "symbol": identity[1], "seed_hash": digest},
                )
            if c.swing_policy.unfilled_lifecycle is not None:
                from app.options.swing_lifecycle import retire_expired

                retire_expired(c, db, seed)


def review_shared_entry(engine, db, key, proposal, quote, underlying, now):
    """Recheck joint-family membership and Swing conditions at preparation and dispatch."""
    from app.options.governor import _fresh
    from app.options.selection import SwingCandidate, parse_candidate
    from app.options.swing import SwingPolicy, SwingScan

    if (
        proposal.action != "OPEN_LONG"
        or not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='execution_option_strategy'"
        ).fetchone()
    ):
        return
    strategy = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    config = json.loads(strategy[0]) if strategy else {}
    if "swing" not in config:
        return
    policy = SwingPolicy.model_validate(config["swing"])
    row = db.execute(
        "SELECT result_json FROM execution_option_opportunities WHERE cycle_key=?", (key,)
    ).fetchone()
    data = json.loads(row[0]) if row and row[0] else {}
    selected = data.get("entry_result", {}).get("plan", {}).get("candidate_id") or data.get(
        "candidate_id"
    )
    matches = [
        parse_candidate(c) for c in data.get("candidates", []) if c["candidate_id"] == selected
    ]
    if (
        len(matches) != 1
        or quote is None
        or underlying is None
        or matches[0].instrument != quote.instrument
        or matches[0].proposal.contract != proposal.contract
    ):
        raise ExecutionBlocked("SHARED_ADMITTED_CANDIDATE_REQUIRED")
    candidate = matches[0]
    if not isinstance(candidate, SwingCandidate):
        return
    scans = [
        SwingScan.model_validate(s)
        for s in data.get("scans", [])
        if s.get("version") == "swing-next-session-v1" and s.get("symbol") == candidate.symbol
    ]
    if len(scans) != 1:
        raise ExecutionBlocked("SWING_SCAN_REQUIRED")
    scan = scans[0]
    seed = scan.seed
    if policy.unfilled_lifecycle is not None:
        from app.options.swing_lifecycle import load_terminal

        if scan.terminal is not None or load_terminal(db, seed) is not None:
            raise ExecutionBlocked("SWING_SEED_TERMINAL")
    row = db.execute(
        "SELECT seed_hash FROM execution_option_swing_seeds WHERE session=? AND symbol=?",
        (seed.target_session.isoformat(), seed.history.symbol),
    ).fetchone()
    window = engine.calendar.current_window(now)
    if (
        row is None
        or row[0] != fingerprint(seed)
        or window is None
        or window.session_date != seed.target_session.isoformat()
    ):
        raise ExecutionBlocked("SWING_SEED_LOCK_REQUIRED")
    catalyst = scan.catalyst
    if policy.unfilled_lifecycle in ("observed-invalidation-v2", "observed-lifecycle-v3"):
        from app.options.swing_lifecycle import quote_terminal, retain_owned_terminal

        terminal = quote_terminal(seed, policy, engine.limits, engine.calendar, underlying, now)
        if terminal is not None:
            retain_owned_terminal(engine, db, seed, terminal, now)
            raise ExecutionBlocked("SWING_SEED_TERMINAL")
    if (
        not _fresh(
            catalyst.source_at,
            catalyst.received_at,
            now,
            policy.catalyst_max_age_seconds,
            engine.limits.max_receive_lag_seconds,
        )
        or catalyst.valid_through < window.closes_at
    ):
        raise ExecutionBlocked("SWING_CATALYST_CLEARANCE_EXPIRED")
    reference = scan.observations[0].reference
    call = candidate.instrument.contract.right == "CALL"
    # Both sides must remain beyond the break. Use the adverse side for chase.
    if (
        underlying.symbol != candidate.symbol
        or (underlying.bid <= reference if call else underlying.ask >= reference)
        or abs((underlying.ask if call else underlying.bid) / reference - 1)
        > policy.maximum_chase_fraction
    ):
        raise ExecutionBlocked("SWING_CURRENT_BREAK_OR_CHASE_REJECTED")
