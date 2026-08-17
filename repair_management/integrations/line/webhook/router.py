from __future__ import annotations

from urllib.parse import parse_qs

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds

from repair_management.integrations.line.actions.registry import dispatch
from repair_management.integrations.line.flows import document_media_upload, media_view, stock_query
from repair_management.integrations.line.flows.base import active
from repair_management.integrations.line.services.recipient import upsert_from_event


def _finalize_request(request_name):
    if not request_name or not frappe.db.exists("LINE Webhook Request", request_name):
        return
    pending = frappe.db.count(
        "LINE Webhook Event",
        {"webhook_request": request_name, "processing_status": ["in", ["Queued", "Processing"]]},
    )
    failed = frappe.db.count(
        "LINE Webhook Event",
        {"webhook_request": request_name, "processing_status": "Failed"},
    )
    if pending:
        status = "Processing"
    elif failed:
        status = "Failed"
    else:
        status = "Completed"
    request_doc = frappe.get_doc("LINE Webhook Request", request_name)
    elapsed = time_diff_in_seconds(now_datetime(), request_doc.received_at) * 1000
    request_doc.db_set({
        "processing_status": status,
        "processing_duration_ms": elapsed,
        "http_response_status": 200,
    })


def process(channel, event_key, event_payload):
    # --- LINE POD echo guard (managed by repair_management_line_pod_v0.2) ---
    from repair_management.integrations.line.delivery_confirmation.webhook import ignore_pod_echo
    if ignore_pod_echo(event_key, event_payload):
        return
    # --- END LINE POD echo guard ---
    event = event_payload
    row = frappe.get_doc("LINE Webhook Event", event_key)
    original_user = frappe.session.user or "Guest"

    try:
        row.db_set("processing_status", "Processing")

        channel_doc = frappe.get_doc("LINE Channel", channel)
        integration_user = channel_doc.integration_user
        if not integration_user:
            frappe.throw(f"LINE Channel {channel} has no Integration User configured")
        if not frappe.db.get_value("User", integration_user, "enabled"):
            frappe.throw(f"LINE Integration User {integration_user} is disabled or does not exist")

        frappe.set_user(integration_user)

        upsert_from_event(channel, event)
        source = event.get("source") or {}
        user = source.get("userId")
        reply = event.get("replyToken")
        typ = event.get("type")

        if typ == "postback" and user:
            params = {
                key: values[-1]
                for key, values in parse_qs(
                    (event.get("postback") or {}).get("data", "")
                ).items()
            }
            action = params.get("action")
            if action == "media_view":
                media_view.start(channel, user, reply)
            elif action == "media_view_document_select":
                media_view.select_document(channel, user, reply, params)
            elif action == "media_view_document_page":
                media_view.document_page(channel, user, reply, params)
            elif action == "media_view_select":
                media_view.select_media(channel, user, reply, params)
            elif action == "media_view_page":
                media_view.media_page(channel, user, reply, params)
            elif action == "stock_search_type":
                stock_query.select_type(channel, user, reply, params)
            elif action == "stock_page":
                stock_query.show_page(channel, user, reply, params)
            elif action == "stock_detail":
                stock_query.show_detail(channel, user, reply, params)
            elif action == "document_select":
                document_media_upload.select_document(channel, user, reply, params)
            elif action == "document_page":
                document_media_upload.show_page(channel, user, reply, params)
            elif action == "document_item_page":
                document_media_upload.show_item_page(channel, user, reply, params)
            elif action == "document_item_select":
                document_media_upload.select_item(channel, user, reply, params)
            elif action == "burn_in_select":
                document_media_upload.select_burn_in(channel, user, reply, params)
            elif action == "media_finish":
                document_media_upload.finish(channel, user, reply, params)
            elif action == "video_attach_help":
                document_media_upload.video_attach_help(channel, user, reply, params)
            elif action == "media_cancel":
                document_media_upload.cancel(channel, user, reply, params)
            elif action:
                dispatch(action, channel, user, reply, params, event)
        elif typ == "message" and user:
            message = event.get("message") or {}
            session = active(channel, user)
            if session and message.get("type") == "text":
                if session.action_key == "stockqry":
                    handler = stock_query.handle_text
                elif session.action_key == "media_view":
                    handler = media_view.handle_text
                else:
                    handler = document_media_upload.handle_text
                handler(channel, user, reply, session, message.get("text", ""))
            elif session and message.get("type") in ("image", "video"):
                document_media_upload.receive(channel, user, reply, session, message)

        row.db_set({
            "processing_status": "Completed",
            "processed_at": now_datetime(),
            "error_message": None,
        })
        _finalize_request(row.webhook_request)
        frappe.db.commit()

    except Exception as exc:
        request_name = row.webhook_request
        frappe.db.rollback()

        failed_row = frappe.get_doc("LINE Webhook Event", event_key)
        failed_row.db_set({
            "processing_status": "Failed",
            "processed_at": now_datetime(),
            "error_message": str(exc),
        })
        _finalize_request(request_name)
        frappe.db.commit()
        raise

    finally:
        if frappe.session.user != original_user:
            frappe.set_user(original_user)
