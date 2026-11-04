"""Read and validate RD's VAT registrant CSV files.

The published files need more care than a plain csv.DictReader:
- Bangkok is CP874, other provinces are UTF-8 with a BOM.
- Both contain NUL bytes, which make Python's csv module raise.
- Values and some headers are padded with spaces.
- Records with `&` or a stray quote in the name are broken across several rows.
"""

import codecs
import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from repair_management.rd_vat.normalize import (
	CSV_FIELDS,
	MAX_LENGTHS,
	build_search_text,
	clean,
	clean_name,
	is_valid_tin,
	record_hash,
)

EXPECTED_HEADERS = (
	"เลขผู้เสียภาษีอากร",
	"เลขที่สาขา",
	"ชื่อผู้ประกอบการ",
	"ชื่อสถานประกอบการ",
	"ชื่ออาคาร",
	"เลขที่ห้อง",
	"ชั้นที่",
	"ชื่อหมู่บ้าน",
	"เลขที่ตั้ง",
	"หมู่",
	"ซอย",
	"แยก",
	"ถนน",
	"ตำบล",
	"อำเภอ",
	"จังหวัด",
	"รหัสไปรษณีย์",
	"วันที่ได้รับอนุมัติ",
)

# More rejected rows than this means the file is wrong, not that a few records are damaged.
MAX_REJECTED_RATIO = 0.05
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

csv.field_size_limit(1 << 24)


class CsvValidationError(Exception):
	"""The file as a whole cannot be imported."""


@dataclass
class ParsedRow:
	line_no: int
	raw: list
	data: dict | None = None
	reason: str = ""
	warnings: list = field(default_factory=list)


@dataclass
class CsvStats:
	encoding: str = ""
	total_rows: int = 0
	valid_rows: int = 0
	rejected_rows: int = 0
	warning_rows: int = 0
	nul_bytes: int = 0


def detect_encoding(path: str) -> str:
	with open(path, "rb") as handle:
		start = handle.read(4)
		if start.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
			raise CsvValidationError("ไฟล์เป็น UTF-16 ซึ่งไม่รองรับ")
		if start.startswith(codecs.BOM_UTF8):
			return "utf-8-sig"

		handle.seek(0)
		decoder = codecs.getincrementaldecoder("utf-8")()
		try:
			while chunk := handle.read(1 << 20):
				decoder.decode(chunk)
			decoder.decode(b"", final=True)
		except UnicodeDecodeError:
			return "cp874"
	return "utf-8"


def parse_values(values: list) -> ParsedRow:
	"""Validate one CSV row. Sets `reason` if it must be rejected."""
	row = ParsedRow(line_no=0, raw=values)
	if len(values) != len(CSV_FIELDS):
		row.reason = f"จำนวนคอลัมน์ไม่ถูกต้อง ({len(values)})"
		return row

	data = {name: clean(value) for name, value in zip(CSV_FIELDS, values, strict=True)}
	data["taxpayer_name"] = clean_name(values[2])
	data["establishment_name"] = clean_name(values[3])

	if not re.fullmatch(r"[0-9]{13}", data["tax_id"]):
		row.reason = "เลขประจำตัวผู้เสียภาษีไม่ใช่ตัวเลข 13 หลัก"
		return row
	if not re.fullmatch(r"[0-9]{1,5}", data["branch_number"]):
		row.reason = "เลขที่สาขาไม่ใช่ตัวเลข 1-5 หลัก"
		return row

	if not is_valid_tin(data["tax_id"]):
		row.warnings.append("check digit ไม่ถูกต้อง")

	if data["vat_approval_date"] and not _DATE.match(data["vat_approval_date"]):
		row.warnings.append("รูปแบบวันที่ไม่ถูกต้อง")
		data["vat_approval_date"] = ""

	incomplete = not data["vat_approval_date"] or not data["province"]
	if incomplete:
		row.warnings.append("ข้อมูลไม่ครบ")

	for name, limit in MAX_LENGTHS.items():
		if len(data[name]) > limit:
			row.warnings.append(f"ตัด {name} ให้สั้นลง")
			data[name] = data[name][:limit]

	data["data_incomplete"] = 1 if incomplete else 0
	data["search_text"] = build_search_text(data["taxpayer_name"], data["establishment_name"])
	data["record_hash"] = record_hash(data)
	row.data = data
	return row


class RDVatCsv:
	"""One pass over the file per call to rows(); `stats` describes the latest pass."""

	def __init__(self, path: str):
		self.path = path
		self.stats = CsvStats(encoding=detect_encoding(path))

	def _lines(self, handle) -> Iterator[str]:
		line_encoding = "cp874" if self.stats.encoding == "cp874" else "utf-8"
		for index, line in enumerate(handle):
			if b"\0" in line:
				self.stats.nul_bytes += line.count(b"\0")
				line = line.replace(b"\0", b"")
			encoding = self.stats.encoding if index == 0 else line_encoding
			yield line.decode(encoding, errors="replace")

	def rows(self) -> Iterator[ParsedRow]:
		self.stats = CsvStats(encoding=self.stats.encoding)
		seen = set()
		with open(self.path, "rb") as handle:
			reader = csv.reader(self._lines(handle))
			try:
				header = next(reader)
			except StopIteration:
				raise CsvValidationError("ไฟล์ว่าง") from None
			_check_header(header)

			for values in reader:
				if not values:
					continue
				self.stats.total_rows += 1
				row = parse_values(values)
				row.line_no = reader.line_num

				if row.data:
					if any("�" in value for value in values):
						row.warnings.append("มีอักขระที่อ่านไม่ได้")
					key = int(row.data["tax_id"] + row.data["branch_number"].zfill(5))
					if key in seen:
						row.reason = "รายการซ้ำในไฟล์"
						row.data = None
					else:
						seen.add(key)

				if row.data:
					self.stats.valid_rows += 1
					if row.warnings:
						self.stats.warning_rows += 1
				else:
					self.stats.rejected_rows += 1
				yield row

	def validate(self) -> CsvStats:
		"""Read the whole file. Raises CsvValidationError if it should not be imported at all."""
		for _row in self.rows():
			pass
		stats = self.stats
		if not stats.valid_rows:
			raise CsvValidationError("ไม่พบรายการที่ถูกต้องในไฟล์")
		if stats.rejected_rows / stats.total_rows > MAX_REJECTED_RATIO:
			raise CsvValidationError(
				f"รายการที่ไม่ถูกต้องมากเกินไป ({stats.rejected_rows:,} จาก {stats.total_rows:,}) "
				"กรุณาตรวจสอบไฟล์ต้นทาง"
			)
		return stats


def _check_header(header: list) -> None:
	found = tuple(clean(name) for name in header)
	if found == EXPECTED_HEADERS:
		return
	if len(found) != len(EXPECTED_HEADERS):
		raise CsvValidationError(f"จำนวนคอลัมน์ไม่ถูกต้อง: พบ {len(found)} ต้องการ {len(EXPECTED_HEADERS)}")
	different = [f"{a!r} แทน {b!r}" for a, b in zip(found, EXPECTED_HEADERS, strict=True) if a != b]
	raise CsvValidationError("หัวคอลัมน์ไม่ตรงกับรูปแบบของกรมสรรพากร: " + "; ".join(different[:5]))
