# Copyright (c) 2025, Chirayut D. and contributors
# For license information, please see license.txt

import frappe
import json
from frappe import _
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

        # (3) Qty
        qty = it.qty or 0
        if qty <= 0 and not has_serial:
            errors.append(f"{row} / {it.item_code}: Qty ต้องมากกว่า 0")

        # (4) Serial — field เก็บได้แค่ 1 บรรทัด (fieldtype Data) จึงรองรับ Serial ได้แถวละ
        # 1 หมายเลขเท่านั้น ดังนั้นสินค้ามี Serial ต้อง Qty = 1 เสมอ (ถ้าต้องการหลายชิ้น ให้
        # แยกเป็นคนละแถว) — กันทั้งกรณี Qty ติดลบและ Qty ไม่ตรงกับจำนวน Serial ที่กรอก
        if has_serial:
            serial_text = (it.serial_no or "").strip()
            if not serial_text:
                errors.append(f"{row} / {it.item_code}: ต้องระบุ Serial No.")
            else:
                serials = [s.strip() for s in serial_text.split("\n") if s.strip()]
                if len(serials) != 1:
                    errors.append(
                        f"{row} / {it.item_code}: สินค้ามี Serial No. ต้องระบุ Serial เพียง 1 หมายเลขต่อแถว "
                        f"(พบ {len(serials)} หมายเลข) กรุณาแยกเป็นคนละแถวต่อ 1 Serial"
                    )
                # กันซ้ำภายในเอกสาร
                for s in serials:
                    if s in serial_seen:
                        errors.append(f"{row} / {it.item_code}: Serial '{s}' ถูกใช้ซ้ำในเอกสารนี้")
                    serial_seen.add(s)

                if qty == 0:
                    # ยังไม่ได้กรอก Qty → ตั้งให้อัตโนมัติเป็น 1
                    it.qty = 1
                elif qty != 1:
                    errors.append(
                        f"{row} / {it.item_code}: สินค้ามี Serial No. ต้องมี Qty = 1 ต่อแถว (พบ Qty={qty})"
                    )

        # (5) Symptom
        symptom = (getattr(it, "symptom", None) or "").strip()
        if not symptom:
            errors.append(f"{row} / {it.item_code}: ต้องเลือก/กรอกอาการที่มีปัญหา (Symptom)")
        elif ALLOWED_SYMPTOMS and symptom not in ALLOWED_SYMPTOMS:
            errors.append(f"{row} / {it.item_code}: ค่า Symptom '{symptom}' ไม่อยู่ในตัวเลือกที่อนุญาต")

        # (6) UOM default
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


def _warn_if_target_warehouse_mismatched_supplier(doc):
    """เตือน (ไม่บล็อกการบันทึก) ถ้า Target Warehouse ที่เลือกถูกกำหนดไว้ว่าเป็นคลังของ
    ซัพพลายเออร์รายอื่น ไม่ตรงกับ Supplier ของเอกสารนี้ — ใช้คู่กับการกรอง dropdown ฝั่ง
    client (repair_list.js). ข้ามการเตือนแบบเงียบๆ ถ้าฟิลด์ custom_supplier บน Warehouse
    ยังไม่ถูกสร้าง (เช่น ยังไม่ได้รัน patch repair_target_warehouse_supplier_v1) หรือถ้าคลัง
    นั้นยังไม่ได้ผูก Supplier ไว้เลย (ยังไม่ได้ตั้งค่า)"""
    if not getattr(doc, "target_warehouse", None) or not getattr(doc, "supplier", None):
        return
    if not frappe.get_meta("Warehouse").has_field("custom_supplier"):
        return

    warehouse_supplier = frappe.db.get_value("Warehouse", doc.target_warehouse, "custom_supplier")
    if warehouse_supplier and warehouse_supplier != doc.supplier:
        supplier_name = (
            frappe.db.get_value("Supplier", warehouse_supplier, "supplier_name") or warehouse_supplier
        )
        frappe.msgprint(
            f"คำเตือน: คลังปลายทาง <b>{doc.target_warehouse}</b> ถูกกำหนดให้เป็นคลังของซัพพลายเออร์ "
            f"<b>{supplier_name}</b> ซึ่งไม่ตรงกับซัพพลายเออร์ของเอกสารนี้",
            title="คำเตือน",
            indicator="orange",
        )


def _insert_and_submit_se(se) -> str:
    """Insert แล้ว submit Stock Entry; ถ้า submit ล้มเหลวให้ลบ draft ทิ้งเพื่อไม่ให้ค้างเป็น
    เอกสาร Stock Entry กำพร้าที่ไม่มีอะไรอ้างอิงถึง แล้วโยน exception เดิมต่อ"""
    se.insert(ignore_permissions=True)
    try:
        se.submit()
    except Exception:
        frappe.delete_doc("Stock Entry", se.name, ignore_permissions=True, force=True)
        raise
    return se.name


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

    return _insert_and_submit_se(se)

