from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import now_datetime


WORKSPACE_NAME = "LINE"
MODULE_NAME = "Repair Management"

CARDS = [
    {
        "label": "ตั้งค่า LINE",
        "links": [
            ("LINE Sales Order Settings", "DocType"),
        ],
    },
    {
        "label": "ผู้รับและการกำหนดเมนู",
        "links": [
            ("LINE Recipients", "DocType"),
            ("LINE Rich Menu Recipient Link", "DocType"),
        ],
    },
    {
        "label": "Rich Menu",
        "links": [
            ("LINE Rich Menu", "DocType"),
            ("LINE Rich Menu Policy", "DocType"),
            ("LINE Rich Menu Deployment", "DocType"),
        ],
    },
    {
        "label": "การอัปโหลด",
        "links": [
            ("LINE Upload Session", "DocType"),
        ],
    },
    {
        "label": "ติดตามและตรวจสอบ",
        "links": [
            ("LINE Rich Menu Log", "DocType"),
        ],
    },
]

SHORTCUTS = [
    ("LINE Sales Order Settings", "DocType"),
    ("LINE Recipients", "DocType"),
    ("LINE Rich Menu", "DocType"),
    ("LINE Rich Menu Deployment", "DocType"),
]


def _bench_path() -> Path:
    app_path = Path(frappe.get_app_path("repair_management")).resolve()
    # .../frappe-bench/apps/repair_management/repair_management
    return app_path.parents[2]


def _backup_workspace(doc) -> str | None:
    if not doc:
        return None

    stamp = now_datetime().strftime("%Y%m%d-%H%M%S")
    backup_dir = _bench_path() / "patch_backups" / f"line_workspace_v1-{stamp}"
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


def _existing_doctypes() -> tuple[list[str], list[str]]:
    requested = [name for card in CARDS for name, _ in card["links"]]
    found = [name for name in requested if frappe.db.exists("DocType", name)]
    missing = [name for name in requested if name not in found]
    return found, missing


def _content(cards: list[dict[str, Any]], shortcuts: list[tuple[str, str]]) -> str:
    blocks: list[dict[str, Any]] = []
    block_no = 1

    blocks.append({
        "id": f"line_header_{block_no}",
        "type": "header",
        "data": {"text": "<span class=\"h4\">LINE Integration</span>", "col": 12},
    })
    block_no += 1

    for label, _ in shortcuts:
        blocks.append({
            "id": f"line_shortcut_{block_no}",
            "type": "shortcut",
            "data": {"shortcut_name": label, "col": 3},
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


def _append_card_links(doc, cards: list[dict[str, Any]]) -> None:
    if not hasattr(doc, "links"):
        return

    for card in cards:
        doc.append("links", {
            "label": card["label"],
            "type": "Card Break",
        })
        for label, link_type in card["links"]:
            doc.append("links", {
                "label": label,
                "type": "Link",
                "link_type": link_type,
                "link_to": label,
                "onboard": 0,
            })


def _append_shortcuts(doc, shortcuts: list[tuple[str, str]]) -> None:
    if not hasattr(doc, "shortcuts"):
        return

    for label, link_type in shortcuts:
        row = {
            "label": label,
            "type": link_type,
            "link_to": label,
        }
        # doc_view is valid for DocType shortcuts in Frappe v15.
        if link_type == "DocType":
            row["doc_view"] = "List"
        doc.append("shortcuts", row)


@frappe.whitelist()
def apply() -> dict[str, Any]:
    found, missing = _existing_doctypes()
    if missing:
        frappe.throw(
            "Cannot create LINE Workspace because required DocType(s) are missing: "
            + ", ".join(missing)
        )

    existing = frappe.get_doc("Workspace", WORKSPACE_NAME) if frappe.db.exists("Workspace", WORKSPACE_NAME) else None
    backup_directory = _backup_workspace(existing)

    if existing:
        doc = existing
        doc.set("links", [])
        doc.set("shortcuts", [])
        if hasattr(doc, "charts"):
            doc.set("charts", [])
        if hasattr(doc, "number_cards"):
            doc.set("number_cards", [])
        if hasattr(doc, "quick_lists"):
            doc.set("quick_lists", [])
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

    _append_card_links(doc, CARDS)
    _append_shortcuts(doc, SHORTCUTS)
    _set_if_supported(doc, meta, "content", _content(CARDS, SHORTCUTS))

    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert()
    else:
        doc.save()

    frappe.db.commit()
    frappe.clear_cache()

    return {
        "status": "created" if existing is None else "updated",
        "workspace": WORKSPACE_NAME,
        "route": "/app/line",
        "module": MODULE_NAME,
        "public": True,
        "doctype_count": len(found),
        "doctypes": found,
        "backup_directory": backup_directory,
        "next_steps": [
            "bench --site local.147 clear-cache",
            "bench --site local.147 clear-website-cache",
            "Restart bench start",
            "Open https://house147.eakthai.com/app/line",
        ],
    }
