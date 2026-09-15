# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from repair_management.repair_management.inventory.reorder import baseline


class TestPureBaselineFormulas(unittest.TestCase):
	def test_avg_demand_lead_time_baseline(self):
		self.assertEqual(baseline.compute_avg_demand_lead_time_baseline(avg_daily_demand=2, lead_time_days=30), 60)

	def test_min_max_baseline(self):
		result = baseline.compute_min_max_baseline(avg_daily_demand=2, lead_time_days=30)
		self.assertEqual(result["min"], 60)
		self.assertEqual(result["max"], 120)


class TestNativeErpnextReorderConfig(FrappeTestCase):
	def test_real_configured_item_reorder_row_is_found(self):
		# Confirmed real on this site during Phase 2 design: BUSH-2012-D24 at
		# บ้าน 147 - ET, level 10.0 / qty 10.0. Pinned against real
		# production data, not a synthetic fixture -- if this Item's master
		# data ever changes, update this test to point at whichever Item
		# Reorder row still exists rather than deleting the coverage.
		rows = frappe.get_all(
			"Item Reorder", filters={"parent": "BUSH-2012-D24"}, fields=["warehouse"], limit_page_length=1
		)
		if not rows:
			self.skipTest("BUSH-2012-D24's Item Reorder row no longer exists on this site")
		warehouse = rows[0].warehouse
		result = baseline.get_native_erpnext_reorder_config("BUSH-2012-D24", [warehouse])
		self.assertIsNotNone(result)
		self.assertEqual(result["warehouse"], warehouse)
		self.assertFalse(result["multiple_rows_found"])

	def test_returns_none_when_no_row_configured(self):
		item = frappe.get_all("Item", filters={"is_stock_item": 1, "disabled": 0}, fields=["name"], limit_page_length=1)[
			0
		].name
		result = baseline.get_native_erpnext_reorder_config(item, ["__no_such_warehouse__"])
		self.assertIsNone(result)


class TestSimulateNativeErpnextBaseline(unittest.TestCase):
	def test_orders_when_projected_qty_drops_to_reorder_level(self):
		result = baseline.simulate_native_erpnext_baseline(
			actual_daily_series=[6.0, 0.0, 0.0],
			start_on_hand=10.0,
			reserved_qty=0.0,
			reorder_level=5.0,
			reorder_qty=20.0,
			lead_time_days=5,
			review_period_days=1,
		)
		self.assertEqual(result["trace"][0]["on_hand"], 4.0)
		self.assertEqual(result["trace"][0]["orders_placed_today"], 1)
		self.assertEqual(len(result["orders"]), 1)
		self.assertEqual(result["orders"][0]["qty"], 20.0)  # max(reorder_qty, level - projected) = max(20, 1)


class TestManualRequestHistory(FrappeTestCase):
	def test_reference_only_history_never_raises_on_no_data(self):
		result = baseline.get_manual_request_history(
			"__no_such_item__", ["__no_such_warehouse__"], "2020-01-01", "2020-12-31"
		)
		self.assertEqual(result, [])


if __name__ == "__main__":
	unittest.main()
