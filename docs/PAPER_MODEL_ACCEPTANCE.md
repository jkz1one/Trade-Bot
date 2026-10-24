# Bounded authenticated model acceptance

This procedure collects evidence from a **new disposable isolated PAPER population**.
It is not a SHADOW upgrade, frozen-experiment reset, live trade or profitability test.
No authenticated provider call has been made by the local fixture tests described
in the status document. Use the verified installed wheel, a dedicated owning UID
and explicitly authorized private model/OAuth files. Do not supply secrets in chat,
share concurrent OAuth refresh ownership or use the deployed SHADOW checkout.

## Prepare one separately reviewed attempt

Use the [full-universe market procedure](PAPER_MARKET_ACCEPTANCE.md) to provision
authorized read-only market access and validate actual session coverage/latency.
For this **distinct** model population, explicitly enroll the same frozen universe,
model key and continuous market source. Choose a new directory, never an existing
population or the production service directory:

```bash
umask 077
python -I -m app.execution.runtime_cli init \
  --directory /var/lib/trade-bot-paper/model-acceptance-001 \
  --capital 10 --symbols SPY QQQ IWM DIA XLK XLF XLE XLI XLV XLY \
  AAPL MSFT NVDA AMZN META GOOGL TSLA AVGO JPM COST \
  --key-file /etc/trade-bot-paper/model/openai.key \
  --total-budget 0.01 --daily-budget 0.01 \
  --market-oauth-file /etc/trade-bot-paper/market/robinhood-oauth.json \
  --continuous-market
```

Paths are examples and require independent authorization/provisioning; this command
does not create a model key or obtain broker OAuth. Startup freezes the isolated
prompt/configuration and uses the existing `gpt-6-luna`, 16,000 input/1,024 output token
ceilings, 20-second SDK request timeout, 30-second model process budget and configured
$0.10/$0.50 per-million rates. These are project configuration, not verified billing.

The total/daily budgets equal the current $0.01 per-call reservation. After any known
positive cost, another full reservation cannot fit; missing usage also blocks new
calls. Do not increase budgets, reset receipts or reinitialize after failure. The
worker still attempts at most one input-count invocation followed by one generation,
with SDK retries disabled. These are SDK method observations, not an invoice or a
guarantee about provider-internal processing/preflight charges.

## Run and retain evidence

During an actual regular XNYS session, run the existing runtime under an explicit
outer timeout. It uses its normal current-slot claim, continuous fresh market reads,
authoritative fake-venue reconciliation, independent supervision, cost reservation
and deterministic approval. It cannot call a broker write method. The fixture venue
can retain a governed hypothetical order but does not fabricate a broker fill.

```bash
timeout --signal=TERM --kill-after=240s 90s \
  python -I -m app.execution.runtime_cli run \
  --directory /var/lib/trade-bot-paper/model-acceptance-001
python -I -m app.execution.runtime_cli report \
  --directory /var/lib/trade-bot-paper/model-acceptance-001 \
  > /var/lib/trade-bot-paper/model-acceptance-001/report.json
```

The GNU timeout wrapper normally returns 124 when its own limit expires; that alone
does not prove a failed or successful runtime drain. Inspect the retained runtime
status, cycle, attempts, uncertainty, usage and events. A forced kill, INTERRUPTED
cycle, missing usage or absent result must remain unresolved evidence. Do not replay
that slot, reconstruct a missing cost as zero or automatically retry on another
population. Closed/stale/unhealthy sessions can skip without a call; skipped HOLD
is not authenticated model evidence. Use the ordinary reviewed recovery contract
for any unresolved state, without adopting this disposable population for trading.

## Assess the existing report

`MODEL_JUDGMENT_RECORDED` now contains `process_evidence`, schema
`paper-model-process-evidence-v1`. It retains model, packet hash, exact frozen
prompt/schema/cost-policy hashes and limits, monotonic admission time, invocation
and child-reaping time, and their total. Child diagnostics record attempted/completed
input-count/generation methods, each elapsed interval and whole `perform` time.
`perform` includes local validation/decision parsing; parent invocation includes
child spawning/imports, client creation/closure, protocol validation and cleanup.
Total ends after reaping and before settlement/recording, not at a provider timestamp.

Child counters are strict integers 0/1; child times are finite, bounded and
nonnegative. Parent times also include owned cleanup and can exceed the invocation
budget during draining or filesystem stalls; OBSERVED is not deadline acceptance.
A method is completed when the SDK returns, before usage/decision acceptance. Refusals or
invalid usage can therefore have completed calls and still fail to HOLD. Coherent
timing/counts receive `OBSERVED`; missing/incoherent observations remain `UNVERIFIED`
without changing decision/accounting/entry policy. Typed invalid diagnostics fail
the existing child protocol. Cancelled work records parent timing only after cleanup,
keeps unknown cost and retains `MODEL_JUDGMENT_INTERRUPTED`. Parent death can leave
only the original durable attempt; absent completion is never invented.

All observations retain `provider_acceptance=UNVERIFIED`,
`billing_acceptance=UNVERIFIED`, `execution_authority=false`. Join the event's existing
source key/result/estimated cost to its saved model attempt, usage request ID,
decision and current-slot cycle. The packet hash matches the saved attempt after
normal deterministic packet/session preparation. Configured-rate settlement must
match retained generation usage; HOLD is first-class, including a failed billed HOLD.
Unknown usage stays unknown. Do not infer an invoice from these fields.

The report makes no provider calls and includes only the latest 100 events and 20
runtime cycle summaries. Absence outside that bounded window is not proof of a
missing attempt or scheduler completeness. Retain the report privately alongside
wheel/release identity, market evidence, provider request/account records, actual
usage/billing evidence and cleanup/host observations. The diagnostic fields contain
no API key, credential path, raw provider response, model input or new tools; the
ordinary journal/report still contains private account/decision audit data.

Actual acceptance requires authenticated session observations and independent
provider usage/billing reconciliation, plus target-host child/lifecycle enforcement.
Local SDK/native-process fixtures cannot satisfy those gates. Do not alter the
frozen `virtual-v1` experiment or enable LIVE based on this acceptance population.
