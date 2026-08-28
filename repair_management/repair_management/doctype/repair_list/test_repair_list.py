# Copyright (c) 2025, Chirayut D. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, nowdate

from repair_management.repair_management.doctype.repair_list.repair_list import receive_return


class TestRepairList(FrappeTestCase):
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
		cls.from_warehouse = warehouses[0].name
		cls.target_warehouse = warehouses[1].name

		item = frappe.get_all(
			"Item",
			filters={"is_stock_item": 1, "has_serial_no": 0, "has_batch_no": 0, "disabled": 0},
			fields=["name", "stock_uom"],
			limit_page_length=1,
		)[0]
		cls.item_code = item.name
		cls.stock_uom = item.stock_uom

		cls.supplier = frappe.get_all("Supplier", filters={"disabled": 0}, limit_page_length=1)[0].name
		cls.symptom = frappe.get_all("Repair Sympton", limit_page_length=1)[0].name

	def _bin_qty(self, warehouse):
		return frappe.db.get_value(
			"Bin", {"item_code": self.item_code, "warehouse": warehouse}, "actual_qty"
		) or 0

	def _make_repair_list(self, qty):
		# seed opening stock in from_warehouse so the outgoing transfer doesn't hit negative stock
		receipt = frappe.new_doc("Stock Entry")
		receipt.stock_entry_type = "Material Receipt"
		receipt.company = self.company
		receipt.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": qty,
				"t_warehouse": self.from_warehouse,
				"uom": self.stock_uom,
			},
		)
		receipt.insert(ignore_permissions=True)
		receipt.submit()

		rl = frappe.new_doc("Repair List")
		rl.supplier = self.supplier
		rl.company = self.company
		rl.from_warehouse = self.from_warehouse
		rl.target_warehouse = self.target_warehouse
		rl.posting_date = nowdate()
		rl.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": qty,
				"uom": self.stock_uom,
				"symptom": self.symptom,
			},
		)
		rl.insert(ignore_permissions=True)
		rl.submit()
		return rl

	def _latest_reversal_qty(self, since, from_warehouse, to_warehouse):
		"""Total qty carried by Material Transfer Stock Entries created after `since`
		moving stock from_warehouse -> to_warehouse (i.e. the cancel-reversal transfer)."""
		entries = frappe.get_all(
			"Stock Entry",
			filters={
				"stock_entry_type": "Material Transfer",
				"from_warehouse": from_warehouse,
				"to_warehouse": to_warehouse,
				"creation": [">=", since],
				"docstatus": 1,
			},
			pluck="name",
		)
		total = 0.0
		for se in entries:
			total += sum(
				frappe.get_all(
					"Stock Entry Detail",
					filters={"parent": se, "item_code": self.item_code},
					pluck="qty",
				)
			)
		return total

	def test_cancel_after_partial_return_reverses_only_outstanding_qty(self):
		target_before = self._bin_qty(self.target_warehouse)

		rl = self._make_repair_list(qty=10)
		self.assertEqual(rl.status, "In Repair")
		self.assertEqual(self._bin_qty(self.target_warehouse), target_before + 10)

		receive_return(
			docname=rl.name,
			selected_idx=[1],
			qty_map={"1": 6},
			use_global_status=1,
			global_status="Free",
		)
		rl.reload()
		self.assertEqual(rl.status, "Partial Returned")
		self.assertEqual(rl.items[0].returned_qty, 6)
		self.assertEqual(self._bin_qty(self.target_warehouse), target_before + 4)

		cancel_start = now_datetime()
		rl.cancel()
		rl.reload()

		self.assertEqual(rl.docstatus, 2)
		self.assertEqual(rl.status, "Cancelled")

		# the fix: only the outstanding 4 units (10 - 6 already returned) should be
		# reversed on cancel, not the original 10 -- otherwise this goes negative /
		# double-counts the 6 units already moved back by receive_return.
		reversed_qty = self._latest_reversal_qty(
			cancel_start, self.target_warehouse, self.from_warehouse
		)
		self.assertEqual(reversed_qty, 4)
		self.assertEqual(self._bin_qty(self.target_warehouse), target_before)

	def test_cancel_without_any_return_reverses_full_qty(self):
		target_before = self._bin_qty(self.target_warehouse)

		rl = self._make_repair_list(qty=5)
		self.assertEqual(self._bin_qty(self.target_warehouse), target_before + 5)

		cancel_start = now_datetime()
		rl.cancel()
		rl.reload()

		self.assertEqual(rl.status, "Cancelled")
		reversed_qty = self._latest_reversal_qty(
			cancel_start, self.target_warehouse, self.from_warehouse
		)
		self.assertEqual(reversed_qty, 5)
		self.assertEqual(self._bin_qty(self.target_warehouse), target_before)
