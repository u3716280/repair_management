from __future__ import annotations

import hashlib

import frappe
from frappe.model.document import Document


class LINERecipientChannel(Document):
    def autoname(self):
        source = f"{self.line_recipient}:{self.line_channel}"
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:20].upper()
        self.name = f"LINE-RC-{digest}"

    def validate(self):
        self.line_recipient = (self.line_recipient or "").strip()
        self.line_channel = (self.line_channel or "").strip()

        if not self.line_recipient:
            frappe.throw("LINE Recipient is required")
        if not self.line_channel:
            frappe.throw("LINE Channel is required")
