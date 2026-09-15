# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt
#
# Pure-math unit tests -- no database needed. Uses plain unittest since
# calculation.py has no frappe.db dependency (frappe.utils helpers used here
# are pure functions themselves).

import unittest

from repair_management.repair_management.inventory.reorder.calculation import (
	DEFAULT_OPTIONS,
	DEFAULT_PLANNING_LEAD_TIME_DAYS,
	DEMAND_INTERMITTENT,
	DEMAND_NO_HISTORY,
	DEMAND_REGULAR,
	DEMAND_SLOW,
	LEAD_TIME_SOURCE_ITEM_MASTER,
	LEAD_TIME_SOURCE_OVERRIDE,
	LEAD_TIME_SOURCE_SYSTEM_DEFAULT,
	STATUS_CRITICAL,
	STATUS_NO_HISTORY,
	STATUS_OK,
	STATUS_REORDER,
	STATUS_REVIEW,
	build_daily_demand_series,
	calculate_item_reorder,
	classify_demand_type,
	compute_planning_position,
	compute_protection_period,
	compute_recommended_qty,
	compute_rop,
	compute_status,
	compute_target_horizon,
	percentile,
	rolling_sum,
)


class TestProtectionPeriodAndHorizon(unittest.TestCase):
	def test_protection_period(self):
		self.assertEqual(compute_protection_period(120, 1), 121)

	def test_target_horizon(self):
		self.assertEqual(compute_target_horizon(120, 1, 30), 151)


class TestRollingSum(unittest.TestCase):
	def test_matches_naive_sum(self):
		series = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]
		window = 4
		expected = [sum(series[i : i + window]) for i in range(len(series) - window + 1)]
		self.assertEqual(rolling_sum(series, window), expected)

	def test_returns_empty_when_series_shorter_than_window(self):
		self.assertEqual(rolling_sum([1, 2, 3], 10), [])

	def test_returns_empty_when_window_non_positive(self):
		self.assertEqual(rolling_sum([1, 2, 3], 0), [])
		self.assertEqual(rolling_sum([1, 2, 3], -1), [])


class TestPercentile(unittest.TestCase):
	def test_known_values(self):
		self.assertEqual(percentile([1, 2, 3, 4], 50), 2.5)
		self.assertEqual(percentile([10], 90), 10)
		self.assertEqual(percentile([], 90), 0.0)

	def test_matches_numpy_when_available(self):
		try:
			import numpy as np
		except ImportError:
			self.skipTest("numpy not available in this environment")
		values = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]
		for pct in (50, 80, 90, 95):
			self.assertAlmostEqual(percentile(values, pct), float(np.percentile(values, pct)))


class TestBuildDailyDemandSeries(unittest.TestCase):
	def test_nets_consumption_and_return_same_day(self):
		rows = [
			{"posting_date": "2026-01-01", "classification": "CONSUMPTION", "demand_qty": 5},
			{"posting_date": "2026-01-01", "classification": "RETURN", "demand_qty": 2},
			{"posting_date": "2026-01-02", "classification": "TRANSFER", "demand_qty": 100},
			{"posting_date": "2026-01-02", "classification": "SUPPLY", "demand_qty": 100},
			{"posting_date": "2026-01-02", "classification": "ADJUSTMENT", "demand_qty": 100},
			{"posting_date": "2026-01-02", "classification": "IGNORE", "demand_qty": 100},
			{"posting_date": "2026-01-02", "classification": "REVIEW", "demand_qty": 100},
		]
		series = build_daily_demand_series(rows, "2026-01-01", "2026-01-03")
		self.assertEqual(series, [3.0, 0.0, 0.0])


class TestRopAverageFallback(unittest.TestCase):
	def test_falls_back_when_window_exceeds_series(self):
		series = [2.0] * 10  # only 10 days of history
		result = compute_rop(series, protection_period_days=121, service_percentile=90)
		self.assertEqual(result["method"], "average_fallback")
		self.assertEqual(result["value"], 2.0 * 121)
		self.assertEqual(result["rolling_values"], [])

	def test_uses_percentile_when_window_fits(self):
		series = [1.0, 2.0, 3.0, 4.0, 5.0]
		result = compute_rop(series, protection_period_days=3, service_percentile=90)
		self.assertEqual(result["method"], "percentile")
		self.assertTrue(result["rolling_values"])


