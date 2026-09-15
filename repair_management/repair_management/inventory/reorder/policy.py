"""Replenishment Policy classification (Phase 2). Pure logic, no frappe.db
calls -- same convention as calculation.py. Computed fresh from demand stats
each analysis run, never persisted as Item master data (see PHASE2_NOTES.md
for why: no per-item schema change was wanted for this phase).

Deliberately NOT a replacement for calculation.classify_demand_type -- that
function (Regular/Intermittent/Slow/No History) remains the statistical
backbone and is still computed/returned as-is. classify_replenishment_policy
takes its output as one input among several to produce the broader 8-value
taxonomy the business actually plans purchasing around.
"""

from .calculation import DEMAND_INTERMITTENT, DEMAND_NO_HISTORY, DEMAND_REGULAR

POLICY_STOCKED = "STOCKED"
POLICY_INTERMITTENT = "INTERMITTENT"
POLICY_SLOW_CRITICAL = "SLOW_CRITICAL"
POLICY_BUY_TO_ORDER = "BUY_TO_ORDER"
POLICY_ONE_TIME = "ONE_TIME"
POLICY_NO_HISTORY = "NO_HISTORY"
POLICY_MANUAL = "MANUAL"
POLICY_REVIEW = "REVIEW"
POLICY_EXCLUDE = "EXCLUDE"

# Only these three are ever auto-assigned into the default batch/backtest
# universe. BUY_TO_ORDER/MANUAL/EXCLUDE are never derivable from demand
# history alone (no signal distinguishes "always custom-ordered" from
# "currently just low-demand") -- they only ever appear via
# manual_policy_override on a single-item analysis, never in a batch run.
ELIGIBLE_FOR_BATCH = {POLICY_STOCKED, POLICY_INTERMITTENT, POLICY_SLOW_CRITICAL}

_NEVER_AUTO_ASSIGNED = {POLICY_BUY_TO_ORDER, POLICY_MANUAL, POLICY_EXCLUDE}


def classify_replenishment_policy(
	*,
	demand_type: str,
	demand_events: int,
	analysis_days: int,
	rop_method: str,
	manual_policy_override: str | None = None,
) -> dict:
	"""Returns {"policy": <one of the 9 constants above>, "reasons": [str, ...]}.

	Decision tree (first match wins):
	1. manual_policy_override, if given, wins outright (only ever supplied by
	   the single-item drill-down path -- never applied to a batch run, never
	   persisted).
	2. No demand history at all -> NO_HISTORY.
	3. Exactly one demand event in the whole window -> ONE_TIME (a deliberate
	   choice over lumping it into REVIEW -- see PHASE2_NOTES.md open
	   question #1 -- ONE_TIME is a more useful purchasing signal than a
	   generic "not enough data" label, and both are batch-excluded anyway).
	4. Regular/Intermittent demand_type -> STOCKED/INTERMITTENT directly.
	5. Slow demand_type (2-4 events, or a wide average gap): if the rolling
	   window couldn't even be built once from the available history
	   (rop_method == "average_fallback") -> REVIEW (data too sparse to
	   trust); otherwise -> SLOW_CRITICAL.
	"""
	if manual_policy_override:
		return {"policy": manual_policy_override, "reasons": ["Manual policy override"]}

	if demand_type == DEMAND_NO_HISTORY:
		return {"policy": POLICY_NO_HISTORY, "reasons": ["No demand history in the analysis window"]}

	if demand_events == 1:
		return {
			"policy": POLICY_ONE_TIME,
			"reasons": ["Exactly one demand event in the analysis window -- possibly a one-time/project item"],
		}

	if demand_type == DEMAND_REGULAR:
		return {"policy": POLICY_STOCKED, "reasons": ["Regular demand pattern"]}

	if demand_type == DEMAND_INTERMITTENT:
		return {"policy": POLICY_INTERMITTENT, "reasons": ["Intermittent demand pattern"]}

	# demand_type == "Slow" from here on (or any unrecognized value -- treat
	# the same as Slow rather than silently defaulting to a batch-eligible
	# policy on unexpected input).
	if rop_method == "average_fallback":
		return {
			"policy": POLICY_REVIEW,
			"reasons": [
				f"Only {demand_events} demand event(s) in {analysis_days} days, and not enough "
				"history for a full rolling-window calculation -- numbers are too sparse to trust"
			],
		}
	return {
		"policy": POLICY_SLOW_CRITICAL,
		"reasons": [f"Slow-moving demand ({demand_events} events in {analysis_days} days) -- treated as critical/low-volume stock"],
	}
