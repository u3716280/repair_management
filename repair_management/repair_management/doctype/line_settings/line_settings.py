
from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class LINESettings(Document):
    def validate(self):
        if cint(self.signed_url_expiry_seconds or 0) < 300:
            self.signed_url_expiry_seconds = 3600
        if not self.background_queue:
            self.background_queue = "short"
        if not self.media_signing_secret:
            self.media_signing_secret = frappe.generate_hash(length=48)
