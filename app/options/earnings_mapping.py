"""Original company earnings observations; no catalyst clearance or entry authority."""

import hashlib
from collections import Counter, defaultdict
from datetime import date, timedelta

from pydantic import Field

from app.options.models import Money, OptionRecord, Symbol
from app.options.read_gateway import MAX_SAMPLE_BYTES, encoded
from app.options.read_mapping import instant

SCHEMA_SHA256 = "847030468e36a4e253757079040089e987603322e0113eeaf643cf6010b42e27"


class EarningsEPS(OptionRecord):
    actual: Money | None
    estimate: Money | None


class EarningsReport(OptionRecord):
    date: date | None
    timing: str | None = Field(max_length=32)
    verified: bool = Field(strict=True)


class EarningsRow(OptionRecord):
    symbol: Symbol
    year: int = Field(strict=True, ge=1900, le=2200)
    quarter: int = Field(strict=True, ge=1, le=4)
    eps: EarningsEPS
    report: EarningsReport | None


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def map_calendar(receipt):
    """Map exactly one reviewed unfiltered window, preserving every original row."""
    if (receipt.get("tool") != "get_earnings_calendar"
            or receipt.get("metadata_sha256") != SCHEMA_SHA256):
        raise ValueError("Reviewed earnings receipt required")
    arguments = receipt.get("arguments", {})
    if (set(arguments) != {"start_date", "days"}
            or type(arguments["days"]) is not int or arguments["days"] not in (1, 7)):
        raise ValueError("Exact reviewed unfiltered earnings window required")
    start = date.fromisoformat(arguments["start_date"])
    end = start + timedelta(days=arguments["days"])
    attempted, received = instant(receipt["attempted_at"]), instant(receipt["received_at"])
    if received < attempted:
        raise ValueError("Earnings receipt clock regressed")
    result = {
        "version": "robinhood-company-earnings-v1", "source": "robinhood-mcp",
        "schema_sha256": SCHEMA_SHA256, "receipt_sha256": digest(receipt),
        "window_start": start.isoformat(), "window_end_exclusive": end.isoformat(),
        "received_at": received.isoformat(), "provider_updated_at": None,
        "entitlement": "UNKNOWN", "status": "UNAVAILABLE", "records": [],
        "issues": [], "complete_catalyst_coverage": False,
        "trading_ready": False, "execution_authority": False, "live_enabled": False,
    }
    if receipt.get("completed") is not True:
        result["issues"] = ["EARNINGS_CAPTURE_FAILED"]
        return result
    raw = receipt.get("raw")
    if (receipt.get("output_schema_validated") is not True or not isinstance(raw, dict)
            or len(encoded(raw)) > MAX_SAMPLE_BYTES or raw.get("isError", False) is not False):
        raise ValueError("Successful bounded validated earnings response required")
    structured = raw.get("structuredContent")
    if not isinstance(structured, dict) or not isinstance(structured.get("data"), dict):
        raise ValueError("Structured earnings data required")
    data = structured["data"]
    if set(data) != {"results"}:
        raise ValueError("Unexpected earnings data fields")
    rows = data["results"]
    if rows is None:
        result["issues"] = ["EARNINGS_RESULTS_NULL"]
        return result
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("Bounded earnings records required")
    by_identity = defaultdict(list)
    for ordinal, original in enumerate(rows):
        record = {"ordinal": ordinal, "original_row_sha256": digest(original), "issues": []}
        if original is None:
            record.update(observation=None, issues=["NULL_EARNINGS_ROW"])
        else:
            value = EarningsRow.model_validate(original)
            report = value.report
            record.update(observation=value.model_dump(mode="json"),
                          release_status="REPORTED" if value.eps.actual is not None else "ACTUAL_EPS_UNAVAILABLE")
            if report is None or report.date is None:
                record["issues"].append("REPORT_DATE_UNAVAILABLE")
            elif not start <= report.date < end:
                record["issues"].append("REPORT_OUTSIDE_REQUESTED_WINDOW")
            if report is None or report.timing not in ("am", "pm"):
                record["issues"].append("REPORT_TIMING_UNKNOWN")
            if report is not None and not report.verified:
                record["issues"].append("REPORT_DATE_TENTATIVE")
            by_identity[(value.symbol, value.year, value.quarter)].append(record)
        result["records"].append(record)
    for records in by_identity.values():
        if len(records) > 1:
            issue = ("CONFLICTING_EVENT_IDENTITY" if len({r["original_row_sha256"] for r in records}) > 1
                     else "REPEATED_EVENT_IDENTITY")
            for record in records:
                record["issues"].append(issue)
    result["issues"] = sorted({i for r in result["records"] for i in r["issues"]})
    result["status"] = "MAPPED_WITH_ISSUES" if result["issues"] else "MAPPED"
    return result


def mapping_summary(mapped):
    """Compact report; normalized records are available through the offline export."""
    rows = mapped["records"]
    observations = [r["observation"] for r in rows if r["observation"] is not None]
    counts = Counter(i for row in rows for i in row["issues"])
    return {k: mapped[k] for k in (
        "version", "status", "window_start", "window_end_exclusive", "received_at",
        "provider_updated_at", "receipt_sha256", "entitlement", "issues",
        "complete_catalyst_coverage", "trading_ready", "execution_authority", "live_enabled",
    )} | {
        "record_count": len(rows) if mapped["status"] != "UNAVAILABLE" else None,
        "unique_company_quarters": len({(r["symbol"], r["year"], r["quarter"]) for r in observations}),
        "issue_counts": dict(sorted(counts.items())), "records_sha256": digest(rows),
        "reported_records": sum(r.get("release_status") == "REPORTED" for r in rows),
        "actual_eps_missing_records": sum(r.get("release_status") == "ACTUAL_EPS_UNAVAILABLE" for r in rows),
    }
