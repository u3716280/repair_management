"""Pure calculation engine for Reorder Analysis. No frappe.db/frappe.get_all
calls anywhere in this file -- everything here is plain-Python math over data
already fetched by service.py from the Phase 0 data layer. Fully
unit-testable without a database.

Percentile and rolling-sum algorithms are reused verbatim (same formulas)
from repair_management/repair_management/page/reorder_point_calcul/
reorder_point_calcul.py's `_percentile`/`_rolling_sums`, so the app's two
reorder-related pages never disagree on what "P90" or "a 121-day rolling
window" means.
"""

import math
import statistics

import frappe
from frappe.utils import cint, date_diff, getdate

from .classification import NET_SIGN

# ---- module-level configuration (MVP: plain constants, not a doctype -- see PHASE1_NOTES.md) ----

DEFAULT_OPTIONS = {
	# None (not 120) is the sentinel for "no explicit Planning Lead Time
	# override" -- calculate_item_reorder() falls back to the Item's own
	# lead_time_days master field first, and only to
	# DEFAULT_PLANNING_LEAD_TIME_DAYS below if that Item has none set.
	"planning_lead_time_days": None,
	"review_period_days": 1,
	"extra_coverage_days": 30,
	"service_level": "Auto",  # "Auto" | "P85" | "P95" (Phase 2 narrowed from P80/P90/P95/P99)
}

DEFAULT_PLANNING_LEAD_TIME_DAYS = 120

LEAD_TIME_SOURCE_OVERRIDE = "override"
LEAD_TIME_SOURCE_ITEM_MASTER = "item_master"
LEAD_TIME_SOURCE_SYSTEM_DEFAULT = "system_default"

# Phase 2: Criticality (never really used -- everyone defaulted to "Normal")
# is replaced by the Replenishment Policy classification itself as the
# criticality signal. SLOW_CRITICAL is the sole P95 trigger; every other
# batch-eligible policy gets P85. See policy.py.
POLICY_TO_PERCENTILE = {"SLOW_CRITICAL": 95, "STOCKED": 85, "INTERMITTENT": 85}
DEFAULT_POLICY_PERCENTILE = 85

# Reuses reorder_point_calcul.py's MIN_EVENTS_FOR_PERCENTILE value, for
# consistency across the app's two reorder-related pages.
MIN_DEMAND_EVENTS_FOR_STATS = 5
ADI_REGULAR_THRESHOLD_DAYS = 7
ADI_SLOW_THRESHOLD_DAYS = 60

DEMAND_NO_HISTORY = "No History"
DEMAND_REGULAR = "Regular"
DEMAND_INTERMITTENT = "Intermittent"
DEMAND_SLOW = "Slow"

STATUS_CRITICAL = "Critical"
STATUS_REORDER = "Reorder"
STATUS_REVIEW = "Review"
STATUS_NO_HISTORY = "No History"
STATUS_OK = "OK"

STATUS_SORT_ORDER = {
	STATUS_CRITICAL: 0,
	STATUS_REORDER: 1,
	STATUS_REVIEW: 2,
	STATUS_NO_HISTORY: 3,
	STATUS_OK: 4,
}


def compute_protection_period(planning_lead_time_days, review_period_days) -> int:
	"""protection_period = planning_lead_time + review_period (e.g. 120+1=121)."""
	return int(planning_lead_time_days) + int(review_period_days)


def compute_target_horizon(planning_lead_time_days, review_period_days, extra_coverage_days) -> int:
	"""target_horizon = planning_lead_time + review_period + extra_coverage (e.g. 120+1+30=151)."""
	return int(planning_lead_time_days) + int(review_period_days) + int(extra_coverage_days)


