from __future__ import annotations

from decimal import Decimal
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


def _d(value: Any, *, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


class RobinhoodReadService:
    def __init__(self, gateway: RobinhoodSafeGateway):
        self.gateway = gateway

    async def get_agentic_account(self) -> RobinhoodAccount:
        data = tool_data(await self.gateway.call_safe("get_accounts", {}))
        accounts = data.get("accounts") or []
        eligible = [a for a in accounts if a and a.get("agentic_allowed") is True]
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
        bp = data.get("buying_power") or {}
        unsupported = sum(
            (
                _d(data.get("options_value")),
                _d(data.get("crypto_value")),
                _d(data.get("futures_value")),
                _d(data.get("event_contracts_value")),
                _d(data.get("mutual_funds_value")),
                _d(data.get("fixed_income_value")),
            ),
            Decimal("0"),
        )
        buying_power = _d(bp.get("buying_power"))
        unleveraged = _d(bp.get("unleveraged_buying_power"))
        safe_buying_power = min(buying_power, max(Decimal("0"), unleveraged))
        return RobinhoodPortfolio(
            total_value=_d(data.get("total_value")),
            equity_value=_d(data.get("equity_value")),
            cash=_d(data.get("cash")),
            buying_power=safe_buying_power,
            unleveraged_buying_power=unleveraged,
            unsupported_value=unsupported,
        )

    async def get_positions(self, account_number: str) -> list[RobinhoodPosition]:
        positions: list[RobinhoodPosition] = []
        cursor: str | None = None
        while True:
            args: dict[str, Any] = {"account_number": account_number}
            if cursor:
                args["cursor"] = cursor
            data = tool_data(await self.gateway.call_safe("get_equity_positions", args))
            for item in data.get("positions") or []:
                if item is not None:
                    positions.append(RobinhoodPosition.model_validate(item))
            cursor = data.get("next") or None
            if not cursor:
                break
        return positions

    async def get_working_orders(self, account_number: str) -> list[RobinhoodOrder]:
        orders: list[RobinhoodOrder] = []
        seen: set[str] = set()
        for state in OPEN_ORDER_STATES:
            cursor: str | None = None
            while True:
                args: dict[str, Any] = {"account_number": account_number, "state": state}
                if cursor:
                    args["cursor"] = cursor
                data = tool_data(await self.gateway.call_safe("get_equity_orders", args))
                for item in data.get("orders") or []:
                    if item is None or item.get("id") in seen:
                        continue
                    order = RobinhoodOrder.model_validate(item)
                    seen.add(order.id)
                    orders.append(order)
                cursor = data.get("next") or None
                if not cursor:
                    break
        return orders

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
