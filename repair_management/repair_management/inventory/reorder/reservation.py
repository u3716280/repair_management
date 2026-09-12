"""Reserved-qty extraction and a basic source drill-down. Read-only.

Phase 0 deliberately does NOT build a full demand-commitment engine: it uses
ERPNext's own Bin reservation fields as the source of truth, kept as separate
named buckets (never pre-summed here) so a later phase can decide how to
avoid double-counting Reserved Qty against Future Demand (spec pt 8/11).
"""

import frappe

_RESERVATION_FIELDS = [
	"item_code",
	"warehouse",
	"reserved_qty",
	"reserved_qty_for_production",
	"reserved_qty_for_sub_contract",
	"reserved_qty_for_production_plan",
	"reserved_stock",
]


def get_reservation(item_code: str | None = None, warehouse: str | None = None) -> list[dict]:
	filters = {}
	if item_code:
		filters["item_code"] = item_code
	if warehouse:
		filters["warehouse"] = warehouse

	return frappe.get_all("Bin", filters=filters, fields=_RESERVATION_FIELDS, limit_page_length=0)


def get_reservation_sources(item_code: str, warehouse: str, limit: int = 50) -> dict:
	"""Best-effort traceability for Bin's reserved-qty figures: which Sales
	Orders/Pick Lists reference this item+warehouse with stock reserved.
	Not a commitment engine -- just enough to answer "where did this
	reservation come from" per spec pt 8/27."""
	sales_orders = frappe.get_all(
		"Sales Order Item",
		filters={
			"item_code": item_code,
			"warehouse": warehouse,
			"docstatus": 1,
			"stock_reserved_qty": [">", 0],
		},
		fields=["parent as sales_order", "stock_reserved_qty", "qty", "delivered_qty"],
		limit_page_length=limit,
	)
	pick_lists = frappe.get_all(
		"Pick List Item",
		filters={"item_code": item_code, "warehouse": warehouse, "docstatus": 1},
		fields=["parent as pick_list", "sales_order", "material_request", "stock_reserved_qty", "picked_qty"],
		limit_page_length=limit,
	)
	return {"sales_orders": sales_orders, "pick_lists": pick_lists}
