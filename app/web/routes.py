from __future__ import annotations

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.metrics.benchmark import benchmark_return
from app.metrics.costs import economic_pnl
from app.metrics.performance import capital_multiple, net_strategy_pnl, simple_return
from app.risk.policy import policy_for_equity

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def dashboard_context(request: Request):
    state = request.app.state.runtime
    broker, repo, settings = state["broker"], state["repo"], state["settings"]
    candidates = state["market"].candidates()
    quotes = {c.quote.symbol: c.quote for c in candidates}
    account = broker.account_state(quotes)
    flows = repo.capital_flow_total()
    cycles = repo.recent_cycles(8)
    ai_cost = repo.model_cost_total()
    pnl = net_strategy_pnl(account, flows)
    has_external_flows = flows != settings.starting_capital
    benchmark_prices = repo.benchmark_range(settings.benchmark_symbol)
    benchmark_pct = None
    if benchmark_prices and not has_external_flows:
        benchmark_pct = benchmark_return(*benchmark_prices) * 100
    latest = None
    if cycles:
        latest = {
            "decision": json.loads(cycles[0].decision_json),
            "risk": json.loads(cycles[0].risk_json),
            "execution": json.loads(cycles[0].execution_json),
        }
    return {
        "request": request,
        "mode": settings.normalized_mode,
        "enabled": state["orchestrator"].system_enabled,
        "account": account,
        "pnl": pnl,
        "return_pct": simple_return(account, flows) * 100,
        "multiple": capital_multiple(account, settings.starting_capital, flows != settings.starting_capital),
        "ai_cost": ai_cost,
        "economic_pnl": economic_pnl(pnl, ai_cost),
        "cycles": cycles,
        "latest": latest,
        "risk_mode": policy_for_equity(account.equity).name,
        "benchmark_symbol": settings.benchmark_symbol,
        "benchmark_pct": benchmark_pct,
        "benchmark_note": "Contribution-adjusted benchmark pending" if has_external_flows else None,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", dashboard_context(request))


@router.post("/cycle")
def run_cycle(request: Request):
    request.app.state.runtime["orchestrator"].cycle()
    return RedirectResponse("/", status_code=303)


@router.post("/halt")
def halt(request: Request):
    request.app.state.runtime["orchestrator"].system_enabled = False
    return RedirectResponse("/", status_code=303)
