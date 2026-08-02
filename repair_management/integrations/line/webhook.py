from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from repair_management.integrations.line.client import (
    reply_location_request,
    reply_text,
)
from repair_management.integrations.line.security import verify_line_signature

STATUS_RECEIVED = "Received"
STATUS_PROCESSED = "Processed"
STATUS_IGNORED = "Ignored"
STATUS_FAILED = "Failed"

STATE_IDLE = "IDLE"
STATE_AWAITING_LOCATION = "AWAITING_LOCATION"


@frappe.whitelist(allow_guest=True, methods=["POST"])
def callback():
    """Receive LINE Messaging API webhook callbacks."""
    request = frappe.local.request
    raw_body = request.get_data(cache=True, as_text=False) or b""
    signature = request.headers.get("X-Line-Signature", "")

    try:
        settings = frappe.get_single("LINE Settings")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "LINE Webhook: settings unavailable")
        return _json_response({"ok": False, "error": "LINE Settings unavailable"}, 503)

    if not settings.enabled:
        return _json_response({"ok": False, "error": "LINE integration disabled"}, 503)

    channel_secret = settings.get_password("channel_secret")
    if not verify_line_signature(raw_body, signature, channel_secret):
        return _json_response({"ok": False, "error": "Invalid LINE signature"}, 401)

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_response({"ok": False, "error": "Invalid JSON payload"}, 400)

    events = payload.get("events") or []
    if not events:
        return _json_response({"ok": True, "events": 0}, 200)

    processed = 0
    for event in events:
        event_id = _get_event_id(event)
        log = _get_or_create_log(event_id, event, settings)

        if log.status in (STATUS_PROCESSED, STATUS_IGNORED):
            continue

        try:
            result_status = _process_event(event, settings)
            _set_values(
                "LINE Webhook Log",
                log.name,
                {
                    "status": result_status,
                    "processed_at": now_datetime(),
                    "error_message": None,
                },
                update_modified=False,
            )
            if result_status == STATUS_PROCESSED:
                processed += 1
        except Exception as exc:
            _set_values(
                "LINE Webhook Log",
                log.name,
                {
                    "status": STATUS_FAILED,
                    "processed_at": now_datetime(),
                    "error_message": str(exc)[:2000],
                },
                update_modified=False,
            )
            frappe.log_error(
                title=f"LINE Webhook failed: {event_id}",
                message=frappe.get_traceback(),
            )
            return _json_response({"ok": False, "error": "Event processing failed"}, 500)

    return _json_response({"ok": True, "events": len(events), "processed": processed}, 200)


def _process_event(event: dict[str, Any], settings) -> str:
    event_type = event.get("type")
    source = event.get("source") or {}
    user_id = source.get("userId")
    reply_token = event.get("replyToken")

    if event_type == "postback":
        return _handle_postback(event, user_id, reply_token, settings)

    if event_type == "message":
        message = event.get("message") or {}
        if message.get("type") == "location":
            return _handle_location(event, user_id, reply_token, settings)

    return STATUS_IGNORED


def _handle_postback(event: dict[str, Any], user_id: str | None, reply_token: str | None, settings) -> str:
    if not user_id:
        frappe.throw("LINE userId is required for delivery confirmation")

    data = ((event.get("postback") or {}).get("data") or "").strip()
    params = parse_qs(data, keep_blank_values=True)
    action = (params.get("action") or [""])[0]
    expected_action = settings.delivery_postback_action or "delivery_complete_request"

    if action != expected_action:
        return STATUS_IGNORED

    reference_doctype = (params.get("doctype") or [None])[0]
    reference_name = (params.get("name") or [None])[0]
    expiry_minutes = max(int(settings.session_expiry_minutes or 15), 1)
    expires_at = add_to_date(now_datetime(), minutes=expiry_minutes, as_datetime=True)

    session = _get_or_create_session(user_id)
    _set_values(
        "LINE User Session",
        session.name,
        {
            "state": STATE_AWAITING_LOCATION,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "expires_at": expires_at,
            "last_event_id": _get_event_id(event),
            "latitude": 0.0,
            "longitude": 0.0,
            "address": "",
            "confirmed_at": None,
        },
        update_modified=True,
    )

    reply_location_request(reply_token, reference_name=reference_name, settings=settings)
    return STATUS_PROCESSED


