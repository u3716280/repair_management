"""Warehouse-group resolution and cross-warehouse aggregation for Phase 2's
Planning Warehouse concept (e.g. เอกไทย - ET grouping its two real children
บ้าน 88 - ET / บ้าน 147 - ET). The aggregation helpers below are pure (no
frappe.db calls) so they're unit-testable with plain dict/list fixtures;
resolve_planning_warehouse_group and get_group_incoming do the DB/Phase-0
calls each needs, reusing Phase 0's incoming.py unchanged.
"""

import frappe
from frappe.utils import date_diff, nowdate
from frappe.utils.nestedset import get_descendants_of

from . import incoming as incoming_mod


def resolve_planning_warehouse_group(planning_warehouse: str) -> dict:
	"""Returns {"leaf_warehouses": [...]}. A group warehouse's own name is
	never included in the result -- Bin has no rows for a group warehouse,
	only real leaves carry stock. A leaf warehouse resolves to itself."""
	is_group = frappe.db.get_value("Warehouse", planning_warehouse, "is_group")
	if not is_group:
		return {"leaf_warehouses": [planning_warehouse]}

	descendants = get_descendants_of("Warehouse", planning_warehouse)
	if not descendants:
		return {"leaf_warehouses": [planning_warehouse]}

	leaves = frappe.get_all("Warehouse", filters={"name": ["in", descendants], "is_group": 0}, pluck="name")
	return {"leaf_warehouses": leaves or [planning_warehouse]}


def aggregate_stock(stock_rows: list) -> dict:
	"""stock_rows: Bin rows (stock.get_stock_snapshot_bulk output) for ONE
	item across some set of leaf warehouses. Returns summed actual_qty/
	reserved_qty, plus stock_value (Bin.stock_value, confirmed present on
	this site) for a group inventory-value estimate."""
	actual_qty = sum(float(r.get("actual_qty") or 0) for r in stock_rows)
	reserved_qty = sum(float(r.get("reserved_qty") or 0) for r in stock_rows)
	stock_value = sum(float(r.get("stock_value") or 0) for r in stock_rows)
	return {"actual_qty": actual_qty, "reserved_qty": reserved_qty, "stock_value": stock_value}


def aggregate_incoming(incoming_rows: list) -> dict:
	"""incoming_rows: incoming.get_incoming() rows across some set of leaf
	warehouses, both reliabilities mixed together. Returns
	{"total_outstanding_qty": sum of ALL rows regardless of reliability,
	"reliable_qty": ..., "late_qty": ...} -- reliability is preserved for
	Purchase Follow-up display, but total_outstanding_qty (which sums both)
	is what Phase 2's Planning Position formula actually uses -- late/overdue
	POs are treated as good as arrived, per the confirmed model change."""
	reliable_qty = sum(r["remaining_qty_stock_uom"] for r in incoming_rows if r["reliability"] == "RELIABLE")
	late_qty = sum(r["remaining_qty_stock_uom"] for r in incoming_rows if r["reliability"] == "LATE")
	return {
		"total_outstanding_qty": reliable_qty + late_qty,
		"reliable_qty": reliable_qty,
		"late_qty": late_qty,
	}


def aggregate_daily_demand_series(per_leaf_series: list) -> list:
	"""Element-wise sum of N equal-length daily series, one per leaf
	warehouse (each already built via calculation.build_daily_demand_series
	for that single leaf). TRANSFER rows always contribute 0 to whichever
	leaf's series they're queried against (NET_SIGN[TRANSFER] == 0, per
	classification.py), so summing per-leaf series that already exclude
	TRANSFER is mathematically identical to building one series from every
	row across all leaves combined -- no special suppression is needed for
	internal transfers between the group's own children."""
	if not per_leaf_series:
		return []
	length = len(per_leaf_series[0])
	merged = [0.0] * length
	for series in per_leaf_series:
		for i, value in enumerate(series):
			merged[i] += value
	return merged


def get_group_incoming(item_code: str, leaf_warehouses: list, today: str | None = None) -> dict:
	"""Calls incoming.get_incoming() once per leaf warehouse (Phase 0's
	function reused unchanged), concatenates rows/exceptions, and separates
	out a Purchase-Follow-up view of the LATE rows only (for display -- this
	is a distinct dict key, never fed back into aggregate_incoming's
	total_outstanding_qty, which always counts every row regardless of
	reliability)."""
	today = today or nowdate()
	all_rows, all_exceptions = [], []
	for warehouse in leaf_warehouses:
		result = incoming_mod.get_incoming(item_code=item_code, warehouse=warehouse, today=today)
		all_rows.extend(result["rows"])
		all_exceptions.extend(result["exceptions"])

	follow_up = sorted(
		(
			{
				**row,
				"days_overdue": max(0, date_diff(today, row["schedule_date"])) if row["schedule_date"] else 0,
			}
			for row in all_rows
			if row["reliability"] == "LATE"
		),
		key=lambda r: r["days_overdue"],
		reverse=True,
	)

	return {"rows": all_rows, "exceptions": all_exceptions, "follow_up": follow_up}
