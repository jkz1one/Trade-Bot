"""One frozen stock/options/Scope choice on the existing native strategy journal."""

import json

from app.execution.engine import ExecutionBlocked
from app.mixed.sources import (
    StockSelectionPolicy,
    StockSourceCandidate,
    candidates,
    validate_source,
)
from app.options.engine import fingerprint
from app.options.selection import parse_candidate
from app.options.swing_base_models import SWING_FAMILIES


def configuration(db):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='execution_option_strategy'"
    ).fetchone():
        return None
    row = db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()
    cfg = json.loads(row[0]) if row else {}
    if "mixed_replay" in cfg:
        from app.mixed.replay_enrollment import validate_stored

        validate_stored(cfg)
    elif "stocks" in cfg and "replay_model" in cfg:
        raise ExecutionBlocked("MIXED_REPLAY_CONFIGURATION_REQUIRED")
    return StockSelectionPolicy.model_validate(cfg["stocks"]) if "stocks" in cfg else None


def tables(db, *, create):
    if not create:
        for name in ("execution_mixed_stock_sources", "execution_mixed_stock_terminals"):
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                raise ExecutionBlocked("STOCK_SOURCE_JOURNAL_MISSING")
        return
    db.execute(
        "CREATE TABLE IF NOT EXISTS execution_mixed_stock_sources(session TEXT NOT NULL,symbol TEXT NOT NULL,source_hash TEXT NOT NULL,source_json TEXT NOT NULL,PRIMARY KEY(session,symbol))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS execution_mixed_stock_terminals(source_hash TEXT NOT NULL,family TEXT NOT NULL,evidence_json TEXT NOT NULL,PRIMARY KEY(source_hash,family))"
    )


def lock(c, db, item):
    if item.swing is None:
        return
    s = validate_source(item.swing, c.stock_policy.swing, c.engine.calendar)
    identity = (s.target_session.isoformat(), s.instrument.symbol)
    row = db.execute(
        "SELECT source_hash FROM execution_mixed_stock_sources WHERE session=? AND symbol=?",
        identity,
    ).fetchone()
    if row and row[0] != fingerprint(s):
        raise ExecutionBlocked("STOCK_ORIGINAL_SOURCE_CHANGED")
    if not row:
        db.execute(
            "INSERT INTO execution_mixed_stock_sources VALUES(?,?,?,?)",
            (*identity, fingerprint(s), s.model_dump_json()),
        )
        c.engine.journal.event(
            db,
            c.now(),
            "STOCK_SOURCE_LOCKED",
            {"source_hash": fingerprint(s), "session": identity[0], "symbol": identity[1]},
        )


def retire(engine, db, digest, family, reason, evidence, now):
    if db.execute(
        "SELECT 1 FROM execution_mixed_stock_terminals WHERE source_hash=? AND family=?",
        (digest, family),
    ).fetchone():
        return
    payload = {
        "source_hash": digest,
        "family": family,
        "reason": reason,
        "observed_at": now.isoformat(),
        "evidence": evidence,
    }
    db.execute(
        "INSERT INTO execution_mixed_stock_terminals VALUES(?,?,?)",
        (digest, family, json.dumps(payload, sort_keys=True)),
    )
    engine.journal.event(db, now, "STOCK_SOURCE_RETIRED", payload)


