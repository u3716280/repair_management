"""Confidence scoring: High/Medium/Low + machine-readable reasons. Pure
logic -- takes already-computed values from calculation.py plus Phase 0's
DataException list; makes no frappe.db calls itself.
"""

from .calculation import DEMAND_INTERMITTENT, DEMAND_NO_HISTORY, DEMAND_SLOW, MIN_DEMAND_EVENTS_FOR_STATS
from .exceptions import ExceptionCode

_LEVELS = {2: "High", 1: "Medium", 0: "Low"}

# These exception codes mean the underlying classification itself is
# untrustworthy, not just "thin data" -- they force Low regardless of anything else.
_FORCE_LOW_CODES = {ExceptionCode.UNKNOWN_VOUCHER, ExceptionCode.UNCLASSIFIED_MOVEMENT}


def compute_confidence(
	*,
	demand_type: str,
	demand_events: int,
	analysis_days: int,
	target_horizon_days: int,
	rop_method: str,
	target_method: str,
	exceptions: list,
	lead_time_sample_count: int,
) -> dict:
	"""Returns {"level": "High"|"Medium"|"Low", "reasons": [str, ...]}."""
	if demand_type == DEMAND_NO_HISTORY:
		return {"level": "Low", "reasons": ["No demand history in the analysis window"]}

	score = 2
	reasons = []

	forced_low_count = sum(1 for e in exceptions if e.code in _FORCE_LOW_CODES)
	if forced_low_count:
		score = 0
		reasons.append(f"{forced_low_count} unclassified/unknown transaction(s) -- classification uncertain")

	if demand_type in (DEMAND_SLOW, DEMAND_INTERMITTENT):
		score = min(score, 1)
		reasons.append(f"{demand_type} demand pattern")

	if demand_events < MIN_DEMAND_EVENTS_FOR_STATS:
		score = min(score, 1)
		reasons.append(f"Only {demand_events} demand event(s) in {analysis_days} days")

	if rop_method == "average_fallback" or target_method == "average_fallback":
		score = min(score, 0)
		reasons.append("Rolling window longer than available history -- using average-based estimate")

	if analysis_days < target_horizon_days * 2 and rop_method != "average_fallback":
		score = min(score, 1)
		reasons.append("Limited rolling-window sample size relative to the target horizon")

	other_exceptions = [e for e in exceptions if e.code not in _FORCE_LOW_CODES]
	if other_exceptions:
		score = max(0, score - 1)
		reasons.append(f"{len(other_exceptions)} data exception(s) flagged for review")

	if lead_time_sample_count == 0:
		reasons.append("No historical lead-time data available (using configured Planning Lead Time only)")

	if not reasons:
		reasons.append("Sufficient history, no data exceptions")

	return {"level": _LEVELS[score], "reasons": reasons}
