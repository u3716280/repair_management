# Copyright (c) 2025, Chirayut D. and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
from frappe.utils import nowdate

# -----------------------------
# Helpers
# -----------------------------
ALLOWED_SYMPTOMS = None  # เช่น ["No Power", "Noise", "Vibration", "Overheat"]

def _validate_items(doc):
    if not getattr(doc, "items", None):
        frappe.throw("ต้องมีรายการอย่างน้อย 1 รายการ")

    serial_seen = set()
    errors, warnings = [], []

    for idx, it in enumerate(doc.items, start=1):
        row = f"แถวที่ {idx}"

        # (1) Item code
        if not it.item_code:
            errors.append(f"{row}: ต้องระบุ Item Code")
            continue

        # (2) flags จาก Item master
        has_serial = frappe.db.get_value("Item", it.item_code, "has_serial_no")
        has_batch  = frappe.db.get_value("Item", it.item_code, "has_batch_no")

        # (3) Qty
        qty = it.qty or 0
        if qty <= 0 and not has_serial:
            errors.append(f"{row} / {it.item_code}: Qty ต้องมากกว่า 0")

        # (4) Serial
        if has_serial:
            serial_text = (it.serial_no or "").strip()
            if not serial_text:
                errors.append(f"{row} / {it.item_code}: ต้องระบุ Serial No.")
            else:
                serials = [s.strip() for s in serial_text.split("\n") if s.strip()]
                # กันซ้ำภายในเอกสาร
                for s in serials:
                    if s in serial_seen:
                        errors.append(f"{row} / {it.item_code}: Serial '{s}' ถูกใช้ซ้ำในเอกสารนี้")
                    serial_seen.add(s)
                # ออโต้เซ็ต qty = จำนวน serial ถ้าไม่ได้กรอก
                if qty == 0:
                    it.qty = len(serials)

        # (5) Batch
        if has_batch and not getattr(it, "batch_no", None):
            # ถ้าองค์กรคุณเข้มเรื่อง Batch เปลี่ยนเป็น errors.append(...) ได้เลย
            warnings.append(f"{row} / {it.item_code}: ควรเลือก Batch No.")

        # (6) Symptom
        symptom = (getattr(it, "symptom", None) or "").strip()
        if not symptom:
            errors.append(f"{row} / {it.item_code}: ต้องเลือก/กรอกอาการที่มีปัญหา (Symptom)")
        elif ALLOWED_SYMPTOMS and symptom not in ALLOWED_SYMPTOMS:
            errors.append(f"{row} / {it.item_code}: ค่า Symptom '{symptom}' ไม่อยู่ในตัวเลือกที่อนุญาต")

        # (7) UOM default
        if not getattr(it, "uom", None):
            stock_uom = frappe.db.get_value("Item", it.item_code, "stock_uom")
            if stock_uom:
                it.uom = stock_uom
            else:
                warnings.append(f"{row} / {it.item_code}: ไม่พบ UOM")

    if warnings:
        frappe.msgprint("<br>".join(warnings), title="คำเตือน", indicator="orange")
    if errors:
        frappe.throw("<br>".join(errors))


def _make_material_transfer(doc, from_warehouse: str, to_warehouse: str) -> str:
    """สร้าง Stock Entry: Material Transfer แล้วคืนค่าเลขที่ SE"""
    if not from_warehouse:
        frappe.throw("ต้องระบุ From Warehouse")
    if not to_warehouse:
        frappe.throw("ต้องระบุ Target Warehouse")

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.company = doc.company
    se.from_warehouse = from_warehouse
    se.to_warehouse = to_warehouse

    for it in doc.items:
        row = {
            "item_code": it.item_code,
            "qty": it.qty or 1,
            "s_warehouse": from_warehouse,
            "t_warehouse": to_warehouse,
            "uom": it.uom or frappe.db.get_value("Item", it.item_code, "stock_uom"),
        }
        if getattr(it, "serial_no", None):
            row["serial_no"] = it.serial_no
        if getattr(it, "batch_no", None):
            row["batch_no"] = it.batch_no
        se.append("items", row)

    se.insert(ignore_permissions=True)
    se.submit()
    return se.name

