# First authentic quote/history/chain samples

The operator reported interactive login exit 0, then supplied a COMPLETE headless
schema summary (`ec65abd4d0374732b52c882a3dbe2c19`) with the exact reviewed pin and
no missing tool/input/output schemas. A subsequent four-read capture
`e813525b3aa04dd98a3c7e0083910296` completed at October 25, 2026 00:49:09 EDT.
All four output schemas, original plan, observation order/clocks and policy digest
validate offline against the installed package. No workspace provider call occurred.
Previous failed captures and authentication diagnostics remain preserved.
[Receipt hashes, exact installed tests and application identities](ROBINHOOD_SAMPLE_ACCEPTANCE_PROOF.json).

## Observed mapping

- Both equity quotes map with original bid/ask source times at Friday October 23
  20:00 EDT, about 28 hours 49 minutes before receipt. They remain stale evidence.
  Neither side has executable size. No last-trade/mark/close price substitutes for
  bid/ask. Full source timestamp strings remain in the retained raw receipt;
  native datetime projections have microsecond precision.
- Both historical responses contain six completed regular five-minute bars from
  October 23 09:30 through 10:00 EDT. All 12 omit the optional `interpolated` flag
  and report positive share volume. The previous mapper required an explicit flag
  and rejected this schema-valid provider shape.
- The mapper now derives non-interpolation from positive volume only under the
  exact reviewed schema, which explicitly states interpolated bars have zero
  volume. This is a schema-backed inference, not a default from missing data.
  Omitted flag with zero/negative volume still fails; explicit interpolation with
  nonzero volume now fails as contradictory. Explicit false with zero volume stays
  false. Null/string flags fail schema validation. Raw observations are unchanged.
- Both chain records identify the requested symbols and list October 26 expiry.
  Their IDs can seed bounded instrument discovery. Broker force-close offsets,
  multiplier and chain flags do not alone establish complete native contract terms.

The installed mapper accepts the two quotes and 12 completed bars. History-window
completeness does not mean fresh strategy warmup or entitlement acceptance: all
mapped observations still have UNKNOWN entitlement. This has not started a feed,
trader, model worker or prospective PAPER owner. The six-tool contract is not fully
accepted: actual instrument, option quote and option historical samples remain open.

## Next bounded contract sample

[Prepared plan](../examples/robinhood-contract-read-plan.json), SHA-256
`d99b811e760fa8e766f4e4894e5a0bf3bcb5655688997a40ce67c7595de7ad93`, requests two
`get_option_instruments` calls: SPY strike 760 and QQQ strike 705, October 26 expiry,
active/tradable, using the exact returned chain IDs. Omitting type requests both
call and put at each exact strike. These are fixed sample subjects near the retained
underlying prices, not trade recommendations or an assumption that those contracts
exist. Empty results, alternate metadata or pagination must be inspected. There is
no automatic pagination, retry, quote call, account read, broker action or model call.
Returned exact UUIDs will determine the next quote/history requests after review.

The operator executes the next step. This plan extends the previous four-read batch;
no additional authenticated calls have been executed by this workspace. Fetch and
check out the published revision supplied in chat first. The existing diagnostic
image already has the unchanged capture CLI; no image rebuild/dashboard refresh is
needed to capture these raw responses. The new mapper is tested locally and is not
yet installed in that host image. One tool-list request precedes the two reads and
must match the pin. The deadline remains 30 seconds.

```bash
bash <<'BASH'
set -euo pipefail
umask 077
cd /opt/trade-bot-dashboard
git fetch origin slice2/robinhood-read-shadow
test -z "$(git status --porcelain)"
# Check out the published revision supplied with this command before continuing.
printf 'd99b811e760fa8e766f4e4894e5a0bf3bcb5655688997a40ce67c7595de7ad93  examples/robinhood-contract-read-plan.json\n' | sha256sum --check --status
contract_dir=$(mktemp -d /root/trade-bot-contract-samples-XXXXXX)
install -m 600 examples/robinhood-contract-read-plan.json "$contract_dir/plan.json"
contract_status=0
docker run --rm --network bridge --init --read-only \
  --user 0:0 --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 512m --pids-limit 64 --tmpfs /tmp:size=64m,mode=1777 \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz,dst=/auth \
  --mount type=bind,src=/root/trade-bot-options-auth-BqLFmz/discovery.json,dst=/auth/discovery.json,readonly \
  --mount "type=bind,src=$contract_dir,dst=/out" \
  trade-bot-read-diagnostic:30e4eba7591b0c6741a9495ad92b9fdc21fd8fd3 \
  python -I -W error -m app.options.read_cli capture \
  --oauth-file /auth/robinhood-oauth.json \
  --schemas /auth/discovery.json \
  --schema-sha256 d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15 \
  --plan /out/plan.json --output /out/samples.json --timeout-seconds 30 \
  > "$contract_dir/summary.json" 2> "$contract_dir/stderr.log" || contract_status=$?
printf '%s\n' "$contract_status" > "$contract_dir/exit-code"
cat "$contract_dir/summary.json"
printf 'Exit code: %s\nContract directory: %s\n' "$contract_status" "$contract_dir"
exit "$contract_status"
BASH
```

Share only the new `summary.json` and `samples.json`. Keep credentials private and
all failed/partial artifacts. Do not repeat successful earlier reads just to make
fresh filenames. The original SHADOW deployment, v1/v2 fixtures and running a3216b6
dashboard remain unchanged. Latest chart/label browser screenshots remain pending.

## Verification

119 installed Python cases pass, including eight added interpolation cases and
read capture/diagnostics regressions, serially from copied tests outside checkout
with Python `-I -W error`, disabled plugin autoload and explicit anyio. All 256
application/template files match source/wheel/installed bytes. Wheel SHA-256:
`2a6944d68e2fe051c848384bca553f040646e1ea8e0fc663f28bcbc487792d1d`.
The actual retained responses separately pass the installed offline mapping and
schema checks. No engine, strategy, dependency, fill, cost or authority changes.
Connected PAPER acceptance remains incomplete.
