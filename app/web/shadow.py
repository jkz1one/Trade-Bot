"""Private observer application; deliberately separate from the PAPER control app."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.domain.models import utc_now
from app.web.shadow_data import read_only_engine, stored_snapshot

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
basic = HTTPBasic(auto_error=False)


def _password(settings):
    if not settings.dashboard_password_file:
        raise RuntimeError("Dashboard password file is required")
    try:
        password = Path(settings.dashboard_password_file).expanduser().read_text().strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("Dashboard password file cannot be read") from exc
    if len(password) < 24 or any(c.isspace() for c in password):
        raise RuntimeError("Dashboard password must be at least 24 characters without whitespace")
    return password


def create_shadow_app(settings=None, *, clock=utc_now):
    settings = settings or Settings()
    if settings.normalized_mode != "SHADOW" or settings.live_enabled:
        raise RuntimeError("The observer requires SHADOW with LIVE disabled")
    _password(settings)  # Refuse startup without authentication; no default credentials.
    path, engine = read_only_engine(settings.robinhood_db_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(
        title="Trade-Bot SHADOW observer",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            }
        )
        return response

    def authenticate(credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)]):
        try:
            password = _password(settings)
        except RuntimeError:
            raise HTTPException(503, "Observer authentication unavailable") from None
        if not credentials or not (
            compare_digest(credentials.username.encode(), b"trader")
            and compare_digest(credentials.password.encode(), password.encode())
        ):
            raise HTTPException(
                401,
                "Authentication required",
                headers={"WWW-Authenticate": 'Basic realm="Trade-Bot"'},
            )

    def report(limit, before):
        try:
            return stored_snapshot(
                path,
                engine,
                benchmark_symbol=settings.benchmark_symbol,
                now=clock(),
                limit=limit,
                before=before,
            )
        except (SQLAlchemyError, ValueError, KeyError, TypeError, OSError):
            return {
                "status": "UNAVAILABLE",
                "reason": "HISTORY_UNAVAILABLE",
                "network_calls": False,
            }

    @app.get("/healthz")
    def health():
        # Observer process readiness is separate from worker/data/model health.
        return {"status": "OK", "service": "shadow-observer"}

    @app.get("/api/shadow", dependencies=[Depends(authenticate)])
    def api(limit: int = Query(25, ge=1, le=100), before: int | None = Query(None, ge=1)):
        from fastapi.responses import JSONResponse

        data = report(limit, before)
        return JSONResponse(data, status_code=503 if data["status"] == "UNAVAILABLE" else 200)

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authenticate)])
    def index(
        request: Request,
        limit: int = Query(25, ge=1, le=100),
        before: int | None = Query(None, ge=1),
        refresh: bool = True,
    ):
        data = report(limit, before)
        return templates.TemplateResponse(
            request,
            "shadow.html",
            {
                "data": data,
                "auto_refresh": refresh and before is None,
                "limit": limit,
            },
            status_code=503 if data["status"] == "UNAVAILABLE" else 200,
        )

    return app
