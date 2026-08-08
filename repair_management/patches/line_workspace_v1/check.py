from __future__ import annotations

import json

import frappe


WORKSPACE_NAME = "LINE"
EXPECTED_DOCTYPES = [
    "LINE Sales Order Settings",
    "LINE Recipients",
    "LINE Rich Menu Recipient Link",
    "LINE Rich Menu",
    "LINE Rich Menu Policy",
    "LINE Rich Menu Deployment",
    "LINE Upload Session",
    "LINE Rich Menu Log",
]


@frappe.whitelist()
def check() -> dict:
    workspace_exists = bool(frappe.db.exists("Workspace", WORKSPACE_NAME))
    found_doctypes = [dt for dt in EXPECTED_DOCTYPES if frappe.db.exists("DocType", dt)]
    missing_doctypes = [dt for dt in EXPECTED_DOCTYPES if dt not in found_doctypes]

    result = {
        "workspace_exists": workspace_exists,
        "workspace": WORKSPACE_NAME,
        "route": "/app/line",
        "found_doctypes": found_doctypes,
        "missing_doctypes": missing_doctypes,
        "is_ready": workspace_exists and not missing_doctypes,
    }

    if workspace_exists:
        doc = frappe.get_doc("Workspace", WORKSPACE_NAME)
        result.update({
            "module": getattr(doc, "module", None),
            "public": bool(getattr(doc, "public", 0)),
            "is_hidden": bool(getattr(doc, "is_hidden", 0)),
            "shortcut_count": len(getattr(doc, "shortcuts", []) or []),
            "link_count": len(getattr(doc, "links", []) or []),
        })

    return result
