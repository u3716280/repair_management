"""Import one RD VAT CSV file into RD VAT Taxpayer in batches.

Safe to re-run: the primary key is {tax_id}-{branch_number}, and a row is only rewritten if its content
hash differs. Rows absent from a file are flagged, never deleted, and never treated as deregistered.
"""

import csv
import io
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import frappe
from frappe.utils import getdate, now_datetime
from frappe.utils.file_manager import save_file

from repair_management.rd_vat.csv_reader import CsvValidationError, ParsedRow, RDVatCsv
from repair_management.rd_vat.normalize import CSV_FIELDS, make_key
from repair_management.rd_vat.search import clear_location_cache

TAXPAYER = "RD VAT Taxpayer"
TAXPAYER_TABLE = "`tabRD VAT Taxpayer`"
LOG = "RD VAT Import Log"
CHANGE = "RD VAT Taxpayer Change"

DEFAULT_BATCH_SIZE = 2000
# Below this share of the previous import's rows, the file looks truncated: don't flag rows as missing.
MISSING_GUARD_RATIO = 0.9
MAX_ERROR_ROWS = 5000
FINISHED_STATUSES = ("Success", "Needs Review")

_DATA_COLUMNS = (*CSV_FIELDS, "search_text", "record_hash", "data_incomplete")
_META_COLUMNS = ("creation", "modified", "modified_by", "owner", "docstatus", "idx")
_INSERT_COLUMNS = (
	"name",
	*_DATA_COLUMNS,
	"source_dataset",
	"source_file_date",
	"imported_on",
	"first_seen_import",
	"last_seen_import",
	"in_latest_dataset",
	*_META_COLUMNS,
)
_CHANGE_COLUMNS = (
	"name",
	"taxpayer",
	"change_type",
	"import_log",
	"changed_fields",
	"old_values",
	"new_values",
	*_META_COLUMNS,
)


@dataclass
class ImportRequest:
	path: str
	dataset: str
	source_type: str
	file_name: str
	file_date: object
	file_hash: str
	file_size: int = 0
	source_url: str = ""
	etag: str = ""
	last_modified_header: str = ""
	batch_size: int = DEFAULT_BATCH_SIZE
	triggered_by: str = ""


