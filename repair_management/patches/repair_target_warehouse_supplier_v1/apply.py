from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# ผูก Warehouse เข้ากับ Supplier (แบบ optional) เพื่อให้ Repair List กรอง Target Warehouse
# ตาม Supplier ที่เลือกได้ (ดู repair_list.js / repair_list.py::_warn_if_target_warehouse_mismatched_supplier)
CUSTOM_FIELDS = {
    "Warehouse": [
        {
            "fieldname": "custom_supplier",
            "label": "Supplier",
            "fieldtype": "Link",
            "options": "Supplier",
            "insert_after": "warehouse_type",
            "in_standard_filter": 1,
            "description": (
                "ระบุถ้าคลังนี้เป็นคลังเฉพาะของซัพพลายเออร์รายใดรายหนึ่ง "
                "ใช้กรอง Target Warehouse ในเอกสาร Repair List (เว้นว่างได้ถ้ายังไม่กำหนด)"
            ),
        },
    ],
}


@frappe.whitelist()
def apply() -> dict:
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Warehouse")
    frappe.db.commit()
    return {
        "status": "applied",
        "doctype": "Warehouse",
        "fieldname": "custom_supplier",
        "next_steps": [
            "Assign Supplier on each relevant Warehouse (List View > select rows > Edit, or open each record)",
            "bench --site local.147 clear-cache",
        ],
    }
