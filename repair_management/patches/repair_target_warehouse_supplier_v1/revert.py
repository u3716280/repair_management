from __future__ import annotations

import frappe


@frappe.whitelist()
def revert() -> dict:
    name = "Warehouse-custom_supplier"
    if not frappe.db.exists("Custom Field", name):
        return {"status": "not_found", "deleted": None}

    frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
    frappe.clear_cache(doctype="Warehouse")
    frappe.db.commit()
    return {"status": "reverted", "deleted": name}
