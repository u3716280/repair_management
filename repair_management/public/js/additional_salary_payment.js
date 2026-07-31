frappe.ui.form.on("Additional Salary", {
    refresh(frm) {
        if (frm.doc.docstatus !== 1 || !["Earning", "Deduction"].includes(frm.doc.type) || frm.doc.is_recurring || frm.doc.disabled) {
            return;
        }

        if (frm.doc.custom_is_payment_offset) {
            return;
        }

        const payment = frm.doc.custom_payment_entry;
        if (payment) {
            const label = frm.doc.custom_payment_status === "Draft" ? __("Open Payment Entry") : __("View Payment Entry");
            frm.add_custom_button(label, () => frappe.set_route("Form", "Payment Entry", payment), __("Payment"));
        }

        if (!payment || ["Cancelled", "Not Paid", null, undefined, ""].includes(frm.doc.custom_payment_status)) {
            frm.add_custom_button(__("Make a Payment"), () => open_payment_dialog(frm), __("Payment"));
        }
    },
});

async function open_payment_dialog(frm) {
    const setup = await frappe.call({
        method: "repair_management.additional_salary_payment.api.get_payment_setup",
        args: { additional_salary: frm.doc.name },
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
                    ${__("Amount")}: ${format_currency(data.amount, data.currency)}
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
            { fieldtype: "Section Break", label: __("Payroll Offset") },
            {
                fieldtype: "Link",
                fieldname: "offset_salary_component",
                label: __("Payment Offset Component"),
                options: "Salary Component",
                reqd: 1,
                default: data.default_offset_salary_component,
                description: __("Use a Deduction component mapped to an Employee Salary Advance asset account."),
                get_query() {
                    return {
                        filters: {
                            type: "Deduction",
                            disabled: 0,
                            statistical_component: 0,
                            do_not_include_in_total: 0,
                            do_not_include_in_accounts: 0,
                        },
                    };
                },
                async onchange() {
                    const component = dialog.get_value("offset_salary_component");
                    if (!component) {
                        dialog.set_value("offset_account", "");
                        return;
                    }
                    const result = await frappe.call({
                        method: "repair_management.additional_salary_payment.api.get_offset_account",
                        args: { salary_component: component, company: data.company },
                    });
                    dialog.set_value("offset_account", result.message.account);
                },
            },
            {
                fieldtype: "Link",
                fieldname: "offset_account",
                label: __("Offset Account"),
                options: "Account",
                read_only: 1,
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
                method: "repair_management.additional_salary_payment.api.create_payment_entry",
                args: {
                    additional_salary: frm.doc.name,
                    posting_date: values.posting_date,
                    mode_of_payment: values.mode_of_payment,
                    paid_from: values.paid_from,
                    offset_salary_component: values.offset_salary_component,
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

    if (data.default_offset_salary_component) {
        dialog.fields_dict.offset_salary_component.df.onchange();
    }
}