def build_daily_demand_series(rows: list, from_date, to_date) -> list:
	"""Zero-filled daily net-demand series over [from_date, to_date] inclusive.
	Only CONSUMPTION (+1) and RETURN (-1) rows contribute, via NET_SIGN --
	every other classification (TRANSFER/SUPPLY/ADJUSTMENT/IGNORE/REVIEW) has
	net_sign 0 and is a no-op, so no explicit classification filter is needed
	beyond reusing NET_SIGN. O(n) over `rows`, one pass."""
	from_date = getdate(from_date)
	to_date = getdate(to_date)
	n = date_diff(to_date, from_date) + 1
	series = [0.0] * max(n, 0)
	for row in rows:
		sign = NET_SIGN.get(row["classification"], 0)
		if sign == 0:
			continue
		idx = date_diff(getdate(row["posting_date"]), from_date)
		if 0 <= idx < n:
			series[idx] += sign * row["demand_qty"]
	return series


def rolling_sum(daily_series: list, window_days) -> list:
	"""Sliding-window sum, O(n) via incremental prefix-sum update (identical
	algorithm to reorder_point_calcul.py's _rolling_sums). Returns [] if
	window_days <= 0 or the series is shorter than the window (cannot build
	even one full window -- caller falls back to an average-based estimate,
	see _rolling_window_percentile)."""
	window = cint(window_days)
	if window <= 0 or len(daily_series) < window:
		return []
	sums = []
	current = sum(daily_series[:window])
	sums.append(current)
	for i in range(window, len(daily_series)):
		current += daily_series[i] - daily_series[i - window]
		sums.append(current)
	return sums


def percentile(values: list, pct: float) -> float:
	"""Linear-interpolation percentile, identical to numpy.percentile's
	default and to reorder_point_calcul.py's own _percentile."""
	if not values:
		return 0.0
	sorted_vals = sorted(values)
	k = (len(sorted_vals) - 1) * (pct / 100)
	f = math.floor(k)
	c = math.ceil(k)
	if f == c:
		return sorted_vals[int(k)]
	d0 = sorted_vals[f] * (c - k)
	d1 = sorted_vals[c] * (k - f)
	return d0 + d1


def rolling_distribution_stats(rolling_values: list) -> dict | None:
	"""mean/median/p80/p90/p95/max of a rolling-sum distribution. Returns None
	(not zeros) when rolling_values is empty, so the UI can render "N/A"
	instead of a falsely-precise 0."""
	if not rolling_values:
		return None
	return {
		"mean": statistics.fmean(rolling_values),
		"median": statistics.median(rolling_values),
		"p80": percentile(rolling_values, 80),
		"p90": percentile(rolling_values, 90),
		"p95": percentile(rolling_values, 95),
		"max": max(rolling_values),
	}


def _rolling_window_percentile(daily_series: list, window_days, service_percentile: float) -> dict:
	"""Shared engine behind compute_rop/compute_target_stock. Returns
	{"value", "method", "rolling_values"}. method is "percentile" when at
	least one full window fits in the series, else "average_fallback" (the
	analysis window is shorter than window_days) which uses avg_daily *
	window instead. Never returns a negative value."""
	window = cint(window_days)
	if window <= 0:
		return {"value": 0.0, "method": "zero_window", "rolling_values": []}
	values = rolling_sum(daily_series, window)
	if values:
		return {
			"value": max(0.0, percentile(values, service_percentile)),
			"method": "percentile",
			"rolling_values": values,
		}
	avg_daily = statistics.fmean(daily_series) if daily_series else 0.0
	return {"value": max(0.0, avg_daily * window), "method": "average_fallback", "rolling_values": []}


def compute_rop(daily_series: list, protection_period_days, service_percentile: float) -> dict:
	"""ROP = Percentile(rolling protection-period-window demand distribution)."""
	return _rolling_window_percentile(daily_series, protection_period_days, service_percentile)


def compute_target_stock(daily_series: list, target_horizon_days, service_percentile: float) -> dict:
	"""Target Stock = Percentile(rolling target-horizon-window demand distribution)."""
	return _rolling_window_percentile(daily_series, target_horizon_days, service_percentile)


