# Copyright (c) 2025, Chirayut D. and contributors
# For license information, please see license.txt

# import frappe


def execute(filters=None):
	columns, data = [], []

	validate_filters(filters)

	return columns, data

def validate_filters(filters):

	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date"))


