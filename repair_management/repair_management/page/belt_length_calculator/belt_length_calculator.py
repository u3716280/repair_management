import frappe


@frappe.whitelist()
def get_context():
    return {
        "status": "ok"
    }
