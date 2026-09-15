# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt
#
# Tests against the REAL warehouse tree on this site: "เอกไทย - ET" (a real
# is_group=1 parent, confirmed via direct DB query during Phase 2 design) and
# its two real children "บ้าน 88 - ET" / "บ้าน 147 - ET". These pin the
# actual tree shape as a regression test -- if it ever changes, this fails
# loudly rather than silently analyzing the wrong warehouses.

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from repair_management.repair_management.inventory.reorder import demand, group, service
from repair_management.repair_management.inventory.reorder.calculation import DEFAULT_OPTIONS

PLANNING_WAREHOUSE_GROUP = "เอกไทย - ET"
LEAF_WAREHOUSE_A = "บ้าน 88 - ET"
LEAF_WAREHOUSE_B = "บ้าน 147 - ET"


class TestResolvePlanningWarehouseGroup(FrappeTestCase):
	def test_real_group_resolves_to_its_two_real_children(self):
		result = group.resolve_planning_warehouse_group(PLANNING_WAREHOUSE_GROUP)
		self.assertEqual(set(result["leaf_warehouses"]), {LEAF_WAREHOUSE_A, LEAF_WAREHOUSE_B})

	def test_leaf_warehouse_resolves_to_itself(self):
		result = group.resolve_planning_warehouse_group(LEAF_WAREHOUSE_B)
		self.assertEqual(result["leaf_warehouses"], [LEAF_WAREHOUSE_B])


class TestGroupAggregationHelpers(FrappeTestCase):
	"""Pure-dict fixtures -- no DB writes needed for these, just run against
	FrappeTestCase for consistency/co-location with the rest of this file."""

	def test_aggregate_stock_sums_across_rows(self):
		rows = [
			{"actual_qty": 10, "reserved_qty": 2, "stock_value": 100},
			{"actual_qty": 5, "reserved_qty": 1, "stock_value": 50},
		]
		result = group.aggregate_stock(rows)
		self.assertEqual(result["actual_qty"], 15)
		self.assertEqual(result["reserved_qty"], 3)
		self.assertEqual(result["stock_value"], 150)

	def test_aggregate_incoming_sums_regardless_of_reliability(self):
		rows = [
			{"remaining_qty_stock_uom": 5, "reliability": "RELIABLE"},
			{"remaining_qty_stock_uom": 7, "reliability": "LATE"},
		]
		result = group.aggregate_incoming(rows)
		self.assertEqual(result["reliable_qty"], 5)
		self.assertEqual(result["late_qty"], 7)
		self.assertEqual(result["total_outstanding_qty"], 12)

	def test_aggregate_daily_demand_series_sums_element_wise(self):
		result = group.aggregate_daily_demand_series([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]])
		self.assertEqual(result, [11.0, 22.0, 33.0])

	def test_aggregate_daily_demand_series_empty_input(self):
		self.assertEqual(group.aggregate_daily_demand_series([]), [])


class TestGroupServiceIntegration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company")
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

	def _transfer(self, from_warehouse, to_warehouse, qty, item_code=None):
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Transfer"
		se.company = self.company
		se.append(
			"items",
			{
				"item_code": item_code or self.item_code,
				"qty": qty,
				"s_warehouse": from_warehouse,
				"t_warehouse": to_warehouse,
				"uom": self.stock_uom,
			},
		)
		se.insert(ignore_permissions=True)
		se.submit()
		return se

	def test_analyze_items_produces_one_row_per_item_per_group_not_per_leaf(self):
		self._seed_stock(LEAF_WAREHOUSE_A, 20, item_code=self.item_code)
		self._issue(LEAF_WAREHOUSE_A, 2, item_code=self.item_code)
		self._seed_stock(LEAF_WAREHOUSE_B, 20, item_code=self.item_code)
		self._issue(LEAF_WAREHOUSE_B, 2, item_code=self.item_code)

		filters = {
			"company": self.company,
			"planning_warehouse": PLANNING_WAREHOUSE_GROUP,
			"item_codes": [self.item_code],
			"status": None,
			"demand_type": None,
			"policy": None,
			"confidence": None,
		}
		rows = service.analyze_items(filters, self._options())
		matching = [r for r in rows if r["item_code"] == self.item_code]
		self.assertEqual(len(matching), 1)
		self.assertEqual(matching[0]["warehouse"], PLANNING_WAREHOUSE_GROUP)

	def test_group_on_hand_sums_both_leaves(self):
		baseline_a = (
			frappe.db.get_value("Bin", {"item_code": self.item_code, "warehouse": LEAF_WAREHOUSE_A}, "actual_qty")
			or 0
		)
		baseline_b = (
			frappe.db.get_value("Bin", {"item_code": self.item_code, "warehouse": LEAF_WAREHOUSE_B}, "actual_qty")
			or 0
		)
		self._seed_stock(LEAF_WAREHOUSE_A, 20, item_code=self.item_code)
		self._seed_stock(LEAF_WAREHOUSE_B, 30, item_code=self.item_code)

		result = service.analyze_item(self.item_code, PLANNING_WAREHOUSE_GROUP, self._options())
		self.assertEqual(result["actual_qty"], baseline_a + baseline_b + 50)

	def test_internal_transfer_between_leaves_does_not_change_group_demand(self):
		self._seed_stock(LEAF_WAREHOUSE_A, 20, item_code=self.item_code)
		before = service.analyze_item(self.item_code, PLANNING_WAREHOUSE_GROUP, self._options())

		self._transfer(LEAF_WAREHOUSE_A, LEAF_WAREHOUSE_B, 5, item_code=self.item_code)
		after = service.analyze_item(self.item_code, PLANNING_WAREHOUSE_GROUP, self._options())

		self.assertEqual(before["total_demand"], after["total_demand"])
		self.assertEqual(before["demand_events"], after["demand_events"])

	def test_analyze_items_calls_demand_history_once_per_leaf_not_per_item(self):
		self._seed_stock(LEAF_WAREHOUSE_A, 20, item_code=self.item_code)
		self._issue(LEAF_WAREHOUSE_A, 2, item_code=self.item_code)
		self._seed_stock(LEAF_WAREHOUSE_A, 20, item_code=self.item_code_2)
		self._issue(LEAF_WAREHOUSE_A, 2, item_code=self.item_code_2)

		filters = {
			"company": self.company,
			"planning_warehouse": PLANNING_WAREHOUSE_GROUP,
			"item_codes": [self.item_code, self.item_code_2],
			"status": None,
			"demand_type": None,
			"policy": None,
			"confidence": None,
		}
		with patch.object(demand, "get_demand_history", wraps=demand.get_demand_history) as spy:
			service.analyze_items(filters, self._options())
		# called once per LEAF warehouse in the group (2), never once per
		# (item, warehouse) pair (would be 4 for 2 items x 2 leaves).
		self.assertEqual(spy.call_count, 2)


if __name__ == "__main__":
	import unittest

	unittest.main()
