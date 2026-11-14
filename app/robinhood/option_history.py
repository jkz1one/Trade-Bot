"""Read and replay exact Robinhood option account records outside the PAPER worker."""

import asyncio
import hashlib
from pathlib import Path
from uuid import UUID

from jsonschema.exceptions import ValidationError as SchemaError

from app.domain.models import utc_now
from app.execution.order_recovery import (
    Attempt,
    Execution,
    History,
    HistoryOrder,
    RecoveryCase,
    recover,
)
from app.options.models import _decimal
from app.options.read_gateway import ENDPOINT, _validator, encoded
from app.options.read_mapping import instant
from app.robinhood.gateway import _normalize_tool_metadata

ORDERS = "get_option_orders"
POSITIONS = "get_option_positions"
VERSION = "robinhood-option-account-reads-v1"
PINS = {
    ORDERS: "03aa0fbfb7948c286af598fdec621d74bcb5ac30613392cd22c66c76259294ad",
    POSITIONS: "e52014a283365878d46b82e00ee3da585a9d7e832d36aec7338512370fe096ea",
}
MAX_PAGES = 8
MAX_PAGE_BYTES = 256 * 1024
READ_ISSUES = frozenset(
    {
        "ORDER_ACCOUNT_SCHEMA_UNREVIEWED",
        "ACCOUNT_PAGE_UNAVAILABLE",
        "ACCOUNT_PAGE_SCHEMA_MISMATCH",
        "ACCOUNT_ROWS_INCOMPLETE",
        "BROKER_ORDER_ID_MISMATCH",
        "POSITION_SUBJECT_CONFLICT",
        "ACCOUNT_CURSOR_UNVERIFIED",
        "ACCOUNT_PAGE_LIMIT",
        "ACCOUNT_READ_FAILED",
        "ACCOUNT_READ_TIMED_OUT",
        "ACCOUNT_CONNECTION_UNAVAILABLE",
        "READ_AUTHORIZATION_REQUIRED",
    }
)


class HistoryIssue(ValueError):
    """Bounded public diagnostic with no account or provider text."""


def _shape(schema):
    """Remove documentation at schema nodes, preserving property names and constraints."""
    return {
        k: (
            {name: _shape(child) for name, child in v.items()}
            if k == "properties"
            else _shape(v)
            if k == "items"
            else v
        )
        for k, v in schema.items()
        if k != "description"
    }


def checked_schema(tool, metadata):
    m = _normalize_tool_metadata(metadata)
    hints = m.get("annotations") or {}
    if (
        tool not in PINS
        or m.get("name") != tool
        or hints.get("readOnlyHint") is not True
        or hints.get("destructiveHint") is True
        or len(encoded(m)) > 128 * 1024
    ):
        raise HistoryIssue("ORDER_ACCOUNT_SCHEMA_UNREVIEWED")
    try:
        shape = {
            "name": tool,
            "annotations": {"readOnlyHint": True},
            **{k: _shape(m[k]) for k in ("inputSchema", "outputSchema")},
        }
    except (KeyError, AttributeError, TypeError, RecursionError):
        raise HistoryIssue("ORDER_ACCOUNT_SCHEMA_UNREVIEWED") from None
    if hashlib.sha256(encoded(shape)).hexdigest() != PINS[tool]:
        raise HistoryIssue("ORDER_ACCOUNT_SCHEMA_UNREVIEWED")
    return shape


def query(attempt, tool):
    if attempt.order_id is None:
        raise HistoryIssue("BROKER_ORDER_ID_REQUIRED")
    try:
        if any(str(UUID(v)) != v for v in (attempt.order_id, attempt.instrument_id)):
            raise ValueError
    except ValueError:
        raise HistoryIssue("BROKER_UUID_REQUIRED") from None
    if tool == ORDERS:
        return {"account_number": attempt.account_id, "order_id": attempt.order_id}
    if tool == POSITIONS:
        return {
            "account_number": attempt.account_id,
            "option_ids": attempt.instrument_id,
            "nonzero": True,
        }
    raise HistoryIssue("UNEXPECTED_ACCOUNT_READ")


def page_data(shape, response):
    if (
        not isinstance(response, dict)
        or response.get("isError", False) is not False
        or len(encoded(response)) > MAX_PAGE_BYTES
    ):
        raise HistoryIssue("ACCOUNT_PAGE_UNAVAILABLE")
    payload = response.get("structuredContent")
    try:
        _validator(shape["outputSchema"]).validate(payload)
    except SchemaError:
        raise HistoryIssue("ACCOUNT_PAGE_SCHEMA_MISMATCH") from None
    data = payload["data"]
    field = "orders" if shape["name"] == ORDERS else "positions"
    if not isinstance(data[field], list) or any(row is None for row in data[field]):
        raise HistoryIssue("ACCOUNT_ROWS_INCOMPLETE")
    return data