def compute_planning_position(actual_qty, total_outstanding_qty, reserved_qty) -> float:
	"""Planning Position = Actual Qty + Total Outstanding PO (ALL reliability,
	RELIABLE and LATE alike) - Reserved Qty.

	Phase 2 change: late/overdue POs are now treated as good as arrived --
	the model must not double-order just because a schedule_date looks
	stale, and a Schedule Date's accuracy is a Purchase Follow-up concern,
	not a Planning Position one. This deliberately REVERSES Phase 1's
	formula, which excluded Late Incoming entirely (see PHASE2_NOTES.md
	Breaking Changes). Lateness is still surfaced separately (see group.py's
	`follow_up`), just never subtracted here."""
	return float(actual_qty) + float(total_outstanding_qty) - float(reserved_qty)


def compute_recommended_qty(planning_position: float, rop: float, target_stock: float) -> float:
	"""No MOQ/order-multiple rounding (explicit non-requirement)."""
	if planning_position <= rop:
		return max(0.0, target_stock - planning_position)
	return 0.0


def classify_demand_type(demand_events: int, analysis_days: int) -> str:
	"""0 events -> No History; fewer than MIN_DEMAND_EVENTS_FOR_STATS -> Slow
	(too few points for any statistic to be trustworthy); otherwise classify
	by the average gap between demand-active days."""
	if demand_events == 0:
		return DEMAND_NO_HISTORY
	if demand_events < MIN_DEMAND_EVENTS_FOR_STATS:
		return DEMAND_SLOW
	adi = analysis_days / demand_events
	if adi <= ADI_REGULAR_THRESHOLD_DAYS:
		return DEMAND_REGULAR
	if adi <= ADI_SLOW_THRESHOLD_DAYS:
		return DEMAND_INTERMITTENT
	return DEMAND_SLOW


def compute_status(planning_position: float, rop: float, demand_type: str, confidence_level: str) -> str:
	"""Explicit precedence (first match wins): an item can simultaneously
	satisfy several of the spec's plain-English status conditions (e.g.
	planning_position<=0 AND insufficient history at once), so a fixed
	precedence chain resolves the ambiguity: an unconditional stockout fact
	(Critical) always wins, then lack of any usable history, then low
	analytical confidence, then the plain reorder/OK comparison."""
	if planning_position <= 0:
		return STATUS_CRITICAL
	if demand_type == DEMAND_NO_HISTORY:
		return STATUS_NO_HISTORY
	if confidence_level == "Low":
		return STATUS_REVIEW
	if planning_position <= rop:
		return STATUS_REORDER
	return STATUS_OK


def resolve_service_percentile(service_level: str | None, policy: str) -> float:
	"""'Auto' (or falsy) -> POLICY_TO_PERCENTILE.get(policy, DEFAULT_POLICY_PERCENTILE);
	an explicit override must be 'P85' or 'P95' -- Phase 2 narrows service
	levels to just these two. Any other explicit "P" value (P80/P90/P99,
	valid in Phase 1) is now a hard error, a deliberate stop rather than a
	silent reinterpretation, so nobody believes they got P90 math when they
	didn't."""
	if service_level and service_level.upper().startswith("P"):
		pct = float(service_level[1:])
		if pct not in (85.0, 95.0):
			frappe.throw(f"Unsupported service_level override: {service_level!r} (only P85/P95 are allowed)")
		return pct
	return float(POLICY_TO_PERCENTILE.get(policy, DEFAULT_POLICY_PERCENTILE))


