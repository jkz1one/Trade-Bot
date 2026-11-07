#!/usr/bin/env python3
"""Read running or stopped PAPER status without a build, run or provider call."""

import argparse
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo
from pathlib import Path

CODE = re.compile(r"[A-Z][A-Z0-9_]{1,95}\Z")
STATE = Path("/var/lib/trade-bot-connected")
MAX_DECISION_BYTES = 16 * 1024 * 1024
MAX_SUMMARY_FIELD = 65536


def codes(value):
    """Only bounded machine-code leaves from explicitly selected evidence fields."""
    found = set()

    def visit(item, depth=0):
        if depth > 8 or len(found) >= 100:
            return
        if isinstance(item, str) and CODE.fullmatch(item.partition(':')[0]):
            # Native coverage codes may suffix a symbol or provider ID. Keep
            # the machine reason without publishing the identifying suffix.
            found.add(item.partition(':')[0])
        elif isinstance(item, dict):
            for child in list(item.values())[:100]:
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item[:100]:
                visit(child, depth + 1)

    visit(value)
    return sorted(found)


def outcome(raw):
    value = json.loads(raw) if raw else {}
    result = {"status": codes(value.get("status")), "reason": codes(value.get("reason"))}
    for field in ("issues", "blocker", "unavailable_families", "rejections",
                  "stock_rejections", "scope_rejections"):
        selected = codes(value.get(field))
        if selected:
            result[field] = selected
    result['entry_timely'] = value.get('entry_timely') if type(value.get('entry_timely')) is bool else None
    result['scope_admission_reasons'] = codes(value.get('scope_admission_reasons'))
    result["option_candidates"] = len(value.get("candidates") or [])
    result["stock_candidates"] = len(value.get("stock_candidates") or [])
    result["scans"] = []
    for scan in (value.get("scans") or [])[:12]:
        result["scans"].append({
            "symbol": codes(scan.get("symbol")),
            "issues": codes(scan.get("issues")),
            "setups": [{"family": codes(o.get("family")), "status": codes(o.get("status")),
                        "reasons": codes(o.get("reasons"))}
                       for o in (scan.get("observations") or [])[:12]],
        })
    result["contract_exclusions"] = sorted(set(
        code for plan in (value.get("read_plans") or [])[:12]
        for code in codes([plan.get("issues"), plan.get("exclusions")])
    ))
    return result


def decision_evidence(db, key):
    """Project only summary fields; large original histories never enter Python."""
    row = db.execute(
        "SELECT length(CAST(result_json AS BLOB)),CASE "
        "WHEN length(CAST(result_json AS BLOB))<=? THEN json_valid(result_json) ELSE 0 END "
        "FROM execution_option_opportunities WHERE cycle_key=?", (MAX_DECISION_BYTES, key),
    ).fetchone()
    size, valid = row
    if not valid:
        reason = ('MISSING' if size is None else 'TOO_LARGE' if size > MAX_DECISION_BYTES else 'INVALID_JSON')
        return {'evidence_available': False, 'evidence_issue': reason, 'evidence_bytes': size,
                'option_candidates': None, 'stock_candidates': None}
    omitted = []
    deadline = time.monotonic() + 15

    def bounded():
        if time.monotonic() > deadline:
            raise ValueError('DECISION_SUMMARY_TIMEOUT')

    def field(path):
        bounded()
        value, kind, length = db.execute(
            "SELECT CASE WHEN length(json_extract(result_json,?))<=? "
            "THEN json_extract(result_json,?) END,json_type(result_json,?),"
            "length(json_extract(result_json,?)) FROM execution_option_opportunities WHERE cycle_key=?",
            (path, MAX_SUMMARY_FIELD, path, path, path, key),
        ).fetchone()
        if length is not None and length > MAX_SUMMARY_FIELD:
            omitted.append(path)
        if kind in ('true', 'false'):
            return kind == 'true'
        return json.loads(value) if value is not None and kind in ('object', 'array') else value

    def count(path):
        bounded()
        return db.execute(
            "SELECT CASE WHEN json_type(result_json,?)='array' THEN json_array_length(result_json,?) "
            "ELSE 0 END FROM execution_option_opportunities WHERE cycle_key=?", (path, path, key),
        ).fetchone()[0]

    value = {name: field('$.' + name) for name in (
        'status', 'reason', 'issues', 'blocker', 'unavailable_families',
        'rejections', 'stock_rejections', 'scope_rejections')}
    value['entry_timely'] = field('$.entry_timely')
    value['scope_admission_reasons'] = field('$.scope_fresh_review.admission_review.reasons')
    value['scans'] = []
    for index in range(min(count('$.scans'), 12)):
        prefix = f'$.scans[{index}]'
        scan = {name: field(prefix + '.' + name) for name in ('symbol', 'issues', 'evaluated_at')}
        scan['observations'] = [{name: field(f'{prefix}.observations[{n}].{name}')
                                 for name in ('family', 'status', 'reasons')}
                                for n in range(min(count(prefix + '.observations'), 12))]
        value['scans'].append(scan)
    value['read_plans'] = [{name: field(f'$.read_plans[{index}].{name}')
                            for name in ('issues', 'exclusions')}
                           for index in range(min(count('$.read_plans'), 12))]
    summary = outcome(json.dumps(value))
    summary.update(option_candidates=count('$.candidates'), stock_candidates=count('$.stock_candidates'),
                   total_scans=count('$.scans'), scans_omitted=max(0, count('$.scans') - 12))
    summary['inventory_timing'] = inventory_timing(db, key, value['scans'])
    return {'evidence_available': True, 'evidence_bytes': size,
            'omitted_summary_fields': omitted, **summary}