@frappe.whitelist()
def receive_return(
    docname: str,
    selected_idx=None,              # JSON list[int], 1-based row index ที่เลือก
    qty_map=None,                   # JSON dict: {"1": 2.0, "3": 1.0} จำนวนรับคืนต่อแถว
    item_status_map=None,           # JSON dict: {"1":"Free","3":"Charge"} ถ้าใช้รายแถว
    use_global_status: int = 1,     # 1 = ใช้สถานะเดียวทั้งชุด
    global_status: str | None = None
):
    """
    รับของกลับจากซ่อมแบบกำหนด 'จำนวนต่อแถว' + 'สถานะซ่อม'
    - คุมไม่ให้รับเกิน (qty - returned_qty)
    - อัปเดต child.returned_qty สะสม
    - เซ็ต child.status ตาม global หรือรายแถว
    - สร้าง Stock Entry (Material Transfer): target_warehouse -> from_warehouse
    - อัปเดต parent.status = Returned/Partial Returned, parent.returned (Check), parent.returned_date
    """
    if isinstance(selected_idx, str):
        selected_idx = json.loads(selected_idx or "[]")
    if isinstance(qty_map, str):
        qty_map = json.loads(qty_map or "{}")
    if isinstance(item_status_map, str):
        item_status_map = json.loads(item_status_map or "{}")

    doc = frappe.get_doc("Repair List", docname)

    # safety checks
    if doc.docstatus != 1:
        frappe.throw("เอกสารต้องอยู่ในสถานะ Submitted ก่อนรับของกลับ")
    if not getattr(doc, "from_warehouse", None):
        frappe.throw("เอกสารไม่มี From Warehouse")
    if not getattr(doc, "target_warehouse", None):
        frappe.throw("เอกสารไม่มี Target Warehouse")

    items_to_return = []
    chosen_count = 0

    for idx, it in enumerate(doc.items, start=1):
        if selected_idx and idx not in selected_idx:
            continue
        if not it.item_code:
            continue

        row_key = str(idx)
        row_qty = float(qty_map.get(row_key, 0)) if qty_map else 0.0

        total_qty = float(it.qty or 0)
        returned_qty = float(getattr(it, "returned_qty", 0) or 0)
        remaining = max(total_qty - returned_qty, 0)

        if remaining <= 0:
            # แถวนี้คืนครบแล้ว ข้าม
            continue
        if row_qty <= 0:
            # ไม่กำหนดจำนวน หรือ <= 0 ข้าม
            continue
        if row_qty > remaining:
            frappe.throw(f"แถว {idx} ({it.item_code}): จำนวนรับคืน {row_qty} เกินยอดคงเหลือ {remaining}")

        # ถ้าเป็นสินค้ามี Serial: บังคับรับเป็น 'เต็มจำนวน serial' เท่านั้น (เพื่อไม่ให้ serial หาย)
        has_serial = frappe.db.get_value("Item", it.item_code, "has_serial_no")
        if has_serial:
            serial_text = (it.serial_no or "").strip()
            serials = [s.strip() for s in serial_text.split("\n") if s.strip()] if serial_text else []
            # ในสคีมาปัจจุบันเราไม่ได้ส่ง serial เฉพาะส่วน ดังนั้นบังคับให้รับครบเท่าจำนวนที่เหลือ
            if row_qty != remaining:
                frappe.throw(f"แถว {idx} ({it.item_code}): เป็นสินค้ามี Serial กรุณารับคืนเต็มจำนวนคงเหลือ {remaining} ชิ้น")

        # ตั้งสถานะซ่อมของแถว
        if int(use_global_status or 0) == 1:
            if global_status:
                it.db_set("status", global_status, update_modified=False)
        else:
            if item_status_map and row_key in item_status_map and item_status_map[row_key]:
                it.db_set("status", item_status_map[row_key], update_modified=False)

        # เตรียมรายการสำหรับ SE
        se_row = {
            "item_code": it.item_code,
            "qty": row_qty,
            "s_warehouse": doc.target_warehouse,
            "t_warehouse": doc.from_warehouse,
            "uom": it.uom or frappe.db.get_value("Item", it.item_code, "stock_uom"),
        }
        if getattr(it, "serial_no", None):
            se_row["serial_no"] = it.serial_no
        if getattr(it, "batch_no", None):
            se_row["batch_no"] = it.batch_no

        items_to_return.append(se_row)
        chosen_count += 1

    if not items_to_return:
        frappe.throw("ไม่มีรายการสำหรับรับกลับ")

    # สร้าง SE: รับกลับ
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.company = doc.company
    se.from_warehouse = doc.target_warehouse
    se.to_warehouse = doc.from_warehouse
    for r in items_to_return:
        se.append("items", r)
    se.insert(ignore_permissions=True)
    se.submit()

    # อัปเดต returned_qty ของแถวที่เลือก (ใช้ค่าที่ commit สำเร็จแล้ว)
    for idx, it in enumerate(doc.items, start=1):
        row_key = str(idx)
        if selected_idx and idx not in selected_idx:
            continue
        inc = float(qty_map.get(row_key, 0)) if qty_map else 0.0
        if inc > 0:
            new_val = float(getattr(it, "returned_qty", 0) or 0) + inc
            if new_val > float(it.qty or 0):
                new_val = float(it.qty or 0)
            it.db_set("returned_qty", new_val, update_modified=False)

    # คำนวณสถานะรวม
    all_returned = True
    for it in doc.items:
        tot = float(it.qty or 0)
        ret = float(getattr(it, "returned_qty", 0) or 0)
        if ret < tot:
            all_returned = False
            break

    if all_returned:
        new_status = "Returned"
        if hasattr(doc, "returned"):
            doc.db_set("returned", 1, update_modified=False)
        if hasattr(doc, "returned_date"):
            doc.db_set("returned_date", nowdate(), update_modified=False)
    else:
        new_status = "Partial Returned"
        if hasattr(doc, "returned"):
            doc.db_set("returned", 0, update_modified=False)

    if hasattr(doc, "status"):
        doc.db_set("status", new_status, update_modified=False)

    if hasattr(doc, "last_stock_entry"):
        doc.db_set("last_stock_entry", se.name, update_modified=False)

    frappe.msgprint(f"สร้าง Stock Entry รับกลับ: <b>{se.name}</b>", indicator="green", alert=True)
    return {"stock_entry": se.name, "new_status": new_status}


