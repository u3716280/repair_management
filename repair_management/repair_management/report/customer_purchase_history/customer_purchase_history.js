frappe.query_reports["Customer Purchase History"] = {
    filters: [
        {
            fieldname: "customer",
            label: __("Customer"),
            fieldtype: "Link",
	    reqd: 1,
            options: "Customer"
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
	    reqd: 1,
            default: frappe.datetime.year_start()
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
	    reqd: 1,
            default: frappe.datetime.get_today()
        }
    ],

    onload: function(report) {
        report.page.add_inner_button(__("Open Calendar View"), () => {
            const filters = report.get_filter_values() || {};

            let route_options = {};

            // ถ้าเลือก customer → ส่งไปเป็น filter ให้ Calendar
            if (filters.customer) {
                route_options.customer = filters.customer;
            }

            // ใช้ posting_date ระหว่าง from_date – to_date
            // เฉพาะกรณีที่มีทั้ง 2 ค่า และไม่ใช่ค่าว่าง
            // if (filters.from_date && filters.to_date) {
            //    route_options.posting_date = ['between', filters.from_date, filters.to_date];
            //}

            // ตั้ง route_options แล้วเปิด Calendar View ของ Sales Invoice
            frappe.route_options = route_options;
            frappe.set_route('List', 'Sales Invoice', 'Calendar');
        });
    }
};

