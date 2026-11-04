"""Get RD's CSV files into the importer: one-click and monthly download, or manual upload in chunks."""

import email.utils
import hashlib
import os
import re

import frappe
import requests
from frappe.utils import cint, getdate, now_datetime, nowdate
from frappe.utils.background_jobs import is_job_enqueued

from repair_management.rd_vat import search_file
from repair_management.rd_vat.importer import (
	LOG,
	ImportRequest,
	create_log,
	last_finished_log,
	run_import,
)

SETTINGS = "RD VAT Import Settings"
DEFAULT_URLS = {
	# Not the link in RD's catalog, which still points to a July 2025 file.
	"Bangkok": "https://data.rd.go.th/datafiles/vat/VAT_TaxpayerAddress_01.csv",
	"Other Provinces": "https://data.rd.go.th/datafiles/vat/VAT_TaxpayerAddress_02.csv",
}
URL_FIELDS = {"Bangkok": "bangkok_url", "Other Provinces": "provinces_url"}
DATASETS = tuple(URL_FIELDS)

JOB_ID = "rd_vat_import"
JOB_TIMEOUT = 6 * 60 * 60
CONNECT_TIMEOUT, READ_TIMEOUT = 30, 120
DOWNLOAD_CHUNK = 1 << 20
MAX_FILE_BYTES = 1 << 30
UPLOAD_CACHE_PREFIX = "rd_vat_upload:"
USER_AGENT = "ERPNext-RD-VAT-Import"


def get_settings() -> dict:
	"""Settings with defaults, so a site where the Single was never saved still works."""
	values = frappe.db.get_singles_dict(SETTINGS)
	auto_update = values.get("auto_update")
	return {
		"Bangkok": values.get("bangkok_url") or DEFAULT_URLS["Bangkok"],
		"Other Provinces": values.get("provinces_url") or DEFAULT_URLS["Other Provinces"],
		"batch_size": cint(values.get("batch_size")) or 2000,
		"auto_update": 1 if auto_update in (None, "") else cint(auto_update),
	}


def _work_dir() -> str:
	path = frappe.get_site_path("private", "rd_vat_import")
	os.makedirs(path, exist_ok=True)
	return path


def is_running() -> bool:
	return is_job_enqueued(JOB_ID)


def _enqueue(method: str, **kwargs) -> bool:
	if is_running():
		return False
	frappe.enqueue(
		method,
		queue="long",
		timeout=JOB_TIMEOUT,
		job_id=JOB_ID,
		deduplicate=True,
		**kwargs,
	)
	return True


def _close_interrupted_logs() -> None:
	"""Only one job runs at a time, so a Running log at job start belongs to a job that died."""
	for name in frappe.get_all(LOG, filters={"status": "Running"}, pluck="name"):
		frappe.db.set_value(
			LOG,
			name,
			{
				"status": "Failed",
				"finished_at": now_datetime(),
				"message": "การนำเข้าถูกขัดจังหวะ สามารถนำเข้าใหม่ได้โดยไม่เกิดข้อมูลซ้ำ",
			},
			update_modified=False,
		)
	frappe.db.commit()


def _file_date(last_modified: str):
	parsed = email.utils.parsedate_to_datetime(last_modified) if last_modified else None
	return parsed.date() if parsed else getdate(nowdate())


def _head(url: str) -> dict:
	response = requests.head(
		url, allow_redirects=True, timeout=CONNECT_TIMEOUT, headers={"User-Agent": USER_AGENT}
	)
	response.raise_for_status()
	return {
		"etag": response.headers.get("ETag") or "",
		"last_modified": response.headers.get("Last-Modified") or "",
	}


def _download(url: str, dest: str) -> dict:
	"""Stream to disk, hashing as it goes. Raises if the transfer is incomplete."""
	digest = hashlib.sha256()
	size = 0
	with requests.get(
		url, stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), headers={"User-Agent": USER_AGENT}
	) as response:
		response.raise_for_status()
		expected = response.headers.get("Content-Length")
		with open(dest, "wb") as handle:
			for chunk in response.iter_content(DOWNLOAD_CHUNK):
				size += len(chunk)
				if size > MAX_FILE_BYTES:
					raise ValueError(f"File is larger than {MAX_FILE_BYTES} bytes")
				digest.update(chunk)
				handle.write(chunk)
		if expected and "Content-Encoding" not in response.headers and int(expected) != size:
			raise ValueError(f"Incomplete download: {size} of {expected} bytes")
		return {
			"hash": digest.hexdigest(),
			"size": size,
			"etag": response.headers.get("ETag") or "",
			"last_modified": response.headers.get("Last-Modified") or "",
		}


