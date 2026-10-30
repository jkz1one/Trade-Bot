# Remaining Robinhood inputs and configuration

The October 29 local PAPER session is enrolled for four DEGEN option candidates.
Enrollment is not market-hours runtime acceptance. Keep that session and its
account intact while reviewing additional capabilities. No new provider or broker
paper account is required by this work.

The existing adapter saves six schemas, not Robinhood's complete advertised tool
inventory. Absence from that allowlist does not prove the service has no tool.
The new `inventory` operation retains bounded metadata without calling a market,
account, order or model tool. It does not add advertised tools to the allowlist.
The same private OAuth connection and process timeout/lease boundaries apply.
A returned read-only annotation is a discovery hint, not execution authorization.

## Shared execution, different inputs

All three families share the simulated account, position cap, execution and
protection path. Current strategy and enrollment requirements differ upstream:

| Area | Actual requirement or limitation | Next evidence/work |
| --- | --- | --- |
| DEGEN options | Intraday completed bars, quotes, option metadata and Greeks; four candidates enrolled | Fresh native acceptance and bounded market-hours run |
| Swing history | 56 completed daily bars and 54 native hourly bars, original pre-open source binding | Verify actual noninterpolated daily bars; exact half-hour aggregation exists |
| Swing historical-data policy | Current original-history path still requires REALTIME and legacy mapping is frozen in the base | Explicit simulation-policy support and reviewed mapping/source enrollment; never relabel UNKNOWN as REALTIME |
| Swing catalyst | Source is currently `unavailable-catalyst`; dated symbol-specific CLEAR/BLOCKED/UNKNOWN coverage is required | Inventory news/calendar/event capabilities, inspect schemas and actual payloads; no empty-news-to-CLEAR conversion |
| Swing options | Current strategy requires 7–45 days to expiration; current helper enrolls same-day intraday contracts | Dated contract discovery and supported future-expiry simulation terms, separate from the four current DEGEN contracts |
| Scope | SPX/SPY/QQQ structure and nine coverage groups, SPXW contract/session data | Inventory index/history/context tools and original payloads; identify unsupported groups accurately |
| Stock metadata | SPY/QQQ records currently have metadata_complete/tradable false | Inspect reference/tradability schemas and source records; reviewed existing-owner update needed |
| Stock executable size | Current equity quote schema/mapping supplies no bid/ask sizes | Search advertised schemas for actual sizes; do not manufacture liquidity |
| Stock affordability | Current share step is one whole share and entry debit is capped at $250 | Independently evaluate current prices against this cap; metadata/sizes alone cannot make a more-expensive whole share fit |

Scope's nine groups are provider readiness, technical structure, options analytics,
dealer structure, options flow, cross-market agreement, economic events, broad
market news and SPXW contracts. These are requirements of the currently implemented
Scope strategy, not generic requirements for every simulated trade. Raw option
Greeks/open interest do not establish dealer holdings or actual trade-flow direction.
A reduced-data strategy would need explicit design and validation; missing inputs
must not silently become neutral observations.

Important code references: `app/mixed/simulation_profile.py`,
`app/mixed/connected_check.py`, `app/mixed/swing_binding.py`,
`app/options/swing.py`, `app/options/scope.py`, `app/options/read_gateway.py`.
The October 29 policy is already enrolled. Do not edit frozen base settings or
re-enroll/reset the account to implement these additional inputs. Future updates
must preserve original journals, held positions and already-admitted policy.

## Host inventory

Build the pinned release, then run:

```sh
bash scripts/robinhood-input-inventory-host.sh
```

This can run outside market hours. It performs one bounded metadata inventory
operation (up to eight tools/list pages and 256 tool names), with zero tool calls.
It mounts no owner/collector/account/model-key directory and starts no workers.
The existing six-tool schema pin remains unchanged. Original discovery.json is
mounted read-only and is not replaced.

The output contains a tool index and candidate schemas grouped by input need.
Groups are search leads, not proof of usable or entitled data. Full normalized
metadata is retained in the private inventory.json where within bounds. Oversized
schema omissions and incomplete property-path extraction are explicit; never infer
that an omitted field/capability does not exist. The full output is bounded, with
no provider exception text, OAuth tokens or account responses printed.

Next work depends on the actual inventory: review specific candidate schemas,
add individually allowed read-only captures and validate original payloads, then
connect the supported inputs through explicit existing-owner policy updates.

## Observed full inventory and next capture

The operator supplied inventory capture 94ca4690043e4f2ea97bc13c156dea71,
containing 87 tools. Its original file SHA-256 is `42245ba9234f5965820edf66a0af3cc3b6cfc102c17547291bd12433822139af`.
Selected original metadata is preserved in
`tests/fixtures/robinhood_input_probe_schemas.json` and matched by full metadata
hash in `app/options/input_probe.py`.

- `get_equity_price_book`: price levels with integer share quantities and a
  snapshot timestamp. This is a book snapshot, not automatically consolidated
  executable NBBO or proof of source-clock freshness. Requires actual payloads.
- `get_earnings_calendar`: seven-day company earnings coverage, with tentative
  versus verified dates. Empty results do not clear all ETF catalysts or macro news.
- `get_indexes`, `get_index_quotes`, `get_index_historicals`: SPX identity and
  market data candidates. The schemas explicitly support restricted results.
  Respect these rather than substituting another symbol or estimating values.
- `get_equity_tradability` requires `account_number`; no account is automatically
  discovered or selected. It is excluded from the new probe.
- Technical indicators exist but do not replace missing original histories or
  independently establish dealer positions/options flow.

Run `bash scripts/robinhood-input-probe-host.sh` with a clean built release.
It saves `probe.json` in a new private `/root/trade-bot-input-probe-*` directory.
This is an evidence-only operation: at most five calls, no auto-retries, and no
runtime enrollment/activation. It uses the existing private-auth lease and fixed
30-second process deadline. All five schemas are pinned before the first call.
Schema changes refuse the probe; capture errors retain bounded diagnostics and
permit independent calls within the same deadline. `COMPLETE` means the capture
finished, not that all symbols are available, current, entitled or strategy-ready.
The report separately exposes per-symbol book failures and index restrictions.

After-close captures can establish response mapping and restriction evidence.
Freshness and advancing book/index clocks still need market-hours verification.
For an actual new trading day, prepare an appropriate new session catalog; the
previous October 29 enrollment does not cover expired contracts on another day.

## Offline report recovery

The index-history schema permits omission of `interpolated`. Report counts keep
explicit true, explicit false and unknown separate; absent does not mean false.
The host's four-read failure has its original observations saved in `probe.json`.
After building the corrected release, recover its report without another request:

```sh
bash scripts/robinhood-input-probe-host.sh --report /root/trade-bot-input-probe-LB05wA
```

The original capture failure remains visible. This mounts only the evidence
folder read-only with network disabled and never overwrites or promotes evidence.
Attach the original `probe.json` for payload mapping, even if its stored status is
FAILED; completed individual responses may still be useful.
