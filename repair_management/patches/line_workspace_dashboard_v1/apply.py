from __future__ import annotations

import json
import frappe
from frappe.utils import now_datetime

WORKSPACE_NAME = "LINE"
MODULE = "Repair Management"

# Candidate doctypes are intentionally resolved at runtime because the LINE module
# evolved during the clean rebuild and not every site has every optional DocType.
DOCTYPE_CANDIDATES = {
    "recipient": ["LINE Recipient", "LINE Recipients"],
    "rich_menu": ["LINE Rich Menu Definition", "LINE Rich Menu"],
    "deployment": ["LINE Rich Menu Deployment"],
    "recipient_link": ["LINE Rich Menu Recipient Link"],
    "policy": ["LINE Rich Menu Policy"],
    "flow_session": ["LINE Flow Session", "LINE Upload Session"],
    "media_profile": ["LINE Document Media Upload Profile"],
    "log": ["LINE Rich Menu Log"],
    "channel": ["LINE Channel"],
}


def _first_existing(candidates):
    for dt in candidates:
        if frappe.db.exists("DocType", dt):
            return dt
    return None


def _resolve_doctypes():
    return {key: _first_existing(value) for key, value in DOCTYPE_CANDIDATES.items()}


def _field_exists(doctype, fieldname):
    if not doctype:
        return False
    try:
        return bool(frappe.get_meta(doctype).has_field(fieldname))
    except Exception:
        return False


def _save_doc(doc):
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    return doc


def _upsert_number_card(label, doctype, filters=None):
    if not doctype:
        return None
    name = f"LINE - {label}"
    existing = frappe.db.exists("Number Card", name)
    doc = frappe.get_doc("Number Card", existing) if existing else frappe.new_doc("Number Card")
    doc.name = name
    doc.label = name
    doc.type = "Document Type"
    doc.document_type = doctype
    doc.function = "Count"
    doc.is_public = 1
    doc.show_percentage_stats = 0
    doc.filters_json = json.dumps(filters or [], ensure_ascii=False)
    _save_doc(doc)
    return doc.name


def _upsert_group_chart(chart_name, doctype, group_field):
    if not doctype or not _field_exists(doctype, group_field):
        return None
    existing = frappe.db.exists("Dashboard Chart", chart_name)
    doc = frappe.get_doc("Dashboard Chart", existing) if existing else frappe.new_doc("Dashboard Chart")
    doc.chart_name = chart_name
    doc.name = chart_name
    doc.chart_type = "Group By"
    doc.document_type = doctype
    doc.group_by_based_on = group_field
    doc.group_by_type = "Count"
    doc.number_of_groups = 10
    doc.is_public = 1
    # Group-by charts do not need a timespan. Keeping filters empty makes this useful
    # across sites regardless of creation timestamps.
    doc.filters_json = "[]"
    _save_doc(doc)
    return doc.name


def _make_shortcut(label, doctype, color="Blue"):
    return {
        "type": "Shortcut",
        "label": label,
        "link_to": doctype,
        "doc_view": "List",
        "color": color,
        "format": "{}",
    }


def _make_card(title, links):
    return {
        "type": "Card",
        "card_name": title,
        "col": 4,
        "links": [
            {
                "type": "Link",
                "label": label,
                "link_to": dt,
                "link_type": "DocType",
                "onboard": 0,
            }
            for label, dt in links if dt
        ],
    }


def _workspace_content(shortcuts, cards, number_cards, charts):
    content = []
    content.append({"id": "line-header", "type": "header", "data": {"text": "<span class=\"h4\">LINE Operations</span>", "col": 12}})

    for shortcut in shortcuts:
        content.append({
            "id": frappe.generate_hash(length=10),
            "type": "shortcut",
            "data": {
                "shortcut_name": shortcut["label"],
                "col": 3,
            },
        })

    if number_cards:
        content.append({"id": "line-kpi-header", "type": "header", "data": {"text": "<span class=\"h4\">Overview</span>", "col": 12}})
        for card_name in number_cards:
            content.append({
                "id": frappe.generate_hash(length=10),
                "type": "number_card",
                "data": {"number_card_name": card_name, "col": 3},
            })

    if charts:
        content.append({"id": "line-monitor-header", "type": "header", "data": {"text": "<span class=\"h4\">Flow Monitoring</span>", "col": 12}})
        for chart_name in charts:
            content.append({
                "id": frappe.generate_hash(length=10),
                "type": "chart",
                "data": {"chart_name": chart_name, "col": 6},
            })

    for card in cards:
        if card["links"]:
            content.append({
                "id": frappe.generate_hash(length=10),
                "type": "card",
                "data": {"card_name": card["card_name"], "col": 4},
            })
    return json.dumps(content, ensure_ascii=False)