def _hash_file(path: str) -> str:
	digest = hashlib.sha256()
	with open(path, "rb") as handle:
		while chunk := handle.read(DOWNLOAD_CHUNK):
			digest.update(chunk)
	return digest.hexdigest()


def _skip(dataset: str, source_type: str, reason: str, triggered_by: str, **values) -> str:
	name = create_log(
		status="Skipped",
		dataset=dataset,
		source_type=source_type,
		finished_at=now_datetime(),
		message=reason,
		triggered_by=triggered_by,
		**values,
	)
	frappe.db.commit()
	return name


def update_dataset(dataset: str, force: bool = False, triggered_by: str = "") -> str:
	"""Check, download and import one dataset. Returns the log name."""
	settings = get_settings()
	url = settings[dataset]
	previous = last_finished_log(dataset)

	if not force and previous:
		remote = _head(url)
		same_validator = remote["etag"] and remote["etag"] == previous.etag
		same_date = remote["last_modified"] and remote["last_modified"] == previous.last_modified_header
		if same_validator and same_date:
			return _skip(
				dataset,
				"Download",
				"ไฟล์ต้นทางไม่เปลี่ยนแปลง (ETag และ Last-Modified ตรงกับการนำเข้าครั้งก่อน)",
				triggered_by,
				source_url=url,
				etag=remote["etag"],
				last_modified_header=remote["last_modified"],
				file_hash=previous.file_hash,
			)

	dest = os.path.join(_work_dir(), f"download-{frappe.generate_hash(length=12)}.csv")
	try:
		info = _download(url, dest)
		if not force and previous and previous.file_hash == info["hash"]:
			return _skip(
				dataset,
				"Download",
				"ไฟล์มี SHA-256 ตรงกับการนำเข้าครั้งก่อน",
				triggered_by,
				source_url=url,
				file_hash=info["hash"],
				file_size=info["size"],
				etag=info["etag"],
				last_modified_header=info["last_modified"],
			)
		return run_import(
			ImportRequest(
				path=dest,
				dataset=dataset,
				source_type="Download",
				file_name=url.rsplit("/", 1)[-1][:255],
				file_date=_file_date(info["last_modified"]),
				file_hash=info["hash"],
				file_size=info["size"],
				source_url=url,
				etag=info["etag"],
				last_modified_header=info["last_modified"],
				batch_size=settings["batch_size"],
				triggered_by=triggered_by,
			)
		)
	finally:
		if os.path.exists(dest):
			os.remove(dest)


def _refresh_search_file(log_names: list) -> None:
	"""Rebuild after data changed, or if the file is missing. Search falls back to SQL if this fails."""
	imported = frappe.get_all(
		LOG,
		filters={"name": ("in", log_names or [""]), "status": ("in", ("Success", "Needs Review"))},
		limit=1,
	)
	if not imported and search_file.exists():
		return
	try:
		search_file.build()
	except Exception:
		frappe.log_error(title="RD VAT search file build failed")


def run_update(force: bool = False, triggered_by: str = "") -> None:
	"""Background job: update every dataset. A failure in one does not stop the other."""
	_close_interrupted_logs()
	log_names = []
	for dataset in DATASETS:
		try:
			log_names.append(update_dataset(dataset, force=cint(force), triggered_by=triggered_by))
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"RD VAT update failed: {dataset}")
			create_log(
				status="Failed",
				dataset=dataset,
				source_type="Download",
				source_url=get_settings()[dataset],
				finished_at=now_datetime(),
				triggered_by=triggered_by,
				message="ดาวน์โหลดไฟล์ไม่สำเร็จ ดูรายละเอียดใน Error Log",
			)
			frappe.db.commit()
	_refresh_search_file(log_names)


def monthly_auto_update() -> None:
	"""Monthly cron entry. Hands off to the long queue, as cron jobs run on the short default queue."""
	if get_settings()["auto_update"]:
		_enqueue("repair_management.rd_vat.sync.run_update", triggered_by="Monthly auto update")


@frappe.whitelist(methods=["POST"])
def trigger_update(force: int | str = 0) -> dict:
	"""One-click: download and import both datasets in the background."""
	frappe.only_for("System Manager")
	started = _enqueue(
		"repair_management.rd_vat.sync.run_update", force=cint(force), triggered_by=frappe.session.user
	)
	return {"started": started}


# ---------------------------------------------------------------------------
# Manual upload. The file (258 MB) is above the site's upload limit (100 MB), so the page sends chunks.
# ---------------------------------------------------------------------------


def _upload_path(upload_id: str) -> str:
	if not re.fullmatch(r"[0-9a-f]{20}", upload_id or ""):
		frappe.throw("Upload ID ไม่ถูกต้อง")
	return os.path.join(_work_dir(), f"upload-{upload_id}.csv")


