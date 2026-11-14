# Dashboard visual balance

The operator's October 24 populated desktop screenshots identified uneven
account/trade card edges and an activity panel beginning alongside the navigation
instead of the decisions panel. This revision removes the inherited section
margin, stretches the two top cards to a common row height and places workspace
navigation above both lower cards. Decisions and recent activity share their
initial top/bottom edges. Activity shows three matching rows by default; expansion
reveals all matching rows in the existing bounded history without stretching the
decisions card. Small screens stack naturally without the desktop minimum height.

Visible copy now uses ordinary account, order and simulation language. Internal
population/source identifiers and the JSON download live under System. Original
trade terms, source clocks, approval/attempt/fill distinctions, costs, unknown/stale
warnings and the paused historical simulation banner remain intact. Original
stored thesis text is never rewritten. No financial, engine or provider behavior
changes; all filtering and expansion stay local to the rendered page.

The operator already activated c2ad7ca successfully; the new refresh action updates
only that reader and reuses v2 read-only. It does not create another fixture.
See [deployment steps](MIXED_DASHBOARD_REVIEW.md#activated-v2-and-layout-refresh).

[Verification](MIXED_DASHBOARD_BALANCE_PROOF.json) records the installed checks and
hashes of the supplied baseline screenshots. Those screenshots prove the populated
baseline was viewed, not that this revision is visually accepted. Updated browser
screenshots and mobile/keyboard interaction review remain pending.
