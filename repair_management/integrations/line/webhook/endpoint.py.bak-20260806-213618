from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import frappe
from frappe.utils import now_datetime


def _headers_json() -> str:
    headers = {str(k): str(v) for k, v in frappe.request.headers.items()}
    return json.dumps(headers, ensure_ascii=False, indent=2, sort_keys=True)


def _event_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(
            tzinfo=None
        )
    except (TypeError, ValueError, OSError):
        return None


def _event_key(event: dict) -> str:
    return (
        event.get("webhookEventId")
        or (event.get("message") or {}).get("id")
        or hashlib.sha256(
            json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    )


def _request_value(source, key: str):
    """Read a key from a Flask/Frappe request mapping without assuming its type."""
    if source is None:
        return None
    getter = getattr(source, "get", None)
    if not callable(getter):
        return None
    try:
        return getter(key)
    except (KeyError, TypeError, AttributeError):
        return None


def _resolve_channel(channel=None) -> str:
    """Resolve the LINE Channel from method args, query string, then form data.

    Frappe does not always bind URL query parameters to whitelisted method
    arguments when the POST body is JSON. LINE sends JSON, so request.args must
    be checked explicitly.
    """
    request = getattr(frappe, "request", None)
    request_args = getattr(request, "args", None) if request is not None else None
    form_dict = getattr(frappe, "form_dict", None)

    candidate = (
        channel
        or _request_value(request_args, "channel")
        or _request_value(form_dict, "channel")
    )
    if candidate is None:
        return ""

    # Flask normally URL-decodes request.args already. unquote_plus keeps this
    # robust for direct method/form invocations that still contain %20 or +.
    return unquote_plus(str(candidate)).strip()


def _insert_request(channel, raw_text, signature, signature_valid, payload, started):
    events = payload.get("events", []) if isinstance(payload, dict) else []
    doc = frappe.get_doc(
        {
            "doctype": "LINE Webhook Request",
            "line_channel": channel,
            "received_at": now_datetime(),
            "destination": payload.get("destination")
            if isinstance(payload, dict)
            else None,
            "event_count": len(events),
            "is_verification_request": 1
            if isinstance(payload, dict) and not events
            else 0,
            "signature": signature,
            "signature_valid": 1 if signature_valid else 0,
            "raw_request_json": raw_text,
            "parsed_request_json": json.dumps(payload, ensure_ascii=False, indent=2)
            if payload is not None
            else None,
            "headers_json": _headers_json(),
            "http_response_status": 200 if signature_valid else 401,
            "processing_status": "Verified" if signature_valid else "Rejected",
            "processing_duration_ms": round(
                (time.perf_counter() - started) * 1000, 3
            ),
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


@frappe.whitelist(allow_guest=True)
def handle(channel=None):
    started = time.perf_counter()
    resolved_channel = _resolve_channel(channel)

    if not resolved_channel or not frappe.db.exists(
        "LINE Channel", resolved_channel
    ):
        frappe.local.response.http_status_code = 404
        return {
            "status": "unknown_channel",
            "channel": resolved_channel or None,
        }

    channel_doc = frappe.get_doc("LINE Channel", resolved_channel)
    raw = frappe.request.get_data(cache=False)
    raw_text = raw.decode("utf-8", errors="replace")
    signature = frappe.get_request_header("X-Line-Signature") or ""
    secret = channel_doc.get_password("channel_secret", raise_exception=False) or ""
    expected = base64.b64encode(
        hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    ).decode("ascii")
    signature_valid = bool(
        signature and secret and hmac.compare_digest(signature, expected)
    )

    payload = None
    parse_error = None
    if signature_valid:
        try:
            payload = json.loads(raw_text)
        except Exception as exc:
            parse_error = str(exc)

    request_doc = _insert_request(
        resolved_channel,
        raw_text,
        signature,
        signature_valid,
        payload,
        started,
    )

    if not signature_valid:
        request_doc.db_set(
            {
                "processing_status": "Rejected",
                "http_response_status": 401,
                "error_message": "Invalid X-Line-Signature",
            }
        )
        frappe.db.commit()
        frappe.local.response.http_status_code = 401
        return {"status": "invalid_signature", "request": request_doc.name}

    if parse_error:
        request_doc.db_set(
            {
                "processing_status": "Failed",
                "http_response_status": 400,
                "error_message": parse_error,
            }
        )
        frappe.db.commit()
        frappe.local.response.http_status_code = 400
        return {"status": "invalid_json", "request": request_doc.name}

    events = payload.get("events", []) if isinstance(payload, dict) else []
    queued = []
    for index, event in enumerate(events):
        key = _event_key(event)
        if frappe.db.exists("LINE Webhook Event", key):
            continue
        source = event.get("source") or {}
        message = event.get("message") or {}
        row = frappe.get_doc(
            {
                "doctype": "LINE Webhook Event",
                "webhook_request": request_doc.name,
                "event_index": index,
                "event_key": key,
                "webhook_event_id": event.get("webhookEventId"),
                "line_channel": resolved_channel,
                "event_type": event.get("type"),
                "event_mode": event.get("mode"),
                "event_timestamp": _event_datetime(event.get("timestamp")),
                "source_type": source.get("type"),
                "line_user_id": source.get("userId"),
                "group_id": source.get("groupId"),
                "room_id": source.get("roomId"),
                "message_id": message.get("id"),
                "payload_json": json.dumps(event, ensure_ascii=False, indent=2),
                "processing_status": "Queued",
            }
        )
        row.insert(ignore_permissions=True)
        queued.append((key, event))

    if queued:
        request_doc.db_set("processing_status", "Queued")
    else:
        request_doc.db_set(
            {
                "processing_status": "Completed",
                "http_response_status": 200,
                "processing_duration_ms": round(
                    (time.perf_counter() - started) * 1000, 3
                ),
            }
        )

    frappe.db.commit()
    for key, event in queued:
        frappe.enqueue(
            "repair_management.integrations.line.webhook.router.process",
            queue="short",
            channel=resolved_channel,
            event_key=key,
            event_payload=event,
            enqueue_after_commit=False,
        )

    return {
        "status": "ok",
        "request": request_doc.name,
        "events": len(events),
        "queued": len(queued),
    }
