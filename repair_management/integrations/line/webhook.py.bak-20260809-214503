from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime
from frappe.utils.file_manager import save_file

from repair_management.integrations.line.client import (
    download_message_content,
    download_message_preview,
    reply_image_request,
    reply_location_request,
    reply_pending_media_classification,
    reply_reference_request,
    reply_text,
)
from repair_management.integrations.line.forwarding import enqueue_confirmation
from repair_management.integrations.line.security import verify_line_signature

STATUS_RECEIVED = "Received"
STATUS_PROCESSED = "Processed"
STATUS_IGNORED = "Ignored"
STATUS_FAILED = "Failed"

STATE_IDLE = "IDLE"
STATE_AWAITING_REFERENCE = "AWAITING_REFERENCE"
STATE_AWAITING_LOCATION = "AWAITING_LOCATION"
STATE_AWAITING_IMAGE = "AWAITING_IMAGE"
STATE_PROCESSING = "PROCESSING"
STATE_COMPLETED = "COMPLETED"

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PREVIEW_BYTES = 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def callback(account: str | None = None):
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

    line_account = _resolve_line_account(account, raw_body, signature)
    if not line_account:
        return _json_response({"ok": False, "error": "Invalid LINE signature or account"}, 401)

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_response({"ok": False, "error": "Invalid JSON payload"}, 400)

    destination = payload.get("destination")
    if line_account.bot_user_id and destination and line_account.bot_user_id != destination:
        return _json_response({"ok": False, "error": "LINE destination mismatch"}, 401)

    events = payload.get("events") or []
    if not events:
        return _json_response({"ok": True, "events": 0, "account": line_account.name}, 200)

    processed = 0
    for event in events:
        event_id = _get_event_id(event)
        log = _get_or_create_log(event_id, event, line_account, destination)

        if log.status in (STATUS_PROCESSED, STATUS_IGNORED):
            continue

        try:
            result_status = _process_event(event, line_account)
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
                title=f"LINE Webhook failed: {line_account.name} / {event_id}",
                message=frappe.get_traceback(),
            )
            return _json_response({"ok": False, "error": "Event processing failed"}, 500)

    return _json_response(
        {"ok": True, "events": len(events), "processed": processed, "account": line_account.name},
        200,
    )


def _resolve_line_account(account_key: str | None, raw_body: bytes, signature: str):
    if account_key:
        name = frappe.db.get_value(
            "LINE Account",
            {"webhook_key": account_key, "enabled": 1},
            "name",
        )
        if not name:
            return None
        candidate = frappe.get_doc("LINE Account", name)
        secret = candidate.get_password("channel_secret")
        return candidate if verify_line_signature(raw_body, signature, secret) else None

    for name in frappe.get_all("LINE Account", filters={"enabled": 1}, pluck="name"):
        candidate = frappe.get_doc("LINE Account", name)
        secret = candidate.get_password("channel_secret")
        if verify_line_signature(raw_body, signature, secret):
            return candidate
    return None


def _process_event(event: dict[str, Any], line_account) -> str:
    event_type = event.get("type")
    source = event.get("source") or {}
    user_id = source.get("userId")
    reply_token = event.get("replyToken")

    if event_type == "postback":
        return _handle_postback(event, user_id, reply_token, line_account)

    if event_type == "message":
        message_type = (event.get("message") or {}).get("type")
        if message_type == "location":
            return _handle_location(event, user_id, reply_token, line_account)
        if message_type == "image":
            return _handle_image(event, user_id, reply_token, line_account)
        if message_type == "text":
            return _handle_text(event, user_id, reply_token, line_account)

    return STATUS_IGNORED


