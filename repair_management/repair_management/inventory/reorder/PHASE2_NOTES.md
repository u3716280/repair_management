# Inventory Reorder Analysis — Phase 2 Technical Notes

Status: implemented, tested, and manually verified in the browser against real production
data (warehouse tree, `Item Reorder`, live analysis/backtest/policy-matrix runs).

## What this adds on top of Phase 0 + Phase 1

Phase 0 (`demand.py`, `stock.py`, `reservation.py`, `incoming.py`, `lead_time.py`,
`classification.py`, `validation.py`) is unchanged. Phase 2 **replaces Phase 1's model in
place** (per the user's explicit decision) and adds:

- `policy.py` — Replenishment Policy classification (`STOCKED`/`INTERMITTENT`/
  `SLOW_CRITICAL`/`BUY_TO_ORDER`/`ONE_TIME`/`NO_HISTORY`/`MANUAL`/`REVIEW`/`EXCLUDE`),
  computed fresh each run from demand stats — no Item schema change.
- `group.py` — Planning Warehouse group resolution and cross-warehouse aggregation (Group
  On Hand, Group Reserved, Total Outstanding PO, group daily demand series).
- `backtest.py` — walk-forward simulation engine (no real documents ever created).
- `metrics.py` — stockout/fill-rate/inventory/stability/outlier/lead-time-mismatch metrics.
- `baseline.py` — avg-demand×lead-time, min/max, and native-ERPNext-reorder-level
  comparators (the last one real and active on this site).
- `calculation.py`/`confidence.py`/`service.py`/`api.py` modified in place; the existing
  Desk page (`inventory_reorder_analysis.js`) updated to match.

## Confirmed facts this design relied on (verified via direct DB query, not assumed)

- `เอกไทย - ET` is a real `is_group=1` parent; `บ้าน 88 - ET` / `บ้าน 147 - ET` are its real
  `is_group=0` children (`parent_warehouse="เอกไทย - ET"`). Pinned as a regression test in
  `test_group.py`.
- `Item Reorder` has 127 real rows (all for `บ้าน 147 - ET`), `Stock Settings.auto_indent=1`
  (ERPNext's native reorder scheduler is genuinely active here). `BUSH-2012-D24` (level
  10.0/qty 10.0) is pinned as a regression test in `test_baseline.py`.
- `Bin.valuation_rate`/`Bin.stock_value` already exist — used for the backtest's inventory
  value estimate with no schema change.
- 30 real `Material Request` docs / 70 items — too sparse for an automated "manual
  practice" baseline; exposed as reference context only (`baseline.get_manual_request_history`).
- `NET_SIGN[TRANSFER] == 0` regardless of which leg/warehouse an SLE row belongs to
  (confirmed by direct code read of `classification.py`) — internal transfers between the
  group's own children need no special suppression at the group level; confirmed
  empirically too, via `test_group.py`'s real-transfer regression test.

## Breaking changes to Phase 1 (all pre-approved, listed so nothing is a silent surprise)

1. **Late Incoming now counts fully toward Planning Position.** `compute_planning_position`'s
   second parameter changed from `reliable_incoming_qty` to `total_outstanding_qty`
   (`reliable_incoming + late_incoming`). Items previously shown Reorder/Critical because a
   late PO's qty was excluded may now show OK/Reorder differently.
2. **Service Level loses P80/P90/P99.** Only `Auto`/`P85`/`P95` are valid now; any other
   explicit `P` value hits a hard `frappe.throw`, not a silent reinterpretation.
3. **Criticality (`DEFAULT_CRITICALITY="Normal"`) is removed entirely**, replaced by
   Policy-driven percentile selection (`SLOW_CRITICAL` → P95, everything else batch-eligible
   → P85). The old `criticality_used`/`is_default_criticality` detail fields are replaced
   by `policy` (a contract field) + `policy_reasons` (detail-only).
4. **The main table is now keyed by `(item, planning_warehouse)`**, which may be a real
   group (one row aggregating every leaf) or a plain leaf (behaves exactly as Phase 1 did).
   A bookmark pointing at a leaf warehouse is unaffected; one pointing at a group warehouse
   (previously returning zero rows, since Bin has no rows for a group) becomes newly
   functional.
5. **Demand Type is no longer the primary batch filter/column** (Policy is), though it's
   kept as a secondary filter (`demand_type` param still honored) and still shown in the
   drill-down.
6. **Default batch scope now excludes 6 of 8 policy values** (`BUY_TO_ORDER`/`ONE_TIME`/
   `NO_HISTORY`/`MANUAL`/`REVIEW`/`EXCLUDE`) unless a specific Item is selected or the user
   explicitly filters for that policy. An item with e.g. exactly one historical demand
   event (previously visible as "Slow") disappears from the default bulk view (now
   `ONE_TIME`).

## Design decisions flagged during design (confirmed or resolved, not hidden)

- **`ONE_TIME` vs `REVIEW`** for exactly-one-demand-event items: resolved to `ONE_TIME`
  (confirmed by the user) — a more useful purchasing signal than lumping it into the
  generic "not enough data" `REVIEW` bucket. Both are batch-excluded either way.
- **`BUY_TO_ORDER`/`MANUAL`/`EXCLUDE` are never auto-derivable** from demand history alone
  — no statistical signal distinguishes "always custom-ordered" from "just currently
  low-demand." They're only reachable via a `manual_policy_override` **request parameter**
  on the single-item drill-down path, never persisted, never applied to a batch run. If the
  business wants these to persist across sessions, that needs an actual schema change —
  explicitly out of scope for Phase 2 per the "no Item schema change" decision.
- **Backtest recompute cadence**: ROP/Target recompute only at each Step Size checkpoint,
  held constant in between (confirmed) — matches how a business would actually operate,
  and gives Step Size a real effect on the simulation.
- **Reserved Qty held constant** for the whole backtest — Bin only stores a live snapshot,
  Stock Ledger Entry has no reservation history, so there's no historical reserved-qty time
  series to reconstruct. Surfaced as an explicit caveat in the backtest result UI, not hidden.
- **Extra Coverage is now a fixed `Select` (30/45/60/90)** (confirmed), not a free Int —
  matches the Policy Matrix's own fixed 4-value axis.
- **Native ERPNext reorder baseline**: reports "not configured" (`None`) for any item with
  no real `Item Reorder` row, rather than fabricating one or summing rows across
  warehouses the business configured independently (confirmed).
- **Stability CV threshold (0.25)** is interpolated from the spec's own two illustrative
  examples (stable ≈0.045, unstable ≈0.52) — a provisional default, not a validated
  statistical result, pinned as an executable test (`test_metrics.py`) against those exact
  two examples so it's visible and revisable.
- **Lead-time-mismatch threshold (30%)**, **outlier detection (IQR/Tukey fence, needs ≥4
  events)**, **fill_rate (qty-weighted) vs cycle_service_level (event-count-weighted)** are
  all stated design decisions in `metrics.py`'s own docstrings, not hidden defaults.

## Automated test coverage

All of the following were run against `local.147` (`allow_tests` enabled, then reverted to
disabled afterward):

- `test_policy.py` (pure `unittest`, 17 tests) — every decision-tree branch, boundary
  cases, `resolve_service_percentile` Auto/override/rejection cases.
- `test_metrics.py` (pure `unittest`, 17 tests) — every formula against hand-built traces,
  including the spec's own two stability examples.
- `test_calculation.py` (extended, 34 tests) — new `compute_planning_position` v2 tests
  (including a direct all-reliable vs all-late vs mixed comparison proving they now
  produce identical Planning Position), `POLICY_TO_PERCENTILE` tests.
- `test_confidence.py` (10 tests) — unchanged from Phase 1, still passing.
- `test_service.py` (extended, 9 tests) — leaf-warehouse behavior (the "group of one"
  case), policy-based default batch filtering.
- `test_group.py` (new, 10 tests) — real `เอกไทย - ET` tree resolution (pinned), group
  aggregation helpers, one-row-per-item-per-group, real inter-child transfer suppression,
  no-N+1 (once per leaf, not per item).
- `test_backtest.py` (new, 9 tests) — pure day-simulation mechanics (order placement,
  no-double-ordering while a prior order is open, receipt on arrival date, stockout
  clamping) plus one real end-to-end `FrappeTestCase` confirming zero real
  Material Request/Purchase Order documents are created by a backtest run.
- `test_baseline.py` (new, 6 tests) — pure formulas, the real `BUSH-2012-D24` `Item
  Reorder` row (pinned), `None` when unconfigured, native-baseline simulation mechanics.

Run commands:
```
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_policy
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_metrics
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_calculation
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_confidence
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_service
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_group
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_backtest
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_baseline
```

## A pre-existing, unrelated issue found (and partially fixed) during verification

Re-running Phase 0's own `test_reorder_data_foundation.py` (untouched by Phase 2) surfaced
a real bug in its `_seed_stock` helper: it was missing `allow_zero_valuation_rate: 1` on
its Material Receipt (the same fix `test_service.py`/`test_group.py` already needed for the
same reason). **Fixed** — this one-line omission was a genuine, safe correction.

After that fix, 5 of that file's 10 tests still failed with inflated demand counts (e.g.
`gross_consumption` of 13/16/130 instead of the expected 5/3/0). Root cause: the test picks
"the first stock item found" (`frappe.get_all("Item", ..., limit_page_length=1)[0]`) with
no `order_by`, and analyzes a window including **today** — if that real, arbitrarily-picked
item already has real production Stock Ledger Entries today (unrelated to the test), those
inflate the counts. This is a **pre-existing fragility in Phase 0's test design** (it
depends on live production data staying quiet on whatever item happens to be picked, which
becomes less reliable as the business's real daily transaction volume grows) — not
something Phase 2's changes caused, since `demand.py`/`classification.py`/this test file's
core logic were never touched this phase. Fixing it properly would mean redesigning Phase
0's test fixture strategy (e.g. anchoring to a dedicated non-production-active item), which
is out of scope for Phase 2 — flagged here for a future session rather than silently
patched over or left unmentioned.

