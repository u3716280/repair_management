"""Standard exception/data-quality codes for the Reorder Analysis data engine.

Phase 0 only *raises and collects* these; it never auto-fixes data, and nothing
here is persisted (persisting would itself be a write, out of scope for Phase 0).
"""

from dataclasses import dataclass, field


class ExceptionCode:
	UNKNOWN_VOUCHER = "UNKNOWN_VOUCHER"
	UNCLASSIFIED_MOVEMENT = "UNCLASSIFIED_MOVEMENT"
	NEGATIVE_STOCK = "NEGATIVE_STOCK"
	MISSING_UOM_CONVERSION = "MISSING_UOM_CONVERSION"
	LATE_PO = "LATE_PO"
	CANCELLED_SOURCE = "CANCELLED_SOURCE"
	ABNORMAL_QTY = "ABNORMAL_QTY"
	MISSING_WAREHOUSE = "MISSING_WAREHOUSE"
	MISSING_ITEM = "MISSING_ITEM"
	DUPLICATE_SOURCE_ROW = "DUPLICATE_SOURCE_ROW"


SEVERITY = {
	ExceptionCode.UNKNOWN_VOUCHER: "review",
	ExceptionCode.UNCLASSIFIED_MOVEMENT: "review",
	ExceptionCode.NEGATIVE_STOCK: "warning",
	ExceptionCode.MISSING_UOM_CONVERSION: "error",
	ExceptionCode.LATE_PO: "info",
	ExceptionCode.CANCELLED_SOURCE: "info",
	ExceptionCode.ABNORMAL_QTY: "flag",
	ExceptionCode.MISSING_WAREHOUSE: "error",
	ExceptionCode.MISSING_ITEM: "error",
	ExceptionCode.DUPLICATE_SOURCE_ROW: "error",
}


@dataclass
class DataException:
	code: str
	message: str
	item_code: str | None = None
	warehouse: str | None = None
	voucher_type: str | None = None
	voucher_no: str | None = None
	voucher_detail_no: str | None = None
	posting_date: str | None = None
	context: dict = field(default_factory=dict)

	@property
	def severity(self) -> str:
		return SEVERITY.get(self.code, "review")

	def as_dict(self) -> dict:
		return {
			"code": self.code,
			"severity": self.severity,
			"message": self.message,
			"item_code": self.item_code,
			"warehouse": self.warehouse,
			"voucher_type": self.voucher_type,
			"voucher_no": self.voucher_no,
			"voucher_detail_no": self.voucher_detail_no,
			"posting_date": self.posting_date,
			"context": self.context,
		}
