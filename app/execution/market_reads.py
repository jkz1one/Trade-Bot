"""Opt-in market-only Robinhood reads for an isolated, source-bound PAPER feed."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator

from app.domain.models import Candidate, MarketPacket, utc_now
from app.execution.engine import _clock
from app.execution.models import Contract
from app.execution.process import _cleanup
from app.execution.quote_feed import DurableQuoteFeed

MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 256 * 1024


class MarketReadAlreadyRunning(RuntimeError):
    pass


@contextmanager
def market_read_lease(path):
    fd = os.open(
        str(path) + ".market-read.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
        ):
            raise ValueError("Private current-owner market reader lock required")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MarketReadAlreadyRunning("A market reader already owns this feed") from None
        yield
    finally:
        os.close(fd)


class MarketReadPolicy(Contract):
    provider: Literal["robinhood-market-read-v1"] = "robinhood-market-read-v1"
    endpoint: Literal["https://agent.robinhood.com/mcp/trading"] = (
        "https://agent.robinhood.com/mcp/trading"
    )
    redirect_uri: Literal["http://127.0.0.1:8765/callback"] = "http://127.0.0.1:8765/callback"
    oauth_file: str = Field(min_length=1, max_length=4096)
    interval: Literal["5minute"] = "5minute"
    lookback_days: Literal[7] = 7
    timeout_seconds: float = Field(default=30, gt=0, le=30)
    max_age_seconds: float = Field(default=90, gt=0, le=90)

    @field_validator("oauth_file")
    @classmethod
    def absolute_path(cls, value):
        if not Path(value).is_absolute() or "\x00" in value:
            raise ValueError("An explicit absolute OAuth file path is required")
        return value


def source_hash(policy):
    return hashlib.sha256(
        json.dumps(policy.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()


def private_oauth(path):
    """Bounded existing credentials, no enrollment/login or credential echo."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
            or not 0 < info.st_size <= 64 * 1024
        ):
            raise ValueError("Private bounded current-owner OAuth file required")
        data = os.read(fd, 64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise ValueError("OAuth file exceeded bound")
        payload = json.loads(data)
        if (
            not isinstance(payload, dict)
            or not payload.get("tokens")
            or not payload.get("client_info")
        ):
            raise ValueError("Existing OAuth authorization required")
        return payload
    finally:
        os.close(fd)


class MarketReadRequest(Contract):
    policy: MarketReadPolicy
    feed_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    symbols: list[str] = Field(min_length=1, max_length=20)
    started_at: datetime
    parent_pid: int = Field(gt=0)
    deadline_monotonic: float = Field(gt=0)

    @field_validator("symbols")
    @classmethod
    def universe(cls, value):
        if len(value) != len(set(value)) or any(
            not s.isascii() or not s.isalpha() or not s.isupper() or len(s) > 5 for s in value
        ):
            raise ValueError("An explicit unique equity universe is required")
        return value


class MarketReadResult(Contract):
    feed_id: str
    request_id: str
    source_hash: str
    collected_at: datetime
    candidates: list[Candidate] = Field(min_length=1, max_length=20)
    regime: Literal["bullish", "bearish", "mixed"]


async def _read(request):
    payload = request.model_dump_json().encode()
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Market read request exceeded protocol limit")
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.execution.market_read_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={
                k: os.environ[k]
                for k in ("PATH", "LANG", "LC_ALL", "PYTHONPATH")
                if k in os.environ
            },
        )
    )
    process = None
    try:
        async with asyncio.timeout(max(0, request.deadline_monotonic - time.monotonic())):
            process = await asyncio.shield(spawn)
            process.stdin.write(payload)
            await process.stdin.drain()
            process.stdin.close()
            data = bytearray()
            while chunk := await process.stdout.read(4096):
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ValueError("Market read response exceeded protocol limit")
            await process.wait()
            if process.returncode:
                raise ValueError("Market read process failed")
            return MarketReadResult.model_validate_json(data)
    finally:
        if process is None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
            if not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            await _cleanup(process)


async def collect_once(feed, *, clock=utc_now):
    """One bounded safe read, then atomic publication. No model/engine/venue handle."""
    if type(feed) is not DurableQuoteFeed or feed.source is None:
        raise ValueError("A separately initialized sourced PAPER feed is required")
    with market_read_lease(feed.path):
        return await _collect_owned(feed, clock=clock)


async def _collect_owned(feed, *, clock):
    policy = MarketReadPolicy.model_validate(feed.source)
    private_oauth(policy.oauth_file)
    started = clock()
    _clock(started)
    request = MarketReadRequest(
        policy=policy,
        feed_id=feed.feed_id,
        request_id=uuid4().hex,
        symbols=feed.symbols,
        started_at=started,
        parent_pid=os.getpid(),
        deadline_monotonic=time.monotonic() + policy.timeout_seconds,
    )
    result = await _read(request)
    completed = clock()
    _clock(completed)
    if (
        result.feed_id != request.feed_id
        or result.request_id != request.request_id
        or result.source_hash != source_hash(policy)
        or not started <= result.collected_at <= completed
        or (completed - result.collected_at).total_seconds() > policy.max_age_seconds
        or {c.quote.symbol for c in result.candidates} != set(feed.symbols)
        or len(result.candidates) != len(feed.symbols)
    ):
        raise ValueError("Market read lineage, collection clock or universe mismatch")
    for candidate in result.candidates:
        _clock(candidate.quote.timestamp)
        if (
            not 0
            <= (completed - candidate.quote.timestamp).total_seconds()
            <= policy.max_age_seconds
            or candidate.quote.timestamp > result.collected_at
            or candidate.quote.ask < candidate.quote.bid
        ):
            raise ValueError("Market read quote is stale, future or crossed")
    packet = MarketPacket(
        as_of=result.collected_at,
        candidates=result.candidates,
        regime=result.regime,
        account={"equity": 0, "cash": 0, "buying_power": 0, "high_watermark": 0},
    )
    sequence = feed.publish(request.request_id, packet, source=policy.model_dump(mode="json"))
    return {
        "status": "PUBLISHED",
        "mode": "FIXTURE_PAPER",
        "provider": policy.provider,
        "feed_sequence": sequence,
        "candidate_count": len(result.candidates),
        "live_enabled": False,
    }
