# Two-play deployment and remaining acceptance

Code/offline proof is recorded in [TWO_PLAY_NATIVE_PROOF.json](TWO_PLAY_NATIVE_PROOF.json).
The operator has confirmed host deployment of acabf4a to frozen ui-review-v3.
Full browser acceptance, ongoing authenticated delivery and market-open simulated
execution are separate, still-unverified stages.
No connected PAPER service or model worker was activated during implementation.

The user wants virtual-money trading here, using real incoming market data and the
same dashboard. No external PAPER/brokerage account is required. Use
[MARKET_DATA_PROOF.md](MARKET_DATA_PROOF.md) for the next bounded data check.

## Confirmed existing host

The operator's supplied output confirms dashboard revision/image
acabf4a816ef5cc674fe36d687d29351d273e469, 283 matching installed application files,
two native simulated fills, authenticated frozen-review mode and health OK.
This is confirmed historical host evidence, not a fresh remote inspection.
The original SHADOW worker/observer remain frozen. Full browser acceptance remains
pending. The previous dashboard is already retained as
`trade-bot-dashboard-before-two-play`; do not reuse that rollback name.
Preserve ui-review-v1, ui-review-v2 and the deployed ui-review-v3.

## Historical V3 deployment procedure (already completed)

Do not rerun the commands below: their directory and rollback name are consumed.
Use the guarded V3 refresh in MARKET_DATA_PROOF.md for the price-formatting fix.

After fetching this validated release, the operator can use the guarded V3 path.
It expects the currently confirmed d2092f1 image and reserves the new unused
`trade-bot-dashboard-before-two-play` rollback name. Preparation is network-free
inside the container and creates a new directory exclusively. Activation changes
only the separate dashboard reader; it never starts a PAPER collector/runtime/model.
Do not rerun prepare if the directory exists, even after a failed attempt.

```bash
cd /opt/trade-bot-dashboard &&
git fetch origin slice2/robinhood-read-shadow &&
test -z "$(git status --porcelain)" &&
git checkout --detach VALIDATED_RELEASE_SHA &&
bash scripts/dashboard-review-host.sh prepare ui-review-v3 &&
bash scripts/dashboard-review-host.sh activate ui-review-v3
```

Use the exact release SHA supplied with this change, not an unreviewed newer HEAD.
The helper verifies source/installed bytes, fixture seed/journal hashes, two held
plays and two native fills before replacement. Both older fixture mounts stay
read-only during preparation. The existing private dashboard password is mounted
only into the reader. Caddy continues to route to 127.0.0.1:8790. The helper checks
that the original SHADOW containers have not changed and restores the prior
reader automatically on activation failure. Docker execution of this procedure
has not been performed in this workspace; the operator must supply host results.

The V3 fixture is synthetic historical evidence at 2026-10-09T14:00:02+00:00.
Use it to review both complete cards, selector labels, green/amber amounts,
Summary/Thesis/Protection/Fills tabs, original-levels disclosure and equal 420px
lower panels at desktop/mobile sizes. It remains paused. Polling identity
preservation is tested separately with active-account mocked DOM checks, which
are not actual browser acceptance. No Chromium is available here.

## Connected PAPER acceptance still blocked

1. Review exact option metadata, expiry/last-trade/settlement evidence and current
   data entitlement. Broker sellout time is not exchange expiry evidence.
2. Supply executable stock sizes from a reviewed source. The captured stock quote
   shape omits sizes; the mapper intentionally leaves them missing.
3. Supply a reviewed Scope/SPX mapping or an explicitly normalized compatible
   source before expecting Scope on a connected feed. Current Robinhood SPY/QQQ
   mappings cannot stand in for SPX quotes/context.
4. At market open, verify fresh original source clocks, continuous delivery for
   both held plays (including retired candidates), rate limits, gaps, reconnects,
   collector/runtime restart, and native simulated fills from eligible quotes.
5. Confirm page reads never cause provider/model/trading work and that signed
   admin changes reach only the explicitly enrolled account owner.

`app.mixed.feed_cli` validates an explicit policy/schema/journal/directory before
running; only `--run` starts collection. Do not invoke it or enroll/activate a
connected PAPER runtime until the unresolved source evidence is reviewed. Existing
credentials remain private and unchanged. LIVE routing remains disabled.
