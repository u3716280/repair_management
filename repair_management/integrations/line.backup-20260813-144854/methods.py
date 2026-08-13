import frappe
from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.utils.public_url import get_webhook_url
@frappe.whitelist()
def verify_connection(channel_name):
    c=frappe.get_doc("LINE Channel",channel_name);r=LineClient(c.name).verify();c.db_set({"webhook_url":get_webhook_url(c),"webhook_verification_status":"Connection OK","last_verified_at":frappe.utils.now_datetime()});return r
