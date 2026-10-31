// Copyright (c) 2026, Chirayut D. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Multi-Year Sales Invoice Trends"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.year_start(), -48),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "period",
			label: __("Period"),
			fieldtype: "Select",
			reqd: 1,
			options: ["Monthly", "Quarterly", "Half-Yearly", "Yearly"],
			default: "Yearly",
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			reqd: 1,
			options: [
				"Company Total",
				"Customer",
				"Customer Group",
				"Territory",
				"Item",
				"Item Group",
			],
			default: "Company Total",
		},
		{
			fieldname: "value_type",
			label: __("Value"),
			fieldtype: "Select",
			reqd: 1,
			options: ["Sales Amount", "Quantity"],
			default: "Sales Amount",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "customer_group",
			label: __("Customer Group"),
			fieldtype: "Link",
			options: "Customer Group",
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Link",
			options: "Territory",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "include_returns",
			label: __("Include Returns / Credit Notes"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "show_yoy",
			label: __("Show YoY %"),
			fieldtype: "Check",
			default: 1,
		},
	],
};