def _handle_postback(event, user_id, reply_token, line_account) -> str:
    if not user_id:
        frappe.throw("LINE userId is required for postback workflow")

    data = ((event.get("postback") or {}).get("data") or "").strip()
    params = parse_qs(data, keep_blank_values=True)
    action = _param(params, "action")

    if action == "classify_media":
        return _handle_classify_media(event, user_id, reply_token, line_account, params)
    if action == "discard_media":
        return _handle_discard_media(event, user_id, reply_token, line_account, params)

    action_config = _get_action_config(line_account, action)
    if not action_config:
        return STATUS_IGNORED

    source_type, source_id = _source_context(event, user_id)
    reference_doctype = _param(params, "doctype") or action_config.reference_doctype
    reference_name = _param(params, "name")
    requested_status = _param(params, "status") or action_config.requested_status

    session = _get_or_create_session(line_account.name, user_id, source_type, source_id)
    _cancel_incomplete_confirmation(session.current_confirmation)
    _initialize_session(
        session,
        line_account,
        action_config,
        source_type=source_type,
        source_id=source_id,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        requested_status=requested_status,
        pending_media=None,
        event_id=_get_event_id(event),
    )

    session = frappe.get_doc("LINE User Session", session.name)
    if reference_name:
        resolved = _resolve_reference_name(action_config, reference_doctype, reference_name)
        _set_values(
            "LINE User Session",
            session.name,
            {"reference_doctype": reference_doctype, "reference_name": resolved},
        )
        session = frappe.get_doc("LINE User Session", session.name)

    if cint(action_config.require_reference) and not session.reference_name:
        _set_values("LINE User Session", session.name, {"state": STATE_AWAITING_REFERENCE})
        reply_reference_request(
            reply_token,
            session.reference_doctype or "Sales Order",
            line_account,
            prompt=action_config.reference_prompt,
        )
        return STATUS_PROCESSED

    return _advance_session(event, reply_token, line_account, session, action_config)


def _handle_classify_media(event, user_id, reply_token, line_account, params) -> str:
    media_name = _param(params, "media")
    target_action = _param(params, "target_action")
    if not media_name or not target_action:
        frappe.throw("Pending media and target action are required")

    pending = _get_owned_pending_media(media_name, line_account.name, user_id, event)
    if pending.status != "Pending Classification":
        reply_text(reply_token, "รูปนี้ถูกจัดการแล้วหรือไม่สามารถใช้งานได้", line_account)
        return STATUS_PROCESSED
    if _pending_media_expired(pending):
        _expire_pending_media(pending)
        reply_text(reply_token, "รูปนี้หมดเวลาแล้ว กรุณาส่งรูปใหม่", line_account)
        return STATUS_PROCESSED

    action_config = _get_action_config(line_account, target_action)
    if not action_config:
        reply_text(reply_token, "ไม่พบประเภทงานที่เลือก กรุณาเริ่มรายการใหม่", line_account)
        return STATUS_PROCESSED

    source_type, source_id = _source_context(event, user_id)
    reference_doctype = _param(params, "doctype") or action_config.reference_doctype
    reference_name = _param(params, "name")
    requested_status = _param(params, "status") or action_config.requested_status

    session = _get_or_create_session(line_account.name, user_id, source_type, source_id)
    _cancel_incomplete_confirmation(session.current_confirmation)
    _initialize_session(
        session,
        line_account,
        action_config,
        source_type=source_type,
        source_id=source_id,
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        requested_status=requested_status,
        pending_media=pending.name,
        event_id=_get_event_id(event),
    )
    _set_values(
        "LINE Pending Media",
        pending.name,
        {"selected_action": target_action},
    )

    session = frappe.get_doc("LINE User Session", session.name)
    if reference_name:
        resolved = _resolve_reference_name(action_config, reference_doctype, reference_name)
        _set_values("LINE User Session", session.name, {"reference_name": resolved})
        session = frappe.get_doc("LINE User Session", session.name)

    if cint(action_config.require_reference) and not session.reference_name:
        _set_values("LINE User Session", session.name, {"state": STATE_AWAITING_REFERENCE})
        reply_reference_request(
            reply_token,
            session.reference_doctype or "Sales Order",
            line_account,
            prompt=action_config.reference_prompt,
        )
        return STATUS_PROCESSED

    return _advance_session(event, reply_token, line_account, session, action_config)


