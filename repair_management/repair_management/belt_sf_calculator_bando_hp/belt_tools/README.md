# Belt SF Calculator — Frappe/ERPNext Custom Page

SPA สำหรับคำนวณแรงตึงติดตั้งสายพาน V-belt (SPZ, SPA, SPB, A, B) หน้าตาแบบ WebCAP

## โครงสร้างไฟล์

```
your_app/
└── your_app/
    └── page/
        └── belt_sf_calculator/
            ├── __init__.py
            ├── belt_sf_calculator.json
            ├── belt_sf_calculator.js
            └── belt_sf_calculator.css
```

## วิธีติดตั้ง (ลงใน custom app ที่มีอยู่แล้ว)

1. คัดลอกโฟลเดอร์ `page/belt_sf_calculator` ไปไว้ใต้ module ใด module หนึ่งของ app คุณ
   เช่น `apps/my_app/my_app/my_app/page/belt_sf_calculator`
2. แก้ค่า `"module"` ในไฟล์ `belt_sf_calculator.json` ให้ตรงกับชื่อ Module ของคุณ
   (ต้องมีอยู่ใน `modules.txt` ของ app) — ค่าเริ่มต้นคือ `Belt Tools`
3. รันคำสั่ง:

```bash
bench --site your-site migrate
bench build --app my_app
bench --site your-site clear-cache
```

4. เปิดใช้งานที่ URL: `https://your-site/app/belt-sf-calculator`

## วิธีติดตั้ง (สร้าง app ใหม่)

```bash
bench new-app belt_tools
bench --site your-site install-app belt_tools
# เพิ่ม module "Belt Tools" ใน apps/belt_tools/belt_tools/modules.txt
# คัดลอกโฟลเดอร์ page/belt_sf_calculator ตามโครงสร้างด้านบน
bench --site your-site migrate && bench build
```

## ฟีเจอร์

- Power สลับหน่วย HP / kW, Belt Length สลับ Inch / mm
- Service Factor พร้อมตารางเลือก (Select SF) ตามลักษณะโหลด × ชั่วโมงใช้งานต่อวัน
- Belt Profile: SPZ, SPA, SPB, A, B พร้อมรายการเส้นผ่านศูนย์กลางพูลเลย์มาตรฐานต่อรุ่น
- Pulley เลือกได้ทั้ง Standard (dropdown) และ Custom (พิมพ์เอง) ทั้ง Driver / Driven
- ผลลัพธ์: กำลังออกแบบ, อัตราทด, ความเร็วสายพาน, ระยะห่างแกน, มุมโอบ + FA,
  T1/T2, แรงตึงติดตั้งสถิตต่อเส้น (N/kgf), แรงกดและระยะกดทดสอบ (deflection 16 mm/m)
- **HP Rating ตามคู่มือ Bando** → คำนวณ "จำนวนเส้นที่แนะนำ" อัตโนมัติ:
  - Base HP + Speed Ratio Adder (bilinear interpolation ตามเส้นผ่านศูนย์กลางพูลเลย์เล็ก × RPM ฝั่งเร็ว)
  - Coefficient of Belt Length (FL) ตามความยาวสายพาน
  - จำนวนเส้น = Design HP ÷ (HP ต่อเส้น × FA × FL) ปัดขึ้น (Bando Procedure 6–7)
  - ตารางอ้างอิง: A = Table 22/23, B = Table 24/25, SPZ ≈ 3V = Table 7/8,
    SPB ≈ 5V = Table 9/10, SPA ≈ AX = Table 32/33 (ใกล้เคียงที่สุดที่ตีพิมพ์)
- คำเตือนอัตโนมัติ: พูลเลย์เล็กกว่าค่าต่ำสุด, ความเร็วเกิน, มุมโอบ < 120°,
  ค่านอกช่วงตาราง rating, จำนวนเส้นที่ใส่น้อยกว่าที่แนะนำ

> ⚠️ ตาราง HP Rating ครอบคลุม RPM 485–3450 (A, SPZ, SPA) และ 485–1750 (B, SPB)
> นอกช่วงนี้ระบบใช้ค่าขอบตารางและแจ้งเตือน — ควรเทียบกับ Bando V-Belt Design Manual ก่อนใช้งานจริง
