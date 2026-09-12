"""Historical stock movement extraction and classification into the demand
taxonomy (see classification.py). Read-only: queries Stock Ledger Entry and a
small batch of source-voucher headers, never writes anything.

Query design is deliberately two-stage and batched to avoid an N+1 pattern:
1. One query pulls all matching Stock Ledger Entry rows for the window.
2. One additional query per *distinct voucher_type present in that batch*
   (plus one for Stock Entry Detail warehouses) resolves the source-voucher
   flags needed for classification -- never one query per SLE row.
"""

import frappe
from frappe.utils import flt

from .classification import NET_SIGN, TRANSFER_EXTERNAL_CONSUMPTION, classify_movement
from .exceptions import DataException, ExceptionCode

# voucher_type -> fields to fetch from that voucher's parent doctype.
# Purchase Invoice / Sales Invoice only ever appear here with update_stock=1,
# since update_stock=0 never produces a Stock Ledger Entry in the first place.
_HEADER_FIELDS = {
	"Stock Entry": ["name", "is_return", "purpose", "work_order"],
	"Purchase Receipt": ["name", "is_return"],
	"Purchase Invoice": ["name", "is_return", "update_stock"],
	"Delivery Note": ["name", "is_return"],
	"Sales Invoice": ["name", "is_return", "update_stock"],
	"Stock Reconciliation": ["name"],
	"Subcontracting Order": ["name"],
	"Subcontracting Receipt": ["name"],
}


def normalize_uom_qty(item_code, qty, uom, conversion_factor, exceptions: list):
	"""Convert `qty` (expressed in `uom`) to Item.stock_uom. Flags
	MISSING_UOM_CONVERSION and returns the qty unconverted (never silently
	dropped) when a conversion factor is required but missing/zero."""
	stock_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
	if not uom or uom == stock_uom:
		return flt(qty), stock_uom
	if not conversion_factor:
		exceptions.append(
			DataException(
				ExceptionCode.MISSING_UOM_CONVERSION,
				f"Missing/zero conversion factor for {item_code} ({uom} -> {stock_uom})",
				item_code=item_code,
			)
		)
		return flt(qty), uom
	return flt(qty) * flt(conversion_factor), stock_uom


def _fetch_headers(voucher_type: str, voucher_names: list) -> dict:
	fields = _HEADER_FIELDS.get(voucher_type)
	if not fields or not voucher_names:
		return {name: {"header_found": False} for name in voucher_names}

	found = frappe.get_all(
		voucher_type,
		filters={"name": ["in", voucher_names]},
		fields=fields,
		limit_page_length=0,
	)
	headers = {}
	for row in found:
		header = dict(row)
		header["header_found"] = True
		headers[row["name"]] = header

	for name in voucher_names:
		headers.setdefault(name, {"header_found": False})
	return headers


def _fetch_stock_entry_detail_warehouses(detail_names: list) -> dict:
	if not detail_names:
		return {}
	rows = frappe.get_all(
		"Stock Entry Detail",
		filters={"name": ["in", detail_names]},
		fields=["name", "s_warehouse", "t_warehouse"],
		limit_page_length=0,
	)
	return {row["name"]: row for row in rows}


def _build_candidate(sle_row: dict, header: dict | None, detail: dict | None) -> dict:
	candidate = {
		"voucher_type": sle_row["voucher_type"],
		"warehouse": sle_row["warehouse"],
		"actual_qty": sle_row["actual_qty"],
		"header_found": bool(header and header.get("header_found")),
	}
	if header and header.get("header_found"):
		candidate["is_return"] = header.get("is_return")
		candidate["purpose"] = header.get("purpose")
		candidate["work_order"] = header.get("work_order")
	if detail:
		candidate["s_warehouse"] = detail.get("s_warehouse")
		candidate["t_warehouse"] = detail.get("t_warehouse")
	return candidate


