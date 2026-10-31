# Copyright (c) 2026, Chirayut D. and contributors
# For license information, please see license.txt

"""Multi-year Sales Invoice Trends.

Amounts are base currency, net of item-level discounts. Submitted invoices only;
returns/credit notes are included (as negative values) unless switched off.
Company Total uses invoice-level base_net_total unless item filters are active,
in which case only matching invoice lines are counted.
"""

from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

PERIODS = {"Monthly", "Quarterly", "Half-Yearly", "Yearly"}
GROUPS = {"Company Total", "Customer", "Customer Group", "Territory", "Item", "Item Group"}
VALUES = {"Sales Amount", "Quantity"}
MAX_YEARS = 20

# filter fieldname -> (table alias, tree doctype)
TREE_FILTERS = {
	"customer_group": ("si", "Customer Group"),
	"territory": ("si", "Territory"),
	"item_group": ("sii", "Item Group"),
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	periods = get_periods(getdate(filters.from_date), getdate(filters.to_date), filters.period)
	show_yoy = bool(cint(filters.get("show_yoy")))
	is_amount = filters.value_type == "Sales Amount"
	currency = frappe.get_cached_value("Company", filters.company, "default_currency") or ""

	# Item-level rows are needed for item grouping/filtering and for quantity.
	use_items = (
		filters.group_by in {"Item", "Item Group"}
		or not is_amount
		or filters.get("item_code")
		or filters.get("item_group")
	)
	records = fetch_items(filters) if use_items else fetch_invoices(filters)

	totals = defaultdict(float)
	overall = defaultdict(float)
	all_groups = set()
	for rec in records:
		p = get_period_key(getdate(rec.posting_date), filters.period)
		group = get_group_name(rec, filters.group_by)
		value = flt(rec.amount if is_amount else rec.qty)
		totals[(group, p)] += value
		overall[p] += value
		all_groups.add(group)

	columns = get_columns(filters, is_amount, show_yoy)
	data = []
	period_set = set(periods)
	for group in sorted(all_groups):
		for p in periods:
			row = {
				"group": group,
				"period": get_period_label(p, filters.period),
				"value": totals[(group, p)],
				"currency": currency,
			}
			if show_yoy:
				previous = (p[0] - 1, p[1])
				# Only compare against last year's period if it is inside the selected range.
				prev_val = totals[(group, previous)] if previous in period_set else 0
				row["yoy"] = (row["value"] - prev_val) / abs(prev_val) * 100 if prev_val else None
			data.append(row)

	precision = 2 if is_amount else 3
	value_fieldtype = "Currency" if is_amount else "Float"
	chart = {
		"data": {
			"labels": [get_period_label(p, filters.period) for p in periods],
			"datasets": [
				{
					"name": _(filters.value_type),
					"values": [flt(overall[p], precision) for p in periods],
				}
			],
		},
		"type": "bar" if filters.period == "Yearly" else "line",
		"fieldtype": value_fieldtype,
	}
	summary = [
		{
			"label": _("Total") if is_amount else _("Total Quantity"),
			"value": flt(sum(overall.values()), precision),
			"indicator": "Blue",
			"datatype": value_fieldtype,
			**({"currency": currency} if is_amount else {}),
		}
	]
	return columns, data, None, chart, summary


def get_columns(filters, is_amount, show_yoy):
	columns = [
		{"fieldname": "group", "label": _(filters.group_by), "fieldtype": "Data", "width": 220},
		{"fieldname": "period", "label": _("Period"), "fieldtype": "Data", "width": 130},
	]
	if is_amount:
		columns.append(
			{
				"fieldname": "currency",
				"label": _("Currency"),
				"fieldtype": "Link",
				"options": "Currency",
				"hidden": 1,
			}
		)
		columns.append(
			{
				"fieldname": "value",
				"label": _("Sales Amount"),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 165,
			}
		)
	else:
		columns.append({"fieldname": "value", "label": _("Quantity"), "fieldtype": "Float", "width": 165})
	if show_yoy:
		columns.append(
			{"fieldname": "yoy", "label": _("YoY Change (%)"), "fieldtype": "Percent", "width": 145}
		)
	return columns


def validate_filters(f):
	for field in ("company", "from_date", "to_date", "period", "group_by", "value_type"):
		if not f.get(field):
			frappe.throw(_("Missing required filter: {0}").format(field))
	if getdate(f.from_date) > getdate(f.to_date):
		frappe.throw(_("From Date must be on or before To Date"))
	if f.period not in PERIODS or f.group_by not in GROUPS or f.value_type not in VALUES:
		frappe.throw(_("Invalid report option"))
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(_("Not permitted to read Sales Invoices"), frappe.PermissionError)
	if not frappe.has_permission("Company", "read", f.company):
		frappe.throw(_("Not permitted to access this company"), frappe.PermissionError)
	if (getdate(f.to_date) - getdate(f.from_date)).days > 365 * MAX_YEARS + 5:
		frappe.throw(_("Select a date range of {0} years or less").format(MAX_YEARS))


def get_conditions(f, item_mode):
	conditions = [
		"si.docstatus = 1",
		"si.company = %(company)s",
		"si.posting_date BETWEEN %(from_date)s AND %(to_date)s",
	]
	if not cint(f.get("include_returns")):
		conditions.append("si.is_return = 0")
	if f.get("customer"):
		conditions.append("si.customer = %(customer)s")
	if item_mode and f.get("item_code"):
		conditions.append("sii.item_code = %(item_code)s")
	for field, (alias, doctype) in TREE_FILTERS.items():
		if not f.get(field) or (alias == "sii" and not item_mode):
			continue
		# Include all descendants of the selected tree node.
		conditions.append(
			f"""{alias}.{field} IN (
				SELECT child.name FROM `tab{doctype}` child, `tab{doctype}` parent
				WHERE parent.name = %({field})s AND child.lft >= parent.lft AND child.rgt <= parent.rgt
			)"""
		)
	return " AND ".join(conditions)


def fetch_invoices(f):
	return frappe.db.sql(
		f"""
		SELECT si.posting_date, si.customer, si.customer_group, si.territory,
			si.base_net_total AS amount, 0 AS qty,
			'' AS item_code, '' AS item_group
		FROM `tabSales Invoice` si
		WHERE {get_conditions(f, False)}
		""",
		f,
		as_dict=True,
	)


def fetch_items(f):
	return frappe.db.sql(
		f"""
		SELECT si.posting_date, si.customer, si.customer_group, si.territory,
			sii.item_code, sii.item_group,
			sii.base_net_amount AS amount, sii.qty AS qty
		FROM `tabSales Invoice` si
		INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE {get_conditions(f, True)}
		""",
		f,
		as_dict=True,
	)


def get_group_name(rec, grouping):
	field = {
		"Company Total": None,
		"Customer": "customer",
		"Customer Group": "customer_group",
		"Territory": "territory",
		"Item": "item_code",
		"Item Group": "item_group",
	}[grouping]
	if not field:
		return _("Company Total")
	return str(rec.get(field) or _("Unspecified"))


def get_period_key(d, period):
	if period == "Monthly":
		return d.year, d.month
	if period == "Quarterly":
		return d.year, (d.month - 1) // 3 + 1
	if period == "Half-Yearly":
		return d.year, (d.month - 1) // 6 + 1
	return d.year, 1


def get_periods(start, end, period):
	cursor = date(start.year, start.month, 1)
	result = []
	while cursor <= end:
		key = get_period_key(cursor, period)
		if not result or result[-1] != key:
			result.append(key)
		cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
	return result


def get_period_label(key, period):
	year, sub = key
	if period == "Yearly":
		return str(year)
	if period == "Monthly":
		return f"{year}-{sub:02d}"
	return f"{year}-{'Q' if period == 'Quarterly' else 'H'}{sub}"
