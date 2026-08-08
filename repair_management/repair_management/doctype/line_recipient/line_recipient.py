from __future__ import annotations

import hashlib

import frappe
from frappe.model.document import Document


class LINERecipient(Document):
    def autoname(self):
        source = f"{self.line_channel}:{self.recipient_type}:{self.recipient_id}"
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:20].upper()
        self.name = f"LINE-REC-{digest}"

    def validate(self):
        self.recipient_id = (self.recipient_id or "").strip()
        if not self.recipient_id:
            frappe.throw("Recipient ID is required")
        if self.recipient_type == "User":
            self.line_user_id = self.recipient_id
        else:
            self.line_user_id = None
