# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

import unittest

from repair_management.repair_management.inventory.reorder.calculation import (
	DEMAND_INTERMITTENT,
	DEMAND_NO_HISTORY,
	DEMAND_REGULAR,
)
from repair_management.repair_management.inventory.reorder.confidence import compute_confidence
from repair_management.repair_management.inventory.reorder.exceptions import DataException, ExceptionCode


def _base_kwargs(**overrides):
	kwargs = {
		"demand_type": DEMAND_REGULAR,
		"demand_events": 30,
		"analysis_days": 730,
		"target_horizon_days": 151,
		"rop_method": "percentile",
		"target_method": "percentile",
		"exceptions": [],
		"lead_time_sample_count": 5,
	}
	kwargs.update(overrides)
	return kwargs


class TestComputeConfidence(unittest.TestCase):
	def test_no_history_short_circuits_to_low(self):
		result = compute_confidence(**_base_kwargs(demand_type=DEMAND_NO_HISTORY, demand_events=0))
		self.assertEqual(result["level"], "Low")
		self.assertEqual(result["reasons"], ["No demand history in the analysis window"])

	def test_forced_low_on_unknown_voucher(self):
		exc = DataException(ExceptionCode.UNKNOWN_VOUCHER, "unknown")
		result = compute_confidence(**_base_kwargs(exceptions=[exc]))
		self.assertEqual(result["level"], "Low")
		self.assertTrue(any("unclassified/unknown" in r for r in result["reasons"]))

	def test_forced_low_on_unclassified_movement(self):
		exc = DataException(ExceptionCode.UNCLASSIFIED_MOVEMENT, "unclassified")
		result = compute_confidence(**_base_kwargs(exceptions=[exc]))
		self.assertEqual(result["level"], "Low")

	def test_slow_or_intermittent_caps_at_medium(self):
		result = compute_confidence(**_base_kwargs(demand_type=DEMAND_INTERMITTENT))
		self.assertEqual(result["level"], "Medium")
		self.assertTrue(any("Intermittent demand pattern" in r for r in result["reasons"]))

	def test_low_event_count_caps_at_medium(self):
		result = compute_confidence(**_base_kwargs(demand_events=3))
		self.assertEqual(result["level"], "Medium")
		self.assertTrue(any("Only 3 demand event" in r for r in result["reasons"]))

	def test_average_fallback_caps_at_low(self):
		result = compute_confidence(**_base_kwargs(rop_method="average_fallback"))
		self.assertEqual(result["level"], "Low")
		self.assertTrue(any("average-based estimate" in r for r in result["reasons"]))

	def test_thin_rolling_window_caps_at_medium(self):
		result = compute_confidence(**_base_kwargs(analysis_days=200, target_horizon_days=151))
		self.assertEqual(result["level"], "Medium")
		self.assertTrue(any("Limited rolling-window sample size" in r for r in result["reasons"]))

	def test_other_exception_downgrades_one_level(self):
		exc = DataException(ExceptionCode.NEGATIVE_STOCK, "negative stock")
		result = compute_confidence(**_base_kwargs(exceptions=[exc]))
		self.assertEqual(result["level"], "Medium")
		self.assertTrue(any("1 data exception(s)" in r for r in result["reasons"]))

	def test_zero_lead_time_samples_is_informational_only(self):
		result = compute_confidence(**_base_kwargs(lead_time_sample_count=0))
		self.assertEqual(result["level"], "High")
		self.assertTrue(any("No historical lead-time data" in r for r in result["reasons"]))

	def test_high_confidence_happy_path_reasons(self):
		result = compute_confidence(**_base_kwargs())
		self.assertEqual(result["level"], "High")
		self.assertEqual(result["reasons"], ["Sufficient history, no data exceptions"])


if __name__ == "__main__":
	unittest.main()
