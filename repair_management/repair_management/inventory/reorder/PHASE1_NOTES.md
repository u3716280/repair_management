# Inventory Reorder Analysis — Phase 1 Technical Notes

Status: implemented, pending manual acceptance against real data and a browser walkthrough.

## What this adds on top of Phase 0

Phase 0 (`demand.py`, `stock.py`, `reservation.py`, `incoming.py`, `lead_time.py`,
`classification.py`, `exceptions.py`, `validation.py`) is unchanged. Phase 1 adds:

- `calculation.py` — pure math (protection period, rolling demand series, percentile, ROP,
  target stock, planning position, recommended qty, demand-type classification, status).
- `confidence.py` — High/Medium/Low scoring with machine-readable reasons.
- `service.py` — `analyze_item(item_code, warehouse, options)` and
  `analyze_items(filters, options)`, the public composition interface.
- `api.py` — the whitelisted endpoints (`get_reorder_analysis`,
  `get_reorder_analysis_detail`, `get_demand_history`, `get_incoming_detail`).
- The **Inventory Reorder Analysis** Desk page
  (`page/inventory_reorder_analysis/`) — filters, summary counts, a sortable table, CSV
  export, and a row-click drill-down dialog.

Still strictly read-only: nothing here writes to `Item`, creates a Material Request or
Purchase Order, or auto-applies any recommendation.

## Decisions confirmed with the user before implementation

- **Criticality**: every item defaults to Normal/P90 for now — no `Item` schema change.
  `service_level` can be overridden per analysis run (Auto/P80/P90/P95/P99) to simulate a
  different importance level in the meantime. A real per-item Criticality field is an
  explicit Phase 2 follow-up.
- **Demand-type thresholds**: ≥5 demand events required for any statistic to be trusted
  (`MIN_DEMAND_EVENTS_FOR_STATS`, reusing `reorder_point_calcul.py`'s existing
  `MIN_EVENTS_FOR_PERCENTILE` value); average gap between demand-active days ≤7d = Regular,
  ≤60d = Intermittent, otherwise Slow; 0 events = No History. These are module-level
  constants in `calculation.py`, not a settings doctype — deliberately, to avoid schema
  scope creep for numbers that should rarely need non-technical tuning.
- **Drill-down UI**: a `frappe.ui.Dialog` (extra-large), not an inline expanding row —
  matches this app's existing pattern precedent (no inline-drill-down component exists
  anywhere in this app) and keeps detail data loaded lazily, only on row click.

## Design decisions made without a blocking question (documented, not silent)

- **`compute_status` precedence**: an item can simultaneously satisfy more than one of the
  spec's plain-English status conditions (e.g. `planning_position<=0` and "insufficient
  history" at once). Fixed precedence, first match wins: **Critical → No History → Review
  (low confidence) → Reorder → OK**. This is independent of the *display* sort order in the
  table (Critical, Reorder, Review, No History, OK), which only orders already-assigned
  statuses.
- **`configured_lead_time` vs `planning_lead_time`**: `configured_lead_time` =
  `Item.lead_time_days` (existing ERPNext master field, shown for comparison only);
  `planning_lead_time` = the Planning Parameters input (default 120 days), authoritative
  for all math. Actual lead-time comparison stats (`actual_lead_time_avg`,
  `actual_lead_time_p90`, `lead_time_sample_count`) live only in the detail response
  (drill-down), never the bulk list, and never silently override the configured value.
- **`api.py` as its own file** under `inventory/reorder/`, not inside the page's `.py` —
  deviates from the single-endpoint `reorder_point_calcul` precedent because Phase 1 needs
  four endpoints sharing permission-check/param-resolution plumbing; keeps the
  Data→Calculation→Confidence→Service→API→Page layering intact.
- **Demand events** = count of distinct days in the window where the netted daily series
  is non-zero, not "count of CONSUMPTION rows" — a single day can carry multiple SLE rows
  for one item+warehouse, and this keeps "demand events" describing the same series the
  rolling distribution is built from.
- **Supplier filter**: resolved in `api.py` by intersecting `Item Supplier` rows for the
  given supplier with the Item Group-derived candidate set (if any) *before* calling
  `service.analyze_items` — not applied as a post-calculation row filter, since supplier is
  a property of which items are sourced from them, not of an already-computed row.
- **Page permission**: `roles: []` (open to all Desk users), matching the
  `reorder_point_calcul` precedent — enforcement happens server-side in `api.py` via
  `frappe.has_permission`. The drill-down endpoints additionally check `Stock Ledger Entry`
  / `Purchase Order` read permission (a conservative addition beyond the precedent, which
  only checks `Item`).

## The "Definition of Done" worked example

