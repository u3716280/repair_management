"""Walk-forward backtest engine (Phase 2). Read-only -- every "order" placed
during a backtest is a plain in-memory dict, never a real Purchase Order or
Material Request. Reuses the exact same group-aware calculation pipeline
(service.analyze_item) for each checkpoint's ROP/Target -- no parallel
formula implementation, so a backtest's "as of day d" numbers are guaranteed
to match what the live page would have shown on that day.

No-look-ahead is structural, not just a convention: the checkpoint recompute
(service.analyze_item with to_date pinned to day-1) and the actual-demand
fetch (the whole validation window, used only to advance simulated stock)
are two entirely separate calls with two separate date ranges -- only the
first ever reaches the ROP/Target calculation.
"""

from frappe.utils import add_days, date_diff, getdate

from . import baseline as baseline_mod
from . import demand as demand_mod
from . import group as group_mod
from . import metrics as metrics_mod
from . import service as service_mod
from . import stock as stock_mod
from .calculation import build_daily_demand_series, compute_planning_position, compute_recommended_qty


def run_backtest(
	*,
	item_code: str,
	planning_warehouse: str,
	company: str | None,
	training_window_days: int,
	validation_window_days: int,
	step_days: int,
	backtest_end_date,
	options: dict,
) -> dict:
	"""Returns {"trace": [...one dict per simulated day...], "orders": [...],
	"metrics": {...}, "config": {...echoed inputs...}}."""
	backtest_end_date = getdate(backtest_end_date)
	backtest_start_date = add_days(backtest_end_date, -validation_window_days)

	leaf_warehouses = group_mod.resolve_planning_warehouse_group(planning_warehouse)["leaf_warehouses"]

	# "What really happened" -- pulled once for the whole validation window,
	# used ONLY to advance simulated on_hand day-by-day. Never touches the
	# checkpoint ROP/Target calculation below.
	actual_demand_rows = []
	for leaf in leaf_warehouses:
		result = demand_mod.get_demand_history(
			warehouse=leaf, item_code=item_code, from_date=backtest_start_date, to_date=backtest_end_date,
			company=company,
		)
		actual_demand_rows.extend(result["rows"])
	actual_daily_series = build_daily_demand_series(actual_demand_rows, backtest_start_date, backtest_end_date)

	# Starting on-hand/reserved snapshot: real current Bin values. Reserved
	# is held constant for the whole simulation -- Bin only stores a live
	# snapshot, Stock Ledger Entry has no reservation history, so there is no
	# historical reserved-qty time series to reconstruct. Documented
	# limitation, surfaced in `config` below, not hidden.
	stock_rows = stock_mod.get_stock_snapshot_bulk([item_code], leaf_warehouses)
	aggregated_stock = group_mod.aggregate_stock(stock_rows)

	state = {
		"on_hand": aggregated_stock["actual_qty"],
		"reserved": aggregated_stock["reserved_qty"],
		"open_orders": [],
	}

	trace: list = []
	orders: list = []
	rop_history: list = []
	target_history: list = []

	checkpoint_dates = _checkpoint_dates(backtest_start_date, backtest_end_date, step_days)
	checkpoint_set = set(checkpoint_dates)
	current_rop, current_target = 0.0, 0.0

	total_days = date_diff(backtest_end_date, backtest_start_date) + 1
	for day_offset in range(total_days):
		day = add_days(backtest_start_date, day_offset)

		# Recompute ROP/Target only at each checkpoint (held constant in
		# between) -- the confirmed cadence. Reuses the same group-aware
		# pipeline the live page uses, with to_date pinned strictly before
		# `day`.
		if day in checkpoint_set:
			checkpoint_options = dict(options)
			checkpoint_options["from_date"] = add_days(day, -training_window_days)
			checkpoint_options["to_date"] = add_days(day, -1)
			checkpoint_result = service_mod.analyze_item(item_code, planning_warehouse, checkpoint_options)
			current_rop = checkpoint_result["reorder_point"]
			current_target = checkpoint_result["target_stock"]
			rop_history.append(current_rop)
			target_history.append(current_target)

		demand_qty = actual_daily_series[day_offset] if day_offset < len(actual_daily_series) else 0.0
		day_trace = _simulate_day(
			state=state,
			day=day,
			actual_demand_qty=demand_qty,
			rop=current_rop,
			target=current_target,
			planning_lead_time_days=options.get("planning_lead_time_days") or 120,
			review_period_days=options.get("review_period_days") or 1,
			orders_sink=orders,
		)
		trace.append(day_trace)

	avg_valuation_rate = (
		aggregated_stock["stock_value"] / aggregated_stock["actual_qty"] if aggregated_stock["actual_qty"] else 0.0
	)
	computed_metrics = metrics_mod.compute_all_metrics(
		trace=trace,
		orders=orders,
		rop_history=rop_history,
		target_history=target_history,
		valuation_rate=avg_valuation_rate,
	)

	lead_time_days = options.get("planning_lead_time_days") or 120
	review_period_days = options.get("review_period_days") or 1
	avg_daily_demand = sum(actual_daily_series) / len(actual_daily_series) if actual_daily_series else 0.0

	native_config = baseline_mod.get_native_erpnext_reorder_config(item_code, leaf_warehouses)
	native_result = None
	if native_config:
		native_result = baseline_mod.simulate_native_erpnext_baseline(
			actual_daily_series=actual_daily_series,
			start_on_hand=aggregated_stock["actual_qty"],
			reserved_qty=aggregated_stock["reserved_qty"],
			reorder_level=native_config["warehouse_reorder_level"],
			reorder_qty=native_config["warehouse_reorder_qty"],
			lead_time_days=lead_time_days,
			review_period_days=review_period_days,
		)

	baselines = {
		"avg_demand_lead_time_rop": baseline_mod.compute_avg_demand_lead_time_baseline(
			avg_daily_demand, lead_time_days
		),
		"min_max": baseline_mod.compute_min_max_baseline(avg_daily_demand, lead_time_days),
		"native_erpnext": {"config": native_config, "result": native_result} if native_config else None,
	}

	return {
		"trace": trace,
		"orders": orders,
		"metrics": computed_metrics,
		"baselines": baselines,
		"config": {
			"item_code": item_code,
			"planning_warehouse": planning_warehouse,
			"leaf_warehouses": leaf_warehouses,
			"training_window_days": training_window_days,
			"validation_window_days": validation_window_days,
			"step_days": step_days,
			"backtest_start_date": str(backtest_start_date),
			"backtest_end_date": str(backtest_end_date),
			"reserved_qty_note": (
				"Reserved Qty held constant at today's snapshot for the whole simulation -- "
				"historical reservation levels are not reconstructable from available data."
			),
		},
	}


