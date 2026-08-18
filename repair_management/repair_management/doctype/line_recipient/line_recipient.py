from __future__ import annotations

import frappe
from frappe.model.document import Document


class LINERecipient(Document):
    """One row per physical LINE person (User/Group/Room), identity only.

    Per-channel relationship data (follow status, rich menu state) lives on
    `LINE Recipient Channel` instead -- see that doctype's docstring. Naming is
    `field:recipient_id` (set in the JSON): LINE user/group/room IDs are
    already globally unique and namespace-prefixed by LINE itself, so no
    hashing is needed here, unlike LINE Recipient Channel's composite key.
    """

    def validate(self):
        self.recipient_type = (self.recipient_type or "").strip()
        self.recipient_id = (self.recipient_id or "").strip()

        if not self.recipient_type:
            frappe.throw("Recipient Type is required")
        if not self.recipient_id:
            frappe.throw("Recipient ID is required")
        if not self.is_new() and self.recipient_id != self.name:
            frappe.throw("Recipient ID cannot be changed after creation")

        if self.recipient_type == "User":
            self.line_user_id = self.recipient_id
        else:
            self.line_user_id = None
