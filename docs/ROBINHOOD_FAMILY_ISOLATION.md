# Robinhood-only strategy input isolation

The collector previously changed every cycle to MARKET whenever an enrolled
Swing or Scope source was missing. That discarded usable DEGEN inputs.

Missing Scope now remains a coverage issue without vetoing ordinary cycles.
Native active-watch coverage still blocks unsafe shared entry.

Missing Swing sources/history/catalysts now produce an explicit portfolio-only
`swing_unavailable` frame. It cannot contain any Swing stock/option sources or
catalysts. That family produces no candidates. Existing held quote coverage and
Swing quote observation remain available for protection and source retirement.
Native source locks and complete-universe validation remain unchanged when Swing
inputs are supplied. Legacy packets omit the new field and retain their hashes.
Older binaries cannot consume frames with the explicit new field.

Native option planning excludes unavailable Swing; extra quotes retained for
protection cannot enter selection without a current admitted read plan. Stock
selection and subsequent source reconstruction preserve the same absence flag.
Missing stock quotes, failed intraday history and unrelated capture errors still
prevent cycles. No UNKNOWN entitlement is promoted and no missing catalyst is
represented as CLEAR. No account reset, host mutation, new provider, or LIVE
activation is included.

The current profile still needs reviewed option terms/candidates, data entitlement
and usable executable inputs. Its stopped entry halt needs the appropriate
reviewed recovery process. Scope's unsupported input groups and Swing's catalyst
requirement remain explicit limitations of those strategies, not a demand to
purchase another provider. Completing this change is not proof of paper fills.

Validation: the broad 175-test run passed 174 tests with one FixtureProcessFailed
while the local package was being reinstalled. The affected three-case source-
tampering test group then passed. The final 41-test runtime/entry/isolation group
passed after installation. The focused collector/delivery/isolation run passed
44 tests. Tests use offline synthetic fixtures, not current trading acceptance.
