"""Business rules for classifying a Stock Ledger Entry into the 7-way Demand
Classification taxonomy: CONSUMPTION, TRANSFER, RETURN, SUPPLY, ADJUSTMENT,
IGNORE, REVIEW.

Pure logic only -- no SQL/frappe.db calls here. `demand.py` is responsible for
joining a raw Stock Ledger Entry row to its source voucher header/child row
and building the "candidate" dict this module consumes.

An unrecognized voucher_type, or a recognized one whose purpose/flags don't
match any rule below, is never guessed at -- it is always routed to REVIEW
(spec requirement: "ห้ามเดา" / must not guess).
"""

from .exceptions import ExceptionCode

CONSUMPTION = "CONSUMPTION"
TRANSFER = "TRANSFER"
RETURN = "RETURN"
SUPPLY = "SUPPLY"
ADJUSTMENT = "ADJUSTMENT"
IGNORE = "IGNORE"
REVIEW = "REVIEW"

TRANSFER_OUT = "TRANSFER_OUT"
TRANSFER_IN = "TRANSFER_IN"
TRANSFER_EXTERNAL_CONSUMPTION = "EXTERNAL_CONSUMPTION"

# net_sign: how a classification contributes to net demand once aggregated.
# CONSUMPTION adds, RETURN subtracts, everything else is 0 at the company
# level (TRANSFER nets to 0 company-wide but is still tracked per-warehouse
# by demand.py using source_warehouse/target_warehouse + transfer_kind).
NET_SIGN = {
	CONSUMPTION: 1,
	RETURN: -1,
	SUPPLY: 0,
	ADJUSTMENT: 0,
	TRANSFER: 0,
	IGNORE: 0,
	REVIEW: 0,
}


def _result(
	classification,
	is_return=False,
	source_warehouse=None,
	target_warehouse=None,
	transfer_kind=None,
	review_reason=None,
	review_code=None,
):
	return {
		"classification": classification,
		"net_sign": NET_SIGN[classification],
		"is_return": bool(is_return),
		"source_warehouse": source_warehouse,
		"target_warehouse": target_warehouse,
		"transfer_kind": transfer_kind,
		"needs_review": classification == REVIEW,
		"review_reason": review_reason,
		"review_code": review_code,
	}


def _classify_stock_entry(row):
	purpose = row.get("purpose")
	is_return = bool(row.get("is_return"))
	warehouse = row.get("warehouse")
	s_warehouse = row.get("s_warehouse")
	t_warehouse = row.get("t_warehouse")
	actual_qty = row.get("actual_qty") or 0

	if purpose == "Material Issue":
		return _result(RETURN if is_return else CONSUMPTION, is_return, source_warehouse=warehouse)

	if purpose == "Material Receipt":
		return _result(RETURN if is_return else SUPPLY, is_return, target_warehouse=warehouse)

	if purpose == "Material Transfer":
		if warehouse == t_warehouse:
			return _result(
				TRANSFER, is_return, source_warehouse=s_warehouse, target_warehouse=t_warehouse, transfer_kind=TRANSFER_IN
			)
		return _result(
			TRANSFER, is_return, source_warehouse=s_warehouse, target_warehouse=t_warehouse, transfer_kind=TRANSFER_OUT
		)

	if purpose == "Material Transfer for Manufacture":
		if warehouse == t_warehouse:
			return _result(
				TRANSFER, is_return, source_warehouse=s_warehouse, target_warehouse=t_warehouse, transfer_kind=TRANSFER_IN
			)
		return _result(
			TRANSFER, is_return, source_warehouse=s_warehouse, target_warehouse=t_warehouse, transfer_kind=TRANSFER_OUT
		)

	if purpose == "Material Consumption for Manufacture":
		return _result(CONSUMPTION, is_return, source_warehouse=s_warehouse or warehouse)

	if purpose == "Manufacture":
		# A "Manufacture" purpose entry can carry both the FG receipt (positive
		# rows) and raw-material consumption (negative rows) in the same
		# document, depending on the Work Order's backflush configuration --
		# it is not always split out into a separate "Material Consumption
		# for Manufacture" entry. Classify by row sign rather than assume.
		if actual_qty > 0:
			return _result(SUPPLY, is_return, target_warehouse=t_warehouse or warehouse)
		return _result(CONSUMPTION, is_return, source_warehouse=s_warehouse or warehouse)

	if purpose == "Repack":
		if actual_qty > 0:
			return _result(SUPPLY, is_return, target_warehouse=t_warehouse or warehouse)
		return _result(CONSUMPTION, is_return, source_warehouse=s_warehouse or warehouse)

	if purpose == "Send to Subcontractor":
		return _result(
			TRANSFER, is_return, source_warehouse=s_warehouse or warehouse, transfer_kind=TRANSFER_EXTERNAL_CONSUMPTION
		)

	if purpose == "Disassemble":
		if actual_qty > 0:
			return _result(SUPPLY, is_return, target_warehouse=t_warehouse or warehouse)
		return _result(CONSUMPTION, is_return, source_warehouse=s_warehouse or warehouse)

	return _result(
		REVIEW,
		review_reason=f"Unrecognized Stock Entry purpose: {purpose!r}",
		review_code=ExceptionCode.UNCLASSIFIED_MOVEMENT,
	)


