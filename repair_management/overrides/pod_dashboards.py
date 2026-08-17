from __future__ import annotations


def _ensure_transaction(data, label, item):
    transactions = data.setdefault("transactions", [])
    for group in transactions:
        if group.get("label") == label:
            items = group.setdefault("items", [])
            if item not in items:
                items.append(item)
            return data
    transactions.append({"label": label, "items": [item]})
    return data


def sales_order_dashboard(data):
    data.setdefault("non_standard_fieldnames", {})["Delivery Confirmation"] = "sales_order"
    return _ensure_transaction(data, "Proof of Delivery", "Delivery Confirmation")


def delivery_note_dashboard(data):
    data.setdefault("non_standard_fieldnames", {})["Delivery Confirmation"] = "delivery_note"
    return _ensure_transaction(data, "Proof of Delivery", "Delivery Confirmation")
