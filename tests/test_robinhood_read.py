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
