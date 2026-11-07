from __future__ import annotations

from decimal import Decimal

import pytest

from app.robinhood.read import OPEN_ORDER_STATES, RobinhoodReadService, tool_data


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def call_safe(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "get_accounts":
            payload = {"data": {"accounts": [{
                "account_number": "RH1234",
                "rhs_account_number": "1234",
                "type": "cash",
                "brokerage_account_type": "individual",
                "agentic_allowed": True,
                "state": "active",
                "deactivated": False,
                "permanently_deactivated": False,
            }]}}
        elif name == "get_portfolio":
            payload = {"data": {
                "total_value": "10.00",
                "equity_value": "0",
                "cash": "10.00",
                "options_value": "0",
                "crypto_value": "0",
                "futures_value": "0",
                "event_contracts_value": "0",
                "mutual_funds_value": "0",
                "fixed_income_value": "0",
                "buying_power": {
                    "buying_power": "15.00",
                    "unleveraged_buying_power": "10.00",
                    "display_currency": "USD",
                },
            }}
        elif name == "get_equity_positions":
            payload = {"data": {"positions": [], "next": ""}}
        elif name == "get_equity_orders":
            payload = {"data": {"orders": [], "next": ""}}
        else:
            raise AssertionError(name)
        return {"structuredContent": payload}


@pytest.mark.anyio
async def test_truth_uses_agentic_account_and_unleveraged_buying_power():
    gateway = FakeGateway()
    truth = await RobinhoodReadService(gateway).truth()
    assert truth.account.account_number == "RH1234"
    assert truth.portfolio.buying_power == Decimal("10.00")
    assert truth.positions == []
    states = [
        args["state"]
        for name, args in gateway.calls
        if name == "get_equity_orders"
    ]
    assert states == list(OPEN_ORDER_STATES)


def test_tool_data_accepts_snake_case_structured_content():
    assert tool_data({"structured_content": {"data": {"x": 1}}}) == {"x": 1}


class PagedGateway(FakeGateway):
    def __init__(self, scripted):
        super().__init__()
        self.scripted = scripted

    async def call_safe(self, name, arguments):
        if name not in self.scripted:
            return await super().call_safe(name, arguments)
        self.calls.append((name, dict(arguments)))
        return self.scripted[name](arguments)


def page(data):
    return {"structuredContent": {"data": data}}


@pytest.mark.anyio
@pytest.mark.parametrize("tool,field", [("get_equity_positions", "positions"), ("get_equity_orders", "orders")])
@pytest.mark.parametrize("damage", ["missing", "null_list", "null_row", "tool_error", "wrong_account", "restricted"])
async def test_incomplete_pages_never_reach_reconciliation(tool, field, damage):
    data = {field: [], "next": ""}
    if damage == "missing":
        del data[field]
    elif damage == "null_list":
        data[field] = None
    elif damage == "null_row":
        data[field] = [None]
    elif damage == "wrong_account":
        data["account_number"] = "another-account"
    elif damage == "restricted":
        data["restricted"] = ["unavailable"]
    gateway = PagedGateway({tool: lambda args: {**page(data), "isError": damage == "tool_error"}})
    with pytest.raises(RuntimeError):
        await RobinhoodReadService(gateway).truth()
    assert gateway.calls[-1][0] == tool


@pytest.mark.anyio
@pytest.mark.parametrize("unique,expected_calls", [(False, 2), (True, 64)])
async def test_incomplete_pagination_is_bounded_without_returning_partial_rows(unique, expected_calls):
    def respond(_args):
        return page({"positions": [], "next": str(len(gateway.calls)) if unique else "repeat"})
    gateway = PagedGateway({"get_equity_positions": respond})
    with pytest.raises(RuntimeError, match="pagination|cursor"):
        await RobinhoodReadService(gateway).get_positions("RH1234")
    assert len(gateway.calls) == expected_calls


@pytest.mark.anyio
@pytest.mark.parametrize("conflict", [False, True])
async def test_partial_order_on_two_pages_must_agree(conflict):
    def respond(args):
        if args["state"] != "partially_filled":
            return page({"orders": []})
        second = "cursor" in args
        order = {"id": "original", "symbol": "SPY", "side": "buy", "state": "partially_filled",
                 "quantity": "2", "cumulative_quantity": "2" if second and conflict else "1"}
        return page({"orders": [order], "next": None if second else "page-two"})
    gateway = PagedGateway({"get_equity_orders": respond})
    if conflict:
        with pytest.raises(RuntimeError, match="Conflicting"):
            await RobinhoodReadService(gateway).truth()
    else:
        snapshot = await RobinhoodReadService(gateway).truth()
        assert [(o.id, o.cumulative_quantity) for o in snapshot.working_orders] == [("original", 1)]
    assert gateway.calls[-1][1] == {"account_number": "RH1234", "state": "partially_filled", "cursor": "page-two"}


@pytest.mark.anyio
@pytest.mark.parametrize("damage", ["omitted_asset", "null_cash", "nonfinite_bp", "offsetting_exposure"])
async def test_portfolio_amounts_cannot_hide_unknown_or_offsetting_exposure(damage):
    response = await FakeGateway().call_safe("get_portfolio", {})
    data = response["structuredContent"]["data"]
    if damage == "omitted_asset":
        del data["options_value"]
    elif damage == "null_cash":
        data["cash"] = None
    elif damage == "nonfinite_bp":
        data["buying_power"]["buying_power"] = "Infinity"
    else:
        data.update(options_value="12", futures_value="-12")
    service = RobinhoodReadService(PagedGateway({"get_portfolio": lambda _: response}))
    if damage == "offsetting_exposure":
        assert (await service.truth()).portfolio.unsupported_value == Decimal("24")
    else:
        with pytest.raises(RuntimeError, match="portfolio amount"):
            await service.truth()
