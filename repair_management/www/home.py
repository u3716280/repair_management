import frappe
from frappe.sessions import get_csrf_token

no_cache = 1

# Fill these in to show them on the page. Empty values stay hidden.
CONTACT = {
	"phone": "",  # e.g. "02 123 4567"
	"line_url": "",  # e.g. "https://line.me/R/ti/p/@yourid"
	"address": "",
}


def get_context(context):
	context.no_breadcrumbs = 1
	context.contact = CONTACT
	context.phone_href = "".join(ch for ch in CONTACT["phone"] if ch.isdigit() or ch == "+")
	context.is_logged_in = frappe.session.user != "Guest"
	context.form_csrf_token = get_csrf_token() if context.is_logged_in else ""
	context.favicon_url = frappe.db.get_single_value("Website Settings", "favicon")
	context.logo_url = frappe.db.get_single_value("Website Settings", "app_logo")
