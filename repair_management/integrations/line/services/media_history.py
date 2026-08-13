from __future__ import annotations

import json
from collections import OrderedDict

import frappe


ACTIVE_SALES_ORDER_STATUSES_EXCLUDED = ("Completed", "Closed", "Cancelled")
SOURCE_ACTIONS = ("parts_confirm", "video_confirm")


def _context(row):
    try:
        return json.loads(row.context_json or "{}")
    except Exception:
        return {}


def _verified_final_file(session_row):
    ctx = _context(session_row)
    file_name = ctx.get("final_file")
    if not file_name or not frappe.db.exists("File", file_name):
        return None

    file_doc = frappe.get_doc("File", file_name)
    if file_doc.attached_to_doctype != "Sales Order":
        return None
    if file_doc.attached_to_name != session_row.target_document:
        return None
    return file_doc


def _completed_media_sessions(channel, user_id, limit=500):
    return frappe.get_all(
        "LINE Flow Session",
        filters={
            "line_channel": channel,
            "line_user_id": user_id,
            "status": "Completed",
            "target_doctype": "Sales Order",
            "action_key": ["in", list(SOURCE_ACTIONS)],
        },
        fields=[
            "name", "action_key", "target_document", "context_json",
            "expected_media_type", "creation", "modified",
        ],
        order_by="creation desc",
        limit_page_length=int(limit),
    )


def _eligible_sales_orders(names):
    if not names:
        return {}
    rows = frappe.get_all(
        "Sales Order",
        filters={
            "name": ["in", list(names)],
            "docstatus": 1,
            "status": ["not in", list(ACTIVE_SALES_ORDER_STATUSES_EXCLUDED)],
        },
        fields=["name", "customer_name", "transaction_date", "delivery_date", "status"],
        order_by="transaction_date desc, name desc",
        limit_page_length=0,
    )
    return {row.name: row for row in rows}


def list_sales_orders(channel, user_id, limit=100):
    sessions = _completed_media_sessions(channel, user_id)
    by_document = OrderedDict()
    for row in sessions:
        if row.target_document and row.target_document not in by_document:
            by_document[row.target_document] = []
        if row.target_document:
            by_document[row.target_document].append(row)

    eligible = _eligible_sales_orders(by_document.keys())
    result = []
    for name, rows in by_document.items():
        sales_order = eligible.get(name)
        if not sales_order:
            continue
        verified_count = sum(1 for row in rows if _verified_final_file(row))
        if not verified_count:
            continue
        sales_order.media_count = verified_count
        result.append(sales_order)
        if len(result) >= int(limit):
            break
    return result


def list_media(channel, user_id, sales_order):
    if not frappe.db.exists(
        "Sales Order",
        {
            "name": sales_order,
            "docstatus": 1,
            "status": ["not in", list(ACTIVE_SALES_ORDER_STATUSES_EXCLUDED)],
        },
    ):
        return []

    rows = frappe.get_all(
        "LINE Flow Session",
        filters={
            "line_channel": channel,
            "line_user_id": user_id,
            "status": "Completed",
            "target_doctype": "Sales Order",
            "target_document": sales_order,
            "action_key": ["in", list(SOURCE_ACTIONS)],
        },
        fields=[
            "name", "action_key", "target_document", "context_json",
            "expected_media_type", "creation", "modified",
        ],
        order_by="creation desc",
        limit_page_length=200,
    )

    result = []
    for row in rows:
        fdoc = _verified_final_file(row)
        if not fdoc:
            continue
        ctx = _context(row)
        media_type = (row.expected_media_type or "").strip() or (
            "Video" if row.action_key == "video_confirm" else "Image"
        )
        result.append(
            frappe._dict(
                session=row.name,
                sales_order=row.target_document,
                file_name=fdoc.name,
                file_url=fdoc.file_url,
                is_private=bool(fdoc.is_private),
                media_type=media_type,
                item_name=ctx.get("item_name") or "-",
                item_code=ctx.get("item_code") or "",
                selected_item_row=ctx.get("selected_item_row") or "",
                confirmed_at=row.modified or row.creation,
            )
        )
    return result


def get_verified_media(channel, user_id, source_session, sales_order=None):
    if not source_session or not frappe.db.exists("LINE Flow Session", source_session):
        return None
    row = frappe.get_doc("LINE Flow Session", source_session)
    if row.line_channel != channel or row.line_user_id != user_id:
        return None
    if row.status != "Completed" or row.target_doctype != "Sales Order":
        return None
    if row.action_key not in SOURCE_ACTIONS:
        return None
    if sales_order and row.target_document != sales_order:
        return None
    if not frappe.db.exists(
        "Sales Order",
        {
            "name": row.target_document,
            "docstatus": 1,
            "status": ["not in", list(ACTIVE_SALES_ORDER_STATUSES_EXCLUDED)],
        },
    ):
        return None
    fdoc = _verified_final_file(row)
    if not fdoc:
        return None
    ctx = _context(row)
    media_type = (row.expected_media_type or "").strip() or (
        "Video" if row.action_key == "video_confirm" else "Image"
    )
    return frappe._dict(
        session=row.name,
        sales_order=row.target_document,
        file_name=fdoc.name,
        file_url=fdoc.file_url,
        is_private=bool(fdoc.is_private),
        media_type=media_type,
        item_name=ctx.get("item_name") or "-",
        confirmed_at=row.modified or row.creation,
    )
