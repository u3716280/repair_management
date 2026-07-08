# HVAC Air Calculator สำหรับ ERPNext

Page สำหรับคำนวณ **ปริมาณลม (CFM)** และ **ความดันสถิต (in.wg)** จาก
- **พื้นที่ห้อง** ตามประเภทห้อง (ASHRAE 62.1 + วิธี ACH)
- **ขนาดฝาชี/ฮู้ดครัว** (ASHRAE 154 / IMC 507)

พร้อมประเมิน ESP, ขนาดท่อแนะนำ, ลมชดเชย (Makeup Air) และคำแนะนำการเลือกพัดลมตาม AMCA 210

## การติดตั้ง

```bash
cd ~/frappe-bench
# วางโฟลเดอร์ hvac_calc ไว้ใน apps/ แล้ว:
bench --site your-site.local install-app hvac_calc
bench build --app hvac_calc
bench --site your-site.local clear-cache
```

เปิดใช้งานที่: `https://your-site/app/hvac-calculator`

> ถ้าไม่ต้องการสร้าง app ใหม่ สามารถสร้าง Page ชื่อ `hvac-calculator`
> ใน custom app ที่มีอยู่แล้ว และคัดลอกไฟล์ `hvac_calculator.js` ไปวางแทนได้เลย

## วิธีคำนวณ

### โหมดพื้นที่ห้อง
คำนวณ 2–3 วิธีแล้วใช้ค่ามากที่สุด:
1. **ACH**: CFM = ปริมาตรห้อง (ft³) × ACH ÷ 60
2. **ASHRAE 62.1 Table 6-1**: CFM = (คน × Rp) + (พื้นที่ ft² × Ra)
3. **Exhaust ขั้นต่ำ** (ห้องน้ำ ครัว ที่จอดรถ ฯลฯ): ASHRAE 62.1 Table 6-2

### โหมดฝาชี (Hood)
1. **Linear method**: CFM = ความยาวฮู้ด (ft) × อัตราตาม Duty (IMC 507.13, ฮู้ดไม่มี listing)
2. **Face velocity check**: CFM = พื้นที่หน้าฮู้ด × 85 fpm
3. Makeup Air ≈ 80% ของลมดูด

### ความดันสถิต (ESP)
ฮู้ด/หน้ากาก + แรงเสียดทานท่อ (in.wg/100ft) + ข้องอ + หัวปล่อยทิ้ง + เผื่อ System Effect 15% (AMCA 201)

## มาตรฐานอ้างอิง
- ASHRAE Standard 62.1 — Ventilation for Acceptable Indoor Air Quality
- ASHRAE Standard 154 — Ventilation for Commercial Cooking Operations
- IMC (International Mechanical Code) Section 507
- AMCA 210 — Laboratory Methods of Testing Fans (Certified Ratings)
- AMCA 201 — Fans and Systems (System Effect Factors)

## ข้อจำกัด
ตัวเลขในตารางเป็นค่าออกแบบทั่วไปเพื่อการประเมินเบื้องต้น/เสนอราคา
วิศวกรผู้ออกแบบต้องตรวจสอบกับมาตรฐานฉบับล่าสุดและกฎกระทรวง/กฎหมายท้องถิ่นก่อนใช้งานจริง