def _handle_discard_media(event, user_id, reply_token, line_account, params) -> str:
    media_name = _param(params, "media")
    if not media_name:
        frappe.throw("Pending media is required")
    pending = _get_owned_pending_media(media_name, line_account.name, user_id, event)
    if pending.status == "Pending Classification":
        _set_values(
            "LINE Pending Media",
            pending.name,
            {"status": "Discarded", "selected_action": "discard_media"},
        )
    reply_text(reply_token, "ยกเลิกรูปนี้แล้ว", line_account)
    return STATUS_PROCESSED


def _handle_text(event, user_id, reply_token, line_account) -> str:
    if not user_id:
        return STATUS_IGNORED

    source_type, source_id = _source_context(event, user_id)
    session = _find_session(line_account.name, user_id, source_type, source_id)
    if not session or session.state != STATE_AWAITING_REFERENCE:
        return STATUS_IGNORED

    if _session_expired(session):
        _expire_session(session)
        reply_text(reply_token, "คำขอหมดเวลาแล้ว กรุณาเริ่มรายการใหม่", line_account)
        return STATUS_PROCESSED

    action_config = _get_action_config(line_account, session.postback_action)
    if not action_config:
        _expire_session(session)
        reply_text(reply_token, "ไม่พบการตั้งค่า Workflow กรุณาเริ่มรายการใหม่", line_account)
        return STATUS_PROCESSED

    raw_reference = ((event.get("message") or {}).get("text") or "").strip()
    try:
        reference_name = _resolve_reference_name(
            action_config,
            session.reference_doctype or action_config.reference_doctype,
            raw_reference,
        )
    except Exception:
        reply_reference_request(
            reply_token,
            session.reference_doctype or "Sales Order",
            line_account,
            prompt=(
                f"ไม่พบ {session.reference_doctype or 'Sales Order'}: {raw_reference}\n"
                "กรุณาตรวจสอบเลขที่เอกสารแล้วส่งใหม่"
            ),
        )
        return STATUS_PROCESSED

    _set_values(
        "LINE User Session",
        session.name,
        {
            "reference_name": reference_name,
            "last_event_id": _get_event_id(event),
        },
    )
    session = frappe.get_doc("LINE User Session", session.name)
    return _advance_session(event, reply_token, line_account, session, action_config)


def _handle_location(event, user_id, reply_token, line_account) -> str:
    if not user_id:
        frappe.throw("LINE userId is required for location confirmation")

    source_type, source_id = _source_context(event, user_id)
    session = _find_session(line_account.name, user_id, source_type, source_id)
    if not session:
        reply_text(reply_token, "ไม่พบรายการที่รอตำแหน่ง กรุณาเริ่มรายการจากเมนูก่อน", line_account)
        return STATUS_PROCESSED

    if session.state != STATE_AWAITING_LOCATION:
        reply_text(reply_token, "รายการนี้ไม่ได้รอรับตำแหน่ง กรุณาเริ่มรายการใหม่", line_account)
        return STATUS_PROCESSED

    if _session_expired(session):
        _expire_session(session)
        reply_text(reply_token, "คำขอหมดเวลาแล้ว กรุณาเริ่มรายการใหม่", line_account)
        return STATUS_PROCESSED

    action_config = _get_action_config(line_account, session.postback_action)
    if not action_config:
        frappe.throw("LINE postback action configuration is missing")

    message = event.get("message") or {}
    latitude = message.get("latitude")
    longitude = message.get("longitude")
    if latitude is None or longitude is None:
        frappe.throw("LINE location event does not contain latitude and longitude")

    received_at = now_datetime()
    address = message.get("address") or message.get("title") or ""
    _set_values(
        "LINE User Session",
        session.name,
        {
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "location_received_at": received_at,
            "last_event_id": _get_event_id(event),
        },
    )
    session = frappe.get_doc("LINE User Session", session.name)
    confirmation = _ensure_confirmation(session, line_account, status="Awaiting Image")

    if session.pending_media:
        pending = frappe.get_doc("LINE Pending Media", session.pending_media)
        _complete_confirmation_from_pending(session, confirmation, pending)
        _reply_completed(reply_token, line_account, session)
        return STATUS_PROCESSED

    if cint(action_config.require_image):
        _set_values(
            "LINE User Session",
            session.name,
            {
                "state": STATE_AWAITING_IMAGE,
                "current_confirmation": confirmation.name,
                "expires_at": _session_expiry(line_account, action_config),
            },
        )
        reply_image_request(
            reply_token,
            session.reference_name,
            line_account,
            action_label=session.action_label or action_config.action_label,
            location_received=True,
        )
        return STATUS_PROCESSED

    _complete_confirmation_without_image(session, confirmation)
    _reply_completed(reply_token, line_account, session)
    return STATUS_PROCESSED