def create_log(status: str = "Running", **values) -> str:
	doc = frappe.get_doc(
		{
			"doctype": LOG,
			"status": status,
			"started_at": now_datetime(),
			"owner": frappe.session.user,
			**values,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def last_finished_log(dataset: str) -> dict | None:
	logs = frappe.get_all(
		LOG,
		filters={"dataset": dataset, "status": ("in", FINISHED_STATUSES)},
		fields=["name", "file_hash", "etag", "last_modified_header", "valid_rows", "file_date"],
		order_by="started_at desc",
		limit=1,
	)
	return logs[0] if logs else None


def run_import(request: ImportRequest, commit: Callable | None = None) -> str:
	"""Validate, then import. Returns the log name. Failures are recorded in the log, not raised."""
	commit = commit or frappe.db.commit
	previous = last_finished_log(request.dataset)
	log_name = create_log(
		dataset=request.dataset,
		source_type=request.source_type,
		file_name=request.file_name,
		source_url=request.source_url,
		file_hash=request.file_hash,
		file_size=request.file_size,
		file_date=getdate(request.file_date),
		etag=request.etag,
		last_modified_header=request.last_modified_header,
		triggered_by=request.triggered_by or frappe.session.user,
		is_baseline=0 if previous else 1,
	)
	commit()

	try:
		_validate_and_import(request, log_name, previous, commit)
	except CsvValidationError as e:
		_finish(log_name, "Failed", commit, message=str(e))
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title=f"RD VAT import failed: {request.dataset}", reference_doctype=LOG, reference_name=log_name
		)
		_finish(
			log_name,
			"Failed",
			commit,
			message="การนำเข้าไม่สำเร็จ ดูรายละเอียดใน Error Log สามารถนำเข้าใหม่ได้โดยไม่เกิดข้อมูลซ้ำ",
		)
	return log_name


def _finish(log_name: str, status: str, commit: Callable, **values) -> None:
	frappe.db.set_value(
		LOG, log_name, {"status": status, "finished_at": now_datetime(), **values}, update_modified=False
	)
	commit()


def _validate_and_import(
	request: ImportRequest, log_name: str, previous: dict | None, commit: Callable
) -> None:
	reader = RDVatCsv(request.path)
	stats = reader.validate()
	frappe.db.set_value(
		LOG,
		log_name,
		{
			"encoding": stats.encoding,
			"total_rows": stats.total_rows,
			"valid_rows": stats.valid_rows,
			"rows_error": stats.rejected_rows,
			"rows_warning": stats.warning_rows,
			"nul_bytes": stats.nul_bytes,
		},
		update_modified=False,
	)
	commit()

	is_baseline = previous is None
	file_date = getdate(request.file_date)
	counts = {
		"rows_new": 0,
		"rows_updated": 0,
		"rows_unchanged": 0,
		"rows_superseded": 0,
		"rows_reappeared": 0,
	}
	rejected = []
	processed = 0

	for batch in _batches(reader, request.batch_size or DEFAULT_BATCH_SIZE, rejected):
		_import_batch(batch, request.dataset, file_date, log_name, is_baseline, counts)
		processed += len(batch)
		frappe.db.set_value(LOG, log_name, {"processed_rows": processed, **counts}, update_modified=False)
		commit()

	error_file = _save_rejected(log_name, rejected)

	status, message, missing = "Success", "", 0
	if previous and stats.valid_rows < (previous.get("valid_rows") or 0) * MISSING_GUARD_RATIO:
		status = "Needs Review"
		message = (
			f"ไฟล์นี้มีรายการที่ถูกต้อง {stats.valid_rows:,} รายการ น้อยกว่าครั้งก่อน "
			f"({previous['valid_rows']:,}) เกิน 10% จึงไม่ได้ทำเครื่องหมายรายการที่หายไป กรุณาตรวจสอบไฟล์"
		)
	else:
		missing = _flag_missing(request.dataset, file_date, log_name, commit)

	_finish(log_name, status, commit, message=message, rows_missing=missing, error_file=error_file, **counts)
	clear_location_cache()


def _batches(reader: RDVatCsv, size: int, rejected: list) -> Iterator[list[dict]]:
	batch = []
	for row in reader.rows():
		if not row.data:
			if len(rejected) < MAX_ERROR_ROWS:
				rejected.append(row)
			continue
		batch.append(row.data)
		if len(batch) >= size:
			yield batch
			batch = []
	if batch:
		yield batch


def _import_batch(
	batch: list[dict], dataset: str, file_date, log_name: str, is_baseline: bool, counts: dict
) -> None:
	now = now_datetime()
	user = frappe.session.user
	rows = {make_key(row["tax_id"], row["branch_number"]): row for row in batch}
	existing = {
		row.name: row
		for row in frappe.db.sql(
			f"""select name, record_hash, source_file_date, source_dataset, in_latest_dataset
			from {TAXPAYER_TABLE} where name in %(names)s""",
			{"names": tuple(rows)},
			as_dict=True,
		)
	}

	new, changed, unchanged, changes = [], [], [], []
	for key, row in rows.items():
		current = existing.get(key)
		if not current:
			new.append(key)
		elif current.source_file_date and getdate(current.source_file_date) > file_date:
			# The newer file wins, whichever order the files are imported in.
			counts["rows_superseded"] += 1
		elif current.record_hash != row["record_hash"]:
			changed.append(key)
		else:
			unchanged.append(key)

	if new:
		values = [
			(
				key,
				*(rows[key][column] for column in _DATA_COLUMNS),
				dataset,
				file_date,
				now,
				log_name,
				log_name,
				1,
				now,
				now,
				user,
				user,
				0,
				0,
			)
			for key in new
		]
		frappe.db.bulk_insert(TAXPAYER, list(_INSERT_COLUMNS), values)
		counts["rows_new"] += len(new)
		if not is_baseline:
			changes += [_change_row(key, "New", log_name, now, user) for key in new]

	if changed:
		changes += _update_changed(changed, rows, dataset, file_date, log_name, now, user)
		counts["rows_updated"] += len(changed)

	if unchanged:
		frappe.db.sql(
			f"""update {TAXPAYER_TABLE}
			set last_seen_import=%(log)s, source_file_date=%(date)s, source_dataset=%(dataset)s,
				in_latest_dataset=1, missing_since=null
			where name in %(names)s""",
			{"log": log_name, "date": file_date, "dataset": dataset, "names": tuple(unchanged)},
		)
		counts["rows_unchanged"] += len(unchanged)

	for key in (*changed, *unchanged):
		if not existing[key].in_latest_dataset:
			counts["rows_reappeared"] += 1
			changes.append(_change_row(key, "Reappeared", log_name, now, user))

	if changes:
		frappe.db.bulk_insert(CHANGE, list(_CHANGE_COLUMNS), changes)


def _update_changed(keys: list, rows: dict, dataset, file_date, log_name, now, user) -> list:
	"""Rewrite changed rows and return their history records."""
	columns = ", ".join(("name", "source_dataset", *CSV_FIELDS))
	old_rows = {
		row.name: row
		for row in frappe.db.sql(
			f"select {columns} from {TAXPAYER_TABLE} where name in %(names)s",
			{"names": tuple(keys)},
			as_dict=True,
		)
	}
	assignments = ", ".join(f"`{column}`=%({column})s" for column in _DATA_COLUMNS)
	history = []
	for key in keys:
		row, old = rows[key], old_rows[key]
		frappe.db.sql(
			f"""update {TAXPAYER_TABLE} set {assignments},
				source_dataset=%(_dataset)s, source_file_date=%(_date)s, imported_on=%(_now)s,
				last_seen_import=%(_log)s, in_latest_dataset=1, missing_since=null,
				modified=%(_now)s, modified_by=%(_user)s
			where name=%(_key)s""",
			{
				**{column: row[column] for column in _DATA_COLUMNS},
				"_dataset": dataset,
				"_date": file_date,
				"_now": now,
				"_log": log_name,
				"_user": user,
				"_key": key,
			},
		)
		fields = [field for field in CSV_FIELDS if (old.get(field) or "") != (row.get(field) or "")]
		change_type = "Moved" if old.source_dataset != dataset else "Changed"
		history.append(
			_change_row(
				key,
				change_type,
				log_name,
				now,
				user,
				fields,
				{field: old.get(field) for field in fields},
				{field: row.get(field) for field in fields},
			)
		)
	return history


def _change_row(key, change_type, log_name, now, user, fields=None, old=None, new=None) -> tuple:
	return (
		frappe.generate_hash(length=16),
		key,
		change_type,
		log_name,
		", ".join(fields or []),
		json.dumps(old, ensure_ascii=False) if old else None,
		json.dumps(new, ensure_ascii=False) if new else None,
		now,
		now,
		user,
		user,
		0,
		0,
	)


def _flag_missing(dataset: str, file_date, log_name: str, commit: Callable) -> int:
	"""Flag rows of this dataset absent from the file. They stay searchable and are never deleted."""
	names = frappe.db.sql_list(
		f"""select name from {TAXPAYER_TABLE}
		where source_dataset=%(dataset)s and in_latest_dataset=1 and source_file_date<=%(date)s
			and (last_seen_import is null or last_seen_import!=%(log)s)""",
		{"dataset": dataset, "date": file_date, "log": log_name},
	)
	now, user = now_datetime(), frappe.session.user
	for start in range(0, len(names), DEFAULT_BATCH_SIZE):
		chunk = names[start : start + DEFAULT_BATCH_SIZE]
		frappe.db.sql(
			f"update {TAXPAYER_TABLE} set in_latest_dataset=0, missing_since=%(date)s where name in %(names)s",
			{"date": now.date(), "names": tuple(chunk)},
		)
		frappe.db.bulk_insert(
			CHANGE, list(_CHANGE_COLUMNS), [_change_row(key, "Missing", log_name, now, user) for key in chunk]
		)
		commit()
	return len(names)


def _save_rejected(log_name: str, rejected: list[ParsedRow]) -> str | None:
	if not rejected:
		return None
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow(["line", "reason", *CSV_FIELDS])
	for row in rejected:
		writer.writerow([row.line_no, row.reason, *row.raw])
	saved = save_file(
		f"{log_name}-rejected.csv",
		("﻿" + buffer.getvalue()).encode("utf-8"),
		LOG,
		log_name,
		is_private=1,
	)
	return saved.file_url