def inventory_timing(db, key, scans):
    """Original saved clocks only, projected without contract IDs or private inputs.

    These diagnostics are not a new inventory validation or a readiness claim.
    They also work for old runs; no provider capture or owner mutation is needed.
    """
    if not scans or 'inputs_json' not in {
            row[1] for row in db.execute('PRAGMA table_info(execution_option_opportunities)')}:
        return []
    valid = db.execute('SELECT CASE WHEN length(CAST(inputs_json AS BLOB))<=? '
                       'THEN json_valid(inputs_json) ELSE 0 END '
                       'FROM execution_option_opportunities WHERE cycle_key=?',
                       (MAX_DECISION_BYTES, key)).fetchone()
    if not valid or not valid[0]:
        return []
    columns = ['symbol', 'source_at', 'received_at']
    projection = ','.join("CASE WHEN json_type(j.value,'$." + name + "')='text' "
                         "AND length(json_extract(j.value,'$." + name + "'))<=128 "
                         "THEN json_extract(j.value,'$." + name + "') END" for name in columns)
    rows = db.execute('SELECT ' + projection + ' FROM execution_option_opportunities o, '
                      "json_each(o.inputs_json,'$.inventories') j WHERE o.cycle_key=? "
                      "AND j.type='object' LIMIT 12", (key,)).fetchall()
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    age_limit = None
    if 'execution_option_strategy' in tables:
        row = db.execute("SELECT json_extract(policy_json,'$.selection.max_metadata_age_seconds') "
                         "FROM execution_option_strategy WHERE id=1 AND json_valid(policy_json)").fetchone()
        if row and type(row[0]) is int and 0 < row[0] <= 60:
            age_limit = row[0]
    results = []
    for symbol, source, received in rows:
        if symbol not in ('SPY', 'QQQ'):
            continue
        matching = [scan for scan in scans if scan.get('symbol') == symbol]
        if len(matching) != 1:
            continue
        evaluated = matching[0].get('evaluated_at')
        try:
            times = [datetime.fromisoformat(s) for s in (source, received, evaluated)]
            if any(t.tzinfo is None or t.utcoffset() is None for t in times):
                continue
        except (TypeError, ValueError):
            continue
        results.append({'symbol': symbol, 'source_at': source, 'received_at': received,
                        'evaluated_at': evaluated,
                        'source_age_seconds': (times[2]-times[0]).total_seconds(),
                        'receive_lag_seconds': (times[1]-times[0]).total_seconds(),
                        'clock_order_valid': times[0] <= times[1] <= times[2],
                        'max_metadata_age_seconds': age_limit})
    return results


