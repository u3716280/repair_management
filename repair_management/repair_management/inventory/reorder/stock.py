"""Current stock position, read straight from Bin -- ERPNext's own source of
truth for on-hand/reserved/on-order quantities. Read-only.

Bin is trusted directly here (Phase 0's acceptance criterion is exact
equality with Bin.actual_qty); an independent SLE-derived cross-check lives
in validation.py, not here.
"""

import frappe

_BIN_FIELDS = [
	"item_code",
	"warehouse",
	"actual_qty",
	"stock_uom",
	"reserved_qty",
	"reserved_qty_for_production",
	"reserved_qty_for_sub_contract",
	"reserved_stock",
	"ordered_qty",
	"projected_qty",
	"indented_qty",
]


def get_stock_snapshot(item_code: str | None = None, warehouse: str | None = None) -> list[dict]:
	"""One Bin row per (item_code, warehouse) matching the given filters."""
	filters = {}
	if item_code:
		filters["item_code"] = item_code
	if warehouse:
		filters["warehouse"] = warehouse

	return frappe.get_all("Bin", filters=filters, fields=_BIN_FIELDS, limit_page_length=0)


def get_stock_snapshot_bulk(item_codes: list, warehouses: list | None = None) -> list[dict]:
	"""Batched variant for many items/warehouses at once (avoids N+1 when
	scanning a whole test dataset)."""
	filters = {"item_code": ["in", item_codes]}
	if warehouses:
		filters["warehouse"] = ["in", warehouses]

	return frappe.get_all("Bin", filters=filters, fields=_BIN_FIELDS, limit_page_length=0)
