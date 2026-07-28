# Copyright (c) 2026
# License: MIT

import math
from datetime import timedelta

import frappe
from frappe.utils import cint, date_diff, flt, getdate
from frappe.utils.nestedset import get_descendants_of


# ถ้า Item มีประวัติการเบิก (จำนวนวันที่มีการเบิก) น้อยกว่านี้ ถือว่าข้อมูลไม่พอสำหรับ
# คำนวณ Percentile อย่างน่าเชื่อถือ จะ fallback ไปใช้ยอดเบิกสูงสุดต่อครั้งแทน
MIN_EVENTS_FOR_PERCENTILE = 5

VALID_PERCENTILES = {90, 95, 97.5, 99}


@frappe.whitelist()
def get_reorder_data(
	from_date,
	to_date,
	item_group=None,
	warehouse=None,
	order_cycle_days=30,
	percentile=95,
):
	"""คำนวณ Reorder Point และ Suggested Order Qty สำหรับ Item หลายรายการ

	หลักการสำคัญ:
	- ใช้วิธี Lead-Time Demand Percentile: สร้าง time series รายวัน (รวมวันที่ไม่มีการใช้
	  เป็น 0) แล้ว sliding-window รวมยอดใช้ทุกช่วงความยาวเท่า Lead Time เพื่อดู distribution
	  ของยอดใช้จริงในแต่ละช่วง Lead Time จากนั้นใช้ Percentile ที่เลือก (P90/95/97.5/99)
	  เป็น Reorder Point โดยตรง แทนการใช้ Max Daily Usage × Lead Time ซึ่งจะสูงเกินจริงมาก
	  สำหรับสินค้าที่เบิกไม่บ่อยแต่ทีละเยอะ (lumpy/intermittent demand)
	- ถ้า Item.safety_stock กรอกไว้ (>0) จะใช้ค่านั้นเป็น Safety Stock เสมอ (ไม่คำนวณ Percentile)
	- ถ้าประวัติการเบิกน้อยกว่า MIN_EVENTS_FOR_PERCENTILE ครั้ง ถือว่า Percentile ไม่น่าเชื่อถือ
	  จะ fallback ไปใช้ยอดเบิกสูงสุดต่อครั้งที่เคยเกิดขึ้นจริงเป็น Safety Stock แทน
	- Minimum Order Qty ใช้ Item.min_order_qty
	- Warehouse ที่เป็น Group จะรวม Warehouse ลูกทั้งหมด
	- ใช้ Actual Stock เป็นหลักในการเทียบกับ Reorder Point
	"""
	frappe.has_permission("Item", "read", throw=True)

	from_date = getdate(from_date)
	to_date = getdate(to_date)
	if date_diff(to_date, from_date) < 0:
		frappe.throw("From Date ต้องมาก่อน To Date")

	order_cycle_days = max(0, cint(order_cycle_days))

	percentile = flt(percentile)
	if percentile not in VALID_PERCENTILES:
		frappe.throw("Percentile ไม่ถูกต้อง (ต้องเป็น 90, 95, 97.5 หรือ 99)")

	total_days = date_diff(to_date, from_date) + 1
	date_list = [from_date + timedelta(days=i) for i in range(total_days)]
	warehouse_names = _get_warehouse_names(warehouse)
	params = {
		"from_date": from_date,
		"to_date": to_date,
		"warehouse_names": tuple(warehouse_names) if warehouse_names else tuple(),
	}

	item_groups = []
	if item_group:
		item_groups = get_descendants_of("Item Group", item_group) + [item_group]
		params["item_groups"] = tuple(item_groups)

	item_condition_dn = _item_group_condition("dni.item_code", bool(item_group))
	item_condition_pi = _item_group_condition("pi.item_code", bool(item_group))
	item_condition_wo = _item_group_condition("wo.production_item", bool(item_group))
	item_condition_se = _item_group_condition("sed.item_code", bool(item_group))

	warehouse_condition_dn = _warehouse_condition("dni.warehouse", warehouse_names)
	warehouse_condition_pi = _warehouse_condition("pi.warehouse", warehouse_names)
	warehouse_condition_wo = _warehouse_condition("wo.fg_warehouse", warehouse_names)
	warehouse_condition_se = _warehouse_condition("sed.s_warehouse", warehouse_names)

	# 1) สินค้าสำเร็จรูปที่ส่งจาก Delivery Note และอ้างอิง Sales Order
	dn_rows = frappe.db.sql(
		f"""
		SELECT dni.item_code, dn.posting_date AS tdate, SUM(dni.stock_qty) AS qty
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus = 1
			AND dn.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND IFNULL(dni.against_sales_order, '') != ''
			{item_condition_dn}
			{warehouse_condition_dn}
		GROUP BY dni.item_code, dn.posting_date
		""",
		params,
		as_dict=True,
	)

	# 2) Component ที่ขายผ่าน Product Bundle
	pi_rows = frappe.db.sql(
		f"""
		SELECT pi.item_code, dn.posting_date AS tdate, SUM(pi.qty) AS qty
		FROM `tabPacked Item` pi
		INNER JOIN `tabDelivery Note Item` dni ON dni.name = pi.parent_detail_docname
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE pi.parenttype = 'Delivery Note'
			AND dn.docstatus = 1
			AND dn.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND IFNULL(dni.against_sales_order, '') != ''
			{item_condition_pi}
			{warehouse_condition_pi}
		GROUP BY pi.item_code, dn.posting_date
		""",
		params,
		as_dict=True,
	)

	# 3) สินค้าที่ผลิตเสร็จจาก Work Order ซึ่งอ้างอิง Sales Order
	wo_rows = frappe.db.sql(
		f"""
		SELECT wo.production_item AS item_code, DATE(wo.actual_end_date) AS tdate,
			SUM(wo.produced_qty) AS qty
		FROM `tabWork Order` wo
		WHERE wo.docstatus = 1
			AND IFNULL(wo.sales_order, '') != ''
			AND wo.produced_qty > 0
			AND DATE(wo.actual_end_date) BETWEEN %(from_date)s AND %(to_date)s
			{item_condition_wo}
			{warehouse_condition_wo}
		GROUP BY wo.production_item, DATE(wo.actual_end_date)
		""",
		params,
		as_dict=True,
	)

	# 4) วัตถุดิบที่เบิกใช้ใน Stock Entry ของ Work Order ซึ่งอ้างอิง Sales Order
	se_rows = frappe.db.sql(
		f"""
		SELECT sed.item_code, se.posting_date AS tdate, SUM(sed.transfer_qty) AS qty
		FROM `tabStock Entry Detail` sed
		INNER JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.docstatus = 1
			AND IFNULL(se.work_order, '') != ''
			AND EXISTS (
				SELECT 1 FROM `tabWork Order` wo_ref
				WHERE wo_ref.name = se.work_order
					AND IFNULL(wo_ref.sales_order, '') != ''
			)
			AND IFNULL(sed.s_warehouse, '') != ''
			AND IFNULL(sed.t_warehouse, '') = ''
			AND se.posting_date BETWEEN %(from_date)s AND %(to_date)s
			{item_condition_se}
			{warehouse_condition_se}
		GROUP BY sed.item_code, se.posting_date
		""",
		params,
		as_dict=True,
	)

	usage_map = _combine_usage(dn_rows + pi_rows + wo_rows + se_rows)
	items = _get_items(item_groups, usage_map)
	if not items:
		return []

	item_codes = [row.name for row in items]
	item_info = {row.name: row for row in items}
	stock_map = _get_stock_map(item_codes, warehouse_names)

	result = []
	for item_code in item_codes:
		item = item_info[item_code]
		item_usage = usage_map.get(item_code, {})
		daily_values = [flt(item_usage.get(d, 0)) for d in date_list]

		total_qty = sum(daily_values)
		avg_daily = total_qty / total_days if total_days else 0
		max_daily = max(daily_values) if daily_values else 0
		num_events = sum(1 for v in daily_values if v > 0)

		lead_time = max(0, cint(item.lead_time_days))
		protection_period = lead_time + order_cycle_days
		avg_lead_time_demand = avg_daily * lead_time
		cycle_demand = avg_daily * order_cycle_days

		lt_windows = _rolling_sums(daily_values, lead_time) if lead_time > 0 else []
		pp_windows = _rolling_sums(daily_values, protection_period) if protection_period > 0 else []
		lead_time_demand_p = _percentile(lt_windows, percentile) if lt_windows else 0

		manual_safety_stock = max(0, flt(item.safety_stock))

		if lead_time <= 0:
			# ไม่ได้กำหนด Lead Time เลย คำนวณ Reorder Point ไม่ได้
			safety_stock = manual_safety_stock
			safety_stock_source = "Item" if manual_safety_stock > 0 else "-"
			reorder_point = safety_stock
		elif manual_safety_stock > 0:
			safety_stock = manual_safety_stock
			safety_stock_source = "Item (Manual)"
			reorder_point = avg_lead_time_demand + safety_stock
		elif num_events >= MIN_EVENTS_FOR_PERCENTILE and lt_windows:
			reorder_point = lead_time_demand_p
			safety_stock = max(0, lead_time_demand_p - avg_lead_time_demand)
			safety_stock_source = f"P{_format_percentile(percentile)}"
		else:
			# ประวัติการเบิกน้อยเกินไป (< MIN_EVENTS_FOR_PERCENTILE ครั้ง) Percentile ไม่น่าเชื่อถือ
			safety_stock = max_daily
			safety_stock_source = "ยอดเบิกสูงสุด/ครั้ง (ข้อมูลน้อย)"
			reorder_point = avg_lead_time_demand + safety_stock

		if (
			lead_time > 0
			and manual_safety_stock <= 0
			and num_events >= MIN_EVENTS_FOR_PERCENTILE
			and pp_windows
		):
			target_stock = _percentile(pp_windows, percentile)
		else:
			target_stock = reorder_point + cycle_demand

		stock = stock_map.get(item_code, {})
		actual_stock = flt(stock.get("actual_stock"))
		reserved_stock = flt(stock.get("reserved_stock"))
		available_stock = actual_stock - reserved_stock
		waiting_stock = flt(stock.get("waiting_stock"))

		minimum_order_qty = max(0, flt(item.min_order_qty))
		raw_order_qty = max(0, target_stock - actual_stock)
		suggested_order_qty = max(raw_order_qty, minimum_order_qty) if raw_order_qty > 0 else 0
		below_reorder_point = actual_stock < reorder_point

		status, status_type = _get_status(
			avg_daily=avg_daily,
			lead_time=lead_time,
			below_reorder_point=below_reorder_point,
			suggested_order_qty=suggested_order_qty,
		)

		result.append(
			{
				"item_code": item_code,
				"item_name": item.item_name or item_code,
				"warehouse": warehouse or "ทุก Warehouse",
				"avg_daily_usage": round(avg_daily, 2),
				"max_daily_usage": round(max_daily, 2),
				"events": num_events,
				"lead_time": lead_time,
				"percentile": _format_percentile(percentile),
				"safety_stock": round(safety_stock, 2),
				"safety_stock_source": safety_stock_source,
				"reorder_point": round(reorder_point, 2),
				"order_cycle_days": order_cycle_days,
				"cycle_demand": round(cycle_demand, 2),
				"target_stock": round(target_stock, 2),
				"actual_stock": round(actual_stock, 2),
				"reserved_stock": round(reserved_stock, 2),
				"available_stock": round(available_stock, 2),
				"waiting_stock": round(waiting_stock, 2),
				"minimum_order_qty": round(minimum_order_qty, 2),
				"raw_order_qty": round(raw_order_qty, 2),
				"suggested_order_qty": round(suggested_order_qty, 2),
				"below_reorder_point": below_reorder_point,
				"status": status,
				"status_type": status_type,
			}
		)

	result.sort(
		key=lambda row: (
			0 if row["status_type"] == "danger" else 1 if row["status_type"] == "warning" else 2,
			row["item_code"],
		)
	)
	return result


