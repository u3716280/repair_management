import frappe


def dispatch(action, channel, user_id, reply_token, params=None, event=None):
    name = frappe.db.get_value(
        "LINE Action Registry",
        {"action_key": action, "enabled": 1},
        "name",
    )
    if not name:
        return None

    action_doc = frappe.get_doc("LINE Action Registry", name)
    flow = frappe.get_doc("LINE Business Flow", action_doc.business_flow)
    if not flow.enabled:
        return None

    handler_path = flow.handler_path or action_doc.handler_path
    if not handler_path:
        frappe.throw(f"No handler configured for Business Flow: {flow.flow_name}")

    return frappe.get_attr(handler_path)(
        channel=channel,
        user_id=user_id,
        reply_token=reply_token,
        flow=flow,
        params=params or {},
        event=event,
    )
