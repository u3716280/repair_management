from __future__ import annotations

import frappe

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False
    context.liff_id = _resolve_liff_id()
    return context


def _resolve_liff_id() -> str:
    try:
        from repair_management.integrations.line.delivery_confirmation.api import config

        return config().get("liff_id") or ""
    except Exception:
        return ""