def calculate_item_reorder(
	*,
	item_code: str,
	warehouse: str,
	item_name: str,
	stock_uom: str,
	configured_lead_time_days,
	demand_rows: list,
	demand_exceptions: list,
	stock_row: dict | None,
	incoming_rows: list,
	incoming_exceptions: list,
	lead_time_rows: list,
	from_date,
	to_date,
	options: dict,
) -> dict:
	"""Top-level pipeline. Returns every Calculation Contract field, PLUS
	detail-only extras (rop_method, target_method, rop_rolling_values,
	actual_lead_time_avg, actual_lead_time_p90, lead_time_sample_count,
	policy_reasons) that service.analyze_items() strips before returning
	bulk rows. Order of computation matters: demand stats -> demand-type
	classification -> Replenishment Policy (needs a preliminary ROP-method
	read, see below) -> service_percentile (policy-driven) -> ROP/Target/
	Position -> confidence -> status (needs confidence)."""
	from .confidence import compute_confidence
	from .demand import summarize_demand
	from .policy import classify_replenishment_policy

	analysis_days = date_diff(getdate(to_date), getdate(from_date)) + 1

	summary = summarize_demand(demand_rows, warehouse=warehouse)
	total_demand = summary["net_demand"]

	daily_series = build_daily_demand_series(demand_rows, from_date, to_date)
	demand_events = sum(1 for v in daily_series if v != 0)
	average_demand_per_event = (total_demand / demand_events) if demand_events else 0.0
	average_monthly_demand = (total_demand / analysis_days) * 30 if analysis_days else 0.0

	demand_type = classify_demand_type(demand_events, analysis_days)

	explicit_planning_lead_time = options.get("planning_lead_time_days")
	if explicit_planning_lead_time is not None:
		planning_lead_time = explicit_planning_lead_time
		lead_time_source = LEAD_TIME_SOURCE_OVERRIDE
	elif configured_lead_time_days:
		planning_lead_time = configured_lead_time_days
		lead_time_source = LEAD_TIME_SOURCE_ITEM_MASTER
	else:
		planning_lead_time = DEFAULT_PLANNING_LEAD_TIME_DAYS
		lead_time_source = LEAD_TIME_SOURCE_SYSTEM_DEFAULT
	review_period = options["review_period_days"]
	extra_coverage = options["extra_coverage_days"]
	protection_period = compute_protection_period(planning_lead_time, review_period)
	target_horizon = compute_target_horizon(planning_lead_time, review_period, extra_coverage)

	# Whether a full protection-period rolling window fits in the available
	# history depends only on daily_series/protection_period, never on which
	# percentile will eventually be used -- so this can be determined before
	# Policy/service_percentile are known, breaking what would otherwise be
	# a circular dependency (Policy's SLOW_CRITICAL-vs-REVIEW branch needs to
	# know this "percentile" vs "average_fallback" method).
	preliminary_rop_method = "percentile" if rolling_sum(daily_series, protection_period) else "average_fallback"

	policy_result = classify_replenishment_policy(
		demand_type=demand_type,
		demand_events=demand_events,
		analysis_days=analysis_days,
		rop_method=preliminary_rop_method,
		manual_policy_override=options.get("manual_policy_override"),
	)
	policy = policy_result["policy"]

	service_percentile = resolve_service_percentile(options.get("service_level"), policy)

	rop_result = compute_rop(daily_series, protection_period, service_percentile)
	target_result = compute_target_stock(daily_series, target_horizon, service_percentile)
	rolling_stats = rolling_distribution_stats(rop_result["rolling_values"])

	stock_row = stock_row or {}
	actual_qty = float(stock_row.get("actual_qty") or 0)
	reserved_qty = float(stock_row.get("reserved_qty") or 0)

	reliable_incoming = sum(r["remaining_qty_stock_uom"] for r in incoming_rows if r["reliability"] == "RELIABLE")
	late_incoming = sum(r["remaining_qty_stock_uom"] for r in incoming_rows if r["reliability"] == "LATE")
	total_outstanding_qty = reliable_incoming + late_incoming

	planning_position = compute_planning_position(actual_qty, total_outstanding_qty, reserved_qty)
	recommended_qty = compute_recommended_qty(planning_position, rop_result["value"], target_result["value"])

	all_exceptions = list(demand_exceptions) + list(incoming_exceptions)

	lead_time_days_list = [r["lead_time_days"] for r in lead_time_rows]
	actual_lead_time_avg = statistics.fmean(lead_time_days_list) if lead_time_days_list else None
	actual_lead_time_p90 = percentile(lead_time_days_list, 90) if lead_time_days_list else None

	confidence = compute_confidence(
		demand_type=demand_type,
		demand_events=demand_events,
		analysis_days=analysis_days,
		target_horizon_days=target_horizon,
		rop_method=rop_result["method"],
		target_method=target_result["method"],
		exceptions=all_exceptions,
		lead_time_sample_count=len(lead_time_rows),
	)
	status = compute_status(planning_position, rop_result["value"], demand_type, confidence["level"])

	return {
		# ---- Calculation Contract fields ----
		"item_code": item_code,
		"item_name": item_name,
		"warehouse": warehouse,
		"stock_uom": stock_uom,
		"analysis_days": analysis_days,
		"demand_type": demand_type,
		"demand_events": demand_events,
		"total_demand": total_demand,
		"average_demand_per_event": average_demand_per_event,
		"average_monthly_demand": average_monthly_demand,
		"configured_lead_time": configured_lead_time_days,
		"planning_lead_time": planning_lead_time,
		"review_period": review_period,
		"protection_period": protection_period,
		"service_level": options.get("service_level") or "Auto",
		"service_percentile": service_percentile,
		"rolling_mean": rolling_stats["mean"] if rolling_stats else None,
		"rolling_median": rolling_stats["median"] if rolling_stats else None,
		"rolling_p80": rolling_stats["p80"] if rolling_stats else None,
		"rolling_p90": rolling_stats["p90"] if rolling_stats else None,
		"rolling_p95": rolling_stats["p95"] if rolling_stats else None,
		"rolling_max": rolling_stats["max"] if rolling_stats else None,
		"reorder_point": rop_result["value"],
		"actual_qty": actual_qty,
		"reserved_qty": reserved_qty,
		"reliable_incoming": reliable_incoming,
		"late_incoming": late_incoming,
		"total_outstanding_qty": total_outstanding_qty,
		"planning_position": planning_position,
		"target_horizon": target_horizon,
		"target_stock": target_result["value"],
		"recommended_qty": recommended_qty,
		"policy": policy,
		"status": status,
		"confidence": confidence["level"],
		"confidence_reason": confidence["reasons"],
		"exception_count": len(all_exceptions),
		"exceptions": [e.as_dict() for e in all_exceptions],
		# ---- detail-only extras, stripped by service.analyze_items() ----
		"rop_method": rop_result["method"],
		"target_method": target_result["method"],
		"rop_rolling_values": rop_result["rolling_values"],
		"actual_lead_time_avg": actual_lead_time_avg,
		"actual_lead_time_p90": actual_lead_time_p90,
		"lead_time_sample_count": len(lead_time_rows),
		"lead_time_source": lead_time_source,
		"policy_reasons": policy_result["reasons"],
	}


CONTRACT_FIELDS = [
	"item_code", "item_name", "warehouse", "stock_uom", "analysis_days", "demand_type",
	"demand_events", "total_demand", "average_demand_per_event", "average_monthly_demand",
	"configured_lead_time", "planning_lead_time", "review_period", "protection_period",
	"service_level", "service_percentile", "rolling_mean", "rolling_median", "rolling_p80",
	"rolling_p90", "rolling_p95", "rolling_max", "reorder_point", "actual_qty", "reserved_qty",
	"reliable_incoming", "late_incoming", "total_outstanding_qty", "planning_position",
	"target_horizon", "target_stock", "recommended_qty", "policy", "status", "confidence",
	"confidence_reason", "exception_count", "exceptions",
]