class TestClassifyDemandType(unittest.TestCase):
	def test_no_history(self):
		self.assertEqual(classify_demand_type(0, 730), DEMAND_NO_HISTORY)

	def test_slow_when_too_few_events(self):
		self.assertEqual(classify_demand_type(4, 730), DEMAND_SLOW)

	def test_regular_at_boundary(self):
		# analysis_days / events == 7 -> Regular (<=7)
		self.assertEqual(classify_demand_type(10, 70), DEMAND_REGULAR)

	def test_intermittent_just_past_regular_boundary(self):
		# 80/10 = 8 -> Intermittent (>7, <=60)
		self.assertEqual(classify_demand_type(10, 80), DEMAND_INTERMITTENT)

	def test_intermittent_at_slow_boundary(self):
		# 600/10 = 60 -> Intermittent (<=60)
		self.assertEqual(classify_demand_type(10, 600), DEMAND_INTERMITTENT)

	def test_slow_just_past_intermittent_boundary(self):
		# 610/10 = 61 -> Slow (>60)
		self.assertEqual(classify_demand_type(10, 610), DEMAND_SLOW)


class TestComputeStatus(unittest.TestCase):
	def test_critical_when_position_non_positive(self):
		self.assertEqual(compute_status(0, 18, DEMAND_REGULAR, "High"), STATUS_CRITICAL)
		self.assertEqual(compute_status(-5, 18, DEMAND_REGULAR, "High"), STATUS_CRITICAL)

	def test_critical_wins_even_with_no_history(self):
		# Ambiguous-overlap case per the spec: planning_position<=0 AND No History
		# both apply -- Critical (the unconditional stockout fact) must win.
		self.assertEqual(compute_status(0, 0, DEMAND_NO_HISTORY, "Low"), STATUS_CRITICAL)

	def test_no_history_when_positive_position(self):
		self.assertEqual(compute_status(10, 0, DEMAND_NO_HISTORY, "Low"), STATUS_NO_HISTORY)

	def test_review_when_low_confidence(self):
		self.assertEqual(compute_status(10, 5, DEMAND_REGULAR, "Low"), STATUS_REVIEW)

	def test_reorder_when_at_or_below_rop(self):
		self.assertEqual(compute_status(10, 18, DEMAND_REGULAR, "High"), STATUS_REORDER)
		self.assertEqual(compute_status(18, 18, DEMAND_REGULAR, "High"), STATUS_REORDER)

	def test_ok_when_above_rop(self):
		self.assertEqual(compute_status(20, 18, DEMAND_REGULAR, "High"), STATUS_OK)


class TestPlanningPositionAndRecommendedQty(unittest.TestCase):
	def test_planning_position_formula(self):
		self.assertEqual(compute_planning_position(actual_qty=11, total_outstanding_qty=2, reserved_qty=3), 10)

	def test_recommended_qty_when_at_or_below_rop(self):
		self.assertEqual(compute_recommended_qty(planning_position=10, rop=18, target_stock=24), 14)

	def test_recommended_qty_zero_when_above_rop(self):
		self.assertEqual(compute_recommended_qty(planning_position=20, rop=18, target_stock=24), 0)

	def test_recommended_qty_never_negative(self):
		# planning_position <= rop but already above target -> clipped at 0, not negative
		self.assertEqual(compute_recommended_qty(planning_position=5, rop=18, target_stock=3), 0)


def _minimal_reorder_call(configured_lead_time_days, options_overrides=None):
	options = dict(DEFAULT_OPTIONS)
	options.update(options_overrides or {})
	return calculate_item_reorder(
		item_code="TEST-ITEM",
		warehouse="TEST-WAREHOUSE",
		item_name="Test Item",
		stock_uom="Nos",
		configured_lead_time_days=configured_lead_time_days,
		demand_rows=[],
		demand_exceptions=[],
		stock_row={"actual_qty": 10, "reserved_qty": 0},
		incoming_rows=[],
		incoming_exceptions=[],
		lead_time_rows=[],
		from_date="2026-01-01",
		to_date="2026-01-10",
		options=options,
	)


