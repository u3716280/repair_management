from __future__ import annotations

import frappe

no_cache = 1


def get_context(context):
    context.no_cache = 1
    channels = frappe.get_all(
        "LINE Channel",
        filters={
            "enabled": 1,
            "mini_app_channel_id": ["is", "set"],
            "mini_app_liff_id": ["is", "set"],
            "default_company": ["is", "set"],
        },
        fields=["channel_name", "mini_app_liff_id"],
        order_by="modified desc",
        limit_page_length=2,
    )

    if len(channels) != 1:
        context.mini_app_configured = False
        context.channel_name = ""
        context.liff_id = ""
        return context

    context.mini_app_configured = True
    context.channel_name = channels[0].channel_name
    context.liff_id = channels[0].mini_app_liff_id
    return context
