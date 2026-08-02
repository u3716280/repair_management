from __future__ import annotations

import frappe
from frappe.model.document import Document


class LINESettings(Document):
    def validate(self):
        if self.enabled:
            if not self.channel_secret:
                frappe.throw("Channel Secret is required when LINE integration is enabled")
            if not self.channel_access_token:
                frappe.throw("Channel Access Token is required when LINE integration is enabled")

        if int(self.session_expiry_minutes or 0) < 1:
            self.session_expiry_minutes = 15

        if not self.delivery_postback_action:
            self.delivery_postback_action = "delivery_complete_request"
