from __future__ import annotations

import hashlib
import uuid
from typing import Any

import frappe
from frappe.utils import now_datetime

from repair_management.integrations.line.client import push_messages
from repair_management.integrations.line.media import get_signed_file_url

STATUS_FORWARDING = "Forwarding"
STATUS_FORWARDED = "Forwarded"
STATUS_PARTIAL = "Partial Failure"
STATUS_FAILED = "Failed"


def enqueue_confirmation(confirmation_name: str) -> dict[str, Any]:
    settings = frappe.get_single("LINE Settings")
    if not settings.enabled:
        return {"queued": False, "reason": "LINE integration disabled"}
    if not settings.auto_forward:
        return {"queued": False, "reason": "Auto forward disabled"}

    confirmation_name = (confirmation_name or "").strip()
    if not confirmation_name:
        return {"queued": False, "reason": "Confirmation name is required"}

    queue = str(settings.background_queue or "short").strip() or "short"
    job_id = f"line-forward::{confirmation_name}"
    frappe.enqueue(
        "repair_management.integrations.line.forwarding.forward_confirmation",
        confirmation_name=confirmation_name,
        queue=queue,
        timeout=300,
        enqueue_after_commit=True,
        at_front=True,
        job_id=job_id,
        deduplicate=True,
    )
    return {"queued": True, "queue": queue, "job_id": job_id}


def forward_confirmation(confirmation_name: str) -> dict[str, Any]:
    confirmation = frappe.get_doc("LINE Delivery Confirmation", confirmation_name)
    routes = _matching_routes(confirmation)

    if not routes:
        frappe.db.set_value(
            "LINE Delivery Confirmation",
            confirmation.name,
            {"forward_status": "No Route", "last_forward_error": None},
            update_modified=True,
        )
        return {"ok": True, "routes": 0, "sent": 0, "failed": 0}

    frappe.db.set_value(
        "LINE Delivery Confirmation",
        confirmation.name,
        {"status": STATUS_FORWARDING, "forward_status": "Processing"},
        update_modified=True,
    )

    sent = 0
    failed = 0
    skipped = 0

    for route in routes:
        for target in sorted(route.targets, key=lambda row: (row.sequence or row.idx, row.idx)):
            if not target.enabled or not target.line_recipient:
                continue

            recipient = frappe.get_doc("LINE Recipient", target.line_recipient)
            if not recipient.enabled:
                skipped += 1
                continue

            log = _get_or_create_forward_log(confirmation, route, recipient)
            if log.status == "Sent":
                skipped += 1
                continue

            try:
                messages = _build_messages(confirmation, target)
                if not messages:
                    frappe.throw("Forward route target produced no LINE messages")

                frappe.db.set_value(
                    "LINE Forward Log",
                    log.name,
                    {
                        "status": "Processing",
                        "attempt_count": int(log.attempt_count or 0) + 1,
                        "last_attempt_at": now_datetime(),
                        "error_message": None,
                    },
                    update_modified=True,
                )

                status_code, response_text = push_messages(
                    recipient.recipient_id,
                    messages,
                    recipient.line_account,
                    retry_key=log.retry_key,
                )
                frappe.db.set_value(
                    "LINE Forward Log",
                    log.name,
                    {
                        "status": "Sent",
                        "sent_at": now_datetime(),
                        "response_code": status_code,
                        "response_body": response_text,
                        "error_message": None,
                    },
                    update_modified=True,
                )
                sent += 1
            except Exception as exc:
                frappe.db.set_value(
                    "LINE Forward Log",
                    log.name,
                    {
                        "status": "Failed",
                        "response_code": 0,
                        "error_message": str(exc)[:2000],
                    },
                    update_modified=True,
                )
                frappe.log_error(
                    title=f"LINE forward failed: {confirmation.name} -> {recipient.name}",
                    message=frappe.get_traceback(),
                )
                failed += 1

    if failed and sent:
        final_status = STATUS_PARTIAL
        forward_status = "Partial Failure"
    elif failed and not sent:
        final_status = STATUS_FAILED
        forward_status = "Failed"
    else:
        final_status = STATUS_FORWARDED
        forward_status = "Sent"

    frappe.db.set_value(
        "LINE Delivery Confirmation",
        confirmation.name,
        {
            "status": final_status,
            "forward_status": forward_status,
            "forwarded_at": now_datetime() if sent else None,
            "last_forward_error": f"{failed} destination(s) failed" if failed else None,
        },
        update_modified=True,
    )
    return {
        "ok": failed == 0,
        "routes": len(routes),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }


