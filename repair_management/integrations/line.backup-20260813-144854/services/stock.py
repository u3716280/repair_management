from __future__ import annotations

import frappe


DEFAULT_CANDIDATE_LIMIT = 100


def _candidate_limit(config):
    for fieldname in ("maximum_results", "max_results", "candidate_limit"):
        value = getattr(config, fieldname, None)
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return min(value, 500)
    return DEFAULT_CANDIDATE_LIMIT


def _unique_sorted_item_codes(item_codes):
    return sorted({code for code in item_codes if code}, key=lambda value: str(value))


def _get_items(item_codes):
    item_codes = _unique_sorted_item_codes(item_codes)
    if not item_codes:
        return []
    rows = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes], "disabled": 0},
        fields=["name", "item_name", "item_group", "stock_uom"],
        order_by="name asc",
        limit_page_length=0,
    )
    by_name = {row.name: row for row in rows}
    return [by_name[name] for name in item_codes if name in by_name]


def search_item_groups(keyword, limit=50):
    """Return Item Group candidates ranked Exact -> Starts With -> Contains."""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    rows = frappe.get_all(
        "Item Group",
        filters={"name": ["like", f"%{keyword}%"]},
        fields=["name", "parent_item_group", "is_group", "lft", "rgt"],
        limit_page_length=min(max(int(limit or 50), 1), 200),
    )

    needle = keyword.casefold()

    def rank(row):
        name = (row.name or "").casefold()
        if name == needle:
            bucket = 0
        elif name.startswith(needle):
            bucket = 1
        else:
            bucket = 2
        return bucket, row.name or ""

    return sorted(rows, key=rank)


def expand_item_group(group_name):
    """Return the selected Item Group plus all descendants using Nested Set lft/rgt."""
    if not group_name or not frappe.db.exists("Item Group", group_name):
        return []

    group = frappe.db.get_value(
        "Item Group",
        group_name,
        ["lft", "rgt"],
        as_dict=True,
    )
    if not group or group.lft is None or group.rgt is None:
        return [group_name]

    return frappe.get_all(
        "Item Group",
        filters={
            "lft": [">=", group.lft],
            "rgt": ["<=", group.rgt],
        },
        pluck="name",
        order_by="lft asc",
        limit_page_length=0,
    )


def items_for_groups(config, group_names):
    group_names = list(dict.fromkeys(group_names or []))
    if not group_names:
        return []
    return frappe.get_all(
        "Item",
        filters={
            "disabled": 0,
            "item_group": ["in", group_names],
        },
        fields=["name", "item_name", "item_group", "stock_uom"],
        order_by="name asc",
        limit_page_length=_candidate_limit(config),
    )


def search(config, kind, keyword):
    """Search Item candidates.

    Item Group selection itself is handled separately by search_item_groups();
    this function keeps the existing interface used by stock_query.py.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return [], None

    fields = ["name", "item_name", "item_group", "stock_uom"]
    limit = _candidate_limit(config)
    serial = None

    if kind == "item_group":
        # The flow must first resolve an Item Group candidate, then call
        # items_for_groups() with the selected group + descendants.
        return [], None

    if kind == "item_code":
        rows = frappe.get_all(
            "Item",
            filters={"disabled": 0, "name": ["like", f"%{keyword}%"]},
            fields=fields,
            order_by="name asc",
            limit_page_length=limit,
        )
        return rows, None

    if kind == "item_name":
        rows = frappe.get_all(
            "Item",
            filters={"disabled": 0, "item_name": ["like", f"%{keyword}%"]},
            fields=fields,
            order_by="name asc",
            limit_page_length=limit,
        )
        return rows, None

    # "any": Item Code + Item Name + Item Group + Serial No.
    rows = frappe.get_all(
        "Item",
        filters={"disabled": 0},
        or_filters=[
            ["Item", "name", "like", f"%{keyword}%"],
            ["Item", "item_name", "like", f"%{keyword}%"],
            ["Item", "item_group", "like", f"%{keyword}%"],
        ],
        fields=fields,
        order_by="name asc",
        limit_page_length=limit,
    )

    item_codes = [row.name for row in rows]
    serial_rows = frappe.get_all(
        "Serial No",
        filters={"name": ["like", f"%{keyword}%"]},
        fields=["name", "item_code"],
        order_by="name asc",
        limit_page_length=limit,
    )
    if serial_rows:
        serial = serial_rows[0].name
        item_codes.extend(row.item_code for row in serial_rows if row.item_code)

    return _get_items(item_codes)[:limit], serial


def detail(config, item_code):
    if not item_code or not frappe.db.exists("Item", item_code):
        return None

    item = frappe.get_doc("Item", item_code)
    if item.disabled:
        return None

    warehouse_filters = {"disabled": 0}
    default_company = getattr(config, "default_company", None)
    if default_company:
        warehouse_filters["company"] = default_company

    warehouses = frappe.get_all(
        "Warehouse",
        filters=warehouse_filters,
        pluck="name",
        order_by="name asc",
        limit_page_length=0,
    )

    bins = []
    if warehouses:
        bins = frappe.get_all(
            "Bin",
            filters={
                "item_code": item_code,
                "warehouse": ["in", warehouses],
            },
            fields=["warehouse", "actual_qty"],
            order_by="warehouse asc",
            limit_page_length=0,
        )

    show_purchase = bool(getattr(config, "show_purchase_price", 0))
    show_selling = bool(getattr(config, "show_selling_price", 0))
    selling_price_list = getattr(config, "selling_price_list", None)

    selling_rate = None
    if show_selling and selling_price_list:
        selling_rate = frappe.db.get_value(
            "Item Price",
            {
                "item_code": item_code,
                "price_list": selling_price_list,
                "selling": 1,
            },
            "price_list_rate",
            order_by="valid_from desc, modified desc",
        )

    return {
        "item_code": item.name,
        "item_name": item.item_name,
        "item_group": item.item_group,
        "stock_uom": item.stock_uom,
        "warehouses": [dict(row) for row in bins],
        "total_actual_qty": sum(float(row.actual_qty or 0) for row in bins),
        "purchase_rate": (
            item.last_purchase_rate or item.valuation_rate
        ) if show_purchase else None,
        "selling_rate": selling_rate,
    }
