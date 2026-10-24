# Hybrid mixed dashboard

The October 24 supplied `Trade-Bot-Hybrid-Dashboard-Plan.html` (SHA-256
`1b7962cb3d90f22b82bb66b18c81165bf3aac7f46786e5f071835fe9dade338d`)
is the design direction. Its older cc990cf/v1.110 baseline is superseded by the
verified 77e69c6/v1.111 handoff. The repeated attachment is byte-identical.

The mixed reader now has a compact account header, three family identity tiles,
persistent account equity and active trade, four separate recorded stages, five
workspace tabs and a bounded recent activity list. Trade Summary / Thesis /
Protection / Fills & costs tabs keep the native stop and required exit outside the
local panels. Existing original terms, exact costs, observations and verified
receipts remain accessible. The legacy option-only template/style/script remain
unchanged. The mixed stylesheet consolidates its own tokens rather than extending
the legacy cascade.

## Stored-field mapping

| Display | Source | Units, clock and completeness |
| --- | --- | --- |
| Equity, cash, settled, reserved, known allocations | Existing mixed report fields of the same names | Exact Decimal strings; overview dollars rounded to two decimals only; original values in API/cost details. Equity remains withheld on stale, unknown-cost, unresolved or incomplete evidence. Snapshot and observation clocks are separate. |
| Recorded equity | `points` through the existing `history_chart` | Last 20 / last 50 / all of at most 100 records. Record-order axis, complete flat boundaries only; nulls and isolated points preserved. Each range is separately computed from the original points, never interpolated. Exact UTC/value/reason table remains available. |
| Active trade | `position`, verified original `entry`, retained `details` | Total basis and gross stored bid value, actual shares/contracts; contract identity/multiplier from stored native contract. Option premium never becomes an underlying rail marker. |
| Required exit and stop | `position.exit_at`, `exit_reason`, `issue`, `original_stop`, `active_stop` | Always outside local trade tabs. Passed deadline is not a fill or failed-exit conclusion. Original terms remain inspectable. |
| Four stages | Paged `decisions[0]`, or latest retained order when no decision exists | Link only matching `intent.source_key` and client identity. A historical decision cannot adopt an unrelated latest order. Missing/ambiguous links remain incomplete. No model proposal is invented for deterministic records. |
| Family tiles/filter | Stock `intent.family` or option `intent.entry_lineage.family` | Latest attributed order in this bounded view, not current process/watch status. Filter affects only order cards; account-wide equity, decisions, fills and activity stay unchanged. Missing saved family resets to All. |
| Activity | Current bounded decisions/orders, verified order observation fills, cost rows | Up to 40 derived rows, eight initially visible, explicit event filter and expansion. Fill activity requires verified accounting. Order links use exact client identity. This is not a complete audit log; independent protection remains visible on the trade card. |
| System | Existing health, captured/observed clocks, supervision, halt, issues, enrollment | Recorded state only; HTTP response does not prove worker liveness. Critical degraded evidence is also surfaced above the main row. |

The display mapping is pure and opens no database, owner or provider. The observer's
native validation remains unchanged. Chart, family and tab actions only inspect
already rendered records; no background fetch or presentation timer exists.
Display times use America/New_York, with UTC retained in tooltips and exact records.
Frozen reviews suppress optional refresh timers; normal historical pagination keeps
its existing no-refresh behavior. Explicit refresh reloads stored evidence only.

## Remaining data and visual work

Mixed candidate/Scope watch projection, continuous marked equity, complete mixed
benchmarks, closed-trade cohorts, lifetime win rate/drawdown and family performance
attribution are not implemented by this presentation slice. Their absence is
explicit. Activity is bounded derived evidence rather than a complete protection
and audit-event projection. No strategy or execution rule was changed to populate
those surfaces.

No-JavaScript pages retain evidence; all exact range data is available in the All
table. Shared accessible tabs preserve Arrow/Home/End navigation, population-scoped
state and hash reveal. The mixed enhancement adds exact-point focus/tap inspection,
family filtering, activity filtering and disclosure state. Small screens stack the
main panels, scroll the tabs and expose exact rail levels. Print styles show panels
and disclosures without duplicating three chart ranges.

Installed verification is recorded in [the hybrid proof](MIXED_HYBRID_PROOF.json).
Logic tests and generated HTML do not establish browser acceptance. Actual desktop
1440x900/1280x800, tablet 768x1024 and mobile 390x844/320px screenshots, keyboard,
clipping and contrast review remain pending on an allowed browser surface. The
previous loopback/workspace browser restrictions are not bypassed. This UI has not
been deployed on the host.

## Retained host failure

The operator's 77e69c6 preparation built the image, then failed at
`review-first-entry`. Activation never ran. Journal evidence records native
approval, `STOCK_ATTEMPT_STARTED`, `FixtureProcessTimeout`, status `UNKNOWN` and
halt `UNCERTAIN_STOCK_ATTEMPT`. Retained venue evidence establishes exactly one
accepted OPEN simulated stock order, zero fills, submit_count 1 and unchanged
$1,000 cash. This is accepted-before-acknowledgment uncertainty, not an approval
rejection or proof that nothing reached the venue.

Two subsequent worker-import-only probes completed in 0.818 and 1.318 seconds.
They do not establish the initial timeout's underlying cause and omit imports
performed during native operations. Cold storage, scheduling, later imports,
response handling and process exit have not been isolated. Do not extend the
five-second deadline, change approval clocks, replay the source key, resume the
halted fixture, delete the directory or rerun preparation based on these probes.

The new [diagnostic](../scripts/dashboard-review-diagnose.py) copies only the
retained SQLite files to private temporary storage, reports hashes and acceptance
counts, measures the full worker/engine import, then sends a native **snapshot**
request to the copied venue. It measures first stdout, EOF and process completion.
The separate 20-second diagnostic observation window does not change native
execution policy. It submits no order, fills nothing, attaches no execution owner
and checks original source bytes remain unchanged. Run network-disabled with no
credentials and a read-only evidence mount using the already built 77e69c6 image:

```bash
docker run --rm -i --network none --init --read-only \
  --user 10001:10001 --cap-drop ALL \
  --security-opt no-new-privileges:true --memory 512m --pids-limit 64 \
  --tmpfs /tmp:size=64m,mode=1777 \
  --mount type=bind,src=/var/lib/trade-bot-dashboard/ui-review-v1,dst=/evidence,readonly \
  --mount type=bind,src=/opt/trade-bot-dashboard,dst=/review-source,readonly \
  trade-bot-dashboard:77e69c60d87336e608d17bf6427eddb00a575a33 \
  python -I -W error /review-source/scripts/dashboard-review-diagnose.py --source /evidence
```

Fetch the diagnostic revision into the separate dashboard checkout before running
this command. It does not build, activate, restart or modify any service. Further
host evidence is required before choosing a correction. The original deployed
experiment, existing dashboard/password/Caddy route, main and draft PR remain
unchanged by this work. LIVE and authenticated provider/model/broker calls remain
disabled; no prospective PAPER runtime is authorized.