def _get_warehouse_names(warehouse):
	if not warehouse:
		return []
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw("ไม่พบ Warehouse ที่เลือก")
	return get_descendants_of("Warehouse", warehouse) + [warehouse]


def _item_group_condition(column, enabled):
	if not enabled:
		return ""
	return f"AND {column} IN (SELECT name FROM `tabItem` WHERE item_group IN %(item_groups)s)"


def _warehouse_condition(column, warehouse_names):
	if not warehouse_names:
		return ""
	return f"AND {column} IN %(warehouse_names)s"


def _combine_usage(rows):
	usage_map = {}
	for row in rows:
		if not row.item_code or not row.tdate:
			continue
		usage_map.setdefault(row.item_code, {})
		usage_map[row.item_code][row.tdate] = (
			usage_map[row.item_code].get(row.tdate, 0) + flt(row.qty)
		)
	return usage_map


def _get_items(item_groups, usage_map):
	fields = ["name", "item_name", "lead_time_days", "safety_stock", "min_order_qty"]
	if item_groups:
		return frappe.get_all(
			"Item",
			filters={
				"item_group": ["in", item_groups],
				"disabled": 0,
				"is_stock_item": 1,
				"has_variants": 0,
			},
			fields=fields,
			limit_page_length=0,
		)

	item_codes = list(usage_map.keys())
	if not item_codes:
		return []
	return frappe.get_all(
		"Item",
		filters={
			"name": ["in", item_codes],
			"disabled": 0,
			"is_stock_item": 1,
			"has_variants": 0,
		},
		fields=fields,
		limit_page_length=0,
	)


