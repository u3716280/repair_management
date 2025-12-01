// Copyright (c) 2025, Chirayut D. and contributors
// For license information, please see license.txt

// frappe.query_reports["Customer Purchase History"] = {
//	"filters": [

//	]
// };

frappe.query_reports["Customer Purchase History"] = {
    "filters": [
        {
            fieldname: "customer",
            label: "Customer",
            fieldtype: "Link",
            options: "Customer",
 	    reqd: 1,
        },
        {
            fieldname: "from_date",
            label: "From Date",
            fieldtype: "Date",
            default: frappe.datetime.year_start(),
            reqd: 1,
        },
        {
            fieldname: "to_date",
            label: "To Date",
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1,
        }
    ]
};

