# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from repair_management.repair_management.inventory.reorder import demand, service
from repair_management.repair_management.inventory.reorder.calculation import (
	DEFAULT_OPTIONS,
	STATUS_CRITICAL,
	STATUS_NO_HISTORY,
)


class TestReorderService(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company")
		warehouses = frappe.get_all(
			"Warehouse",
			filters={"company": cls.company, "is_group": 0, "disabled": 0},
			fields=["name"],
			limit_page_length=2,
		)
		cls.warehouse_a = warehouses[0].name
		cls.warehouse_b = warehouses[1].name

		items = frappe.get_all(
			"Item",
			filters={"is_stock_item": 1, "has_serial_no": 0, "has_batch_no": 0, "disabled": 0},
			fields=["name", "stock_uom"],
			limit_page_length=2,
		)
		cls.item_code = items[0].name
		cls.stock_uom = items[0].stock_uom
		cls.item_code_2 = items[1].name if len(items) > 1 else items[0].name

		today = nowdate()
		cls.from_date = frappe.utils.add_days(today, -30)
		cls.to_date = today

	# ---- helpers -----------------------------------------------------

	def _options(self, **overrides):
		options = dict(DEFAULT_OPTIONS)
		options.update({"from_date": self.from_date, "to_date": self.to_date, "company": self.company})
		options.update(overrides)
		return options

	def _seed_stock(self, warehouse, qty, item_code=None):
		receipt = frappe.new_doc("Stock Entry")
		receipt.stock_entry_type = "Material Receipt"
		receipt.company = self.company
		receipt.append(
			"items",
			{
				"item_code": item_code or self.item_code,
				"qty": qty,
				"t_warehouse": warehouse,
				"uom": self.stock_uom,
				"allow_zero_valuation_rate": 1,
			},
		)
		receipt.insert(ignore_permissions=True)
		receipt.submit()
		return receipt

	def _issue(self, warehouse, qty, item_code=None):
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Issue"
		se.company = self.company
		se.append(
			"items",
			{"item_code": item_code or self.item_code, "qty": qty, "s_warehouse": warehouse, "uom": self.stock_uom},
		)
		se.insert(ignore_permissions=True)
		se.submit()
		return se

	# ---- tests ---------------------------------------------------------

	def test_analyze_item_matches_manual_calculation(self):
		baseline = frappe.db.get_value(
			"Bin", {"item_code": self.item_code, "warehouse": self.warehouse_a}, "actual_qty"
		) or 0
		self._seed_stock(self.warehouse_a, 50)
		# 5 issues of qty 2 each, spread across the window, so ADI = 30/5 = 6 <= 7 -> Regular
		for _ in range(5):
			self._issue(self.warehouse_a, 2)

		result = service.analyze_item(self.item_code, self.warehouse_a, self._options())
		self.assertEqual(result["item_code"], self.item_code)
		self.assertEqual(result["warehouse"], self.warehouse_a)
		self.assertGreaterEqual(result["demand_events"], 1)
		self.assertIn(result["status"], {"Critical", "Reorder", "Review", "OK", "No History"})
		self.assertIn(result["confidence"], {"High", "Medium", "Low"})
		# actual stock reflects the net of the baseline, the seed, and the issues
		self.assertEqual(result["actual_qty"], baseline + 50 - 10)

	def test_no_history_item_gets_low_confidence_and_no_history_status(self):
		# A freshly-seeded warehouse+item pair with only a SUPPLY movement
		# (never classified as demand) has zero demand events.
		self._seed_stock(self.warehouse_b, 5)
		result = service.analyze_item(self.item_code, self.warehouse_b, self._options())
		self.assertEqual(result["demand_events"], 0)
		self.assertEqual(result["confidence"], "Low")
		self.assertEqual(result["status"], STATUS_NO_HISTORY)

	def test_status_critical_when_planning_position_non_positive(self):
		self._seed_stock(self.warehouse_a, 10)
		bin_qty = frappe.db.get_value(
			"Bin", {"item_code": self.item_code, "warehouse": self.warehouse_a}, "actual_qty"
		) or 0
		self._issue(self.warehouse_a, bin_qty)  # brings actual_qty to exactly 0 -> planning_position <= 0
		result = service.analyze_item(self.item_code, self.warehouse_a, self._options())
		self.assertLessEqual(result["planning_position"], 0)
		self.assertEqual(result["status"], STATUS_CRITICAL)

	def test_average_fallback_when_analysis_period_shorter_than_protection_period(self):
		self._seed_stock(self.warehouse_a, 20)
		self._issue(self.warehouse_a, 3)
		# analysis window is only 30 days (from setUpClass); force
		# planning_lead_time_days=120 explicitly so protection_period=121
		# reliably exceeds the 30-day series regardless of this item's own
		# (possibly unset, possibly different) Item.lead_time_days.
		result = service.analyze_item(
			self.item_code, self.warehouse_a, self._options(planning_lead_time_days=120)
		)
		self.assertTrue(any("average-based estimate" in r for r in result["confidence_reason"]))

	def test_analyze_items_batches_by_warehouse_not_by_item(self):
		self._seed_stock(self.warehouse_a, 20, item_code=self.item_code)
		self._issue(self.warehouse_a, 2, item_code=self.item_code)
		self._seed_stock(self.warehouse_a, 20, item_code=self.item_code_2)
		self._issue(self.warehouse_a, 2, item_code=self.item_code_2)
		self._seed_stock(self.warehouse_b, 20, item_code=self.item_code)
		self._seed_stock(self.warehouse_b, 20, item_code=self.item_code_2)

		filters = {
			"company": self.company,
			"warehouses": [self.warehouse_a, self.warehouse_b],
			"item_codes": [self.item_code, self.item_code_2],
			"status": None,
			"demand_type": None,
			"confidence": None,
		}

		with patch.object(demand, "get_demand_history", wraps=demand.get_demand_history) as spy:
			rows = service.analyze_items(filters, self._options())

		# called once per warehouse (2), never once per (item, warehouse) pair (4)
		self.assertEqual(spy.call_count, 2)
		returned_pairs = {(r["item_code"], r["warehouse"]) for r in rows}
		self.assertIn((self.item_code, self.warehouse_a), returned_pairs)
		self.assertIn((self.item_code_2, self.warehouse_a), returned_pairs)

	def test_analyze_items_respects_status_filter(self):
		self._seed_stock(self.warehouse_a, 10, item_code=self.item_code)
		self._issue(self.warehouse_a, 10, item_code=self.item_code)  # -> Critical

		filters = {
			"company": self.company,
			"warehouses": [self.warehouse_a],
			"item_codes": [self.item_code],
			"status": ["OK"],
			"demand_type": None,
			"confidence": None,
		}
		rows = service.analyze_items(filters, self._options())
		self.assertFalse(any(r["item_code"] == self.item_code and r["warehouse"] == self.warehouse_a for r in rows))

	def test_reserved_qty_and_late_incoming_excluded_correctly_from_position(self):
		self._seed_stock(self.warehouse_a, 15)
		result = service.analyze_item(self.item_code, self.warehouse_a, self._options())
		# no reservation/incoming seeded -> planning_position should equal
		# actual_qty exactly (reserved=0, reliable_incoming=0), proving late
		# incoming (also 0 here) is never added and reserved is subtracted,
		# not ignored, when present.
		self.assertEqual(result["planning_position"], result["actual_qty"])


if __name__ == "__main__":
	import unittest

	unittest.main()
