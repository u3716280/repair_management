"""Composition/reporting layer: cross-checks and manual-validation-sheet
building. This is the only module in the package allowed to import from the
others -- it composes their output, it does not extract new raw data itself.

Read-only, used interactively via `bench execute`/`bench console` (see
PHASE0_NOTES.md for the manual validation procedure).
"""

import frappe
from frappe.utils import flt

from . import demand as demand_mod
from . import incoming as incoming_mod
from . import reservation as reservation_mod


def compare_stock_with_bin(item_code: str, warehouse: str) -> dict:
	"""Re-derives 'actual qty as of today' from the latest non-cancelled SLE's
	qty_after_transaction and diffs it against Bin.actual_qty. A mismatch
	means Bin is out of sync with the ledger -- a real operational finding,
	even though Phase 0 always reports Bin.actual_qty as the trusted number."""
	bin_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	sle_qty = (
		frappe.db.get_value(
			"Stock Ledger Entry",
			{"item_code": item_code, "warehouse": warehouse, "is_cancelled": 0},
			"qty_after_transaction",
			order_by="posting_date desc, posting_time desc, creation desc",
		)
		or 0
	)
	bin_qty, sle_qty = flt(bin_qty), flt(sle_qty)
	return {
		"bin_qty": bin_qty,
		"sle_derived_qty": sle_qty,
		"matches": bin_qty == sle_qty,
		"diff": sle_qty - bin_qty,
	}


def explain_demand(item_code: str, warehouse: str, from_date: str, to_date: str) -> dict:
	"""Transaction-level audit: any aggregate figure must be explodable back
	to the contributing voucher rows (spec pt 27)."""
	result = demand_mod.get_demand_history(item_code=item_code, warehouse=warehouse, from_date=from_date, to_date=to_date)
	rows = result["rows"]

	by_class: dict[str, list] = {}
	for row in rows:
		by_class.setdefault(row["classification"], []).append(row)

	summary = {
		cls: {"count": len(class_rows), "total_demand_qty": sum(r["demand_qty"] for r in class_rows)}
		for cls, class_rows in by_class.items()
	}
	return {"summary": summary, "rows": rows, "exceptions": result["exceptions"]}


def build_manual_validation_row(item_code: str, warehouse: str, from_date: str, to_date: str) -> dict:
	"""One row of the manual validation sheet (spec pt 26): system-computed
	figures for a single (item, warehouse), ready to sit next to a manually
	computed column."""
	demand_result = explain_demand(item_code, warehouse, from_date, to_date)
	stock_check = compare_stock_with_bin(item_code, warehouse)
	reservation_rows = reservation_mod.get_reservation(item_code, warehouse)
	incoming_result = incoming_mod.get_incoming(item_code, warehouse)

	reliable = [r for r in incoming_result["rows"] if r["reliability"] == "RELIABLE"]
	late = [r for r in incoming_result["rows"] if r["reliability"] == "LATE"]

	transfer_out_qty = sum(
		r["demand_qty"]
		for r in demand_result["rows"]
		if r["classification"] == "TRANSFER" and r["source_warehouse"] == warehouse
	)
	transfer_in_qty = sum(
		r["demand_qty"]
		for r in demand_result["rows"]
		if r["classification"] == "TRANSFER" and r["target_warehouse"] == warehouse
	)

	return {
		"item_code": item_code,
		"warehouse": warehouse,
		"total_consumption": demand_result["summary"].get("CONSUMPTION", {}).get("total_demand_qty", 0),
		"transfer_out_qty": transfer_out_qty,
		"transfer_in_qty": transfer_in_qty,
		"return_qty": demand_result["summary"].get("RETURN", {}).get("total_demand_qty", 0),
		"actual_qty": stock_check["bin_qty"],
		"stock_check_matches": stock_check["matches"],
		"reserved_qty": reservation_rows[0]["reserved_qty"] if reservation_rows else 0,
		"reliable_incoming_qty": sum(r["remaining_qty"] for r in reliable),
		"late_incoming_qty": sum(r["remaining_qty"] for r in late),
		"exceptions": [e.as_dict() for e in demand_result["exceptions"] + incoming_result["exceptions"]],
	}


def build_manual_validation_sheet(items_and_warehouses: list, from_date: str, to_date: str) -> list:
	"""items_and_warehouses: [(item_code, warehouse), ...] -- the 5-10
	test-dataset pairs. Returns one build_manual_validation_row() dict per
	pair, for pasting into the manual validation spreadsheet (spec pt 26/31)."""
	return [
		build_manual_validation_row(item_code, warehouse, from_date, to_date)
		for item_code, warehouse in items_and_warehouses
	]
