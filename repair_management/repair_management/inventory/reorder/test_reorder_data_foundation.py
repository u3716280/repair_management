# Copyright (c) 2026, Chirayut D. and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, nowtime

from repair_management.repair_management.inventory.reorder import classification, demand, incoming, stock
from repair_management.repair_management.inventory.reorder.exceptions import ExceptionCode


class TestReorderDataFoundation(FrappeTestCase):
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

		item = frappe.get_all(
			"Item",
			filters={"is_stock_item": 1, "has_serial_no": 0, "has_batch_no": 0, "disabled": 0},
			fields=["name", "stock_uom"],
			limit_page_length=1,
		)[0]
		cls.item_code = item.name
		cls.stock_uom = item.stock_uom

		cls.supplier = frappe.get_all("Supplier", filters={"disabled": 0}, limit_page_length=1)[0].name

	# ---- helpers -----------------------------------------------------

	def _seed_stock(self, warehouse, qty):
		receipt = frappe.new_doc("Stock Entry")
		receipt.stock_entry_type = "Material Receipt"
		receipt.company = self.company
		receipt.append(
			"items", {"item_code": self.item_code, "qty": qty, "t_warehouse": warehouse, "uom": self.stock_uom}
		)
		receipt.insert(ignore_permissions=True)
		receipt.submit()
		return receipt

	def _issue(self, warehouse, qty):
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Issue"
		se.company = self.company
		se.append("items", {"item_code": self.item_code, "qty": qty, "s_warehouse": warehouse, "uom": self.stock_uom})
		se.insert(ignore_permissions=True)
		se.submit()
		return se

	def _transfer(self, from_warehouse, to_warehouse, qty):
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Transfer"
		se.company = self.company
		se.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": qty,
				"s_warehouse": from_warehouse,
				"t_warehouse": to_warehouse,
				"uom": self.stock_uom,
			},
		)
		se.insert(ignore_permissions=True)
		se.submit()
		return se

	def _make_po(self, warehouse, qty, uom=None, conversion_factor=None, item_code=None):
		po = frappe.new_doc("Purchase Order")
		po.company = self.company
		po.supplier = self.supplier
		po.transaction_date = nowdate()
		po.schedule_date = nowdate()
		po.append(
			"items",
			{
				"item_code": item_code or self.item_code,
				"qty": qty,
				"rate": 1,
				"uom": uom or self.stock_uom,
				"conversion_factor": conversion_factor or 1,
				"warehouse": warehouse,
				"schedule_date": nowdate(),
			},
		)
		po.insert(ignore_permissions=True)
		po.submit()
		return po

	def _receive_against_po(self, po, qty):
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

		pr = make_purchase_receipt(po.name)
		pr.items[0].qty = qty
		pr.insert(ignore_permissions=True)
		pr.submit()
		return pr

	def _demand(self, warehouse, item_code=None, from_date=None, to_date=None):
		today = nowdate()
		return demand.get_demand_history(
			item_code=item_code or self.item_code,
			warehouse=warehouse,
			from_date=from_date or today,
			to_date=to_date or today,
		)

	# ---- tests ---------------------------------------------------------

	def test_cancel_returns_net_demand_to_zero(self):
		self._seed_stock(self.warehouse_a, 50)
		issue = self._issue(self.warehouse_a, 5)

		result = self._demand(self.warehouse_a)
		summary = demand.summarize_demand(result["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary["gross_consumption"], 5)
		self.assertEqual(summary["net_demand"], 5)

		issue.cancel()

		result = self._demand(self.warehouse_a)
		summary = demand.summarize_demand(result["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary["gross_consumption"], 0)
		self.assertEqual(summary["net_demand"], 0)

	def test_amend_supersedes_original(self):
		self._seed_stock(self.warehouse_a, 50)
		original = self._issue(self.warehouse_a, 5)
		original.cancel()

		amended = frappe.copy_doc(original)
		amended.amended_from = original.name
		amended.docstatus = 0
		amended.items[0].qty = 8
		amended.insert(ignore_permissions=True)
		amended.submit()

		result = self._demand(self.warehouse_a)
		summary = demand.summarize_demand(result["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary["gross_consumption"], 8)

	def test_transfer_nets_zero_company_but_shows_in_both_warehouses(self):
		self._seed_stock(self.warehouse_a, 20)
		self._transfer(self.warehouse_a, self.warehouse_b, 10)

		result_a = self._demand(self.warehouse_a)
		summary_a = demand.summarize_demand(result_a["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary_a["transfer_out"], 10)
		self.assertEqual(summary_a["gross_consumption"], 0)

		result_b = self._demand(self.warehouse_b)
		summary_b = demand.summarize_demand(result_b["rows"], warehouse=self.warehouse_b)
		self.assertEqual(summary_b["transfer_in"], 10)
		self.assertEqual(summary_b["gross_consumption"], 0)

		for row in result_a["rows"] + result_b["rows"]:
			if row["voucher_type"] == "Stock Entry":
				self.assertEqual(row["classification"], "TRANSFER")

	def test_partial_po_receipt_remaining_qty(self):
		po = self._make_po(self.warehouse_a, qty=100)

		result = incoming.get_incoming(item_code=self.item_code, warehouse=self.warehouse_a)
		row = next(r for r in result["rows"] if r["purchase_order"] == po.name)
		self.assertEqual(row["remaining_qty"], 100)

		self._receive_against_po(po, 40)
		result = incoming.get_incoming(item_code=self.item_code, warehouse=self.warehouse_a)
		row = next(r for r in result["rows"] if r["purchase_order"] == po.name)
		self.assertEqual(row["received_qty"], 40)
		self.assertEqual(row["remaining_qty"], 60)

		self._receive_against_po(po, 60)
		result = incoming.get_incoming(item_code=self.item_code, warehouse=self.warehouse_a)
		self.assertFalse(any(r["purchase_order"] == po.name for r in result["rows"]))

	def test_uom_conversion_alternate_uom(self):
		conv = frappe.get_all(
			"UOM Conversion Detail",
			filters={"conversion_factor": ["!=", 1]},
			fields=["parent as item_code", "uom", "conversion_factor"],
			limit_page_length=1,
		)
		if not conv:
			self.skipTest("No item with an alternate (non-1) UOM conversion found on this site")
		row = conv[0]
		item = frappe.get_doc("Item", row.item_code)
		if item.disabled or not item.is_stock_item:
			self.skipTest("Found UOM-conversion item is not a usable stock item")

		po = self._make_po(
			self.warehouse_a,
			qty=5,
			uom=row.uom,
			conversion_factor=row.conversion_factor,
			item_code=row.item_code,
		)

		result = incoming.get_incoming(item_code=row.item_code, warehouse=self.warehouse_a)
		incoming_row = next(r for r in result["rows"] if r["purchase_order"] == po.name)
		self.assertEqual(incoming_row["remaining_qty_stock_uom"], 5 * row.conversion_factor)

	def test_negative_stock_raises_warning(self):
		allow_negative = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
		if not allow_negative:
			frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
			self.addCleanup(
				lambda: frappe.db.set_single_value("Stock Settings", "allow_negative_stock", allow_negative)
			)

		self._seed_stock(self.warehouse_a, 5)
		bin_qty = (
			frappe.db.get_value("Bin", {"item_code": self.item_code, "warehouse": self.warehouse_a}, "actual_qty")
			or 0
		)
		issue_qty = bin_qty + 5
		self._issue(self.warehouse_a, issue_qty)

		result = self._demand(self.warehouse_a)
		codes = {e.code for e in result["exceptions"]}
		self.assertIn(ExceptionCode.NEGATIVE_STOCK, codes)

		summary = demand.summarize_demand(result["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary["gross_consumption"], issue_qty)

	def test_stock_reconciliation_never_counted_as_demand(self):
		self._seed_stock(self.warehouse_a, 20)

		sr = frappe.new_doc("Stock Reconciliation")
		sr.company = self.company
		sr.purpose = "Stock Reconciliation"
		sr.set_posting_time = 1
		sr.posting_date = nowdate()
		sr.posting_time = nowtime()
		sr.expense_account = frappe.get_cached_value(
			"Company", self.company, "stock_adjustment_account"
		) or frappe.get_cached_value("Account", {"account_type": "Stock Adjustment", "company": self.company}, "name")
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center") or frappe.get_cached_value(
			"Cost Center", {"is_group": 0, "company": self.company}
		)
		sr.append(
			"items",
			{"item_code": self.item_code, "warehouse": self.warehouse_a, "qty": 15, "valuation_rate": 1},
		)
		sr.insert(ignore_permissions=True)
		sr.submit()

		result = self._demand(self.warehouse_a)
		sr_rows = [r for r in result["rows"] if r["voucher_type"] == "Stock Reconciliation"]
		self.assertTrue(sr_rows)
		for row in sr_rows:
			self.assertEqual(row["classification"], "ADJUSTMENT")

		summary = demand.summarize_demand(result["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary["net_demand"], 0)

	def test_duplicate_source_row_guard(self):
		self._seed_stock(self.warehouse_a, 20)
		self._issue(self.warehouse_a, 3)

		real_get_all = frappe.get_all

		def duplicating_get_all(doctype, *args, **kwargs):
			rows = real_get_all(doctype, *args, **kwargs)
			if doctype == "Stock Ledger Entry":
				return rows + rows
			return rows

		with patch(
			"repair_management.repair_management.inventory.reorder.demand.frappe.get_all",
			side_effect=duplicating_get_all,
		):
			result = self._demand(self.warehouse_a)

		codes = {e.code for e in result["exceptions"]}
		self.assertIn(ExceptionCode.DUPLICATE_SOURCE_ROW, codes)

		summary = demand.summarize_demand(result["rows"], warehouse=self.warehouse_a)
		self.assertEqual(summary["gross_consumption"], 3)

	def test_stock_snapshot_matches_bin(self):
		self._seed_stock(self.warehouse_a, 7)
		snapshot = stock.get_stock_snapshot(item_code=self.item_code, warehouse=self.warehouse_a)
		bin_qty = frappe.db.get_value(
			"Bin", {"item_code": self.item_code, "warehouse": self.warehouse_a}, "actual_qty"
		)
		self.assertEqual(snapshot[0]["actual_qty"], bin_qty)

	def test_unknown_voucher_type_goes_to_review(self):
		result = classification.classify_movement(
			{
				"voucher_type": "Some Nonexistent Voucher",
				"warehouse": self.warehouse_a,
				"actual_qty": -1,
				"header_found": False,
			}
		)
		self.assertEqual(result["classification"], "REVIEW")
		self.assertEqual(result["review_code"], ExceptionCode.UNKNOWN_VOUCHER)
