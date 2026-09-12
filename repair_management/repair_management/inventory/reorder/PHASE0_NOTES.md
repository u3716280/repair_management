# Inventory Reorder Analysis — Phase 0 Technical Notes

Status: implemented, pending the manual validation pass described below.

## What this module is

A read-only data foundation under `repair_management/repair_management/inventory/reorder/`
for a future Reorder Analysis engine (Phase 1+). It classifies every Stock Ledger Entry
into one of seven buckets, extracts a trustworthy stock/reserved/incoming/lead-time
picture per `Item + Warehouse`, and flags anything it can't classify confidently instead
of guessing. It makes no writes of any kind.

Modules: `exceptions.py`, `classification.py`, `demand.py`, `stock.py`, `reservation.py`,
`incoming.py`, `lead_time.py`, `validation.py`. See each module's docstring for its
responsibility. All are plain, permission-agnostic Python — callable via `bench execute`
or `bench console`, not exposed as a whitelisted Desk API in this phase.

## Classification rule table

| voucher_type / purpose | classification | notes |
|---|---|---|
| Stock Entry: Material Issue | CONSUMPTION / RETURN (header.is_return) | |
| Stock Entry: Material Receipt | SUPPLY / RETURN (header.is_return) | |
| Stock Entry: Material Transfer | TRANSFER (OUT/IN by leg) | never counted as company consumption |
| Stock Entry: Material Transfer for Manufacture | TRANSFER | internal WIP staging |
| Stock Entry: Material Consumption for Manufacture | CONSUMPTION | BOM raw-material use |
| Stock Entry: Manufacture | SUPPLY (output row) | |
| Stock Entry: Repack | SUPPLY (output) / CONSUMPTION (input) | by actual_qty sign |
| Stock Entry: Send to Subcontractor | TRANSFER (EXTERNAL_CONSUMPTION) | leaves company-controlled warehouses |
| Stock Entry: Disassemble | CONSUMPTION (input) / SUPPLY (output) | |
| Purchase Receipt | SUPPLY / RETURN | historical demand = 0 either way |
| Purchase Invoice (update_stock=1) | same as Purchase Receipt | update_stock=0 never produces an SLE |
| Delivery Note | CONSUMPTION / RETURN | genuine external demand |
| Sales Invoice (update_stock=1) | same as Delivery Note | |
| Stock Reconciliation | ADJUSTMENT always | never demand |
| Subcontracting Order | TRANSFER (EXTERNAL_CONSUMPTION) | included for completeness — verify usage |
| Subcontracting Receipt | SUPPLY | included for completeness — verify usage |
| SLE with actual_qty == 0 | IGNORE | valuation-only rows |
| Unrecognized voucher_type | REVIEW / UNKNOWN_VOUCHER | never guessed |
| Recognized type, no rule matches | REVIEW / UNCLASSIFIED_MOVEMENT | never guessed |

`demand_qty` is always a positive magnitude; net demand is `SUM(demand_qty * net_sign)`
where CONSUMPTION=+1, RETURN=-1, everything else=0 at the company level. Transfers are
still tracked per-warehouse (`transfer_out`/`transfer_in`/`external_consumption` in
`summarize_demand`).

## Exception codes

`UNKNOWN_VOUCHER`, `UNCLASSIFIED_MOVEMENT`, `NEGATIVE_STOCK`, `MISSING_UOM_CONVERSION`,
`LATE_PO`, `CANCELLED_SOURCE`, `ABNORMAL_QTY`, `MISSING_WAREHOUSE`, `MISSING_ITEM`,
`DUPLICATE_SOURCE_ROW` — see `exceptions.py`.

## Automated test coverage

`test_reorder_data_foundation.py` covers: cancel → net demand returns to 0; cancel+amend
supersedes the original; warehouse transfer nets to 0 company-wide but shows correctly on
both warehouse ledgers; partial PO receipt computes correct remaining qty; UOM conversion
(skipped if no alternate-UOM item exists on this site); negative stock raises a warning
without breaking the demand count; Stock Reconciliation is never counted as demand;
duplicate source rows are deduplicated; stock snapshot matches `Bin.actual_qty` exactly;
an unrecognized voucher_type routes to REVIEW.

Run with:
```
bench --site local.147 run-tests --module repair_management.repair_management.inventory.reorder.test_reorder_data_foundation
```

## Manual validation procedure (not automated — do this before starting Phase 1)

1. Pick 5–10 real items from `local.147` covering: regular demand, intermittent,
   slow-moving, transfer-heavy (147↔88), has-returns, partial-PO-receipt, cancel/amend
   history, mixed UOM, negative-stock history, and a brand-new/no-history item. Identify
   candidates via a `bench console` scan grouping Stock Ledger Entry counts/voucher types
   by item over the last 24 months.
2. For each `(item_code, warehouse)` pair, run:
   ```python
   from repair_management.repair_management.inventory.reorder import validation
   rows = validation.build_manual_validation_sheet(
       [(item_code, warehouse), ...], from_date="2024-09-01", to_date="2026-08-31"
   )
   ```
3. Export `rows` to a spreadsheet and manually recompute each column independently
   (by hand or via Desk report filters) to confirm equality.
4. Record the outcome here (append a dated section below) before Phase 1 begins, along
   with anything from the open-items list that turned out to matter.

## Open items verified / to verify empirically

- [x] `Stock Ledger Entry.is_cancelled` exists in this install's schema and is the correct
  cancellation filter (not `docstatus`) — exercised by
  `test_cancel_returns_net_demand_to_zero`.
- [x] `Purchase Order Item.returned_qty` exists in this install's schema.
- [ ] Whether historical POs on this site have `returned_qty` populated correctly for
  returns made before the field existed — check during the manual validation pass.
- [ ] Whether this business actually uses Pick List, Subcontracting Order/Receipt, or
  Repack/Disassemble/Manufacture Stock Entry purposes at all. If unused, the corresponding
  code paths simply always return empty/zero — safe, just worth noting.
- [ ] Whether "Allow Negative Stock" (Stock Settings) is normally enabled on this site, or
  only temporarily toggled by the test.

## Explicit non-changes

This module does not modify `reorder_point_calcul/*` (or its backup copies),
`integrations/line/*`, `hooks.py`, `modules.txt`, or any doctype JSON. No new doctype,
custom field, or database write was introduced.
