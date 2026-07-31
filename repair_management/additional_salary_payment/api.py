from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def _get_component_account(component: str, company: str) -> str:
    account = frappe.db.get_value(
        "Salary Component Account",
        {"parent": component, "company": company},
        "account",
    )
    if not account:
        frappe.throw(
            _("Salary Component {0} has no account configured for Company {1}.").format(
                frappe.bold(component), frappe.bold(company)
            )
        )
    return account


def _validate_offset_component(component: str, company: str) -> str:
    details = frappe.db.get_value(
        "Salary Component",
        component,
        [
            "type",
            "disabled",
            "statistical_component",
            "do_not_include_in_total",
            "do_not_include_in_accounts",
            "variable_based_on_taxable_salary",
        ],
        as_dict=True,
    )
    if not details:
        frappe.throw(_("Salary Component {0} was not found.").format(frappe.bold(component)))
    if details.type != "Deduction":
        frappe.throw(_("Payment Offset Component must be a Deduction component."))
    if details.disabled:
        frappe.throw(_("Payment Offset Component is disabled."))
    if details.statistical_component or details.do_not_include_in_total:
        frappe.throw(_("Payment Offset Component must reduce Net Pay."))
    if details.do_not_include_in_accounts:
        frappe.throw(_("Payment Offset Component must be included in accounting entries."))
    if details.variable_based_on_taxable_salary:
        frappe.throw(_("A tax-calculated Salary Component cannot be used as the payment offset."))

    account = _get_component_account(component, company)
    account_details = frappe.db.get_value(
        "Account",
        account,
        ["is_group", "company", "root_type", "account_type", "account_currency", "disabled"],
        as_dict=True,
    )
    if not account_details or account_details.disabled:
        frappe.throw(_("The account configured for the offset component is unavailable."))
    if account_details.company != company or account_details.is_group:
        frappe.throw(_("The payment offset account must be a ledger account in the same Company."))
    if account_details.root_type != "Asset":
        frappe.throw(_("The payment offset account must be an Asset account, such as Employee Salary Advance."))
    if account_details.account_type in ("Bank", "Cash", "Receivable", "Payable"):
        frappe.throw(
            _("Use a normal Asset account without Bank, Cash, Receivable, or Payable account type.")
        )
    return account


def _validate_source(doc) -> None:
    if doc.docstatus != 1:
        frappe.throw(_("Additional Salary must be submitted before making payment."))
    if doc.type not in ("Earning", "Deduction"):
        frappe.throw(_("Make a Payment is available only for Earning or Deduction Additional Salary."))
    if doc.is_recurring:
        frappe.throw(_("Recurring Additional Salary cannot be paid with this button."))
    if doc.disabled:
        frappe.throw(_("This Additional Salary is disabled."))
    if doc.custom_is_payment_offset:
        frappe.throw(_("A payment-offset Additional Salary cannot create another payment."))
    if flt(doc.amount) <= 0:
        frappe.throw(_("Payment amount must be greater than zero."))


def _get_live_payment(source) -> str | None:
    payment_name = source.custom_payment_entry
    if payment_name and frappe.db.exists("Payment Entry", payment_name):
        status = frappe.db.get_value("Payment Entry", payment_name, "docstatus")
        if status in (0, 1):
            return payment_name

    payment_name = frappe.db.get_value(
        "Payment Entry",
        {"custom_additional_salary": source.name, "docstatus": ["in", [0, 1]]},
        "name",
        order_by="creation desc",
    )
    return payment_name


def _get_default_offset_component(source) -> str | None:
    component = source.salary_component
    if not component:
        return None
    details = frappe.db.get_value(
        "Salary Component",
        component,
        ["type", "disabled", "statistical_component", "do_not_include_in_total"],
        as_dict=True,
    )
    if not details:
        return None
    if details.type != "Deduction":
        return None
    if details.disabled or details.statistical_component or details.do_not_include_in_total:
        return None
    return component


@frappe.whitelist()
def get_payment_setup(additional_salary: str) -> dict[str, Any]:
    source = frappe.get_doc("Additional Salary", additional_salary)
    source.check_permission("read")
    _validate_source(source)

    live_payment = _get_live_payment(source)
    if live_payment:
        return {"existing_payment_entry": live_payment}

    return {
        "company": source.company,
        "employee": source.employee,
        "employee_name": source.employee_name,
        "amount": source.amount,
        "currency": source.currency,
        "posting_date": nowdate(),
        "payroll_date": source.payroll_date,
        "default_offset_salary_component": _get_default_offset_component(source),
    }


