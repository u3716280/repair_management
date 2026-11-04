"""Fast partial name search using a plain file.

`LIKE '%x%'` has to read a 600 MB index and took over 15 seconds on this server, while scanning this file
takes about 0.1 seconds. Thai has no word breaks, so a word-based index cannot find text inside a name.

Each line holds: search_text, province, district, subdistrict, key. The file is derived from RD VAT Taxpayer
and can always be rebuilt. If it is missing, search falls back to SQL.
"""

import mmap
import os
from dataclasses import dataclass

import frappe

from repair_management.rd_vat.normalize import SEARCH_SEPARATOR

TABLE = "`tabRD VAT Taxpayer`"
FIELD_SEPARATOR = b"\x1e"
NAME_SEPARATOR = SEARCH_SEPARATOR.encode()
BUILD_CHUNK = 20000


@dataclass
class SearchFileResult:
	names: list
	total: int
	capped: bool


def file_path() -> str:
	return frappe.get_site_path("private", "rd_vat_index", "search.idx")


def exists() -> bool:
	return os.path.exists(file_path())


def build() -> int:
	"""Write a new file, then swap it in, so a search in progress always sees a complete file."""
	path = file_path()
	os.makedirs(os.path.dirname(path), exist_ok=True)
	temp = f"{path}.{frappe.generate_hash(length=8)}.tmp"
	count, last = 0, ""
	try:
		with open(temp, "wb") as handle:
			while True:
				rows = frappe.db.sql(
					f"""select name, province, district, subdistrict, search_text from {TABLE}
					where name > %(last)s order by name limit %(limit)s""",
					{"last": last, "limit": BUILD_CHUNK},
				)
				if not rows:
					break
				handle.write(
					"".join(
						f"{row[4] or ''}\x1e{row[1] or ''}\x1e{row[2] or ''}\x1e{row[3] or ''}\x1e{row[0]}\n"
						for row in rows
					).encode()
				)
				count += len(rows)
				last = rows[-1][0]
		os.replace(temp, path)
	finally:
		if os.path.exists(temp):
			os.remove(temp)
	return count


def _matches_scope(search_text: bytes, needle: bytes, scope: str) -> bool:
	"""search_text is taxpayer name + separator + establishment name."""
	taxpayer, _, establishment = search_text.partition(NAME_SEPARATOR)
	if scope == "taxpayer_name":
		return needle in taxpayer
	if scope == "establishment_name":
		return needle in establishment
	return needle in taxpayer or needle in establishment


def _sort_key(sort: str):
	if sort == "tax_id":
		return lambda row: row[4]
	if sort == "province":
		return lambda row: (row[1], row[2], row[3], row[0], row[4])
	return lambda row: (row[0], row[4])


def search(
	text: str,
	scope: str = "all",
	province: str = "",
	district: str = "",
	subdistrict: str = "",
	branch: str = "",
	sort: str = "name",
	start: int = 0,
	length: int = 20,
	cap: int = 10000,
	path: str | None = None,
) -> SearchFileResult | None:
	"""Find matching keys for one page. Returns None if the file is unavailable.

	Stops collecting after `cap` matches, so very common words stay fast. In that case only those matches
	are sorted, and the caller tells the user to refine the search.
	"""
	path = path or file_path()
	needle = text.encode()
	suffix = f"-{branch}".encode() if branch != "" else b""
	wanted = (
		(1, province.encode() if province else None),
		(2, district.encode() if district else None),
		(3, subdistrict.encode() if subdistrict else None),
	)
	wanted = [(index, value) for index, value in wanted if value is not None]

	try:
		handle = open(path, "rb")
	except OSError:
		return None

	rows, seen_line_end, position = [], -1, 0
	limit = cap + 1
	with handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
		while len(rows) < limit:
			hit = data.find(needle, position)
			if hit < 0:
				break
			line_start = data.rfind(b"\n", 0, hit) + 1
			line_end = data.find(b"\n", hit)
			if line_end < 0:
				line_end = len(data)
			position = line_end + 1
			if line_start <= seen_line_end:
				continue
			seen_line_end = line_end

			fields = data[line_start:line_end].split(FIELD_SEPARATOR)
			if len(fields) != 5:
				continue
			# A hit in a location column is not a name match.
			if not _matches_scope(fields[0], needle, scope):
				continue
			if suffix and not fields[4].endswith(suffix):
				continue
			if any(fields[index] != value for index, value in wanted):
				continue
			rows.append(fields)

	capped = len(rows) > cap
	rows = rows[:cap]
	rows.sort(key=_sort_key(sort))
	names = [row[4].decode() for row in rows[start : start + length]]
	return SearchFileResult(names=names, total=len(rows), capped=capped)