## Manual acceptance

- **Done** — Browser walkthrough: Planning Warehouse = `เอกไทย - ET`, `มู่เล่ย์ SPZ-1 ร่อง`
  item group: confirmed one row per item (3 items, not 6), group aggregation columns
  populated, Policy badges rendered, drill-down verdict/policy/leaf-warehouse/Purchase
  Follow-up sections all correct, late PO counted fully into Planning Position (`25 + 3 -
  0 = 28`).
- **Done** — Ran Backtest and Policy Matrix (8 combos) via the page for
  `PU-1-SPZ-106mm-1610-0-MT` (`SLOW_CRITICAL`): both render without error.
- **Done** — Confirmed P95 gives a tighter (larger) ROP/Target than P85 for the same
  `SLOW_CRITICAL` item, by explicitly overriding Service Level and comparing the analysis
  table row: P85 → ROP 5 / Target 7; P95 (Auto, policy-driven) → ROP 7 / Target 8.
- **Done** — Found and fixed a real gap during this verification pass: `baseline.py` was
  fully written and unit-tested but never actually wired into `backtest.run_backtest`'s
  result or the JS UI, so the backtest page had no baseline-comparison table at all,
  contradicting the plan's own architecture note and UI section. Fixed by adding a
  `baselines` key to `run_backtest`'s return value (avg-demand×lead-time, min/max, and —
  when a real `Item Reorder` row exists — a full native-ERPNext-baseline simulation run
  over the same actual-demand series) and a new `render_baseline_comparison()` section in
  the JS. Re-verified `test_backtest.py` (9/9) and `test_baseline.py` (6/6) still pass
  after the change (`allow_tests` toggled on/off around the run, per the established
  pattern).
- **Done** — Confirmed `BUSH-2012-D24`'s native-ERPNext-baseline comparison (at `บ้าน 147 -
  ET`) shows its real configured `warehouse_reorder_level=10.0`/`qty=10.0` in the page's
  new Baseline Comparison table, matching the pinned `test_baseline.py` regression test
  exactly.
- **Not done** — hand-verifying 3–5 consecutive simulated backtest days against a
  spreadsheet by hand. `test_backtest.py`'s `TestSimulateDay` class already covers the
  same day-simulation mechanics with hand-computed expected values per test case, which
  substantially overlaps this item; a full multi-day spreadsheet cross-check was not done
  and is left as an optional follow-up if deeper confidence is wanted.

## Explicit non-changes

Still fully read-only — `backtest.py`/`baseline.py` never call `.insert()`/`.submit()` on
any doctype (verified by `test_backtest.py`'s document-count assertion). No Item schema
change. `Item.lead_time_days` is validated against actual history but never auto-corrected.
