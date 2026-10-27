"""Documented source adapters. IO is only in fetch(); parsing is independently testable."""

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib.metadata import version
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as HttpRequest
from zoneinfo import ZoneInfo

from app.events.models import Coverage, Event, MarketSample, Session, Volatility
from app.options.engine import fingerprint
from app.robinhood.schedule import XNYSCalendar

BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
VIX_URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
MAX_RESPONSE = 8 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Source redirect requires review")


def get(url, headers=None, *, timeout=10):
    """Bounded GET; no retries, redirects or credential-bearing URL logging."""
    req = HttpRequest(url, headers={"User-Agent": "Trade-Bot-event-research/1", **(headers or {})})
    with build_opener(NoRedirect).open(req, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError("Source response too large")
        return body.decode("utf-8-sig")


def local_time(value, zone):
    """Reject nonexistent/ambiguous wall times instead of silently choosing a DST fold."""
    tz = ZoneInfo(zone)
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")  # noqa: DTZ007 - explicit DST validation below
    first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive
    ):
        raise ValueError("Ambiguous or nonexistent event time")
    return first.astimezone(UTC)


def ical_time(prop):
    params, value = prop
    zone = params.get("TZID", "UTC" if value.endswith("Z") else None)
    if params.get("VALUE") == "DATE" or len(value) == 8:
        # No false exact announcement time for an all-day entry.
        zone = zone or "America/New_York"
        start = datetime.combine(date.fromisoformat(value), time(), ZoneInfo(zone))
        return start.astimezone(UTC), zone, "DATE"
    if zone is None:
        raise ValueError("Floating iCalendar time unsupported")
    return local_time(value.removesuffix("Z"), zone), zone, "EXACT"


@dataclass(frozen=True)
class SourceSpec:
    source: str
    source_version: str
    dataset: str
    starts_at: datetime
    ends_at: datetime
    symbols: tuple[str, ...] = ()
    ttl_seconds: int = 21600

    def coverage(self, now, status="PARTIAL", issues=()):
        return Coverage(
            source=self.source,
            source_version=self.source_version,
            dataset=self.dataset,
            scope="SYMBOL" if self.symbols else "MARKET",
            symbols=self.symbols,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            checked_at=now,
            fresh_until=now + timedelta(seconds=self.ttl_seconds),
            status=status,
            issues=issues,
        )


class ICalendarAdapter:
    """Free BLS/BEA calendars, scoped to their own releases, never all-macro clearance.

    Retains every release; provisional classification treats listed releases as
    high impact. Unknown/recurring schemas fail the collection, not silently skip.
    """

    def __init__(self, spec, url):
        if url not in {BLS_URL, BEA_URL}:
            raise ValueError("Unreviewed iCalendar endpoint")
        self.spec, self.url = spec, url

    def fetch(self):
        return get(self.url)

    def parse(self, raw, received_at):
        if (
            len(raw.encode()) > MAX_RESPONSE
            or "BEGIN:VCALENDAR" not in raw
            or "END:VCALENDAR" not in raw
        ):
            raise ValueError("Complete bounded iCalendar required")
        lines = re.sub(r"\r?\n[ \t]", "", raw).splitlines()
        records, current = [], None
        for line in lines:
            if line == "BEGIN:VEVENT":
                if current is not None:
                    raise ValueError("Nested event")
                current = {}
            elif line == "END:VEVENT":
                if current is None:
                    raise ValueError("Unmatched event end")
                records.append(current)
                current = None
            elif current is not None and line:
                key, value = line.split(":", 1)
                parts = key.split(";")
                if parts[0] in {"RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"}:
                    raise ValueError("Recurring events require expanded reviewed records")
                if parts[0] in current:
                    raise ValueError("Duplicate event property")
                current[parts[0]] = (
                    {k: v.strip('"') for k, v in (p.split("=", 1) for p in parts[1:])},
                    value,
                )
        if current is not None or not records:
            raise ValueError("Truncated or empty calendar")
        events = []
        for r in records:
            start, zone, precision = ical_time(r["DTSTART"])
            if "DTEND" in r:
                end = ical_time(r["DTEND"])[0]
            elif precision == "DATE":
                end = (start.astimezone(ZoneInfo(zone)) + timedelta(days=1)).astimezone(UTC)
            elif "DURATION" in r:
                duration = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", r["DURATION"][1])
                if not duration or not any(duration.groups()):
                    raise ValueError("Unsupported event duration")
                h, m, s = (int(v or 0) for v in duration.groups())
                end = start + timedelta(hours=h, minutes=m, seconds=s)
            else:
                end = start
            source_at = (
                ical_time(r["LAST-MODIFIED"] if "LAST-MODIFIED" in r else r["DTSTAMP"])[0]
                if ("LAST-MODIFIED" in r or "DTSTAMP" in r)
                else None
            )
            uid = r["UID"][1]
            title = r["SUMMARY"][1].replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
            events.append(
                Event(
                    source=self.spec.source,
                    source_version=self.spec.source_version,
                    event_id=uid,
                    revision=r.get("SEQUENCE", ({}, "0"))[1],
                    revision_sequence=int(r.get("SEQUENCE", ({}, "0"))[1]),
                    category=self.spec.dataset,
                    title=title,
                    scope="MARKET",
                    source_at=source_at,
                    received_at=received_at,
                    starts_at=start,
                    ends_at=end,
                    timezone=zone,
                    precision=precision,
                    importance="HIGH",
                    status=r.get("STATUS", ({}, "SCHEDULED"))[1].replace("CONFIRMED", "SCHEDULED"),
                    complete=source_at is not None and precision == "EXACT",
                    evidence_ref=self.url + "#" + uid,
                )
            )
        # Feed bounds are not an attestation that omitted events do not exist.
        return {
            "events": [e.model_dump(mode="json") for e in events],
            "coverage": [
                self.spec.coverage(
                    received_at, issues=("PROVIDER_COMPLETENESS_UNATTESTED",)
                ).model_dump(mode="json")
            ],
        }