def _matching_routes(confirmation):
    if confirmation.forward_route:
        if not frappe.db.exists("LINE Forward Route", confirmation.forward_route):
            return []
        route = frappe.get_doc("LINE Forward Route", confirmation.forward_route)
        return [route] if route.enabled and _route_matches(route, confirmation, direct=True) else []

    names = frappe.get_all(
        "LINE Forward Route",
        filters={"enabled": 1},
        order_by="priority asc, modified asc",
        pluck="name",
    )
    routes = []
    for name in names:
        route = frappe.get_doc("LINE Forward Route", name)
        if _route_matches(route, confirmation, direct=False):
            routes.append(route)
    return routes


def _route_matches(route, confirmation, *, direct: bool) -> bool:
    confirmation_type = confirmation.confirmation_type or "Delivery"
    trigger_event = route.trigger_event or "Delivery Confirmation"

    if not direct:
        if confirmation_type == "Delivery":
            if trigger_event not in {"Delivery Confirmation", "Confirmation"}:
                return False
        elif trigger_event != "Confirmation":
            return False

    if route.source_line_account and route.source_line_account != confirmation.source_line_account:
        return False
    if route.confirmation_type and route.confirmation_type != confirmation_type:
        return False
    if route.postback_action and route.postback_action != confirmation.postback_action:
        return False
    if route.requested_status and route.requested_status != confirmation.requested_status:
        return False
    if route.reference_doctype and route.reference_doctype != confirmation.reference_doctype:
        return False
    return True


def _build_messages(confirmation, target) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    if target.send_text:
        lines = [_title_for_confirmation(confirmation)]
        if confirmation.requested_status:
            lines.append(f"สถานะ: {confirmation.requested_status}")
        if confirmation.reference_name:
            lines.append(f"เอกสาร: {confirmation.reference_name}")
            lines.extend(_reference_summary(confirmation))
        if confirmation.address:
            lines.append(f"สถานที่: {confirmation.address}")
        lines.append(f"เวลา: {confirmation.confirmed_at or confirmation.image_received_at}")
        if (
            target.include_location_link
            and confirmation.latitude not in (None, 0, 0.0)
            and confirmation.longitude not in (None, 0, 0.0)
        ):
            lines.append(
                f"แผนที่: https://www.google.com/maps?q={confirmation.latitude},{confirmation.longitude}"
            )
        messages.append({"type": "text", "text": "\n".join(lines)[:5000]})

    if target.send_image and confirmation.image_file_doc and confirmation.preview_file_doc:
        messages.append(
            {
                "type": "image",
                "originalContentUrl": get_signed_file_url(confirmation.image_file_doc),
                "previewImageUrl": get_signed_file_url(confirmation.preview_file_doc),
            }
        )

    return messages[:5]


def _title_for_confirmation(confirmation) -> str:
    confirmation_type = confirmation.confirmation_type or "Delivery"
    if confirmation.action_label:
        return f"✅ {confirmation.action_label}"
    return {
        "Delivery": "✅ ยืนยันการส่งสินค้าเรียบร้อยแล้ว",
        "Payment": "💳 ยืนยันการชำระเงิน",
        "Service": "🛠 ภาพถ่าย Service หน้างาน",
        "Installation": "🛠 ยืนยันงานติดตั้ง",
        "Other": "✅ ยืนยันรายการ",
    }.get(confirmation_type, "✅ ยืนยันรายการ")


def _reference_summary(confirmation) -> list[str]:
    if confirmation.reference_doctype != "Sales Order" or not confirmation.reference_name:
        return []
    if not frappe.db.exists("Sales Order", confirmation.reference_name):
        return []

    values = frappe.db.get_value(
        "Sales Order",
        confirmation.reference_name,
        ["customer", "customer_name", "transaction_date"],
        as_dict=True,
    )
    if not values:
        return []
    lines = []
    customer = values.customer_name or values.customer
    if customer:
        lines.append(f"ลูกค้า: {customer}")
    if values.transaction_date:
        lines.append(f"วันที่ Sales Order: {values.transaction_date}")
    return lines


def _get_or_create_forward_log(confirmation, route, recipient):
    raw_key = f"{confirmation.name}|{route.name}|{recipient.name}"
    log_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    existing = frappe.db.exists("LINE Forward Log", {"log_key": log_key})
    if existing:
        return frappe.get_doc("LINE Forward Log", existing)

    doc = frappe.get_doc(
        {
            "doctype": "LINE Forward Log",
            "log_key": log_key,
            "delivery_confirmation": confirmation.name,
            "forward_route": route.name,
            "line_recipient": recipient.name,
            "line_account": recipient.line_account,
            "recipient_type": recipient.recipient_type,
            "recipient_id": recipient.recipient_id,
            "status": "Pending",
            "attempt_count": 0,
            "retry_key": str(uuid.uuid4()),
        }
    )
    doc.insert(ignore_permissions=True)
    return doc
