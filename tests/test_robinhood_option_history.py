"""Account history wire-to-recovery round trips. Account rows here are synthetic."""

import asyncio
import copy
import json
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.execution.order_recovery import Attempt
from app.robinhood import option_history as wire

BID = "28ace6f5-edd5-4592-934c-3733e12e30ab"
OID = "deddfe18-31ce-4b48-8190-677b421a4239"
START = datetime(2026, 11, 6, 15, tzinfo=UTC)
ATTEMPT = Attempt(
    account_id="private-account",
    client_id="private-client",
    order_id=BID,
    instrument_id=OID,
    side="BUY",
    quantity=2,
    limit_price="1.1",
    time_in_force="DAY",
    order_type="LIMIT",
    position_effect="OPEN",
    attempted_at=START,
)
METADATA = json.loads(
    (Path(__file__).parent / "fixtures/robinhood_option_account_schema.json").read_text()
)


def when(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def order(state):
    filled = {
        "queued": 0,
        "confirmed": 0,
        "rejected": 0,
        "partially_filled": 1,
        "pending_cancelled": 1,
        "cancelled": 1,
        "filled": 2,
    }[state]
    fills = [
        {
            "id": f"fill-{i}",
            "quantity": "1.0000",
            "price": "1.05",
            "timestamp": when(2 + i),
            "settlement_date": "2026-11-09",
            "trade_date": "2026-11-06",
        }
        for i in range(filled)
    ]
    return {
        "id": BID,
        "chain_id": "chain",
        "chain_symbol": "SPY",
        "state": state,
        "type": "limit",
        "trigger": "immediate",
        "direction": "debit",
        "quantity": "2.0000",
        "processed_quantity": str(filled),
        "pending_quantity": str(2 - filled if state not in {"cancelled", "rejected"} else 0),
        "canceled_quantity": str(2 - filled if state == "cancelled" else 0),
        "price": "1.1000",
        "stop_price": None,
        "premium": "220",
        "processed_premium": str(filled * 105),
        "trade_value_multiplier": "100",
        "time_in_force": "gfd",
        "market_hours": "regular_hours",
        "opening_strategy": "long_call",
        "closing_strategy": None,
        "placed_agent": "user",
        "agent_initiated": True,
        "created_at": when(1),
        "updated_at": when(4 if state in {"filled", "cancelled"} else 3),
        "last_transaction_at": when(3),
        "reject_reason": "",
        "is_replaceable": False,
        "legs": [
            {
                "id": "leg",
                "option_id": OID,
                "side": "buy",
                "position_effect": "open",
                "ratio_quantity": 1,
                "expiration_date": "2026-11-06",
                "strike_price": "765",
                "option_type": "call",
                "executions": fills,
            }
        ],
    }


def position():
    return {
        "option_id": OID,
        "chain_id": "chain",
        "chain_symbol": "SPY",
        "type": "long",
        "quantity": "3.00",
        "average_price": "1.07",
        "expiration_date": "2026-11-06",
        "trade_value_multiplier": "100",
        "intraday_average_open_price": "1.07",
        "intraday_quantity": "1",
        "pending_buy_quantity": "1",
        "pending_sell_quantity": "0",
        "pending_exercise_quantity": "0",
        "pending_assignment_quantity": "0",
        "pending_expiration_quantity": "0",
        "opened_at": when(1),
    }


def response(rows, *, field="orders", cursor=""):
    return {
        "isError": False,
        "structuredContent": {"data": {field: rows, "next": cursor}, "guide": ""},
    }


class Client:
    def __init__(self, orders, positions=()):
        self.tools = copy.deepcopy(list(METADATA.values()))
        self.responses = {wire.ORDERS: list(orders), wire.POSITIONS: list(positions)}
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call_tool(self, tool, args):
        assert tool in self.responses
        self.calls.append((tool, args))
        return self.responses[tool].pop(0)


def captured(client, *, at=5, positions=False, attempt=ATTEMPT):
    counter = iter(range(at, at + 100))
    return asyncio.run(
        wire.capture(
            client,
            attempt,
            with_position=positions,
            clock=lambda: START + timedelta(seconds=next(counter)),
        )
    )


@pytest.mark.parametrize("terminal", ["filled", "cancelled"])
def test_private_broker_pages_recover_fills_and_preserve_account_position(terminal):
    first = Client([response([order("partially_filled")])])
    prior = captured(first)
    last = Client(
        [response([], cursor="page2"), response([order(terminal)])],
        [response([position()], field="positions")],
    )
    final = captured(last, at=15, positions=True)
    result = wire.replay(ATTEMPT, [prior, final])
    assert result["status"] == "MATCHED" and result["terminal_confirmed"]
    assert result["last_verified_filled_quantity"] == (1 if terminal == "cancelled" else 2)
    assert result["position"]["quantity"] == 3 and result["position"]["pending_buy_quantity"] == 1
    assert result["resubmit"] is result["provider_calls"] is result["live_enabled"] is False
    assert last.calls == [
        (wire.ORDERS, {"account_number": "private-account", "order_id": BID}),
        (wire.ORDERS, {"account_number": "private-account", "order_id": BID, "cursor": "page2"}),
        (wire.POSITIONS, {"account_number": "private-account", "option_ids": OID, "nonzero": True}),
    ]
    assert "private-" not in json.dumps(result) and BID not in json.dumps(result)


def test_pending_cancel_with_confirmed_fill_is_still_working():
    result = wire.replay(ATTEMPT, [captured(Client([response([order("pending_cancelled")])]))])
    assert result["last_verified_status"] == "PENDING_CANCEL" and not result["terminal_confirmed"]
    assert result["last_verified_filled_quantity"] == 1


@pytest.mark.parametrize(
    "damage",
    [
        "missing_executions",
        "unknown_state",
        "missing_timestamp",
        "multi_leg",
        "ratio",
        "stop_limit",
        "wrong_direction",
        "fraction",
        "missing_option_id",
        "different_limit",
        "wrong_hours",
        "future_fill",
        "wrong_quantity",
        "wrong_order",
        "wrong_account",
        "modified_cursor",
        "future_update_first_page",
        "missing_last_page",
    ],
)
def test_unusable_update_keeps_prior_verified_fill(damage):
    prior = captured(Client([response([order("partially_filled")])]))
    new = captured(Client([response([order("filled")], cursor="next"), response([])]), at=15)
    stream = new["streams"][wire.ORDERS]
    page = stream["pages"][0]
    row = page["response"]["structuredContent"]["data"]["orders"][0]
    leg = row["legs"][0]
    if damage == "missing_executions":
        del leg["executions"]
    elif damage == "unknown_state":
        row["state"] = "future-state"
    elif damage == "missing_timestamp":
        del row["updated_at"]
    elif damage == "multi_leg":
        row["legs"].append(leg.copy())
    elif damage == "ratio":
        leg["ratio_quantity"] = 2
    elif damage == "stop_limit":
        row["trigger"] = "stop"
    elif damage == "wrong_direction":
        row["direction"] = "credit"
    elif damage == "fraction":
        row["processed_quantity"] = "1.1"
    elif damage == "missing_option_id":
        del leg["option_id"]
    elif damage == "different_limit":
        row["price"] = "1.11"
    elif damage == "wrong_hours":
        row["market_hours"] = "regular_curb_hours"
    elif damage == "future_fill":
        leg["executions"][1]["timestamp"] = when(99)
    elif damage == "wrong_quantity":
        row["processed_quantity"] = "1"
    elif damage == "wrong_order":
        row["id"] = OID
    elif damage == "wrong_account":
        page["arguments"]["account_number"] = "another"
    elif damage == "modified_cursor":
        stream["pages"][1]["arguments"]["cursor"] = "wrong"
    elif damage == "future_update_first_page":
        row["updated_at"] = when(17)
    else:
        stream["pages"].pop()
    result = wire.replay(ATTEMPT, [prior, new])
    assert result["status"] == "UNRESOLVED", result
    assert result["last_verified_filled_quantity"] == 1 and not result["terminal_confirmed"]
    assert not result["resubmit"]


@pytest.mark.parametrize(
    "kind",
    [
        "no_id",
        "changed_schema",
        "mutating_hint",
        "duplicate_tool",
        "repeated_cursor",
        "missing_terminal",
        "tool_error",
    ],
)
def test_no_guessing_and_bounded_reads(kind):
    replies = [response([order("filled")])]
    if kind == "repeated_cursor":
        replies = [response([], cursor="x"), response([], cursor="x")]
    elif kind == "missing_terminal":
        replies = [response([])]
        del replies[0]["structuredContent"]["data"]["next"]
    elif kind == "tool_error":
        replies[0]["isError"] = True
    client = Client(replies)
    if kind == "no_id":
        with pytest.raises(wire.HistoryIssue, match="BROKER_ORDER_ID_REQUIRED"):
            captured(client, attempt=ATTEMPT.model_copy(update={"order_id": None}))
        assert not client.calls
        return
    meta = next(t for t in client.tools if t["name"] == wire.ORDERS)
    if kind == "changed_schema":
        meta["inputSchema"]["properties"]["state"]["type"] = "integer"
    elif kind == "mutating_hint":
        meta["annotations"]["readOnlyHint"] = False
    elif kind == "duplicate_tool":
        client.tools.append(meta)
    artifact = captured(client)
    assert not artifact["streams"][wire.ORDERS]["complete"]
    assert len(client.calls) == (
        {"repeated_cursor": 2, "missing_terminal": 1, "tool_error": 1}.get(kind, 0)
    )
    assert wire.replay(ATTEMPT, [artifact])["status"] == "UNRESOLVED"


@pytest.mark.parametrize("kind", ["empty", "missing_next", "bad_subject", "null_rows"])
def test_positions_never_supply_order_ownership_or_hide_a_gap(kind):
    pos = response([], field="positions")
    if kind == "missing_next":
        del pos["structuredContent"]["data"]["next"]
    elif kind == "bad_subject":
        pos = response([position() | {"option_id": BID}], field="positions")
    elif kind == "null_rows":
        pos["structuredContent"]["data"]["positions"] = None
    data = captured(Client([response([order("filled")])], [pos]), positions=True)
    result = wire.replay(ATTEMPT, [data])
    assert result["terminal_confirmed"] and result["last_verified_fill_count"] == 2
    assert result["position"]["status"] == ("NO_OPEN_ROW" if kind == "empty" else "UNAVAILABLE")


def test_cli_round_trip_retains_private_file_uses_no_trading_gateway(tmp_path, monkeypatch, capsys):
    from test_option_read_capture import oauth

    from app.options import read_worker
    from app.robinhood import cli

    tmp_path.chmod(0o700)
    attempt = tmp_path / "attempt.json"
    attempt.write_text(ATTEMPT.model_dump_json())
    attempt.chmod(0o600)
    output = tmp_path / "evidence.json"
    client = Client([response([order("filled")])])

    @asynccontextmanager
    async def connected():
        yield client

    class Connection:
        client = staticmethod(connected)

    monkeypatch.setattr(read_worker, "connection", lambda _: Connection())
    monkeypatch.setattr(wire, "utc_now", lambda: START + timedelta(seconds=5))
    monkeypatch.setattr(cli, "Settings", lambda: pytest.fail("opened trade runtime"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cli",
            "capture-option-history",
            "--attempt",
            str(attempt),
            "--oauth-file",
            str(oauth(tmp_path)),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as code:
        cli.main()
    assert (
        code.value.code == 0 and json.loads(capsys.readouterr().out)["status"] == "HISTORY_CAPTURED"
    )
    assert output.stat().st_mode & 0o777 == 0o600
    original = output.read_bytes()
    with pytest.raises(SystemExit) as code:
        cli.main()
    assert (
        code.value.code == 2
        and json.loads(capsys.readouterr().out)["reason"] == "HISTORY_DESTINATION_EXISTS"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli", "order-recovery-report", "--attempt", str(attempt), "--history", str(output)],
    )
    with pytest.raises(SystemExit) as code:
        cli.main()
    assert code.value.code == 0
    stdout = capsys.readouterr().out
    assert "private-" not in stdout and json.loads(stdout)["last_verified_status"] == "FILLED"
    assert len(client.calls) == 1 and output.read_bytes() == original


def test_later_read_can_recover_from_outage_but_not_conflicting_broker_evidence():
    first = captured(Client([response([order("partially_filled")])]), at=5)
    down = captured(Client([], [response([position()], field="positions")]), at=10, positions=True)
    result = wire.replay(ATTEMPT, [first, down])
    assert (
        result["reason"] == "ACCOUNT_READ_FAILED" and result["last_verified_filled_quantity"] == 1
    )
    assert result["position"]["quantity"] == 3
    final = captured(Client([response([order("filled")])]), at=20)
    assert wire.replay(ATTEMPT, [first, down, final])["last_verified_filled_quantity"] == 2
    changed = order("filled")
    changed["legs"][0]["executions"][0]["price"] = "0.75"
    conflict = captured(Client([response([changed])]), at=10)
    result = wire.replay(ATTEMPT, [first, conflict, final])
    assert result["status"] == "UNRESOLVED" and result["last_verified_filled_quantity"] == 1


def test_attempt_without_broker_id_never_opens_history_sources():
    def forbidden():
        pytest.fail("opened account history")
        yield

    result = wire.replay(ATTEMPT.model_copy(update={"order_id": None}), forbidden())
    assert result["reason"] == "BROKER_ORDER_ID_REQUIRED" and result["resubmit"] is False


def test_existing_discovery_metadata_support_and_changed_shape_are_separate():
    saved = {"endpoint": wire.ENDPOINT, "tools": copy.deepcopy(METADATA)}
    before = copy.deepcopy(saved)
    result = wire.inventory_report(saved)
    assert result["tools"] == {wire.ORDERS: "SUPPORTED", wire.POSITIONS: "SUPPORTED"}
    assert result["account_permissions"] == "UNVERIFIED" and not result["provider_calls"]
    assert saved == before
    saved["tools"][wire.ORDERS]["outputSchema"]["properties"]["data"]["type"] = "array"
    del saved["tools"][wire.POSITIONS]
    assert wire.inventory_report(saved)["tools"] == {
        wire.ORDERS: "SCHEMA_CHANGED",
        wire.POSITIONS: "NOT_LISTED",
    }


def test_sell_to_close_reconciles_only_credit_executions_at_or_above_limit():
    attempt = ATTEMPT.model_copy(update={"side": "SELL", "position_effect": "CLOSE"})
    row = order("filled")
    row.update(direction="credit", opening_strategy=None, closing_strategy="long_call")
    leg = row["legs"][0]
    leg.update(side="sell", position_effect="close")
    for fill in leg["executions"]:
        fill["price"] = "1.15"

    def result():
        return wire.replay(attempt, [captured(Client([response([row])]), attempt=attempt)])

    assert result()["last_verified_filled_quantity"] == 2
    leg["executions"][0]["price"] = "1.09"
    assert result()["status"] == "UNRESOLVED"


def test_cancellation_requires_accounting_for_the_unfilled_contracts():
    row = order("cancelled")
    row["canceled_quantity"] = "0"
    result = wire.replay(ATTEMPT, [captured(Client([response([row])]))])
    assert result["reason"] == "INCONSISTENT_BROKER_FILL_QUANTITY"
    assert not result["terminal_confirmed"]


def test_unreadable_later_receipt_retains_verified_quantity(tmp_path):
    attempt = tmp_path / "attempt.json"
    attempt.write_text(ATTEMPT.model_dump_json())
    attempt.chmod(0o600)
    first = tmp_path / "first.json"
    first.write_text(json.dumps(captured(Client([response([order("partially_filled")])]))))
    first.chmod(0o600)
    result = wire.report_files(attempt, [first, tmp_path / "missing.json"])
    assert result["reason"] == "HISTORY_CAPTURE_UNREADABLE"
    assert result["last_verified_filled_quantity"] == 1 and not result["terminal_confirmed"]


def test_position_keeps_original_clock_and_does_not_gain_freshness_on_later_order_read():
    pos = response([position()], field="positions", cursor="next")
    both = captured(
        Client([response([order("partially_filled")])], [pos, response([], field="positions")]),
        positions=True,
    )
    expected = both["streams"][wire.POSITIONS]["pages"][0]["received_at"]
    last = captured(Client([response([order("filled")])]), at=25)
    result = wire.replay(ATTEMPT, [both, last])
    assert result["terminal_confirmed"]
    assert result["position"]["observed_at"] == expected
    position_row = both["streams"][wire.POSITIONS]["pages"][0]["response"]["structuredContent"][
        "data"
    ]["positions"][0]
    position_row["opened_at"] = (
        datetime.fromisoformat(expected) + timedelta(seconds=1)
    ).isoformat()
    assert wire.replay(ATTEMPT, [both])["position"]["reason"] == "POSITION_CLOCK_CONFLICT"


def test_offline_cli_accepts_saved_discovery_and_identifies_unretained_metadata(
    tmp_path, monkeypatch, capsys
):
    from test_option_read_capture import Client as SchemaClient
    from test_option_read_capture import metadata

    from app.options.read_capture import CaptureResult
    from app.options.read_gateway import OptionReadGateway
    from app.robinhood import cli

    advertised = copy.deepcopy(list(METADATA.values()))
    advertised[1]["description"] = "x" * (65 * 1024)
    client = SchemaClient(metadata() + advertised)
    gateway = OptionReadGateway(client)
    schemas = asyncio.run(gateway.discover(include_inventory=True))
    capture = CaptureResult(
        request_id="a" * 32,
        policy_sha256="b" * 64,
        operation="DISCOVER",
        status="COMPLETE",
        started_at=START,
        collected_at=START,
        elapsed_seconds=0,
        schemas=schemas,
        inventory=gateway.inventory,
    )
    artifact = {
        "operation": "inventory",
        "status": "COMPLETE",
        "result": capture.model_dump(mode="json"),
    }
    file = tmp_path / "inventory.json"
    file.write_text(json.dumps(artifact))
    file.chmod(0o600)
    monkeypatch.setattr(cli, "Settings", lambda: pytest.fail("opened trade runtime"))
    monkeypatch.setattr(sys, "argv", ["cli", "order-history-schema-report", "--source", str(file)])
    with pytest.raises(SystemExit) as exit_code:
        cli.main()
    assert exit_code.value.code == 0 and not client.calls
    report = json.loads(capsys.readouterr().out)
    assert report["tools"] == {
        advertised[0]["name"]: "SUPPORTED",
        advertised[1]["name"]: "SCHEMA_NOT_RETAINED",
    }
    assert report["account_permissions"] == "UNVERIFIED"
