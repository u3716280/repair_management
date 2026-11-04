import frappe

from repair_management.rd_vat.sync import DEFAULT_URLS, SETTINGS, get_settings


def execute():
	"""Store the defaults once, so the Settings form shows what the import really uses."""
	stored = frappe.db.get_singles_dict(SETTINGS)
	settings = get_settings()
	defaults = {
		"bangkok_url": DEFAULT_URLS["Bangkok"],
		"provinces_url": DEFAULT_URLS["Other Provinces"],
		"batch_size": settings["batch_size"],
		"auto_update": settings["auto_update"],
	}
	for field, value in defaults.items():
		if stored.get(field) in (None, ""):
			frappe.db.set_single_value(SETTINGS, field, value)
