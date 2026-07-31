frappe.ui.form.on("Salary Slip", {
    refresh(frm) {
        if (frm.doc.docstatus !== 1) {
            return;
        }

        const payment = frm.doc.custom_payment_entry;
        if (payment) {
            const label = frm.doc.custom_payment_status === "Draft" ? __("Open Payment Entry") : __("View Payment Entry");
            frm.add_custom_button(label, () => frappe.set_route("Form", "Payment Entry", payment), __("Payment"));
        }

        if (!payment || ["Cancelled", "Not Paid", null, undefined, ""].includes(frm.doc.custom_payment_status)) {
            frm.add_custom_button(__("Make a Payment"), () => open_salary_slip_payment_dialog(frm), __("Payment"));
        }
    },
});

async function open_salary_slip_payment_dialog(frm) {
    const setup = await frappe.call({
        method: "repair_management.additional_salary_payment.api.get_salary_slip_payment_setup",
        args: { salary_slip: frm.doc.name },
        freeze: true,
        freeze_message: __("Preparing payment..."),
    });

    if (setup.message.existing_payment_entry) {
        frappe.set_route("Form", "Payment Entry", setup.message.existing_payment_entry);
        return;
    }

    const data = setup.message;
    const dialog = new frappe.ui.Dialog({
        title: __("Make a Payment"),
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "summary",
                options: `<div class="mb-3">
                    <b>${frappe.utils.escape_html(data.employee_name || data.employee)}</b><br>
                    ${__("Net Pay")}: ${format_currency(data.amount, data.currency)}
                </div>`,
            },
            {
                fieldtype: "Date",
                fieldname: "posting_date",
                label: __("Posting Date"),
                default: data.posting_date,
                reqd: 1,
            },
            {
                fieldtype: "Link",
                fieldname: "mode_of_payment",
                label: __("Mode of Payment"),
                options: "Mode of Payment",
                reqd: 1,
            },
            { fieldtype: "Column Break" },
            {
                fieldtype: "Link",
                fieldname: "paid_from",
                label: __("Account Paid From"),
                options: "Account",
                reqd: 1,
                get_query() {
                    return {
                        filters: {
                            company: data.company,
                            is_group: 0,
                            disabled: 0,
                            account_type: ["in", ["Bank", "Cash"]],
                        },
                    };
                },
            },
            {
                fieldtype: "Link",
                fieldname: "paid_to",
                label: __("Account Paid To"),
                options: "Account",
                reqd: 1,
                default: data.default_paid_to,
                description: __("Must be a Payable account, such as the Payroll Payable Account."),
                get_query() {
                    return {
                        filters: {
                            company: data.company,
                            is_group: 0,
                            disabled: 0,
                            account_type: "Payable",
                        },
                    };
                },
            },
            { fieldtype: "Section Break", label: __("Bank Reference") },
            {
                fieldtype: "Data",
                fieldname: "reference_no",
                label: __("Reference No"),
            },
            { fieldtype: "Column Break" },
            {
                fieldtype: "Date",
                fieldname: "reference_date",
                label: __("Reference Date"),
                default: data.posting_date,
            },
        ],
        primary_action_label: __("Create Payment Entry"),
        async primary_action(values) {
            const result = await frappe.call({
                method: "repair_management.additional_salary_payment.api.create_salary_slip_payment",
                args: {
                    salary_slip: frm.doc.name,
                    posting_date: values.posting_date,
                    mode_of_payment: values.mode_of_payment,
                    paid_from: values.paid_from,
                    paid_to: values.paid_to,
                    reference_no: values.reference_no,
                    reference_date: values.reference_date,
                },
                freeze: true,
                freeze_message: __("Creating Payment Entry..."),
            });
            dialog.hide();
            frappe.set_route("Form", "Payment Entry", result.message.payment_entry);
        },
    });

    dialog.show();
}
