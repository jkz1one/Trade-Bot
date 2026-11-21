# Bounded host Swing history proof

The connected October 27 session started during regular hours. It delivered 39
MARKET packets but had no original pre-open Swing sources. Quote evidence alone
does not verify the daily/hourly historical response formats needed for source
preparation. These histories can be captured after the preceding close or before
the next session opens; another regular-session quote test is unnecessary.

`scripts/swing-history-proof-host.sh` performs one bounded capture using the
existing host-verified 105f1a1 image. It mounts only the frozen connected feed policy
read-only, existing read credentials, the helper script and a new private evidence
directory. It does not mount the account/collector databases, export directory or
model key, and starts no runtime, model or dashboard worker. OAuth refresh may
update the existing read credential through the normal read gateway.

The helper uses the actual enrolled history policy and stock universe. Current
configuration requests SPY/QQQ daily 56-bar and hourly 54-bar series: four calls.
The native calendar supplies exact prior-session bounds, holidays and short days.
Mid-session execution reports WAIT_FOR_PREOPEN_WINDOW without opening credentials
or reading providers. The normal capture timeout and schema/response bounds stay
unchanged. An incomplete four-call capture is not retried automatically.

Run on the host after fetching this release, with a clean checkout:

```bash
bash scripts/swing-history-proof-host.sh
```

No Docker rebuild is necessary. The exact image must already exist. The helper
writes a new `/root/trade-bot-swing-history-*` directory and prints its path.
Artifacts are create-only: plan.json, original capture.json, report.json, and
history.json only if the native mapper accepts every required original bar.
The original capture remains available when mapping fails. The compact report
shows per-symbol interval, count and first/last source labels to identify provider
format differences without dumping private transport diagnostics. Share report.json
first; preserve capture.json for offline inspection. Never include the auth folder.

HISTORY_MAPPED means only that the native daily/hourly mapper accepted original
bars. Entitlement stays UNKNOWN. No source-binding receipt is installed, no
account is re-enrolled, no entry halt is cleared and no catalyst clearance is
inferred. An offline proof must not be copied into the collector database or
restamped as a new original. Operational preparation still uses its existing
raw-verified native collector path.

HISTORY_MAPPING_UNAVAILABLE means raw reads completed but do not match the current
strict mapper. Inspect the retained raw response before changing bar alignment,
coverage, interpolation or session handling. HISTORY_UNAVAILABLE means a required
read was incomplete. Both keep trading_ready=false; neither is a simulated trade.

This release completes the bounded history evidence collection operation. Actual
provider response acceptance is still needed for this path. Swing catalyst and
Scope SPX/context ingestion remain unfinished and are not supplied by these reads.
