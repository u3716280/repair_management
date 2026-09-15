"""Composition layer: the public interface other layers (api.py, backtest.py,
tests, any future caller) should call. Combines Phase 0's data layer with
group.py/calculation.py/policy.py/confidence.py. No frappe.whitelist() here
-- permission checks live in api.py, not in this pure-composition/
business-logic layer, so this stays usable from a scheduled job, a backtest
run, or the console as well as the Desk page.

Phase 2: analyze_item/analyze_items now operate at the PLANNING WAREHOUSE
level -- a single warehouse that may be a real group (aggregating every leaf
warehouse under it into one row per item) or a plain leaf (in which case it
behaves exactly as a "group of one", identical to Phase 1's behavior). There
is deliberately only one code path for both cases, via
group.resolve_planning_warehouse_group -- not two parallel implementations.
"""

import frappe

from . import demand as demand_mod
from . import group as group_mod
from . import incoming as incoming_mod
from . import lead_time as lead_time_mod
from . import policy as policy_mod
from . import stock as stock_mod
from .calculation import CONTRACT_FIELDS, DEFAULT_OPTIONS, STATUS_SORT_ORDER, calculate_item_reorder


def _resolve_options(options: dict | None) -> dict:
	resolved = dict(DEFAULT_OPTIONS)
	resolved.update(options or {})
	if not resolved.get("from_date") or not resolved.get("to_date"):
		frappe.throw("from_date and to_date are required (via options)")
	return resolved


def analyze_item(item_code: str, planning_warehouse: str, options: dict | None = None) -> dict:
	"""Single Item + Planning Warehouse (group or leaf) full analysis (used
	by the detail/drill-down endpoint and by backtest.py's checkpoint
	recompute). Returns the FULL superset dict from calculate_item_reorder
	(contract fields + detail-only extras), plus `leaf_warehouses` and
	`follow_up` (late/overdue POs, for Purchase Follow-up display -- never
	fed back into the planning-position math, see group.py)."""
	options = _resolve_options(options)
	from_date, to_date = options["from_date"], options["to_date"]

	item_rows = frappe.get_all(
		"Item",
		filters={"name": item_code},
		fields=["name", "item_name", "stock_uom", "lead_time_days"],
		limit_page_length=1,
	)
	if not item_rows:
		frappe.throw(f"Item {item_code} not found")
	item_row = item_rows[0]

	leaf_warehouses = group_mod.resolve_planning_warehouse_group(planning_warehouse)["leaf_warehouses"]

	demand_rows, demand_exceptions = [], []
	for warehouse in leaf_warehouses:
		result = demand_mod.get_demand_history(
			item_code=item_code, warehouse=warehouse, from_date=from_date, to_date=to_date,
			company=options.get("company"),
		)
		demand_rows.extend(result["rows"])
		demand_exceptions.extend(result["exceptions"])

	stock_rows = stock_mod.get_stock_snapshot_bulk([item_code], leaf_warehouses)
	aggregated_stock = group_mod.aggregate_stock(stock_rows)

	incoming_result = group_mod.get_group_incoming(item_code, leaf_warehouses)

	lead_time_result = lead_time_mod.get_lead_time_history(item_code=item_code, from_date=from_date, to_date=to_date)
	lead_time_rows = [r for r in lead_time_result["rows"] if r["warehouse"] in leaf_warehouses]

	full = calculate_item_reorder(
		item_code=item_code,
		warehouse=planning_warehouse,
		item_name=item_row["item_name"] or item_code,
		stock_uom=item_row["stock_uom"],
		configured_lead_time_days=item_row["lead_time_days"] or 0,
		demand_rows=demand_rows,
		demand_exceptions=demand_exceptions,
		stock_row=aggregated_stock,
		incoming_rows=incoming_result["rows"],
		incoming_exceptions=incoming_result["exceptions"],
		lead_time_rows=lead_time_rows,
		from_date=from_date,
		to_date=to_date,
		options=options,
	)
	full["leaf_warehouses"] = leaf_warehouses
	full["follow_up"] = incoming_result["follow_up"]
	return full


def _bin_anchored_item_codes(warehouses: list) -> list:
	"""When no Item/Item Group filter narrows the candidate set, anchor on
	whatever Bin rows already exist for the resolved leaf warehouses --
	avoids analyzing the entire Item master when only a handful of items
	ever touched these warehouses."""
	return frappe.get_all(
		"Bin", filters={"warehouse": ["in", warehouses]}, pluck="item_code", distinct=True
	)


