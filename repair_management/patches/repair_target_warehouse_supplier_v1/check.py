from __future__ import annotations

import frappe


@frappe.whitelist()
def check() -> dict:
    exists = bool(frappe.db.exists("Custom Field", "Warehouse-custom_supplier"))
    assignments = (
        frappe.get_all(
            "Warehouse",
            filters={"custom_supplier": ["is", "set"]},
            fields=["name", "custom_supplier"],
        )
        if exists
        else []
    )
    total_warehouses = frappe.db.count("Warehouse") if exists else 0
    return {
        "field_exists": exists,
        "total_warehouses": total_warehouses,
        "warehouses_with_supplier_assigned": len(assignments),
        "assignments": assignments,
    }
