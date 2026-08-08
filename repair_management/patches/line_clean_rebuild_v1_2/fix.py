from __future__ import annotations

import json

import frappe

EXPECTED_DOCTYPES = [
    "LINE Channel",
    "LINE Recipient",
    "LINE Webhook Request",
    "LINE Webhook Event",
    "LINE Action Registry",
    "LINE Business Flow",
    "LINE Rich Menu Recipient Assignment",
]

WORKSPACE_SHORTCUTS = [
    "LINE Channel",
    "LINE Recipient",
    "LINE Webhook Request",
    "LINE Webhook Event",
    "LINE Action Registry",
    "LINE Business Flow",
    "LINE Stock Query Configuration",
    "LINE Document Media Upload Profile",
    "LINE Rich Menu Definition",
    "LINE Rich Menu Deployment",
    "LINE Rich Menu Audience",
    "LINE Rich Menu Recipient Assignment",
    "LINE Rich Menu Recipient Link",
    "LINE Flow Session",
    "LINE Integration Log",
]


def _print(data):
    print(json.dumps(data, ensure_ascii=False))
    return data


def _valid_child_values(child_doctype, values):
    meta = frappe.get_meta(child_doctype)
    valid = {field.fieldname for field in meta.fields}
    return {key: value for key, value in values.items() if key in valid}


@frappe.whitelist()
def create_workspace():
    if frappe.db.exists("Workspace", "LINE"):
        frappe.delete_doc("Workspace", "LINE", force=True, ignore_permissions=True)

    workspace = frappe.new_doc("Workspace")
    workspace.name = "LINE"
    meta = frappe.get_meta("Workspace")
    for fieldname, value in {
        "label": "LINE",
        "title": "LINE",
        "module": "Repair Management",
        "public": 1,
        "is_hidden": 0,
        "icon": "message-square",
        "parent_page": "",
    }.items():
        if meta.get_field(fieldname):
            workspace.set(fieldname, value)

    shortcuts = []
    if meta.get_field("shortcuts"):
        child_doctype = meta.get_field("shortcuts").options
        for doctype in WORKSPACE_SHORTCUTS:
            if not frappe.db.exists("DocType", doctype):
                continue
            workspace.append("shortcuts", _valid_child_values(child_doctype, {
                "type": "DocType",
                "label": doctype,
                "link_to": doctype,
                "doc_view": "List",
                "color": "Blue",
            }))
            shortcuts.append(doctype)

    if meta.get_field("content"):
        content = [{
            "id": "line-header",
            "type": "header",
            "data": {"text": '<span class="h4">LINE Integration</span>', "col": 12},
        }]
        for index, doctype in enumerate(shortcuts, start=1):
            content.append({
                "id": f"line-shortcut-{index}",
                "type": "shortcut",
                "data": {"shortcut_name": doctype, "col": 3},
            })
        workspace.content = json.dumps(content, ensure_ascii=False)

    workspace.insert(ignore_permissions=True)
    frappe.db.commit()
    return _print({"workspace": workspace.name, "shortcuts": shortcuts})


@frappe.whitelist()
def verify():
    missing = [name for name in EXPECTED_DOCTYPES if not frappe.db.exists("DocType", name)]
    action_field = frappe.get_meta("LINE Action Registry").get_field("business_flow")
    assignment_field = frappe.get_meta("LINE Rich Menu Recipient Assignment").get_field("recipient")
    flow_doc = frappe.get_doc("DocType", "LINE Business Flow")
    channel_meta = frappe.get_meta("LINE Channel")
    checks = {
        "action_business_flow_is_link": bool(action_field and action_field.fieldtype == "Link" and action_field.options == "LINE Business Flow"),
        "assignment_recipient_is_link": bool(assignment_field and assignment_field.fieldtype == "Link" and assignment_field.options == "LINE Recipient"),
        "business_flow_title_field": flow_doc.title_field,
        "business_flow_show_title_in_link": int(flow_doc.show_title_field_in_link or 0),
        "channel_secret_length": int(channel_meta.get_field("channel_secret").length or 0),
        "channel_access_token_length": int(channel_meta.get_field("channel_access_token").length or 0),
        "workspace_exists": bool(frappe.db.exists("Workspace", "LINE")),
    }
    ready = (
        not missing
        and checks["action_business_flow_is_link"]
        and checks["assignment_recipient_is_link"]
        and checks["business_flow_title_field"] == "flow_name"
        and checks["business_flow_show_title_in_link"] == 1
        and checks["channel_secret_length"] >= 512
        and checks["channel_access_token_length"] >= 512
        and checks["workspace_exists"]
    )
    return _print({"site": frappe.local.site, "missing_doctypes": missing, "checks": checks, "ready": ready})
