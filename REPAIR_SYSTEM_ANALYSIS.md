# Repair System Analysis

Analysis of the core repair-flow doctypes — `Repair List`, `Repair Item List`, `Repair Sympton` —
under `repair_management/repair_management/doctype/`, plus the fixes applied as a result.

## Doctype model

- **Repair List** — submittable header doc. Naming series `REPR-.YY.MM.-.###`. Key fields:
  `supplier`, `company`, `from_warehouse`, `target_warehouse`, `posting_date`, `items` (child
  table), `remarks`, plus a hidden system-managed `status`
  (Draft/In Repair/Partial Returned/Returned/Cancelled) and a hidden `returned` flag/`returned_date`.
- **Repair Item List** — child table only (no standalone permissions/list). Fields: `item_code`,
  `item_name`/`uom`/`image` (fetched), `serial_no` (editable only when the item is serialized),
  `qty`, `symptom` (Link → Repair Sympton, required), row-level `status`
  (In Progress/Free/Charge/No Repair), `remark`, `returned_qty` (running received total). There is
  no `batch_no` field, despite the controller having historically probed for one.
- **Repair Sympton** — trivial master doctype, single field `sympton_name` (autoname = itself,
  `quick_entry: 1`, System Manager only). The "Sympton" misspelling is consistent throughout the
  codebase (doctype name, field name) — not a typo to fix.

Relationship: Repair List 1—* Repair Item List (embedded child rows) *—1 Repair Sympton (Link on
each row). No direct Repair List ↔ Repair Sympton link; no reverse links on Repair Sympton.

## Status / workflow model

No Frappe `Workflow` doctype is used (`states: []`). All transitions happen in Python via
`db_set`:

- `Draft` (implicit initial value)
- → `In Repair` on submit, after an outbound Stock Entry (Material Transfer,
  `from_warehouse → target_warehouse`) is created for every row
- → `Partial Returned` / `Returned` from the whitelisted `receive_return()` RPC, depending on
  whether every row's `returned_qty` has caught up to `qty`
- → `Cancelled` on cancel (always set, independent of whether the stock reversal succeeded)

The `status` field is hidden + read-only in the form — users cannot set it manually. Row-level
`status` on Repair Item List (In Progress/Free/Charge/No Repair) is a separate state machine for
repair outcome/billing category, only tied to the parent status via `receive_return()`'s
aggregation.

## Core business logic (`repair_list.py`)

- `validate()` requires supplier/company/from_warehouse/target_warehouse, then runs
  `_validate_items()`: ≥1 row, `item_code` required, serialized items need a matching `serial_no`
  count with no in-doc duplicates, `symptom` required per row, `uom` auto-filled from the Item
  master.
- `on_submit()` creates/submits the outbound Material Transfer Stock Entry and sets
  `status = "In Repair"`.
- `on_cancel()` reverses only the *outstanding* qty (`qty - returned_qty` per row, not the original
  qty) back `target_warehouse → from_warehouse`.
- `receive_return(docname, selected_idx, qty_map, item_status_map, use_global_status,
  global_status)` — the whitelisted RPC behind the form's "Return" button. Validates the doc is
  submitted and per-row remaining qty, requires serialized rows to be received in full (no
  partial-serial tracking), sets row status, submits an inbound Material Transfer Stock Entry,
  updates `returned_qty`, then recomputes and sets the parent's aggregate status.

This reversal-of-outstanding-qty-only behavior is covered by `test_repair_list.py`'s two tests
(`test_cancel_after_partial_return_reverses_only_outstanding_qty`,
`test_cancel_without_any_return_reverses_full_qty`), which assert warehouse bin quantities land
back exactly at baseline in both the partial- and zero-return cancel cases.

## Client-side (`repair_list.js`, doctype-folder version — the one actually loaded)

A single "Return" button (under an "Actions" group), shown only when `docstatus === 1` and status
is `In Repair`/`Partial Returned`. Opens a dialog listing outstanding rows with editable return-qty
and per-row/global status, forces serialized rows' return qty to the full remaining amount
client-side, and calls `receive_return` on submit, then reloads the doc.

