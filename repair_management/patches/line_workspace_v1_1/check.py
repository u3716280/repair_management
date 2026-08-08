from __future__ import annotations

import frappe


WORKSPACE_NAME = "LINE"

GROUPS = {
    "LINE Sales Order Settings": ["LINE Sales Order Settings"],
    "LINE Recipients": ["LINE Recipients", "LINE Recipient"],
    "LINE Rich Menu Recipient Link": ["LINE Rich Menu Recipient Link"],
    "LINE Rich Menu": ["LINE Rich Menu"],
    "LINE Rich Menu Policy": ["LINE Rich Menu Policy"],
    "LINE Rich Menu Deployment": ["LINE Rich Menu Deployment"],
    "LINE Upload Session": ["LINE Upload Session"],
    "LINE Rich Menu Log": ["LINE Rich Menu Log"],
}

OPTIONAL = {"LINE Recipients", "LINE Upload Session", "LINE Rich Menu Log"}


@frappe.whitelist()
def check() -> dict:
    resolved = {}
    missing_required = []
    missing_optional = []

    for label, candidates in GROUPS.items():
        selected = next(
            (candidate for candidate in candidates if frappe.db.exists("DocType", candidate)),
            None,
        )
        if selected:
            resolved[label] = selected
        elif label in OPTIONAL:
            missing_optional.append(label)
        else:
            missing_required.append(label)

    workspace_exists = bool(frappe.db.exists("Workspace", WORKSPACE_NAME))
    result = {
        "workspace_exists": workspace_exists,
        "workspace": WORKSPACE_NAME,
        "route": "/app/line",
        "resolved_doctypes": resolved,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "can_create": not missing_required,
        "is_ready": workspace_exists and not missing_required,
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