def _handle_image(event, user_id, reply_token, line_account) -> str:
    if not user_id:
        frappe.throw("LINE userId is required for image workflow")

    source_type, source_id = _source_context(event, user_id)
    session = _find_session(line_account.name, user_id, source_type, source_id)

    if session and _session_expired(session):
        _expire_session(session)
        session = None

    if not session or session.state not in {
        STATE_AWAITING_REFERENCE,
        STATE_AWAITING_LOCATION,
        STATE_AWAITING_IMAGE,
    }:
        pending = _save_pending_media(event, line_account, user_id, source_type, source_id)
        reply_pending_media_classification(
            reply_token,
            pending.name,
            _classification_actions(line_account),
            line_account,
        )
        return STATUS_PROCESSED

    if session.state in {STATE_AWAITING_REFERENCE, STATE_AWAITING_LOCATION}:
        pending = _save_pending_media(event, line_account, user_id, source_type, source_id)
        _set_values(
            "LINE User Session",
            session.name,
            {"pending_media": pending.name, "last_event_id": _get_event_id(event)},
        )
        if session.state == STATE_AWAITING_REFERENCE:
            reply_reference_request(
                reply_token,
                session.reference_doctype or "Sales Order",
                line_account,
                prompt="เก็บรูปไว้แล้ว กรุณาส่งเลขที่ Sales Order ที่เกี่ยวข้อง",
            )
        else:
            reply_location_request(
                reply_token,
                session.reference_name,
                line_account,
                action_label=session.action_label or "ภาพถ่าย Service หน้างาน",
            )
        return STATUS_PROCESSED

    if not session.current_confirmation or not frappe.db.exists(
        "LINE Delivery Confirmation", session.current_confirmation
    ):
        confirmation = _ensure_confirmation(session, line_account, status="Awaiting Image")
    else:
        confirmation = frappe.get_doc("LINE Delivery Confirmation", session.current_confirmation)

    file_data = _download_and_save_image(
        event,
        line_account,
        attached_to_doctype="LINE Delivery Confirmation",
        attached_to_name=confirmation.name,
        filename_prefix="line-confirmation",
    )
    _complete_confirmation(session, confirmation, file_data)
    _reply_completed(reply_token, line_account, session)
    return STATUS_PROCESSED


def _advance_session(event, reply_token, line_account, session, action_config) -> str:
    if cint(action_config.require_location):
        _set_values(
            "LINE User Session",
            session.name,
            {
                "state": STATE_AWAITING_LOCATION,
                "expires_at": _session_expiry(line_account, action_config),
                "last_event_id": _get_event_id(event),
            },
        )
        reply_location_request(
            reply_token,
            session.reference_name,
            line_account,
            action_label=session.action_label or action_config.action_label,
        )
        return STATUS_PROCESSED

    confirmation = _ensure_confirmation(session, line_account, status="Awaiting Image")
    if session.pending_media:
        pending = frappe.get_doc("LINE Pending Media", session.pending_media)
        _complete_confirmation_from_pending(session, confirmation, pending)
        _reply_completed(reply_token, line_account, session)
        return STATUS_PROCESSED

    if cint(action_config.require_image):
        _set_values(
            "LINE User Session",
            session.name,
            {
                "state": STATE_AWAITING_IMAGE,
                "current_confirmation": confirmation.name,
                "expires_at": _session_expiry(line_account, action_config),
                "last_event_id": _get_event_id(event),
            },
        )
        reply_image_request(
            reply_token,
            session.reference_name,
            line_account,
            action_label=session.action_label or action_config.action_label,
            location_received=False,
        )
        return STATUS_PROCESSED

    _complete_confirmation_without_image(session, confirmation)
    _reply_completed(reply_token, line_account, session)
    return STATUS_PROCESSED