def receipt(policy, key, evidence):
    choices = []
    for raw in evidence.get("stock_candidates", []):
        c = StockSourceCandidate.model_validate(raw["candidate"])
        if raw["admission"]["outcome"] != "APPROVED":
            raise ValueError("Only admitted stock candidates may compete")
        choices.append(
            {
                "asset": "STOCK",
                "family": c.proposal.family,
                "candidate_id": c.candidate_id,
                "candidate_hash": fingerprint(raw),
                "source_key": key,
            }
        )
    for raw in evidence["candidates"]:
        c = parse_candidate(raw)
        if c.admission.outcome != "APPROVED":
            raise ValueError("Only admitted option candidates may compete")
        choices.append(
            {
                "asset": "OPTION",
                "family": "SWING" if c.family in SWING_FAMILIES else "DEGEN",
                "candidate_id": c.candidate_id,
                "candidate_hash": fingerprint(c),
                "source_key": key,
            }
        )
    if evidence.get("scope_candidate") is not None:
        from app.options.scope_execution import lineage

        packet = evidence["scope_candidate"]
        label = lineage(packet)
        if packet["execution_blockers"]:
            raise ValueError("Blocked Scope candidate")
        choices.append(
            {
                "asset": "OPTION",
                "family": "SCOPE",
                "candidate_id": label.candidate_id,
                "candidate_hash": fingerprint(packet),
                "source_key": label.opportunity_key,
            }
        )
    if (
        len(choices) > 64
        or len({(x["asset"], x["candidate_id"]) for x in choices}) != len(choices)
        or any(x["family"] not in policy.family_priority for x in choices)
    ):
        raise ValueError("Bounded unique enrolled mixed candidates required")
    choices.sort(
        key=lambda x: (
            policy.family_priority.index(x["family"]),
            policy.asset_priority.index(x["asset"]),
        )
    )
    chosen = choices[0] if choices else None
    if policy.paid_selection is not None:
        chosen = None
        plan = evidence.get("entry_result", {}).get("plan", {})
        if plan.get("action") == "ENTER":
            matches = [
                x
                for x in choices
                if (
                    (
                        x["asset"] == "STOCK"
                        and plan.get("stock") is True
                        and x["candidate_id"] == plan.get("candidate_id")
                    )
                    or (
                        x["asset"] == "OPTION"
                        and plan.get("stock") is False
                        and (
                            (
                                x["family"] == "SCOPE"
                                and plan.get("scope") is True
                                and x["candidate_hash"] == plan.get("candidate_id")
                            )
                            or (
                                x["family"] != "SCOPE"
                                and plan.get("scope") is False
                                and x["candidate_id"] == plan.get("candidate_id")
                            )
                        )
                    )
                )
            ]
            if len(matches) != 1:
                raise ValueError("MIXED_EXACT_MODEL_SELECTION_REQUIRED")
            chosen = dict(matches[0])
            if chosen["family"] == "SCOPE" and evidence.get("scope_fresh_candidate"):
                from app.options.scope_execution import lineage

                chosen["source_key"] = lineage(evidence["scope_fresh_candidate"]).opportunity_key
    return {
        "version": policy.version,
        "cycle_key": key,
        "policy_hash": fingerprint(policy),
        "choices": choices,
        "selected": chosen,
    }


