import frappe
from frappe.model.document import Document


class LINERichMenuRecipientAssignment(Document):
    def validate(self):
        if not self.recipient:
            return
        recipient = frappe.get_doc("LINE Recipient", self.recipient)
        if recipient.recipient_type != "User":
            frappe.throw("Per-user Rich Menu can only be assigned to a User recipient")
        self.line_channel = recipient.line_channel
        self.line_user_id = recipient.recipient_id
        self.recipient_name = recipient.display_name
