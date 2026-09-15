# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt
#
# Whitelisted, thin endpoints for the "Inventory Reorder Analysis" Desk page.
# Business logic lives in calculation.py/confidence.py/policy.py/group.py/
# service.py/backtest.py -- this file only resolves parameters (date ranges,
# warehouse/item-group/supplier expansion), checks permissions, and calls
# into those layers.

import frappe
from frappe.utils import add_months, cint, date_diff, getdate, nowdate
from frappe.utils.nestedset import get_descendants_of

from . import backtest as backtest_mod
from . import group as group_mod
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
	policy=None,
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
	"""`warehouse` is the Planning Warehouse -- a group warehouse (aggregated
	across all its leaf children into one row per item) or a plain leaf
	(behaves exactly as a group of one)."""
	frappe.has_permission("Item", "read", throw=True)

	from_date, to_date = _resolve_period(analysis_period, from_date, to_date)
	planning_warehouse = _validate_warehouse(warehouse)
	item_codes = _resolve_item_codes(item_code, item_group, supplier)

	filters = {
		"company": company,
		"planning_warehouse": planning_warehouse,
		"item_codes": item_codes,
		"status": _split_csv(status),
		"demand_type": _split_csv(demand_type),
		"policy": _split_csv(policy),
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
	manual_policy_override=None,
):
	"""manual_policy_override is only ever meaningful here (the single-item
	Manual Analysis path) -- get_reorder_analysis (the bulk list) never
	accepts it, per the confirmed design (no persisted override, never
	applied to a batch run)."""
	frappe.has_permission("Item", "read", throw=True)
	from_date, to_date = _resolve_period(analysis_period, from_date, to_date)
	options = _resolve_options(
		planning_lead_time, review_period, extra_coverage, service_level, from_date, to_date, company
	)
	if manual_policy_override:
		options["manual_policy_override"] = manual_policy_override
	return service_mod.analyze_item(item_code, warehouse, options)


@frappe.whitelist()
def get_demand_history(item_code, warehouse, analysis_period=None, from_date=None, to_date=None, company=None):
	"""`warehouse` is the Planning Warehouse -- expanded to its leaf
	warehouses so the drill-down's Demand Transactions table shows every
	leaf's activity, not just one."""
	frappe.has_permission("Item", "read", throw=True)
	frappe.has_permission("Stock Ledger Entry", "read", throw=True)
	from_date, to_date = _resolve_period(analysis_period, from_date, to_date)
	leaf_warehouses = group_mod.resolve_planning_warehouse_group(warehouse)["leaf_warehouses"]

	rows, exceptions = [], []
	for leaf in leaf_warehouses:
		result = _get_demand_history(
			item_code=item_code, warehouse=leaf, from_date=from_date, to_date=to_date, company=company
		)
		rows.extend(result["rows"])
		exceptions.extend(result["exceptions"])

	return {
		"rows": [_format_demand_row(r) for r in rows],
		"exceptions": [e.as_dict() for e in exceptions],
	}


@frappe.whitelist()
def get_incoming_detail(item_code, warehouse):
	"""`warehouse` is the Planning Warehouse. Returns both the combined
	Incoming PO table (all reliability, the number that feeds Planning
	Position) and a `follow_up` list (LATE rows only, with days_overdue,
	worst-first) for the Purchase Follow-up section -- informational only,
	never fed back into the planning math."""
	frappe.has_permission("Item", "read", throw=True)
	frappe.has_permission("Purchase Order", "read", throw=True)
	today = nowdate()
	leaf_warehouses = group_mod.resolve_planning_warehouse_group(warehouse)["leaf_warehouses"]
	result = group_mod.get_group_incoming(item_code, leaf_warehouses, today=today)

	rows = []
	for r in result["rows"]:
		days_overdue = max(0, date_diff(today, r["schedule_date"])) if r["schedule_date"] else 0
		rows.append({**r, "days_overdue": days_overdue})

	return {
		"rows": rows,
		"exceptions": [e.as_dict() for e in result["exceptions"]],
		"follow_up": result["follow_up"],
	}


@frappe.whitelist()
def run_backtest(
	item_code,
	warehouse,
	company=None,
	training_window_days=180,
	validation_window_days=90,
	step_days=7,
	backtest_end_date=None,
	planning_lead_time=None,
	review_period=None,
	extra_coverage=None,
	service_level=None,
):
	"""Single-item walk-forward backtest. Read-only -- backtest_mod.run_backtest
	only ever simulates orders in memory, never creates real documents."""
	frappe.has_permission("Item", "read", throw=True)
	options = _resolve_options(planning_lead_time, review_period, extra_coverage, service_level, None, None, company)
	return backtest_mod.run_backtest(
		item_code=item_code,
		planning_warehouse=warehouse,
		company=company,
		training_window_days=cint(training_window_days),
		validation_window_days=cint(validation_window_days),
		step_days=cint(step_days),
		backtest_end_date=getdate(backtest_end_date) if backtest_end_date else getdate(nowdate()),
		options=options,
	)


@frappe.whitelist()
def run_policy_matrix(
	item_code,
	warehouse,
	company=None,
	training_window_days=180,
	validation_window_days=90,
	step_days=7,
	backtest_end_date=None,
	planning_lead_time=None,
	review_period=None,
):
	"""Runs the 8-combination P85/P95 x 30/45/60/90-day-Extra-Coverage policy
	matrix for one item, server-side (one round trip instead of 8), reusing
	run_backtest per combination."""
	frappe.has_permission("Item", "read", throw=True)
	results = []
	for service_level in ("P85", "P95"):
		for extra_coverage in (30, 45, 60, 90):
			result = run_backtest(
				item_code=item_code,
				warehouse=warehouse,
				company=company,
				training_window_days=training_window_days,
				validation_window_days=validation_window_days,
				step_days=step_days,
				backtest_end_date=backtest_end_date,
				planning_lead_time=planning_lead_time,
				review_period=review_period,
				extra_coverage=extra_coverage,
				service_level=service_level,
			)
			results.append(
				{
					"service_level": service_level,
					"extra_coverage": extra_coverage,
					"metrics": result["metrics"],
				}
			)
	return results


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


def _validate_warehouse(warehouse):
	if not warehouse:
		frappe.throw("Warehouse is required")
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw("Warehouse not found")
	return warehouse


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