def check_subjects(tool, data, attempt):
    if tool == ORDERS:
        if len(data["orders"]) > 1 or any(r["id"] != attempt.order_id for r in data["orders"]):
            raise HistoryIssue("BROKER_ORDER_ID_MISMATCH")
    elif any(r["option_id"] != attempt.instrument_id for r in data["positions"]):
        raise HistoryIssue("POSITION_SUBJECT_CONFLICT")


def next_cursor(tool, data, seen):
    cursor = data.get("next")
    # Single-order mode promises at most one row. For an empty result or
    # a positions listing require explicit end-of-pagination to certify absence.
    if cursor is None and tool == ORDERS and len(data["orders"]) == 1:
        return ""
    if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in seen:
        raise HistoryIssue("ACCOUNT_CURSOR_UNVERIFIED")
    if cursor:
        seen.add(cursor)
    return cursor


def attempt_digest(attempt):
    return hashlib.sha256(encoded(attempt.model_dump(mode="json"))).hexdigest()


def empty_capture(attempt, with_position):
    query(attempt, ORDERS)
    names = (ORDERS, POSITIONS) if with_position else (ORDERS,)
    return {
        "version": VERSION,
        "endpoint": ENDPOINT,
        "attempt_sha256": attempt_digest(attempt),
        "streams": {name: {"metadata": None, "pages": [], "complete": False} for name in names},
    }


async def capture(client, attempt, *, with_position=False, clock=utc_now):
    bundle = empty_capture(attempt, with_position)
    await _collect_into(client, attempt, bundle, clock)
    return bundle


async def _collect_into(client, attempt, bundle, clock):
    """Discovery and only the two fixed account reads can reach the client."""
    inventory = await client.list_tools()
    for tool, stream in bundle["streams"].items():
        try:
            matches = [m for m in inventory if m.get("name") == tool]
            if len(matches) != 1:
                raise HistoryIssue("ORDER_ACCOUNT_SCHEMA_UNREVIEWED")
            metadata = _normalize_tool_metadata(matches[0])
            shape = checked_schema(tool, metadata)
            stream["metadata"] = metadata
            args = query(attempt, tool)
            seen = set()
            for _ in range(MAX_PAGES):
                _validator(shape["inputSchema"]).validate(args)
                requested = instant(clock())
                response = await client.call_tool(tool, args.copy())
                received = instant(clock())
                data = page_data(shape, response)
                check_subjects(tool, data, attempt)
                stream["pages"].append(
                    {
                        "arguments": args.copy(),
                        "requested_at": requested.isoformat(),
                        "received_at": received.isoformat(),
                        "response": response,
                    }
                )
                cursor = next_cursor(tool, data, seen)
                if not cursor:
                    stream["complete"] = True
                    break
                args["cursor"] = cursor
            else:
                raise HistoryIssue("ACCOUNT_PAGE_LIMIT")
        except HistoryIssue as exc:
            stream["issue"] = str(exc)
        except Exception:  # noqa: BLE001 - SDK errors may contain private account data.
            stream["issue"] = "ACCOUNT_READ_FAILED"
        finally:
            stream["observed_at"] = instant(clock()).isoformat()


def read_pages(stream, attempt, tool):
    if stream.get("complete") is not True or "issue" in stream:
        reason = stream.get("issue")
        raise HistoryIssue(
            reason
            if isinstance(reason, str) and reason in READ_ISSUES
            else "ACCOUNT_READ_INCOMPLETE"
        )
    shape = checked_schema(tool, stream["metadata"])
    args = query(attempt, tool)
    pages = stream["pages"]
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise HistoryIssue("ACCOUNT_PAGE_LIMIT")
    rows, seen, previous = [], set(), attempt.attempted_at
    row_received_at = None
    for index, page in enumerate(pages):
        start, end = instant(page["requested_at"]), instant(page["received_at"])
        if page["arguments"] != args or not previous <= start <= end:
            raise HistoryIssue("ACCOUNT_PAGE_BINDING_CHANGED")
        data = page_data(shape, page["response"])
        check_subjects(tool, data, attempt)
        if tool == ORDERS:
            rows.extend(map_order(row, attempt, end) for row in data["orders"])
        else:
            if data["positions"]:
                row_received_at = end
            rows.extend(data["positions"])
        cursor = next_cursor(tool, data, seen)
        if bool(cursor) != (index < len(pages) - 1):
            raise HistoryIssue("ACCOUNT_PAGE_CHAIN_INCOMPLETE")
        args = {**args, "cursor": cursor}
        previous = end
    if previous > instant(stream["observed_at"]):
        raise HistoryIssue("ACCOUNT_PAGE_BINDING_CHANGED")
    return rows, row_received_at or previous


