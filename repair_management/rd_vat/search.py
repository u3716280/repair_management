"""Offline search over RD VAT Taxpayer, falling back to RD's live SOAP service for tax IDs."""

import re

import frappe
from frappe.utils import cint

from repair_management.rd_vat import search_file
from repair_management.rd_vat.normalize import (
	CSV_FIELDS,
	SEARCH_SEPARATOR,
	SEARCH_TEXT_LENGTH,
	is_valid_tin,
	normalize_search,
	normalize_tin,
	to_display,
)

TAXPAYER = "RD VAT Taxpayer"
TABLE = "`tabRD VAT Taxpayer`"
LOG = "RD VAT Import Log"
SEARCH_INDEX = "rd_vat_search_idx"

MIN_QUERY_LENGTH = 3
MAX_QUERY_LENGTH = 200
MAX_COUNT = 10000
QUERY_TIMEOUT_SECONDS = 15
PAGE_LENGTHS = (20, 50, 100)
LOCATION_CACHE_KEY = "rd_vat_locations"

# Every sort can be served from the covering search index plus the primary key.
SORTS = {
	"name": "search_text asc, name asc",
	"tax_id": "name asc",
	"province": "province asc, district asc, subdistrict asc, search_text asc",
}

_ROW_FIELDS = (
	"name",
	*CSV_FIELDS,
	"source_dataset",
	"source_file_date",
	"imported_on",
	"in_latest_dataset",
	"missing_since",
	"data_incomplete",
	"first_seen_import",
	"last_seen_import",
)


def ensure_search_index() -> None:
	"""Called on doctype update. search_text is already normalized, so compare it byte by byte."""
	collation = frappe.db.sql(
		"""select collation_name from information_schema.columns
		where table_schema=database() and table_name='tabRD VAT Taxpayer' and column_name='search_text'"""
	)
	if collation and collation[0][0] != "utf8mb4_bin":
		frappe.db.sql_ddl(
			f"alter table {TABLE} modify `search_text` varchar({SEARCH_TEXT_LENGTH}) "
			"character set utf8mb4 collate utf8mb4_bin"
		)
	frappe.db.add_index(
		TAXPAYER, ["province", "district", "subdistrict", "search_text"], index_name=SEARCH_INDEX
	)


def _escape_like(text: str) -> str:
	return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _timed(sql: str) -> str:
	return f"set statement max_statement_time={QUERY_TIMEOUT_SECONDS} for {sql}"


def _build_where(query, search_by, province, district, subdistrict, branch) -> tuple[list, dict, str, str]:
	"""Returns conditions, values, the exact tax ID if searching for one, and normalized name text."""
	conditions, values, exact_tin, name_text = [], {}, "", ""

	digits = normalize_tin(query)
	is_tax_id_search = search_by == "tax_id" or (search_by == "all" and digits.isdigit())

	if query and is_tax_id_search:
		if not digits.isdigit():
			frappe.throw("เลขประจำตัวผู้เสียภาษีต้องเป็นตัวเลข")
		if len(digits) == 13:
			if not is_valid_tin(digits):
				frappe.throw("เลขประจำตัวผู้เสียภาษีอากร (13 หลัก) ไม่ถูกต้องตามหลักเกณฑ์ กรุณาตรวจสอบอีกครั้ง")
			exact_tin = digits
			conditions.append("tax_id=%(tax_id)s")
			values["tax_id"] = digits
		elif len(digits) > 13:
			frappe.throw("เลขประจำตัวผู้เสียภาษีต้องไม่เกิน 13 หลัก")
		elif len(digits) < MIN_QUERY_LENGTH:
			frappe.throw(f"กรุณากรอกอย่างน้อย {MIN_QUERY_LENGTH} หลัก")
		else:
			conditions.append("tax_id like %(tax_prefix)s")
			values["tax_prefix"] = digits + "%"
	elif query:
		text = normalize_search(query)
		if len(text) < MIN_QUERY_LENGTH:
			frappe.throw(f"กรุณากรอกอย่างน้อย {MIN_QUERY_LENGTH} ตัวอักษร")
		name_text = text[:MAX_QUERY_LENGTH]
		like = _escape_like(name_text)
		if search_by == "taxpayer_name":
			values["search"] = f"%{like}%{SEARCH_SEPARATOR}%"
		elif search_by == "establishment_name":
			values["search"] = f"%{SEARCH_SEPARATOR}%{like}%"
		else:
			values["search"] = f"%{like}%"
		conditions.append("search_text like %(search)s")

	for field, value in (("province", province), ("district", district), ("subdistrict", subdistrict)):
		if value:
			conditions.append(f"{field}=%({field})s")
			values[field] = value

	if branch not in (None, ""):
		branch_text = str(branch).strip()
		if not re.fullmatch(r"[0-9]{1,5}", branch_text):
			frappe.throw("เลขที่สาขาต้องเป็นตัวเลขไม่เกิน 5 หลัก")
		# The key ends in the branch number, and the search index already holds the key.
		conditions.append("name like %(branch)s")
		values["branch"] = f"%-{int(branch_text)}"

	return conditions, values, exact_tin, name_text


