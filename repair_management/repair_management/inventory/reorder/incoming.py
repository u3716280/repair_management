"""Open Purchase Order Item extraction -- line-item level, not just an
aggregate ordered_qty. Read-only.

Excludes cancelled/closed POs and fully-received lines, nets out
Purchase Return qty, and classifies each remaining line RELIABLE/LATE by
schedule date. No overdue-day thresholds yet (deferred to a later phase).
"""

import frappe
from frappe.utils import flt, getdate, nowdate

from .demand import normalize_uom_qty
from .exceptions import DataException, ExceptionCode

RELIABLE = "RELIABLE"
LATE = "LATE"


def get_incoming(item_code: str | None = None, warehouse: str | None = None, today: str | None = None) -> dict:
	"""Returns {"rows": [...], "exceptions": [...]}. One row per open
	Purchase Order Item line (never aggregated across POs)."""
	today = today or nowdate()

	poi_filters = {"docstatus": 1}
	if item_code:
		poi_filters["item_code"] = item_code
	if warehouse:
		poi_filters["warehouse"] = warehouse

	poi_rows = frappe.get_all(
		"Purchase Order Item",
		filters=poi_filters,
		fields=[
			"parent as purchase_order",
			"item_code",
			"warehouse",
			"qty",
			"received_qty",
			"returned_qty",
			"stock_qty",
			"stock_uom",
			"uom",
			"conversion_factor",
			"schedule_date",
		],
		limit_page_length=0,
	)
	if not poi_rows:
		return {"rows": [], "exceptions": []}

	po_names = list({r["purchase_order"] for r in poi_rows})
	po_headers = {
		h["name"]: h
		for h in frappe.get_all(
			"Purchase Order",
			filters={"name": ["in", po_names], "docstatus": 1, "status": ["not in", ["Cancelled", "Closed"]]},
			fields=["name", "status", "transaction_date", "supplier", "company"],
			limit_page_length=0,
		)
	}

	rows = []
	exceptions: list[DataException] = []

	for r in poi_rows:
		header = po_headers.get(r["purchase_order"])
		if header is None:
			# PO itself cancelled/closed -> excluded (spec pt 9)
			continue

		net_qty = flt(r["qty"]) - flt(r["returned_qty"] or 0)
		remaining_qty = net_qty - flt(r["received_qty"] or 0)
		if remaining_qty <= 0:
			continue

		is_late = bool(r["schedule_date"]) and getdate(r["schedule_date"]) < getdate(today)
		reliability = LATE if is_late else RELIABLE
		if is_late:
			exceptions.append(
				DataException(
					ExceptionCode.LATE_PO,
					f"PO line overdue: schedule_date {r['schedule_date']} < {today}",
					item_code=r["item_code"],
					warehouse=r["warehouse"],
					voucher_type="Purchase Order",
					voucher_no=r["purchase_order"],
				)
			)

		remaining_qty_stock_uom, _ = normalize_uom_qty(
			r["item_code"], remaining_qty, r["uom"], r["conversion_factor"], exceptions
		)

		rows.append(
			{
				"purchase_order": r["purchase_order"],
				"item_code": r["item_code"],
				"warehouse": r["warehouse"],
				"supplier": header["supplier"],
				"po_date": header["transaction_date"],
				"schedule_date": r["schedule_date"],
				"qty": r["qty"],
				"returned_qty": r["returned_qty"],
				"received_qty": r["received_qty"],
				"remaining_qty": remaining_qty,
				"remaining_qty_stock_uom": remaining_qty_stock_uom,
				"uom": r["uom"],
				"stock_uom": r["stock_uom"],
				"conversion_factor": r["conversion_factor"],
				"reliability": reliability,
			}
		)

	return {"rows": rows, "exceptions": exceptions}
