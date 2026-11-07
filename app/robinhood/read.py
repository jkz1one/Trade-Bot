from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal, InvalidOperation
from typing import Any

from app.robinhood.gateway import RobinhoodSafeGateway
from app.robinhood.models import (
    RobinhoodAccount,
    RobinhoodOrder,
    RobinhoodPortfolio,
    RobinhoodPosition,
    RobinhoodTruth,
)


OPEN_ORDER_STATES = (
    "new",
    "queued",
    "confirmed",
    "unconfirmed",
    "partially_filled",
)


def tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Return the output-schema object from an MCP CallToolResult dump."""
    if any(result.get(flag, False) is not False for flag in ("isError", "is_error")):
        raise RuntimeError("Robinhood tool reported an error")
    raw = result.get("structuredContent")
    if raw is None:
        raw = result.get("structured_content")
    if raw is None:
        raw = result
    if not isinstance(raw, dict):
        raise RuntimeError("Robinhood MCP returned no structured object payload")
    return raw


def tool_data(result: dict[str, Any]) -> dict[str, Any]:
    payload = tool_payload(result)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Robinhood MCP result is missing structured data")
    return data


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise RuntimeError("Incomplete Robinhood portfolio amount") from None
    if not amount.is_finite():
        raise RuntimeError("Incomplete Robinhood portfolio amount")
    return amount


def _account_binding(data: dict[str, Any], expected: str) -> None:
    if "account_number" in data and data["account_number"] != expected:
        raise RuntimeError("Robinhood account identity changed")


class RobinhoodReadService:
    def __init__(self, gateway: RobinhoodSafeGateway):
        self.gateway = gateway

    async def get_agentic_account(self) -> RobinhoodAccount:
        data = tool_data(await self.gateway.call_safe("get_accounts", {}))
        accounts = data.get("accounts")
        if (not isinstance(accounts, list) or data.get("next") or data.get("restricted")
                or any(not isinstance(a, dict) or type(a.get("agentic_allowed")) is not bool for a in accounts)):
            raise RuntimeError("Incomplete Robinhood account selection")
        eligible = [a for a in accounts if a["agentic_allowed"]]
        if len(eligible) != 1:
            raise RuntimeError(
                f"Expected exactly one Robinhood account accessible to this agent; found {len(eligible)}"
            )
        account = RobinhoodAccount.model_validate(eligible[0])
        if account.state != "active" or account.deactivated or account.permanently_deactivated:
            raise RuntimeError("Robinhood agentic account is not active")
        return account

    async def get_portfolio(self, account_number: str) -> RobinhoodPortfolio:
        data = tool_data(
            await self.gateway.call_safe("get_portfolio", {"account_number": account_number})
        )
        _account_binding(data, account_number)
        bp = data.get("buying_power")
        if not isinstance(bp, dict):
            raise RuntimeError("Incomplete Robinhood buying power")
        # Any unsupported exposure blocks equity reconciliation, including offsetting values.
        unsupported = sum((_money(data.get(field)).copy_abs() for field in (
            "options_value", "crypto_value", "futures_value", "event_contracts_value",
            "mutual_funds_value", "fixed_income_value",
        )), Decimal("0"))
        buying_power = _money(bp.get("buying_power"))
        unleveraged = _money(bp.get("unleveraged_buying_power"))
        safe_buying_power = min(buying_power, max(Decimal("0"), unleveraged))
        return RobinhoodPortfolio(
            total_value=_money(data.get("total_value")),
            equity_value=_money(data.get("equity_value")),
            cash=_money(data.get("cash")),
            buying_power=safe_buying_power,
            unleveraged_buying_power=unleveraged,
            unsupported_value=unsupported,
        )

    async def _rows(self, tool: str, field: str, account_number: str,
                    **filters: str) -> AsyncIterator[dict[str, Any]]:
        arguments = {"account_number": account_number, **filters}
        cursors: set[str] = set()
        for _ in range(64):
            data = tool_data(await self.gateway.call_safe(tool, arguments.copy()))
            _account_binding(data, account_number)
            rows = data.get(field)
            if not isinstance(rows, list) or data.get("restricted"):
                raise RuntimeError("Incomplete Robinhood account page")
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("Incomplete Robinhood account row")
                _account_binding(row, account_number)
                yield row
            cursor = data.get("next")
            if cursor is None or cursor == "":
                return
            if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in cursors:
                raise RuntimeError("Invalid or repeated Robinhood account cursor")
            cursors.add(cursor)
            arguments["cursor"] = cursor
        raise RuntimeError("Robinhood account pagination exceeds bound")

    async def get_positions(self, account_number: str) -> list[RobinhoodPosition]:
        positions = []
        symbols = set()
        async for row in self._rows("get_equity_positions", "positions", account_number):
            position = RobinhoodPosition.model_validate(row)
            if position.symbol in symbols:
                raise RuntimeError("Duplicate Robinhood position in account snapshot")
            symbols.add(position.symbol)
            positions.append(position)
        return positions

    async def get_working_orders(self, account_number: str) -> list[RobinhoodOrder]:
        orders: dict[str, RobinhoodOrder] = {}
        for state in OPEN_ORDER_STATES:
            async for row in self._rows("get_equity_orders", "orders", account_number, state=state):
                order = RobinhoodOrder.model_validate(row)
                previous = orders.get(order.id)
                if order.state != state or (previous is not None and order != previous):
                    raise RuntimeError("Conflicting Robinhood working-order observations")
                orders[order.id] = order
        return list(orders.values())

    async def truth(self) -> RobinhoodTruth:
        account = await self.get_agentic_account()
        portfolio = await self.get_portfolio(account.account_number)
        positions = await self.get_positions(account.account_number)
        working_orders = await self.get_working_orders(account.account_number)
        return RobinhoodTruth(
            account=account,
            portfolio=portfolio,
            positions=positions,
            working_orders=working_orders,
        )