def _initialize_session(
    session,
    line_account,
    action_config,
    *,
    source_type: str,
    source_id: str,
    reference_doctype: str | None,
    reference_name: str | None,
    requested_status: str | None,
    pending_media: str | None,
    event_id: str,
) -> None:
    _set_values(
        "LINE User Session",
        session.name,
        {
            "state": STATE_IDLE,
            "source_type": source_type,
            "source_id": source_id,
            "postback_action": action_config.action_code,
            "action_label": action_config.action_label,
            "confirmation_type": action_config.confirmation_type or "Delivery",
            "requested_status": requested_status,
            "require_location": cint(action_config.require_location),
            "require_image": cint(action_config.require_image),
            "forward_route": action_config.forward_route,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "current_confirmation": None,
            "pending_media": pending_media,
            "expires_at": _session_expiry(line_account, action_config),
            "last_event_id": event_id,
            "latitude": 0.0,
            "longitude": 0.0,
            "address": "",
            "location_received_at": None,
            "image_message_id": "",
            "image_file": "",
            "image_received_at": None,
            "confirmed_at": None,
        },
    )


def _ensure_confirmation(session, line_account, *, status: str):
    if session.current_confirmation and frappe.db.exists(
        "LINE Delivery Confirmation", session.current_confirmation
    ):
        return frappe.get_doc("LINE Delivery Confirmation", session.current_confirmation)

    confirmation = frappe.get_doc(
        {
            "doctype": "LINE Delivery Confirmation",
            "confirmation_type": session.confirmation_type or "Delivery",
            "postback_action": session.postback_action,
            "action_label": session.action_label,
            "requested_status": session.requested_status,
            "forward_route": session.forward_route,
            "source_line_account": line_account.name,
            "source_user_id": session.line_user_id,
            "source_type": session.source_type,
            "source_id": session.source_id,
            "line_user_session": session.name,
            "reference_doctype": session.reference_doctype,
            "reference_name": session.reference_name,
            "latitude": session.latitude or 0.0,
            "longitude": session.longitude or 0.0,
            "address": session.address,
            "location_received_at": session.location_received_at,
            "status": status,
            "forward_status": "Pending",
        }
    )
    confirmation.insert(ignore_permissions=True)
    _set_values(
        "LINE User Session",
        session.name,
        {"current_confirmation": confirmation.name},
    )
    return confirmation


def _complete_confirmation(session, confirmation, file_data: dict[str, Any]) -> None:
    completed_at = now_datetime()
    _set_values(
        "LINE Delivery Confirmation",
        confirmation.name,
        {
            "image_message_id": file_data["message_id"],
            "image_file": file_data["original_file_url"],
            "image_file_doc": file_data["original_file_doc"],
            "preview_file_doc": file_data["preview_file_doc"],
            "image_content_type": file_data["content_type"],
            "image_received_at": completed_at,
            "confirmed_at": completed_at,
            "status": "Complete",
            "forward_status": "Pending",
        },
    )
    _set_values(
        "LINE User Session",
        session.name,
        {
            "state": STATE_COMPLETED,
            "image_message_id": file_data["message_id"],
            "image_file": file_data["original_file_url"],
            "image_received_at": completed_at,
            "confirmed_at": completed_at,
            "expires_at": None,
        },
    )
    enqueue_confirmation(confirmation.name)


