# Reviewed November 12 Robinhood schema revision

Reviewed November 13, 2026 America/New_York. Implementation:
`194563c0616ad5146f172f9d9fa061c8c5d38801`.

## Observed incident

The operator's deployed d2046f6 controller recorded three capture-session failures
for November 12 before preparing a receipt or launching a worker. Saved context
captures identify VALIDATE_PLAN, nested ExceptionGroup/ValueError causes, and zero
market-read attempts. The expected metadata digest was
`d6a6d50fb64753b33658f310fcc0ca211ab018194c075fa8f952f5d0597f7a15`;
authenticated discovery observed
`dc15d335d30cd024e60910982942cf27d4c51dd83651630630c6b6e1cfa27718`.
This is a confirmed schema-compatibility blocker, separate from the loaded-journal
dispatch-latency failure. The November 11 controller also recorded preparation
failures, but this evidence does not establish their exact cause.

## Exact review

The equity-history top-level description matches the previously reviewed
November 4 revision. Relative to that revision, the only changes are the interval
parameter descriptions of get_equity_historicals and get_option_historicals.
Both add that there is no 15minute interval and that three 5minute bars are used.
No parameter names, required fields, types, additionalProperties rules, output
schemas, capability annotations or other tool metadata changed.

Applying the two operator-supplied complete descriptions to the retained
November 4 fixture reproduces the full observed six-tool digest exactly. The
small delta fixture records this provenance and both digests; no observed capture
time was supplied, so tests retain their base fixture clock rather than fabricate
a new observation timestamp.

The gateway now recognizes exactly three reviewed metadata hashes. Different
revisions must first satisfy this exact allowlist, then match outside the three
reviewed description locations (one top-level description and two interval
parameter descriptions). An arbitrary description change or actual argument/output
change remains blocked. Every read still validates its arguments and original
response. Stored discovery, enrollment and raw captures retain their original
hashes and timestamps. The current strategy already derives fifteen-minute
confirmation from three completed five-minute bars; no strategy rewrite is needed.

## Verification

The unchanged application failed ten new compatibility/capture cases, reproducing
the blocker. After the fix, **502 installed-package tests pass with zero failures
and zero skips**. Coverage includes every pair of reviewed revisions, unreviewed
descriptions and structural changes, invalid outputs, worker and parent capture,
full synthetic catalog capture, preserved original clocks, and collector restart
without enrollment changes. Related mapping, Swing, session and host tests pass.
All 331 application files match source, wheel and installation; all 60 runtime
pins match and the dependency check passes.

See [PAPER_SCHEMA_REVISION_20261112_PROOF.json](PAPER_SCHEMA_REVISION_20261112_PROOF.json).
Tests used synthetic providers and an isolated network namespace. These are not
new successful Robinhood reads or connected session acceptance.

## Host boundary

Publishing this fix does not update the d2046f6 host image or its pinned daily
schedule. Existing discovery.json and account/configuration files do not need to
be replaced. Rollout must use a clean pinned release and the existing guarded
installation path, preserving native state, limits, prior timeout review and
failed-day retry counts. A day that already exhausted its three preparation
attempts is not automatically retried by this change. No deployment, account
reset, schema-file rewrite, resume, provider/model call or limit change was made.
The separate A2/A4/A6 capacity and full-duration acceptance gates remain open.
