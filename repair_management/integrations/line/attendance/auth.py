from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import frappe
import requests

LINE_ID_TOKEN_VERIFY_URL = "https://api.line.me/oauth2/v2.1/verify"


@dataclass(frozen=True)
class AttendanceAuthContext:
    channel_name: str
    integration_user: str
    default_company: str
    recipient_name: str
    line_user_id: str


def _get_channel(channel_name: str):
    if not channel_name:
        frappe.throw("LINE MINI App configuration is missing.", frappe.ValidationError)

    channel = frappe.db.get_value(
        "LINE Channel",
        channel_name,
        [
            "name",
            "enabled",
            "integration_user",
            "default_company",
            "mini_app_channel_id",
            "mini_app_liff_id",
        ],
        as_dict=True,
    )
    if not channel or not channel.enabled:
        frappe.throw("LINE Channel is not available.", frappe.PermissionError)
    if not channel.mini_app_channel_id or not channel.mini_app_liff_id:
        frappe.throw("LINE MINI App configuration is incomplete.", frappe.ValidationError)
    if not channel.integration_user or not channel.default_company:
        frappe.throw("LINE attendance configuration is incomplete.", frappe.ValidationError)
    return channel


def _verify_id_token(id_token: str, mini_app_channel_id: str) -> dict:
    if not id_token:
        frappe.throw("LINE Login is required.", frappe.AuthenticationError)

    try:
        response = requests.post(
            LINE_ID_TOKEN_VERIFY_URL,
            data={"id_token": id_token, "client_id": mini_app_channel_id},
            timeout=10,
        )
    except requests.RequestException:
        frappe.throw("Unable to verify LINE Login.", frappe.AuthenticationError)

    if response.status_code != 200:
        frappe.throw("LINE Login verification failed.", frappe.AuthenticationError)

    payload = response.json()
    if not payload.get("sub"):
        frappe.throw("LINE Login verification failed.", frappe.AuthenticationError)
    return payload


def _sibling_channel_names(channel) -> list[str]:
    """All enabled LINE Channel rows configured as the same shared MINI App.

    Multiple LINE Channel rows (distinct bots/webhooks) can point at the same
    LINE Login/LIFF app. A LINE Recipient may be registered under any one of
    them, so authorization must not be scoped to only the single channel row
    that happened to be selected as the MINI App's entry point.
    """
    return frappe.get_all(
        "LINE Channel",
        filters={
            "enabled": 1,
            "mini_app_channel_id": channel.mini_app_channel_id,
            "mini_app_liff_id": channel.mini_app_liff_id,
        },
        pluck="name",
    )


def _get_authorized_recipient(channel_names: list[str], line_user_id: str):
    recipients = frappe.get_all(
        "LINE Recipient",
        filters={
            "line_channel": ["in", channel_names],
            "recipient_type": "User",
            "enabled": 1,
            "allow_mark_attendance": 1,
        },
        or_filters={"line_user_id": line_user_id, "recipient_id": line_user_id},
        fields=["name", "line_channel", "line_user_id", "recipient_id"],
        order_by="last_seen_at desc, modified desc",
        limit_page_length=0,
    )
    if not recipients:
        frappe.throw("ไม่มีสิทธิ์ใช้งาน", frappe.PermissionError)

    if len(recipients) > 1:
        # The same physical LINE identity can end up with a separate `LINE
        # Recipient` row per sibling channel (each channel's webhook upserts
        # its own row independently -- see services/recipient.py). Rather
        # than block the user from marking attendance, resolve to the most
        # recently active row, mirroring the dedup strategy already used in
        # services/recipient.py::_existing_recipient, and log it so the
        # duplicate rows can be cleaned up.
        frappe.log_error(
            title="Duplicate LINE Recipient for attendance",
            message=frappe.as_json(
                {
                    "line_user_id": line_user_id,
                    "channel_names": channel_names,
                    "chosen": recipients[0].name,
                    "duplicates": [r.name for r in recipients],
                }
            ),
        )

    return recipients[0]


def authenticate(id_token: str, channel_name: str) -> AttendanceAuthContext:
    channel = _get_channel(channel_name)
    payload = _verify_id_token(id_token, channel.mini_app_channel_id)
    line_user_id = payload["sub"]

    recipient = _get_authorized_recipient(_sibling_channel_names(channel), line_user_id)

    if not frappe.db.get_value("User", channel.integration_user, "enabled"):
        frappe.throw("LINE Integration User is disabled.", frappe.PermissionError)

    return AttendanceAuthContext(
        channel_name=channel.name,
        integration_user=channel.integration_user,
        default_company=channel.default_company,
        recipient_name=recipient.name,
        line_user_id=line_user_id,
    )


@contextmanager
def as_integration_user(auth: AttendanceAuthContext):
    previous_user = frappe.session.user
    frappe.set_user(auth.integration_user)
    try:
        yield
    finally:
        frappe.set_user(previous_user)
