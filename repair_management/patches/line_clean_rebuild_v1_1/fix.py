from __future__ import annotations

import json
from pathlib import Path

import frappe

LEGACY_DOCTYPES = [
    "LINE Account",
    "LINE Delivery Confirmation",
    "LINE Forward Log",
    "LINE Forward Route",
    "LINE Forward Route Target",
    "LINE Pending Media",
    "LINE Postback Action",
    "LINE Recipient",
    "LINE Settings",
    "LINE User Session",
    "LINE Webhook Log",
]

EXPECTED_DOCTYPES = [
    "LINE Channel",
    "LINE Action Registry",
    "LINE Business Flow",
    "LINE Document Display Field",
    "LINE Document Filter",
    "LINE Document Media Upload Profile",
    "LINE Document Search Field",
    "LINE Flow Session",
    "LINE Integration Log",
    "LINE Media File",
    "LINE Rich Menu Area",
    "LINE Rich Menu Audience",
    "LINE Rich Menu Definition",
    "LINE Rich Menu Deployment",
    "LINE Rich Menu Recipient Assignment",
    "LINE Rich Menu Recipient Link",
    "LINE Stock Allowed Item Group",
    "LINE Stock Allowed Warehouse",
    "LINE Stock Query Configuration",
    "LINE Webhook Event",
]

WORKSPACE_SHORTCUTS = [
    "LINE Channel",
    "LINE Rich Menu Definition",
    "LINE Rich Menu Deployment",
    "LINE Rich Menu Audience",
    "LINE Rich Menu Recipient Assignment",
    "LINE Rich Menu Recipient Link",
    "LINE Action Registry",
    "LINE Business Flow",
    "LINE Stock Query Configuration",
    "LINE Document Media Upload Profile",
    "LINE Flow Session",
    "LINE Integration Log",
    "LINE Webhook Event",
]


def _print(data: dict) -> dict:
    print(json.dumps(data, ensure_ascii=False))
    return data


@frappe.whitelist()
def cleanup_legacy_doctypes():
    removed = []
    missing = []
    for doctype in LEGACY_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            frappe.delete_doc(
                "DocType",
                doctype,
                force=True,
                ignore_permissions=True,
            )
            removed.append(doctype)
        else:
            missing.append(doctype)

    # Remove old LINE workspaces only. A clean workspace is recreated later.
    for name in frappe.get_all(
        "Workspace",
        filters={"name": ["in", ["LINE", "Line"]]},
        pluck="name",
    ):
        frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True)

    frappe.db.commit()
    return _print({"removed_legacy_doctypes": removed, "already_absent": missing})


def _valid_child_values(child_doctype: str, values: dict) -> dict:
    meta = frappe.get_meta(child_doctype)
    valid = {field.fieldname for field in meta.fields}
    return {key: value for key, value in values.items() if key in valid}


@frappe.whitelist()
def create_workspace():
    if frappe.db.exists("Workspace", "LINE"):
        frappe.delete_doc("Workspace", "LINE", force=True, ignore_permissions=True)

    workspace = frappe.new_doc("Workspace")
    workspace.name = "LINE"

    workspace_meta = frappe.get_meta("Workspace")
    values = {
        "label": "LINE",
        "title": "LINE",
        "module": "Repair Management",
        "public": 1,
        "is_hidden": 0,
        "icon": "message-square",
        "parent_page": "",
    }
    for fieldname, value in values.items():
        if workspace_meta.get_field(fieldname):
            workspace.set(fieldname, value)

    shortcut_rows = []
    if workspace_meta.get_field("shortcuts"):
        child_doctype = workspace_meta.get_field("shortcuts").options
        for doctype in WORKSPACE_SHORTCUTS:
            if not frappe.db.exists("DocType", doctype):
                continue
            row = _valid_child_values(
                child_doctype,
                {
                    "type": "DocType",
                    "label": doctype,
                    "link_to": doctype,
                    "doc_view": "List",
                    "color": "Blue",
                },
            )
            workspace.append("shortcuts", row)
            shortcut_rows.append(doctype)

    # Workspace v15 uses content to place shortcut blocks on the canvas.
    if workspace_meta.get_field("content"):
        content = [
            {
                "id": "line-header",
                "type": "header",
                "data": {
                    "text": '<span class="h4">LINE Integration</span>',
                    "col": 12,
                },
            }
        ]
        for index, doctype in enumerate(shortcut_rows, start=1):
            content.append(
                {
                    "id": f"line-shortcut-{index}",
                    "type": "shortcut",
                    "data": {"shortcut_name": doctype, "col": 3},
                }
            )
        workspace.content = json.dumps(content, ensure_ascii=False)

    workspace.insert(ignore_permissions=True)
    frappe.db.commit()
    return _print({"workspace": workspace.name, "shortcuts": shortcut_rows})


@frappe.whitelist()
def verify():
    legacy_present = [
        doctype for doctype in LEGACY_DOCTYPES if frappe.db.exists("DocType", doctype)
    ]
    missing_expected = [
        doctype for doctype in EXPECTED_DOCTYPES if not frappe.db.exists("DocType", doctype)
    ]

    doctype_root = Path(
        frappe.get_app_path("repair_management", "repair_management", "doctype")
    )
    legacy_source_present = []
    for folder in (
        "line_account",
        "line_delivery_confirmation",
        "line_forward_log",
        "line_forward_route",
        "line_forward_route_target",
        "line_pending_media",
        "line_postback_action",
        "line_recipient",
        "line_settings",
        "line_user_session",
        "line_webhook_log",
    ):
        if (doctype_root / folder).exists():
            legacy_source_present.append(folder)

    required_source_missing = []
    for folder in (
        "line_rich_menu_area",
        "line_rich_menu_deployment",
        "line_rich_menu_recipient_link",
    ):
        if not (doctype_root / folder).exists():
            required_source_missing.append(folder)

    workspace_exists = bool(frappe.db.exists("Workspace", "LINE"))
    result = {
        "site": frappe.local.site,
        "legacy_doctypes_present": legacy_present,
        "legacy_source_present": legacy_source_present,
        "missing_expected_doctypes": missing_expected,
        "missing_required_source": required_source_missing,
        "workspace_exists": workspace_exists,
        "ready": not legacy_present
        and not legacy_source_present
        and not missing_expected
        and not required_source_missing
        and workspace_exists,
    }
    return _print(result)
