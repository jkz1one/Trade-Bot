#!/usr/bin/env python3
"""Read running or stopped PAPER status without a build, run or provider call."""

import argparse
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
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
        scan = {name: field(prefix + '.' + name) for name in ('symbol', 'issues')}
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
    return {'evidence_available': True, 'evidence_bytes': size,
            'omitted_summary_fields': omitted, **summary}


def connection(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def fill_count(db):
    """Count the owner's actual receipt store, without mixing legacy projections."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'execution_portfolio_orders' in tables:
        count = 0
        for row in db.execute(
            'SELECT CASE WHEN length(observation_json)<=2097152 THEN observation_json '
            'ELSE NULL END FROM execution_portfolio_orders WHERE observation_json IS NOT NULL'
        ):
            if row[0] is None:
                raise ValueError('FILL_EVIDENCE_TOO_LARGE')
            observation = json.loads(row[0])
            fills = observation.get('fills') if isinstance(observation, dict) else None
            if not isinstance(fills, list):
                raise ValueError('FILL_EVIDENCE_UNAVAILABLE')
            count += len(fills)
        return count, 'PORTFOLIO_ORDER_OBSERVATIONS'
    count = db.execute('SELECT COUNT(*) FROM execution_fills').fetchone()[0]
    if 'execution_stock_fills' in tables:
        count += db.execute('SELECT COUNT(*) FROM execution_stock_fills').fetchone()[0]
    return count, 'LEGACY_FILL_TABLES'


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
    elif 'SCOPE_WATCH_NEW_SOURCE_OBSERVATIONS_REQUIRED' in decision.get('scope_admission_reasons', []):
        status, why = 'MISSING_INPUTS', decision['scope_admission_reasons']
    elif decision.get('evidence_available') and decision.get('status') == ['HOLD']:
        # A completed HOLD with missing history/quotes is not a no-setup claim.
        missing = codes([decision.get('issues'), decision.get('blocker'),
                         [scan.get('issues') for scan in decision.get('scans', [])]])
        setup_reasons = codes([setup.get('reasons') for scan in decision.get('scans', [])
                              for setup in scan.get('setups', [])])
        missing = sorted(set(missing + [r for r in setup_reasons if r in {
            'COMPLETED_STRUCTURE_INSUFFICIENT', 'HISTORY_UNAVAILABLE_DELAYED_OR_STALE'}]))
        status, why = ('MISSING_INPUTS', missing) if missing else ('WAITING_FOR_SETUP', reasons)
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
        result["account_total_fills"], result["fill_count_source"] = fill_count(db)
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
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError,
            sqlite3.Error, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if type(exc) is ValueError and CODE.fullmatch(str(exc)) else type(exc).__name__
        print(json.dumps({"status": "UNAVAILABLE", "reason": reason,
                          "state_modified": False, "provider_calls": False}))
        raise SystemExit(2)
