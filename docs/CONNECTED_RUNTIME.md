# Coordinated simulation startup and restart

The installed `app.mixed.connected_runtime` command joins the native virtual-money
owner and the continuous read collector. It reopens an explicitly enrolled owner
and collector. It cannot create a population, reset cash, migrate a fixture,
clear an entry halt or replace the dashboard. LIVE routing remains absent.

This implementation is validated offline. The host still runs the frozen a653cc7
dashboard; no collector, simulation runtime or model worker has been activated.
No host action is requested while the operator is unavailable.

## Read-only check

`check` reads private runtime, policy and schema files, frozen owner configuration
and collector configuration. It reports wiring and entry blockers, stored runtime
generation/feed sequence, the entry halt, and the exact journal/population for a
stored dashboard reader. It does not acquire writable owners, recover state,
open credentials, start workers or make provider/model calls.

Interface example only, with intentionally unresolved paths:

```bash
python -I -m app.mixed.connected_runtime check \
  --directory ABSOLUTE_EXISTING_OWNER \
  --feed-directory ABSOLUTE_EXISTING_COLLECTOR \
  --policy ABSOLUTE_FEED_POLICY_JSON \
  --schemas ABSOLUTE_EXPORTED_SCHEMAS_JSON
```

A successful check is not trading permission or a guarantee that locks are free.
Native owner, strategy and restore-fence verification still run during startup.
Missing owner/collector databases are errors. Frozen replay reasons or a retained
PORTFOLIO_REPLAY_STARTED event reject review populations before writable startup.

## Explicit bounded run

`run` uses the same arguments and additionally requires `--seconds` from 1 to
86400. This operation starts provider reads and may use an already enrolled model
configuration. It is not an offline validation command. Do not use it on the host
until the complete settings, data eligibility and deployment procedure are ready.

Startup obtains the existing native owner lease, verifies enrollment, reopens the
collector under its own lease, and retains both through shutdown. The owner's
first tick performs native reconciliation/protection before the collector requests
held identities. Thus a crash between a durable venue fill and journal recording
can recover both plays before their quote coverage is planned. Completion of that
first tick does not assert fresh data, successful reconciliation or entry readiness.
Unresolved evidence continues to block admission under native rules.

Each component shares the runtime shutdown event. Failure or an unexpected early
return sets that event immediately, fencing new entry. Both components receive a
30-second graceful shutdown allowance; remaining tasks are cancelled and awaited
through provider/model child cleanup before leases are released. SIGINT, SIGTERM
and the explicit duration use the same shutdown path. Component failures return a
nonzero CLI result without printing raw provider exceptions or credentials.

Restart reuses the same options.db, venue.db and collector.db. It preserves cash,
play identities, original entries, fills, feed sequence and retained read budgets.
Interrupted native work and entry halts retain their existing review rules. The
runner never automatically resumes entry or resubmits an uncertain order.

## Dashboard and remaining work

The existing dashboard remains a separate stored reader. The check's
dashboard_journal and dashboard_population_id identify the running account to
bind later; no page request starts workers. No Caddy, port, password or existing
review container changes are part of this command. Preserve all review fixtures
and consumed rollback names.

Still required: reviewed operational enrollment/configuration, full contract/data
eligibility, replacement option candidates, Swing catalyst/metadata and runtime-frame delivery,
Scope SPX/context, and a reviewed host deployment/dashboard switch. Then the
operator can verify ongoing operation on the server. The accepted October 26
regular-session quote sample does not need to be recollected to continue coding.
Optional daily/hourly capture and persistence now has its own
[offline implementation](SWING_HISTORY_FEED.md); it does not yet supply Swing signals.
Native original source/seed preparation is also [implemented](SWING_SOURCE_BINDING.md),
with retained blockers and original creation times. Current history is still ineligible.

Offline evidence is recorded in CONNECTED_RUNTIME_PROOF.json. The synthetic native
two-play tests exercise empty and held restarts, including durable fills awaiting
reconciliation. They do not represent trades executed on the uploaded market data.
