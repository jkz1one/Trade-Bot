"""Private options observer factory. Only persisted reads, no trading routes."""

import os
import stat
from pathlib import Path
from secrets import compare_digest
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.domain.models import utc_now
from app.options.observer import OptionObserver

basic = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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


def create_options_app(journal, population_id, password_file, *, clock=utc_now):
    if not Path(password_file).is_absolute():
        raise ValueError("Absolute private observer password path required")
    password(password_file)
    observer = OptionObserver(journal, population_id, clock=clock)
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
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
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

    @app.get("/api/options", dependencies=[Depends(authenticate)])
    def api(
        limit: int = Query(25, ge=1, le=100),
        before: int | None = Query(None, ge=1),
        family: Literal["ALL", "DEGEN", "SWING", "SCOPE"] = "ALL",
    ):
        data = observer.report(limit=limit, before=before, family=family)
        return JSONResponse(data, status_code=503 if data["status"] == "UNAVAILABLE" else 200)

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authenticate)])
    def index(
        request: Request,
        limit: int = Query(25, ge=1, le=100),
        before: int | None = Query(None, ge=1),
        family: Literal["ALL", "DEGEN", "SWING", "SCOPE"] = "ALL",
        refresh: bool = False,
    ):
        data = observer.report(limit=limit, before=before, family=family)
        return templates.TemplateResponse(
            request,
            "options.html",
            {"data": data, "auto_refresh": refresh and before is None, "family": family},
            status_code=503 if data["status"] == "UNAVAILABLE" else 200,
        )

    return app
