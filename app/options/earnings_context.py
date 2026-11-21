"""Session-bound company calendar observations, separate from strategy authority."""

from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.options.earnings_mapping import digest, map_calendar, mapping_summary
from app.options.models import OptionRecord
from app.options.read_gateway import encoded
from app.options.read_mapping import instant

DIGEST = r"^[a-f0-9]{64}$"


class CompanyEarningsObservation(OptionRecord):
    version: Literal["company-earnings-observation-v1"] = "company-earnings-observation-v1"
    target_session: date
    capture_sha256: str = Field(pattern=DIGEST)
    receipt_sha256: str = Field(pattern=DIGEST)
    records_sha256: str = Field(pattern=DIGEST)
    received_at: datetime
    window_start: date
    window_end_exclusive: date
    record_count: int = Field(strict=True, ge=0, le=2000)
    unique_company_quarters: int = Field(strict=True, ge=0, le=2000)
    reported_records: int = Field(strict=True, ge=0, le=2000)
    actual_eps_missing_records: int = Field(strict=True, ge=0, le=2000)
    issue_counts: dict[str, Annotated[int, Field(strict=True, ge=0, le=2000)]] = Field(max_length=16)
    coverage: Literal["PARTIAL_COMPANY_CALENDAR", "OUTSIDE_REQUESTED_WINDOW"]
    source: Literal["robinhood-mcp"] = "robinhood-mcp"
    provider_updated_at: None = None
    entitlement: Literal["UNKNOWN"] = "UNKNOWN"
    complete_catalyst_coverage: Literal[False] = False
    execution_authority: Literal[False] = False
    trading_ready: Literal[False] = False
    live_enabled: Literal[False] = False

    @model_validator(mode="after")
    def bounded(self):
        instant(self.received_at)
        if ((self.window_end_exclusive - self.window_start).days not in (1, 7)
                or self.unique_company_quarters > self.record_count
                or self.reported_records + self.actual_eps_missing_records > self.record_count
                or any(type(v) is not int or not 0 <= v <= self.record_count
                       for v in self.issue_counts.values())):
            raise ValueError("Invalid company earnings observation coverage")
        expected = ("PARTIAL_COMPANY_CALENDAR"
                    if self.window_start <= self.target_session < self.window_end_exclusive
                    else "OUTSIDE_REQUESTED_WINDOW")
        if self.coverage != expected:
            raise ValueError("Company calendar coverage does not match its requested window")
        return self


class CompanyEarningsBinding(OptionRecord):
    """Retain the original bounded receipt in the reviewed session policy."""
    version: Literal["company-earnings-binding-v1"] = "company-earnings-binding-v1"
    target_session: date
    capture_sha256: str = Field(pattern=DIGEST)
    receipt: dict

    @model_validator(mode="after")
    def original(self):
        if len(encoded(self.receipt)) > 160 * 1024:
            raise ValueError("Bounded original company earnings receipt required")
        if map_calendar(self.receipt)["status"] == "UNAVAILABLE":
            raise ValueError("Mapped original company earnings receipt required")
        return self

    def observation(self):
        summary = mapping_summary(map_calendar(self.receipt))
        fields = {key: summary[key] for key in (
            "receipt_sha256", "records_sha256", "received_at", "window_start",
            "window_end_exclusive", "record_count", "unique_company_quarters",
            "reported_records", "actual_eps_missing_records", "issue_counts",
        )}
        covered = summary["window_start"] <= self.target_session.isoformat() < summary["window_end_exclusive"]
        return CompanyEarningsObservation(
            target_session=self.target_session, capture_sha256=self.capture_sha256,
            coverage="PARTIAL_COMPANY_CALENDAR" if covered else "OUTSIDE_REQUESTED_WINDOW",
            **fields,
        )


def from_probe(artifact, target):
    """Validate original capture bindings; never import a derived export as original."""
    from app.options.input_probe import validate_observations
    from app.options.read_capture import CaptureResult

    if len(encoded(artifact)) > 1024 * 1024 or artifact.get("operation") != "input-probe":
        raise ValueError("Bounded original input probe required")
    result = CaptureResult.model_validate(artifact["result"])
    if result.operation != "INPUT_PROBE":
        raise ValueError("Original input probe required")
    validate_observations(result.observations, result.started_at)
    matches = [r for r in result.observations if r["tool"] == "get_earnings_calendar"]
    if len(matches) != 1:
        raise ValueError("Exactly one original earnings receipt required")
    receipt = matches[0]
    if not result.started_at <= instant(receipt["attempted_at"]) <= instant(receipt["received_at"]) <= result.collected_at:
        raise ValueError("Original earnings capture clocks required")
    return CompanyEarningsBinding(target_session=target, capture_sha256=digest(artifact), receipt=receipt)


def for_delivery(binding, now):
    if binding is None or binding.target_session != instant(now).astimezone(ZoneInfo("America/New_York")).date():
        return None
    observation = binding.observation()
    if observation.received_at > instant(now):
        raise ValueError("Company earnings were not available at delivery")
    return observation
