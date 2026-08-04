from __future__ import annotations

import frappe
from frappe.utils import now_datetime


DEFAULT_ACTIONS = [
    {
        "enabled": 1,
        "action_code": "job_status",
        "action_label": "ยืนยันการส่งสินค้า",
        "confirmation_type": "Delivery",
        "requested_status": "delivered",
        "require_reference": 0,
        "require_location": 1,
        "require_image": 1,
        "session_expiry_minutes": 15,
        "classification_order": 10,
    },
    {
        "enabled": 1,
        "action_code": "payment_confirm",
        "action_label": "ยืนยันการชำระเงิน",
        "confirmation_type": "Payment",
        "requested_status": "paid",
        "require_reference": 0,
        "require_location": 0,
        "require_image": 1,
        "session_expiry_minutes": 15,
        "classification_order": 20,
    },
    {
        "enabled": 1,
        "action_code": "service_photo",
        "action_label": "ภาพถ่าย Service หน้างาน",
        "confirmation_type": "Service",
        "requested_status": "onsite",
        "require_reference": 1,
        "reference_doctype": "Sales Order",
        "reference_prompt": "กรุณาส่งเลขที่ Sales Order ที่เกี่ยวข้องกับงาน Service",
        "require_location": 1,
        "require_image": 1,
        "session_expiry_minutes": 30,
        "classification_order": 30,
    },
]


def apply():
    results = []
    for name in frappe.get_all("LINE Account", pluck="name"):
        account = frappe.get_doc("LINE Account", name)
        existing = {(row.action_code or "").strip() for row in account.get("postback_actions") or []}
        added = []
        for values in DEFAULT_ACTIONS:
            action_code = values["action_code"]
            if action_code in existing:
                continue
            account.append("postback_actions", values)
            added.append(action_code)
        if not account.pending_media_expiry_hours:
            account.pending_media_expiry_hours = 24
        if added:
            account.save(ignore_permissions=True)
        results.append({"line_account": name, "added_actions": added})

    frappe.db.commit()
    return {"ok": True, "applied_at": str(now_datetime()), "accounts": results}
