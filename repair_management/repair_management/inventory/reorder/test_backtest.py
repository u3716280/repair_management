# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from repair_management.repair_management.inventory.reorder import backtest as backtest_mod
from repair_management.repair_management.inventory.reorder.backtest import _checkpoint_dates, _simulate_day
from repair_management.repair_management.inventory.reorder.calculation import DEFAULT_OPTIONS


class TestCheckpointDates(unittest.TestCase):
	def test_first_checkpoint_is_start_date(self):
		start = getdate("2026-01-01")
		end = getdate("2026-01-20")
		dates = _checkpoint_dates(start, end, step_days=7)
		self.assertEqual(dates[0], start)

	def test_checkpoints_spaced_by_step_days(self):
		start = getdate("2026-01-01")
		end = getdate("2026-01-20")
		dates = _checkpoint_dates(start, end, step_days=7)
		self.assertEqual(dates, [start, add_days(start, 7), add_days(start, 14)])

	def test_never_exceeds_end_date(self):
		start = getdate("2026-01-01")
		end = getdate("2026-01-05")
		dates = _checkpoint_dates(start, end, step_days=7)
		self.assertEqual(dates, [start])


class TestSimulateDay(unittest.TestCase):
	"""Pure mechanics, no DB -- the day-by-day loop's core correctness
	properties: an order fires exactly when planning_position drops to or
	below rop, a prior open order suppresses re-triggering (the single most
	important property named in the spec), receipts land on their own
	expected_arrival_date, and stockouts clamp on_hand at 0."""

	def test_places_order_when_position_drops_to_or_below_rop(self):
		state = {"on_hand": 10.0, "reserved": 0.0, "open_orders": []}
		orders = []
		day = getdate("2026-01-01")
		trace_row = _simulate_day(
			state=state, day=day, actual_demand_qty=6.0, rop=5.0, target=20.0,
			planning_lead_time_days=10, review_period_days=1, orders_sink=orders,
		)
		self.assertEqual(trace_row["on_hand"], 4.0)
		self.assertEqual(trace_row["orders_placed_today"], 1)
		self.assertEqual(len(orders), 1)
		self.assertEqual(orders[0]["qty"], 16.0)  # target(20) - position(4)
		self.assertEqual(orders[0]["expected_arrival_date"], add_days(day, 11))

	def test_does_not_double_order_while_a_prior_order_is_still_open(self):
		state = {
			"on_hand": 4.0,
			"reserved": 0.0,
			"open_orders": [
				{"order_date": getdate("2026-01-01"), "expected_arrival_date": getdate("2026-01-15"), "qty": 16.0}
			],
		}
		orders = []
		day = getdate("2026-01-02")
		trace_row = _simulate_day(
			state=state, day=day, actual_demand_qty=1.0, rop=5.0, target=20.0,
			planning_lead_time_days=10, review_period_days=1, orders_sink=orders,
		)
		# outstanding_qty (16, from the still-open order) keeps planning
		# position well above rop -- no second order should fire.
		self.assertEqual(trace_row["orders_placed_today"], 0)
		self.assertEqual(len(orders), 0)
		self.assertEqual(trace_row["open_order_count"], 1)

	def test_receives_order_on_its_arrival_date(self):
		arrival = getdate("2026-01-10")
		state = {
			"on_hand": 2.0,
			"reserved": 0.0,
			"open_orders": [{"order_date": getdate("2026-01-01"), "expected_arrival_date": arrival, "qty": 20.0}],
		}
		orders = []
		trace_row = _simulate_day(
			state=state, day=arrival, actual_demand_qty=1.0, rop=5.0, target=20.0,
			planning_lead_time_days=10, review_period_days=1, orders_sink=orders,
		)
		self.assertEqual(trace_row["on_hand"], 21.0)  # 2 + 20 - 1
		self.assertEqual(trace_row["open_order_count"], 0)

	def test_stockout_clamps_on_hand_at_zero_and_records_shortfall(self):
		state = {"on_hand": 3.0, "reserved": 0.0, "open_orders": []}
		orders = []
		trace_row = _simulate_day(
			state=state, day=getdate("2026-01-01"), actual_demand_qty=10.0, rop=0.0, target=0.0,
			planning_lead_time_days=10, review_period_days=1, orders_sink=orders,
		)
		self.assertEqual(trace_row["on_hand"], 0.0)
		self.assertEqual(trace_row["stockout_qty"], 7.0)
		self.assertEqual(state["on_hand"], 0.0)

	def test_no_order_placed_when_position_above_rop(self):
		state = {"on_hand": 50.0, "reserved": 0.0, "open_orders": []}
		orders = []
		trace_row = _simulate_day(
			state=state, day=getdate("2026-01-01"), actual_demand_qty=1.0, rop=5.0, target=20.0,
			planning_lead_time_days=10, review_period_days=1, orders_sink=orders,
		)
		self.assertEqual(trace_row["orders_placed_today"], 0)
		self.assertEqual(len(orders), 0)


class TestRunBacktestIntegration(FrappeTestCase):
	"""End-to-end, real DB, real warehouse tree -- confirms the whole pipeline
	runs without error and, critically, never creates a real document."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company")
		warehouses = frappe.get_all(
			"Warehouse",
			filters={"company": cls.company, "is_group": 0, "disabled": 0},
			fields=["name"],
			limit_page_length=1,
		)
		cls.warehouse = warehouses[0].name
		item = frappe.get_all(
			"Item",
			filters={"is_stock_item": 1, "has_serial_no": 0, "has_batch_no": 0, "disabled": 0},
			fields=["name", "stock_uom"],
			limit_page_length=1,
		)[0]
		cls.item_code = item.name
		cls.stock_uom = item.stock_uom

	def _seed_stock(self, qty):
		receipt = frappe.new_doc("Stock Entry")
		receipt.stock_entry_type = "Material Receipt"
		receipt.company = self.company
		receipt.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": qty,
				"t_warehouse": self.warehouse,
				"uom": self.stock_uom,
				"allow_zero_valuation_rate": 1,
			},
		)
		receipt.insert(ignore_permissions=True)
		receipt.submit()

	def test_run_backtest_end_to_end_creates_no_real_documents(self):
		self._seed_stock(50)
		material_request_count_before = frappe.db.count("Material Request")
		purchase_order_count_before = frappe.db.count("Purchase Order")

		options = dict(DEFAULT_OPTIONS)
		options["company"] = self.company
		result = backtest_mod.run_backtest(
			item_code=self.item_code,
			planning_warehouse=self.warehouse,
			company=self.company,
			training_window_days=60,
			validation_window_days=14,
			step_days=7,
			backtest_end_date=nowdate(),
			options=options,
		)

		self.assertIn("trace", result)
		self.assertIn("metrics", result)
		self.assertIn("orders", result)
		self.assertEqual(len(result["trace"]), 15)  # 14-day window, inclusive of both ends

		self.assertEqual(frappe.db.count("Material Request"), material_request_count_before)
		self.assertEqual(frappe.db.count("Purchase Order"), purchase_order_count_before)


if __name__ == "__main__":
	unittest.main()