def _get_stock_map(item_codes, warehouse_names):
	warehouse_condition = ""
	params = {"item_codes": tuple(item_codes)}
	if warehouse_names:
		warehouse_condition = "AND warehouse IN %(warehouse_names)s"
		params["warehouse_names"] = tuple(warehouse_names)

	rows = frappe.db.sql(
		f"""
		SELECT
			item_code,
			SUM(IFNULL(actual_qty, 0)) AS actual_stock,
			SUM(
				IFNULL(reserved_qty, 0)
				+ IFNULL(reserved_qty_for_production, 0)
				+ IFNULL(reserved_qty_for_sub_contract, 0)
			) AS reserved_stock,
			SUM(IFNULL(ordered_qty, 0)) AS waiting_stock
		FROM `tabBin`
		WHERE item_code IN %(item_codes)s
			{warehouse_condition}
		GROUP BY item_code
		""",
		params,
		as_dict=True,
	)
	return {row.item_code: row for row in rows}


def _get_status(avg_daily, lead_time, below_reorder_point, suggested_order_qty):
	if avg_daily <= 0:
		return "ไม่มีประวัติการใช้", "muted"
	if lead_time <= 0:
		return "ไม่ได้กำหนด Lead Time", "warning"
	if suggested_order_qty > 0:
		return "ต้องสั่งซื้อ", "danger"
	if below_reorder_point:
		return "ต่ำกว่า Reorder Point", "warning"
	return "สต็อกเพียงพอ", "success"


def _rolling_sums(daily_values, window):
	"""คำนวณผลรวมแบบ sliding window ความยาว `window` วัน จาก daily_values (รวมวันที่ไม่มีการใช้เป็น 0)
	คืนค่า list ว่างถ้าประวัติสั้นกว่า window (คำนวณไม่ได้)"""
	window = cint(window)
	if window <= 0 or len(daily_values) < window:
		return []

	sums = []
	current = sum(daily_values[:window])
	sums.append(current)
	for i in range(window, len(daily_values)):
		current += daily_values[i] - daily_values[i - window]
		sums.append(current)
	return sums


def _percentile(values, pct):
	"""Percentile แบบ linear interpolation (เทียบเท่า numpy.percentile ค่า default)"""
	if not values:
		return 0
	sorted_vals = sorted(values)
	k = (len(sorted_vals) - 1) * (pct / 100)
	f = math.floor(k)
	c = math.ceil(k)
	if f == c:
		return sorted_vals[int(k)]
	d0 = sorted_vals[f] * (c - k)
	d1 = sorted_vals[c] * (k - f)
	return d0 + d1


def _format_percentile(pct):
	return str(int(pct)) if pct == int(pct) else str(pct)
