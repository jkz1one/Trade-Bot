# Catalog proposals from retained option captures

The October 27 connected session completed its ten-minute run and published a
snapshot. The operator's journal reports generation 3, feed sequence 65 and
STOPPED; the collector reached sequence 66. Exactly 39 batches in that run were
MARKET packets with SWING_ORIGINAL_SOURCES_UNAVAILABLE and
SCOPE_CURRENT_INPUT_UNAVAILABLE. This is collection/ingestion acceptance for one
bounded run, not eligible strategy evaluation, simulated fills or a permanent
timeout fix. The public dashboard has not been switched by this work.

The uploaded option archive independently captured four October 28 SPY/QQQ
contracts and three quote samples at 16:10:30–16:10:47 EDT. All four source clocks
advanced, all twelve books had positive bid/ask sizes, and their ages at capture
were below the existing thirty-second diagnostic threshold. These historical
observations are not current quotes, regular-equity-session proof or entitlement.

## Implemented preparation

`app.mixed.contract_catalog` verifies completed captures against the pinned wire
schema and original request subjects. It rejects missing or mislabeled receipts,
unfinished pagination, duplicate identities, changed chain/expiration/strike,
inactive contracts, incomplete quote coverage, reordered/reused captures, future
or regressing source clocks, and changed quote content at an unchanged clock.
The report retains original provider contract records, source/receipt times and
semantic capture hashes. No OAuth file, network connection or account is opened.

The inspect mode needs the original private capture files, not their printed
terminal summaries. Example interface (paths are placeholders):

```bash
python -I -m app.mixed.contract_catalog \
  --contracts /private/proof/contracts.json \
  --quotes /private/proof/quotes-1.json /private/proof/quotes-2.json /private/proof/quotes-3.json
```

The real archive returns REVIEWED_TERMS_REQUIRED. Discovery does not provide all
native contract terms. In particular, sellout_datetime is a broker liquidation
cutoff; it must not be copied into last_trading_at, expires_at or settles_at.
Exercise, settlement, deliverable, adjustment and other omitted terms remain
explicit. The reported multiplier alone does not establish an unadjusted contract.

An explicitly reviewed JSON list of complete native OptionInstrument records can
be supplied with `--terms`. The preparation step cross-checks identity, underlying,
right, strike, expiration, multiplier and representable tick schedules against
discovery. It then runs the selected original quote rows through the existing
quote/Greek/metadata mapper. Supplemental terms are caller-supplied declarations;
this operation does not independently certify their legal correctness. Tests use
synthetic supplemental terms and do not approve those terms for the host.

With `--base-policy`, `--target-session` and `--output` together, the same command
writes a create-only full FeedPolicy proposal. The output directory must be private
(0700); all input files must be current-owner private files (0600). Candidate
selection is explicit (one to six records); no list-order trade choice is made.
Only candidates and carry intents for that exact target session may differ.
Existing future-session calendar, expiry and identity checks run before writing.
The printed report binds the proposed policy hash and the captured evidence.

The proposal is consumed by the existing [feed rollover](FEED_ROLLOVER.md)
review/apply mechanism; creation does not enroll it. The existing owner, cash,
positions, halts, feed sequence and risk policy are not changed. Original capture
files remain untouched. `state_modified=false` refers to runtime/account state;
proposal mode writes only the requested new proposal artifact.

## Still required

Actual supplemental contract terms and entitlement evidence are not supplied by
this change. The current collector still lacks Swing catalyst ingestion and
Scope SPX/context ingestion. Swing pre-open history and source preparation also
require valid source evidence. No family is silently dropped, no partial strategy
cycle is promoted, and no missing market data is invented. The diagnostic strikes
are not strategy recommendations or an automatically approved shortlist.

The real capture fixture deduplicates the already retained identical wire schema;
tests reconstruct it without changing quote/provider fields. The original archive
and per-member hashes in CAPTURED_OPTION_CATALOG_PROOF.json identify the uploaded
bytes separately from reconstructed fixture hashes.