def _upload_state(upload_id: str) -> dict:
	state = frappe.cache.get_value(UPLOAD_CACHE_PREFIX + upload_id)
	if not state or state.get("user") != frappe.session.user:
		frappe.throw("ไม่พบการอัปโหลดนี้หรือหมดอายุแล้ว กรุณาเริ่มใหม่")
	return state


@frappe.whitelist(methods=["POST"])
def start_upload(dataset: str, file_name: str, file_date: str, size: int | str) -> dict:
	frappe.only_for("System Manager")
	if dataset not in DATASETS:
		frappe.throw("ชุดข้อมูลไม่ถูกต้อง")
	size = cint(size)
	if size <= 0 or size > MAX_FILE_BYTES:
		frappe.throw("ขนาดไฟล์ไม่ถูกต้อง")
	if not file_date or getdate(file_date) > getdate(nowdate()):
		frappe.throw("กรุณาระบุวันที่ของข้อมูลในไฟล์ และต้องไม่เป็นวันที่ในอนาคต")
	if is_running():
		frappe.throw("กำลังมีการนำเข้าข้อมูลอยู่ กรุณารอให้เสร็จก่อน")

	upload_id = frappe.generate_hash(length=20).lower()
	frappe.cache.set_value(
		UPLOAD_CACHE_PREFIX + upload_id,
		{
			"user": frappe.session.user,
			"dataset": dataset,
			"file_name": os.path.basename(str(file_name or "upload.csv"))[:255],
			"file_date": str(getdate(file_date)),
			"size": size,
		},
		expires_in_sec=24 * 60 * 60,
	)
	open(_upload_path(upload_id), "wb").close()
	return {"upload_id": upload_id}


@frappe.whitelist(methods=["POST"])
def upload_chunk(upload_id: str, offset: int | str) -> dict:
	frappe.only_for("System Manager")
	state = _upload_state(upload_id)
	path = _upload_path(upload_id)
	chunk = frappe.request.files.get("chunk")
	if not chunk:
		frappe.throw("ไม่พบข้อมูลที่อัปโหลด")
	if cint(offset) != os.path.getsize(path):
		frappe.throw("ลำดับข้อมูลไม่ถูกต้อง กรุณาเริ่มอัปโหลดใหม่")
	data = chunk.stream.read()
	if os.path.getsize(path) + len(data) > state["size"]:
		frappe.throw("ข้อมูลเกินขนาดไฟล์ที่ระบุ")
	with open(path, "ab") as handle:
		handle.write(data)
	return {"received": os.path.getsize(path)}


@frappe.whitelist(methods=["POST"])
def finish_upload(upload_id: str, force: int | str = 0) -> dict:
	frappe.only_for("System Manager")
	state = _upload_state(upload_id)
	path = _upload_path(upload_id)
	if os.path.getsize(path) != state["size"]:
		frappe.throw("อัปโหลดไม่ครบ กรุณาเริ่มใหม่")
	started = _enqueue(
		"repair_management.rd_vat.sync.run_uploaded",
		path=path,
		dataset=state["dataset"],
		file_name=state["file_name"],
		file_date=state["file_date"],
		force=cint(force),
		triggered_by=frappe.session.user,
	)
	if not started:
		frappe.throw("กำลังมีการนำเข้าข้อมูลอยู่ กรุณาลองใหม่เมื่อเสร็จแล้ว")
	frappe.cache.delete_value(UPLOAD_CACHE_PREFIX + upload_id)
	return {"started": True}


def run_uploaded(
	path: str, dataset: str, file_name: str, file_date: str, force: int = 0, triggered_by: str = ""
) -> None:
	"""Background job: import an uploaded file, then remove the temporary copy."""
	_close_interrupted_logs()
	try:
		file_hash = _hash_file(path)
		previous = last_finished_log(dataset)
		if not cint(force) and previous and previous.file_hash == file_hash:
			_skip(
				dataset,
				"Upload",
				"ไฟล์มี SHA-256 ตรงกับการนำเข้าครั้งก่อน",
				triggered_by,
				file_name=file_name,
				file_hash=file_hash,
				file_size=os.path.getsize(path),
			)
			return
		log_name = run_import(
			ImportRequest(
				path=path,
				dataset=dataset,
				source_type="Upload",
				file_name=file_name,
				file_date=file_date,
				file_hash=file_hash,
				file_size=os.path.getsize(path),
				batch_size=get_settings()["batch_size"],
				triggered_by=triggered_by,
			)
		)
		_refresh_search_file([log_name])
	finally:
		if os.path.exists(path):
			os.remove(path)