def whole(raw):
    number = _decimal(raw)
    if not 0 <= number <= 1_000_000 or number != number.to_integral_value():
        raise HistoryIssue("NON_WHOLE_CONTRACT_QUANTITY")
    return int(number)


def map_order(row, attempt, as_of):
    if row["id"] != attempt.order_id:
        raise HistoryIssue("BROKER_ORDER_ID_MISMATCH")
    if (
        row["type"] != "limit"
        or row["trigger"] != "immediate"
        or row["stop_price"] is not None
        or row["time_in_force"] != "gfd"
        or row["market_hours"] != "regular_hours"
    ):
        raise HistoryIssue("UNSUPPORTED_ORDER_TERMS")
    legs = row["legs"]
    if not isinstance(legs, list) or len(legs) != 1 or legs[0]["ratio_quantity"] != 1:
        raise HistoryIssue("SINGLE_OPTION_LEG_REQUIRED")
    leg = legs[0]
    if (
        leg.get("option_id") != attempt.instrument_id
        or leg["side"] != attempt.side.lower()
        or leg["position_effect"] != attempt.position_effect.lower()
        or row["direction"] != ("debit" if attempt.side == "BUY" else "credit")
        or whole(row["quantity"]) != attempt.quantity
        or _decimal(row["price"]) != attempt.limit_price
    ):
        raise HistoryIssue("ORDER_IDENTITY_CONFLICT")
    status = {
        "queued": "OPEN",
        "confirmed": "OPEN",
        "partially_filled": "PARTIAL",
        "filled": "FILLED",
        "cancelled": "CANCELED",
        "rejected": "REJECTED",
        "pending_cancelled": "PENDING_CANCEL",
    }.get(row["state"])
    if status is None:
        raise HistoryIssue("UNMAPPED_BROKER_ORDER_STATE")
    if not row.get("updated_at"):
        raise HistoryIssue("ORDER_UPDATE_TIME_MISSING")
    created, updated = instant(row["created_at"]), instant(row["updated_at"])
    if not attempt.attempted_at <= created <= updated <= as_of:
        raise HistoryIssue("ORDER_CLOCK_CONFLICT")
    filled, pending, canceled = (
        whole(row[k]) for k in ("processed_quantity", "pending_quantity", "canceled_quantity")
    )
    if (
        filled + pending + canceled > attempt.quantity
        or (status in {"FILLED", "REJECTED", "CANCELED"} and pending)
        or (status == "CANCELED" and filled + canceled != attempt.quantity)
    ):
        raise HistoryIssue("INCONSISTENT_BROKER_FILL_QUANTITY")
    raw_fills = leg.get("executions")
    if filled and not raw_fills:
        raise HistoryIssue("EXECUTION_DETAILS_MISSING")
    executions = tuple(
        Execution(
            fill_id=f["id"],
            quantity=whole(f["quantity"]),
            price=f["price"],
            occurred_at=instant(f["timestamp"]),
        )
        for f in raw_fills or ()
    )
    if any(f.occurred_at < created for f in executions):
        raise HistoryIssue("ORDER_CLOCK_CONFLICT")
    return HistoryOrder(
        order_id=row["id"],
        client_id=None,
        instrument_id=leg["option_id"],
        side=attempt.side,
        position_effect=attempt.position_effect,
        order_type="LIMIT",
        time_in_force="DAY",
        limit_price=row["price"],
        quantity=whole(row["quantity"]),
        updated_at=updated,
        status=status,
        filled_quantity=filled,
        fills=executions,
    )