def get_demand_history(
	item_code: str | None = None,
	warehouse: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	company: str | None = None,
) -> dict:
	"""Returns {"rows": [...schema below...], "exceptions": [DataException, ...]}.

	Row schema: posting_date, posting_time, item_code, warehouse, actual_qty,
	demand_qty, stock_uom, voucher_type, voucher_no, voucher_detail_no,
	purpose, classification, source_warehouse, target_warehouse, transfer_kind,
	is_return, is_cancelled, remarks.
	"""
	if not from_date or not to_date:
		frappe.throw("from_date and to_date are required")

	sle_filters = {
		"posting_date": ["between", [from_date, to_date]],
		"is_cancelled": 0,
	}
	if item_code:
		sle_filters["item_code"] = item_code
	if warehouse:
		sle_filters["warehouse"] = warehouse
	if company:
		sle_filters["company"] = company

	sle_rows = frappe.get_all(
		"Stock Ledger Entry",
		filters=sle_filters,
		fields=[
			"name",
			"item_code",
			"warehouse",
			"posting_date",
			"posting_time",
			"actual_qty",
			"qty_after_transaction",
			"stock_uom",
			"voucher_type",
			"voucher_no",
			"voucher_detail_no",
			"company",
		],
		order_by="posting_date asc, posting_time asc, creation asc",
		limit_page_length=0,
	)

	by_type: dict[str, set] = {}
	for r in sle_rows:
		by_type.setdefault(r["voucher_type"], set()).add(r["voucher_no"])

	header_cache = {}
	for vtype, vnames in by_type.items():
		for vname, header in _fetch_headers(vtype, list(vnames)).items():
			header_cache[(vtype, vname)] = header

	detail_names = [
		r["voucher_detail_no"] for r in sle_rows if r["voucher_type"] == "Stock Entry" and r["voucher_detail_no"]
	]
	detail_cache = _fetch_stock_entry_detail_warehouses(detail_names)

	seen_keys = set()
	rows = []
	exceptions: list[DataException] = []

	for r in sle_rows:
		key = (r["voucher_type"], r["voucher_no"], r["voucher_detail_no"], r["warehouse"], r["item_code"])
		if key in seen_keys:
			exceptions.append(
				DataException(
					ExceptionCode.DUPLICATE_SOURCE_ROW,
					"Duplicate (voucher_type, voucher_no, voucher_detail_no, warehouse, item_code) row",
					item_code=r["item_code"],
					warehouse=r["warehouse"],
					voucher_type=r["voucher_type"],
					voucher_no=r["voucher_no"],
					voucher_detail_no=r["voucher_detail_no"],
					posting_date=str(r["posting_date"]),
					context={"sle": r["name"]},
				)
			)
			continue
		seen_keys.add(key)

		if not r["warehouse"]:
			exceptions.append(
				DataException(
					ExceptionCode.MISSING_WAREHOUSE,
					"Stock Ledger Entry has no warehouse",
					item_code=r["item_code"],
					voucher_type=r["voucher_type"],
					voucher_no=r["voucher_no"],
					voucher_detail_no=r["voucher_detail_no"],
					context={"sle": r["name"]},
				)
			)
			continue
		if not r["item_code"]:
			exceptions.append(
				DataException(
					ExceptionCode.MISSING_ITEM,
					"Stock Ledger Entry has no item_code",
					warehouse=r["warehouse"],
					voucher_type=r["voucher_type"],
					voucher_no=r["voucher_no"],
					voucher_detail_no=r["voucher_detail_no"],
					context={"sle": r["name"]},
				)
			)
			continue

		header = header_cache.get((r["voucher_type"], r["voucher_no"]))
		detail = detail_cache.get(r["voucher_detail_no"]) if r["voucher_type"] == "Stock Entry" else None
		candidate = _build_candidate(r, header, detail)
		result = classify_movement(candidate)

		if result["needs_review"]:
			exceptions.append(
				DataException(
					result.get("review_code") or ExceptionCode.UNCLASSIFIED_MOVEMENT,
					result.get("review_reason") or "Unclassified movement",
					item_code=r["item_code"],
					warehouse=r["warehouse"],
					voucher_type=r["voucher_type"],
					voucher_no=r["voucher_no"],
					voucher_detail_no=r["voucher_detail_no"],
					posting_date=str(r["posting_date"]),
				)
			)

		item_stock_uom = frappe.get_cached_value("Item", r["item_code"], "stock_uom")
		if item_stock_uom and r["stock_uom"] and item_stock_uom != r["stock_uom"]:
			exceptions.append(
				DataException(
					ExceptionCode.MISSING_UOM_CONVERSION,
					f"SLE stock_uom {r['stock_uom']!r} differs from current Item.stock_uom {item_stock_uom!r}",
					item_code=r["item_code"],
					warehouse=r["warehouse"],
					voucher_type=r["voucher_type"],
					voucher_no=r["voucher_no"],
					voucher_detail_no=r["voucher_detail_no"],
				)
			)

		if r["qty_after_transaction"] is not None and flt(r["qty_after_transaction"]) < 0:
			exceptions.append(
				DataException(
					ExceptionCode.NEGATIVE_STOCK,
					f"Stock went negative ({r['qty_after_transaction']}) after this entry",
					item_code=r["item_code"],
					warehouse=r["warehouse"],
					voucher_type=r["voucher_type"],
					voucher_no=r["voucher_no"],
					voucher_detail_no=r["voucher_detail_no"],
					posting_date=str(r["posting_date"]),
					context={"qty_after_transaction": r["qty_after_transaction"]},
				)
			)

		rows.append(
			{
				"posting_date": r["posting_date"],
				"posting_time": r["posting_time"],
				"item_code": r["item_code"],
				"warehouse": r["warehouse"],
				"actual_qty": r["actual_qty"],
				"demand_qty": abs(flt(r["actual_qty"])),
				"stock_uom": r["stock_uom"],
				"voucher_type": r["voucher_type"],
				"voucher_no": r["voucher_no"],
				"voucher_detail_no": r["voucher_detail_no"],
				"purpose": candidate.get("purpose"),
				"classification": result["classification"],
				"source_warehouse": result["source_warehouse"],
				"target_warehouse": result["target_warehouse"],
				"transfer_kind": result["transfer_kind"],
				"is_return": result["is_return"],
				"is_cancelled": 0,
				"remarks": result.get("review_reason"),
			}
		)

	return {"rows": rows, "exceptions": exceptions}


def summarize_demand(rows: list, warehouse: str | None = None) -> dict:
	"""Aggregate a demand-history row list into headline figures, keeping the
	row list itself as the transaction-level audit trail (spec pt 27)."""
	summary = {
		"gross_consumption": 0.0,
		"net_demand": 0.0,
		"transfer_out": 0.0,
		"transfer_in": 0.0,
		"external_consumption": 0.0,
		"returns": 0.0,
	}
	for row in rows:
		cls = row["classification"]
		summary["net_demand"] += row["demand_qty"] * NET_SIGN.get(cls, 0)

		if cls == "CONSUMPTION":
			summary["gross_consumption"] += row["demand_qty"]
		elif cls == "RETURN":
			summary["returns"] += row["demand_qty"]
		elif cls == "TRANSFER":
			if row.get("transfer_kind") == TRANSFER_EXTERNAL_CONSUMPTION:
				summary["external_consumption"] += row["demand_qty"]
			elif warehouse and row.get("source_warehouse") == warehouse:
				summary["transfer_out"] += row["demand_qty"]
			elif warehouse and row.get("target_warehouse") == warehouse:
				summary["transfer_in"] += row["demand_qty"]
	return summary
