// Copyright (c) 2026, Chirayut D. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Total Sales Tax Each Month Chart Report"] = {
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
			fieldname: "tax_percent",
			label: __("Tax Percent"),
			fieldtype: "Select",
			options: get_percent_options(),
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

function get_percent_options() {
	let options = [""];
	frappe.db
		.get_list("Sales Tax Invoice", {
			fields: ["tax_percent"],
			distinct: 1,
			order_by: "tax_percent",
		})
		.then((res) => {
			res.forEach((dimension) => {
				options.push(dimension.tax_percent + "%");
			});
		});
	return options;
}