def position_summary(rows, attempt, received):
    if len(rows) > 1 or any(r["option_id"] != attempt.instrument_id for r in rows):
        raise HistoryIssue("POSITION_SUBJECT_CONFLICT")
    if not rows:
        return {"status": "NO_OPEN_ROW", "observed_at": received.isoformat()}
    row = rows[0]
    if whole(row["quantity"]) == 0:
        raise HistoryIssue("NONZERO_POSITION_CONFLICT")
    if row.get("opened_at") and instant(row["opened_at"]) > received:
        raise HistoryIssue("POSITION_CLOCK_CONFLICT")
    if row["type"] not in {"long", "short"}:
        raise HistoryIssue("POSITION_TYPE_UNKNOWN")
    return {
        "status": "OBSERVED",
        "side": row["type"],
        "observed_at": received.isoformat(),
        **{
            k: whole(row[k])
            for k in (
                "quantity",
                "pending_buy_quantity",
                "pending_sell_quantity",
                "pending_exercise_quantity",
                "pending_assignment_quantity",
                "pending_expiration_quantity",
            )
        },
    }


def _unresolved(attempt, snapshots, reason):
    result = {
        "version": "option-order-recovery-v1",
        "last_verified_status": None,
        "last_verified_fill_count": None,
        "last_verified_filled_quantity": None,
        "resubmit": False,
        "live_enabled": False,
        "provider_calls": False,
        "state_modified": False,
    }
    if snapshots:
        result.update(
            recover(RecoveryCase(version=result["version"], attempt=attempt, snapshots=snapshots))
        )
    return {**result, "status": "UNRESOLVED", "reason": reason, "terminal_confirmed": False}


def _position_report(attempt, stream):
    try:
        rows, received = read_pages(stream, attempt, POSITIONS)
        return position_summary(rows, attempt, received)
    except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError) as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": str(exc) if isinstance(exc, HistoryIssue) else "POSITION_EVIDENCE_INVALID",
        }


def replay(attempt, bundles):
    snapshots = []
    position = {"status": "NOT_REQUESTED"}
    if attempt.order_id is None:
        return {**_unresolved(attempt, snapshots, "BROKER_ORDER_ID_REQUIRED"), "position": position}
    query(attempt, ORDERS)
    gap = None
    for bundle in bundles:
        if bundle is None:
            return {
                **_unresolved(attempt, snapshots, "HISTORY_CAPTURE_UNREADABLE"),
                "position": position,
            }
        if (
            not isinstance(bundle, dict)
            or bundle.get("version") != VERSION
            or bundle.get("endpoint") != ENDPOINT
            or bundle.get("attempt_sha256") != attempt_digest(attempt)
            or not isinstance(bundle.get("streams"), dict)
            or set(bundle["streams"]) not in ({ORDERS}, {ORDERS, POSITIONS})
        ):
            return {
                **_unresolved(attempt, snapshots, "HISTORY_CAPTURE_BINDING_CHANGED"),
                "position": {"status": "UNAVAILABLE"},
            }
        streams = bundle["streams"]
        if POSITIONS in streams:
            position = _position_report(attempt, streams[POSITIONS])
        stream = streams[ORDERS]
        try:
            rows, received = read_pages(stream, attempt, ORDERS)
            snapshots.append(
                History(
                    account_id=attempt.account_id,
                    observed_at=received,
                    complete=True,
                    orders=tuple(rows),
                )
            )
            gap = None
        except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, HistoryIssue) else "ORDER_EVIDENCE_INVALID"
            # A later complete read can resolve a read outage. A conflicting or
            # tampered observation requires review even if another file follows.
            if (
                isinstance(stream, dict)
                and stream.get("complete") is False
                and reason
                in {
                    "ACCOUNT_READ_FAILED",
                    "ACCOUNT_READ_TIMED_OUT",
                    "ACCOUNT_CONNECTION_UNAVAILABLE",
                    "READ_AUTHORIZATION_REQUIRED",
                    "ACCOUNT_PAGE_LIMIT",
                    "ACCOUNT_PAGE_UNAVAILABLE",
                    "ACCOUNT_ROWS_INCOMPLETE",
                    "ORDER_ACCOUNT_SCHEMA_UNREVIEWED",
                }
            ):
                try:
                    observed = instant(stream["observed_at"])
                except (KeyError, TypeError, ValueError):
                    reason = "ORDER_EVIDENCE_INVALID"
                else:
                    gap = reason
                    snapshots.append(
                        History(
                            account_id=attempt.account_id,
                            observed_at=observed,
                            complete=False,
                            orders=(),
                        )
                    )
                    continue
            return {**_unresolved(attempt, snapshots, reason), "position": position}
    if not snapshots:
        return {**_unresolved(attempt, [], "HISTORY_CAPTURE_REQUIRED"), "position": position}
    result = recover(
        RecoveryCase(version="option-order-recovery-v1", attempt=attempt, snapshots=snapshots)
    )
    if gap and result["reason"] == "ORDER_HISTORY_INCOMPLETE":
        result["reason"] = gap
    return {**result, "position": position}


