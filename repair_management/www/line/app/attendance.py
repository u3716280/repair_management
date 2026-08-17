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
        fields=["channel_name", "mini_app_channel_id", "mini_app_liff_id"],
        order_by="channel_name",
    )

    # Multiple LINE Channel rows (distinct bots/webhooks) may legitimately
    # share one MINI App identity -- only fail when enabled channels disagree
    # on which LIFF app to open. Which single row is picked as the entry
    # point doesn't matter: authenticate() checks recipients across every
    # enabled channel sharing that identity, not just this one.
    identities = {(row.mini_app_channel_id, row.mini_app_liff_id) for row in channels}
    if len(identities) != 1:
        context.mini_app_configured = False
        context.channel_name = ""
        context.liff_id = ""
        return context

    context.mini_app_configured = True
    context.channel_name = channels[0].channel_name
    context.liff_id = channels[0].mini_app_liff_id
    return context
