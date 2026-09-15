# Copyright (c) 2026, Chirayut D. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Month"), "fieldname": "sales_month", "fieldtype": "Data", "width": 100},
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 180},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 260},
		{"label": _("Stock UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 100},
		{"label": _("Total Qty"), "fieldname": "total_qty", "fieldtype": "Float", "width": 140},
		{"label": _("Direct Item Qty"), "fieldname": "direct_qty", "fieldtype": "Float", "width": 140},
		{"label": _("Packed Item Qty"), "fieldname": "packed_qty", "fieldtype": "Float", "width": 140},
		{"label": _("WO Consumed Qty"), "fieldname": "wo_consumed_qty", "fieldtype": "Float", "width": 150},
		{"label": _("Sales Order Count"), "fieldname": "sales_order_count", "fieldtype": "Int", "width": 140},
	]


def get_data(filters):
	# Built as our own params dict (not the raw filters the client sent) so that
	# item_code is always present, even when the Item Code filter is left blank.
	# frappe.db.sql substitutes %(name)s placeholders via Python's `%` string
	# formatting, which raises KeyError if a referenced key is missing from the
	# params dict -- as opposed to just being None/empty.
	params = {
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"item_code": filters.get("item_code") or None,
	}

	query = """
		WITH filtered_sales_order AS (

			/* =========================================================
			   Sales Order ที่ Submit แล้ว
			   กำหนดเดือนจากวันที่ Sales Order
			   ========================================================= */
			SELECT
				so.name,
				so.transaction_date,

				DATE_FORMAT(
					so.transaction_date,
					'%%Y-%%m'
				) AS sales_month

			FROM `tabSales Order` so

			WHERE
				so.docstatus = 1

				AND so.transaction_date >= %(from_date)s
				AND so.transaction_date <= %(to_date)s
		),


		submitted_work_order AS (

			/* =========================================================
			   Work Order ที่เชื่อมกับ Sales Order ในช่วงวันที่เลือก
			   ========================================================= */
			SELECT
				wo.name AS work_order,
				wo.sales_order,
				wo.production_item,

				so.sales_month

			FROM `tabWork Order` wo

			INNER JOIN filtered_sales_order so
				ON so.name = wo.sales_order

			WHERE
				wo.docstatus = 1
		),


		normal_sales_order_item AS (

			/* =========================================================
			   1. Item ปกติจาก Sales Order Item

			   ไม่นำมารวมในกรณี:
			   - เป็น Product Bundle Parent
			   - มี Work Order เพราะจะใช้วัตถุดิบจริงจาก Stock Entry แทน
			   ========================================================= */
			SELECT
				so.sales_month,
				so.name AS sales_order,

				soi.item_code,
				soi.stock_qty AS qty,

				'Sales Order Item' AS source_type

			FROM filtered_sales_order so

			INNER JOIN `tabSales Order Item` soi
				ON soi.parent = so.name
				AND soi.parenttype = 'Sales Order'
				AND soi.docstatus = 1

			WHERE
				NOT EXISTS (
					SELECT 1

					FROM `tabPacked Item` pi

					WHERE
						pi.parent = so.name
						AND pi.parenttype = 'Sales Order'
						AND pi.parent_detail_docname = soi.name
						AND pi.docstatus = 1
				)

				AND NOT EXISTS (
					SELECT 1

					FROM submitted_work_order wo

					WHERE
						wo.sales_order = so.name
						AND wo.production_item = soi.item_code
				)
		),


		packed_item AS (

			/* =========================================================
			   2. Item ย่อยจาก Product Bundle

			   ถ้า Packed Item มี Work Order ให้ไม่นับ Packed Item ตรง ๆ
			   เพราะต้องใช้วัตถุดิบจริงจาก Stock Entry ของ Work Order แทน
			   ========================================================= */
			SELECT
				so.sales_month,
				so.name AS sales_order,

				pi.item_code,
				pi.qty AS qty,

				'Packed Item' AS source_type

			FROM filtered_sales_order so

			INNER JOIN `tabPacked Item` pi
				ON pi.parent = so.name
				AND pi.parenttype = 'Sales Order'
				AND pi.docstatus = 1

			WHERE
				NOT EXISTS (
					SELECT 1

					FROM submitted_work_order wo

					WHERE
						wo.sales_order = so.name
						AND wo.production_item = pi.item_code
				)
		),


		work_order_consumption_entry AS (

			/* =========================================================
			   ตรวจสอบว่า Work Order ใดมี Stock Entry
			   ประเภท Material Consumption for Manufacture

			   ถ้ามี ให้ใช้รายการกลุ่มนี้แทน Manufacture
			   เพื่อป้องกันการนับวัตถุดิบซ้ำ
			   ========================================================= */
			SELECT DISTINCT
				se.work_order

			FROM `tabStock Entry` se

			INNER JOIN submitted_work_order wo
				ON wo.work_order = se.work_order

			WHERE
				se.docstatus = 1

				AND se.purpose =
					'Material Consumption for Manufacture'
		),


		work_order_consumed_item AS (

			/* =========================================================
			   3. วัตถุดิบที่ใช้จริงใน Stock Entry ของ Work Order

			   กรณี A:
			   มี Material Consumption for Manufacture
			   -> ใช้ Stock Entry ประเภทนี้

			   กรณี B:
			   ไม่มี Material Consumption for Manufacture
			   -> ใช้วัตถุดิบจาก Stock Entry ประเภท Manufacture

			   ไม่ใช้ Material Transfer for Manufacture
			   เพราะเป็นเพียงการย้ายเข้า WIP
			   ========================================================= */
			SELECT
				wo.sales_month,
				wo.sales_order,

				sed.item_code,

				SUM(sed.transfer_qty) AS qty,

				'Work Order Consumption' AS source_type

			FROM submitted_work_order wo

			INNER JOIN `tabStock Entry` se
				ON se.work_order = wo.work_order
				AND se.docstatus = 1

			INNER JOIN `tabStock Entry Detail` sed
				ON sed.parent = se.name
				AND sed.parenttype = 'Stock Entry'
				AND sed.docstatus = 1

			WHERE
				(
					se.purpose =
						'Material Consumption for Manufacture'

					OR (
						se.purpose = 'Manufacture'

						AND NOT EXISTS (
							SELECT 1

							FROM work_order_consumption_entry consumed

							WHERE
								consumed.work_order = wo.work_order
						)
					)
				)

				/* ตัด Finished Good ออก */
				AND COALESCE(sed.is_finished_item, 0) = 0

				/* ตัด Scrap Item ออก */
				AND COALESCE(sed.is_scrap_item, 0) = 0

				/* ต้องเป็นรายการที่ถูกตัดออกจาก Warehouse */
				AND COALESCE(sed.s_warehouse, '') != ''

			GROUP BY
				wo.sales_month,
				wo.sales_order,
				sed.item_code
		),


		final_item AS (

			/* =========================================================
			   รวมข้อมูลจากทุกแหล่ง
			   ========================================================= */
			SELECT
				sales_month,
				sales_order,
				item_code,
				qty,
				source_type

			FROM normal_sales_order_item


			UNION ALL


			SELECT
				sales_month,
				sales_order,
				item_code,
				qty,
				source_type

			FROM packed_item


			UNION ALL


			SELECT
				sales_month,
				sales_order,
				item_code,
				qty,
				source_type

			FROM work_order_consumed_item
		)


		SELECT
			sales.sales_month AS sales_month,

			sales.item_code AS item_code,

			MAX(item.item_name) AS item_name,

			MAX(item.stock_uom) AS stock_uom,

			SUM(sales.qty) AS total_qty,

			SUM(
				CASE
					WHEN sales.source_type = 'Sales Order Item'
					THEN sales.qty
					ELSE 0
				END
			) AS direct_qty,

			SUM(
				CASE
					WHEN sales.source_type = 'Packed Item'
					THEN sales.qty
					ELSE 0
				END
			) AS packed_qty,

			SUM(
				CASE
					WHEN sales.source_type = 'Work Order Consumption'
					THEN sales.qty
					ELSE 0
				END
			) AS wo_consumed_qty,

			COUNT(DISTINCT sales.sales_order) AS sales_order_count

		FROM final_item sales

		LEFT JOIN `tabItem` item
			ON item.name = sales.item_code

		WHERE
			(
				%(item_code)s IS NULL
				OR sales.item_code = %(item_code)s
			)

		GROUP BY
			sales.sales_month,
			sales.item_code

		ORDER BY
			sales.sales_month ASC,
			SUM(sales.qty) DESC,
			sales.item_code ASC
	"""

	return frappe.db.sql(query, params, as_dict=1)
