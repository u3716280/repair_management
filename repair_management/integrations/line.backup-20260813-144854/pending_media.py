from __future__ import annotations

import frappe
from frappe.utils import get_datetime, now_datetime


@frappe.whitelist()
def cleanup_expired_pending_media(delete_files: int = 1):
    names = frappe.get_all(
        "LINE Pending Media",
        filters={
            "status": "Pending Classification",
            "expires_at": ["<", now_datetime()],
        },
        pluck="name",
        limit_page_length=500,
    )
    expired = 0
    deleted_files = 0

    for name in names:
        doc = frappe.get_doc("LINE Pending Media", name)
        doc.status = "Expired"
        doc.save(ignore_permissions=True)
        expired += 1

        if int(delete_files):
            for file_name in (doc.original_file_doc, doc.preview_file_doc):
                if file_name and frappe.db.exists("File", file_name):
                    frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
                    deleted_files += 1

    frappe.db.commit()
    return {"ok": True, "expired": expired, "deleted_files": deleted_files}
