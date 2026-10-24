"""Private options observer factory. Only persisted reads, no trading routes."""

import os
import stat
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.domain.models import utc_now
from app.options.observer import OptionObserver
from app.web.mixed_view import display_time, evidence_id, family_of, mixed_view
from app.web.trade_rail import trade_rail

basic = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["trade_rail"] = trade_rail
templates.env.filters["dollars"] = lambda value: format(Decimal(value), ",.2f")
templates.env.filters["display_time"] = display_time
templates.env.filters["evidence_id"] = evidence_id
templates.env.globals["family_of"] = family_of
templates.env.globals["mixed_view"] = mixed_view


def password(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 24 <= info.st_size <= 513
        ):
            raise ValueError("Private bounded observer password required")
        value = os.read(fd, 514).removesuffix(b"\n")
        if not 24 <= len(value) <= 512 or any(c < 33 or c > 126 for c in value):
            raise ValueError("Visible ASCII observer password required")
        return value
    finally:
        os.close(fd)


def create_options_app(
    journal,
    population_id,
    password_file,
    *,
    clock=utc_now,
    comparison_file=None,
    mixed=False,
    review_at=None,
):
    if review_at is not None:
        from app.options.engine import clock as checked_clock

        if not mixed or not population_id.startswith("ui-review-") or clock is not utc_now:
            raise ValueError("Frozen review requires an explicit isolated mixed UI population")
        review_at = checked_clock(datetime.fromisoformat(review_at))
        if review_at > utc_now():
            raise ValueError("Review timestamp must be historical")
        clock = lambda: review_at
    if not Path(password_file).is_absolute():
        raise ValueError("Absolute private observer password path required")
    password(password_file)
    if mixed and comparison_file is not None:
        raise ValueError("Legacy comparison files cannot label mixed-account returns")
    from app.mixed.observer import MixedObserver

    observer_class = MixedObserver if mixed else OptionObserver
    observer = observer_class(journal, population_id, clock=clock, comparison_file=comparison_file)
    app = FastAPI(title="Options PAPER observer", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def privacy(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            }
        )
        return response

    def authenticate(credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)]):
        try:
            secret = password(password_file)
        except (OSError, ValueError):
            raise HTTPException(503, "Observer authentication unavailable") from None
        if not credentials or not (
            compare_digest(credentials.username.encode(), b"trader")
            and compare_digest(credentials.password.encode(), secret)
        ):
            raise HTTPException(
                401,
                "Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="Options PAPER observer"'},
            )

    @app.get("/healthz")
    def health():
        return {"status": "OK", "service": "options-observer", "trader_health": "NOT_CHECKED"}

    @app.get("/desk.js", dependencies=[Depends(authenticate)])
    def desk_script():
        return Response(
            templates.env.get_template("options_desk_script.html").render()
            + (templates.env.get_template("mixed_desk_script.html").render() if mixed else ""),
            media_type="application/javascript",
        )

    @app.get("/api/mixed" if mixed else "/api/options", dependencies=[Depends(authenticate)])
    def api(
        limit: int = Query(25, ge=1, le=100),
        before: int | None = Query(None, ge=1),
        family: Literal["ALL", "DEGEN", "SWING", "SCOPE"] = "ALL",
    ):
        if mixed and family != "ALL":
            raise HTTPException(422, "Mixed desk shows the common account; use ALL")
        data = observer.report(limit=limit, before=before, family=family)
        if review_at is not None:
            data["review"] = {"mode": "FROZEN_OFFLINE_UI_FIXTURE", "as_of": review_at.isoformat()}
        return JSONResponse(data, status_code=503 if data["status"] == "UNAVAILABLE" else 200)

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authenticate)])
    def index(
        request: Request,
        limit: int = Query(25, ge=1, le=100),
        before: int | None = Query(None, ge=1),
        family: Literal["ALL", "DEGEN", "SWING", "SCOPE"] = "ALL",
        refresh: bool = False,
    ):
        if mixed and family != "ALL":
            raise HTTPException(422, "Mixed desk shows the common account; use ALL")
        data = observer.report(limit=limit, before=before, family=family)
        if review_at is not None:
            data["review"] = {"mode": "FROZEN_OFFLINE_UI_FIXTURE", "as_of": review_at.isoformat()}
        from app.options.comparison_view import chart_data

        return templates.TemplateResponse(
            request,
            "mixed_desk.html" if mixed else "options.html",
            {
                "data": data,
                "view": mixed_view(data) if mixed else None,
                "auto_refresh": refresh and before is None and review_at is None,
                "family": family,
                "comparison_chart": chart_data(
                    data.get("comparison", {"status": "NOT_CONFIGURED"})
                ),
            },
            status_code=503 if data["status"] == "UNAVAILABLE" else 200,
        )

    return app