# -----------------------------
# DocType Controller
# -----------------------------
class RepairList(Document):
    def get_indicator(self):
        color = "gray"
        if self.status == "In Repair":
            color = "orange"
        elif self.status == "Partial Returned":
            color = "yellow"
        elif self.status == "Returned":
            color = "green"
        elif self.status == "Cancelled":
            color = "red"
        return _(self.status or "Draft"), color, f"status,=,{self.status or 'Draft'}"

    def before_save(self):
        # เติมสรุป (ปรับชื่อฟิลด์ตาม Doctype ของคุณ)
        if getattr(self, "supplier", None):
            sup_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name") or self.supplier
        else:
            sup_name = ""
        if hasattr(self, "summary"):
            self.summary = f"{sup_name} - Repair List"

    def validate(self):
        if not getattr(self, "supplier", None) or not getattr(self, "company", None):
            frappe.throw("Supplier และ Company จำเป็น")
        # ตรวจว่ามีคลังด้วย (ตั้งชื่อฟิลด์ให้สอดคล้องกับ Doctype ของคุณ)
        if not getattr(self, "from_warehouse", None):
            frappe.throw("ต้องระบุ From Warehouse")
        if not getattr(self, "target_warehouse", None):
            frappe.throw("ต้องระบุ Target Warehouse")

        _validate_items(self)

    def on_submit(self):
        # โอนเข้า "คลังซ่อม/ซัพพลายเออร์"
        se_name = _make_material_transfer(self, self.from_warehouse, self.target_warehouse)

        # เก็บอ้างอิง SE ไว้ในเอกสาร เพื่อ reverse ตอน cancel
        if hasattr(self, "last_stock_entry"):
            self.db_set("last_stock_entry", se_name, update_modified=False)

        # อัปเดตสถานะ
        if hasattr(self, "status"):
            self.db_set("status", "In Repair", update_modified=False)

    def on_cancel(self):
        # ถ้าต้องย้อนสต็อกอัตโนมัติ: reverse transfer กลับ
        # ใช้เลขที่ SE ที่เก็บไว้ ถ้าไม่มี ให้ทำใหม่โดย swap คลัง
        try:
            # ป้องกันเคสฟิลด์ไม่มี/ว่าง
            _ = getattr(self, "from_warehouse")
            _ = getattr(self, "target_warehouse")

            # Reverse โอนกลับ
            _make_material_transfer(self, self.target_warehouse, self.from_warehouse)

            if hasattr(self, "status"):
                self.db_set("status", "Cancelled", update_modified=False)
        except Exception:
            # ไม่บล็อกการ cancel เอกสารหลัก หากย้อนสต็อกล้มเหลว
            frappe.msgprint("คำเตือน: ย้อน Stock Entry ไม่สำเร็จ โปรดตรวจสอบด้วยตนเอง")