def connection(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def amount(value):
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        number = Decimal(value)
        if number.is_finite() and 0 <= number <= Decimal('1e12') and number.as_tuple().exponent >= -30:
            return number
    except InvalidOperation:
        pass
    return None


def spending(db, start, end):
    """Exact settled costs only. Unknown charges stay visible, never become zero."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_model_calls'").fetchone():
        return {'status': 'UNAVAILABLE'}
    first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    day = last.astimezone(ZoneInfo('America/New_York')).date()
    totals = {k: {'settled_cost': Decimal(0), 'unknown_calls': 0} for k in ('run', 'day', 'account_total')}
    with localcontext() as context:
        context.prec = 192
        for raw, at in db.execute('SELECT CASE WHEN length(cost)<=128 THEN cost END,started_at FROM execution_model_calls'):
            try:
                at = datetime.fromisoformat(at)
                if at.tzinfo is None:
                    raise ValueError('Unbound model clock')
            except (ValueError, TypeError):
                return {'status': 'UNAVAILABLE', 'reason': 'MODEL_COST_CLOCK_INVALID'}
            groups = ['account_total']
            if first <= at <= last:
                groups.append('run')
            if at.astimezone(ZoneInfo('America/New_York')).date() == day:
                groups.append('day')
            value = amount(raw)
            for group in groups:
                if value is None:
                    totals[group]['unknown_calls'] += 1
                else:
                    totals[group]['settled_cost'] += value
    budgets = {'daily_budget': None, 'total_budget': None}
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_cost_policy'").fetchone():
        row = db.execute("SELECT CASE WHEN length(policy_json)<=65536 AND json_valid(policy_json) THEN "
                         "json_extract(policy_json,'$.daily_budget') END,CASE WHEN length(policy_json)<=65536 "
                         "AND json_valid(policy_json) THEN json_extract(policy_json,'$.total_budget') END "
                         "FROM execution_cost_policy WHERE id=1").fetchone()
        if row:
            budgets = {key: format(amount(v), 'f') if amount(v) is not None else None
                       for key, v in zip(budgets, row)}
    return {'status': 'INCOMPLETE' if totals['account_total']['unknown_calls'] else 'COMPLETE',
            'day': day.isoformat(), 'timezone': 'America/New_York', 'budgets': budgets,
            'costs': {k: {**v, 'settled_cost': format(v['settled_cost'], 'f')} for k,v in totals.items()}}


def decision_input_issues(decision):
    """Retained blockers only; a HOLD or completed cycle alone proves no scan."""
    missing = codes([decision.get('issues'), decision.get('blocker'),
                     [scan.get('issues') for scan in decision.get('scans', [])]])
    setup_reasons = codes([setup.get('reasons') for scan in decision.get('scans', [])
                          for setup in scan.get('setups', [])])
    missing += [r for r in setup_reasons if r in {
        'COMPLETED_STRUCTURE_INSUFFICIENT', 'HISTORY_UNAVAILABLE_DELAYED_OR_STALE'}]
    missing += [r for r in codes(decision.get('contract_exclusions')) if r in {
        'INVENTORY_BINDING_COVERAGE_OR_FRESHNESS', 'INVENTORY_UNAVAILABLE',
        'SCAN_TIME_OR_STRUCTURE_MISMATCH'}]
    missing += [r for r in codes(decision.get('reason')) if r in {
        'AUTHORITATIVE_RECONCILIATION_REQUIRED', 'PORTFOLIO_PROTECTION_REQUIRED'}]
    return sorted(set(missing))


def short_report(result):
    """Bounded public text projected from the same read-only structured report."""
    def reasons(value):
        values = codes(value)
        return ', '.join(values[:5]) + (f' (+{len(values)-5} more)' if len(values)>5 else '')
    operation = result.get('operation', {})
    clocks = result.get('runtime_evidence', {})
    decision = next(iter(reversed(result.get('decisions', []))), {})
    accepted = (result.get('accepted_packet') or {}).get('sequence', 'unknown')
    collected = (result.get('latest_packet') or {}).get('sequence', 'unknown')
    run_id = result.get('run_id', 'unknown')
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}', run_id):
        run_id = 'unknown'
    lines = [f"PAPER {run_id}: {reasons(operation.get('state')) or 'UNKNOWN'}",
             'Reason: ' + (reasons(operation.get('reasons')) or 'not reported'),
             f"Data: heartbeat {reasons(clocks.get('heartbeat')) or 'UNKNOWN'}; feed {reasons(clocks.get('feed')) or 'UNKNOWN'}; accepted {accepted}, collected {collected}"]
    families = operation.get('family_input_issues', {})
    for family in ('DEGEN', 'SWING', 'SCOPE'):
        issues = list(families.get(family, []))
        if family == 'SCOPE':
            issues += codes([decision.get('scope_rejections'), decision.get('scope_admission_reasons')])
        if family == 'DEGEN':
            issues += codes([scan.get('issues') for scan in decision.get('scans', [])])
        if family in decision.get('unavailable_families', []):
            issues.append(family + '_INPUT_UNAVAILABLE')
        fallback = 'no input blocker reported' if result.get('accepted_packet') else 'input not established'
        if family == 'DEGEN':
            if not result.get('decision_count', len(result.get('decisions', []))):
                fallback = 'no decision recorded; scan not established'
            elif not decision.get('scans'):
                fallback = 'last decision did not record a scan'
            else:
                fallback = 'scan recorded; entry checks below'
        lines.append(family + ': ' + (reasons(issues) or fallback))
    lines.append('Last decision: ' + (reasons([decision.get('status'), decision.get('reason')]) or 'none recorded'))
    checks = codes([decision.get('issues'), decision.get('blocker'),
                    decision.get('rejections'), decision.get('contract_exclusions')])
    if checks:
        lines.append('Entry checks: ' + reasons(checks[:8]))
    for timing in decision.get('inventory_timing', [])[:4]:
        limit = timing['max_metadata_age_seconds']
        lines.append(f"Inventory {timing['symbol']}: source age {timing['source_age_seconds']:.3f}s; "
                     f"limit <{limit}s; receive lag {timing['receive_lag_seconds']:.3f}s; "
                     f"clock order {'valid' if timing['clock_order_valid'] else 'invalid'}"
                     if limit is not None else
                     f"Inventory {timing['symbol']}: retained clocks available; age limit unavailable")
    scans = decision.get('scans', [])
    if scans:
        setups = [s for scan in scans for s in scan.get('setups', [])]
        symbols = reasons([scan.get('symbol') for scan in scans])
        lines.append('Last scan: ' + symbols + '; ' + '; '.join(
            f'{status.lower()} {sum(status in s.get("status", []) for s in setups)}'
            for status in ('CONFIRMED', 'WATCHING', 'BLOCKED')))
        counts = {}
        for setup in setups:
            for reason in codes(setup.get('reasons')):
                counts[reason] = counts.get(reason, 0) + 1
        if counts:
            lines.append('Setup reasons (shown): ' + '; '.join(
                f'{reason} ({count})' for reason, count in
                sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:6]))
    decisions = result.get('decisions', [])
    if decisions:
        scanned = sum(bool(d.get('scans')) for d in decisions)
        lines.append(f'Decisions shown: {len(decisions)}; with scans {scanned}; without scans {len(decisions)-scanned}')
    total = result.get('account_total_fills')
    lines.append(f"Fills (account total): {total if total is not None else 'unknown'}; cycles (run): {result.get('cycle_count', 'unknown')}")
    execution = result.get('run_execution', {})
    if execution.get('status') == 'RECORDED':
        lines.append(f"Run execution: entry fills {execution['entry_fills']}; exit fills {execution['exit_fills']}; "
                     f"completed round trips {execution['completed_round_trips']}; "
                     f"prior-run plays fully exited {execution['carry_in_exits']}")
    elif execution:
        lines.append("Run execution: unavailable (" + (reasons(execution.get('reason')) or 'unknown') + ")")
    recovery = result.get('attempt_recovery')
    if recovery and (recovery['matched_in_run'] or recovery['unresolved_at_last_snapshot']):
        lines.append(f"Order recovery: matched {recovery['matched_in_run']}; "
                     f"unresolved at last reconciliation {recovery['unresolved_at_last_snapshot']}")
    outcomes = result.get('cycle_outcomes')
    if outcomes is not None:
        counts = {s: sum(r['count'] for r in outcomes if s in r['status'])
                  for s in ('COMPLETE', 'SKIPPED', 'WAITING_FOR_FEED', 'STARTED', 'INTERRUPTED')}
        lines.append('Cycles: ' + '; '.join(f'{s.lower()} {n}' for s,n in counts.items()))
        why = [f"{reasons(r['reason'])} ({r['count']})" for r in outcomes if reasons(r['reason'])]
        if why:
            lines.append('Cycle reasons: ' + '; '.join(why[:5]))
    lines.append(f"Feed recoveries: {result.get('flat_feed_recoveries', 'unknown')}; reviewed resumes: {result.get('reviewed_entry_resumes', 'unknown')}")
    collection = result.get('collection', [])
    lines.append('Collection: ' + '; '.join(f"{s.lower()} {sum(r['attempts'] for r in collection if r['status']==s)}"
                                           for s in ('DELIVERED', 'FAILED', 'INTERRUPTED')))
    if result.get('collector_failures'):
        last = result['collector_failures'][-1]
        phase = reasons((last.get('read_progress') or {}).get('stage')) or 'unavailable'
        lines.append(f"Last collection failure: {last.get('error_class', 'unknown')}; read phase {phase}")
        phases = {}
        for failure in result['collector_failures']:
            phase = reasons((failure.get('read_progress') or {}).get('stage')) or 'unavailable'
            phases[phase] = phases.get(phase, 0) + 1
        lines.append('Read failure phases (shown): ' + '; '.join(
            f'{phase} ({count})' for phase, count in sorted(phases.items())[:8]))
    paid = result.get('model_spending', {})
    if 'costs' in paid:
        values, limits = paid['costs'], paid['budgets']
        lines.append(f"AI settled: run ${values['run']['settled_cost']}; {paid['day']} NY ${values['day']['settled_cost']} / ${limits['daily_budget'] or '?'}; account ${values['account_total']['settled_cost']} / ${limits['total_budget'] or '?'}")
        lines.append(f"AI unsettled/invalid calls (account): {values['account_total']['unknown_calls']}")
    else:
        lines.append('AI spending: unavailable')
    if result.get('run_issues'):
        lines.append('Run issues: ' + reasons(result['run_issues']))
    lines.append('LIVE disabled. No trading-readiness claim; --format json retains the detailed evidence.')
    return '\n'.join(lines)


class RunFillWindow:
    """Group original fill receipts by their native portfolio entry and source clock."""

    def __init__(self, start, end):
        self.first = datetime.fromisoformat(start)
        self.last = datetime.fromisoformat(end)
        self.plays = {}
        self.fill_ids = set()
        self.sequences = set()
        self.entry_fills = 0
        self.exit_fills = 0

    def add(self, play, client, order_id, observation):
        side = observation.get('side')
        instrument = observation.get('instrument', {}).get('instrument_id')
        if (not all(isinstance(key, str) and key for key in (play, client, order_id, instrument))
                or observation.get('client_id') != client or observation.get('order_id') != order_id
                or side not in ('BUY', 'SELL') or (side == 'BUY') != (play == client)):
            raise ValueError('Invalid fill binding')
        total = Decimal(0)
        for fill in observation['fills']:
            if not isinstance(fill, dict):
                raise ValueError('Invalid fill')
            identity, sequence = fill.get('fill_id'), fill.get('sequence')
            at = datetime.fromisoformat(fill['occurred_at'])
            quantity = amount(str(fill.get('quantity')))
            if (not at.tzinfo or quantity is None or quantity <= 0 or type(sequence) is not int
                    or sequence <= 0 or not isinstance(identity, str) or not identity
                    or fill.get('order_id') != order_id or identity in self.fill_ids or sequence in self.sequences):
                raise ValueError('Invalid fill receipt')
            self.fill_ids.add(identity)
            self.sequences.add(sequence)
            total += quantity
            if at <= self.last:
                self.plays.setdefault(play, []).append((sequence, at, side, quantity, instrument))
            if self.first <= at <= self.last:
                if side == 'BUY':
                    self.entry_fills += 1
                else:
                    self.exit_fills += 1
        if total != amount(str(observation.get('filled_quantity'))):
            raise ValueError('Incomplete fill receipts')

    def summary(self):
        round_trips = carry_in_exits = 0
        for events in self.plays.values():
            events.sort()
            balance = Decimal(0)
            opened = previous = events[0][1]
            for index, (_, at, side, quantity, instrument) in enumerate(events):
                if at < previous or (index and balance == 0) or instrument != events[0][4]:
                    raise ValueError('Inconsistent play fills')
                balance += quantity if side == 'BUY' else -quantity
                if balance < 0:
                    raise ValueError('Missing entry fills')
                previous = at
            if balance == 0 and previous >= self.first:
                if opened >= self.first:
                    round_trips += 1
                else:
                    carry_in_exits += 1
        return {'status': 'RECORDED', 'entry_fills': self.entry_fills, 'exit_fills': self.exit_fills,
                'completed_round_trips': round_trips, 'carry_in_exits': carry_in_exits}


def fill_evidence(db, start=None, end=None):
    """Keep the account total independent of availability of per-run fill evidence."""
    columns = {r[1] for r in db.execute('PRAGMA table_info(execution_portfolio_orders)')}
    if not columns:
        count = db.execute('SELECT COUNT(*) FROM execution_fills').fetchone()[0]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_stock_fills'").fetchone():
            count += db.execute('SELECT COUNT(*) FROM execution_stock_fills').fetchone()[0]
        return count, 'LEGACY_FILL_TABLES', {'status': 'UNAVAILABLE', 'reason': 'LEGACY_FILL_TABLES'}

    detailed = start is not None and {'play_id', 'client_id', 'order_id'} <= columns
    bindings = 'play_id,client_id,order_id' if detailed else 'NULL,NULL,NULL'
    rows = db.execute(f'SELECT {bindings},CASE WHEN length(observation_json)<=2097152 THEN observation_json '
                      'END FROM execution_portfolio_orders WHERE observation_json IS NOT NULL')
    count = 0
    run = {'status': 'UNAVAILABLE', 'reason': 'RUN_FILL_BINDINGS_UNAVAILABLE'}
    window = RunFillWindow(start, end) if detailed else None
    with localcontext() as context:
        context.prec = 192
        for play, client, order_id, raw in rows:
            if raw is None:
                raise ValueError('FILL_EVIDENCE_TOO_LARGE')
            obs = json.loads(raw)
            if not isinstance(obs, dict) or not isinstance(obs.get('fills'), list):
                raise ValueError('FILL_EVIDENCE_UNAVAILABLE')
            count += len(obs['fills'])
            if window is not None:
                try:
                    window.add(play, client, order_id, obs)
                except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
                    run = {'status': 'UNAVAILABLE', 'reason': 'RUN_FILL_EVIDENCE_INVALID'}
                    window = None
        if window is not None:
            try:
                run = window.summary()
            except ValueError:
                run = {'status': 'UNAVAILABLE', 'reason': 'RUN_FILL_EVIDENCE_INVALID'}
    if run.get('reason') == 'RUN_FILL_EVIDENCE_INVALID':
        count = None
    return count, 'PORTFOLIO_ORDER_OBSERVATIONS', run


def fill_count(db):
    count, source, _ = fill_evidence(db)
    return count, source


def runtime_failures(db, start, end):
    if 'payload' not in {r[1] for r in db.execute('PRAGMA table_info(execution_events)')}:
        return []
    failures = []
    for row in db.execute(
        "SELECT occurred_at,CASE WHEN length(payload)<=65536 THEN payload END AS payload "
        "FROM execution_events WHERE kind='FIXTURE_READ_FAILED' AND occurred_at>=? "
        "AND occurred_at<=? ORDER BY occurred_at DESC LIMIT 10", (start, end)
    ):
        value = json.loads(row['payload']) if row['payload'] else {}
        item = {'occurred_at': row['occurred_at']}
        error = value.get('error_class')
        if isinstance(error, str) and re.fullmatch(r'[A-Z][A-Za-z0-9]{0,63}', error):
            item['error_class'] = error
        for key in ('timeout_seconds', 'elapsed_seconds'):
            number = value.get(key)
            if type(number) in (int, float) and 0 <= number <= 86400:
                item[key] = number
        failures.append(item)
    return failures


def failure_evidence(raw):
    """Retain safe native failure locations, never exception messages or locals."""
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {'codes': [], 'evidence_available': False, 'evidence_issue': 'INVALID_JSON'}
    if not isinstance(value, dict):
        return {'codes': [], 'evidence_available': False}
    result = {'codes': codes(value.get('stage')), 'evidence_available': raw is not None}
    error = value.get('error_class')
    if isinstance(error, str) and error in {
        'ValueError', 'TypeError', 'KeyError', 'RuntimeError', 'TimeoutError',
        'OSError', 'PermissionError', 'FileNotFoundError', 'MemoryError',
        'FixtureProcessTimeout', 'FixtureProcessFailed', 'FixtureProcessProtocolError',
        'OperationalError', 'DatabaseError', 'IntegrityError', 'ProgrammingError',
        'CancelledError', 'ExecutionBlocked', 'OTHER_ERROR',
    }:
        result['error_class'] = error
    result['frames'] = []
    progress = value.get('read_progress')
    if (isinstance(progress, dict) and progress.get('stage') in {
            'PRIVATE_AUTH', 'CONNECT', 'DISCOVER', 'VALIDATE_PLAN', 'MARKET_READ', 'CLOSE', 'SERIALIZE'}
            and type(progress.get('completed_reads')) is int and 0 <= progress['completed_reads'] <= 8):
        result['read_progress'] = {k: progress[k] for k in ('stage', 'completed_reads')}
    frames = value.get('frames')
    for frame in frames[-8:] if isinstance(frames, list) else []:
        if not isinstance(frame, dict):
            continue
        path, line = frame.get('file'), frame.get('line')
        if (isinstance(path, str) and len(path) <= 240
                and re.fullmatch(r'app/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py', path)
                and type(line) is int and 0 < line <= 1000000):
            result['frames'].append({'file': path, 'line': line})
    return result


def attempt_recovery_counts(db, start, end):
    snapshot = db.execute(
        "SELECT CASE WHEN length(payload)<=65536 AND json_valid(payload) "
        "THEN json_extract(payload,'$.attempt_recovery.unresolved') END "
        "FROM execution_events WHERE kind='PORTFOLIO_RECONCILED' AND occurred_at>=? AND occurred_at<=? "
        "ORDER BY occurred_at DESC,rowid DESC LIMIT 1", (start, end)).fetchone()
    if snapshot and type(snapshot[0]) is int and snapshot[0] >= 0:
        matched = db.execute(
            "SELECT COUNT(*) FROM execution_events WHERE kind='PORTFOLIO_ATTEMPT_RECOVERED' "
            "AND occurred_at>=? AND occurred_at<=?", (start, end)).fetchone()[0]
        return {'matched_in_run': matched, 'unresolved_at_last_snapshot': snapshot[0]}
    return None


def owner_diagnostics(db, start, end):
    result = {'first_decisions': [], 'decision_reason_counts': [], 'halt_history': []}
    for row in db.execute(
        "SELECT cycle_key,started_at,status FROM execution_option_opportunities "
        "WHERE started_at>=? AND started_at<=? ORDER BY started_at,cycle_key LIMIT 3", (start, end)
    ):
        result['first_decisions'].append({'cycle_key': row['cycle_key'], 'started_at': row['started_at'],
                                         'stored_status': row['status'],
                                         **decision_evidence(db, row['cycle_key'])})
    for row in db.execute(
        "SELECT CASE WHEN length(result_json)<=? AND json_valid(result_json) THEN "
        "CASE WHEN json_type(result_json,'$.reason')='text' "
        "AND length(json_extract(result_json,'$.reason'))<=128 "
        "THEN json_extract(result_json,'$.reason') END END AS reason,"
        "COUNT(*) AS decisions,MIN(started_at) AS first_at,MAX(started_at) AS last_at "
        "FROM execution_option_opportunities WHERE started_at>=? AND started_at<=? "
        "GROUP BY reason ORDER BY first_at LIMIT 25", (MAX_DECISION_BYTES, start, end)
    ):
        result['decision_reason_counts'].append({**dict(row), 'reason': codes(row['reason'])})
    if 'payload' in {r[1] for r in db.execute('PRAGMA table_info(execution_events)')}:
        recovery = attempt_recovery_counts(db, start, end)
        if recovery is not None:
            result['attempt_recovery'] = recovery
        result['flat_feed_recoveries'] = db.execute(
            "SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_REVIEWED_RESUME' "
            "AND occurred_at>=? AND occurred_at<=? AND CASE WHEN length(payload)<=65536 "
            "AND json_valid(payload) THEN json_extract(payload,'$.reason') END="
            "'CONNECTED_FLAT_FEED_RECOVERY'", (start, end)).fetchone()[0]
        for row in db.execute(
            "SELECT occurred_at,CASE WHEN length(payload)<=65536 AND json_valid(payload) "
            "THEN json_extract(payload,'$.reason') END AS reason FROM execution_events "
            "WHERE kind='MANUAL_HALT' AND occurred_at>=? AND occurred_at<=? "
            "ORDER BY occurred_at LIMIT 20", (start, end)
        ):
            result['halt_history'].append({'occurred_at': row['occurred_at'], 'reason': codes(row['reason'])})
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_model_calls'").fetchone():
        result['model_calls'] = {}
        for name, where, args in (('run', 'WHERE started_at>=? AND started_at<=?', (start, end)),
                                  ('account_total', '', ())):
            row = db.execute("SELECT COUNT(*) AS attempts,COALESCE(SUM(cost IS NULL),0) AS unsettled "
                             "FROM execution_model_calls " + where, args).fetchone()
            result['model_calls'][name] = dict(row)
    return result


def source_capture(db, sequence):
    """Project saved worker diagnostics only, including captures from older releases."""
    if 'raw_json' not in {r[1] for r in db.execute('PRAGMA table_info(attempts)')}:
        return {'evidence_available': False}
    row = db.execute(
        "SELECT CASE WHEN length(raw_json)<=1048576 AND json_valid(raw_json) THEN "
        "json_object('status',json_extract(raw_json,'$.status'),"
        "'failure',json_extract(raw_json,'$.failure'),"
        "'schemas_present',json_type(raw_json,'$.schemas')='object') END "
        "FROM attempts WHERE sequence=?", (sequence,)).fetchone()
    if row is None or row[0] is None or len(row[0]) > 65536:
        return {'evidence_available': False}
    value = json.loads(row[0])
    result = {'evidence_available': True, 'status': codes(value.get('status')),
              'schemas_present': bool(value.get('schemas_present'))}
    failure = value.get('failure')
    if not isinstance(failure, dict):
        return result
    stage = failure.get('stage')
    if isinstance(stage, str) and stage in {
        'PRIVATE_AUTH', 'CONNECT', 'DISCOVER', 'VALIDATE_PLAN', 'MARKET_READ', 'CLOSE', 'PARENT'}:
        result['stage'] = stage
    result['causes'] = []
    for cause in failure.get('causes', [])[:16] if isinstance(failure.get('causes'), list) else []:
        if not isinstance(cause, dict):
            continue
        error = cause.get('error_class')
        known = {'ReadAuthorizationRequired', 'HTTPStatusError', 'ExceptionGroup', 'BaseExceptionGroup',
                 'OAuthFlowError', 'OAuthTokenError', 'OAuthRegistrationError',
                 'InvalidScopeError', 'InvalidRedirectUriError',
                 'ValueError', 'TypeError', 'KeyError', 'RuntimeError', 'TimeoutError', 'OSError',
                 'PermissionError', 'FileNotFoundError', 'ValidationError', 'McpError',
                 'ConnectError', 'ReadError', 'WriteError', 'ConnectTimeout', 'ReadTimeout',
                 'WriteTimeout', 'PoolTimeout', 'RemoteProtocolError', 'LocalProtocolError',
                 'EndOfStream', 'BrokenResourceError', 'ClosedResourceError', 'CancelledError'}
        item = {'error_class': error if isinstance(error, str) and error in known else 'OTHER_ERROR'}
        status, oauth = cause.get('http_status'), cause.get('oauth_error')
        if type(status) is int and 100 <= status <= 599:
            item['http_status'] = status
        if isinstance(oauth, str) and oauth in {
            'invalid_request', 'invalid_client', 'invalid_grant', 'unauthorized_client',
            'unsupported_grant_type', 'invalid_scope', 'access_denied', 'server_error',
            'temporarily_unavailable'}:
            item['oauth_error'] = oauth
        result['causes'].append(item)
    result['truncated'] = failure.get('truncated') is True
    return result


def runtime_evidence(db, now):
    """Current stored clocks and their enrolled bounds; never refresh a heartbeat."""
    columns = {r[1] for r in db.execute('PRAGMA table_info(execution_option_runtime)')}
    if not {'heartbeat_at', 'feed_recorded_at', 'config_json'} <= columns:
        return {'heartbeat': 'UNKNOWN', 'feed': 'UNKNOWN'}
    row = db.execute("SELECT heartbeat_at,feed_recorded_at,CASE WHEN length(config_json)<=262144 "
                     "THEN config_json END AS config FROM execution_option_runtime WHERE id=1").fetchone()
    if row is None or row['config'] is None:
        return {'heartbeat': 'UNKNOWN', 'feed': 'UNKNOWN'}
    policy = json.loads(row['config'])['runtime']
    result = {}
    for key, field, limit in (('heartbeat', 'heartbeat_at', 'heartbeat_max_age_seconds'),
                              ('feed', 'feed_recorded_at', 'feed_max_age_seconds')):
        stamp, bound = row[field], policy[limit]
        if type(bound) not in (int, float) or not 0 < bound <= 86400:
            raise ValueError('INVALID_RUNTIME_FRESHNESS_BOUND')
        age = (now - datetime.fromisoformat(stamp)).total_seconds() if stamp else None
        result.update({key: 'MISSING' if age is None else 'FUTURE' if age < 0 else
                       'FRESH' if age < bound else 'STALE', key + '_at': stamp,
                       key + '_age_seconds': age, key + '_max_age_seconds': bound})
    return result


def operation(result, state):
    """Separate container lifetime, current input health and last setup decision.

    Family gaps are additive: missing Scope/Swing never turns an evaluated DEGEN
    no-setup result into a global failure. No state here grants entry authority.
    """
    runtime = next(iter(result.get('current_runtime', [])), {})
    control = next(iter(result.get('current_control', [])), {})
    clocks = result.get('runtime_evidence', {})
    packet = result.get('accepted_packet') or {}
    decision = next(iter(reversed(result.get('decisions', []))), {})
    issues = packet.get('coverage_issues', [])
    families = {name: sorted(c for c in issues if c.startswith(prefixes))
                for name, prefixes in (('SCOPE', ('SCOPE_', 'SPX_')), ('SWING', ('SWING_',)))}
    reasons = codes([decision.get('reason'), decision.get('issues'), decision.get('blocker'),
                     decision.get('rejections'), decision.get('contract_exclusions')])
    last_failure = next(iter(reversed(result.get('collector_failures', []))), {})
    auth_blocked = (authorization_required(last_failure)
                    and last_failure.get('sequence', 0) > (result.get('latest_packet') or {}).get('sequence', 0))
    if state['Status'] == 'exited':
        status = 'STOPPED' if state.get('ExitCode') == 0 else 'FAILED'
        why = ['BOUNDED_SESSION_ENDED' if status == 'STOPPED' else 'CONTAINER_EXIT_NONZERO']
    elif runtime.get('status') == 'FAILED':
        status, why = 'FAILED', codes(runtime.get('reason'))
    elif clocks.get('heartbeat') != 'FRESH':
        status, why = 'MISSING_INPUTS', ['RUNTIME_HEARTBEAT_' + clocks.get('heartbeat', 'UNKNOWN')]
    elif runtime.get('status') in {'STOPPED', 'STOPPING'}:
        status, why = 'STOPPED', codes(runtime.get('reason'))
    elif auth_blocked:
        status, why = 'MISSING_INPUTS', ['READ_AUTHORIZATION_REQUIRED']
    elif control.get('halted'):
        status, why = 'MISSING_INPUTS', codes(control.get('halt_reason')) or ['ENTRIES_HALTED']
    elif clocks.get('feed') != 'FRESH':
        status, why = 'MISSING_INPUTS', ['RUNTIME_FEED_' + clocks.get('feed', 'UNKNOWN')]
    elif runtime.get('status') == 'BLOCKED':
        status, why = 'MISSING_INPUTS', codes(runtime.get('reason'))
    elif any(not c.startswith(('SCOPE_', 'SPX_', 'SWING_')) for c in issues):
        status, why = 'MISSING_INPUTS', issues
    elif not packet:
        status, why = 'MISSING_INPUTS', ['ACCEPTED_INPUT_NOT_RECORDED']
    elif decision.get('entry_timely') is False:
        status, why = 'MISSING_INPUTS', ['ENTRY_RESPONSE_EXPIRED']
    elif 'ENTRY_HEALTH_BLOCKED' in decision.get('reason', []):
        status, why = 'MISSING_INPUTS', ['ENTRY_HEALTH_BLOCKED']
    elif any(r.startswith('SCOPE_PAID_REFRESH_') or r == 'SCOPE_FRESH_EVIDENCE_TIMEOUT'
             for r in decision.get('reason', [])):
        status, why = 'MISSING_INPUTS', decision['reason']
    elif decision.get('status') == ['HOLD'] and any(
            r.startswith('SCOPE_REFRESH_') for r in decision.get('scope_rejections', [])):
        status, why = 'MISSING_INPUTS', decision['scope_rejections']
    elif 'SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED' in decision.get('scope_admission_reasons', []):
        status, why = 'MISSING_INPUTS', decision['scope_admission_reasons']
    elif decision.get('evidence_available') and decision.get('status') == ['HOLD']:
        # A completed HOLD with missing history/quotes is not a no-setup claim.
        missing = decision_input_issues(decision)
        status, why = (('MISSING_INPUTS', missing) if missing else
                       ('WAITING_FOR_SETUP', reasons) if decision.get('scans') else
                       ('RUNNING', ['SCAN_NOT_RECORDED']))
    else:
        status, why = 'RUNNING', ['AWAITING_FIRST_SCAN'] if not decision else reasons
    return {'state': status, 'reasons': why, 'family_input_issues': families,
            'last_decision_at': decision.get('started_at'),
            'last_decision_reasons': reasons, 'container_running': state['Status'] == 'running',
            'trading_ready': False}


def authorization_required(failure):
    return any(c.get('error_class') == 'ReadAuthorizationRequired'
               for c in failure.get('source_capture', {}).get('causes', []))


def report(directory, started, finished):
    start = datetime.fromisoformat(started).astimezone(timezone.utc).isoformat()
    end = datetime.fromisoformat(finished).astimezone(timezone.utc).isoformat()
    if end < start:
        raise ValueError("INVALID_SESSION_WINDOW")
    result = {"window_start": start, "window_end": end, "live_enabled": False,
              "provider_calls": False, "state_modified": False}
    db = connection(directory / "owner/options.db")
    try:
        result["cycles"] = [dict(r) for r in db.execute(
            "SELECT slot,status,reason,started_at,completed_at FROM execution_option_runtime_slots "
            "WHERE started_at>=? AND started_at<=? ORDER BY slot DESC LIMIT 25", (start, end))]
        result["decisions"] = []
        for row in db.execute(
            "SELECT cycle_key,started_at,status FROM execution_option_opportunities "
            "WHERE started_at>=? AND started_at<=? ORDER BY started_at DESC LIMIT 5", (start, end)
        ):
            result["decisions"].append({"cycle_key": row["cycle_key"],
                "started_at": row["started_at"], "stored_status": row["status"],
                **decision_evidence(db, row["cycle_key"])})
        result['cycle_count'] = db.execute(
            'SELECT COUNT(*) FROM execution_option_runtime_slots WHERE started_at>=? AND started_at<=?',
            (start, end)).fetchone()[0]
        result['cycle_outcomes'] = [{'status': codes(r['status']), 'reason': codes(r['reason']),
                                     'count': r['count']} for r in db.execute(
            'SELECT status,reason,COUNT(*) AS count FROM execution_option_runtime_slots '
            'WHERE started_at>=? AND started_at<=? GROUP BY status,reason ORDER BY status,reason LIMIT 25',
            (start, end))]
        result['decision_count'] = db.execute(
            'SELECT COUNT(*) FROM execution_option_opportunities WHERE started_at>=? AND started_at<=?',
            (start, end)).fetchone()[0]
        result['cycles_omitted'] = max(0, result['cycle_count'] - len(result['cycles']))
        result['decisions_omitted'] = max(0, result['decision_count'] - len(result['decisions']))
        result["cycles"].reverse()
        result["decisions"].reverse()
        result["runtime_evidence"] = runtime_evidence(db, datetime.fromisoformat(end))
        result["reviewed_entry_resumes"] = db.execute(
            "SELECT COUNT(*) FROM execution_events WHERE kind='OPTION_REVIEWED_RESUME' "
            "AND occurred_at>=? AND occurred_at<=?", (start, end)).fetchone()[0]
        result["current_runtime"] = [dict(r) for r in db.execute(
            "SELECT status,reason,feed_sequence FROM execution_option_runtime WHERE id=1")]
        result['accepted_packet'] = None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_mixed_runtime_inputs'").fetchone():
            accepted = db.execute(
                "SELECT sequence,accepted_at,json_extract(packet_json,'$.kind') AS kind,"
                "CASE WHEN length(json_extract(packet_json,'$.coverage_issues'))<=65536 "
                "THEN json_extract(packet_json,'$.coverage_issues') END AS issues "
                "FROM execution_mixed_runtime_inputs WHERE status='DELIVERED' AND sequence="
                "(SELECT feed_sequence FROM execution_option_runtime WHERE id=1) "
                "AND accepted_at>=? AND accepted_at<=? AND json_valid(packet_json)", (start, end)).fetchone()
            if accepted:
                result['accepted_packet'] = {'sequence': accepted['sequence'], 'accepted_at': accepted['accepted_at'],
                    'kind': codes(accepted['kind']), 'coverage_issues': codes(json.loads(accepted['issues'] or '[]'))}
        result["current_control"] = [dict(r) for r in db.execute(
            "SELECT halted,halt_reason FROM execution_control WHERE id=1")]
        (result["account_total_fills"], result["fill_count_source"],
         result["run_execution"]) = fill_evidence(db, start, end)
        result['model_spending'] = spending(db, start, end)
        result["runtime_failures"] = runtime_failures(db, start, end)
        result.update(owner_diagnostics(db, start, end))
    finally:
        db.close()
    db = connection(directory / "collector/collector.db")
    try:
        result["collection"] = [dict(r) for r in db.execute(
            "SELECT status,COUNT(*) AS attempts,MIN(sequence) AS first_sequence,"
            "MAX(sequence) AS last_sequence FROM attempts WHERE started_at>=? "
            "AND started_at<=? GROUP BY status", (start, end))]
        if 'packet_json' in {r[1] for r in db.execute('PRAGMA table_info(attempts)')}:
            latest = db.execute(
                "SELECT sequence,started_at,status,json_extract(packet_json,'$.kind') AS kind,"
                "CASE WHEN length(json_extract(packet_json,'$.coverage_issues'))<=65536 "
                "THEN json_extract(packet_json,'$.coverage_issues') END AS issues "
                "FROM attempts WHERE started_at>=? AND started_at<=? AND status='DELIVERED' "
                "AND json_valid(packet_json) ORDER BY sequence DESC LIMIT 1", (start, end)).fetchone()
            result['latest_packet'] = ({'sequence': latest['sequence'], 'started_at': latest['started_at'],
                'kind': codes(latest['kind']), 'coverage_issues': codes(json.loads(latest['issues'] or '[]'))}
                if latest else None)
            result['packet_summary'] = [{
                'kind': codes(row['kind']), 'coverage_issues': codes(json.loads(row['issues'] or '[]')),
                'packets': row['packets'], 'first_sequence': row['first_sequence'],
                'last_sequence': row['last_sequence'],
            } for row in db.execute(
                "SELECT json_extract(packet_json,'$.kind') AS kind,"
                "CASE WHEN length(json_extract(packet_json,'$.coverage_issues'))<=65536 "
                "THEN json_extract(packet_json,'$.coverage_issues') END AS issues,"
                "COUNT(*) AS packets,MIN(sequence) AS first_sequence,MAX(sequence) AS last_sequence "
                "FROM attempts WHERE started_at>=? AND started_at<=? AND packet_json IS NOT NULL "
                "AND json_valid(packet_json) GROUP BY kind,issues ORDER BY first_sequence LIMIT 25", (start, end))]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='attempt_failures'").fetchone():
            result['collector_failures'] = [{
                'sequence': row['sequence'], 'started_at': row['started_at'],
                **failure_evidence(row['details']),
                'source_capture': source_capture(db, row['sequence']),
            } for row in db.execute(
                'SELECT f.sequence,a.started_at,CASE WHEN length(f.details_json)<=65536 THEN f.details_json END AS details '
                'FROM attempt_failures f JOIN attempts a USING(sequence) '
                'WHERE a.started_at>=? AND a.started_at<=? AND f.sequence IN ('
                'SELECT f.sequence FROM attempt_failures f JOIN attempts a USING(sequence) '
                'WHERE a.started_at>=? AND a.started_at<=? ORDER BY f.sequence ASC LIMIT 3) '
                'UNION SELECT f.sequence,a.started_at,CASE WHEN length(f.details_json)<=65536 '
                'THEN f.details_json END FROM attempt_failures f JOIN attempts a USING(sequence) '
                'WHERE a.started_at>=? AND a.started_at<=? AND f.sequence IN ('
                'SELECT f.sequence FROM attempt_failures f JOIN attempts a USING(sequence) '
                'WHERE a.started_at>=? AND a.started_at<=? ORDER BY f.sequence DESC LIMIT 10) '
                'ORDER BY sequence', (start, end, start, end, start, end, start, end))]
    finally:
        db.close()
    concerns = []
    if result['run_execution'].get('reason') == 'RUN_FILL_EVIDENCE_INVALID':
        concerns.append('RUN_FILL_EVIDENCE_INVALID')
    if result['decision_count'] == 0:
        concerns.append('NO_DECISION_RECORDED')
    if result.get('runtime_evidence', {}).get('feed') in {'MISSING', 'STALE', 'FUTURE'}:
        concerns.append('FEED_' + result['runtime_evidence']['feed'])
    if any(row['status'] == 'FAILED' and row['attempts'] for row in result['collection']):
        concerns.append('COLLECTOR_FAILURES_RECORDED')
    if any(authorization_required(f) for f in result.get('collector_failures', [])):
        concerns.append('READ_AUTHORIZATION_REQUIRED_RECORDED')
    if result['runtime_failures']:
        concerns.append('RUNTIME_READ_FAILURES_RECORDED')
    if any('ENTRY_HEALTH_BLOCKED' in row['reason'] for row in result['decision_reason_counts']):
        concerns.append('ENTRY_HEALTH_BLOCKED')
    result['run_issues'] = concerns
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument('--format', choices=('json', 'text'), default='json')
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.run_id):
        raise ValueError("INVALID_RUN_ID")
    fmt = '{"state":{{json .State}},"label":{{json (index .Config.Labels "trade-bot.connected-session-v1")}}}'
    inspected = subprocess.run(
        ["docker", "inspect", "--format", fmt, "trade-bot-connected-" + args.run_id],
        capture_output=True, text=True, timeout=10,
    )
    if inspected.returncode or len(inspected.stdout) > 16384:
        raise ValueError("SESSION_INSPECTION_FAILED")
    container = json.loads(inspected.stdout)
    if not container.get("label"):
        raise ValueError("NOT_A_CONNECTED_SESSION")
    state = container["state"]
    if state['Status'] not in {'running', 'exited'}:
        raise ValueError('SESSION_NOT_RUNNING_OR_FINISHED')
    active = state['Status'] == 'running'
    end = datetime.now(timezone.utc).isoformat() if active else state['FinishedAt']
    result = report(STATE, state['StartedAt'], end)
    result.update(run_id=args.run_id, container_exit_code=None if active else state['ExitCode'],
                  status='CURRENT_SESSION_REPORT' if active else 'SAVED_SESSION_REPORT',
                  operation=operation(result, state))
    print(short_report(result) if args.format == 'text' else json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError,
            sqlite3.Error, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if type(exc) is ValueError and CODE.fullmatch(str(exc)) else type(exc).__name__
        print(json.dumps({"status": "UNAVAILABLE", "reason": reason,
                          "state_modified": False, "provider_calls": False}))
        raise SystemExit(2)
