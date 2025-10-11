import frappe
from frappe.model.document import Document
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

# Helper
ALLOWED_SYMPTOMS = None  # ถ้าอยากคุมตัวเลือก ให้ใส่ลิสต์เช่น ["No Power","Noise","Vibration","Overheat"]

def _validate_items(doc):
    if not getattr(doc, "items", None):
        frappe.throw("ต้องมีรายการอย่างน้อย 1 รายการ")

    serial_seen = set()
    errors = []
    warnings = []

    for idx, it in enumerate(doc.items, start=1):
        row = f"แถวที่ {idx}"

        # 1) item code
        if not it.item_code:
            errors.append(f"{row}: ต้องระบุ Item Code")
            continue  # ข้ามเช็คอื่นในแถวนี้

        # 2) flags จาก Item master
        has_serial = frappe.db.get_value("Item", it.item_code, "has_serial_no")
        has_batch  = frappe.db.get_value("Item", it.item_code, "has_batch_no")

        # 3) qty
        qty = (it.qty or 0)
        if qty <= 0:
            # ถ้าเป็น item non-serial ต้อง > 0 เสมอ
            if not has_serial:
                errors.append(f"{row} / {it.item_code}: Qty ต้องมากกว่า 0")
        # ถ้าเป็น serial—ปกติควร qty=1 (ถ้าคุณต้องการบังคับจริง ๆ ปลดคอมเมนต์บรรทัดถัดไป)
        # elif has_serial and qty != 1:
        #     errors.append(f"{row} / {it.item_code}: เป็นสินค้าแบบ Serial ควรใส่ Qty = 1 ต่อหนึ่งแถว")

        # 4) serial
        if has_serial:
            if not it.serial_no:
                errors.append(f"{row} / {it.item_code}: ต้องระบุ Serial No.")
            else:
                # กัน serial ซ้ำในเอกสารเดียวกัน
                serials = [s.strip() for s in str(it.serial_no).split("\n") if s.strip()]
                for s in serials:
                    if s in serial_seen:
                        errors.append(f"{row} / {it.item_code}: Serial '{s}' ถูกใช้ซ้ำในเอกสารนี้")
                    serial_seen.add(s)

        # 5) batch
        if has_batch:
            # เปลี่ยนเป็นบังคับถ้าองค์กรคุณ track batch จริงจัง
            if not getattr(it, "batch_no", None):
                warnings.append(f"{row} / {it.item_code}: ควรเลือก Batch No. (ไม่เลือกได้ แต่ไม่แนะนำ)")

        # 6) symptom (ควรบังคับจริง ไม่ใช่ msgprint)
        symptom = (getattr(it, "symptom", None) or "").strip()
        if not symptom:
            errors.append(f"{row} / {it.item_code}: ต้องเลือก/กรอกอาการที่มีปัญหา (Symptom)")
        elif ALLOWED_SYMPTOMS and symptom not in ALLOWED_SYMPTOMS:
            errors.append(f"{row} / {it.item_code}: ค่า Symptom '{symptom}' ไม่อยู่ในตัวเลือกที่อนุญาต")

        # 7) UOM (กันแถวว่าง UOM ในบางเคส)
        if not getattr(it, "uom", None):
            # ดึง stock_uom มาใส่ให้เลย ถ้าว่าง
            stock_uom = frappe.db.get_value("Item", it.item_code, "stock_uom")
            if stock_uom:
                it.uom = stock_uom
            else:
                warnings.append(f"{row} / {it.item_code}: ไม่พบ UOM จะพยายามใช้ Stock UOM อัตโนมัติ")

    if warnings:
        frappe.msgprint("<br>".join(warnings), title="คำเตือน", indicator="orange")

    if errors:
        # รวมเป็นก้อนเดียว โยนทิ้งเพื่อให้ผู้ใช้แก้
        frappe.throw("<br>".join(errors))

# def _make_entry(doc):
#        se = frappe.new_doc("Stock Entry")
#        se.stock_entry_type = "Material Transfer"
#        se.company = doc.company
#        se.from_warehouse = doc.from_warehouse
#        se.to_warehouse = doc.target_warehouse
#        for it in doc.items:
#            se.append("items", {
#                "item_code": it.item_code,
#                "qty": it.qty,
#                "s_warehouse": doc.from_warehouse,
#                "t_warehouse": doc.target_warehouse,
#                "serial_no": it.serial_no or None,
#                "uom": it.uom or frappe.db.get_value("Item", it.item_code, "stock_uom"),
#            })
#        se.insert(ignore_permissions=True)
#        se.submit()
#        frappe.db.set_value(doc.doctype, doc.name, "status", "In Repair")


class RepairList(Document):
    # ตัวอย่าง: สร้างฟิลด์ช่วยประกอบชื่อ หรือข้อมูลสรุปก่อนบันทึก
    def before_save(self):
        # ถ้ามี field supplier_name และ title/subject ใน DocType
        if getattr(self, "supplier", None):
            sup_name = frappe.db.get_value("Supplier", self.supplier, "supplier_name") or self.supplier
        else:
            sup_name = ""
        # ถ้ามี field summary ใน doctype ให้เติมค่า (ปรับชื่อฟิลด์ตามที่คุณสร้าง)
        # if hasattr(self, "summary"):
        #    self.summary = f"{sup_name} - Repair List"

    def validate(self):
        if not getattr(self, "supplier", None) or not getattr(self, "company", None):
            frappe.throw("Supplier และ Company จำเป็น")
        _validate_items(self)

    def on_submit(self):
        # ที่นี่คุณจะทำอะไรก็ได้ตอน Submit
        # ตัวอย่าง: เปลี่ยนสถานะ/บันทึกเวลา/แจ้งเตือน
        # if hasattr(self, "status"):
        #    self.status = "In Repair"
        # ถ้าจะสร้าง Stock Entry ก็ทำได้คล้าย Repair Shipment ของเรา
        # (คอมเมนต์ไว้เป็นตัวอย่าง)
        # se = frappe.new_doc("Stock Entry")
        # se.stock_entry_type = "Material Transfer"
        # se.company = self.company
        # se.from_warehouse = self.source_warehouse
        # se.to_warehouse = self.repair_wareh
        # frappe.db.set_value(self.doctype, self.name, "status", "In Repair")
	# self.set_status()
