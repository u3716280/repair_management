
from __future__ import annotations

import frappe
from frappe.model.document import Document


class LINEForwardRoute(Document):
    def validate(self):
        if self.enabled and not any(row.enabled for row in self.targets):
            frappe.throw("At least one enabled LINE Forward Route Target is required")
