"""PO -> Purchase Receipt lead-time history extraction. Read-only.

Deliberately does no averaging/percentile/optimization -- that's Phase 1+
territory. Partial deliveries are kept as separate rows, never collapsed.
"""

import frappe
from frappe.utils import date_diff


def get_lead_time_history(
	item_code: str | None = None,
	supplier: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
) -> dict:
	"""Returns {"rows": [...], "exceptions": []}. One row per Purchase Receipt
	Item line with a resolvable Purchase Order link."""
	pri_filters = {"docstatus": 1}
	if item_code:
		pri_filters["item_code"] = item_code
	if from_date and to_date:
		pri_filters["parent"] = ["in", _receipts_in_range(from_date, to_date)]

	pri_rows = frappe.get_all(
		"Purchase Receipt Item",
		filters=pri_filters,
		fields=["parent as purchase_receipt", "item_code", "warehouse", "qty", "purchase_order", "schedule_date"],
		limit_page_length=0,
	)
	if not pri_rows:
		return {"rows": [], "exceptions": []}

	pr_names = list({r["purchase_receipt"] for r in pri_rows})
	pr_headers = {
		h["name"]: h
		for h in frappe.get_all(
			"Purchase Receipt",
			filters={"name": ["in", pr_names], "docstatus": 1},
			fields=["name", "posting_date", "supplier"],
			limit_page_length=0,
		)
	}

	po_names = list({r["purchase_order"] for r in pri_rows if r["purchase_order"]})
	po_headers = {
		h["name"]: h
		for h in frappe.get_all(
			"Purchase Order",
			filters={"name": ["in", po_names]},
			fields=["name", "transaction_date", "supplier"],
			limit_page_length=0,
		)
	}

	rows = []
	for r in pri_rows:
		pr = pr_headers.get(r["purchase_receipt"])
		po = po_headers.get(r["purchase_order"]) if r["purchase_order"] else None
		if not pr or not po:
			# no PO linkage -> can't compute lead time; excluded, not an error
			continue
		if supplier and po["supplier"] != supplier:
			continue

		rows.append(
			{
				"item_code": r["item_code"],
				"supplier": po["supplier"],
				"purchase_order": r["purchase_order"],
				"po_date": po["transaction_date"],
				"schedule_date": r["schedule_date"],
				"purchase_receipt": r["purchase_receipt"],
				"receipt_date": pr["posting_date"],
				"received_qty": r["qty"],
				"warehouse": r["warehouse"],
				"lead_time_days": date_diff(pr["posting_date"], po["transaction_date"]),
			}
		)

	return {"rows": rows, "exceptions": []}


def _receipts_in_range(from_date: str, to_date: str) -> list:
	return frappe.get_all(
		"Purchase Receipt",
		filters={"docstatus": 1, "posting_date": ["between", [from_date, to_date]]},
		pluck="name",
	)
