from __future__ import annotations

import hashlib

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class LINERecipient(Document):
    def autoname(self):
        source = f"{self.line_channel}:{self.recipient_type}:{self.recipient_id}"
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:20].upper()
        self.name = f"LINE-REC-{digest}"

    def validate(self):
        self.line_channel = (self.line_channel or "").strip()
        self.recipient_type = (self.recipient_type or "").strip()
        self.recipient_id = (self.recipient_id or "").strip()

        if not self.line_channel:
            frappe.throw("LINE Channel is required")

        if not self.recipient_type:
            frappe.throw("Recipient Type is required")

        if not self.recipient_id:
            frappe.throw("Recipient ID is required")

        if self.recipient_type == "User":
            self.line_user_id = self.recipient_id
        else:
            self.line_user_id = None

        self._prevent_duplicate_identity()

    def _prevent_duplicate_identity(self):
        """Prevent new/active duplicate records for the same LINE identity.

        This also protects manual creation and API writes outside the webhook
        upsert path.  Disabled legacy duplicates may remain for historical
        cleanup, but they cannot be re-enabled while another active identity
        exists.
        """
        rows = frappe.get_all(
            "LINE Recipient",
            filters={
                "line_channel": self.line_channel,
                "recipient_type": self.recipient_type,
                "recipient_id": self.recipient_id,
                "name": ["!=", self.name or ""],
            },
            fields=["name", "enabled"],
            limit_page_length=0,
        )

        if self.recipient_type == "User":
            legacy_rows = frappe.get_all(
                "LINE Recipient",
                filters={
                    "line_channel": self.line_channel,
                    "recipient_type": "User",
                    "line_user_id": self.recipient_id,
                    "name": ["!=", self.name or ""],
                },
                fields=["name", "enabled"],
                limit_page_length=0,
            )

            seen = {row.name for row in rows}
            rows.extend(row for row in legacy_rows if row.name not in seen)

        if not rows:
            return

        # A brand-new document must never create a second identity, even when
        # the existing legacy record is disabled. The webhook upsert will reuse
        # that existing record instead.
        if self.is_new():
            frappe.throw(
                "LINE Recipient already exists for this Channel / Type / Recipient ID."
            )

        # Existing disabled legacy duplicates can still be edited for cleanup,
        # but they cannot be enabled when another active record exists.
        active_duplicates = [row.name for row in rows if cint(row.enabled)]
        if cint(self.enabled) and active_duplicates:
            frappe.throw(
                "Another enabled LINE Recipient already exists for this LINE identity: "
                + ", ".join(active_duplicates)
            )