def _make_cancel_reversal(doc, from_warehouse: str, to_warehouse: str):
    """สร้าง Stock Entry ย้อนสต็อกตอน cancel เฉพาะจำนวนที่ยังไม่ได้รับคืน (qty - returned_qty)"""
    rows = []
    for it in doc.items:
        if not it.item_code:
            continue
        remaining = float(it.qty or 0) - float(getattr(it, "returned_qty", 0) or 0)
        if remaining <= 0:
            continue
        row = {
            "item_code": it.item_code,
            "qty": remaining,
            "s_warehouse": from_warehouse,
            "t_warehouse": to_warehouse,
            "uom": it.uom or frappe.db.get_value("Item", it.item_code, "stock_uom"),
        }
        if getattr(it, "serial_no", None):
            row["serial_no"] = it.serial_no
        if getattr(it, "batch_no", None):
            row["batch_no"] = it.batch_no
        rows.append(row)

    if not rows:
        return None

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.company = doc.company
    se.from_warehouse = from_warehouse
    se.to_warehouse = to_warehouse
    for row in rows:
        se.append("items", row)
    return _insert_and_submit_se(se)


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

    # กันคำขอ receive_return สองคำขอชนกันบนเอกสารเดียวกัน (เช่น ผู้ใช้กดปุ่มซ้ำ) ซึ่งอาจทำให้
    # ทั้งคู่อ่าน returned_qty เดิมก่อนที่อีกฝั่งจะเขียน แล้วรับเกิน remaining ร่วมกันได้
    try:
        doc.lock(timeout=5)
    except frappe.DocumentLockedError:
        frappe.throw("เอกสารนี้กำลังถูกประมวลผลรับคืนโดยคำขออื่นอยู่ กรุณาลองใหม่อีกครั้ง")

    try:
        # safety checks
        if doc.docstatus != 1:
            frappe.throw("เอกสารต้องอยู่ในสถานะ Submitted ก่อนรับของกลับ")
        if not getattr(doc, "from_warehouse", None):
            frappe.throw("เอกสารไม่มี From Warehouse")
        if not getattr(doc, "target_warehouse", None):
            frappe.throw("เอกสารไม่มี Target Warehouse")

        items_to_return = []
        # idx -> qty ที่ถูกรวมเข้า items_to_return จริง ใช้เป็นแหล่งความจริงเดียวสำหรับอัปเดต
        # returned_qty ด้านล่าง กันไม่ให้ returned_qty ขยับโดยไม่มี Stock Entry รองรับจริง
        qty_by_idx = {}

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
            # เทียบแบบมี tolerance กันปัญหาความคลาดเคลื่อนของ float (เหมือนเช็ค full-return
            # ของสินค้ามี Serial ด้านล่าง) ไม่งั้นรายการที่มี Qty ทศนิยมอาจโดนปฏิเสธการรับคืน
            # เต็มจำนวนคงเหลือ ทั้งที่จริงพอดีเป๊ะ เพราะ remaining คลาดเคลื่อนเล็กน้อยจาก float
            if row_qty > remaining + 1e-6:
                frappe.throw(f"แถว {idx} ({it.item_code}): จำนวนรับคืน {row_qty} เกินยอดคงเหลือ {remaining}")

            # ถ้าเป็นสินค้ามี Serial: บังคับรับเป็น 'เต็มจำนวน serial' เท่านั้น (เพื่อไม่ให้ serial หาย)
            has_serial = frappe.db.get_value("Item", it.item_code, "has_serial_no")
            if has_serial:
                serial_text = (it.serial_no or "").strip()
                serials = [s.strip() for s in serial_text.split("\n") if s.strip()] if serial_text else []
                # ในสคีมาปัจจุบันเราไม่ได้ส่ง serial เฉพาะส่วน ดังนั้นบังคับให้รับครบเท่าจำนวนที่เหลือ
                # เทียบแบบมี tolerance กันปัญหาความคลาดเคลื่อนของ float
                if abs(row_qty - remaining) > 1e-6:
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
            qty_by_idx[idx] = row_qty

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
        _insert_and_submit_se(se)

        # อัปเดต returned_qty เฉพาะแถวที่ถูกรวมเข้า Stock Entry ที่เพิ่ง submit จริงเท่านั้น
        # (ใช้ qty_by_idx แทนการคำนวณ eligibility ซ้ำจาก selected_idx/qty_map เพื่อไม่ให้
        # returned_qty ขยับโดยไม่มี Stock Entry รองรับ — ดู qty_by_idx ด้านบน)
        for idx, it in enumerate(doc.items, start=1):
            inc = qty_by_idx.get(idx, 0)
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

        frappe.msgprint(f"สร้าง Stock Entry รับกลับ: <b>{se.name}</b>", indicator="green", alert=True)
        return {"stock_entry": se.name, "new_status": new_status}
    finally:
        doc.unlock()


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

    def validate(self):
        if not getattr(self, "supplier", None) or not getattr(self, "company", None):
            frappe.throw("Supplier และ Company จำเป็น")
        # ตรวจว่ามีคลังด้วย (ตั้งชื่อฟิลด์ให้สอดคล้องกับ Doctype ของคุณ)
        if not getattr(self, "from_warehouse", None):
            frappe.throw("ต้องระบุ From Warehouse")
        if not getattr(self, "target_warehouse", None):
            frappe.throw("ต้องระบุ Target Warehouse")

        _validate_items(self)
        _warn_if_target_warehouse_mismatched_supplier(self)

    def on_submit(self):
        # โอนเข้า "คลังซ่อม/ซัพพลายเออร์"
        _make_material_transfer(self, self.from_warehouse, self.target_warehouse)

        # อัปเดตสถานะ
        if hasattr(self, "status"):
            self.db_set("status", "In Repair", update_modified=False)

    def on_cancel(self):
        # กันชนกับ receive_return ที่อาจกำลังประมวลผลอยู่บนเอกสารเดียวกัน (ใช้ lock เดียวกันกับ
        # receive_return()) ไม่งั้น on_cancel อาจอ่าน returned_qty ที่กำลังจะเปลี่ยน (stale) แล้ว
        # สร้าง Stock Entry ย้อนสต็อกซ้ำกับที่ receive_return กำลังจะสร้าง
        try:
            self.lock(timeout=5)
        except frappe.DocumentLockedError:
            frappe.throw("เอกสารนี้กำลังถูกประมวลผลรับคืนอยู่ กรุณาลองยกเลิกใหม่อีกครั้งในอีกสักครู่")

        # ถ้าต้องย้อนสต็อกอัตโนมัติ: reverse transfer กลับเฉพาะจำนวนที่ยังไม่ได้รับคืน
        # (ส่วนที่รับคืนแล้วผ่าน receive_return ถูกย้อนสต็อกไปแล้ว ไม่ต้องทำซ้ำ)
        try:
            # from_warehouse/target_warehouse เป็นฟิลด์บังคับที่ validate() คุมไว้แล้ว จึงไม่ต้องเช็คซ้ำ
            # ที่นี่ (เดิมมี `_ = getattr(...)` เป็นการ์ดที่ไม่มีผลจริง แต่ดันไปบัง frappe._
            # ฟังก์ชันแปลภาษาทั้งเมธอดนี้โดยไม่ตั้งใจ — เอาออกแทนที่จะเปลี่ยนชื่อ)

            # Reverse โอนกลับเฉพาะยอดคงเหลือ
            se_name = _make_cancel_reversal(self, self.target_warehouse, self.from_warehouse)
            if se_name:
                self.add_comment(
                    "Comment", f"ยกเลิกเอกสาร: สร้าง Stock Entry ย้อนสต็อก <b>{se_name}</b>"
                )
        except Exception:
            # ไม่บล็อกการ cancel เอกสารหลัก หากย้อนสต็อกล้มเหลว แต่ต้องบันทึกไว้ถาวร
            # ไม่ใช่แค่ msgprint ที่หายไปทันทีที่ผู้ใช้ปิดหน้าจอ
            frappe.log_error(frappe.get_traceback(), "Repair List: Cancel reversal failed")
            self.add_comment(
                "Comment",
                "คำเตือน: ย้อน Stock Entry ไม่สำเร็จเมื่อยกเลิกเอกสารนี้ "
                "สต็อกในคลังปลายทางอาจค้างอยู่ กรุณาตรวจสอบและย้อนด้วยตนเอง (ดู Error Log)",
            )
            frappe.msgprint(
                "คำเตือน: ย้อน Stock Entry ไม่สำเร็จ โปรดตรวจสอบด้วยตนเอง (บันทึกไว้ใน Comment ของเอกสารนี้แล้ว)",
                indicator="red",
            )
        finally:
            # สถานะต้องสอดคล้องกับ docstatus เสมอ ไม่ว่าการย้อนสต็อกจะสำเร็จหรือไม่
            if hasattr(self, "status"):
                self.db_set("status", "Cancelled", update_modified=False)
            self.unlock()