def report_files(attempt_path, sources):
    from app.options.read_cli import private_json

    if len(sources) > 256:
        raise HistoryIssue("HISTORY_CAPTURE_COUNT_INVALID")
    attempt = Attempt.model_validate(private_json(attempt_path))

    def bundles():
        for source in sources:
            try:
                yield private_json(source, 8 * 1024 * 1024)
            except (OSError, ValueError):
                yield None
                return

    return replay(attempt, bundles())


def inventory_report(artifact):
    """Inspect retained tools/list evidence without credentials or an account query."""
    if artifact.get("endpoint") == ENDPOINT and isinstance(artifact.get("tools"), dict):
        tools = artifact["tools"]
        available = {k: tools[k] for k in PINS if k in tools}
    else:
        from app.options.read_capture import CaptureResult

        result = CaptureResult.model_validate(artifact["result"])
        if (
            artifact.get("operation") != "inventory"
            or artifact.get("status") != "COMPLETE"
            or result.operation != "DISCOVER"
            or result.status != "COMPLETE"
            or result.schemas is None
            or result.schemas.endpoint != ENDPOINT
            or result.inventory is None
        ):
            raise HistoryIssue("FULL_SCHEMA_INVENTORY_REQUIRED")
        entries = result.inventory["tools"]
        if not isinstance(entries, list) or len({entry["name"] for entry in entries}) != len(
            entries
        ):
            raise HistoryIssue("INVALID_SCHEMA_INVENTORY")
        available = {
            entry["name"]: entry.get("metadata") for entry in entries if entry["name"] in PINS
        }
    checks = {}
    for tool in PINS:
        if tool not in available:
            checks[tool] = "NOT_LISTED"
        elif not isinstance(available[tool], dict):
            checks[tool] = "SCHEMA_NOT_RETAINED"
        else:
            try:
                checked_schema(tool, available[tool])
            except (ValueError, KeyError, TypeError, AttributeError):
                checks[tool] = "SCHEMA_CHANGED"
            else:
                checks[tool] = "SUPPORTED"
    return {
        "status": "SAVED_SCHEMA_REPORT",
        "tools": checks,
        "account_permissions": "UNVERIFIED",
        "provider_calls": False,
        "execution_authority": False,
        "live_enabled": False,
    }


def capture_file(attempt_path, oauth_file, output, with_position):
    from app.execution.market_reads import market_read_lease, private_oauth
    from app.options.operator_inbox import private_directory, save
    from app.options.read_capture import CapturePolicy
    from app.options.read_cli import private_json
    from app.options.read_worker import connection

    attempt = Attempt.model_validate(private_json(attempt_path))
    query(attempt, ORDERS)
    output = Path(output)
    private_directory(output.parent)
    policy = CapturePolicy(oauth_file=oauth_file, timeout_seconds=30.0)

    async def run():
        bundle = empty_capture(attempt, with_position)
        try:
            async with asyncio.timeout(policy.timeout_seconds):
                async with connection(policy).client() as client:
                    await _collect_into(client, attempt, bundle, utc_now)
        except Exception as exc:  # noqa: BLE001 - persist partial reads even if SDK cleanup fails.
            from app.options.read_worker import ReadAuthorizationRequired

            reason = (
                "ACCOUNT_READ_TIMED_OUT"
                if isinstance(exc, TimeoutError)
                else "READ_AUTHORIZATION_REQUIRED"
                if isinstance(exc, ReadAuthorizationRequired)
                else "ACCOUNT_CONNECTION_UNAVAILABLE"
            )
            bundle["connection_issue"] = reason
            for stream in bundle["streams"].values():
                if not stream["complete"]:
                    stream.setdefault("issue", reason)
                    stream.setdefault("observed_at", utc_now().isoformat())
        return bundle

    with market_read_lease(policy.oauth_file):
        if output.exists() or output.is_symlink():
            raise HistoryIssue("HISTORY_DESTINATION_EXISTS")
        private_oauth(policy.oauth_file)
        bundle = asyncio.run(run())
        save(output, bundle)
    return {
        "status": "HISTORY_CAPTURED"
        if all(s["complete"] for s in bundle["streams"].values())
        else "HISTORY_INCOMPLETE",
        "reads": {
            tool: {"pages": len(s["pages"]), "complete": s["complete"], "issue": s.get("issue")}
            for tool, s in bundle["streams"].items()
        },
        "live_enabled": False,
        "execution_authority": False,
        "connection_issue": bundle.get("connection_issue"),
    }
