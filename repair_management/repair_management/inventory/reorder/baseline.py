"""Baseline comparators for Phase 2's backtest. Four candidates were
assessed: avg-demand x lead-time and simple Min/Max are always computable
(pure functions, no DB); the native ERPNext reorder-level baseline is real
and active on this site (Item Reorder / Stock Settings.auto_indent); manual
Material Request history is too sparse (30 docs / 70 items site-wide) for an
automated comparison metric and is exposed as reference context only, never
fed into a computed baseline.
"""

import frappe

from . import metrics as metrics_mod


def compute_avg_demand_lead_time_baseline(avg_daily_demand: float, lead_time_days: float) -> float:
	"""Naive ROP = average daily demand x lead time -- no percentile, no
	protection-period distinction."""
	return float(avg_daily_demand) * float(lead_time_days)


def compute_min_max_baseline(avg_daily_demand: float, lead_time_days: float) -> dict:
	"""A classic simplistic Min/Max policy: Min = the same naive
	avg-demand x lead-time ROP; Max = Min plus one more lead-time's worth of
	average demand -- deliberately simplistic, distinct from the model's
	percentile-based ROP/Target."""
	naive_rop = compute_avg_demand_lead_time_baseline(avg_daily_demand, lead_time_days)
	return {"min": naive_rop, "max": naive_rop + float(avg_daily_demand) * float(lead_time_days)}


def get_native_erpnext_reorder_config(item_code: str, leaf_warehouses: list) -> dict | None:
	"""Reads real `Item Reorder` child rows (Item.reorder_levels) for this
	item where warehouse is one of leaf_warehouses. Returns None when no row
	exists for ANY leaf in the group -- never fabricates a level, never
	sums rows across warehouses the business configured independently
	(confirmed design choice)."""
	rows = frappe.get_all(
		"Item Reorder",
		filters={"parent": item_code, "warehouse": ["in", leaf_warehouses]},
		fields=["warehouse", "warehouse_reorder_level", "warehouse_reorder_qty", "material_request_type"],
	)
	if not rows:
		return None
	if len(rows) > 1:
		# This site's real data (as of Phase 2 design time) only ever had one
		# configured row (บ้าน 147 - ET). If more than one leaf warehouse has
		# its own row, report the first and flag the ambiguity rather than
		# silently summing levels the business configured independently.
		return {**rows[0], "multiple_rows_found": True, "all_rows": rows}
	return {**rows[0], "multiple_rows_found": False}


def simulate_native_erpnext_baseline(
	*,
	actual_daily_series: list,
	start_on_hand: float,
	reserved_qty: float,
	reorder_level: float,
	reorder_qty: float,
	lead_time_days: int,
	review_period_days: int,
) -> dict:
	"""Same day-by-day mechanics as backtest.py's loop, but the trigger rule
	is ERPNext's own `projected_qty <= reorder_level -> order
	max(reorder_qty, reorder_level - projected_qty)`, with reorder_level/
	reorder_qty held FIXED for the whole run (real, already-configured
	master data -- not recomputed on a schedule the way the new model's
	ROP/Target are). `projected_qty` is approximated as
	on_hand + outstanding - reserved (the same shape as Planning Position --
	a full ERPNext `projected_qty` also folds in indented_qty/planned_qty,
	which this backtest doesn't track; documented simplification)."""
	state = {"on_hand": start_on_hand, "open_orders": []}
	trace: list = []
	orders: list = []

	for day_offset, demand_qty in enumerate(actual_daily_series):
		arriving = [o for o in state["open_orders"] if o["arrival_offset"] == day_offset]
		for order in arriving:
			state["on_hand"] += order["qty"]
		if arriving:
			state["open_orders"] = [o for o in state["open_orders"] if o["arrival_offset"] != day_offset]

		stockout_qty = 0.0
		if demand_qty > state["on_hand"]:
			stockout_qty = demand_qty - state["on_hand"]
			state["on_hand"] = 0.0
		else:
			state["on_hand"] -= demand_qty

		outstanding_qty = sum(o["qty"] for o in state["open_orders"])
		projected_qty = state["on_hand"] + outstanding_qty - reserved_qty

		orders_placed_today = 0
		if projected_qty <= reorder_level:
			qty_to_order = max(reorder_qty, reorder_level - projected_qty)
			if qty_to_order > 0:
				order = {"arrival_offset": day_offset + lead_time_days + review_period_days, "qty": qty_to_order}
				state["open_orders"].append(order)
				orders.append(order)
				orders_placed_today = 1

		trace.append(
			{
				"date": str(day_offset),
				"on_hand": state["on_hand"],
				"outstanding_qty": outstanding_qty,
				"reserved": reserved_qty,
				"planning_position": projected_qty,
				"rop": reorder_level,
				"target": reorder_level + reorder_qty,
				"demand_qty": demand_qty,
				"stockout_qty": stockout_qty,
				"orders_placed_today": orders_placed_today,
				"open_order_count": len(state["open_orders"]),
			}
		)

	computed_metrics = metrics_mod.compute_all_metrics(
		trace=trace,
		orders=orders,
		rop_history=[reorder_level],
		target_history=[reorder_level + reorder_qty],
		valuation_rate=0.0,
	)
	return {"trace": trace, "orders": orders, "metrics": computed_metrics}


def get_manual_request_history(item_code: str, leaf_warehouses: list, from_date, to_date) -> list:
	"""Reference-only Material Request Item history -- NOT fed into any
	metric (only 30 Material Request docs / 70 items exist site-wide, too
	sparse for an automated comparison). Exposed in the drill-down as
	context: when did a human actually order this, how much."""
	rows = frappe.get_all(
		"Material Request Item",
		filters={"item_code": item_code, "warehouse": ["in", leaf_warehouses]},
		fields=["parent as material_request", "warehouse", "qty", "schedule_date"],
	)
	if not rows:
		return []
	parents = list({r["material_request"] for r in rows})
	headers = {
		h["name"]: h
		for h in frappe.get_all(
			"Material Request",
			filters={"name": ["in", parents], "docstatus": 1, "transaction_date": ["between", [from_date, to_date]]},
			fields=["name", "transaction_date", "material_request_type"],
		)
	}
	return [
		{
			**row,
			"transaction_date": headers[row["material_request"]]["transaction_date"],
			"material_request_type": headers[row["material_request"]]["material_request_type"],
		}
		for row in rows
		if row["material_request"] in headers
	]
