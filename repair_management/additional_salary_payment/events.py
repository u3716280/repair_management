from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from repair_management.additional_salary_payment.api import (
    _get_component_account,
    _validate_offset_component,
    _validate_salary_slip_source,
    _validate_source,
)


def _same_amount(a, b, precision=2) -> bool:
    return flt(a, precision) == flt(b, precision)


def before_cancel_payment_entry(doc, method=None) -> None:
    if doc.custom_additional_salary or doc.custom_salary_slip:
        # Frappe's check_no_back_links_exist() runs after on_cancel and would otherwise
        # block cancelling this Payment Entry because the source (and offset) Additional
        # Salary, or the Salary Slip, are still submitted and link back to this document.
        # NOTE: ERPNext's own PaymentEntry.on_cancel() reassigns self.ignore_linked_doctypes
        # for its own GL/Payment Ledger cleanup, which would overwrite (not merge with) a
        # value set here — so use flags.ignore_links instead, which skips the whole
        # back-link check regardless of what runs afterwards.
        doc.flags.ignore_links = True


def validate_payment_entry(doc, method=None) -> None:
    if not doc.custom_additional_salary:
        return

    source = frappe.get_doc("Additional Salary", doc.custom_additional_salary)
    _validate_source(source)

    if doc.payment_type != "Pay":
        frappe.throw(_("Payment Entry linked to Additional Salary must use Payment Type Pay."))
    if doc.company != source.company:
        frappe.throw(_("Payment Entry Company must match Additional Salary Company."))
    if doc.party_type != "Employee" or doc.party != source.employee:
        frappe.throw(_("Payment Entry Employee must match Additional Salary Employee."))
    if not _same_amount(doc.paid_amount, source.amount) or not _same_amount(doc.received_amount, source.amount):
        frappe.throw(_("Payment Entry amount must equal the Additional Salary amount."))
    if not doc.custom_offset_salary_component:
        frappe.throw(_("Payment Offset Component is required."))

    expected_account = _validate_offset_component(doc.custom_offset_salary_component, source.company)
    if doc.paid_to != expected_account:
        frappe.throw(
            _("Account Paid To must be {0}, from the selected Payment Offset Component.").format(
                frappe.bold(expected_account)
            )
        )

    duplicate = frappe.db.get_value(
        "Payment Entry",
        {
            "custom_additional_salary": source.name,
            "docstatus": ["in", [0, 1]],
            "name": ["!=", doc.name],
        },
        "name",
    )
    if duplicate:
        frappe.throw(
            _("Payment Entry {0} already exists for this Additional Salary.").format(
                frappe.bold(duplicate)
            )
        )


def _create_offset_additional_salary(payment, source) -> str:
    existing = payment.custom_offset_additional_salary or source.custom_offset_additional_salary
    if existing and frappe.db.exists("Additional Salary", existing):
        existing_status = frappe.db.get_value("Additional Salary", existing, "docstatus")
        if existing_status == 1:
            return existing
        if existing_status == 0:
            offset = frappe.get_doc("Additional Salary", existing)
            offset.submit()
            return offset.name

    offset = frappe.new_doc("Additional Salary")
    offset.employee = source.employee
    offset.company = source.company
    offset.salary_component = payment.custom_offset_salary_component
    offset.amount = source.amount
    offset.currency = source.currency
    offset.payroll_date = source.payroll_date
    offset.overwrite_salary_structure_amount = 0
    offset.deduct_full_tax_on_selected_payroll_date = 0
    offset.ref_doctype = "Additional Salary"
    offset.ref_docname = source.name
    offset.custom_is_payment_offset = 1
    offset.custom_source_additional_salary = source.name
    offset.custom_payment_entry = payment.name
    offset.custom_payment_status = "Paid"
    offset.custom_paid_amount = source.amount
    offset.custom_offset_salary_component = payment.custom_offset_salary_component
    offset.flags.ignore_permissions = True
    offset.insert()
    offset.submit()
    return offset.name


def on_submit_payment_entry(doc, method=None) -> None:
    if not doc.custom_additional_salary:
        return

    source = frappe.get_doc("Additional Salary", doc.custom_additional_salary)

    offset_name = None
    if source.type == "Earning":
        # Only an Earning needs a compensating Deduction, since it would otherwise
        # still be counted as income in the next Payroll on top of this direct payment.
        # A Deduction source already reduces Payroll on its own; creating an offset
        # here would deduct the same amount twice.
        offset_name = _create_offset_additional_salary(doc, source)

    doc.db_set("custom_offset_additional_salary", offset_name, update_modified=False)
    source.db_set("custom_payment_entry", doc.name, update_modified=False)
    source.db_set("custom_payment_status", "Paid", update_modified=False)
    source.db_set("custom_paid_amount", doc.paid_amount, update_modified=False)
    source.db_set("custom_offset_salary_component", doc.custom_offset_salary_component, update_modified=False)
    source.db_set("custom_offset_additional_salary", offset_name, update_modified=False)


