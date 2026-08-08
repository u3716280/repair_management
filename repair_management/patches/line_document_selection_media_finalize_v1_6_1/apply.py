import frappe
from repair_management.integrations.line.flows import document_media_upload


def apply():
    # No schema/data migration is required. This patch is runtime flow logic only.
    return check()


def check():
    active = frappe.get_all(
        "LINE Flow Session",
        filters={
            "action_key": ["in", ["parts_confirm", "video_confirm"]],
            "status": "Active",
        },
        fields=[
            "name", "action_key", "current_state", "target_doctype",
            "target_document", "expected_media_type", "received_files", "expires_at",
        ],
        order_by="modified desc",
        limit=20,
    )
    pending = []
    for row in active:
        row["downloaded_media"] = frappe.db.count(
            "LINE Media File",
            {"flow_session": row.name, "processing_status": "Downloaded"},
        )
        pending.append(row)
    return {
        "status": "ready",
        "runtime": "v1.6.1",
        "active_media_sessions": pending,
    }


def finalize_pending(session_name):
    if not frappe.db.exists("LINE Flow Session", session_name):
        frappe.throw(f"LINE Flow Session not found: {session_name}")
    session = frappe.get_doc("LINE Flow Session", session_name)
    if session.action_key != "parts_confirm":
        frappe.throw("finalize_pending supports parts_confirm image sessions only")
    if session.status != "Active":
        frappe.throw(f"Session is not Active: {session.status}")
    count = frappe.db.count(
        "LINE Media File",
        {"flow_session": session.name, "media_type": "Image", "processing_status": "Downloaded"},
    )
    if count < 1:
        frappe.throw("No downloaded images found in this session")
    if not session.target_doctype or not session.target_document:
        frappe.throw("Session has no target_doctype/target_document")

    # Mark before enqueue so another Finish click cannot queue the same work again.
    session.db_set({"received_files": count, "current_state": "Finalizing"})
    frappe.db.commit()
    frappe.enqueue(
        document_media_upload.finalize,
        queue="long",
        channel=session.line_channel,
        session_name=session.name,
        enqueue_after_commit=False,
    )
    return {
        "status": "queued",
        "session": session.name,
        "target_doctype": session.target_doctype,
        "target_document": session.target_document,
        "images": count,
    }