def _complete_confirmation_from_pending(session, confirmation, pending) -> None:
    if pending.status != "Pending Classification":
        frappe.throw("Pending media is no longer available")
    if _pending_media_expired(pending):
        _expire_pending_media(pending)
        frappe.throw("Pending media has expired")

    for file_name in (pending.original_file_doc, pending.preview_file_doc):
        if file_name and frappe.db.exists("File", file_name):
            frappe.db.set_value(
                "File",
                file_name,
                {
                    "attached_to_doctype": "LINE Delivery Confirmation",
                    "attached_to_name": confirmation.name,
                    "attached_to_field": None,
                },
                update_modified=True,
            )

    file_data = {
        "message_id": pending.image_message_id,
        "original_file_url": pending.image_file,
        "original_file_doc": pending.original_file_doc,
        "preview_file_doc": pending.preview_file_doc,
        "content_type": pending.image_content_type,
    }
    _complete_confirmation(session, confirmation, file_data)
    _set_values(
        "LINE Pending Media",
        pending.name,
        {
            "status": "Assigned",
            "assigned_confirmation": confirmation.name,
            "selected_action": session.postback_action,
        },
    )
    _set_values("LINE User Session", session.name, {"pending_media": None})


def _complete_confirmation_without_image(session, confirmation) -> None:
    completed_at = now_datetime()
    _set_values(
        "LINE Delivery Confirmation",
        confirmation.name,
        {
            "confirmed_at": completed_at,
            "status": "Complete",
            "forward_status": "Pending",
        },
    )
    _set_values(
        "LINE User Session",
        session.name,
        {
            "state": STATE_COMPLETED,
            "confirmed_at": completed_at,
            "expires_at": None,
        },
    )
    enqueue_confirmation(confirmation.name)


def _save_pending_media(event, line_account, user_id, source_type, source_id):
    message_id = ((event.get("message") or {}).get("id") or "").strip()
    existing = frappe.db.exists(
        "LINE Pending Media",
        {"line_account": line_account.name, "image_message_id": message_id},
    )
    if existing:
        return frappe.get_doc("LINE Pending Media", existing)

    hours = max(cint(line_account.pending_media_expiry_hours or 24), 1)
    pending = frappe.get_doc(
        {
            "doctype": "LINE Pending Media",
            "status": "Pending Classification",
            "line_account": line_account.name,
            "line_user_id": user_id,
            "source_type": source_type,
            "source_id": source_id,
            "image_message_id": message_id,
            "received_at": now_datetime(),
            "expires_at": add_to_date(now_datetime(), hours=hours, as_datetime=True),
        }
    )
    pending.insert(ignore_permissions=True)

    file_data = _download_and_save_image(
        event,
        line_account,
        attached_to_doctype="LINE Pending Media",
        attached_to_name=pending.name,
        filename_prefix="line-pending",
    )
    _set_values(
        "LINE Pending Media",
        pending.name,
        {
            "image_file": file_data["original_file_url"],
            "original_file_doc": file_data["original_file_doc"],
            "preview_file_doc": file_data["preview_file_doc"],
            "image_content_type": file_data["content_type"],
        },
    )
    return frappe.get_doc("LINE Pending Media", pending.name)


def _download_and_save_image(
    event,
    line_account,
    *,
    attached_to_doctype: str,
    attached_to_name: str,
    filename_prefix: str,
) -> dict[str, Any]:
    message = event.get("message") or {}
    content_provider = message.get("contentProvider") or {}
    if content_provider.get("type", "line") != "line":
        frappe.throw("Only images stored by LINE content provider are supported")

    message_id = message.get("id")
    content, content_type = download_message_content(message_id, line_account)
    if content_type not in ALLOWED_IMAGE_TYPES:
        frappe.throw(f"Unsupported image content type: {content_type}")
    if not content or len(content) > MAX_IMAGE_BYTES:
        frappe.throw("Image is empty or exceeds the 10 MB forwarding limit")

    extension = ".png" if content_type == "image/png" else ".jpg"
    original_file = save_file(
        f"{filename_prefix}-{message_id}{extension}",
        content,
        attached_to_doctype,
        attached_to_name,
        is_private=1,
    )

    preview_content, preview_content_type = download_message_preview(message_id, line_account)
    if preview_content_type not in ALLOWED_IMAGE_TYPES or not preview_content:
        frappe.throw(f"Unsupported LINE preview content type: {preview_content_type}")
    if len(preview_content) > MAX_PREVIEW_BYTES:
        frappe.throw("LINE preview image exceeds the 1 MB forwarding limit")

    preview_extension = ".png" if preview_content_type == "image/png" else ".jpg"
    preview_file = save_file(
        f"{filename_prefix}-{message_id}-preview{preview_extension}",
        preview_content,
        attached_to_doctype,
        attached_to_name,
        is_private=1,
    )
    return {
        "message_id": message_id,
        "original_file_url": original_file.file_url,
        "original_file_doc": original_file.name,
        "preview_file_doc": preview_file.name,
        "content_type": content_type,
    }


