# Candidate daily and half-hour history mapping

The uploaded archive (capture SHA-256
`de406f6c478391588f14762d385cffbcb308c27554b053c55b3c68c272498ca8`)
contains successful reads but cannot satisfy the enrolled history policy.
Each daily series has 55 midnight-UTC labels ending October 26; October 27 is
absent. Each hourly series has 47 whole-UTC-hour labels. Complete later sessions
have 14:00–19:00 UTC starts, not the strategy's 13:30–19:30 session-aligned starts.
These are different price intervals. Relabeling the whole-hour prices would change
strategy meaning. The missing daily bar's cause is not established by one capture.

A separate candidate-format proof now requests daily bounds at UTC midnight and
30-minute intraday bars over the exact required session hours. The daily end is
the target session's UTC midnight, never a future time. Thus this proof can run
after that boundary and before the next open; it refuses otherwise before any
provider access. This changes diagnostic requests, not frozen collector settings.

The candidate mapper treats exact midnight daily labels as session-date keys and
binds them to the native calendar's opens/closes. Every expected session must be
present. For hourly history it requires every exact half-hour interval and
combines observed pieces: first open, maximum high, minimum low, last close and
summed volume. The final short session interval stays short. Raw provider bars,
request bounds and original receipt times remain in capture.json; normalized
history binds that complete original capture hash. Missing, duplicate, shifted,
zero-volume and interpolated bars are rejected. No OHLC, volume or absent interval
is invented. The uploaded whole-hour capture remains rejected.

Run the revised proof on the same existing image, with a clean checkout:

```bash
bash scripts/swing-history-proof-host.sh --resampled
```

The host helper accepts only that exact optional flag. The default original
proof remains available. No image rebuild or application deployment is required.
A successful candidate response reports CANDIDATE_HISTORY_MAPPED, not native
collector acceptance. It keeps entitlement UNKNOWN and trading_ready=false.
The normal collector, frozen history settings, original source bindings, account,
entry halts and live routing are unchanged. Do not copy proof history into the
collector or restamp it. Integrating a new mapping into durable collector replay
requires a separate explicit version/compatibility decision after real evidence.

Tests use synthetic complete half-hour series plus the actual uploaded incomplete
daily/whole-hour capture. They cover exact aggregation, bad components, holidays,
short sessions and DST. Real daily date-key and half-hour response acceptance
remains pending; the report from the next proof determines whether this candidate
mapping fits the provider. A changed daily bound is a hypothesis to test, not a
claim that October 27 data is available. Scope/catalyst integrations remain absent.
