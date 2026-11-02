"""One-off site setup for the public landing page.

Run with: bench --site local.147 execute repair_management.landing_setup.apply
Safe to run more than once. Follow it with `bench --site local.147 clear-cache`,
because the home page is cached per user.
"""

import frappe


def apply():
	# "/desk" is not a page, so "/" returned 404 for every logged-in user.
	frappe.db.set_single_value("Portal Settings", "default_portal_home", "")

	# Web Pages outrank www templates, so this one would shadow www/home.html.
	if frappe.db.exists("Web Page", "test-home"):
		frappe.db.set_value("Web Page", "test-home", "published", 0)

	if not frappe.db.exists("Lead Source", "Website"):
		frappe.get_doc({"doctype": "Lead Source", "source_name": "Website"}).insert(ignore_permissions=True)

	frappe.db.commit()
