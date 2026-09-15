"""Metrics suite over a backtest trace (Phase 2). Pure post-hoc math, no
frappe.db calls -- takes the trace/orders lists backtest.py already built.
Every formula below is a stated design decision (the spec names the
metrics, not their formulas) -- see PHASE2_NOTES.md for the reasoning behind
each choice; nothing here is a hidden default.
"""

import statistics

# Interpolated from the spec's own two illustrative series: a "stable" ROP
# history (18,19,17,18) has cv ~= 0.045; an "unstable" one (8,30,12,27) has
# cv ~= 0.52. 0.25 sits comfortably between the two -- a provisional default,
# not a validated statistical result, subject to revision once real backtest
# output has been reviewed.
STABILITY_CV_THRESHOLD = 0.25

# Flags an item's actual-vs-configured lead time as mismatched when they
# diverge by more than this fraction. An arbitrary but defensible round
# number, consistent with this app's other ~30%-ish tolerance conventions
# (e.g. Extra Coverage's own 30-day minimum). Never auto-corrects
# Item.lead_time_days -- flag only, for a human to act on.
LEAD_TIME_MISMATCH_THRESHOLD = 0.30


def compute_stockout_metrics(trace: list) -> dict:
	"""stockout_events/stockout_days: a stockout that recurs across N
	consecutive days without a receipt in between counts as N events, not 1
	-- each day's own shortfall against that day's own demand is a distinct
	event. fill_rate is qty-weighted (% of demanded UNITS actually served);
	cycle_service_level is event-count-weighted (classic textbook
	definition) -- these are deliberately different metrics, not two names
	for the same number."""
	stockout_days = sum(1 for day in trace if day["stockout_qty"] > 0)
	stockout_qty = sum(day["stockout_qty"] for day in trace)
	demand_days = [day for day in trace if day["demand_qty"] > 0]
	total_demand_qty = sum(day["demand_qty"] for day in trace)
	total_demand_events = len(demand_days)

	fill_rate = 1 - (stockout_qty / total_demand_qty) if total_demand_qty else None
	cycle_service_level = 1 - (stockout_days / total_demand_events) if total_demand_events else None

	return {
		"stockout_events": stockout_days,
		"stockout_days": stockout_days,
		"stockout_qty": stockout_qty,
		"fill_rate": fill_rate,
		"cycle_service_level": cycle_service_level,
		"demand_events_fully_served": (total_demand_events - stockout_days) if total_demand_events else None,
	}


def compute_inventory_metrics(trace: list) -> dict:
	"""excess_stock_days is measured against each day's OWN target (which may
	itself have changed between checkpoints), not one fixed global
	threshold."""
	if not trace:
		return {
			"average_inventory": 0.0, "max_inventory": 0.0, "min_inventory": 0.0,
			"average_days_of_supply": None, "excess_stock_days": 0,
		}
	on_hand_values = [day["on_hand"] for day in trace]
	average_inventory = statistics.fmean(on_hand_values)
	total_demand_qty = sum(day["demand_qty"] for day in trace)
	average_daily_demand = total_demand_qty / len(trace) if trace else 0.0

	return {
		"average_inventory": average_inventory,
		"max_inventory": max(on_hand_values),
		"min_inventory": min(on_hand_values),
		"average_days_of_supply": (average_inventory / average_daily_demand) if average_daily_demand else None,
		"excess_stock_days": sum(1 for day in trace if day["on_hand"] > day["target"]),
	}


def compute_order_metrics(orders: list) -> dict:
	if not orders:
		return {"number_of_orders": 0, "average_order_qty": None, "max_order_qty": None}
	quantities = [order["qty"] for order in orders]
	return {
		"number_of_orders": len(orders),
		"average_order_qty": statistics.fmean(quantities),
		"max_order_qty": max(quantities),
	}


def compute_inventory_value(trace: list, valuation_rate: float) -> dict:
	"""average_inventory_value = average on-hand qty * a single representative
	valuation rate (from Bin.valuation_rate at backtest start) -- the
	backtest tracks quantity only, not day-by-day cost layers, so a full
	historical valuation simulation is out of scope; this is an explicit
	simplification, not a precise costing."""
	if not trace:
		return {"average_inventory_value": 0.0}
	average_inventory = statistics.fmean(day["on_hand"] for day in trace)
	return {"average_inventory_value": average_inventory * (valuation_rate or 0.0)}


def compute_stability(rop_history: list, target_history: list) -> dict:
	"""Coefficient of variation (stdev/mean) of the checkpoint-by-checkpoint
	ROP/Target history. STABILITY_CV_THRESHOLD (0.25) is a provisional,
	stated default -- see module docstring."""

	def _cv(values):
		if len(values) < 2:
			return None
		mean = statistics.fmean(values)
		if not mean:
			return None
		return statistics.stdev(values) / mean

	rop_cv = _cv(rop_history)
	target_cv = _cv(target_history)
	return {
		"rop_cv": rop_cv,
		"target_cv": target_cv,
		"rop_stable": (rop_cv is not None and rop_cv <= STABILITY_CV_THRESHOLD),
		"target_stable": (target_cv is not None and target_cv <= STABILITY_CV_THRESHOLD),
	}


def detect_outliers(demand_events_qty: list) -> list:
	"""IQR/Tukey-fence method (flag values > Q3 + 1.5*(Q3-Q1)), chosen over
	z-score since demand here is typically sparse/right-skewed (per
	classify_demand_type's own Slow/Intermittent buckets), where z-score
	(assumes a near-normal distribution) tends to under-flag with few
	samples. Needs >= 4 events to compute a meaningful quartile split;
	returns no flags below that rather than flagging on a near-meaningless
	split of 1-3 points. Returns the (0-based) indices of flagged values."""
	if len(demand_events_qty) < 4:
		return []
	sorted_vals = sorted(demand_events_qty)
	n = len(sorted_vals)
	q1 = sorted_vals[n // 4]
	q3 = sorted_vals[(3 * n) // 4]
	fence = q3 + 1.5 * (q3 - q1)
	return [i for i, value in enumerate(demand_events_qty) if value > fence]


def compute_lead_time_mismatch(configured_lead_time_days: float, actual_lead_time_p90: float | None) -> dict:
	"""Never auto-corrects Item.lead_time_days -- returns a flag + both
	numbers for a human to act on."""
	if actual_lead_time_p90 is None or not configured_lead_time_days:
		return {"mismatch": False, "configured": configured_lead_time_days, "actual_p90": actual_lead_time_p90}
	ratio = abs(actual_lead_time_p90 - configured_lead_time_days) / max(configured_lead_time_days, 1)
	return {
		"mismatch": ratio > LEAD_TIME_MISMATCH_THRESHOLD,
		"configured": configured_lead_time_days,
		"actual_p90": actual_lead_time_p90,
		"ratio": ratio,
	}


def compute_all_metrics(*, trace: list, orders: list, rop_history: list, target_history: list, valuation_rate: float) -> dict:
	"""Convenience aggregator used by backtest.py -- runs every metric
	function above over one backtest's output."""
	return {
		**compute_stockout_metrics(trace),
		**compute_inventory_metrics(trace),
		**compute_order_metrics(orders),
		**compute_inventory_value(trace, valuation_rate),
		"stability": compute_stability(rop_history, target_history),
	}
