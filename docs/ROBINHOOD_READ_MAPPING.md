# Reviewed Robinhood mapping and first response capture

The user subsequently authorized this capture. It failed before schema discovery
completed and returned no market observations. Preserve that failed attempt; use
the [schema-only diagnostic](OPTIONS_READ_DIAGNOSTICS.md) before another market
capture. The command below records the original reviewed plan, not a blind retry.

The operator supplied `schemas.json` on October 24, 2026 America/New_York.
Its file SHA-256 is `d370d0a27b371e581b881fabc7a4d3e2fffc31e08e11dbf6deb6474b433dce1f`.
Recomputing the six-tool metadata digest matches the original authenticated pin:
`d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15`.
All six input/output schemas are present. The metadata-only export is retained as
a regression fixture; it contains no OAuth or account/market response artifact.

`app.options.read_mapping` now maps the reviewed wire structure to existing native
evidence models. It performs no network, model, venue, feed-file or journal work.
Mappings require the exact reviewed schema, successful bounded structured output,
exact requested subject coverage and valid original clocks. Schema descriptions
and provider guide text never become executable instructions or trading advice.

| Evidence | Mapping and limits |
| --- | --- |
| Equity bid/ask | Uses each side's original timestamp and the older timestamp for conservative combined freshness; preserves receipt time. No last trade, close or mark fallback. Inactive/never-traded symbols are incomplete; zero/crossed books are unavailable. |
| Shares | Requires an independently reviewed `StockInstrument`; sizes remain `None` because this schema supplies neither side's size. Existing quote-fill rules therefore cannot simulate stock fills from this endpoint alone. |
| Five-minute history | Explicit regular/split request and echoed interval, ascending unique aligned bars, original OHLCV and interpolation/session flags. Forming bars are excluded. Missing/interpolated intervals remain incomplete. No synthetic gap filling. |
| Option quotes/Greeks | Exact option UUID coverage and caller-supplied reviewed `OptionInstrument` metadata; preserves actual bid/ask sizes and source timestamp. Null Greeks remain unavailable. Zero books never become mark-price fills. |
| Option liquidity | Retains observed volume/open interest and delta provenance in existing `ContractMetadata`. |

Entitlement remains `UNKNOWN`: this schema advertises real-time tools but has no
per-observation entitlement field, and actual market response acceptance has not
occurred. The mapper supplies no override that silently promotes it to REALTIME.
It does not create a complete option contract from partial provider metadata.
In particular, `sellout_datetime` is the broker's force-close timestamp, not proof
of exchange last trading, expiration or settlement times. Deliverable details,
exercise/settlement terms, adjusted status and exact timestamp metadata still need
authoritative binding. Multiplier 100 alone is not that proof. Tick cutoffs must
also match the native contract representation rather than be assumed.

## Prepared first capture

[The reviewed plan](../examples/robinhood-initial-read-plan.json) contains exactly:

1. `get_equity_quotes` for SPY and QQQ.
2. `get_equity_historicals` for both, October 23 09:30–10:00 EDT
   (`13:30–14:00Z`), regular hours, split-adjusted, five-minute bars.
3. `get_option_chains` for SPY.
4. `get_option_chains` for QQQ.

The installed gateway validates every argument against the actual supplied schema.
Capture first rediscovers the tool metadata and rejects any pin drift before market
reads. The deadline remains 30 seconds; there is no automatic retry or pagination.
This short historical range is response-mapping evidence, not a complete strategy
warmup. Weekend quote responses must retain their actual old source clocks.
No option quote or instrument ID is invented: returned chain metadata and exact
reviewed expiry/strike subjects will determine the later bounded contract sample.
These four reads alone do not establish all six tools' response acceptance.

The user originally prohibited authenticated provider calls, then explicitly
authorized this four-read capture, its preceding tool-list request and necessary
OAuth refresh. That failed attempt is now retained for diagnosis. The operator executes host commands. A separate
PAPER service, model calls, orders, account reads and LIVE remain outside this step.

The command below is ready for review, not an instruction to bypass that boundary.
Use only the existing separately managed authorization in the supplied directory,
with no concurrent credential consumer. The installed a3216b6 image already has
the unchanged capture command, so no dashboard restart or image rebuild is needed.
After authorization, fetch this branch in the separate dashboard checkout and
verify the reviewed plan before running:

```bash
bash <<'BASH'
set -euo pipefail
umask 077
cd /opt/trade-bot-dashboard
test -z "$(git status --porcelain)"
printf '552d91c8d0dd4cbee2c765291980c258df8c2c91d481186daae8de9892ca0660  examples/robinhood-initial-read-plan.json\n' | sha256sum --check --status
sample_dir=$(mktemp -d /root/trade-bot-read-samples-XXXXXX)
install -m 600 examples/robinhood-initial-read-plan.json "$sample_dir/plan.json"
sample_status=0
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz,dst=/auth \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz/discovery.json,dst=/auth/discovery.json,readonly \
  --mount "type=bind,src=$sample_dir,dst=/out" \
  trade-bot-dashboard:a3216b6d3953d1291643830b20ac4ef69fd8b37b \
  python -I -W error -m app.options.read_cli capture \
  --oauth-file /auth/robinhood-oauth.json \
  --schemas /auth/discovery.json \
  --schema-sha256 d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15 \
  --plan /out/plan.json --output /out/samples.json --timeout-seconds 30 \
  > "$sample_dir/summary.json" 2> "$sample_dir/stderr.log" || sample_status=$?
printf '%s\n' "$sample_status" > "$sample_dir/exit-code"
cat "$sample_dir/summary.json"
printf 'Private sample directory: %s\n' "$sample_dir"
exit "$sample_status"
BASH
```

The auth-directory mount allows the existing private OAuth refresh and shared
reader lock to persist; the discovery file is mounted read-only. The capture
command only writes its new output and normal authorization refresh/lock state.
Keep any failed/partial output, inspect it, and do not blindly repeat. Only the
sample artifact and summary are relevant for mapping review; authorization files
remain private on the host. Original SHADOW services and frozen v1/v2 UI data are
not mounted or changed.

## Verification and current deployment

[Installed proof](ROBINHOOD_READ_MAPPING_PROOF.json) records 97 passing Python cases,
the tested wheel and all application/template byte identities. Tests use synthetic
responses validated against the real captured schemas. They do not claim actual
provider responses, entitlement, contract metadata completeness or feed acceptance.
No engine/admission/strategy/dependency changes were made. No authenticated call or
prospective PAPER activation occurred. An ongoing normalized collector and final
provider/model/host acceptance still remain.

The operator successfully refreshed the dashboard to a3216b6: all 255 application
files matched, three historical native fills remained, health/authentication passed
after startup retries and e6fd353 was retained as `trade-bot-dashboard-before-chart`.
This confirms that release's Docker host acceptance. Actual browser review of its
chart/label fixes is still pending. This mapping revision changes no UI and needs
no dashboard refresh; the prior refresh action intentionally rejects another run.
