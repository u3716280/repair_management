from frappe.model.document import Document


class RDVATTaxpayer(Document):
	pass


def on_doctype_update():
	from repair_management.rd_vat.search import ensure_search_index

	ensure_search_index()
