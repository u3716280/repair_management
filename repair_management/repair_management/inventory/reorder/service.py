"""Composition layer: the public interface other layers (api.py, tests, any
future caller) should call. Combines Phase 0's data layer with
calculation.py/confidence.py. No frappe.whitelist() here -- permission
checks live in api.py, not in this pure-composition/business-logic layer, so
this stays usable from a scheduled job or the console as well as the Desk page.
"""

import frappe

from . import demand as demand_mod
from . import incoming as incoming_mod
from . import lead_time as lead_time_mod
from . import stock as stock_mod
from .calculation import CONTRACT_FIELDS, DEFAULT_OPTIONS, STATUS_SORT_ORDER, calculate_item_reorder


def _resolve_options(options: dict | None) -> dict:
	resolved = dict(DEFAULT_OPTIONS)
	resolved.update(options or {})
	if not resolved.get("from_date") or not resolved.get("to_date"):
		frappe.throw("from_date and to_date are required (via options)")
	return resolved


def analyze_item(item_code: str, warehouse: str, options: dict | None = None) -> dict:
	"""Single Item+Warehouse full analysis (used for the detail/drill-down
	endpoint). Returns the FULL superset dict from calculate_item_reorder
	(contract fields + detail-only extras)."""
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

	demand_result = demand_mod.get_demand_history(
		item_code=item_code, warehouse=warehouse, from_date=from_date, to_date=to_date,
		company=options.get("company"),
	)
	stock_rows = stock_mod.get_stock_snapshot(item_code=item_code, warehouse=warehouse)
	incoming_result = incoming_mod.get_incoming(item_code=item_code, warehouse=warehouse)
	lead_time_result = lead_time_mod.get_lead_time_history(
		item_code=item_code, from_date=from_date, to_date=to_date
	)

	return calculate_item_reorder(
		item_code=item_code,
		warehouse=warehouse,
		item_name=item_row["item_name"] or item_code,
		stock_uom=item_row["stock_uom"],
		configured_lead_time_days=item_row["lead_time_days"] or 0,
		demand_rows=demand_result["rows"],
		demand_exceptions=demand_result["exceptions"],
		stock_row=stock_rows[0] if stock_rows else None,
		incoming_rows=incoming_result["rows"],
		incoming_exceptions=incoming_result["exceptions"],
		lead_time_rows=[r for r in lead_time_result["rows"] if r["warehouse"] == warehouse],
		from_date=from_date,
		to_date=to_date,
		options=options,
	)


def _bin_anchored_item_codes(warehouses: list) -> list:
	"""When no Item/Item Group filter narrows the candidate set, anchor on
	whatever Bin rows already exist for the resolved warehouses -- avoids
	analyzing the entire Item master when only a handful of items ever
	touched these warehouses."""
	return frappe.get_all(
		"Bin", filters={"warehouse": ["in", warehouses]}, pluck="item_code", distinct=True
	)


def _apply_display_filters(rows: list, filters: dict) -> list:
	"""Supplier filtering happens earlier, in api.py's item_codes resolution
	(a supplier is a property of which items are sourced from them, not of an
	already-computed analysis row) -- only the row-level fields are filtered here."""
	status = filters.get("status")
	demand_type = filters.get("demand_type")
	confidence = filters.get("confidence")

	if status:
		rows = [r for r in rows if r["status"] in status]
	if demand_type:
		rows = [r for r in rows if r["demand_type"] in demand_type]
	if confidence:
		rows = [r for r in rows if r["confidence"] in confidence]
	return rows


def _project_to_contract(row: dict) -> dict:
	return {field: row[field] for field in CONTRACT_FIELDS}


def analyze_items(filters: dict, options: dict | None = None) -> list:
	"""Batched multi-item/warehouse analysis for the main list.

	filters (already resolved to concrete values by api.py):
	  company, warehouses: list[str] (already expanded via get_descendants_of
	  if a Warehouse Group), item_codes: list[str] | None (already expanded
	  via get_descendants_of("Item Group", ...) if item_group was given),
	  status/demand_type/confidence: list[str] | None, supplier: str | None.
	"""
	options = _resolve_options(options)
	warehouses = filters["warehouses"]
	from_date, to_date = options["from_date"], options["to_date"]

	item_codes = filters.get("item_codes") or _bin_anchored_item_codes(warehouses)
	items_by_code = {
		r["name"]: r
		for r in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes]},
			fields=["name", "item_name", "stock_uom", "lead_time_days"],
			limit_page_length=0,
		)
	}

	stock_rows = stock_mod.get_stock_snapshot_bulk(item_codes, warehouses) if item_codes else []
	stock_by_pair = {(r["item_code"], r["warehouse"]): r for r in stock_rows}

	demand_by_pair: dict = {}
	demand_exceptions_by_pair: dict = {}
	for wh in warehouses:
		result = demand_mod.get_demand_history(
			warehouse=wh, from_date=from_date, to_date=to_date, company=filters.get("company")
		)
		for row in result["rows"]:
			demand_by_pair.setdefault((row["item_code"], row["warehouse"]), []).append(row)
		for exc in result["exceptions"]:
			demand_exceptions_by_pair.setdefault((exc.item_code, exc.warehouse), []).append(exc)

	incoming_result = incoming_mod.get_incoming()
	incoming_by_pair: dict = {}
	incoming_exceptions_by_pair: dict = {}
	for row in incoming_result["rows"]:
		incoming_by_pair.setdefault((row["item_code"], row["warehouse"]), []).append(row)
	for exc in incoming_result["exceptions"]:
		incoming_exceptions_by_pair.setdefault((exc.item_code, exc.warehouse), []).append(exc)

	lead_time_result = lead_time_mod.get_lead_time_history(from_date=from_date, to_date=to_date)
	lead_time_by_pair: dict = {}
	for row in lead_time_result["rows"]:
		lead_time_by_pair.setdefault((row["item_code"], row["warehouse"]), []).append(row)

	rows = []
	for item_code in item_codes:
		item = items_by_code.get(item_code)
		if not item:
			continue
		for wh in warehouses:
			pair = (item_code, wh)
			if pair not in stock_by_pair and pair not in demand_by_pair and pair not in incoming_by_pair:
				continue  # never touched at this warehouse -- nothing to analyze
			full = calculate_item_reorder(
				item_code=item_code,
				warehouse=wh,
				item_name=item["item_name"] or item_code,
				stock_uom=item["stock_uom"],
				configured_lead_time_days=item["lead_time_days"] or 0,
				demand_rows=demand_by_pair.get(pair, []),
				demand_exceptions=demand_exceptions_by_pair.get(pair, []),
				stock_row=stock_by_pair.get(pair),
				incoming_rows=incoming_by_pair.get(pair, []),
				incoming_exceptions=incoming_exceptions_by_pair.get(pair, []),
				lead_time_rows=lead_time_by_pair.get(pair, []),
				from_date=from_date,
				to_date=to_date,
				options=options,
			)
			rows.append(full)

	rows = _apply_display_filters(rows, filters)
	rows.sort(key=lambda r: (STATUS_SORT_ORDER.get(r["status"], 9), -r["recommended_qty"]))
	return [_project_to_contract(r) for r in rows]
