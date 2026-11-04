"""Use RD VAT data with ERPNext Customer, Supplier and Address.

Nothing changes without an explicit confirmed apply call, and all reads and writes respect the user's
permissions. Values always come from the server's own copy of the record, never from the browser.
"""

import re

import frappe
from frappe.utils import cint

from repair_management.rd_vat.normalize import (
	BANGKOK_PROVINCE,
	clean,
	format_address,
	normalize_search,
	pad_branch,
	to_display,
)

PARTIES = {
	"Customer": {
		"name_field": "customer_name",
		"type_field": "customer_type",
		"group_field": "customer_group",
	},
	"Supplier": {
		"name_field": "supplier_name",
		"type_field": "supplier_type",
		"group_field": "supplier_group",
	},
}
PARTY_UPDATABLE = {"party_name", "tax_id", "branch_code"}
ADDRESS_UPDATABLE = {
	"address_line1",
	"address_line2",
	"city",
	"county",
	"state",
	"pincode",
	"branch_code",
	"custom_branch_no",
}
DEFAULT_VAT_CUSTOMER_GROUP = "ลูกค้ามี VAT"
_INDIVIDUAL_TITLES = re.compile(r"^(นาย|นาง|นางสาว|น\.ส\.|ด\.ช\.|ด\.ญ\.)\s*")
_ADDRESS_LABELS = {
	"address_line1": "ที่อยู่บรรทัด 1",
	"address_line2": "ที่อยู่บรรทัด 2",
	"city": "ตำบล/แขวง",
	"county": "อำเภอ/เขต",
	"state": "จังหวัด",
	"pincode": "รหัสไปรษณีย์",
	"branch_code": "Branch Code",
	"custom_branch_no": "Branch No",
}


def _load_source(key: str = "", tax_id: str = "", branch: str = "", online: int = 0) -> dict:
	"""Read the taxpayer on the server: from the database, or again from SOAP for online results."""
	frappe.has_permission("RD VAT Taxpayer", "read", throw=True)
	if cint(online):
		from repair_management.repair_management.page.vatinfo.vatinfo import lookup_tin

		result = lookup_tin(tax_id, cint(branch))
		wanted = str(cint(branch))
		for row in result["rows"]:
			if str(cint(row.get("branch_number"))) == wanted:
				return row
		frappe.throw("ไม่พบข้อมูลนี้จากบริการของกรมสรรพากร กรุณาลองใหม่อีกครั้ง")

	from repair_management.rd_vat.search import get_taxpayer

	return get_taxpayer(key)


def _proposed_party(source: dict) -> dict:
	name = clean(source.get("taxpayer_name"))
	return {
		"party_name": name,
		"tax_id": source.get("tax_id"),
		"branch_code": pad_branch(source.get("branch_number")),
		"party_type_value": "Individual" if _INDIVIDUAL_TITLES.match(name) else "Company",
	}


def _proposed_address(source: dict) -> dict:
	is_bangkok = clean(source.get("province")) == BANGKOK_PROVINCE
	line1_parts = [
		("อาคาร", "building_name"),
		("ห้อง ", "room_no"),
		("ชั้น ", "floor_no"),
		("หมู่บ้าน", "village"),
		("", "house_no"),
		("หมู่ที่ ", "moo"),
	]
	line2_parts = [("ซอย", "soi"), ("แยก", "yaek"), ("ถนน", "road")]

	def join(parts):
		return " ".join(prefix + clean(source.get(key)) for prefix, key in parts if clean(source.get(key)))

	def prefixed(prefix, key):
		value = clean(source.get(key))
		return prefix + value if value else ""

	branch = pad_branch(source.get("branch_number"))
	return {
		"address_line1": join(line1_parts) or join(line2_parts) or "-",
		"address_line2": join(line2_parts) if join(line1_parts) else "",
		"city": prefixed("แขวง" if is_bangkok else "ต.", "subdistrict") or "-",
		"county": prefixed("เขต" if is_bangkok else "อ.", "district"),
		"state": clean(source.get("province")) if is_bangkok else prefixed("จ.", "province"),
		"pincode": clean(source.get("postcode")),
		"branch_code": branch,
		"custom_branch_no": branch,
	}