def _offline_search(conditions, values, exact_tin, sort, start, page_length) -> tuple[list, int]:
	where = " and ".join(conditions)
	limits = {**values, "start": start, "length": page_length, "cap": MAX_COUNT + 1}
	total = frappe.db.sql(
		_timed(f"select count(*) from (select 1 from {TABLE} where {where} limit %(cap)s) matches"), limits
	)[0][0]
	if not total:
		return [], 0

	# Branches of one tax ID read best in numeric order; the key alone would put 10 before 2.
	order = "cast(branch_number as unsigned) asc" if exact_tin else SORTS.get(sort, SORTS["name"])
	names = frappe.db.sql_list(
		_timed(f"select name from {TABLE} where {where} order by {order} limit %(start)s, %(length)s"), limits
	)
	return _load_rows(names), total


def _load_rows(names: list) -> list:
	"""Load one page of rows, keeping the given order."""
	if not names:
		return []
	columns = ", ".join(f"`{field}`" for field in _ROW_FIELDS)
	rows = frappe.db.sql(
		f"select {columns} from {TABLE} where name in %(names)s", {"names": tuple(names)}, as_dict=True
	)
	by_name = {row.name: row for row in rows}
	return [_offline_row(by_name[name]) for name in names if name in by_name]


def _is_timeout(error: Exception) -> bool:
	"""Frappe does not always convert MariaDB's max_statement_time error (1969) to QueryTimeoutError."""
	return isinstance(error, frappe.QueryTimeoutError) or (bool(error.args) and error.args[0] == 1969)


def _offline_row(row) -> dict:
	return {**to_display(row), "key": row.name, "source": "offline"}


def _online_fallback(tin: str, branch) -> dict:
	from repair_management.repair_management.page.vatinfo.vatinfo import lookup_tin

	result = lookup_tin(tin, cint(branch) if branch not in (None, "") else 0)
	result["rows"] = [{**row, "source": "online"} for row in result["rows"]]
	return result