def collect(c, key, frame, evidence):
    from app.mixed.native_execution import review
    from app.mixed.native_store import history as cash_history

    by_symbol = {x.quote.instrument.symbol: x for x in frame.stocks}
    histories = {x.symbol: x for x in frame.histories}
    if len(by_symbol) != len(frame.stocks) or set(by_symbol) != set(c.policy.symbols):
        raise ValueError("EXACT_STOCK_SOURCE_COVERAGE_REQUIRED")
    accepted, rejected = [], {}
    with c.engine.journal.write() as db:
        c._bound(db)
        for symbol in c.policy.symbols:
            item = by_symbol[symbol]
            if c.stock_policy.swing is None and (
                item.swing is not None or item.catalyst is not None
            ):
                raise ValueError("STOCK_SWING_NOT_ENROLLED")
            if c.stock_policy.swing is not None:
                if item.swing is None or item.catalyst is None:
                    raise ValueError("STOCK_COMPLETE_SWING_SOURCE_REQUIRED")
                lock(c, db, item)
            proposed, issues, terminals = candidates(
                item,
                histories[symbol],
                c.policy,
                c.stock_policy,
                c.engine.policy,
                c.engine.calendar,
                now=c.now(),
            )
            rejected[symbol] = issues
            for family, reason in terminals.items():
                retire(
                    c.engine,
                    db,
                    fingerprint(item.swing),
                    family,
                    reason,
                    item.model_dump(mode="json"),
                    c.now(),
                )
            for candidate in proposed:
                if (
                    candidate.proposal.family == "SWING"
                    and db.execute(
                        "SELECT 1 FROM execution_mixed_stock_terminals WHERE source_hash=? AND family=?",
                        (candidate.proposal.source_hash, candidate.setup_family),
                    ).fetchone()
                ):
                    rejected[symbol][candidate.setup_family] = ("STOCK_SOURCE_RETIRED",)
                    continue
                try:
                    admission, account, window = review(
                        c.engine, db, candidate.proposal, item.quote, c.now()
                    )
                    if admission.outcome == "APPROVED":
                        accepted.append(
                            {
                                "candidate": candidate.model_dump(mode="json"),
                                "admission": admission.model_dump(mode="json"),
                                "account_revision": c.engine.journal.revision(db),
                                "snapshot_id": account.snapshot_id,
                                "history": cash_history(c.engine, db, as_of=c.now()).model_dump(
                                    mode="json"
                                ),
                                "account": account.model_dump(mode="json"),
                                "session": window.model_dump(mode="json"),
                            }
                        )
                    else:
                        rejected[symbol][candidate.setup_family] = admission.reasons
                except ExecutionBlocked as exc:
                    rejected[symbol][candidate.setup_family] = (str(exc),)
    evidence.update(stock_candidates=accepted, stock_rejections=rejected)


def select(c, key, evidence):
    evidence["mixed_selection"] = receipt(c.stock_policy, key, evidence)
    c._pending_evidence(key, evidence)
    return evidence["mixed_selection"]["selected"]


def selected(db, source_key):
    policy = configuration(db)
    if policy is None:
        return None
    rows = db.execute(
        "SELECT cycle_key,inputs_json,result_json,started_at,fingerprint FROM execution_option_opportunities WHERE cycle_key=? OR json_extract(result_json,'$.mixed_selection.selected.source_key')=? LIMIT 2",
        (source_key, source_key),
    ).fetchall()
    matches = []
    for row in rows:
        data = json.loads(row["result_json"])
        chosen = data.get("mixed_selection", {}).get("selected")
        if chosen and chosen["source_key"] == source_key:
            matches.append((row, data, chosen))
    if len(matches) != 1:
        raise ExecutionBlocked("MIXED_ORIGINAL_SELECTION_REQUIRED")
    row, data, chosen = matches[0]
    if data["mixed_selection"] != receipt(policy, row["cycle_key"], data):
        raise ExecutionBlocked("MIXED_SELECTION_CHANGED")
    return policy, row, data, chosen


def guard_option(db, source_key, proposal, quote):
    if proposal.action != "OPEN_LONG":
        return
    result = selected(db, source_key)
    if result is None:
        return
    policy, row, data, choice = result
    if policy.paid_selection is not None:
        from app.mixed.entry import validate_stored

        validate_stored(db, row["cycle_key"], data)
    if choice["asset"] != "OPTION":
        raise ExecutionBlocked("MIXED_SELECTED_STOCK_REQUIRED")
    if choice["family"] != "SCOPE":
        raw = next(x for x in data["candidates"] if x["candidate_id"] == choice["candidate_id"])
        candidate = parse_candidate(raw)
        if (
            (
                candidate.proposal != proposal
                if policy.paid_selection is None
                else candidate.proposal.contract != proposal.contract
            )
            or quote is None
            or quote.instrument != candidate.instrument
        ):
            raise ExecutionBlocked("MIXED_SELECTED_OPTION_CHANGED")


