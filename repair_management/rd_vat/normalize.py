"""Pure helpers shared by the RD VAT importer, search and Customer/Supplier code. No database access."""

import hashlib
import json
import re
import unicodedata

# Column order of RD's CSV files.
CSV_FIELDS = (
	"tax_id",
	"branch_number",
	"taxpayer_name",
	"establishment_name",
	"building_name",
	"room_no",
	"floor_no",
	"village",
	"house_no",
	"moo",
	"soi",
	"yaek",
	"road",
	"subdistrict",
	"district",
	"province",
	"postcode",
	"vat_approval_date",
)

# Must match the field lengths in rd_vat_taxpayer.json.
MAX_LENGTHS = {
	"tax_id": 13,
	"branch_number": 5,
	"taxpayer_name": 200,
	"establishment_name": 200,
	"building_name": 100,
	"room_no": 60,
	"floor_no": 40,
	"village": 60,
	"house_no": 80,
	"moo": 20,
	"soi": 80,
	"yaek": 40,
	"road": 60,
	"subdistrict": 40,
	"district": 40,
	"province": 40,
	"postcode": 10,
	"vat_approval_date": 20,
}

SEARCH_TEXT_LENGTH = 340
# Separates the two names in search_text so a search can be limited to one of them.
SEARCH_SEPARATOR = "\x1f"
BANGKOK_PROVINCE = "กรุงเทพมหานคร"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‍﻿]")
_WHITESPACE = re.compile(r"\s+")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def clean(value) -> str:
	"""Trim padding and collapse spaces. RD uses both blank and "-" for empty values."""
	text = _CONTROL_CHARS.sub("", str(value or ""))
	text = _WHITESPACE.sub(" ", text).strip()
	return "" if text == "-" else text


def clean_name(value) -> str:
	"""Names may end in " -" where RD's surname column was empty."""
	return re.sub(r"(\s+-)+$", "", clean(value))


def normalize_search(value) -> str:
	"""Normalize text for matching, so spacing and equivalent Thai spellings do not matter."""
	text = unicodedata.normalize("NFC", _CONTROL_CHARS.sub("", str(value or "")))
	text = text.replace("ํา", "ำ")  # nikhahit + sara aa is written the same as sara am
	return _WHITESPACE.sub("", text).lower()


def build_search_text(taxpayer_name, establishment_name) -> str:
	text = normalize_search(taxpayer_name) + SEARCH_SEPARATOR + normalize_search(establishment_name)
	return text[:SEARCH_TEXT_LENGTH]


def is_valid_tin(tin) -> bool:
	"""Check the length and check digit of a 13-digit Thai tax ID."""
	if not re.fullmatch(r"[0-9]{13}", str(tin or "")):
		return False
	total = sum(int(digit) * (13 - index) for index, digit in enumerate(tin[:12]))
	return (11 - total % 11) % 10 == int(tin[12])


def normalize_tin(value) -> str:
	return re.sub(r"[-\s]", "", str(value or ""))


def make_key(tax_id, branch_number) -> str:
	return f"{tax_id}-{branch_number}"


def record_hash(row: dict) -> str:
	"""Hash of the source fields only, so a new file date alone does not count as a change."""
	payload = json.dumps([row.get(field) or "" for field in CSV_FIELDS], ensure_ascii=False)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pad_branch(branch_number) -> str:
	"""ERPNext's branch_code fields use five digits (00000 = head office)."""
	return str(branch_number or "0").zfill(5)


def branch_label(branch_number) -> str:
	text = str(branch_number if branch_number is not None else "")
	if text == "":
		return ""
	return "สำนักงานใหญ่" if text.isdigit() and int(text) == 0 else pad_branch(text)


def format_address(row: dict) -> str:
	is_bangkok = clean(row.get("province")) == BANGKOK_PROVINCE
	parts = [
		("อาคาร", "building_name"),
		("ห้อง ", "room_no"),
		("ชั้น ", "floor_no"),
		("หมู่บ้าน", "village"),
		("", "house_no"),
		("หมู่ ", "moo"),
		("ซอย", "soi"),
		("แยก", "yaek"),
		("ถนน", "road"),
		("แขวง" if is_bangkok else "ตำบล", "subdistrict"),
		("เขต" if is_bangkok else "อำเภอ", "district"),
		("" if is_bangkok else "จังหวัด", "province"),
		("", "postcode"),
	]
	return " ".join(prefix + clean(row.get(key)) for prefix, key in parts if clean(row.get(key)))


def format_be_date(value) -> str:
	"""RD dates are already Buddhist Era (2535-01-03), so only the layout changes."""
	text = clean(value)
	match = _DATE.match(text)
	return f"{match.group(3)}/{match.group(2)}/{match.group(1)}" if match else text


def to_display(row: dict) -> dict:
	"""Add the formatted values the page shows, whether the row came from the database or SOAP."""
	return {
		**row,
		"branch_label": branch_label(row.get("branch_number")),
		"address": format_address(row),
		"registered_date": format_be_date(row.get("vat_approval_date")),
	}