@frappe.whitelist()
def search(
	query: str = "",
	search_by: str = "all",
	province: str = "",
	district: str = "",
	subdistrict: str = "",
	branch: str = "",
	sort: str = "name",
	page: int | str = 1,
	page_length: int | str = 20,
) -> dict:
	frappe.has_permission(TAXPAYER, "read", throw=True)

	query = str(query or "").strip()
	if search_by not in ("all", "tax_id", "taxpayer_name", "establishment_name"):
		frappe.throw("ประเภทการค้นหาไม่ถูกต้อง")
	if not query and not province:
		frappe.throw("กรุณาระบุคำค้นหา หรือเลือกจังหวัด")

	page = max(cint(page), 1)
	page_length = cint(page_length) if cint(page_length) in PAGE_LENGTHS else PAGE_LENGTHS[0]
	start = (page - 1) * page_length

	conditions, values, exact_tin, name_text = _build_where(
		query, search_by, province, district, subdistrict, branch
	)
	response = {
		"status": "ok",
		"source": "offline",
		"rows": [],
		"total": 0,
		"capped": False,
		"page": page,
		"page_length": page_length,
	}

	if name_text:
		found = search_file.search(
			name_text,
			scope=search_by,
			province=province,
			district=district,
			subdistrict=subdistrict,
			branch=str(int(branch)) if str(branch or "").strip() else "",
			sort=sort,
			start=start,
			length=page_length,
			cap=MAX_COUNT,
		)
		if found is not None:
			response.update(rows=_load_rows(found.names), total=found.total, capped=found.capped)
			return response

	offline_failed = False
	try:
		rows, total = _offline_search(conditions, values, exact_tin, sort, start, page_length)
		response.update(rows=rows, total=min(total, MAX_COUNT), capped=total > MAX_COUNT)
	except Exception as e:
		if _is_timeout(e):
			if not exact_tin:
				response["status"] = "timeout"
				return response
		else:
			frappe.db.rollback()
			frappe.log_error(title="RD VAT offline search failed")
			if not exact_tin:
				response["status"] = "error"
				return response
		offline_failed = True

	if exact_tin and not response["rows"]:
		online = _online_fallback(exact_tin, branch)
		response.update(
			source="online",
			status=online["status"],
			rows=online["rows"],
			total=len(online["rows"]),
			message=online.get("message"),
			offline_failed=offline_failed,
			filters_ignored=bool(province or district or subdistrict),
		)
	return response


@frappe.whitelist()
def get_taxpayer(name: str) -> dict:
	frappe.has_permission(TAXPAYER, "read", throw=True)
	columns = ", ".join(f"`{field}`" for field in _ROW_FIELDS)
	rows = frappe.db.sql(f"select {columns} from {TABLE} where name=%(name)s", {"name": name}, as_dict=True)
	if not rows:
		frappe.throw("ไม่พบรายการนี้")
	return _offline_row(rows[0])


@frappe.whitelist()
def get_locations(province: str = "", district: str = "") -> list:
	"""Distinct values for the cascading filters, served from the search index and cached."""
	frappe.has_permission(TAXPAYER, "read", throw=True)
	cache_key = f"{province}|{district}"
	cached = frappe.cache.hget(LOCATION_CACHE_KEY, cache_key)
	if cached is not None:
		return cached

	if province and district:
		sql = f"select distinct subdistrict from {TABLE} where province=%(p)s and district=%(d)s and subdistrict!=''"
	elif province:
		sql = f"select distinct district from {TABLE} where province=%(p)s and district!=''"
	else:
		sql = f"select distinct province from {TABLE} where province!=''"
	values = sorted(frappe.db.sql_list(_timed(sql), {"p": province, "d": district}))
	frappe.cache.hset(LOCATION_CACHE_KEY, cache_key, values)
	return values


def clear_location_cache() -> None:
	frappe.cache.delete_value(LOCATION_CACHE_KEY)


@frappe.whitelist()
def get_status() -> dict:
	"""Data dates for the banner, plus import controls for System Managers."""
	from repair_management.rd_vat import sync

	frappe.has_permission(TAXPAYER, "read", throw=True)
	datasets = []
	for dataset in sync.DATASETS:
		logs = frappe.get_all(
			LOG,
			filters={"dataset": dataset, "status": ("in", ("Success", "Needs Review"))},
			fields=["file_date", "finished_at", "valid_rows"],
			order_by="started_at desc",
			limit=1,
		)
		datasets.append({"dataset": dataset, **(logs[0] if logs else {})})

	response = {"datasets": datasets, "is_admin": "System Manager" in frappe.get_roles()}
	if response["is_admin"]:
		response.update(
			running=sync.is_running(),
			auto_update=sync.get_settings()["auto_update"],
			logs=frappe.get_all(
				LOG,
				fields=[
					"name",
					"status",
					"dataset",
					"source_type",
					"started_at",
					"file_date",
					"total_rows",
					"processed_rows",
					"rows_new",
					"rows_updated",
					"rows_unchanged",
					"rows_superseded",
					"rows_missing",
					"rows_error",
					"message",
				],
				order_by="started_at desc",
				limit=8,
			),
		)
	return response