def guard_stock(engine, db, source_key, proposal, quote, now, *, original=False):
    if proposal.action != "OPEN_LONG":
        return None
    result = selected(db, source_key)
    if result is None:
        return None
    policy, row, data, choice = result
    if engine is None:
        from app.options.lifecycle import OptionExecutionPolicy
        from app.robinhood.schedule import XNYSCalendar

        owner = json.loads(
            db.execute("SELECT config_json FROM execution_control WHERE id=1").fetchone()[0]
        )
        execution, calendar = OptionExecutionPolicy.model_validate(owner["policy"]), XNYSCalendar()
    else:
        execution, calendar = engine.policy, engine.calendar
    if choice["asset"] != "STOCK":
        raise ExecutionBlocked("MIXED_SELECTED_OPTION_REQUIRED")
    from datetime import datetime

    from app.options.coordinator import DegenFrame
    from app.options.degen import DegenPolicy
    from app.options.engine import clock

    raw = next(
        x
        for x in data["stock_candidates"]
        if x["candidate"]["candidate_id"] == choice["candidate_id"]
    )
    candidate = StockSourceCandidate.model_validate(raw["candidate"])
    frame = DegenFrame.model_validate_json(row["inputs_json"])
    if fingerprint(frame) != row["fingerprint"]:
        raise ExecutionBlocked("STOCK_ORIGINAL_FRAME_CHANGED")
    from datetime import timedelta

    from app.mixed.governor import admit_stock
    from app.mixed.models import CashHistory
    from app.options.models import OptionAccount, SessionWindow

    h = CashHistory.model_validate(raw["history"])
    a = OptionAccount.model_validate(raw["account"])
    w = SessionWindow.model_validate(raw["session"])
    reviewed = admit_stock(
        candidate.proposal,
        next(x.quote for x in frame.stocks if x.quote.instrument == candidate.proposal.instrument),
        h,
        w,
        now=h.captured_at,
        reconciled=a.reconciled,
        entry_halted=a.entry_halted,
    )
    if reviewed.outcome != "APPROVED":
        raise ExecutionBlocked("STOCK_ORIGINAL_CANDIDATE_ADMISSION_CHANGED")
    reviewed = reviewed.model_copy(
        update={
            "approval_expires_at": min(
                reviewed.approval_expires_at,
                a.captured_at + timedelta(seconds=h.policy.options.account_max_age_seconds),
            )
        }
    )
    if reviewed.model_dump(mode="json") != raw["admission"] or a.snapshot_id != raw["snapshot_id"]:
        raise ExecutionBlocked("STOCK_ORIGINAL_CANDIDATE_ADMISSION_CHANGED")
    cfg = json.loads(
        db.execute("SELECT policy_json FROM execution_option_strategy WHERE id=1").fetchone()[0]
    )
    item = next(x for x in frame.stocks if x.quote.instrument == candidate.proposal.instrument)
    history = next(x for x in frame.histories if x.symbol == item.quote.instrument.symbol)
    at = clock(datetime.fromisoformat(row["started_at"]))
    rebuilt, _, _ = candidates(
        item, history, DegenPolicy.model_validate(cfg["setup"]), policy, execution, calendar, now=at
    )
    if (
        candidate not in rebuilt
        or proposal != candidate.proposal
        or quote is None
        or quote.instrument != proposal.instrument
    ):
        raise ExecutionBlocked("STOCK_ORIGINAL_SELECTED_SOURCE_CHANGED")
    if not original:
        from app.options.governor import _fresh

        limits = execution.mixed_owner.stocks
        if (
            quote.source != limits.quote_source
            or not quote.complete
            or quote.entitlement != "REALTIME"
            or not _fresh(
                quote.source_at,
                quote.received_at,
                now,
                limits.quote_max_age_seconds,
                limits.max_receive_lag_seconds,
            )
        ):
            raise ExecutionBlocked("STOCK_FRESH_SELECTION_QUOTE_REQUIRED")
    if proposal.family == "SWING":
        lockrow = db.execute(
            "SELECT source_hash,source_json FROM execution_mixed_stock_sources WHERE session=? AND symbol=?",
            (item.swing.target_session.isoformat(), proposal.instrument.symbol),
        ).fetchone()
        if (
            lockrow is None
            or lockrow[0] != proposal.source_hash
            or lockrow[1] != item.swing.model_dump_json()
        ):
            raise ExecutionBlocked("STOCK_ORIGINAL_SOURCE_LOCK_REQUIRED")
        if not original:
            if db.execute(
                "SELECT 1 FROM execution_mixed_stock_terminals WHERE source_hash=? AND family=?",
                (proposal.source_hash, candidate.setup_family),
            ).fetchone():
                raise ExecutionBlocked("STOCK_SOURCE_RETIRED")
            if quote.bid <= proposal.original_invalidation or quote.bid >= candidate.targets[0]:
                reason = (
                    "INVALIDATED"
                    if quote.bid <= proposal.original_invalidation
                    else "TARGET_CONSUMED"
                )
                retire(
                    engine,
                    db,
                    proposal.source_hash,
                    candidate.setup_family,
                    reason,
                    quote.model_dump(mode="json"),
                    now,
                )
                raise ExecutionBlocked("STOCK_SOURCE_RETIRED")
            if (
                quote.bid <= candidate.reference
                or abs(quote.ask / candidate.reference - 1) > policy.swing.maximum_chase_fraction
            ):
                raise ExecutionBlocked("STOCK_CURRENT_BREAK_OR_CHASE_REQUIRED")
    if not original and now >= datetime.fromisoformat(raw["admission"]["approval_expires_at"]):
        raise ExecutionBlocked("STOCK_SELECTION_EXPIRED")
    ceiling = dict(raw["admission"])
    if policy.paid_selection is not None:
        from app.mixed.entry import stock_ceiling

        deadline = stock_ceiling(db, row["cycle_key"], data, candidate, now=now, original=original)
        ceiling["approval_expires_at"] = deadline.isoformat()
    return ceiling


