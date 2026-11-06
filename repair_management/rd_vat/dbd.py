"""Juristic person lookups against the Department of Business Development (DBD) open API.

A juristic person's 13-digit tax ID is its DBD registration number. The API needs no key, but it sits behind
an Incapsula WAF that answers with an HTML page when called too often, so results are cached and calls are
only made when a user asks.

The API has no directors, shareholders or financial statements; those are only on DBD DataWarehouse.
"""

import frappe
import requests

from repair_management.rd_vat.normalize import BANGKOK_PROVINCE, clean, is_valid_tin, normalize_tin

DBD_URL = "https://openapi.dbd.go.th/api/v1/juristic_person/{}"
TIMEOUT_SECONDS = 15
CACHE_KEY = "vatinfo:dbd:{}"
CACHE_FOUND_SECONDS = 24 * 60 * 60
CACHE_NOT_FOUND_SECONDS = 60 * 60
SUCCESS_CODE = "1000"
NOT_FOUND_CODE = "1004"


class DBDServiceError(Exception):
	"""DBD did not give a usable answer (network failure, HTTP error, WAF page, bad JSON)."""


def _text(value) -> str:
	return clean(value) if isinstance(value, str | int | float) else ""


def _iso_date(value) -> str:
	text = _text(value)
	return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 and text.isdigit() else ""


def _amount(value) -> float | None:
	try:
		return float(value)
	except (TypeError, ValueError):
		return None


def _address(data: dict) -> str:
	address = ((data.get("cd:OrganizationJuristicAddress") or {}).get("cr:AddressType")) or {}
	subdistrict = _text((address.get("cd:CitySubDivision") or {}).get("cr:CitySubDivisionTextTH"))
	district = _text((address.get("cd:City") or {}).get("cr:CityTextTH"))
	province = _text((address.get("cd:CountrySubDivision") or {}).get("cr:CountrySubDivisionTextTH"))
	# DBD gives the district with its prefix (เขต/อำเภอ) but the sub-district without one.
	if subdistrict and not subdistrict.startswith(("แขวง", "ตำบล")):
		subdistrict = ("แขวง" if province == BANGKOK_PROVINCE else "ตำบล") + subdistrict
	parts = [_text(address.get("cd:Address")), subdistrict, district, province]
	return " ".join(part for part in parts if part)


def _objective(data: dict) -> str:
	objective = (data.get("cd:OrganizationJuristicObjective") or {}).get("td:JuristicObjective") or {}
	if isinstance(objective, list):
		objective = objective[0] if objective else {}
	code = _text(objective.get("td:JuristicObjectiveCode"))
	text = _text(objective.get("td:JuristicObjectiveTextTH"))
	return f"{code} {text}".strip() if text else code


def to_display(data: dict) -> dict:
	"""Flatten one DBD juristic person record into the keys the VATinfo page shows."""
	return {
		"tax_id": _text(data.get("cd:OrganizationJuristicID")),
		"name_th": _text(data.get("cd:OrganizationJuristicNameTH")),
		"name_en": _text(data.get("cd:OrganizationJuristicNameEN")),
		"juristic_type": _text(data.get("cd:OrganizationJuristicType")),
		"status": _text(data.get("cd:OrganizationJuristicStatus")),
		"register_date": _iso_date(data.get("cd:OrganizationJuristicRegisterDate")),
		"objective": _objective(data),
		"register_capital": _amount(data.get("cd:OrganizationJuristicRegisterCapital")),
		"paid_up_capital": _amount(data.get("cd:OrganizationJuristicPaidUpCapital")),
		"branch_name": _text(data.get("cd:OrganizationJuristicBranchName")),
		"address": _address(data),
	}


def _fetch(tin: str) -> dict | None:
	"""The DBD record for a tax ID, or None if DBD has none."""
	try:
		response = requests.get(DBD_URL.format(tin), timeout=TIMEOUT_SECONDS)
	except requests.RequestException as e:
		raise DBDServiceError(f"Request failed: {e}") from e

	# DBD answers "not found" with HTTP 200 and code 1004; any other HTTP status is a failure.
	if response.status_code != 200:
		raise DBDServiceError(f"HTTP {response.status_code}: {response.text[:500]}")
	# DBD labels its JSON with the wrong content type, so parse by content, not by header.
	try:
		payload = response.json()
	except ValueError as e:
		raise DBDServiceError(f"Not JSON (WAF page?): {response.text[:500]}") from e
	if not isinstance(payload, dict):
		raise DBDServiceError(f"Unexpected JSON: {response.text[:500]}")

	status = payload.get("status") or {}
	code = str(status.get("code"))
	records = payload.get("data") or []
	if code == NOT_FOUND_CODE or (code == SUCCESS_CODE and not records):
		return None
	if code != SUCCESS_CODE:
		raise DBDServiceError(f"DBD status {code}: {status.get('description')}")
	record = records[0].get("cd:OrganizationJuristicPerson") if isinstance(records[0], dict) else None
	return record or None


def lookup(tin: str) -> dict:
	"""Look up one juristic person. Status is ok, not_found or unavailable."""
	cache = frappe.cache()
	key = CACHE_KEY.format(tin)
	cached = cache.get_value(key)
	if cached:
		return cached

	try:
		record = _fetch(tin)
	except DBDServiceError as e:
		frappe.log_error(title="VAT Info: DBD service error", message=f"{tin}\n{e}")
		return {"status": "unavailable"}

	if record:
		result = {"status": "ok", "data": to_display(record)}
		cache.set_value(key, result, expires_in_sec=CACHE_FOUND_SECONDS)
	else:
		result = {"status": "not_found"}
		cache.set_value(key, result, expires_in_sec=CACHE_NOT_FOUND_SECONDS)
	return result


@frappe.whitelist()
def dbd_lookup(tax_id: str) -> dict:
	"""Juristic person data from DBD, for the VATinfo detail dialog."""
	frappe.has_permission("RD VAT Taxpayer", "read", throw=True)
	tin = normalize_tin(tax_id)
	if not is_valid_tin(tin):
		frappe.throw("เลขประจำตัวผู้เสียภาษีอากร (13 หลัก) ไม่ถูกต้องตามหลักเกณฑ์ กรุณาตรวจสอบอีกครั้ง")
	# Juristic person IDs start with 0; personal IDs are not registered at DBD.
	if not tin.startswith("0"):
		return {"status": "not_juristic"}
	return lookup(tin)
