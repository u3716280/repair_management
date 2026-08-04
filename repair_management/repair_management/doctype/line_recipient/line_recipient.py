
from __future__ import annotations

import frappe
from frappe.model.document import Document


class LINERecipient(Document):
    def validate(self):
        prefixes = {"User": "U", "Group": "C", "Room": "R"}
        expected = prefixes.get(self.recipient_type)
        if expected and self.recipient_id and not self.recipient_id.startswith(expected):
            frappe.throw(f"{self.recipient_type} recipient ID must start with {expected}")

        duplicate = frappe.db.exists(
            "LINE Recipient",
            {
                "line_account": self.line_account,
                "recipient_type": self.recipient_type,
                "recipient_id": self.recipient_id,
                "name": ["!=", self.name or ""],
            },
        )
        if duplicate:
            frappe.throw(f"This recipient already exists as {duplicate}")
