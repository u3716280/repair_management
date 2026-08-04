
from __future__ import annotations

import frappe
from frappe.utils import get_url


def migrate_legacy_settings():
    """Create the first LINE Account from legacy single-account LINE Settings."""
    settings = frappe.get_single("LINE Settings")

    if settings.default_line_account and frappe.db.exists("LINE Account", settings.default_line_account):
        account = frappe.get_doc("LINE Account", settings.default_line_account)
        return {
            "status": "already_migrated",
            "line_account": account.name,
            "webhook_url": account.webhook_url,
        }

    secret = settings.get_password("channel_secret")
    token = settings.get_password("channel_access_token")
    if not secret or not token:
        return {
            "status": "skipped",
            "reason": "Legacy Channel Secret or Channel Access Token is empty",
        }

    account_name = "LINE-DEFAULT"
    if frappe.db.exists("LINE Account", account_name):
        account = frappe.get_doc("LINE Account", account_name)
    else:
        account = frappe.get_doc(
            {
                "doctype": "LINE Account",
                "account_code": account_name,
                "account_name": "Default LINE Official Account",
                "enabled": 1,
                "channel_secret": secret,
                "channel_access_token": token,
                "delivery_postback_action": settings.delivery_postback_action or "job_status",
                "session_expiry_minutes": settings.session_expiry_minutes or 15,
                "log_payload": settings.log_payload,
            }
        )
        account.insert(ignore_permissions=True)

    settings.default_line_account = account.name
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "status": "migrated",
        "line_account": account.name,
        "webhook_key": account.webhook_key,
        "webhook_url": account.webhook_url
        or f"{get_url()}/api/method/repair_management.integrations.line.webhook.callback?account={account.webhook_key}",
    }
