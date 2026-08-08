from __future__ import annotations

import json
from pathlib import Path

import frappe


WORKSPACE_NAME = "LINE"


@frappe.whitelist()
def revert(backup_directory: str | None = None) -> dict:
    if backup_directory:
        backup_file = Path(backup_directory) / "LINE.workspace.json"
        if not backup_file.exists():
            frappe.throw(f"Backup file not found: {backup_file}")

        data = json.loads(backup_file.read_text(encoding="utf-8"))
        data.pop("doctype", None)

        if frappe.db.exists("Workspace", WORKSPACE_NAME):
            frappe.delete_doc("Workspace", WORKSPACE_NAME, force=True, ignore_permissions=True)

        data["doctype"] = "Workspace"
        doc = frappe.get_doc(data)
        doc.flags.ignore_permissions = True
        doc.insert()
        status = "restored"
    else:
        if frappe.db.exists("Workspace", WORKSPACE_NAME):
            frappe.delete_doc("Workspace", WORKSPACE_NAME, force=True, ignore_permissions=True)
            status = "deleted"
        else:
            status = "not_found"

    frappe.db.commit()
    frappe.clear_cache()
    return {"status": status, "workspace": WORKSPACE_NAME}
