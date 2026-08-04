from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cint, get_url


class LINEAccount(Document):
    def validate(self):
        if not self.webhook_key:
            self.webhook_key = frappe.generate_hash(length=20)
        if not self.delivery_postback_action:
            self.delivery_postback_action = "job_status"
        if cint(self.session_expiry_minutes or 0) < 1:
            self.session_expiry_minutes = 15
        if cint(self.pending_media_expiry_hours or 0) < 1:
            self.pending_media_expiry_hours = 24
        if self.enabled and (not self.channel_secret or not self.channel_access_token):
            frappe.throw("Channel Secret and Channel Access Token are required for an enabled LINE Account")

        self._validate_postback_actions()

        configured_host = None
        if getattr(frappe, "conf", None):
            configured_host = (
                frappe.conf.get("google_redirect_base_url")
                or frappe.conf.get("host_name")
            )
        base_url = (configured_host or get_url()).rstrip("/")
        self.webhook_url = (
            f"{base_url}/api/method/repair_management.integrations.line.webhook.callback"
            f"?account={self.webhook_key}"
        )

    def _validate_postback_actions(self):
        seen = set()
        for row in self.get("postback_actions") or []:
            code = (row.action_code or "").strip()
            if not code:
                frappe.throw(f"Postback Action row {row.idx}: Action Code is required")
            if code in {"classify_media", "discard_media"}:
                frappe.throw(f"Postback Action {code} is reserved by the system")
            if code in seen:
                frappe.throw(f"Duplicate Postback Action Code: {code}")
            seen.add(code)

            row.action_code = code
            if not row.action_label:
                row.action_label = code
            if not row.confirmation_type:
                row.confirmation_type = "Delivery"
            if cint(row.session_expiry_minutes or 0) < 1:
                row.session_expiry_minutes = self.session_expiry_minutes or 15
            if row.require_reference and not row.reference_doctype:
                frappe.throw(
                    f"Postback Action {code}: Reference DocType is required when Require Reference is enabled"
                )
