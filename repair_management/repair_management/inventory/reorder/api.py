# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt
#
# Whitelisted, thin endpoints for the "Inventory Reorder Analysis" Desk page.
# Business logic lives in calculation.py/confidence.py/service.py -- this
# file only resolves parameters (date ranges, warehouse/item-group/supplier
# expansion), checks permissions, and calls into service.py.

import frappe
from frappe.utils import add_months, cint, date_diff, getdate, nowdate
from frappe.utils.nestedset import get_descendants_of

from . import incoming as incoming_mod
from . import service as service_mod
from .demand import get_demand_history as _get_demand_history

DEFAULT_ANALYSIS_PERIOD_MONTHS = 24


@frappe.whitelist()
def get_reorder_analysis(
	company,
	warehouse,
	item_group=None,
	item_code=None,
	supplier=None,
	demand_type=None,
	status=None,
	confidence=None,
	analysis_period=None,
	from_date=None,
	to_date=None,
	planning_lead_time=None,
	review_period=None,
	extra_coverage=None,
	service_level=None,
):
	frappe.has_permission("Item", "read", throw=True)

	from_date, to_date = _resolve_period(analysis_period, from_date, to_date)
	warehouses = _expand_warehouse(warehouse)
	item_codes = _resolve_item_codes(item_code, item_group, supplier)

	filters = {
		"company": company,
		"warehouses": warehouses,
		"item_codes": item_codes,
		"status": _split_csv(status),
		"demand_type": _split_csv(demand_type),
		"confidence": _split_csv(confidence),
	}
	options = _resolve_options(
		planning_lead_time, review_period, extra_coverage, service_level, from_date, to_date, company
	)
	return service_mod.analyze_items(filters, options)


@frappe.whitelist()
def get_reorder_analysis_detail(
	item_code,
	warehouse,
	company=None,
	analysis_period=None,
	from_date=None,
	to_date=None,
	planning_lead_time=None,
	review_period=None,
	extra_coverage=None,
	service_level=None,
):
	frappe.has_permission("Item", "read", throw=True)
	from_date, to_date = _resolve_period(analysis_period, from_date, to_date)
	options = _resolve_options(
		planning_lead_time, review_period, extra_coverage, service_level, from_date, to_date, company
	)
	return service_mod.analyze_item(item_code, warehouse, options)


@frappe.whitelist()
def get_demand_history(item_code, warehouse, analysis_period=None, from_date=None, to_date=None, company=None):
	frappe.has_permission("Item", "read", throw=True)
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	from_date, to_date = _resolve_period(analysis_period, from_date, to_date)
	result = _get_demand_history(item_code=item_code, warehouse=warehouse, from_date=from_date, to_date=to_date, company=company)
	return {
		"rows": [_format_demand_row(r) for r in result["rows"]],
		"exceptions": [e.as_dict() for e in result["exceptions"]],
	}


@frappe.whitelist()
def get_incoming_detail(item_code, warehouse):
	frappe.has_permission("Item", "read", throw=True)
	frappe.has_permission("Purchase Order", "read", throw=True)
	today = nowdate()
	result = incoming_mod.get_incoming(item_code=item_code, warehouse=warehouse, today=today)
	rows = []
	for r in result["rows"]:
		days_overdue = max(0, date_diff(today, r["schedule_date"])) if r["schedule_date"] else 0
		rows.append({**r, "days_overdue": days_overdue})
	return {"rows": rows, "exceptions": [e.as_dict() for e in result["exceptions"]]}


# ---- private helpers ---------------------------------------------------


def _resolve_period(analysis_period, from_date, to_date):
	"""Dual mode: explicit from_date/to_date wins (used by tests and power
	users); otherwise analysis_period (an integer count of MONTHS, matching
	the '24 months' UI default) is measured back from today."""
	if from_date and to_date:
		return getdate(from_date), getdate(to_date)
	months = cint(analysis_period) or DEFAULT_ANALYSIS_PERIOD_MONTHS
	to_date = getdate(nowdate())
	from_date = getdate(add_months(to_date, -months))
	return from_date, to_date


def _expand_warehouse(warehouse):
	if not warehouse:
		frappe.throw("Warehouse is required")
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw("Warehouse not found")
	return get_descendants_of("Warehouse", warehouse) + [warehouse]


def _resolve_item_codes(item_code, item_group, supplier):
	"""Intersects whichever of Item / Item Group / Supplier filters are
	given into a single concrete item_codes list. None (not an empty list)
	means "no narrowing filter given" -- analyze_items() falls back to
	whatever items actually have Bin activity in the resolved warehouses."""
	if item_code:
		return [item_code]

	item_codes = None
	if item_group:
		if not frappe.db.exists("Item Group", item_group):
			frappe.throw("Item Group not found")
		groups = get_descendants_of("Item Group", item_group) + [item_group]
		item_codes = set(
			frappe.get_all(
				"Item",
				filters={"item_group": ["in", groups], "disabled": 0, "is_stock_item": 1, "has_variants": 0},
				pluck="name",
			)
		)

	if supplier:
		supplier_item_codes = set(frappe.get_all("Item Supplier", filters={"supplier": supplier}, pluck="parent"))
		item_codes = supplier_item_codes if item_codes is None else (item_codes & supplier_item_codes)

	return list(item_codes) if item_codes is not None else None


def _resolve_options(planning_lead_time, review_period, extra_coverage, service_level, from_date, to_date, company):
	from .calculation import DEFAULT_OPTIONS

	options = dict(DEFAULT_OPTIONS)
	# A blank field can arrive here as "" rather than a true None (depending
	# on how the client serializes it), so check for "not provided" against
	# both -- "" must never be coerced by cint() into a real override of 0.
	if planning_lead_time not in (None, ""):
		options["planning_lead_time_days"] = cint(planning_lead_time)
	if review_period not in (None, ""):
		options["review_period_days"] = cint(review_period)
	if extra_coverage not in (None, ""):
		options["extra_coverage_days"] = cint(extra_coverage)
	if service_level:
		options["service_level"] = service_level
	options["from_date"], options["to_date"], options["company"] = from_date, to_date, company
	return options


def _split_csv(value):
	if not value:
		return None
	return [v for v in (value if isinstance(value, list) else value.split(",")) if v]


def _format_demand_row(row):
	return {
		"posting_date": row["posting_date"],
		"voucher_type": row["voucher_type"],
		"voucher_no": row["voucher_no"],
		"classification": row["classification"],
		"demand_qty": row["demand_qty"],
		"stock_uom": row["stock_uom"],
		"is_return": row["is_return"],
		"transfer_kind": row["transfer_kind"],
		"remarks": row["remarks"],
	}
