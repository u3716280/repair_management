# Copyright (c) 2026, Chirayut D. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import CustomFunction
from frappe.query_builder.functions import Count, Sum
from frappe.utils import add_months, flt, getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	return columns, data, None, chart


def get_columns():
	return [
		{
			"label": _("Month"),
			"fieldname": "month",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("No. of Invoices"),
			"fieldname": "invoice_count",
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"label": _("Tax Base"),
			"fieldname": "tax_base",
			"fieldtype": "Currency",
			"width": 180,
		},
		{
			"label": _("Tax Amount"),
			"fieldname": "tax_amount",
			"fieldtype": "Currency",
			"width": 180,
		},
	]


def get_months(filters):
	fy = frappe.get_cached_doc("Fiscal Year", filters.year)
	start = getdate(fy.year_start_date).replace(day=1)
	end = getdate(fy.year_end_date)
	months = []
	while start <= end:
		months.append(start)
		start = add_months(start, 1)
	return fy, months


def get_data(filters):
	if not filters.get("year"):
		return []

	fy, months = get_months(filters)

	tinv = frappe.qb.DocType("Sales Tax Invoice")
	date_format = CustomFunction("date_format", ["date", "format"])
	period = date_format(tinv.report_date, "%Y-%m")

	query = (
		frappe.qb.from_(tinv)
		.select(
			period.as_("period"),
			Count(tinv.name).as_("invoice_count"),
			Sum(tinv.tax_base).as_("tax_base"),
			Sum(tinv.tax_amount).as_("tax_amount"),
		)
		.where(tinv.docstatus == 1)
		.where(tinv.report_date >= fy.year_start_date)
		.where(tinv.report_date <= fy.year_end_date)
		.groupby(period)
	)

	if filters.get("company"):
		query = query.where(tinv.company == filters.company)

	if filters.get("tax_percent"):
		query = query.where(tinv.tax_percent == flt(filters.tax_percent.rstrip("%")))

	if filters.get("company_tax_address"):
		query = query.where(tinv.company_tax_address == filters.company_tax_address)

	totals = {row.period: row for row in query.run(as_dict=True)}

	data = []
	for m in months:
		row = totals.get(m.strftime("%Y-%m"), {})
		data.append(
			{
				"month": m.strftime("%b %Y"),
				"invoice_count": row.get("invoice_count") or 0,
				"tax_base": flt(row.get("tax_base"), 2),
				"tax_amount": flt(row.get("tax_amount"), 2),
			}
		)
	return data


def get_chart(data):
	return {
		"data": {
			"labels": [d["month"] for d in data],
			"datasets": [
				{"name": _("Tax Amount"), "values": [d["tax_amount"] for d in data]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
		"colors": ["#5e64ff"],
		"title": _("Total Sales Tax Each Month"),
	}