def _compare(current: dict, proposed: dict, labels: dict) -> list:
	return [
		{
			"field": field,
			"label": label,
			"current": current.get(field) or "",
			"proposed": proposed.get(field) or "",
			"differs": clean(current.get(field)) != clean(proposed.get(field)),
		}
		for field, label in labels.items()
	]


def _is_duplicate_address(address: dict, source: dict) -> bool:
	"""The same postcode and house number already in line 1 means this address likely exists."""
	house = normalize_search(source.get("house_no"))
	return bool(
		house
		and clean(address.get("pincode")) == clean(source.get("postcode"))
		and house in normalize_search(address.get("address_line1"))
	)


def _linked_addresses(party_type: str, party: str, proposed: dict, source: dict) -> list:
	names = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": party_type, "link_name": party},
		pluck="parent",
	)
	if not names:
		return []
	fields = ["name", "address_title", *ADDRESS_UPDATABLE]
	result = []
	for address in frappe.get_list("Address", filters={"name": ("in", names)}, fields=fields):
		result.append(
			{
				"name": address.name,
				"title": address.address_title,
				"is_duplicate": _is_duplicate_address(address, source),
				"can_write": frappe.has_permission("Address", "write", doc=address.name),
				"compare": _compare(address, proposed, _ADDRESS_LABELS),
			}
		)
	return result


def _check_party_type(party_type: str) -> dict:
	if party_type not in PARTIES:
		frappe.throw("ประเภทไม่ถูกต้อง")
	return PARTIES[party_type]


@frappe.whitelist()
def get_preview(
	party_type: str, key: str = "", tax_id: str = "", branch: str = "", online: int | str = 0
) -> dict:
	"""Read-only. Shows what exists in ERPNext and how it differs from RD's data."""
	config = _check_party_type(party_type)
	frappe.has_permission(party_type, "read", throw=True)

	source = _load_source(key, tax_id, branch, online)
	proposed = _proposed_party(source)
	address = _proposed_address(source)
	name_field = config["name_field"]
	fields = ["name", name_field, "tax_id", "branch_code", "disabled"]

	matches = []
	for row in frappe.get_list(
		party_type, filters={"tax_id": source["tax_id"]}, fields=fields, order_by="name asc"
	):
		current = {"party_name": row.get(name_field), "tax_id": row.tax_id, "branch_code": row.branch_code}
		matches.append(
			{
				"name": row.name,
				"party_name": row.get(name_field),
				"tax_id": row.tax_id,
				"branch_code": row.branch_code,
				"disabled": row.disabled,
				"can_write": frappe.has_permission(party_type, "write", doc=row.name),
				"compare": _compare(
					current,
					proposed,
					{"party_name": "ชื่อ", "tax_id": "เลขประจำตัวผู้เสียภาษี", "branch_code": "Branch Code"},
				),
				"addresses": _linked_addresses(party_type, row.name, address, source),
			}
		)

	matched = [row["name"] for row in matches]
	same_name = frappe.get_list(
		party_type,
		filters={name_field: proposed["party_name"], "name": ("not in", matched or [""])},
		fields=fields,
		order_by="name asc",
	)

	group_doctype = "Customer Group" if party_type == "Customer" else "Supplier Group"
	groups = frappe.get_list(group_doctype, filters={"is_group": 0}, pluck="name", order_by="name asc")
	if party_type == "Customer":
		default_group = (
			DEFAULT_VAT_CUSTOMER_GROUP
			if DEFAULT_VAT_CUSTOMER_GROUP in groups
			else frappe.db.get_single_value("Selling Settings", "customer_group")
		)
	else:
		default_group = frappe.db.get_single_value("Buying Settings", "supplier_group")

	return {
		"source": to_display(source),
		"party_type": party_type,
		"proposed": proposed,
		"proposed_address": address,
		"address_text": format_address(source),
		"matches": matches,
		"same_name": [
			{"name": row.name, "party_name": row.get(name_field), "tax_id": row.tax_id} for row in same_name
		],
		"can_create": frappe.has_permission(party_type, "create"),
		"can_create_address": frappe.has_permission("Address", "create"),
		"groups": groups,
		"default_group": default_group,
	}


