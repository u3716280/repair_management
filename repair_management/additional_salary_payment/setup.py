from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ADDITIONAL_SALARY_FIELDS = [
    {
        "fieldname": "custom_payment_section",
        "label": "Direct Payment",
        "fieldtype": "Section Break",
        "insert_after": "ref_docname",
        "collapsible": 1,
    },
    {
        "fieldname": "custom_payment_entry",
        "label": "Payment Entry",
        "fieldtype": "Link",
        "options": "Payment Entry",
        "insert_after": "custom_payment_section",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_payment_status",
        "label": "Payment Status",
        "fieldtype": "Select",
        "options": "Not Paid\nDraft\nPaid\nCancelled",
        "default": "Not Paid",
        "insert_after": "custom_payment_entry",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_paid_amount",
        "label": "Paid Amount",
        "fieldtype": "Currency",
        "options": "currency",
        "insert_after": "custom_payment_status",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_offset_salary_component",
        "label": "Payment Offset Component",
        "fieldtype": "Link",
        "options": "Salary Component",
        "insert_after": "custom_paid_amount",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_offset_additional_salary",
        "label": "Offset Additional Salary",
        "fieldtype": "Link",
        "options": "Additional Salary",
        "insert_after": "custom_offset_salary_component",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_is_payment_offset",
        "label": "Is Payment Offset",
        "fieldtype": "Check",
        "insert_after": "custom_offset_additional_salary",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
        "hidden": 1,
    },
    {
        "fieldname": "custom_source_additional_salary",
        "label": "Source Additional Salary",
        "fieldtype": "Link",
        "options": "Additional Salary",
        "insert_after": "custom_is_payment_offset",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
        "hidden": 1,
    },
]

PAYMENT_ENTRY_FIELDS = [
    {
        "fieldname": "custom_additional_salary",
        "label": "Additional Salary",
        "fieldtype": "Link",
        "options": "Additional Salary",
        "insert_after": "party_name",
        "read_only": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_offset_salary_component",
        "label": "Payment Offset Component",
        "fieldtype": "Link",
        "options": "Salary Component",
        "insert_after": "custom_additional_salary",
        "read_only": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_offset_additional_salary",
        "label": "Offset Additional Salary",
        "fieldtype": "Link",
        "options": "Additional Salary",
        "insert_after": "custom_offset_salary_component",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_salary_slip",
        "label": "Salary Slip",
        "fieldtype": "Link",
        "options": "Salary Slip",
        "insert_after": "custom_offset_additional_salary",
        "read_only": 1,
        "no_copy": 1,
    },
]

SALARY_SLIP_FIELDS = [
    {
        "fieldname": "custom_payment_section",
        "label": "Direct Payment",
        "fieldtype": "Section Break",
        "insert_after": "net_pay",
        "collapsible": 1,
    },
    {
        "fieldname": "custom_payment_entry",
        "label": "Payment Entry",
        "fieldtype": "Link",
        "options": "Payment Entry",
        "insert_after": "custom_payment_section",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_payment_status",
        "label": "Payment Status",
        "fieldtype": "Select",
        "options": "Not Paid\nDraft\nPaid\nCancelled",
        "default": "Not Paid",
        "insert_after": "custom_payment_entry",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
    {
        "fieldname": "custom_paid_amount",
        "label": "Paid Amount",
        "fieldtype": "Currency",
        "options": "currency",
        "insert_after": "custom_payment_status",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
    },
]


def install() -> None:
    custom_fields = {
        "Additional Salary": ADDITIONAL_SALARY_FIELDS,
        "Payment Entry": PAYMENT_ENTRY_FIELDS,
        "Salary Slip": SALARY_SLIP_FIELDS,
    }
    create_custom_fields(custom_fields, update=True)
    frappe.clear_cache(doctype="Additional Salary")
    frappe.clear_cache(doctype="Payment Entry")
    frappe.clear_cache(doctype="Salary Slip")
