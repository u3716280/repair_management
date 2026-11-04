"""Live lookups against the Revenue Department VAT web service, used when a tax ID is not found offline.

Offline search lives in repair_management.rd_vat.search. RD's SOAP name search returns no results, so only
tax ID lookups are made here.

Service documentation: https://www.rd.go.th/42535.html
Sample requests: https://www.rd.go.th/fileadmin/webservice/Sample_SOAP_Request_V5.pdf
"""

import re
from xml.sax.saxutils import escape

import frappe
import requests
from frappe.utils import cint
from lxml import etree

from repair_management.rd_vat.normalize import clean, clean_name, is_valid_tin, normalize_tin, to_display

VAT_URL = "https://rdws.rd.go.th/serviceRD3/vatserviceRD3.asmx"
VAT_NS = "https://rdws.rd.go.th/serviceRD3/vatserviceRD3"

# RD documents these fixed values for its public services.
RD_USERNAME = "anonymous"
RD_PASSWORD = "anonymous"

TIMEOUT_SECONDS = 15
MAX_BRANCH_NUMBER = 99998  # same limit as the RD website

_SOAP_FIELDS = {
	"building_name": "vBuildingName",
	"room_no": "vRoomNumber",
	"floor_no": "vFloorNumber",
	"village": "vVillageName",
	"house_no": "vHouseNumber",
	"moo": "vMooNumber",
	"soi": "vSoiName",
	"yaek": "vYaek",
	"road": "vStreetName",
	"subdistrict": "vThambol",
	"district": "vAmphur",
	"province": "vProvince",
	"postcode": "vPostCode",
	"vat_approval_date": "vBusinessFirstDate",
}


class RDServiceError(Exception):
	"""RD did not give a usable answer (network failure, HTTP error, SOAP fault, bad XML)."""


def build_envelope(namespace: str, values: dict) -> bytes:
	"""Build a SOAP 1.2 `Service` request. All values are XML-escaped."""
	fields = "".join(f"<{key}>{escape(str(value))}</{key}>" for key, value in values.items())
	return (
		'<?xml version="1.0" encoding="utf-8"?>'
		'<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
		f'<soap:Body><Service xmlns="{namespace}">{fields}</Service></soap:Body>'
		"</soap:Envelope>"
	).encode()


def _local_name(element) -> str:
	return etree.QName(element).localname if isinstance(element.tag, str) else ""


def parse_service_response(content: bytes) -> dict | None:
	"""Turn a `Service` response into {field: [values]}.

	RD returns one parallel array per field, each holding one <anyType> per matching record.
	Returns None when the response has no ServiceResult (RD answered, but with nothing).
	"""
	parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
	try:
		root = etree.fromstring(content, parser=parser)
	except etree.XMLSyntaxError as e:
		raise RDServiceError(f"Invalid XML from RD: {e}") from e

	for element in root.iter():
		if _local_name(element) == "Fault":
			raise RDServiceError("SOAP fault: " + " ".join(element.itertext()).strip())

	result = next((el for el in root.iter() if _local_name(el) == "ServiceResult"), None)
	if result is None:
		return None

	fields = {}
	for field in result:
		values = [(item.text or "").strip() for item in field if _local_name(item) == "anyType"]
		if not values and (field.text or "").strip():
			values = [field.text.strip()]
		fields[_local_name(field)] = values
	return fields


def _post(values: dict) -> dict | None:
	try:
		response = requests.post(
			VAT_URL,
			data=build_envelope(VAT_NS, {"username": RD_USERNAME, "password": RD_PASSWORD, **values}),
			headers={"Content-Type": "application/soap+xml; charset=utf-8"},
			timeout=TIMEOUT_SECONDS,
		)
	except requests.RequestException as e:
		raise RDServiceError(f"Could not reach RD: {e}") from e

	# RD reports SOAP faults as HTTP 500, so parse first to keep the fault text in the log.
	fields = parse_service_response(response.content)
	if not response.ok:
		raise RDServiceError(f"RD returned HTTP {response.status_code}")
	return fields


def _join_name(*parts) -> str:
	return " ".join(filter(None, (clean(part) for part in parts)))


def fields_to_rows(fields: dict) -> list[dict]:
	"""Zip RD's parallel arrays into rows shaped like RD VAT Taxpayer, ready for display."""
	count = max((len(values) for key, values in fields.items() if key != "vmsgerr"), default=0)

	def value(key, index):
		values = fields.get(key) or []
		return values[index] if index < len(values) else ""

	rows = []
	for index in range(count):
		row = {
			"tax_id": clean(value("vNID", index)) or clean(value("vtin", index)),
			"branch_number": clean(value("vBranchNumber", index)),
			"taxpayer_name": clean_name(
				_join_name(value("vtitleName", index), value("vName", index), value("vSurname", index))
			),
			"establishment_name": clean_name(
				_join_name(value("vBranchTitleName", index), value("vBranchName", index))
			),
		}
		for field, soap_field in _SOAP_FIELDS.items():
			row[field] = clean(value(soap_field, index))
		rows.append(to_display(row))
	return rows


def _rd_message(fields: dict) -> str:
	"""RD's own message, without the '<br> Data not found' English half."""
	messages = fields.get("vmsgerr") or []
	return re.split(r"<br\s*/?>", messages[0])[0].strip() if messages else ""


def lookup_tin(tin: str, branch: int = 0) -> dict:
	"""Look up one tax ID. Status is ok, not_found, empty or unavailable."""
	try:
		fields = _post(
			{"TIN": tin, "Name": "", "ProvinceCode": 0, "BranchNumber": cint(branch), "AmphurCode": 0}
		)
	except RDServiceError as e:
		frappe.log_error(title="VAT Info: RD service error", message=str(e))
		return {"status": "unavailable", "rows": []}

	if fields is None:
		return {"status": "empty", "rows": []}

	rows = fields_to_rows(fields)
	if rows:
		return {"status": "ok", "rows": rows}

	message = _rd_message(fields)
	return (
		{"status": "not_found", "rows": [], "message": message}
		if message
		else {"status": "empty", "rows": []}
	)


@frappe.whitelist()
def live_lookup(tax_id: str, branch: str | int | None = None) -> dict:
	"""Manual live check from the detail dialog."""
	frappe.has_permission("RD VAT Taxpayer", "read", throw=True)
	tin = normalize_tin(tax_id)
	if not is_valid_tin(tin):
		frappe.throw("เลขประจำตัวผู้เสียภาษีอากร (13 หลัก) ไม่ถูกต้องตามหลักเกณฑ์ กรุณาตรวจสอบอีกครั้ง")
	branch_number = cint(branch)
	if branch_number < 0 or branch_number > MAX_BRANCH_NUMBER:
		frappe.throw(f"เลขที่สาขา จะต้องมีค่าไม่เกิน {MAX_BRANCH_NUMBER}")
	return lookup_tin(tin, branch_number)