def _create_party(party_type: str, config: dict, proposed: dict, group: str):
	values = {
		"doctype": party_type,
		config["name_field"]: proposed["party_name"],
		config["type_field"]: proposed["party_type_value"],
		config["group_field"]: group,
		"tax_id": proposed["tax_id"],
		"branch_code": proposed["branch_code"],
	}
	if party_type == "Customer":
		values["territory"] = frappe.db.get_single_value("Selling Settings", "territory")
	doc = frappe.get_doc(values)
	doc.insert()
	return doc


def _update_party(party_type: str, config: dict, target: str, proposed: dict, fields: list):
	doc = frappe.get_doc(party_type, target)
	doc.check_permission("write")
	for field in fields:
		if field == "party_name":
			doc.set(config["name_field"], proposed["party_name"])
		else:
			doc.set(field, proposed[field])
	doc.save()
	return doc


def _create_address(party_type: str, party, values: dict, source: dict):
	name = clean(source.get("establishment_name")) or clean(source.get("taxpayer_name"))
	doc = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": name,
			"address_type": "Billing",
			"country": "Thailand",
			# Left off: when set, the erpnext_thailand hook overwrites the linked party's tax details.
			"update_tax_branch": 0,
			"links": [{"link_doctype": party_type, "link_name": party}],
			**values,
		}
	)
	doc.insert()
	return doc


def _update_address(target: str, values: dict, fields: list):
	doc = frappe.get_doc("Address", target)
	doc.check_permission("write")
	for field in fields:
		doc.set(field, values[field])
	doc.save()
	return doc


@frappe.whitelist(methods=["POST"])
def apply(
	party_type: str,
	action: str,
	key: str = "",
	tax_id: str = "",
	branch: str = "",
	online: int | str = 0,
	target: str = "",
	fields: str | list | None = None,
	group: str = "",
	address_action: str = "none",
	address_target: str = "",
	address_fields: str | list | None = None,
	confirmed: int | str = 0,
) -> dict:
	"""Create or update after the user has confirmed. Everything rolls back together on an error."""
	config = _check_party_type(party_type)
	if not cint(confirmed):
		frappe.throw("ต้องได้รับการยืนยันจากผู้ใช้งานก่อน")
	if action not in ("create", "update"):
		frappe.throw("การดำเนินการไม่ถูกต้อง")
	if address_action not in ("none", "create", "update"):
		frappe.throw("การดำเนินการกับที่อยู่ไม่ถูกต้อง")

	fields = set(frappe.parse_json(fields) or []) & PARTY_UPDATABLE
	address_fields = set(frappe.parse_json(address_fields) or []) & ADDRESS_UPDATABLE

	source = _load_source(key, tax_id, branch, online)
	proposed = _proposed_party(source)
	address_values = _proposed_address(source)

	if action == "create":
		if not group:
			frappe.throw("กรุณาเลือกกลุ่ม")
		party = _create_party(party_type, config, proposed, group)
	else:
		if not target:
			frappe.throw("กรุณาเลือกรายการที่ต้องการอัปเดต")
		party = _update_party(party_type, config, target, proposed, sorted(fields))

	address_name = None
	if address_action == "create":
		address_name = _create_address(party_type, party.name, address_values, source).name
	elif address_action == "update":
		if not address_target:
			frappe.throw("กรุณาเลือกที่อยู่ที่ต้องการอัปเดต")
		linked = frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Address",
				"parent": address_target,
				"link_doctype": party_type,
				"link_name": party.name,
			},
			limit=1,
		)
		if not linked:
			frappe.throw("ที่อยู่นี้ไม่ได้เชื่อมกับรายการที่เลือก")
		address_name = _update_address(address_target, address_values, sorted(address_fields)).name

	return {"party": party.name, "address": address_name}
