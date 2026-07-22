from __future__ import annotations

import json
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import flt


def _filters(serial_no=None, item_code=None, warehouse=None, purchase_receipt=None):
    cond = ["IFNULL(sn.purchase_rate, 0) = 0"]
    values = {}
    if serial_no:
        cond.append("sn.name LIKE %(serial_no)s")
        values["serial_no"] = f"%{serial_no}%"
    if item_code:
        cond.append("sn.item_code = %(item_code)s")
        values["item_code"] = item_code
    if warehouse:
        cond.append("sn.warehouse = %(warehouse)s")
        values["warehouse"] = warehouse
    if purchase_receipt:
        cond.append("sn.purchase_document_no = %(purchase_receipt)s")
        values["purchase_receipt"] = purchase_receipt
    return " AND ".join(cond), values


def _get_purchase_receipt_rate(serial: dict) -> tuple[float, str]:
    pr = serial.get("purchase_document_no")
    if not pr:
        return 0.0, ""

    rows = frappe.db.sql(
        """
        SELECT pri.valuation_rate, pri.item_code, pri.serial_and_batch_bundle
        FROM `tabPurchase Receipt Item` pri
        WHERE pri.parent = %s AND pri.item_code = %s
        ORDER BY pri.idx
        """,
        (pr, serial.get("item_code")),
        as_dict=True,
    )

    if not rows:
        return 0.0, ""

    # Prefer the row whose bundle actually contains this serial.
    for row in rows:
        bundle = row.get("serial_and_batch_bundle")
        if bundle and frappe.db.exists(
            "Serial and Batch Entry", {"parent": bundle, "serial_no": serial.get("name")}
        ):
            return flt(row.get("valuation_rate")), f"Purchase Receipt {pr}"

    if len(rows) == 1:
        return flt(rows[0].get("valuation_rate")), f"Purchase Receipt {pr}"

    return 0.0, ""


def _get_first_incoming_sle_rate(serial: dict) -> tuple[float, str]:
    rows = frappe.db.sql(
        """
        SELECT sle.voucher_type, sle.voucher_no, sle.incoming_rate, sle.valuation_rate,
               sle.stock_value_difference, sle.actual_qty
        FROM `tabStock Ledger Entry` sle
        INNER JOIN `tabSerial and Batch Entry` sbe
            ON sbe.parent = sle.serial_and_batch_bundle
        WHERE sbe.serial_no = %s
          AND sle.item_code = %s
          AND sle.is_cancelled = 0
          AND sle.actual_qty > 0
        ORDER BY sle.posting_date, sle.posting_time, sle.creation
        LIMIT 1
        """,
        (serial.get("name"), serial.get("item_code")),
        as_dict=True,
    )
    if not rows:
        return 0.0, ""
    row = rows[0]
    rate = flt(row.get("incoming_rate")) or flt(row.get("valuation_rate"))
    if not rate and flt(row.get("actual_qty")):
        rate = abs(flt(row.get("stock_value_difference")) / flt(row.get("actual_qty")))
    return rate, f"{row.get('voucher_type')} {row.get('voucher_no')}"


def _suggest(serial: dict) -> dict:
    rate, source = _get_purchase_receipt_rate(serial)
    if rate <= 0:
        rate, source = _get_first_incoming_sle_rate(serial)

    can_repair = rate > 0
    return {
        "serial_no": serial.get("name"),
        "item_code": serial.get("item_code"),
        "warehouse": serial.get("warehouse"),
        "current_rate": flt(serial.get("purchase_rate")),
        "suggested_rate": rate,
        "source": source or _("No reliable source found"),
        "status": _("Ready") if can_repair else _("Review required"),
        "can_repair": can_repair,
    }


@frappe.whitelist()
def preview(serial_no=None, item_code=None, warehouse=None, purchase_receipt=None):
    frappe.only_for(("System Manager", "Stock Manager"))
    where, values = _filters(serial_no, item_code, warehouse, purchase_receipt)
    serials = frappe.db.sql(
        f"""
        SELECT sn.name, sn.item_code, sn.warehouse, sn.purchase_rate,
               sn.purchase_document_no, sn.reference_doctype, sn.reference_name
        FROM `tabSerial No` sn
        WHERE {where}
        ORDER BY sn.modified DESC
        LIMIT 500
        """,
        values,
        as_dict=True,
    )
    return [_suggest(row) for row in serials]


@frappe.whitelist()
def repair(serial_nos):
    frappe.only_for(("System Manager", "Stock Manager"))
    if isinstance(serial_nos, str):
        serial_nos = json.loads(serial_nos)
    if not isinstance(serial_nos, list) or not serial_nos:
        frappe.throw(_("No Serial Nos selected."))

    updated = 0
    skipped = []
    for serial_no in serial_nos:
        serial = frappe.db.get_value(
            "Serial No",
            serial_no,
            ["name", "item_code", "warehouse", "purchase_rate", "purchase_document_no", "reference_doctype", "reference_name"],
            as_dict=True,
        )
        if not serial:
            skipped.append({"serial_no": serial_no, "reason": "Not found"})
            continue
        if flt(serial.purchase_rate) > 0:
            skipped.append({"serial_no": serial_no, "reason": "Rate already exists"})
            continue

        result = _suggest(serial)
        if not result["can_repair"]:
            skipped.append({"serial_no": serial_no, "reason": "No reliable source"})
            continue

        old_rate = flt(serial.purchase_rate)
        new_rate = flt(result["suggested_rate"])

        frappe.db.set_value("Serial No", serial_no, "purchase_rate", new_rate, update_modified=True)
        _write_log(serial_no, serial.item_code, old_rate, new_rate, result["source"])
        updated += 1

    frappe.db.commit()
    return {"updated": updated, "skipped": skipped}


def _write_log(serial_no, item_code, old_rate, new_rate, source):
    if not frappe.db.exists("DocType", "Serial Rate Repair Log"):
        return
    doc = frappe.get_doc({
        "doctype": "Serial Rate Repair Log",
        "serial_no": serial_no,
        "item_code": item_code,
        "old_purchase_rate": old_rate,
        "new_purchase_rate": new_rate,
        "source_reference": source,
        "repaired_by": frappe.session.user,
    })
    doc.insert(ignore_permissions=True)