def _upsert_workspace(doctypes, number_cards, charts):
    recipient = doctypes["recipient"]
    rich_menu = doctypes["rich_menu"]
    flow_session = doctypes["flow_session"]
    media_profile = doctypes["media_profile"]

    shortcut_defs = [
        ("Recipients", recipient, "Green"),
        ("Rich Menus", rich_menu, "Blue"),
        ("Flow Sessions", flow_session, "Orange"),
        ("Media Profiles", media_profile, "Purple"),
    ]
    shortcut_defs = [x for x in shortcut_defs if x[1]]

    cards = [
        _make_card("Configuration", [
            ("LINE Channel", doctypes["channel"]),
            ("Media Upload Profiles", media_profile),
            ("Rich Menu Policies", doctypes["policy"]),
        ]),
        _make_card("Rich Menu", [
            ("Rich Menu Definitions", rich_menu),
            ("Deployments", doctypes["deployment"]),
            ("Recipient Links", doctypes["recipient_link"]),
        ]),
        _make_card("Operations", [
            ("Recipients", recipient),
            ("Flow Sessions", flow_session),
            ("Logs", doctypes["log"]),
        ]),
    ]

    existing = frappe.db.exists("Workspace", WORKSPACE_NAME)
    ws = frappe.get_doc("Workspace", existing) if existing else frappe.new_doc("Workspace")
    ws.name = WORKSPACE_NAME
    ws.label = WORKSPACE_NAME
    ws.title = WORKSPACE_NAME
    ws.module = MODULE if frappe.db.exists("Module Def", MODULE) else "Home"
    ws.public = 1
    ws.is_hidden = 0
    ws.sequence_id = 1
    # Custom "line" icon ships via public/icons/line-icons.svg (symbol id "icon-line"),
    # registered through the app_include_icons hook.
    ws.icon = "line"

    ws.set("shortcuts", [])
    for label, dt, color in shortcut_defs:
        row = ws.append("shortcuts", {})
        row.type = "DocType"
        row.label = label
        row.link_to = dt
        row.doc_view = "List"
        row.color = color

    ws.set("links", [])
    for card in cards:
        if not card["links"]:
            continue
        heading = ws.append("links", {})
        heading.type = "Card Break"
        heading.label = card["card_name"]
        for link in card["links"]:
            row = ws.append("links", {})
            row.type = "Link"
            row.label = link["label"]
            row.link_to = link["link_to"]
            row.link_type = "DocType"

    ws.set("number_cards", [])
    for name in number_cards:
        row = ws.append("number_cards", {})
        row.number_card_name = name

    ws.set("charts", [])
    for name in charts:
        row = ws.append("charts", {})
        row.chart_name = name

    ws.content = _workspace_content(
        [{"label": x[0]} for x in shortcut_defs], cards, number_cards, charts
    )
    _save_doc(ws)
    return ws


def apply():
    doctypes = _resolve_doctypes()

    recipient = doctypes["recipient"]
    flow = doctypes["flow_session"]
    rich_menu = doctypes["rich_menu"]
    deployment = doctypes["deployment"]

    cards = []
    cards.append(_upsert_number_card("Recipients", recipient))
    cards.append(_upsert_number_card("Rich Menus", rich_menu))
    cards.append(_upsert_number_card("Deployments", deployment))

    # Active flow sessions: adapt to whichever status field is present.
    if flow:
        if _field_exists(flow, "status"):
            cards.append(_upsert_number_card(
                "Active Flow Sessions",
                flow,
                [[flow, "status", "not in", ["Completed", "Cancelled", "Expired"]]],
            ))
        else:
            cards.append(_upsert_number_card("Flow Sessions", flow))

    cards = [c for c in cards if c]

    charts = []
    if flow:
        for fieldname in ("status", "state", "action_key", "action"):
            if _field_exists(flow, fieldname):
                charts.append(_upsert_group_chart(f"LINE - Flow Sessions by {fieldname.replace('_', ' ').title()}", flow, fieldname))
                if len(charts) >= 2:
                    break

    if recipient:
        for fieldname in ("enabled", "custom_line_menu_policy", "line_menu_policy"):
            if _field_exists(recipient, fieldname):
                charts.append(_upsert_group_chart(f"LINE - Recipients by {fieldname.replace('_', ' ').title()}", recipient, fieldname))
                break

    charts = [c for c in charts if c]
    ws = _upsert_workspace(doctypes, cards, charts)

    frappe.db.commit()
    result = {
        "status": "installed",
        "workspace": ws.name,
        "route": "/app/line",
        "resolved_doctypes": doctypes,
        "number_cards": cards,
        "charts": charts,
        "installed_at": str(now_datetime()),
        "next_steps": [
            "bench --site <site> clear-cache",
            "bench --site <site> clear-website-cache",
            "Reload Desk and open /app/line",
        ],
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


@frappe.whitelist()
def check():
    doctypes = _resolve_doctypes()
    result = {
        "workspace_exists": bool(frappe.db.exists("Workspace", WORKSPACE_NAME)),
        "workspace": WORKSPACE_NAME,
        "route": "/app/line",
        "resolved_doctypes": doctypes,
        "number_cards": frappe.get_all("Number Card", filters={"name": ["like", "LINE - %"]}, pluck="name"),
        "charts": frappe.get_all("Dashboard Chart", filters={"name": ["like", "LINE - %"]}, pluck="name"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result