def _apply_display_filters(rows: list, filters: dict) -> list:
	"""Supplier filtering happens earlier, in api.py's item_codes resolution
	(a supplier is a property of which items are sourced from them, not of an
	already-computed analysis row) -- only row-level fields are filtered here.

	Default batch scope: unless the caller narrowed to exactly one concrete
	Item (the "Manual Analysis" path, where any policy is fair to inspect),
	rows are restricted to policy.ELIGIBLE_FOR_BATCH (STOCKED/INTERMITTENT/
	SLOW_CRITICAL) -- an explicit `policy` filter overrides this default
	instead of being combined with it, so a user can deliberately browse e.g.
	BUY_TO_ORDER/EXCLUDE items in bulk if they choose to filter for them."""
	status = filters.get("status")
	demand_type = filters.get("demand_type")
	confidence = filters.get("confidence")
	policy = filters.get("policy")
	single_item_selected = len(filters.get("item_codes") or []) == 1

	if status:
		rows = [r for r in rows if r["status"] in status]
	if demand_type:
		rows = [r for r in rows if r["demand_type"] in demand_type]
	if confidence:
		rows = [r for r in rows if r["confidence"] in confidence]
	if policy:
		rows = [r for r in rows if r["policy"] in policy]
	elif not single_item_selected:
		rows = [r for r in rows if r["policy"] in policy_mod.ELIGIBLE_FOR_BATCH]
	return rows


def _project_to_contract(row: dict) -> dict:
	return {field: row[field] for field in CONTRACT_FIELDS}


def analyze_items(filters: dict, options: dict | None = None) -> list:
	"""Batched multi-item analysis for the main list -- ONE row per (item,
	planning_warehouse), aggregating across every leaf warehouse in the
	group (or just the one leaf, if planning_warehouse is itself a leaf).

	filters (already resolved to concrete values by api.py):
	  company, planning_warehouse: str, item_codes: list[str] | None (already
	  expanded via get_descendants_of("Item Group", ...) if item_group was
	  given), status/demand_type/policy/confidence: list[str] | None.

	No N+1: one demand/incoming/lead-time query per LEAF WAREHOUSE in the
	group (not per item), exactly mirroring Phase 1's own no-N+1 guarantee.
	"""
	options = _resolve_options(options)
	planning_warehouse = filters["planning_warehouse"]
	from_date, to_date = options["from_date"], options["to_date"]

	leaf_warehouses = group_mod.resolve_planning_warehouse_group(planning_warehouse)["leaf_warehouses"]

	item_codes = filters.get("item_codes") or _bin_anchored_item_codes(leaf_warehouses)
	items_by_code = {
		r["name"]: r
		for r in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "item_name", "stock_uom", "lead_time_days"],
			limit_page_length=0,
		)
	}

	stock_rows = stock_mod.get_stock_snapshot_bulk(item_codes, leaf_warehouses) if item_codes else []
	stock_by_item: dict = {}
	for row in stock_rows:
		stock_by_item.setdefault(row["item_code"], []).append(row)

	demand_by_item: dict = {}
	demand_exceptions_by_item: dict = {}
	for warehouse in leaf_warehouses:
		result = demand_mod.get_demand_history(
			warehouse=warehouse, from_date=from_date, to_date=to_date, company=filters.get("company")
		)
		for row in result["rows"]:
			demand_by_item.setdefault(row["item_code"], []).append(row)
		for exc in result["exceptions"]:
			demand_exceptions_by_item.setdefault(exc.item_code, []).append(exc)

	incoming_result = incoming_mod.get_incoming()
	incoming_by_item: dict = {}
	incoming_exceptions_by_item: dict = {}
	for row in incoming_result["rows"]:
		if row["warehouse"] not in leaf_warehouses:
			continue
		incoming_by_item.setdefault(row["item_code"], []).append(row)
	for exc in incoming_result["exceptions"]:
		if exc.warehouse not in leaf_warehouses:
			continue
		incoming_exceptions_by_item.setdefault(exc.item_code, []).append(exc)

	lead_time_result = lead_time_mod.get_lead_time_history(from_date=from_date, to_date=to_date)
	lead_time_by_item: dict = {}
	for row in lead_time_result["rows"]:
		if row["warehouse"] not in leaf_warehouses:
			continue
		lead_time_by_item.setdefault(row["item_code"], []).append(row)

	rows = []
	for item_code in item_codes:
		item = items_by_code.get(item_code)
		if not item:
			continue
		if (
			item_code not in stock_by_item
			and item_code not in demand_by_item
			and item_code not in incoming_by_item
		):
			continue  # never touched anywhere in this group -- nothing to analyze
		aggregated_stock = group_mod.aggregate_stock(stock_by_item.get(item_code, []))
		full = calculate_item_reorder(
			item_code=item_code,
			warehouse=planning_warehouse,
			item_name=item["item_name"] or item_code,
			stock_uom=item["stock_uom"],
			configured_lead_time_days=item["lead_time_days"] or 0,
			demand_rows=demand_by_item.get(item_code, []),
			demand_exceptions=demand_exceptions_by_item.get(item_code, []),
			stock_row=aggregated_stock,
			incoming_rows=incoming_by_item.get(item_code, []),
			incoming_exceptions=incoming_exceptions_by_item.get(item_code, []),
			lead_time_rows=lead_time_by_item.get(item_code, []),
			from_date=from_date,
			to_date=to_date,
			options=options,
		)
		rows.append(full)

	rows = _apply_display_filters(rows, filters)
	rows.sort(key=lambda r: (STATUS_SORT_ORDER.get(r["status"], 9), -r["recommended_qty"]))
	return [_project_to_contract(r) for r in rows]
