import frappe
from frappe.model.document import Document


class LINERichMenuRecipientAssignment(Document):
    def validate(self):
        if not self.recipient:
            return
        channel_link = frappe.get_doc("LINE Recipient Channel", self.recipient)
        recipient_type = frappe.db.get_value("LINE Recipient", channel_link.line_recipient, "recipient_type")
        if recipient_type != "User":
            frappe.throw("Per-user Rich Menu can only be assigned to a User recipient")
        self.line_channel = channel_link.line_channel
        self.line_user_id = channel_link.recipient_id
        self.recipient_name = channel_link.display_name
