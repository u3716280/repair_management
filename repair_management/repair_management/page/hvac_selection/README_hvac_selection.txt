HVAC Selection — Frappe Desk Page

ไฟล์หลัก: hvac_selection.js
Route/Page name: hvac-selection
Class: HVACSelection

สิ่งที่เพิ่มจากไฟล์ฐาน
- Fan duty point summary
- ประมาณ BHP, shaft kW, input kW และขนาดมอเตอร์มาตรฐาน
- เลือกชนิดพัดลมและกำหนด Fan/Motor efficiency
- Motor margin
- Duct velocity range ตามประเภทระบบ
- Rectangular duct aspect-ratio warning
- Noise-risk indicator
- System-effect checklist
- Duct-size comparison หลายความเร็ว
- Calculation assumptions ในผลลัพธ์และรายงานพิมพ์
- Exhaust cap แบบเลือกเปิด/ปิด
- Collector แยกจากท่อเมนหลายแถว
- ห้องน้ำคำนวณตามจำนวนโถ
- Makeup Air ปรับเปอร์เซ็นต์ได้
- ใช้ความเร็วรูที่เลือกคำนวณ Hood entry

การติดตั้งโดยย่อ
1. สร้าง Page ใน Frappe ชื่อ hvac-selection
2. วางไฟล์เป็น JavaScript ของ Page หรือแทนไฟล์ generated page script ตามโครงสร้าง custom app
3. build/restart ตาม workflow ของ bench ที่ใช้งาน
4. clear cache แล้วเปิด route /app/hvac-selection

หมายเหตุ
- ยังไม่รวม branch-level elbow tracking ตามคำสั่ง
- ผลลัพธ์เป็น preliminary selection ต้องตรวจ Fan Curve, motor service factor, electrical load และข้อกำหนดหน้างานจริง
