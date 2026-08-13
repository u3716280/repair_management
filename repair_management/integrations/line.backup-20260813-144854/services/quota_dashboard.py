from __future__ import annotations

from typing import Any

import frappe
import requests

QUOTA_URL = "https://api.line.me/v2/bot/message/quota"
CONSUMPTION_URL = "https://api.line.me/v2/bot/message/quota/consumption"
TIMEOUT_SECONDS = 10


def _channel_from_filters(filters: Any = None) -> str:
    """Resolve LINE Channel name from Number Card filters without trusting arbitrary DocTypes."""
    if isinstance(filters, str):
        try:
            filters = frappe.parse_json(filters)
        except Exception:
            filters = None

    if isinstance(filters, dict):
        value = filters.get("name") or filters.get("line_channel") or filters.get("channel")
        if value:
            return str(value)

    if isinstance(filters, (list, tuple)):
        for row in filters:
            if isinstance(row, dict):
                fieldname = row.get("fieldname") or row.get("field")
                value = row.get("value")
                if fieldname in {"name", "line_channel", "channel"} and value:
                    return str(value)
            elif isinstance(row, (list, tuple)):
                # Typical Frappe filter shapes:
                # ["LINE Channel", "name", "=", "ErpNext Server"]
                # ["name", "=", "ErpNext Server"]
                if len(row) >= 4 and row[0] == "LINE Channel" and row[1] == "name" and row[3]:
                    return str(row[3])
                if len(row) >= 3 and row[0] == "name" and row[2]:
                    return str(row[2])

    channels = frappe.get_all("LINE Channel", pluck="name", order_by="name asc", limit_page_length=2)
    if len(channels) == 1:
        return channels[0]

    frappe.throw("LINE Channel is required for Message Quota dashboard card")


def _get_channel(channel_name: str):
    if not frappe.db.exists("LINE Channel", channel_name):
        frappe.throw(f"LINE Channel not found: {channel_name}")

    if not frappe.has_permission("LINE Channel", "read"):
        frappe.throw("Not permitted to read LINE Channel", frappe.PermissionError)

    return frappe.get_doc("LINE Channel", channel_name)


def _get_access_token(channel) -> str:
    meta = frappe.get_meta("LINE Channel")
    candidates = ("channel_access_token", "access_token")

    for fieldname in candidates:
        df = meta.get_field(fieldname)
        if not df:
            continue

        value = None
        if df.fieldtype == "Password":
            try:
                value = channel.get_password(fieldname)
            except Exception:
                value = None
        else:
            value = channel.get(fieldname)

        if value:
            return str(value)

    frappe.throw(
        "LINE Channel Access Token is not configured. Expected field: channel_access_token or access_token"
    )


def _get_json(channel_name: str, url: str) -> dict[str, Any]:
    channel = _get_channel(channel_name)
    token = _get_access_token(channel)

    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise frappe.ValidationError(f"LINE Messaging API request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = (response.text or "").strip()[:500]
        raise frappe.ValidationError(
            f"LINE Messaging API returned HTTP {response.status_code}: {detail or 'No response body'}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise frappe.ValidationError("LINE Messaging API returned invalid JSON") from exc


def get_quota_snapshot(channel_name: str) -> dict[str, Any]:
    quota = _get_json(channel_name, QUOTA_URL)
    consumption = _get_json(channel_name, CONSUMPTION_URL)

    quota_type = quota.get("type")
    limit_value = quota.get("value") if quota_type == "limited" else None
    used = int(consumption.get("totalUsage") or 0)

    remaining = None
    usage_percent = None
    if limit_value is not None:
        limit_value = int(limit_value)
        remaining = max(limit_value - used, 0)
        usage_percent = (used / limit_value * 100.0) if limit_value > 0 else 0.0

    return {
        "channel": channel_name,
        "quota_type": quota_type,
        "limit": limit_value,
        "used": used,
        "remaining": remaining,
        "usage_percent": usage_percent,
    }


def _safe_snapshot(filters=None):
    channel_name = _channel_from_filters(filters)
    try:
        return get_quota_snapshot(channel_name)
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"LINE Message Quota: {channel_name}")
        return {
            "channel": channel_name,
            "quota_type": None,
            "limit": None,
            "used": None,
            "remaining": None,
            "usage_percent": None,
        }


def _route(channel_name: str):
    return {
        "route": ["Form", "LINE Channel", channel_name],
    }


@frappe.whitelist()
def quota_limit(filters=None):
    data = _safe_snapshot(filters)
    return {
        "value": data["limit"],
        "fieldtype": "Int",
        **_route(data["channel"]),
    }


@frappe.whitelist()
def quota_used(filters=None):
    data = _safe_snapshot(filters)
    return {
        "value": data["used"],
        "fieldtype": "Int",
        **_route(data["channel"]),
    }


@frappe.whitelist()
def quota_remaining(filters=None):
    data = _safe_snapshot(filters)
    return {
        "value": data["remaining"],
        "fieldtype": "Int",
        **_route(data["channel"]),
    }


@frappe.whitelist()
def quota_usage_percent(filters=None):
    data = _safe_snapshot(filters)
    return {
        "value": data["usage_percent"],
        "fieldtype": "Percent",
        "precision": 1,
        **_route(data["channel"]),
    }


@frappe.whitelist()
def check(channel: str | None = None):
    if not channel:
        channels = frappe.get_all("LINE Channel", pluck="name", order_by="name asc", limit_page_length=0)
        return {name: get_quota_snapshot(name) for name in channels}
    return get_quota_snapshot(channel)
