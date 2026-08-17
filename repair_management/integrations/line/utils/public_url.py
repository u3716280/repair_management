from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe.utils import get_url


def get_public_base_url(channel=None):
    """Return the externally reachable base URL for LINE integration.

    Compatibility order retained from the existing LINE integration:
    1. google_redirect_base_url
    2. LINE Channel.public_base_url (when supplied)
    3. host_name
    4. frappe.utils.get_url()
    """
    configured_channel_url = None
    if channel is not None:
        try:
            configured_channel_url = channel.get("public_base_url")
        except AttributeError:
            configured_channel_url = getattr(channel, "public_base_url", None)

    base = (
        frappe.conf.get("google_redirect_base_url")
        or configured_channel_url
        or frappe.conf.get("host_name")
        or get_url()
    )
    return str(base).rstrip("/")


def public_base_url(channel=None):
    """Alias used by signed LINE media URLs."""
    return get_public_base_url(channel)


def get_webhook_url(channel):
    """Build the current LINE webhook endpoint URL for a LINE Channel."""
    if channel is None or not getattr(channel, "name", None):
        frappe.throw("LINE Channel is required to build webhook URL")

    return (
        f"{get_public_base_url(channel)}/api/method/"
        "repair_management.integrations.line.webhook.endpoint.handle"
        f"?channel={quote(str(channel.name), safe='')}"
    )