@frappe.whitelist()
def get_offset_account(salary_component: str, company: str) -> dict[str, str]:
    frappe.has_permission("Salary Component", "read", throw=True)
    account = _validate_offset_component(salary_component, company)
    currency = frappe.db.get_value("Account", account, "account_currency")
    return {"account": account, "currency": currency}


def _validate_salary_slip_source(doc) -> None:
    if doc.docstatus != 1:
        frappe.throw(_("Salary Slip must be submitted before making payment."))
    if flt(doc.net_pay) <= 0:
        frappe.throw(_("Net Pay must be greater than zero."))


def _get_live_salary_slip_payment(source) -> str | None:
    payment_name = source.custom_payment_entry
    if payment_name and frappe.db.exists("Payment Entry", payment_name):
        status = frappe.db.get_value("Payment Entry", payment_name, "docstatus")
        if status in (0, 1):
            return payment_name

    payment_name = frappe.db.get_value(
        "Payment Entry",
        {"custom_salary_slip": source.name, "docstatus": ["in", [0, 1]]},
        "name",
        order_by="creation desc",
    )
    return payment_name


def _get_default_payable_account(company: str) -> str | None:
    account = frappe.db.get_value("Company", company, "default_payroll_payable_account")
    if account and frappe.db.get_value("Account", account, "disabled"):
        return None
    return account


@frappe.whitelist()
def get_salary_slip_payment_setup(salary_slip: str) -> dict[str, Any]:
    source = frappe.get_doc("Salary Slip", salary_slip)
    source.check_permission("read")
    _validate_salary_slip_source(source)

    live_payment = _get_live_salary_slip_payment(source)
    if live_payment:
        return {"existing_payment_entry": live_payment}

    return {
        "company": source.company,
        "employee": source.employee,
        "employee_name": source.employee_name,
        "amount": source.net_pay,
        "currency": source.currency or frappe.get_cached_value("Company", source.company, "default_currency"),
        "posting_date": nowdate(),
        "default_paid_to": _get_default_payable_account(source.company),
    }


@frappe.whitelist()
def create_salary_slip_payment(
    salary_slip: str,
    posting_date: str,
    mode_of_payment: str,
    paid_from: str,
    paid_to: str,
    reference_no: str | None = None,
    reference_date: str | None = None,
) -> dict[str, str]:
    source = frappe.get_doc("Salary Slip", salary_slip)
    source.check_permission("write")
    _validate_salary_slip_source(source)

    existing = _get_live_salary_slip_payment(source)
    if existing:
        frappe.throw(
            _("Payment Entry {0} already exists.").format(frappe.bold(existing)),
            title=_("Duplicate Payment Prevented"),
        )

    if not mode_of_payment:
        frappe.throw(_("Mode of Payment is required."))
    if not paid_from:
        frappe.throw(_("Account Paid From is required."))
    if not paid_to:
        frappe.throw(_("Account Paid To is required."))

    posting_date = getdate(posting_date or nowdate())
    paid_from_details = frappe.db.get_value(
        "Account",
        paid_from,
        ["company", "is_group", "disabled", "account_type", "account_currency"],
        as_dict=True,
    )
    if not paid_from_details or paid_from_details.disabled:
        frappe.throw(_("Account Paid From is unavailable."))
    if paid_from_details.company != source.company or paid_from_details.is_group:
        frappe.throw(_("Account Paid From must be a ledger account in the same Company."))
    if paid_from_details.account_type not in ("Bank", "Cash"):
        frappe.throw(_("Account Paid From must be a Bank or Cash account."))

    paid_to_details = frappe.db.get_value(
        "Account",
        paid_to,
        ["company", "is_group", "disabled", "account_type", "account_currency"],
        as_dict=True,
    )
    if not paid_to_details or paid_to_details.disabled:
        frappe.throw(_("Account Paid To is unavailable."))
    if paid_to_details.company != source.company or paid_to_details.is_group:
        frappe.throw(_("Account Paid To must be a ledger account in the same Company."))
    if paid_to_details.account_type != "Payable":
        frappe.throw(_("Account Paid To must be a Payable account, such as the Payroll Payable Account."))

    slip_currency = source.currency or frappe.get_cached_value("Company", source.company, "default_currency")
    if slip_currency not in (paid_from_details.account_currency, paid_to_details.account_currency):
        frappe.throw(_("Salary Slip currency must match at least one Payment Entry account currency."))

    if paid_from_details.account_type == "Bank" and not (reference_no and reference_date):
        frappe.throw(_("Reference No and Reference Date are required for a Bank payment."))

    payment = frappe.new_doc("Payment Entry")
    payment.payment_type = "Pay"
    payment.company = source.company
    payment.posting_date = posting_date
    payment.mode_of_payment = mode_of_payment
    payment.party_type = "Employee"
    payment.party = source.employee
    payment.paid_from = paid_from
    payment.paid_to = paid_to
    payment.paid_amount = source.net_pay
    payment.received_amount = source.net_pay
    payment.reference_no = reference_no
    payment.reference_date = getdate(reference_date) if reference_date else None
    payment.custom_remarks = 1
    payment.remarks = _("Direct Net Pay payment for Salary Slip {0} ({1})").format(
        source.name, source.employee_name or source.employee
    )
    payment.custom_salary_slip = source.name
    payment.flags.ignore_permissions = False
    payment.insert()

    source.db_set("custom_payment_entry", payment.name, update_modified=False)
    source.db_set("custom_payment_status", "Draft", update_modified=False)
    source.db_set("custom_paid_amount", 0, update_modified=False)

    return {"payment_entry": payment.name}