class TradingEconomicsAdapter:
    """Broad scheduled US releases; requires reviewed calendar subscription/API key.

    LastUpdate and event Date are documented UTC. No category/name whitelist.
    Distinct CalendarId values preserve policy decisions and press conferences.
    """

    def __init__(self, spec, api_key=None):
        self.spec, self.api_key = spec, api_key

    def fetch(self):
        if not self.api_key:
            raise PermissionError("Trading Economics calendar credential required")
        a, b = self.spec.starts_at.date(), self.spec.ends_at.date()
        return get(
            f"https://api.tradingeconomics.com/calendar/country/united%20states/{a}/{b}?f=json",
            {"Authorization": self.api_key},
        )

    def parse(self, raw, received_at):
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) >= 1000:
            raise ValueError("Calendar response invalid or at provider truncation limit")
        events = []
        for r in rows:
            if r["Country"] != "United States":
                raise ValueError("Unexpected calendar country")
            start = datetime.fromisoformat(r["Date"])
            start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
            source_at = datetime.fromisoformat(r["LastUpdate"]) if r.get("LastUpdate") else None
            if source_at is not None and source_at.tzinfo is None:
                source_at = source_at.replace(tzinfo=UTC)
            exact = str(r.get("DateSpan")) == "0"
            end = start if exact else start + timedelta(days=1)
            events.append(
                Event(
                    source=self.spec.source,
                    source_version=self.spec.source_version,
                    event_id=str(r["CalendarId"]),
                    revision=r.get("LastUpdate") or "unknown",
                    category="macro." + re.sub(r"[^a-z0-9]+", "_", r["Category"].lower()),
                    title=r["Event"],
                    scope="MARKET",
                    source_at=source_at,
                    received_at=received_at,
                    starts_at=start,
                    ends_at=end,
                    timezone="UTC",
                    precision="EXACT" if exact else "RANGE",
                    importance="HIGH" if int(r["Importance"]) == 3 else "MEDIUM",
                    complete=source_at is not None and exact,
                    evidence_ref="te:calendar:" + str(r["CalendarId"]),
                )
            )
        return {
            "events": [e.model_dump(mode="json") for e in events],
            "coverage": [
                self.spec.coverage(
                    received_at, issues=("PROVIDER_COVERAGE_ACCEPTANCE_PENDING",)
                ).model_dump(mode="json")
            ],
        }


class FinnhubEarningsAdapter:
    """Company earnings date/time-bucket interface; missing update clocks stay unknown."""

    def __init__(self, spec, api_key=None):
        if len(spec.symbols) != 1:
            raise ValueError("One explicit company symbol per request")
        self.spec, self.api_key = spec, api_key

    def fetch(self):
        if not self.api_key:
            raise PermissionError("Finnhub earnings API key and plan access required")
        query = urlencode(
            {
                "from": self.spec.starts_at.date().isoformat(),
                "to": self.spec.ends_at.date().isoformat(),
                "symbol": self.spec.symbols[0],
            }
        )
        return get(
            "https://finnhub.io/api/v1/calendar/earnings?" + query,
            {"X-Finnhub-Token": self.api_key},
        )

    def parse(self, raw, received_at):
        rows = json.loads(raw)["earningsCalendar"]
        if not isinstance(rows, list):
            raise TypeError("Earnings list required")
        events = []
        for r in rows:
            if r["symbol"] != self.spec.symbols[0]:
                raise ValueError("Company identity mismatch")
            day = date.fromisoformat(r["date"])
            start = datetime.combine(day, time(), ZoneInfo("America/New_York"))
            # BMO/AMC are buckets, not exact times. Use the entire local date;
            # retain the original bucket in raw evidence rather than invent 08:00.
            uid = f"{r['symbol']}:{r['year']}:{r['quarter']}"
            events.append(
                Event(
                    source=self.spec.source,
                    source_version=self.spec.source_version,
                    event_id=uid,
                    revision=fingerprint(r),
                    category="company.earnings",
                    title=r["symbol"] + " earnings",
                    scope="SYMBOL",
                    symbols=self.spec.symbols,
                    source_at=None,
                    received_at=received_at,
                    starts_at=start,
                    ends_at=start + timedelta(days=1),
                    timezone="America/New_York",
                    precision="DATE",
                    importance="HIGH",
                    status="TENTATIVE",
                    complete=False,
                    evidence_ref="finnhub:earnings:" + uid,
                )
            )
        return {
            "events": [e.model_dump(mode="json") for e in events],
            "coverage": [
                self.spec.coverage(
                    received_at, issues=("NO_PROVIDER_UPDATE_TIMESTAMP", "EARNINGS_ONLY")
                ).model_dump(mode="json")
            ],
        }