class TestLateIncomingCountsFully(unittest.TestCase):
	"""Phase 2's confirmed reversal of Phase 1's Planning Position formula:
	late/overdue incoming now counts the same as on-time incoming, via
	total_outstanding_qty = reliable_incoming + late_incoming. reliable_
	incoming/late_incoming are still both computed and returned separately
	(for Purchase Follow-up display), but the calculation no longer excludes
	the late portion."""

	def _call_with_incoming(self, incoming_rows):
		options = dict(DEFAULT_OPTIONS)
		return calculate_item_reorder(
			item_code="TEST-ITEM",
			warehouse="TEST-WAREHOUSE",
			item_name="Test Item",
			stock_uom="Nos",
			configured_lead_time_days=30,
			demand_rows=[],
			demand_exceptions=[],
			stock_row={"actual_qty": 5, "reserved_qty": 0},
			incoming_rows=incoming_rows,
			incoming_exceptions=[],
			lead_time_rows=[],
			from_date="2026-01-01",
			to_date="2026-01-10",
			options=options,
		)

	def test_all_reliable_incoming_counted(self):
		result = self._call_with_incoming([{"remaining_qty_stock_uom": 10, "reliability": "RELIABLE"}])
		self.assertEqual(result["reliable_incoming"], 10)
		self.assertEqual(result["late_incoming"], 0)
		self.assertEqual(result["total_outstanding_qty"], 10)
		self.assertEqual(result["planning_position"], 15)

	def test_all_late_incoming_still_counted_fully(self):
		# The whole point of the reversal: a fully-overdue PO must count
		# exactly the same as an on-time one.
		result = self._call_with_incoming([{"remaining_qty_stock_uom": 10, "reliability": "LATE"}])
		self.assertEqual(result["reliable_incoming"], 0)
		self.assertEqual(result["late_incoming"], 10)
		self.assertEqual(result["total_outstanding_qty"], 10)
		self.assertEqual(result["planning_position"], 15)

	def test_mixed_reliability_sums_to_the_same_position(self):
		reliable_only = self._call_with_incoming([{"remaining_qty_stock_uom": 10, "reliability": "RELIABLE"}])
		late_only = self._call_with_incoming([{"remaining_qty_stock_uom": 10, "reliability": "LATE"}])
		mixed = self._call_with_incoming(
			[
				{"remaining_qty_stock_uom": 4, "reliability": "RELIABLE"},
				{"remaining_qty_stock_uom": 6, "reliability": "LATE"},
			]
		)
		self.assertEqual(reliable_only["planning_position"], late_only["planning_position"])
		self.assertEqual(mixed["planning_position"], reliable_only["planning_position"])


class TestPlanningLeadTimeResolution(unittest.TestCase):
	"""planning_lead_time priority: explicit override > Item's own
	configured lead time (Item.lead_time_days) > system default (120)."""

	def test_explicit_override_wins_even_when_item_has_its_own_lead_time(self):
		result = _minimal_reorder_call(configured_lead_time_days=30, options_overrides={"planning_lead_time_days": 45})
		self.assertEqual(result["planning_lead_time"], 45)
		self.assertEqual(result["lead_time_source"], LEAD_TIME_SOURCE_OVERRIDE)

	def test_falls_back_to_item_configured_lead_time_when_no_override(self):
		result = _minimal_reorder_call(configured_lead_time_days=30)
		self.assertEqual(result["planning_lead_time"], 30)
		self.assertEqual(result["lead_time_source"], LEAD_TIME_SOURCE_ITEM_MASTER)

	def test_falls_back_to_system_default_when_item_has_no_lead_time_either(self):
		result = _minimal_reorder_call(configured_lead_time_days=0)
		self.assertEqual(result["planning_lead_time"], DEFAULT_PLANNING_LEAD_TIME_DAYS)
		self.assertEqual(result["lead_time_source"], LEAD_TIME_SOURCE_SYSTEM_DEFAULT)

	def test_configured_lead_time_of_none_also_falls_back_to_system_default(self):
		result = _minimal_reorder_call(configured_lead_time_days=None)
		self.assertEqual(result["planning_lead_time"], DEFAULT_PLANNING_LEAD_TIME_DAYS)
		self.assertEqual(result["lead_time_source"], LEAD_TIME_SOURCE_SYSTEM_DEFAULT)


class TestWorkedExample(unittest.TestCase):
	"""A hand-verified scenario with the same qualitative shape as the spec's
	Definition-of-Done example (Reorder status, recommended = target -
	position). The spec's own worked example gave only final output numbers
	(ROP=18, Position=10, Target=24, Recommended=14), not the underlying
	input series, so this is a from-scratch equivalent, not a literal
	reproduction -- see PHASE1_NOTES.md."""

	def test_periodic_series_produces_stable_rolling_windows(self):
		# A repeating 7-day pattern: every 7-day window sums to the same
		# total (14), by construction, since shifting by one day just moves
		# one value from front to back with the same multiset.
		pattern = [2, 2, 2, 2, 2, 2, 2]  # sums to 14 over any 7 consecutive days
		series = pattern * 20  # 140 days of history

		protection_period = 7
		rop_result = compute_rop(series, protection_period, service_percentile=90)
		self.assertEqual(rop_result["method"], "percentile")
		self.assertEqual(rop_result["value"], 14.0)

		target_horizon = 14
		target_result = compute_rop(series, target_horizon, service_percentile=90)
		self.assertEqual(target_result["value"], 28.0)

		planning_position = compute_planning_position(actual_qty=20, total_outstanding_qty=2, reserved_qty=8)
		self.assertEqual(planning_position, 14.0)

		status = compute_status(planning_position, rop_result["value"], DEMAND_REGULAR, "High")
		self.assertEqual(status, STATUS_REORDER)

		recommended = compute_recommended_qty(planning_position, rop_result["value"], target_result["value"])
		self.assertEqual(recommended, 14.0)


if __name__ == "__main__":
	unittest.main()