def on_cancel_payment_entry(doc, method=None) -> None:
    if not doc.custom_additional_salary:
        return

    offset_name = doc.custom_offset_additional_salary
    if offset_name and frappe.db.exists("Additional Salary", offset_name):
        offset = frappe.get_doc("Additional Salary", offset_name)
        if offset.docstatus == 1:
            frappe.flags.additional_salary_payment_cancel = True
            try:
                offset.flags.ignore_permissions = True
                # the source Additional Salary is still submitted at this point and
                # links back to this offset, which would otherwise trip Frappe's
                # generic back-link check
                offset.flags.ignore_links = True
                offset.cancel()
            finally:
                frappe.flags.additional_salary_payment_cancel = False

    if frappe.db.exists("Additional Salary", doc.custom_additional_salary):
        source = frappe.get_doc("Additional Salary", doc.custom_additional_salary)
        source.db_set("custom_payment_status", "Cancelled", update_modified=False)
        source.db_set("custom_paid_amount", 0, update_modified=False)


def on_trash_payment_entry(doc, method=None) -> None:
    if doc.custom_additional_salary and frappe.db.exists("Additional Salary", doc.custom_additional_salary):
        source = frappe.get_doc("Additional Salary", doc.custom_additional_salary)
        if source.custom_payment_entry == doc.name:
            source.db_set("custom_payment_entry", None, update_modified=False)
            source.db_set("custom_payment_status", "Not Paid", update_modified=False)
            source.db_set("custom_paid_amount", 0, update_modified=False)
            source.db_set("custom_offset_salary_component", None, update_modified=False)
            source.db_set("custom_offset_additional_salary", None, update_modified=False)

    if doc.custom_salary_slip and frappe.db.exists("Salary Slip", doc.custom_salary_slip):
        slip = frappe.get_doc("Salary Slip", doc.custom_salary_slip)
        if slip.custom_payment_entry == doc.name:
            slip.db_set("custom_payment_entry", None, update_modified=False)
            slip.db_set("custom_payment_status", "Not Paid", update_modified=False)
            slip.db_set("custom_paid_amount", 0, update_modified=False)


def before_cancel_additional_salary(doc, method=None) -> None:
    if doc.custom_is_payment_offset:
        if frappe.flags.get("additional_salary_payment_cancel"):
            return
        payment = doc.custom_payment_entry
        if payment and frappe.db.exists("Payment Entry", payment):
            payment_status = frappe.db.get_value("Payment Entry", payment, "docstatus")
            if payment_status == 1:
                frappe.throw(
                    _("Cancel Payment Entry {0} first. The offset will be cancelled automatically.").format(
                        frappe.bold(payment)
                    )
                )
        return

    payment = doc.custom_payment_entry
    if payment and frappe.db.exists("Payment Entry", payment):
        payment_status = frappe.db.get_value("Payment Entry", payment, "docstatus")
        if payment_status == 0:
            frappe.throw(
                _("Delete draft Payment Entry {0} before cancelling this Additional Salary.").format(
                    frappe.bold(payment)
                )
            )
        if payment_status == 1:
            frappe.throw(
                _("Cancel Payment Entry {0} before cancelling this Additional Salary.").format(
                    frappe.bold(payment)
                )
            )


def validate_salary_slip_payment_entry(doc, method=None) -> None:
    if not doc.custom_salary_slip:
        return

    source = frappe.get_doc("Salary Slip", doc.custom_salary_slip)
    _validate_salary_slip_source(source)

    if doc.payment_type != "Pay":
        frappe.throw(_("Payment Entry linked to Salary Slip must use Payment Type Pay."))
    if doc.company != source.company:
        frappe.throw(_("Payment Entry Company must match Salary Slip Company."))
    if doc.party_type != "Employee" or doc.party != source.employee:
        frappe.throw(_("Payment Entry Employee must match Salary Slip Employee."))
    if not _same_amount(doc.paid_amount, source.net_pay) or not _same_amount(doc.received_amount, source.net_pay):
        frappe.throw(_("Payment Entry amount must equal the Salary Slip Net Pay."))

    duplicate = frappe.db.get_value(
        "Payment Entry",
        {
            "custom_salary_slip": source.name,
            "docstatus": ["in", [0, 1]],
            "name": ["!=", doc.name],
        },
        "name",
    )
    if duplicate:
        frappe.throw(
            _("Payment Entry {0} already exists for this Salary Slip.").format(frappe.bold(duplicate))
        )


def on_submit_salary_slip_payment(doc, method=None) -> None:
    if not doc.custom_salary_slip:
        return

    source = frappe.get_doc("Salary Slip", doc.custom_salary_slip)
    source.db_set("custom_payment_entry", doc.name, update_modified=False)
    source.db_set("custom_payment_status", "Paid", update_modified=False)
    source.db_set("custom_paid_amount", doc.paid_amount, update_modified=False)


def on_cancel_salary_slip_payment(doc, method=None) -> None:
    if not doc.custom_salary_slip or not frappe.db.exists("Salary Slip", doc.custom_salary_slip):
        return

    slip = frappe.get_doc("Salary Slip", doc.custom_salary_slip)
    slip.db_set("custom_payment_status", "Cancelled", update_modified=False)
    slip.db_set("custom_paid_amount", 0, update_modified=False)


def before_cancel_salary_slip(doc, method=None) -> None:
    payment = doc.custom_payment_entry
    if payment and frappe.db.exists("Payment Entry", payment):
        payment_status = frappe.db.get_value("Payment Entry", payment, "docstatus")
        if payment_status == 0:
            frappe.throw(
                _("Delete draft Payment Entry {0} before cancelling this Salary Slip.").format(
                    frappe.bold(payment)
                )
            )
        if payment_status == 1:
            frappe.throw(
                _("Cancel Payment Entry {0} before cancelling this Salary Slip.").format(
                    frappe.bold(payment)
                )
            )
