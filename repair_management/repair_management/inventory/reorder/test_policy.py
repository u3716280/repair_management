# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

import unittest

from repair_management.repair_management.inventory.reorder.calculation import (
	DEMAND_INTERMITTENT,
	DEMAND_NO_HISTORY,
	DEMAND_REGULAR,
	DEMAND_SLOW,
	resolve_service_percentile,
)
from repair_management.repair_management.inventory.reorder.policy import (
	POLICY_INTERMITTENT,
	POLICY_NO_HISTORY,
	POLICY_ONE_TIME,
	POLICY_REVIEW,
	POLICY_SLOW_CRITICAL,
	POLICY_STOCKED,
	classify_replenishment_policy,
)


def _classify(**overrides):
	kwargs = {
		"demand_type": DEMAND_REGULAR,
		"demand_events": 10,
		"analysis_days": 70,
		"rop_method": "percentile",
	}
	kwargs.update(overrides)
	return classify_replenishment_policy(**kwargs)


class TestClassifyReplenishmentPolicy(unittest.TestCase):
	def test_no_history(self):
		result = _classify(demand_type=DEMAND_NO_HISTORY, demand_events=0)
		self.assertEqual(result["policy"], POLICY_NO_HISTORY)

	def test_exactly_one_event_is_one_time_not_review(self):
		result = _classify(demand_type=DEMAND_SLOW, demand_events=1)
		self.assertEqual(result["policy"], POLICY_ONE_TIME)

	def test_regular_is_stocked(self):
		result = _classify(demand_type=DEMAND_REGULAR, demand_events=10)
		self.assertEqual(result["policy"], POLICY_STOCKED)

	def test_intermittent(self):
		result = _classify(demand_type=DEMAND_INTERMITTENT, demand_events=8)
		self.assertEqual(result["policy"], POLICY_INTERMITTENT)

	def test_slow_with_percentile_method_is_slow_critical(self):
		result = _classify(demand_type=DEMAND_SLOW, demand_events=3, rop_method="percentile")
		self.assertEqual(result["policy"], POLICY_SLOW_CRITICAL)

	def test_slow_with_average_fallback_is_review(self):
		result = _classify(demand_type=DEMAND_SLOW, demand_events=3, rop_method="average_fallback")
		self.assertEqual(result["policy"], POLICY_REVIEW)

	def test_manual_override_wins_outright(self):
		result = _classify(demand_type=DEMAND_REGULAR, demand_events=10, manual_policy_override="BUY_TO_ORDER")
		self.assertEqual(result["policy"], "BUY_TO_ORDER")

	def test_manual_override_wins_even_over_no_history(self):
		result = _classify(demand_type=DEMAND_NO_HISTORY, demand_events=0, manual_policy_override="EXCLUDE")
		self.assertEqual(result["policy"], "EXCLUDE")

	def test_reasons_always_present(self):
		result = _classify()
		self.assertTrue(result["reasons"])


class TestResolveServicePercentileByPolicy(unittest.TestCase):
	def test_auto_slow_critical_is_p95(self):
		self.assertEqual(resolve_service_percentile("Auto", "SLOW_CRITICAL"), 95.0)

	def test_auto_stocked_is_p85(self):
		self.assertEqual(resolve_service_percentile("Auto", "STOCKED"), 85.0)

	def test_auto_intermittent_is_p85(self):
		self.assertEqual(resolve_service_percentile("Auto", "INTERMITTENT"), 85.0)

	def test_auto_unknown_policy_falls_back_to_default(self):
		self.assertEqual(resolve_service_percentile("Auto", "REVIEW"), 85.0)

	def test_explicit_p85_override_wins_regardless_of_policy(self):
		self.assertEqual(resolve_service_percentile("P85", "SLOW_CRITICAL"), 85.0)

	def test_explicit_p95_override_wins_regardless_of_policy(self):
		self.assertEqual(resolve_service_percentile("P95", "STOCKED"), 95.0)

	def test_explicit_p90_is_rejected(self):
		with self.assertRaises(Exception):
			resolve_service_percentile("P90", "STOCKED")

	def test_explicit_p80_is_rejected(self):
		with self.assertRaises(Exception):
			resolve_service_percentile("P80", "STOCKED")


if __name__ == "__main__":
	unittest.main()