def _checkpoint_dates(start_date, end_date, step_days) -> list:
	"""First checkpoint is always start_date itself (an initial ROP/Target is
	needed before day 0's reorder decision can be evaluated), then every
	step_days thereafter."""
	step_days = max(1, int(step_days))
	dates = []
	day = start_date
	while day <= end_date:
		dates.append(day)
		day = add_days(day, step_days)
	return dates


def _simulate_day(
	*, state: dict, day, actual_demand_qty: float, rop: float, target: float,
	planning_lead_time_days: int, review_period_days: int, orders_sink: list,
) -> dict:
	"""Mutates `state` in place (on_hand, open_orders); appends to
	`orders_sink` when a simulated order is placed. Returns this day's trace
	row. `state["open_orders"]` is exactly the mechanism that prevents the
	simulation from double-ordering while a prior simulated order is still
	in flight -- outstanding_qty always sums every currently-open order."""
	arriving = [o for o in state["open_orders"] if o["expected_arrival_date"] == day]
	for order in arriving:
		state["on_hand"] += order["qty"]
	if arriving:
		state["open_orders"] = [o for o in state["open_orders"] if o["expected_arrival_date"] != day]

	stockout_qty = 0.0
	if actual_demand_qty > state["on_hand"]:
		stockout_qty = actual_demand_qty - state["on_hand"]
		state["on_hand"] = 0.0
	else:
		state["on_hand"] -= actual_demand_qty

	outstanding_qty = sum(o["qty"] for o in state["open_orders"])
	planning_position = compute_planning_position(state["on_hand"], outstanding_qty, state["reserved"])

	orders_placed_today = 0
	if planning_position <= rop:
		recommended = compute_recommended_qty(planning_position, rop, target)
		if recommended > 0:
			expected_arrival = add_days(day, planning_lead_time_days + review_period_days)
			order = {"order_date": day, "expected_arrival_date": expected_arrival, "qty": recommended}
			state["open_orders"].append(order)
			orders_sink.append(order)
			orders_placed_today = 1

	return {
		"date": str(day),
		"on_hand": state["on_hand"],
		"outstanding_qty": outstanding_qty,
		"reserved": state["reserved"],
		"planning_position": planning_position,
		"rop": rop,
		"target": target,
		"demand_qty": actual_demand_qty,
		"stockout_qty": stockout_qty,
		"orders_placed_today": orders_placed_today,
		"open_order_count": len(state["open_orders"]),
	}
