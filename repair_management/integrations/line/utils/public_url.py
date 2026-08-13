from __future__ import annotations

import frappe
from frappe.utils import get_url


def public_base_url():
    conf = frappe.local.conf
    base = conf.get("google_redirect_base_url") or conf.get("host_name")
    if base:
        return str(base).rstrip("/")
    return get_url().rstrip("/")
