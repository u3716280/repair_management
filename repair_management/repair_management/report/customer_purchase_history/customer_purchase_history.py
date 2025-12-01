# Copyright (c) 2025, Chirayut D. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, today, flt, cint

def execute(filters=None):
	columns, data = [], []
	"""Execute the Custom Sales Invoice Report"""
	if not filters:
		filters = {}

	validate_filters(filters)
	columns = get_columns(filters)

	# Get data based on filters
	data = get_data(filters)

	return columns, data

def validate_filters(filters):
	# Validate date range
	if getdate(filters.get("from_date")) > getdate(filters.get("to_date")):
		frappe.throw(_("From Date cannot be greater than To Date"))

	# if filters.from_date > filters.to_date:
	#	frappe.throw(_("From Date must be before To Date"))


def get_columns(filters):
	"""Define report columns based on filters"""
	columns = [
	    {
		"fieldname": "item_code",
		"label": _("Item Code"),
		"fieldtype": "Link",
		"options": "Item",
		"width": 200
	    },
	    {
		"fieldname": "item_name",
		"label": _("Item Name"),
		"fieldtype": "Data",
		"width": 350
	    },
	    {
		"fieldname": "qty",
		"label": _("Qty"),
		"fieldtype": "Float",
		"width": 80
	    },
	    {
		"fieldname": "uom",
		"label": _("UOM"),
		"fieldtype": "Data",
		"width": 80
	    },
	    {
		"fieldname": "rate",
		"label": _("Rate"),
		"fieldtype": "Currency",
		"width": 100
	    },
	    {
		"fieldname": "amount",
		"label": _("Amount"),
		"fieldtype": "Currency",
		"width": 100
	    },
	    {
		"fieldname": "posting_date",
		"label": _("Date"),
		"fieldtype": "Date",
		"width": 100
	    },
	    {
		"fieldname": "name",
		"label": _("Sales Invoice No"),
		"fieldtype": "Link",
		"options": "Sales Invoice",
		"width": 200
	    }
        ]

	return columns

def get_data(filters):
	"""Get filtered data based on user inputs"""
	query =
	   """
		SELECT
		    sii.item_code,
		    sii.item_name,
		    sii.qty,
		    sii.uom,
		    sii.rate,
		    sii.amount,
		    si.posting_date,
		    si.name
		FROM
		    `tabSales Invoice` si
		JOIN
		    `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE
		    si.docstatus = 1
		    AND (%(customer)s IS NULL OR %(customer)s = '' OR si.customer = %(customer)s)
		    AND (si.posting_date BETWEEN %(from_date)s AND %(to_date)s)
		ORDER BY
		    si.posting_date DESC, sii.item_code;
	   """
	# Execute query
	data = frappe.db.sql(query, filters, as_dict=1)

	return data