class CboeDailyAdapter:
    def __init__(self, spec):
        self.spec = spec

    def fetch(self):
        return get(VIX_URL)

    def parse(self, raw, received_at):
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows:
            raise ValueError("Empty volatility history")

        def day_of(row):
            month, day, year = map(int, row["DATE"].split("/"))
            return date(year, month, day)

        r = max(rows, key=day_of)
        day = day_of(r)
        if day >= received_at.astimezone(ZoneInfo("America/New_York")).date():
            raise ValueError("Daily publication availability unverified for same/future date")
        v = Volatility(
            source=self.spec.source,
            source_version=self.spec.source_version,
            symbol="VIX",
            observed_date=day,
            value=r["CLOSE"],
            received_at=received_at,
            evidence_ref=VIX_URL,
        )
        return {
            "volatility": [v.model_dump(mode="json")],
            "coverage": [
                self.spec.coverage(received_at, issues=("DAILY_CLOSE_NOT_INTRADAY",)).model_dump(
                    mode="json"
                )
            ],
        }


def sessions(start: date, end: date, *, received_at):
    """Materialize actual XNYS dates in a background worker, including early closes."""
    cal = XNYSCalendar().calendar
    if start > end or (end - start).days > 366:
        raise ValueError("Bounded session coverage required")
    days = cal.sessions_in_range(start.isoformat(), end.isoformat())
    values = [
        Session(
            day=d.date(),
            opens_at=cal.session_open(d).to_pydatetime(),
            closes_at=cal.session_close(d).to_pydatetime(),
        )
        for d in days
    ]
    tz = ZoneInfo("America/New_York")
    spec = SourceSpec(
        "exchange-calendars",
        version("exchange-calendars"),
        "session.xnys",
        datetime.combine(start, time(), tz),
        datetime.combine(end + timedelta(days=1), time(), tz),
        ttl_seconds=86400,
    )
    return {
        "sessions": [s.model_dump(mode="json") for s in values],
        "coverage": [spec.coverage(received_at, "COMPLETE").model_dump(mode="json")],
    }


def native_sample(quote, *, evidence_ref, reference=None):
    """Reuse existing normalized stock/option/underlying evidence, with original clocks.

    No provider read, entitlement promotion or manufactured missing size.
    """
    from app.mixed.stock_models import StockQuote
    from app.options.models import OptionQuote, UnderlyingQuote

    if isinstance(quote, OptionQuote):
        identity, symbol, asset = (
            quote.instrument.instrument_id,
            quote.instrument.contract.underlying,
            "OPTION",
        )
    elif isinstance(quote, StockQuote):
        identity, symbol, asset = quote.instrument.instrument_id, quote.instrument.symbol, "STOCK"
    elif isinstance(quote, UnderlyingQuote):
        identity, symbol, asset = (
            quote.symbol,
            quote.symbol,
            "INDEX" if quote.symbol == "SPX" else "STOCK",
        )
    else:
        raise TypeError("Supported native quote required")
    previous = None
    if reference is not None:
        previous = native_sample(reference, evidence_ref=evidence_ref)
        if previous.instrument_id != identity or previous.source != quote.source:
            raise ValueError("Price reference identity/source mismatch")
    return MarketSample(
        source=quote.source,
        source_version="native-quote-v1",
        evidence_ref=evidence_ref,
        instrument_id=identity,
        symbol=symbol,
        asset=asset,
        source_at=quote.source_at,
        received_at=quote.received_at,
        bid=quote.bid,
        ask=quote.ask,
        bid_size=getattr(quote, "bid_size", None),
        ask_size=getattr(quote, "ask_size", None),
        entitlement=quote.entitlement,
        complete=quote.complete,
        reference_at=previous.source_at if previous else None,
        reference_price=(previous.bid + previous.ask) / 2
        if previous
        and previous.bid
        and previous.ask
        and previous.ask >= previous.bid
        and previous.complete
        and previous.entitlement == "REALTIME"
        and previous.source_at <= previous.received_at
        else None,
    )