def _classify_return_or_supply(row):
	is_return = bool(row.get("is_return"))
	warehouse = row.get("warehouse")
	if is_return:
		return _result(RETURN, is_return, source_warehouse=warehouse)
	return _result(SUPPLY, is_return, target_warehouse=warehouse)


def _classify_return_or_consumption(row):
	is_return = bool(row.get("is_return"))
	warehouse = row.get("warehouse")
	if is_return:
		return _result(RETURN, is_return, target_warehouse=warehouse)
	return _result(CONSUMPTION, is_return, source_warehouse=warehouse)


def _classify_stock_reconciliation(row):
	return _result(ADJUSTMENT, source_warehouse=row.get("warehouse"), target_warehouse=row.get("warehouse"))


def _classify_subcontracting_order(row):
	warehouse = row.get("warehouse")
	return _result(TRANSFER, source_warehouse=warehouse, transfer_kind=TRANSFER_EXTERNAL_CONSUMPTION)


def _classify_subcontracting_receipt(row):
	return _result(SUPPLY, target_warehouse=row.get("warehouse"))


# voucher_type -> handler. Purchase Invoice/Sales Invoice only ever reach here
# when update_stock=1 (demand.py never emits Purchase/Sales Invoice SLE rows
# with update_stock=0, since those never produce an SLE in the first place).
_VOUCHER_HANDLERS = {
	"Stock Entry": _classify_stock_entry,
	"Purchase Receipt": _classify_return_or_supply,
	"Purchase Invoice": _classify_return_or_supply,
	"Delivery Note": _classify_return_or_consumption,
	"Sales Invoice": _classify_return_or_consumption,
	"Stock Reconciliation": _classify_stock_reconciliation,
	"Subcontracting Order": _classify_subcontracting_order,
	"Subcontracting Receipt": _classify_subcontracting_receipt,
}


def classify_movement(row: dict) -> dict:
	"""Classify a single normalized movement candidate row.

	`row` is expected to carry at least: voucher_type, warehouse, actual_qty,
	and (when available) is_return, purpose, s_warehouse, t_warehouse --
	whatever `demand.py` was able to resolve from the source voucher header.
	`row["header_found"] = False` signals the voucher_type/header lookup
	itself failed (e.g. an unrecognized voucher_type), which always routes to
	REVIEW/UNKNOWN_VOUCHER regardless of any other field.

	Never raises. Never returns anything other than one of the 7 taxonomy
	classifications.
	"""
	if row.get("header_found") is False:
		return _result(
			REVIEW,
			review_reason=f"Unrecognized voucher_type: {row.get('voucher_type')!r}",
			review_code=ExceptionCode.UNKNOWN_VOUCHER,
		)

	if (row.get("actual_qty") or 0) == 0:
		return _result(IGNORE)

	handler = _VOUCHER_HANDLERS.get(row.get("voucher_type"))
	if handler is None:
		return _result(
			REVIEW,
			review_reason=f"Unrecognized voucher_type: {row.get('voucher_type')!r}",
			review_code=ExceptionCode.UNKNOWN_VOUCHER,
		)

	return handler(row)
