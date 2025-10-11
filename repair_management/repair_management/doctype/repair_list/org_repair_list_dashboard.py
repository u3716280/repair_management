from frappe import _


def get_data():
	return {
		"heatmap": False,
		"heatmap_message": _("This is based on stock movement. See {0} for details").format(
			'<a href="/app/query-report/Stock Ledger">' + _("Stock Ledger") + "</a>"
		),
		"fieldname": "item_code",
		"non_standard_fieldnames": {
			"Batch": "item",

			# เอกสารที่อ้าง item_code ผ่าน child table
			"Sales Order": "items.item_code",
			"Delivery Note": "items.item_code",
			"Sales Invoice": "items.item_code",
			"Purchase Order": "items.item_code",
			"Purchase Receipt": "items.item_code",
			"Stock Entry": "items.item_code",
			"Stock Reconciliation": "items.item_code",
		},
		"transactions": [
			{"label": _("Pricing"), "items": ["Item Price", "Pricing Rule"]},
			{"label": _("Sell"), "items": ["Sales Order", "Delivery Note", "Sales Invoice"]},
			{
				"label": _("Buy"),
				"items": [
					"Purchase Order",
					"Purchase Receipt",
				],
			},
			{"label": _("Stock Movement"), "items": ["Stock Entry", "Stock Reconciliation"]},
		],
	}