A second, unrelated prototype (`public/js/repair_list.js`, top-level) is dead code — its `hooks.py`
wiring (`doctypr_js`, misspelled) is commented out, so it never loads.

## Cross-subsystem integration

Despite sharing an app with the LINE integration, the repair system is functionally isolated: no
references to `repair_list`/`repair_item_list`/`repair_sympton` exist in `api.py`, the LINE
integration package, LINE patches, or `line_send.py`. The only real integration point is the
standard ERPNext Stock module — `repair_list.py` creates/submits `Stock Entry` (Material Transfer)
documents directly.

## Does cancelling a Repair List cancel the original Stock Entry?

**No.** `on_cancel()` never references the original outbound Stock Entry (or any inbound ones from
`receive_return`) — there's no stored link back to them, and no custom field anywhere ties `Stock
Entry` back to `Repair List`. Instead, it creates a **new, separate** Stock Entry that reverses only
the outstanding qty. Net effect: stock *quantities* end up correct, but the original transfer(s)
stay `Submitted` forever, with no document-level trace connecting them to the (now cancelled)
Repair List.

## Fixes applied

### 1. Silent stock-reversal failure on cancel

**Problem:** if `_make_cancel_reversal()` raised inside `on_cancel()`, the failure was caught and
only shown via an ephemeral `frappe.msgprint()` — nothing persisted once the user navigated away,
even though the Repair List still got force-marked `Cancelled` and outstanding stock could be left
stuck in `target_warehouse` with no record explaining why.

**Fix:** the exception is now logged to the Error Log (`frappe.log_error` with full traceback), a
permanent Comment is added to the Repair List's timeline describing the failure and pointing to the
Error Log, and the on-screen warning is a red msgprint referencing that comment. On success, a
Comment is also added recording which Stock Entry was created for the cancel-reversal, closing part
of the traceability gap.

### 2. `get_indicator()` NameError bug

**Problem:** `get_indicator()` called `_(self.status or "Draft")` but the module never imported `_`
from `frappe` — this would raise `NameError` if the indicator were ever actually invoked
server-side.

**Fix:** added `from frappe import _` to the top-level imports.

### 3. Dead code removal

- `before_save()` — removed entirely; it only ever wrote to a `summary` field that doesn't exist in
  the schema, so it was a permanent no-op.
- `last_stock_entry` writes — removed from both `on_submit()` and `receive_return()`; the field
  doesn't exist in the schema.
- Non-actionable batch warning in `_validate_items()` — removed the branch that always warned
  "ควรเลือก Batch No." for batch-tracked items, since there is no `batch_no` field on Repair Item
  List for a user to ever satisfy it. Removed the now-unused `has_batch` lookup alongside it.

### Left as-is

- `ALLOWED_SYMPTOMS = None` — an inert, documented extensibility hook (the inline Thai comment
  explains how to populate it if the org wants an enforced symptom allow-list), not a bug.

## Third round of fixes

A follow-up re-read of the post-fix `repair_list.py` surfaced five more issues, all fixed:

### 1. Orphaned draft Stock Entry on submit failure

**Problem:** `_make_material_transfer()`, `_make_cancel_reversal()`, and the inbound Stock Entry in
`receive_return()` each did `se.insert()` then `se.submit()`. If `insert()` succeeded but `submit()`
failed (e.g. a stock validation error), the draft (`docstatus=0`) Stock Entry was left behind in the
database, unreferenced by anything — most visibly in `on_cancel()`, where the failure is caught and
doesn't roll back the transaction.

**Fix:** added a shared `_insert_and_submit_se()` helper that deletes the just-inserted draft before
re-raising if `submit()` fails, so a failed reversal/transfer no longer leaves orphaned records. All
three call sites now go through it.

### 2. `_` shadowing footgun in `on_cancel()`

**Problem:** `on_cancel()` reused `_` as a throwaway variable name (`_ = getattr(self,
"from_warehouse")`), which — now that `_` is the imported `frappe` translation function (fix #2 from
round two) — would shadow it for the whole method if a translated string were ever added there.

**Fix:** removed the lines entirely rather than renaming; they never guarded anything real (both
fields are already required by `validate()`, and `getattr` without a default doesn't raise for a
real schema field).

### 3. Dead `chosen_count` variable

**Problem:** `receive_return()` incremented `chosen_count` but never read it afterward.

**Fix:** removed.

### 4. Float equality check for serial full-return

**Problem:** the serialized-item check used strict `row_qty != remaining`, fragile for float
comparisons.

**Fix:** changed to a tolerance check, `abs(row_qty - remaining) > 1e-6`.

### 5. No locking around concurrent `receive_return` calls

**Problem:** two near-simultaneous `receive_return` calls on the same document (e.g. a double-click)
could both read the same `returned_qty` before either wrote, both pass the `row_qty > remaining`
check, and jointly overshoot the item's remaining quantity.

**Fix:** the whole function body now runs under Frappe's file-based document lock
(`doc.lock(timeout=5)` / `doc.unlock()` in a `finally`), keyed on `doctype:name`. A second concurrent
call gets a friendly Thai "already being processed, try again" error instead of racing.

## Fourth round of fixes

A pass focused specifically on the "receive return" flow (`receive_return()` server-side, plus the
"Return" dialog in `repair_list.js`) surfaced one more real correctness bug, fixed:

### `returned_qty` update loop decoupled from the actual transfer loop

**Problem:** `receive_return()` had two separate loops over `doc.items`, meant to act on the same
set of rows, but using different eligibility logic:

- **Loop 1** (builds `items_to_return`, the rows that go into the Stock Entry) silently skips a row
  when `remaining <= 0` (already fully returned) or `it.item_code` is blank.
- **Loop 2** (updates `returned_qty`) re-derived eligibility independently from `selected_idx`/
  `qty_map` only — it never re-checked `remaining <= 0` or `it.item_code`.

So if `selected_idx` included a row that loop 1 silently excluded (already fully returned, or a
blank child row) while `qty_map` still carried a positive value for that row's index, loop 2 would
still `db_set("returned_qty", ...)` for it — incrementing the recorded return quantity with **no
corresponding Stock Entry ever created**, desyncing `returned_qty` from actual stock movement and
potentially flipping the parent status to `Returned`/`Partial Returned` incorrectly. The "Return"
dialog itself always filters out fully-returned rows before building `qty_map`, so a well-behaved
client never triggers this — but `receive_return` is a whitelisted RPC reachable from the API or a
stale/cached client, so this was a self-consistency bug in the function's own logic, independent of
the round-three locking fix (which only prevents two full calls from overlapping, not the two loops
within a single call from disagreeing).

**Fix:** loop 1 now also records `qty_by_idx = {idx: row_qty}` for every row it actually includes in
`items_to_return`. Loop 2 no longer re-derives eligibility at all — it reads `returned_qty`
increments strictly from `qty_by_idx`, so `returned_qty` can only ever advance by exactly the
quantity that was actually included in the submitted Stock Entry.

All changes are in `repair_management/repair_management/doctype/repair_list/repair_list.py`.
Verified with `python3 -m py_compile` and an `ast.parse` structural check; no automated test run
across any of the four rounds (site's `allow_tests` is off — this is the live production site with
no dev/staging environment, and running tests was deferred per request each time).

## New feature: Target Warehouse scoped to Supplier

**Request:** when a Supplier is selected on a Repair List, the Target Warehouse should be restricted
to warehouse(s) owned by that supplier.

**Investigation:** no structured Warehouse↔Supplier link existed anywhere in the bench (checked
ERPNext's core `Warehouse` schema and all `Custom Field` records — neither had one). The only hint of
ownership was an informal naming convention: warehouses named `รง.<name>` (e.g. `รง.AC.Tech`,
`รง.Pioneer`, `รง.Fujiki`, `รง.Muller`) loosely mirror some Supplier names, but inconsistently — casing
differs, some warehouses combine two suppliers (`รง.ไท้เฮง - TH/KL`), and most of the ~43 suppliers
sampled had no matching warehouse at all. So a real data model had to be added first; this needed two
decisions, made with the user before implementing:

- **Enforcement:** soft only — the dropdown filters, but nothing blocks save if they don't match
  (chosen over a hard block, since most suppliers currently have zero warehouses assigned and a hard
  block would have prevented creating Repair Lists for them immediately after rollout).
- **Backfill of the ~31 existing warehouses' Supplier value:** left for the user to assign manually
  (via the Warehouse list/bulk edit) rather than auto-guessed from the unreliable `รง.*` naming
  convention.

### What was built

1. **New patch** `repair_management/patches/repair_target_warehouse_supplier_v1/` (`apply.py`/
   `check.py`/`revert.py`/`howto.txt`, following the same one-off `apply`/`check`/`revert` convention
   as the existing LINE patches) — adds an optional `custom_supplier` Link-to-Supplier field on
   **Warehouse**, via `create_custom_fields`. Already run on `local.147`
   (`bench --site local.147 execute repair_management.patches.repair_target_warehouse_supplier_v1.apply.apply`)
   — field exists, 31 warehouses total, 0 assigned yet.
2. **`repair_list.py`** — new `_warn_if_target_warehouse_mismatched_supplier()`, called from
   `validate()`: a non-blocking orange `msgprint` if `target_warehouse` is assigned (via
   `custom_supplier`) to a different supplier than the document's `supplier`. Silently no-ops if the
   field doesn't exist yet (`frappe.get_meta("Warehouse").has_field(...)` guard, so the code stays
   safe even before the patch is applied) or if the warehouse has no supplier assigned.
3. **`repair_list.js`** — `target_warehouse`'s dropdown now uses `frm.set_query` to filter to
   warehouses where `custom_supplier` is either the selected supplier or still blank/unassigned
   (`["custom_supplier", "in", [frm.doc.supplier, ""]]`), re-applied on `refresh` and whenever
   `supplier` changes. Because no warehouse has a supplier assigned yet, this changes nothing visible
   today — as suppliers get assigned to specific warehouses, the dropdown narrows automatically for
   that supplier while still showing all not-yet-assigned warehouses to everyone else.

Verified with `python3 -m py_compile` (patch files + `repair_list.py`) and `node --check`
(`repair_list.js`); the patch's own `check.py` confirmed the field was created. No automated
Frappe test run, same tradeoff as the four rounds above.

## Fifth round of fixes — fresh re-analysis after the Target Warehouse feature

A full re-read of the current `repair_list.py`/`.js` (post all prior rounds) turned up five new
issues. Three were fixed this round; two were deliberately left as informational/lower-priority.

### Fixed

1. **Qty validation was skipped entirely for serialized rows.** In `_validate_items()`, the
   `qty <= 0` check only applied `and not has_serial` — so a serialized row could carry a
   **negative** `qty` (schema has no `non_negative` constraint on the `Repair Item List.qty`
   field, confirmed via the doctype JSON) with no validation error at all, and any *nonzero* `qty`
   for a serialized row was never cross-checked against the serial count (only `qty == 0` triggered
   an auto-set). A bad negative-qty row could reach `_make_material_transfer` and create a
   negative-quantity Stock Entry on submit; later, `on_cancel`'s reversal (`_make_cancel_reversal`)
   explicitly skips rows where `remaining <= 0`, so that bad movement would never get reversed on
   cancel either.

   **Decision with the user:** rather than widening the `serial_no` field (see #2 below), the fix
   is a business rule — **a serialized row must have exactly one serial number and `qty == 1`**.
   `_validate_items()` now: requires exactly one serial in `serial_no` (errors if more/less),
   auto-sets `qty = 1` when left blank, and throws if `qty` is explicitly anything other than `1`
   (covers the negative-qty case directly, since `-5 != 1`). Needing more than one unit of a
   serialized item now means adding another row, one serial each.

2. **`serial_no` field type can't actually hold multiple serials.** `Repair Item List.serial_no`
   is `fieldtype: "Data"` (single-line, ~140-char input) — but the old validation/`receive_return`
   logic parsed it as newline-separated multiple serials (`.split("\n")`), which isn't achievable
   through the standard Desk grid editor (Enter doesn't insert a newline in a Data field). Rather
   than changing the field type, this is now moot: fix #1's "exactly one serial number, qty must
   be 1" rule means the field only ever needs to hold a single value, which a Data field handles
   fine. Field left as-is per the user's explicit decision.

3. **`on_cancel` didn't take the same lock `receive_return()` uses (race condition).**
   `receive_return()` acquires `doc.lock(timeout=5)` before touching anything, to serialize
   concurrent return requests on the same document. `on_cancel()` never did — so a cancel landing
   at the same moment as an in-flight `receive_return()` could read a stale `returned_qty`
   snapshot and create a reversal Stock Entry for qty that the in-flight return was also about to
   move, double-reversing the same units back to `from_warehouse`.

   Note: the *ordinary* (non-racing) case — cancelling a submitted document that already has a
   partial return — was already correct and is covered by
   `test_cancel_after_partial_return_reverses_only_outstanding_qty`; nothing needed to change
   there. The fix is purely about mutual exclusion: `on_cancel()` now calls `self.lock(timeout=5)`
   at the very start (throwing a clear Thai retry message on `frappe.DocumentLockedError`,
   mirroring `receive_return()`'s own message), and releases it via `self.unlock()` in the same
   `finally` block that sets `status = "Cancelled"` — so cancel and return can never interleave on
   one document; whichever request arrives first runs to completion, the other gets a clean,
   retryable error instead of silently racing.

### Left as informational (not fixed this round)

- **`has_serial_flag`** — a `Check` field on `Repair Item List` that's never read or written
  anywhere in the app (grepped `.py`/`.js`, zero hits). The code always re-derives serial status
  live from the Item master (`frappe.db.get_value("Item", ..., "has_serial_no")`) instead. Dead
  schema, harmless.
- **`_make_material_transfer`'s `"qty": it.qty or 1` fallback** — silently substitutes `1` if
  `qty` were ever falsy at Stock-Entry-build time instead of throwing. Mostly moot now that fix #1
  above closes off how a bad `qty` could get that far, but still a silent-fallback pattern rather
  than a loud one if some future code path bypasses `validate()`.

Verified with `python3 -m py_compile` on `repair_list.py`. No automated Frappe test run, same
tradeoff as all prior rounds.

## Sixth round of fixes — focused re-read of `receive_return()`

Re-checked the return flow specifically, including how it interacts with the fifth round's new
"serialized row must be `qty == 1`" invariant. That invariant holds cleanly through
`receive_return()` (which still forces serialized rows to return in full, unchanged) and is
backward-compatible with any pre-existing submitted documents that have multi-serial rows from
before the rule existed — `receive_return()` never assumed the invariant itself, so nothing there
regressed.

One fresh issue found and fixed:

- **Missing float tolerance on the over-return check.** `remaining = total_qty - returned_qty` is
  a float subtraction with no epsilon guard, while the serialized-row "must return in full" check
  a few lines below it already uses `abs(row_qty - remaining) > 1e-6` for exactly this reason. For
  any item with a non-integer `qty` (the field is `Float`, not restricted to whole units), repeated
  partial returns accumulating in `returned_qty` could leave `remaining` off by a tiny float
  epsilon (e.g. `0.9999999997` instead of `1.0`), so a user requesting the exact legitimate
  remaining amount could get a spurious "exceeds remaining" error and be unable to complete the
  return through the UI. Fixed by applying the same tolerance pattern:
  `if row_qty > remaining + 1e-6: frappe.throw(...)`.

Verified with `python3 -m py_compile` on `repair_list.py`. No automated Frappe test run, same
tradeoff as all prior rounds.
