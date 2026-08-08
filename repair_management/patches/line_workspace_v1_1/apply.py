from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import now_datetime


WORKSPACE_NAME = "LINE"
MODULE_NAME = "Repair Management"

# Each entry may contain aliases. The first existing DocType will be used.
CARD_DEFINITIONS = [
    {
        "label": "ตั้งค่า LINE",
        "items": [
            {"label": "LINE Sales Order Settings", "candidates": ["LINE Sales Order Settings"]},
        ],
    },
    {
        "label": "ผู้รับและการกำหนดเมนู",
        "items": [
            {
                "label": "LINE Recipients",
                "candidates": ["LINE Recipients", "LINE Recipient"],
                "optional": True,
            },
            {
                "label": "LINE Rich Menu Recipient Link",
                "candidates": ["LINE Rich Menu Recipient Link"],
            },
        ],
    },
    {
        "label": "Rich Menu",
        "items": [
            {"label": "LINE Rich Menu", "candidates": ["LINE Rich Menu"]},
            {"label": "LINE Rich Menu Policy", "candidates": ["LINE Rich Menu Policy"]},
            {"label": "LINE Rich Menu Deployment", "candidates": ["LINE Rich Menu Deployment"]},
        ],
    },
    {
        "label": "การอัปโหลด",
        "items": [
            {"label": "LINE Upload Session", "candidates": ["LINE Upload Session"], "optional": True},
        ],
    },
    {
        "label": "ติดตามและตรวจสอบ",
        "items": [
            {"label": "LINE Rich Menu Log", "candidates": ["LINE Rich Menu Log"], "optional": True},
        ],
    },
]

SHORTCUT_LABELS = [
    "LINE Sales Order Settings",
    "LINE Recipients",
    "LINE Rich Menu",
    "LINE Rich Menu Deployment",
]


def _bench_path() -> Path:
    app_path = Path(frappe.get_app_path("repair_management")).resolve()
    return app_path.parents[2]


def _backup_workspace(doc) -> str | None:
    if not doc:
        return None

    stamp = now_datetime().strftime("%Y%m%d-%H%M%S")
    backup_dir = _bench_path() / "patch_backups" / f"line_workspace_v1_1-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / "LINE.workspace.json"
    backup_file.write_text(
        json.dumps(doc.as_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return str(backup_dir)


def _field_exists(meta, fieldname: str) -> bool:
    return bool(meta.get_field(fieldname))


def _set_if_supported(doc, meta, fieldname: str, value: Any) -> None:
    if _field_exists(meta, fieldname):
        doc.set(fieldname, value)


def _resolve_cards():
    cards = []
    resolved = {}
    missing_required = []
    skipped_optional = []

    for card in CARD_DEFINITIONS:
        links = []
        for item in card["items"]:
            selected = next(
                (candidate for candidate in item["candidates"]
                 if frappe.db.exists("DocType", candidate)),
                None,
            )
            if selected:
                resolved[item["label"]] = selected
                links.append((item["label"], selected))
            elif item.get("optional"):
                skipped_optional.append(item["label"])
            else:
                missing_required.append(item["label"])

        if links:
            cards.append({"label": card["label"], "links": links})

    return cards, resolved, missing_required, skipped_optional


def _content(cards, shortcuts):
    blocks = []
    block_no = 1

    blocks.append({
        "id": f"line_header_{block_no}",
        "type": "header",
        "data": {"text": "<span class=\"h4\">LINE Integration</span>", "col": 12},
    })
    block_no += 1

    for shortcut in shortcuts:
        blocks.append({
            "id": f"line_shortcut_{block_no}",
            "type": "shortcut",
            "data": {"shortcut_name": shortcut["label"], "col": 3},
        })
        block_no += 1

    blocks.append({
        "id": f"line_spacer_{block_no}",
        "type": "spacer",
        "data": {"col": 12},
    })
    block_no += 1

    for card in cards:
        blocks.append({
            "id": f"line_card_{block_no}",
            "type": "card",
            "data": {"card_name": card["label"], "col": 4},
        })
        block_no += 1

    return json.dumps(blocks, ensure_ascii=False)


def _append_card_links(doc, cards):
    if not hasattr(doc, "links"):
        return

    for card in cards:
        doc.append("links", {"label": card["label"], "type": "Card Break"})
        for display_label, doctype_name in card["links"]:
            doc.append("links", {
                "label": display_label,
                "type": "Link",
                "link_type": "DocType",
                "link_to": doctype_name,
                "onboard": 0,
            })


def _append_shortcuts(doc, shortcuts):
    if not hasattr(doc, "shortcuts"):
        return

    for shortcut in shortcuts:
        doc.append("shortcuts", {
            "label": shortcut["label"],
            "type": "DocType",
            "link_to": shortcut["doctype"],
            "doc_view": "List",
        })


@frappe.whitelist()
def apply() -> dict[str, Any]:
    cards, resolved, missing_required, skipped_optional = _resolve_cards()

    if missing_required:
        frappe.throw(
            "Cannot create LINE Workspace because required DocType(s) are missing: "
            + ", ".join(missing_required)
        )

    shortcuts = []
    for label in SHORTCUT_LABELS:
        doctype_name = resolved.get(label)
        if doctype_name:
            shortcuts.append({"label": label, "doctype": doctype_name})

    existing = (
        frappe.get_doc("Workspace", WORKSPACE_NAME)
        if frappe.db.exists("Workspace", WORKSPACE_NAME)
        else None
    )
    backup_directory = _backup_workspace(existing)

    if existing:
        doc = existing
        for table_field in ("links", "shortcuts", "charts", "number_cards", "quick_lists"):
            if hasattr(doc, table_field):
                doc.set(table_field, [])
    else:
        doc = frappe.new_doc("Workspace")
        doc.name = WORKSPACE_NAME

    meta = frappe.get_meta("Workspace")
    _set_if_supported(doc, meta, "title", WORKSPACE_NAME)
    _set_if_supported(doc, meta, "label", WORKSPACE_NAME)
    _set_if_supported(doc, meta, "module", MODULE_NAME)
    _set_if_supported(doc, meta, "icon", "message-circle")
    _set_if_supported(doc, meta, "indicator_color", "green")
    _set_if_supported(doc, meta, "public", 1)
    _set_if_supported(doc, meta, "is_hidden", 0)
    _set_if_supported(doc, meta, "parent_page", "")
    _set_if_supported(doc, meta, "for_user", "")
    _set_if_supported(doc, meta, "sequence_id", 20)

    _append_card_links(doc, cards)
    _append_shortcuts(doc, shortcuts)
    _set_if_supported(doc, meta, "content", _content(cards, shortcuts))

    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert()
        status = "created"
    else:
        doc.save()
        status = "updated"

    frappe.db.commit()
    frappe.clear_cache()

    return {
        "status": status,
        "workspace": WORKSPACE_NAME,
        "route": "/app/line",
        "module": MODULE_NAME,
        "resolved_doctypes": resolved,
        "skipped_optional_doctypes": skipped_optional,
        "backup_directory": backup_directory,
        "next_steps": [
            "bench --site local.147 clear-cache",
            "bench --site local.147 clear-website-cache",
            "Restart bench start",
            "Open https://house147.eakthai.com/app/line",
        ],
    }