async def execute_stock(c, key, frame, evidence, choice):
    raw = next(
        x
        for x in evidence["stock_candidates"]
        if x["candidate"]["candidate_id"] == choice["candidate_id"]
    )
    candidate = StockSourceCandidate.model_validate(raw["candidate"])
    quote = next(
        x.quote for x in frame.stocks if x.quote.instrument == candidate.proposal.instrument
    )
    prepared = c.engine.prepare_stock(key, candidate.proposal, quote, now=c.now())
    if prepared["status"] != "PREPARED":
        return c._finish(
            key,
            {
                **evidence,
                "status": "HOLD",
                "prepared": prepared,
                "reason": "FRESH_STOCK_ADMISSION_REJECTED",
            },
        )
    status = await c.engine.dispatch_stock(prepared["client_id"], quote, now=c.now())
    return c._finish(
        key,
        {
            **evidence,
            "status": status,
            "client_id": prepared["client_id"],
            "candidate_id": candidate.candidate_id,
            "selected_family": candidate.proposal.family,
            "selected_asset": "STOCK",
        },
    )


def entry_lineage(db, entry):
    result = selected(db, entry.source_key)
    if result is None:
        return {}
    _, _, data, choice = result
    if choice["asset"] != "STOCK":
        raise ValueError("Stock entry must retain its original selected asset")
    raw = next(
        x
        for x in data["stock_candidates"]
        if x["candidate"]["candidate_id"] == choice["candidate_id"]
    )
    candidate = StockSourceCandidate.model_validate(raw["candidate"])
    return {
        **(
            {"paid_entry": data["entry_result"]["plan"], "paid_source_key": entry.source_key}
            if "entry_result" in data
            else {}
        ),
        "setup_family": candidate.setup_family,
        "candidate_id": candidate.candidate_id,
        "selection_hash": fingerprint(data["mixed_selection"]),
        "original_targets": [str(x) for x in candidate.targets],
    }
