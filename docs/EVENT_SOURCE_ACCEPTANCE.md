# Public event-source capture and replay

This slice starts from `376652dd827351c1f61453f7d5934845020eeb43` on
`feat/event-awareness-baseline`. Remote base advanced to
`988ff86ca2bf549215fb19624fd0b43f2431e1bb`; reviewed its Swing daily/half-hour history
proof changes. During verification, `f25efaa0ee848ae6242783a7c341d54b199feb23`
added further proof-only daily-placeholder diagnostics; reviewed and incorporated
that latest base **into this feature only**. It changes no
native application contracts. The source-of-truth conflict was resolved by
preserving the complete latest base status beneath the feature history.

## Actual workspace evidence

These are real public responses, distinct from synthetic unit fixtures. The
original receipts are retained in `tests/fixtures/event_sources/`; tests replay
these files offline and never insert them into an operational event store.

| Source | Receipt (UTC) | Result | Remaining limits |
| --- | --- | --- | --- |
| BEA | 2026-10-28 04:00:21.815614 | 168 events parsed | Agency-only, PARTIAL coverage; not all high-impact macro |
| Daily VIX | 2026-10-28 04:00:26.398432 | One 2026-10-27 daily close normalized | Historical date, not a live VIX quote or spike policy |
| BLS, initial | 2026-10-28 04:00:29.970141 | Custom timezone rejected | Original failed attempt retained; see exact receipt for clocks |
| BLS, reviewed mapping | 2026-10-28 04:05:06.207758 | 313 events parsed | All 313 lack original revision timestamps; coverage remains PARTIAL |

The exact receipt JSON and `EVENT_SOURCE_PROOF.json` take precedence over rounded
presentation times. Counts span the downloaded feeds, not only the requested
30-day horizon. No response is treated as proof that omitted events do not exist.
Public download access was demonstrated from this workspace, not from the trading
host. No key or subscription was used. An earlier connectivity-only BLS request
returned `URLError`; that unretained preflight is not provider acceptance.

BLS's feed declares `US-Eastern` in its own `VTIMEZONE`. It is not an IANA key.
The adapter now requires the exact reviewed definition (UTC-5 standard, UTC-4
summer, second Sunday in March and first Sunday in November transitions) and
maps only BLS timestamp properties to `America/New_York`. Missing definitions,
changed offsets/rules, ambiguous/nonexistent local times, or the same custom
alias on another provider fail parsing. This is `bls-adapter-v2`, shared by the
existing collection CLI and the new probe. It is not a general timezone rewrite.
Original raw text retains the provider's custom name. Missing BLS source clocks
remain null and those events remain incomplete; receipt time does not replace
revision time. BEA and VIX source versions remain unchanged.

## Bounded capture contract

`python -m app.events.source_probe capture` runs a single fixed local child for
one allowlisted public source: `bls`, `bea` or `vix`. There is no generic command,
endpoint override, credential input, model call, scheduler, native account access
or operational publication. Existing destination directories are refused.

The request fixes an aware UTC interval of at most 366 days and a child timeout
of 1–60 seconds (default 20). The child timeout includes import, network and parse
work. A slow child is killed and reaped; the parent retains a timeout receipt.
The existing HTTP adapter additionally limits decoded responses to 8 MiB, refuses
redirects and performs no retry. Normalized row counts and JSON size are bounded.
This is not a hard-real-time guarantee for filesystem IO or OS scheduling.
Capture/replay must remain outside trading and mandatory-protection processes.

Each fresh mode-0700 directory receives an atomic mode-0600 `capture.json` with:

- Original decoded UTF-8 text and SHA-256, request/source/endpoint/version,
  parent/child receipt clocks, elapsed capture/parse time and adapter-code hash.
- Original normalized event/coverage/volatility records on successful parsing.
- Explicit transport, parse, protocol, launch or process-timeout status. Parse
  failures retain raw text and never supply normalized evidence. Exception
  messages and child stderr are not retained; safe HTTP status codes are retained.
- `coverage_accepted=false`, `host_accepted=false`,
  `operational_evidence_published=false`, and no execution authority.

The retained body is the adapter's decoded response, not exact HTTP wire bytes:
UTF-8 BOM removal, HTTP decompression/transport and response headers are not
recorded. Its hash is an integrity check, not a provider signature. A failure to
write the local receipt fails the command; no durable-success claim is made.

`verify` performs no network calls. It checks hashes, source identity, ordered
clocks, original receipt bindings and normalized content by replaying the parser
at the original receipt time. It does not refresh evidence. A changed adapter
implementation is reported; replay succeeds only if the recorded result still
matches exactly. The initial BLS failure is historical evidence from the previous
adapter and intentionally no longer reproduces under v2. Its original capture
and raw hash remain intact; the new successful receipt is separate.

## Usage after installing the feature wheel

Create a private request file (mode 0600), for example:

```json
{
  "source": "bea",
  "starts_at": "2026-10-28T04:00:00Z",
  "ends_at": "2026-11-27T04:00:00Z",
  "timeout_seconds": 20
}
```

Choose fresh dates for a new capture; this example does not enroll a provider or
claim current evidence. Run in an independent process outside the owner services:

```bash
python -I -m app.events.source_probe capture --request /private/request.json --directory /private/new-capture
python -I -m app.events.source_probe verify --artifact /private/new-capture/capture.json
```

`PARSED_PARTIAL` exits 0; unavailable/failed outcomes exit 2. Neither outcome means
trade approval. To replay repository receipts, first copy one into a private
location with mode 0600; git checkout permissions are not an input acceptance
contract. No import-to-operational-store command is provided by this probe.

## Verification and next dependencies

`EVENT_SOURCE_PROOF.json` records installed tests, source/wheel/install identity,
actual capture hashes, replay outcomes and collection/parse elapsed times.
Subprocess tests use explicitly synthetic responses; original-response tests use
the retained public receipts. Timeout/protocol/error redaction, tampering, receipt
clocks, atomic publication, DST/custom rules and unchanged native protection and
accounting are covered separately from actual source schema acceptance.

This does not prove source-to-trading-detection latency, polling reliability,
provider completeness, production-host connectivity, host process/UID isolation
or readiness of Swing catalysts/Scope context. Calendar checks remain separate
from quote freshness. Existing earnings/IV diagnostic and local latency proof
are unchanged; no new under-5-ms performance claim is made.

Still needed: Trading Economics calendar credential/subscription and complete
macro coverage acceptance; Finnhub `/calendar/earnings` key and symbol/plan access;
actual contract-IV delivery/entitlement; reviewed licensed live VIX source if
wanted; and host observer integration. Exact paid-plan costs remain unverified.
No paid services were purchased. Non-earnings company events, unscheduled news,
FX/cross-asset interpretation and emergency closures remain unsupported.
