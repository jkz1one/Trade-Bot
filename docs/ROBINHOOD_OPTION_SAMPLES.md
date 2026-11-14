# Observed option IDs and accepted quote/history samples

The four-decimal strike attempt completed with the same two empty results. It did
not fix the observed issue. A later broader listing initially failed with Docker
exit 125 because the auth bind source was missing; no container/provider read ran
for that failure. The user reported deleting files, and the original credential
and login-backup glob found no copies. Fresh interactive login and headless discovery
then returned exit 0 using **`/var/lib/trade-bot-read-auth`**. Keep that dedicated
credential directory private and separate from disposable sample outputs. Older
runbooks' `/root/trade-bot-options-auth-BqLFmz` path is historical, not current.

Capture `f15f524e90ff4a75b941f04e0f5100cf`, collected October 25, 2026 at 01:11:55 EDT,
completed two `get_option_instruments` calls. Each used its known chain ID,
October 26 expiry and explicit `type=call`, without exact-strike/state/tradability
filters. Both returned 100 records and a next-page cursor. All returned IDs are
unique within each page and all chain/symbol/type/expiry identities match the
requests. Pinned schemas and original plan/receipt clocks validate offline.
[Retained evidence hashes and selected records](ROBINHOOD_CONTRACT_LISTING_PROOF.json).

This proves first-page contract discovery, not complete chain coverage. Both exact
previously requested strikes are already present, so no further page is needed for
this sample. Formatting alone failed earlier; because the broad query changed
several filters and authentication was subsequently renewed, the exact cause of the
old empty results is not isolated. Do not attribute it to one filter as established.

| Sample contract | Returned UUID |
| --- | --- |
| SPY 760 call, 2026-10-26 | `0eb7725e-bf00-4817-8e47-0092d1910f75` |
| QQQ 705 call, 2026-10-26 | `6058511b-ce40-4dd6-8ef9-8f5a3736ed90` |

Both records report active/tradable equity-underlying calls, multiplier 100 and
one-cent ticks. Their broker sellout timestamp is October 26 15:45 EDT. That is
not exchange last trading, expiration or settlement proof. No complete native
OptionInstrument is synthesized from these partial terms. Deliverables, exercise,
settlement, adjusted status and required exchange timestamps still need reviewed
binding. These are fixed schema samples, not trade recommendations.

## Completed quote and history reads

The [two-read plan](../examples/robinhood-option-sample-plan.json), SHA-256
`4f189991fa7b57b79c43304fc9ab5bfe86f02af423c0d9d154fbc63506f49d4e`, completed as
capture `778715467a4a4b3ea503ceff1b5b285a` at October 25 01:16:47 EDT.
Both calls validate against the pinned schemas, original plan, identities and
receipt clocks. [Response acceptance proof](ROBINHOOD_OPTION_RESPONSE_PROOF.json)
retains artifact hashes and the observed fields without credentials or account data.

| October 26 call | Bid / ask | Bid / ask size | Delta | Volume / open interest |
| --- | --- | --- | --- | --- |
| SPY 760 | 3.34 / 3.35 | 29 / 10 | 0.541653 | 46010 / 276 |
| QQQ 705 | 5.03 / 5.10 | 8 / 4 | 0.519612 | 47893 / 693 |

Both source timestamps are October 23 about 16:14:59 EDT, approximately 33 hours
before receipt. These are stale weekend observations, not executable current
quotes. Original nanosecond source strings remain in the proof. Theta and implied
volatility are also present; mark/adjusted-mark/fill-rate prices are not simulated
fills. Entitlement remains UNKNOWN. Native option mapping is not claimed because
complete reviewed OptionInstrument metadata has not been supplied.

Each history contains six coherent regular-session five-minute OHLC bars from
October 23 09:30–10:00 EDT. UUIDs and OCC symbols match the selected contracts.
The option-history tool supplies no volume, and these responses omit interpolation
flags. Both remain unavailable/unknown; the equity mapper's positive-volume
inference does not apply. No synthetic bars, volume, flags or execution liquidity
are added. Option history is not an executable quote source.

All six read tools now have successful authentic response samples. No additional
sample capture is required now. This completes wire-response evidence collection,
not a connected PAPER service. Remaining integration work is:

- Bind complete reviewed contract terms and real-time entitlement evidence without
  treating broker sellout as exchange expiration or settlement.
- Connect bounded read capture and the existing mapper to continuous normalized
  packet delivery, retaining original source/receipt clocks, stale/unknown blockers
  and independent protection. Supply sufficient underlying history for each strategy.
- Verify fresh market-session inputs and native simulated fills on the host before
  prospective PAPER activation. Equity sizes are still missing from this endpoint,
  so stock fills remain blocked by existing rules.

No model/PAPER/LIVE activation or new provider calls were performed by this review.
The existing 119 installed cases and 256-file identity proof remain prior code
verification; this is a documentation/evidence update, not a new test-suite run.
Dashboard chart/label browser acceptance remains pending.

## Historical command for the completed capture

Do not rerun this command merely to finish the sample review. It is retained to
explain how the accepted artifacts were produced; no refresh or rebuild is needed.

The operator fetched the published revision supplied in chat first. The already-built
30e4eba diagnostic image has the unchanged capture CLI; no rebuild or dashboard
refresh is required. The local mapper correction remains separate from that host
image. Capture rediscovers/pins schemas before either read, retains normal OAuth
refresh locking and the unchanged 30-second deadline, and writes a new directory.

```bash
bash <<'BASH'
set -euo pipefail
umask 077
cd /opt/trade-bot-dashboard
test -z "$(git status --porcelain)"
auth_dir=/var/lib/trade-bot-read-auth
test -f "$auth_dir/robinhood-oauth.json"
test -f "$auth_dir/discovery.json"
printf '4f189991fa7b57b79c43304fc9ab5bfe86f02af423c0d9d154fbc63506f49d4e  examples/robinhood-option-sample-plan.json\n' | sha256sum --check --status
sample_dir=$(mktemp -d /root/trade-bot-option-samples-XXXXXX)
install -m 600 examples/robinhood-option-sample-plan.json "$sample_dir/plan.json"
sample_status=0
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --mount "type=bind,src=$auth_dir,dst=/auth" \
  --mount "type=bind,src=$auth_dir/discovery.json,dst=/auth/discovery.json,readonly" \
  --mount "type=bind,src=$sample_dir,dst=/out" \
  trade-bot-read-diagnostic:30e4eba7591b0c6741a9495ad92b9fdc21fd8fd3 \
  python -I -W error -m app.options.read_cli capture \
  --oauth-file /auth/robinhood-oauth.json \
  --schemas /auth/discovery.json \
  --schema-sha256 d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15 \
  --plan /out/plan.json --output /out/samples.json --timeout-seconds 30 \
  > "$sample_dir/summary.json" 2> "$sample_dir/stderr.log" || sample_status=$?
printf '%s\n' "$sample_status" > "$sample_dir/exit-code"
cat "$sample_dir/summary.json"
printf 'Exit code: %s\nDirectory: %s\n' "$sample_status" "$sample_dir"
exit "$sample_status"
BASH
```

Share only the new summary and sample artifact, not the credential directory.
Application files remain unchanged from d19d4ee, with the prior 119 installed cases
and 256-file source/wheel/installed proof. This documentation/plan update adds no
new application test claim. Latest chart/label browser acceptance and connected
PAPER acceptance remain open; no original SHADOW or dashboard service is changed.
