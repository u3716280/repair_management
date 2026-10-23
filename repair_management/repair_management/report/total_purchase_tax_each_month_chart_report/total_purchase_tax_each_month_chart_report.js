// Copyright (c) 2026, Chirayut D. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Total Purchase Tax Each Month Chart Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.defaults.get_user_default("fiscal_year"),
			reqd: 1,
		},
		{
			fieldname: "company_tax_address",
			label: __("Company Address"),
			fieldtype: "Link",
			options: "Address",
			get_query: () => {
				return {
					filters: {
						is_your_company_address: 1,
					},
				};
			},
		},
	],
};
