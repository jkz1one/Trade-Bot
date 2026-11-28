# Versioned production Swing history mapping

The daily date-key / exact half-hour mapper now has a production path in
`app.mixed.swing_bar_mapping`. Opt-in is
`swing_history.bar_mapping = "utc-day-halfhour-v1"`. Existing configurations default
to `session-aligned-v1`; that default is omitted from serialization, preserving
existing frozen policy hashes and legacy capture replay.

The collector plans, normalizes, persists and revalidates history with the mapping
for the history's target session. This matters after UTC midnight but before New
York midnight: current quote policy belongs to the current New York date, while
preparation belongs to the next exchange session. Reopening stored history uses
its target's retained policy, never whichever mapping happens to be current.

The existing exact-hash future-session rollover now permits changing only this
mapping field within an already enrolled Swing history policy. Lookbacks, history
enrollment, polling, credentials, stock universe and all other transport fields
remain frozen. An existing target history/source receipt prevents rollover, so no
original history is reinterpreted. Duplicate, same-day and unreviewed updates are
still rejected. This uses the same collector, owner and bankroll; it does not
reset an account, clear a halt or start a worker. Old binaries cannot parse the
new explicit field and must not be used against an enrolled new-mode receipt.

Application deployment is required before enrolling this production mode. The
separate proof helper still reuses the earlier host image and does not enroll
anything. The host's current base policy remains legacy; no server change was
performed from this workspace. Prepare a proposed future-session policy through
the existing review/apply path, not by editing the frozen base policy in place.

Native mapping requires complete calendar coverage, original noninterpolated
positive-volume bars and exact request/receipt identity. Half-hour aggregation
preserves observed OHLCV and original capture hashes; final short intervals remain
short. Daily midnight labels are session-date keys. Missing completed daily bars
still block history, and UNKNOWN entitlement still blocks source preparation.
No closed-day price is fabricated to replace the real uploaded placeholders.

Validation covers native capture persistence/reopen, rejected placeholders,
unchanged legacy serialization, calendar-specific policy selection, and an actual
review/apply rollover with unchanged owner bytes. Full existing collector,
rollover, connected-runtime and profile suites run against the installed wheel.

## External inputs still missing

The captured Robinhood gateway exposes equity quotes/history and option
chains/instruments/quotes/history. It provides no reviewed catalyst/news mapping,
SPX history mapping, dealer structure or options-flow source in this integration.
Scope explicitly requires nine coverage groups plus SPX/SPY/QQQ history and SPXW
contract/session data. The profile still names unavailable Scope sources. Swing
requires catalyst evidence with a known source, timestamp, status and coverage
horizon; an empty news response cannot be turned into CLEAR.

Those adapters cannot be called complete without an identified source contract
and representative original payloads. No endpoint, credential, data entitlement,
CLEAR verdict or provider shape was invented here. This release finishes the
versioned production history connection; it does not finish the other strategy
source integrations or paper-trading readiness.