def _reply_completed(reply_token, line_account, session) -> None:
    label = session.action_label or "ยืนยันรายการ"
    lines = [f"✅ บันทึก{label}เรียบร้อยแล้ว"]
    if session.reference_name:
        lines.append(f"เอกสาร: {session.reference_name}")
    if session.latitude not in (None, 0, 0.0) and session.longitude not in (None, 0, 0.0):
        lines.append(f"แผนที่: https://www.google.com/maps?q={session.latitude},{session.longitude}")
    reply_text(reply_token, "\n".join(lines), line_account)


def _get_action_config(line_account, action_code: str | None):
    action_code = (action_code or "").strip()
    if not action_code:
        return None

    for row in line_account.get("postback_actions") or []:
        if cint(row.enabled) and (row.action_code or "").strip() == action_code:
            return row

    legacy_action = (line_account.delivery_postback_action or "job_status").strip()
    if action_code == legacy_action:
        return frappe._dict(
            {
                "enabled": 1,
                "action_code": legacy_action,
                "action_label": "ยืนยันสถานะ",
                "confirmation_type": "Delivery",
                "requested_status": "delivered",
                "require_reference": 0,
                "reference_doctype": None,
                "reference_lookup_field": None,
                "reference_prompt": None,
                "require_location": 1,
                "require_image": 1,
                "forward_route": None,
                "session_expiry_minutes": line_account.session_expiry_minutes or 15,
            }
        )
    return None


def _classification_actions(line_account) -> list[dict[str, str]]:
    result = []
    for row in sorted(
        [row for row in (line_account.get("postback_actions") or []) if cint(row.enabled)],
        key=lambda row: (cint(row.classification_order or 100), row.idx),
    ):
        if cint(row.require_image):
            result.append(
                {
                    "action_code": row.action_code,
                    "action_label": row.action_label,
                }
            )
    if not result:
        result.append(
            {
                "action_code": line_account.delivery_postback_action or "job_status",
                "action_label": "ยืนยันการส่งสินค้า",
            }
        )
    return result


def _resolve_reference_name(action_config, reference_doctype: str | None, value: str | None) -> str:
    reference_doctype = (reference_doctype or "").strip()
    value = (value or "").strip()
    if not reference_doctype or not value:
        frappe.throw("Reference DocType and document name are required")

    if frappe.db.exists(reference_doctype, value):
        return value

    lookup_field = (action_config.reference_lookup_field or "").strip()
    if lookup_field:
        meta = frappe.get_meta(reference_doctype)
        if not meta.has_field(lookup_field):
            frappe.throw(f"Field {lookup_field} does not exist in {reference_doctype}")
        resolved = frappe.db.get_value(reference_doctype, {lookup_field: value}, "name")
        if resolved:
            return resolved

    frappe.throw(f"{reference_doctype} {value} was not found")


def _get_owned_pending_media(media_name, line_account, user_id, event):
    if not frappe.db.exists("LINE Pending Media", media_name):
        frappe.throw("Pending media was not found")
    pending = frappe.get_doc("LINE Pending Media", media_name)
    source_type, source_id = _source_context(event, user_id)
    if (
        pending.line_account != line_account
        or pending.line_user_id != user_id
        or pending.source_type != source_type
        or pending.source_id != source_id
    ):
        frappe.throw("Pending media does not belong to this LINE conversation")
    return pending


def _pending_media_expired(pending) -> bool:
    return bool(pending.expires_at and get_datetime(pending.expires_at) < now_datetime())


