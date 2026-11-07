# Isolated PAPER market acceptance evidence

The existing `runtime_cli collect` now reports measured intervals and tool counts
for the full-universe latency gate. This procedure must use actual authenticated
provider access with trusted installed code. Local MCP fixtures prove the contract
only. No namespace, model usage/billing, LIVE or profitability claim follows from
a market report.

## Provision explicitly and preserve the deployed experiment

Use the reviewed Python 3.12 wheel with pinned dependencies in the separate PAPER
environment. Record its exact commit and independently verified wheel digest.
The service UID must already own a mode-600 regular OAuth file with authorized
tokens/client metadata and the frozen callback registration. The operator manages
that file exclusively. Do not borrow the deployed worker's live OAuth file, create
concurrent refresh writers or reset/re-enroll the frozen `virtual-v1` experiment.
The fixed child can persist OAuth refresh, but cannot review, place or cancel orders.

Initialize a **new** disposable one-shot population outside both the deployed state
and the fixed service population. Its parent directory must already be provisioned
for the service UID. This example uses all 20 frozen project symbols, stub HOLD,
fake venue authority and no model/alert enrollment or running trader:

```bash
sudo -u tradebot-paper /opt/trade-bot-paper/venv/bin/python -I -B \
  -m app.execution.runtime_cli init \
  --directory /var/lib/trade-bot-paper/market-acceptance-001 --capital 10 \
  --symbols SPY QQQ IWM DIA XLK XLF XLE XLI XLV XLY \
    AAPL MSFT NVDA AMZN META GOOGL TSLA AVGO JPM COST \
  --market-oauth-file /etc/trade-bot-paper/market/paper-acceptance-oauth.json
```

Paths are explicit examples; provision the dedicated OAuth file before init.
The command validates enrollment without provider calls. Existing or incomplete
population directories are not silently reused. Do not add `--continuous-market`,
start a trader or opt into a model merely to collect this evidence.

## Capture a regular-session read

When actual current-session quotes are available, make one explicit collection:

```bash
umask 077
sudo -u tradebot-paper /opt/trade-bot-paper/venv/bin/python -I -B \
  -m app.execution.runtime_cli collect \
  --directory /var/lib/trade-bot-paper/market-acceptance-001 \
  > market-acceptance-001.json
```

Preserve the exit status, report hash, tested commit/wheel, UTC time, host identity
and whether this was genuine provider traffic. Do not share OAuth contents. Retain
the report independently; this CLI does not archive it or claim off-host protection.
Another read is a separately reviewed explicit invocation with a distinct report
path/request ID, not automatic retry or a changed deadline. No session backfill,
fabricated price or manual fixture publication belongs in authenticated evidence.

## Review the report

| Observation | Required evidence for this gate |
| --- | --- |
| Exit/result | Exit 0, `PUBLISHED`, `candidate_count=20` |
| Universe | Exact 20 requested symbols; no narrowed substitute universe |
| Saved lineage | Feed/request/source identities, feed sequence and saved packet hash |
| Tool calls | `OBSERVED`: 1 account, 1 quotes, 2 tradability, 20 historical attempts/completions |
| Timing | Actual parent read/reaping, validation/publication and total intervals, compared with the frozen 30-second deadline |
| Freshness | Collection/check/oldest quote clocks under the existing age checks |
| Provenance | Trusted installed wheel and operator evidence of authenticated provider traffic |

`OBSERVED` validates diagnostic counts/timing relationships; it is not endpoint
authentication or a provider acceptance decision. The report always retains
`provider_acceptance=UNVERIFIED`, `execution_authority=false` and LIVE disabled.
The packet hash identifies the saved parsed market packet, not raw provider replies.
Tool counts describe gateway invocations, not every HTTP exchange/OAuth refresh or
provider-internal retry. No account identifier or credential path/value is included.

The parent interval ends after successful SQLite publication. Deadline checks still
fence publication admission, not hard filesystem/fsync completion. Do not treat
`PUBLISHED` alone as satisfactory latency if measured total approaches/exceeds the
frozen budget. Failure publishes no successful report and preserves the existing
failure/cleanup semantics; a sanitized error cannot prove complete market coverage.
Review evidence before deciding whether another explicit attempt is appropriate.

One successful read does not establish continuous cadence, provider availability
through a full session or application boot/lifecycle behavior. Collect representative
session evidence without changing the frozen policies. Actual isolated-host sandbox
acceptance, bounded authenticated model usage/billing, independent alerts/archive
recovery and a host-loss drill remain separate gates.