@frappe.whitelist()
def create_payment_entry(
    additional_salary: str,
    posting_date: str,
    mode_of_payment: str,
    paid_from: str,
    offset_salary_component: str,
    reference_no: str | None = None,
    reference_date: str | None = None,
) -> dict[str, str]:
    source = frappe.get_doc("Additional Salary", additional_salary)
    source.check_permission("write")
    _validate_source(source)

    existing = _get_live_payment(source)
    if existing:
        frappe.throw(
            _("Payment Entry {0} already exists.").format(frappe.bold(existing)),
            title=_("Duplicate Payment Prevented"),
        )

    if not mode_of_payment:
        frappe.throw(_("Mode of Payment is required."))
    if not paid_from:
        frappe.throw(_("Account Paid From is required."))

    posting_date = getdate(posting_date or nowdate())
    paid_from_details = frappe.db.get_value(
        "Account",
        paid_from,
        ["company", "is_group", "disabled", "account_type", "account_currency"],
        as_dict=True,
    )
    if not paid_from_details or paid_from_details.disabled:
        frappe.throw(_("Account Paid From is unavailable."))
    if paid_from_details.company != source.company or paid_from_details.is_group:
        frappe.throw(_("Account Paid From must be a ledger account in the same Company."))
    if paid_from_details.account_type not in ("Bank", "Cash"):
        frappe.throw(_("Account Paid From must be a Bank or Cash account."))

    offset_account = _validate_offset_component(offset_salary_component, source.company)
    offset_currency = frappe.db.get_value("Account", offset_account, "account_currency")
    if source.currency not in (paid_from_details.account_currency, offset_currency):
        frappe.throw(
            _("Additional Salary currency must match at least one Payment Entry account currency.")
        )

    if paid_from_details.account_type == "Bank" and not (reference_no and reference_date):
        frappe.throw(_("Reference No and Reference Date are required for a Bank payment."))

    payment = frappe.new_doc("Payment Entry")
    payment.payment_type = "Pay"
    payment.company = source.company
    payment.posting_date = posting_date
    payment.mode_of_payment = mode_of_payment
    payment.party_type = "Employee"
    payment.party = source.employee
    payment.paid_from = paid_from
    payment.paid_to = offset_account
    payment.paid_amount = source.amount
    payment.received_amount = source.amount
    payment.reference_no = reference_no
    payment.reference_date = getdate(reference_date) if reference_date else None
    payment.custom_remarks = 1
    payment.remarks = _("Direct payment for Additional Salary {0} ({1})").format(
        source.name, source.employee_name or source.employee
    )
    payment.custom_additional_salary = source.name
    payment.custom_offset_salary_component = offset_salary_component
    payment.flags.ignore_permissions = False
    payment.insert()

    source.db_set("custom_payment_entry", payment.name, update_modified=False)
    source.db_set("custom_payment_status", "Draft", update_modified=False)
    source.db_set("custom_paid_amount", 0, update_modified=False)
    source.db_set("custom_offset_salary_component", offset_salary_component, update_modified=False)

    return {"payment_entry": payment.name}