def _expire_pending_media(pending) -> None:
    _set_values("LINE Pending Media", pending.name, {"status": "Expired"})


def _find_session(line_account: str, user_id: str, source_type: str, source_id: str):
    keys = [
        _session_key(line_account, user_id, source_type, source_id),
        _legacy_session_key(line_account, user_id),
    ]
    for key in keys:
        name = frappe.db.exists("LINE User Session", {"session_key": key})
        if name:
            return frappe.get_doc("LINE User Session", name)
    return None


def _get_or_create_session(line_account: str, user_id: str, source_type: str, source_id: str):
    session = _find_session(line_account, user_id, source_type, source_id)
    if session:
        new_key = _session_key(line_account, user_id, source_type, source_id)
        if session.session_key != new_key:
            session.session_key = new_key
            session.source_type = source_type
            session.source_id = source_id
            session.save(ignore_permissions=True)
        return session

    doc = frappe.get_doc(
        {
            "doctype": "LINE User Session",
            "session_key": _session_key(line_account, user_id, source_type, source_id),
            "line_account": line_account,
            "line_user_id": user_id,
            "source_type": source_type,
            "source_id": source_id,
            "state": STATE_IDLE,
            "latitude": 0.0,
            "longitude": 0.0,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def _source_context(event, user_id: str) -> tuple[str, str]:
    source = event.get("source") or {}
    source_type = source.get("type") or "user"
    source_id = source.get("groupId") or source.get("roomId") or user_id
    return source_type, source_id


def _session_key(line_account: str, user_id: str, source_type: str, source_id: str) -> str:
    raw = f"{line_account}|{source_type}|{source_id}|{user_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_session_key(line_account: str, user_id: str) -> str:
    return hashlib.sha256(f"{line_account}|{user_id}".encode("utf-8")).hexdigest()


def _session_expiry(line_account, action_config):
    minutes = cint(action_config.session_expiry_minutes or line_account.session_expiry_minutes or 15)
    return add_to_date(now_datetime(), minutes=max(minutes, 1), as_datetime=True)


def _session_expired(session) -> bool:
    return bool(session.expires_at and get_datetime(session.expires_at) < now_datetime())


def _expire_session(session) -> None:
    _cancel_incomplete_confirmation(session.current_confirmation)
    _set_values(
        "LINE User Session",
        session.name,
        {
            "state": STATE_IDLE,
            "expires_at": None,
            "current_confirmation": None,
            "postback_action": None,
            "pending_media": None,
        },
    )


def _cancel_incomplete_confirmation(confirmation_name: str | None) -> None:
    if not confirmation_name or not frappe.db.exists("LINE Delivery Confirmation", confirmation_name):
        return
    status = frappe.db.get_value("LINE Delivery Confirmation", confirmation_name, "status")
    if status == "Awaiting Image":
        frappe.db.set_value(
            "LINE Delivery Confirmation",
            confirmation_name,
            {"status": "Cancelled", "forward_status": "Not Sent"},
            update_modified=True,
        )


def _get_or_create_log(event_id: str, event: dict[str, Any], line_account, destination):
    event_key = hashlib.sha256(f"{line_account.name}|{event_id}".encode("utf-8")).hexdigest()
    existing = frappe.db.exists("LINE Webhook Log", {"event_key": event_key})
    if existing:
        return frappe.get_doc("LINE Webhook Log", existing)

    source = event.get("source") or {}
    message = event.get("message") or {}
    postback = event.get("postback") or {}
    payload = None
    if line_account.log_payload:
        payload = json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True)

    doc = frappe.get_doc(
        {
            "doctype": "LINE Webhook Log",
            "event_key": event_key,
            "line_account": line_account.name,
            "destination": destination,
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


def _param(params, name: str) -> str | None:
    value = (params.get(name) or [None])[0]
    return value.strip() if isinstance(value, str) and value.strip() else None


def _set_values(doctype: str, name: str, values: dict[str, Any], update_modified: bool = True) -> None:
    frappe.db.set_value(doctype, name, values, update_modified=update_modified)


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
