# Copyright (c) 2026
# License: MIT

import frappe
from frappe.utils import getdate, date_diff, flt, cint


@frappe.whitelist()
def get_reorder_data(from_date, to_date, item_group=None):
	"""
	คำนวณจุดสั่งซื้อ (Reorder Point) ของ Item หลายรายการพร้อมกัน
	โดยใช้ยอดใช้จริงจาก Delivery Note (ที่อ้างอิง Sales Order)
	และ Work Order (ที่อ้างอิง Sales Order) ย้อนหลังตามช่วงวันที่ที่กำหนด
	"""
	frappe.has_permission("Item", "read", throw=True)

	from_date = getdate(from_date)
	to_date = getdate(to_date)

	if date_diff(to_date, from_date) < 0:
		frappe.throw("From Date ต้องมาก่อน To Date")

	total_days = date_diff(to_date, from_date) + 1

	item_group_condition_dn = ""
	item_group_condition_wo = ""
	params = {"from_date": from_date, "to_date": to_date}

	if item_group:
		params["item_group"] = item_group
		item_group_condition_dn = """
			AND dni.item_code IN (
				SELECT name FROM `tabItem` WHERE item_group = %(item_group)s
			)
		"""
		item_group_condition_wo = """
			AND wo.production_item IN (
				SELECT name FROM `tabItem` WHERE item_group = %(item_group)s
			)
		"""

	# --- 1) Usage from Delivery Note Item against Sales Order ---
	dn_rows = frappe.db.sql(
		f"""
		SELECT dni.item_code AS item_code, dn.posting_date AS tdate, SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus = 1
			AND dn.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND IFNULL(dni.against_sales_order, '') != ''
			{item_group_condition_dn}
		GROUP BY dni.item_code, dn.posting_date
		""",
		params,
		as_dict=True,
	)

	# --- 2) Usage from Work Order (produced against a Sales Order) ---
	wo_rows = frappe.db.sql(
		f"""
		SELECT wo.production_item AS item_code, wo.actual_end_date AS tdate, SUM(wo.produced_qty) AS qty
		FROM `tabWork Order` wo
		WHERE wo.docstatus = 1
			AND IFNULL(wo.sales_order, '') != ''
			AND wo.produced_qty > 0
			AND wo.actual_end_date BETWEEN %(from_date)s AND %(to_date)s
			{item_group_condition_wo}
		GROUP BY wo.production_item, wo.actual_end_date
		""",
		params,
		as_dict=True,
	)

	# --- Combine usage into { item_code: { date: qty } } ---
	usage_map = {}
	for row in dn_rows + wo_rows:
		item_code = row.item_code
		tdate = row.tdate
		qty = flt(row.qty)
		usage_map.setdefault(item_code, {})
		usage_map[item_code][tdate] = usage_map[item_code].get(tdate, 0) + qty

	if not usage_map:
		return []

	item_codes = list(usage_map.keys())

	# --- Item master info (name, existing lead_time_days) ---
	items = frappe.get_all(
		"Item",
		filters={"name": ["in", item_codes]},
		fields=["name", "item_name", "lead_time_days"],
	)
	item_info = {d.name: d for d in items}

	# --- Lead time from Item Supplier child table (fallback to Item.lead_time_days) ---
	supplier_lead_rows = frappe.db.sql(
		"""
		SELECT parent AS item_code, lead_time_days
		FROM `tabItem Supplier`
		WHERE parent IN %(item_codes)s
			AND IFNULL(lead_time_days, 0) > 0
		""",
		{"item_codes": item_codes},
		as_dict=True,
	)
	supplier_lead_map = {}
	for row in supplier_lead_rows:
		supplier_lead_map.setdefault(row.item_code, []).append(flt(row.lead_time_days))

	# --- Current stock on hand (all warehouses) ---
	bin_rows = frappe.db.sql(
		"""
		SELECT item_code, SUM(actual_qty) AS qty
		FROM `tabBin`
		WHERE item_code IN %(item_codes)s
		GROUP BY item_code
		""",
		{"item_codes": item_codes},
		as_dict=True,
	)
	stock_map = {row.item_code: flt(row.qty) for row in bin_rows}

	result = []
	for item_code, daily_usage in usage_map.items():
		daily_values = list(daily_usage.values())
		total_qty = sum(daily_values)
		avg_daily = total_qty / total_days if total_days else 0
		max_daily = max(daily_values) if daily_values else 0

		lead_times = supplier_lead_map.get(item_code)
		if lead_times:
			avg_lead = sum(lead_times) / len(lead_times)
			max_lead = max(lead_times)
		else:
			fallback_lead = flt(item_info.get(item_code, {}).get("lead_time_days") or 0)
			avg_lead = fallback_lead
			max_lead = fallback_lead

		safety_stock = max(0, (max_daily * max_lead) - (avg_daily * avg_lead))
		reorder_point = (avg_daily * avg_lead) + safety_stock
		current_stock = stock_map.get(item_code, 0)

		result.append(
			{
				"item_code": item_code,
				"item_name": item_info.get(item_code, {}).get("item_name") or item_code,
				"avg_daily_usage": round(avg_daily, 2),
				"max_daily_usage": round(max_daily, 2),
				"avg_lead_time": round(avg_lead, 2),
				"max_lead_time": round(max_lead, 2),
				"safety_stock": round(safety_stock, 2),
				"reorder_point": round(reorder_point, 2),
				"current_stock": round(current_stock, 2),
				"below_reorder_point": current_stock < reorder_point,
			}
		)

	# เรียง Item ที่ต่ำกว่าจุดสั่งซื้อไว้บนสุด
	result.sort(key=lambda d: (not d["below_reorder_point"], d["item_code"]))

	return result
