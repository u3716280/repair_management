# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

import unittest

from repair_management.repair_management.inventory.reorder.metrics import (
	compute_inventory_metrics,
	compute_inventory_value,
	compute_lead_time_mismatch,
	compute_order_metrics,
	compute_stability,
	compute_stockout_metrics,
	detect_outliers,
)


def _day(demand_qty=0.0, stockout_qty=0.0, on_hand=0.0, target=0.0):
	return {"demand_qty": demand_qty, "stockout_qty": stockout_qty, "on_hand": on_hand, "target": target}


class TestStockoutMetrics(unittest.TestCase):
	def test_fill_rate_and_cycle_service_level(self):
		# 10 demand-event days, 2 of them short by a known qty.
		trace = [_day(demand_qty=10) for _ in range(8)] + [
			_day(demand_qty=10, stockout_qty=4),
			_day(demand_qty=10, stockout_qty=6),
		]
		result = compute_stockout_metrics(trace)
		self.assertEqual(result["stockout_days"], 2)
		self.assertEqual(result["stockout_qty"], 10)
		self.assertAlmostEqual(result["fill_rate"], 1 - (10 / 100))
		self.assertAlmostEqual(result["cycle_service_level"], 1 - (2 / 10))
		self.assertEqual(result["demand_events_fully_served"], 8)

	def test_multi_day_stockout_counts_once_per_day(self):
		trace = [_day(demand_qty=5, stockout_qty=5) for _ in range(3)]
		result = compute_stockout_metrics(trace)
		self.assertEqual(result["stockout_days"], 3)

	def test_no_demand_returns_none_rates(self):
		trace = [_day() for _ in range(5)]
		result = compute_stockout_metrics(trace)
		self.assertIsNone(result["fill_rate"])
		self.assertIsNone(result["cycle_service_level"])


class TestInventoryMetrics(unittest.TestCase):
	def test_average_max_min_and_excess_days(self):
		trace = [
			_day(on_hand=10, target=20),
			_day(on_hand=25, target=20),  # excess
			_day(on_hand=5, target=20),
		]
		result = compute_inventory_metrics(trace)
		self.assertAlmostEqual(result["average_inventory"], 40 / 3)
		self.assertEqual(result["max_inventory"], 25)
		self.assertEqual(result["min_inventory"], 5)
		self.assertEqual(result["excess_stock_days"], 1)

	def test_empty_trace(self):
		result = compute_inventory_metrics([])
		self.assertEqual(result["average_inventory"], 0.0)
		self.assertEqual(result["excess_stock_days"], 0)


class TestOrderMetrics(unittest.TestCase):
	def test_counts_and_averages(self):
		orders = [{"qty": 10}, {"qty": 20}, {"qty": 30}]
		result = compute_order_metrics(orders)
		self.assertEqual(result["number_of_orders"], 3)
		self.assertAlmostEqual(result["average_order_qty"], 20)
		self.assertEqual(result["max_order_qty"], 30)

	def test_no_orders(self):
		result = compute_order_metrics([])
		self.assertEqual(result["number_of_orders"], 0)
		self.assertIsNone(result["average_order_qty"])


class TestInventoryValue(unittest.TestCase):
	def test_value_is_average_on_hand_times_rate(self):
		trace = [_day(on_hand=10), _day(on_hand=20)]
		result = compute_inventory_value(trace, valuation_rate=2.0)
		self.assertAlmostEqual(result["average_inventory_value"], 15 * 2.0)


class TestStability(unittest.TestCase):
	def test_spec_stable_example(self):
		result = compute_stability([18, 19, 17, 18], [18, 19, 17, 18])
		self.assertTrue(result["rop_stable"])
		self.assertLess(result["rop_cv"], 0.25)

	def test_spec_unstable_example(self):
		result = compute_stability([8, 30, 12, 27], [8, 30, 12, 27])
		self.assertFalse(result["rop_stable"])
		self.assertGreater(result["rop_cv"], 0.25)

	def test_fewer_than_two_values_is_none(self):
		result = compute_stability([18], [])
		self.assertIsNone(result["rop_cv"])
		self.assertIsNone(result["target_cv"])
		self.assertFalse(result["rop_stable"])


class TestDetectOutliers(unittest.TestCase):
	def test_flags_obvious_outlier(self):
		values = [5, 6, 5, 7, 6, 100]
		flagged = detect_outliers(values)
		self.assertIn(5, flagged)

	def test_below_minimum_sample_returns_empty(self):
		self.assertEqual(detect_outliers([1, 2, 3]), [])

	def test_no_outliers_in_uniform_data(self):
		self.assertEqual(detect_outliers([5, 5, 5, 5, 5]), [])


class TestLeadTimeMismatch(unittest.TestCase):
	def test_flags_large_divergence(self):
		result = compute_lead_time_mismatch(configured_lead_time_days=120, actual_lead_time_p90=60)
		self.assertTrue(result["mismatch"])

	def test_no_flag_within_tolerance(self):
		result = compute_lead_time_mismatch(configured_lead_time_days=120, actual_lead_time_p90=110)
		self.assertFalse(result["mismatch"])

	def test_no_actual_data_never_flags(self):
		result = compute_lead_time_mismatch(configured_lead_time_days=120, actual_lead_time_p90=None)
		self.assertFalse(result["mismatch"])


if __name__ == "__main__":
	unittest.main()
