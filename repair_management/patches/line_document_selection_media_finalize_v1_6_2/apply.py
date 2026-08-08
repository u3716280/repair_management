import frappe
from pathlib import Path

from repair_management.integrations.line.flows import document_media_upload


def apply():
    return check()


def _session_info(row):
    row["downloaded_media"] = frappe.db.count(
        "LINE Media File",
        {
            "flow_session": row.name,
            "media_type": "Image",
            "processing_status": ["in", ["Downloaded", "Finalized"]],
        },
    )
    row["attached_collages"] = frappe.db.count(
        "File",
        {
            "attached_to_doctype": row.target_doctype,
            "attached_to_name": row.target_document,
            "file_name": ["like", f"COLLAGE-{row.target_document}-%"] if row.target_document else "",
        },
    ) if row.target_document else 0
    return row


def check():
    sessions = frappe.get_all(
        "LINE Flow Session",
        filters={"action_key": ["in", ["parts_confirm", "video_confirm"]]},
        fields=[
            "name", "action_key", "status", "current_state", "target_doctype",
            "target_document", "expected_media_type", "received_files", "expires_at",
            "error_message",
        ],
        order_by="modified desc",
        limit=20,
    )
    return {
        "status": "ready",
        "runtime": "v1.6.2",
        "media_sessions": [_session_info(row) for row in sessions],
    }


def recover_session(session_name, enqueue=False):
    if not frappe.db.exists("LINE Flow Session", session_name):
        frappe.throw(f"LINE Flow Session not found: {session_name}")
    session = frappe.get_doc("LINE Flow Session", session_name)
    if session.action_key != "parts_confirm":
        frappe.throw("recover_session supports parts_confirm image sessions only")
    if not session.target_doctype or not session.target_document:
        frappe.throw("Session has no target document")

    p = document_media_upload._session_profile(session)
    rows = frappe.get_all(
        "LINE Media File",
        filters={
            "flow_session": session.name,
            "media_type": "Image",
            "processing_status": ["in", ["Downloaded", "Finalized"]],
        },
        fields=["name", "temporary_file", "image_index", "processing_status"],
        order_by="image_index asc",
    )
    if not rows:
        frappe.throw("No LINE Media File rows found")

    existing = document_media_upload._find_existing_collage(session)
    if existing:
        cleanup_errors = (
            document_media_upload._cleanup_original_media(rows)
            if p.delete_originals_after_merge else []
        )
        session.db_set({
            "status": "Completed",
            "current_state": "Completed",
            "error_message": "\n".join(cleanup_errors)[:1400] if cleanup_errors else None,
        })
        frappe.db.commit()
        return {
            "status": "recovered_existing_attachment",
            "session": session.name,
            "target_document": session.target_document,
            "collage_file": existing.name,
            "cleanup_errors": cleanup_errors,
        }

    # Look for a physical collage left by a rolled-back/failed job.
    recovered = document_media_upload._recover_physical_collage(session, p)
    if recovered:
        cleanup_errors = (
            document_media_upload._cleanup_original_media(rows)
            if p.delete_originals_after_merge else []
        )
        session.db_set({
            "status": "Completed",
            "current_state": "Completed",
            "error_message": "\n".join(cleanup_errors)[:1400] if cleanup_errors else None,
        })
        frappe.db.commit()
        return {
            "status": "recovered_physical_collage",
            "session": session.name,
            "target_document": session.target_document,
            "collage_file": recovered.name,
            "cleanup_errors": cleanup_errors,
        }

    if enqueue:
        session.db_set({"status": "Active", "current_state": "Finalizing", "error_message": None})
        frappe.db.commit()
        frappe.enqueue(
            document_media_upload.finalize,
            queue="long",
            channel=session.line_channel,
            session_name=session.name,
            enqueue_after_commit=False,
        )
        return {
            "status": "queued_rebuild",
            "session": session.name,
            "target_document": session.target_document,
            "images": len(rows),
        }

    missing = []
    available = []
    for row in rows:
        if row.temporary_file and frappe.db.exists("File", row.temporary_file):
            fdoc = frappe.get_doc("File", row.temporary_file)
            try:
                if document_media_upload.resolve_file_path(fdoc.file_url).exists():
                    available.append(row.name)
                else:
                    missing.append(row.name)
            except Exception:
                missing.append(row.name)
        else:
            missing.append(row.name)

    return {
        "status": "needs_rebuild" if not missing else "incomplete_originals",
        "session": session.name,
        "target_document": session.target_document,
        "available_originals": available,
        "missing_originals": missing,
        "next_command": (
            "recover_session(..., enqueue=True)"
            if not missing else
            "No automatic rebuild is safe because one or more originals are missing."
        ),
    }
