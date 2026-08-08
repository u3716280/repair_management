from urllib.parse import quote
import frappe

def get_public_base_url(channel=None):
    return str(frappe.conf.get("google_redirect_base_url") or (channel and channel.get("public_base_url")) or frappe.conf.get("host_name") or frappe.utils.get_url()).rstrip("/")

def get_webhook_url(channel):
    return f"{get_public_base_url(channel)}/api/method/repair_management.integrations.line.webhook.endpoint.handle?channel={quote(channel.name,safe='')}"
