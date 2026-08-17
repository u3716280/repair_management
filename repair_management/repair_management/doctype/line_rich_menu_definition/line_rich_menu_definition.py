from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document


_ALIAS_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class LINERichMenuDefinition(Document):
    def validate(self):
        self._validate_alias_id()

    def _validate_alias_id(self):
        alias_id = (self.alias_id or "").strip()
        self.alias_id = alias_id

        if not alias_id:
            return

        if not _ALIAS_RE.fullmatch(alias_id):
            frappe.throw(
                _(
                    "Alias ID must be 1-32 characters and contain only "
                    "lowercase a-z, 0-9, underscore (_) or hyphen (-)."
                )
            )

        duplicate = frappe.db.exists(
            "LINE Rich Menu Definition",
            {
                "line_channel": self.line_channel,
                "alias_id": alias_id,
                "name": ["!=", self.name or ""],
            },
        )
        if duplicate:
            frappe.throw(
                _("Alias ID {0} is already used by Rich Menu Definition {1} in this LINE Channel.").format(
                    frappe.bold(alias_id),
                    frappe.bold(duplicate),
                )
            )