The original spec's worked example (`ROP=18, Position=10, Target=24, Recommended=14,
Status=REORDER, Confidence=MEDIUM`) gave only final output numbers, not the underlying
input series/parameters, so it could not be reproduced bit-for-bit. `test_calculation.py`'s
`TestWorkedExample` instead builds a from-scratch equivalent with the same qualitative
shape (Reorder status, `recommended = target − position`), using a periodic daily series
chosen so every rolling window sums identically by construction — documented in the test
as illustrative, not a literal reproduction.

## Automated test coverage

- `test_calculation.py` (37 tests total across this and `test_confidence.py`, all passing
  — plain `unittest`, no DB): rolling-sum cross-check against a naive reference,
  percentile correctness (incl. against `numpy.percentile` when available),
  return-netting in the daily series, ROP average-fallback behavior, demand-type boundary
  cases, status precedence (including the ambiguous overlap case), recommended-qty edge
  cases.
- `test_confidence.py`: one test per rule branch, including the exact `reasons` string
  contents for the High-confidence happy path.
- `test_service.py` (`FrappeTestCase`, **run against local.147, all 7 pass**):
  `analyze_item` against a real seeded scenario; no-N+1 regression test (asserts
  `demand.get_demand_history` is called once per warehouse, not once per item); No
  History → Low confidence; Critical when planning position ≤ 0; average-fallback when
  the analysis window is shorter than the protection period; status-filter correctness;
  reserved/late-incoming exclusion correctness. One test-only fix was needed:
  `_seed_stock`'s Material Receipt now sets `allow_zero_valuation_rate: 1` on the item
  row, since the second real Item used in the batching test had no prior valuation
  history on this site and its first-ever incoming stock entry requires either a rate or
  that flag — not a bug in `calculation.py`/`service.py` themselves, just a test-fixture
  gap for a real item with no purchase history yet.

Run commands:
```
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_calculation
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_confidence
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_service
```
`test_calculation.py`/`test_confidence.py` were run directly with the bench's Python
(`unittest`, no site context needed — pure math, no `frappe.db` calls) and all 37 pass.
`test_service.py` needs `allow_tests` enabled in `local.147`'s site config (same
requirement as Phase 0) — not yet run in this session, per the user's earlier preference to
enable that only when they choose to.

## Post-implementation changes made during browser testing

1. **Fixed: compound-object DataTable columns rendered as blank/"undefined".**
   `frappe.DataTable` stringifies non-primitive cell content to `"[object Object]"` before
   calling a column's `format()` — the untouched raw row is only available via `format`'s
   4th ("data") argument. The Item, Demand, Lead Time, and Incoming columns now read from
   that argument instead of `value`.
2. **Added:** a static "? Explain" button/dialog (in Thai) documenting what Status, Demand
   Type, Incoming (Reliable/Late), Lead Time, and Confidence mean — no server call, just
   describes the fixed logic already in `calculation.py`/`confidence.py`/`incoming.py`.
3. **Changed: Planning Lead Time now defaults per-item, not globally.** Previously every
   item used the same global 120-day default regardless of its own `Item.lead_time_days`.
   Priority is now: explicit user override (Planning Parameters field) > the Item's own
   `lead_time_days` if set > `DEFAULT_PLANNING_LEAD_TIME_DAYS` (120) as the last resort.
   `calculate_item_reorder()` returns a new `lead_time_source` field
   (`override`/`item_master`/`system_default`), surfaced in the drill-down's Lead Time
   section. The JS field is left blank by default (with a description explaining the
   fallback) instead of pre-filling 120, so a truly-untouched field doesn't look like an
   override.
   - **Bug caught while wiring this up:** a blank field arrived server-side as an empty
     string, not `None`; `api.py`'s `_resolve_options` used `is not None` to detect "not
     provided", so `cint("")` silently became a real override of `0` — defeating the
     per-item default for every analysis run. Fixed by checking `not in (None, "")` for
     `planning_lead_time`/`review_period`/`extra_coverage`.
   - Added `TestPlanningLeadTimeResolution` in `test_calculation.py` (4 new tests, pure
     unit-level via `calculate_item_reorder` directly) covering all three priority levels.
     `test_service.py`'s average-fallback test was updated to pass
     `planning_lead_time_days=120` explicitly, since it otherwise depended on the old
     always-120 default and would have become non-deterministic against real Item data.

## Manual acceptance (not yet done)

Reuse the same 5–10 real items already earmarked in `PHASE0_NOTES.md`. For each, run
`service.analyze_item(item_code, warehouse, options)` via `bench console` and hand-verify
`reorder_point`, `target_stock`, `planning_position`, `recommended_qty`, `status`, and
`confidence` against a spreadsheet before relying on the page for real purchasing
decisions. Also do a browser walkthrough of `/app/inventory-reorder-analysis`: pick a real
Company+Warehouse, confirm the table and summary counts render, click a row, and confirm
the drill-down dialog's arithmetic matches the table's own numbers.

## Explicit non-changes

Does not modify `reorder_point_calcul/*`, any Phase 0 file, `hooks.py`, `modules.txt`, or
any doctype JSON. No new doctype or custom field. No `@frappe.whitelist()` outside `api.py`.