def _handle_location(event: dict[str, Any], user_id: str | None, reply_token: str | None, settings) -> str:
    if not user_id:
        frappe.throw("LINE userId is required for location confirmation")

    session = frappe.db.exists("LINE User Session", user_id)
    if not session:
        reply_text(
            reply_token,
            "ไม่พบคำขอยืนยันการส่งสินค้า กรุณากดเมนู “ส่งของเรียบร้อย” ก่อนส่งตำแหน่ง",
            settings=settings,
        )
        return STATUS_PROCESSED

    session_doc = frappe.get_doc("LINE User Session", user_id)
    if session_doc.state != STATE_AWAITING_LOCATION:
        reply_text(
            reply_token,
            "ยังไม่มีรายการที่รอรับตำแหน่ง กรุณากดเมนู “ส่งของเรียบร้อย” ก่อน",
            settings=settings,
        )
        return STATUS_PROCESSED

    if session_doc.expires_at and get_datetime(session_doc.expires_at) < now_datetime():
        _set_values(
            "LINE User Session",
            session_doc.name,
            {"state": STATE_IDLE, "expires_at": None},
            update_modified=True,
        )
        reply_text(
            reply_token,
            "คำขอยืนยันหมดเวลาแล้ว กรุณากดเมนู “ส่งของเรียบร้อย” ใหม่อีกครั้ง",
            settings=settings,
        )
        return STATUS_PROCESSED

    message = event.get("message") or {}
    latitude = message.get("latitude")
    longitude = message.get("longitude")
    address = message.get("address") or message.get("title")
    confirmed_at = now_datetime()

    _set_values(
        "LINE User Session",
        session_doc.name,
        {
            "state": STATE_IDLE,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "confirmed_at": confirmed_at,
            "expires_at": None,
            "last_event_id": _get_event_id(event),
        },
        update_modified=True,
    )

    reference_text = f" {session_doc.reference_name}" if session_doc.reference_name else ""
    map_url = ""
    if latitude is not None and longitude is not None:
        map_url = f"\nแผนที่: https://www.google.com/maps?q={latitude},{longitude}"

    reply_text(
        reply_token,
        f"ยืนยันการส่งสินค้า{reference_text}เรียบร้อยแล้ว{map_url}",
        settings=settings,
    )
    return STATUS_PROCESSED


def _get_or_create_session(user_id: str):
    if frappe.db.exists("LINE User Session", user_id):
        return frappe.get_doc("LINE User Session", user_id)

    doc = frappe.get_doc(
        {
            "doctype": "LINE User Session",
            "line_user_id": user_id,
            "state": STATE_IDLE,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def _get_or_create_log(event_id: str, event: dict[str, Any], settings):
    if frappe.db.exists("LINE Webhook Log", event_id):
        return frappe.get_doc("LINE Webhook Log", event_id)

    source = event.get("source") or {}
    message = event.get("message") or {}
    postback = event.get("postback") or {}

    payload = None
    if settings.log_payload:
        payload = json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True)

    doc = frappe.get_doc(
        {
            "doctype": "LINE Webhook Log",
            "webhook_event_id": event_id,
            "event_type": event.get("type"),
            "message_type": message.get("type"),
            "source_type": source.get("type"),
            "source_id": source.get("userId") or source.get("groupId") or source.get("roomId"),
            "user_id": source.get("userId"),
            "group_id": source.get("groupId"),
            "room_id": source.get("roomId"),
            "postback_data": postback.get("data"),
            "status": STATUS_RECEIVED,
            "payload": payload,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def _set_values(doctype: str, name: str, values: dict[str, Any], update_modified: bool = True) -> None:
    frappe.db.set_value(
        doctype,
        name,
        values,
        update_modified=update_modified,
    )


def _get_event_id(event: dict[str, Any]) -> str:
    event_id = event.get("webhookEventId")
    if event_id:
        return str(event_id)

    normalized = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"generated-{digest[:48]}"


def _json_response(payload: dict[str, Any], status_code: int):
    frappe.local.response["http_status_code"] = status_code
    return payload

