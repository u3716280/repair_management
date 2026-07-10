/* HVAC Air Calculator — CFM & Static Pressure (in.wg)
 * อ้างอิง: ASHRAE 62.1 (Ventilation Rate Procedure & Exhaust Rates),
 * ASHRAE 154 / IMC 507 (Kitchen Hood Exhaust), AMCA 210 (Fan Rating), AMCA 201 (System Effect)
 * หมายเหตุ: ตัวเลขในตารางเป็นค่าออกแบบทั่วไปเพื่อประเมินเบื้องต้น
 * ผู้ออกแบบต้องตรวจสอบกับมาตรฐานฉบับล่าสุดและกฎหมายท้องถิ่นก่อนใช้งานจริง
 */

frappe.pages['hvac-calculator'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('HVAC Air Calculator (CFM / in.wg)'),
		single_column: true,
	});

	new HVACCalculator(page);
};

/* ---------------- ข้อมูลมาตรฐาน ---------------- */

// ASHRAE 62.1 Table 6-1 (ตัวแทนค่า) + ACH ที่ใช้ออกแบบทั่วไป
// rp = cfm/person, ra = cfm/ft², density = คน/1000 ft², ach = Air Changes/Hour (ช่วงออกแบบ)
const ROOM_TYPES = [
	{ id: 'office',      th: 'สำนักงาน (Office)',                rp: 5,    ra: 0.06, density: 5,   ach: [4, 6],   ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'conference',  th: 'ห้องประชุม (Conference)',           rp: 5,    ra: 0.06, density: 50,  ach: [6, 10],  ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'classroom',   th: 'ห้องเรียน (Classroom 9+)',          rp: 10,   ra: 0.12, density: 35,  ach: [4, 6],   ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'dining',      th: 'ร้านอาหาร–โซนนั่งทาน (Dining)',      rp: 7.5,  ra: 0.18, density: 70,  ach: [8, 12],  ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'kitchen',     th: 'ครัวพาณิชย์ (Commercial Kitchen)',  rp: 7.5,  ra: 0.12, density: 20,  ach: [20, 30], exhaust_ra: 0.70, ref: 'ASHRAE 62.1 Table 6-2 (Exhaust 0.7 cfm/ft²)' },
	{ id: 'toilet',      th: 'ห้องน้ำรวม (Public Toilet)',        rp: 0,    ra: 0,    density: 0,   ach: [10, 15], exhaust_fixture: 70, ref: 'ASHRAE 62.1 Table 6-2 (50–70 cfm/โถ)' },
	{ id: 'locker',      th: 'ห้องล็อกเกอร์/เปลี่ยนเสื้อ',         rp: 0,    ra: 0,    density: 0,   ach: [8, 12],  exhaust_ra: 0.50, ref: 'ASHRAE 62.1 Table 6-2 (0.5 cfm/ft²)' },
	{ id: 'gym',         th: 'ฟิตเนส (Gym / Weight Room)',        rp: 20,   ra: 0.06, density: 10,  ach: [8, 12],  ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'retail',      th: 'ร้านค้า (Retail)',                  rp: 7.5,  ra: 0.12, density: 15,  ach: [4, 8],   ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'lobby',       th: 'ล็อบบี้ (Lobby)',                   rp: 5,    ra: 0.06, density: 10,  ach: [4, 6],   ref: 'ASHRAE 62.1 Table 6-1' },
	{ id: 'server',      th: 'ห้อง Server / Electrical',          rp: 0,    ra: 0.06, density: 0,   ach: [15, 20], ref: 'แนวปฏิบัติ (cooling-driven)' },
	{ id: 'lab',         th: 'ห้องปฏิบัติการ (Laboratory)',       rp: 10,   ra: 0.18, density: 25,  ach: [6, 12],  ref: 'ASHRAE 62.1 / Lab guide' },
	{ id: 'machine',     th: 'ห้องเครื่องจักรปล่อยความร้อน (Machine/Equipment)', rp: 0, ra: 0.06, density: 0, ach: [15, 25], ref: 'แนวปฏิบัติ heat-driven — ควรตรวจสอบจากภาระความร้อนจริง (Q = H/(ρ·Cp·ΔT))' },
	{ id: 'factory',     th: 'โรงงาน (Factory / Manufacturing)', rp: 10, ra: 0.18, density: 7, ach: [6, 10], ref: 'ASHRAE 62.1 Table 6-1 (Manufacturing, ไม่ใช้สารอันตราย)' },
	{ id: 'parking',     th: 'ที่จอดรถในอาคาร (Enclosed Parking)', rp: 0,    ra: 0,    density: 0,   ach: [6, 10],  exhaust_ra: 0.75, ref: 'ASHRAE 62.1 Table 6-2 (0.75 cfm/ft²)' },
	{ id: 'laundry',     th: 'ห้องซักรีด (Laundry)',              rp: 0,    ra: 0,    density: 0,   ach: [10, 15], exhaust_ra: 0.50, ref: 'ASHRAE 62.1 Table 6-2' },
];

// อัตราดูดอากาศฮู้ดครัว (ฮู้ดไม่มี listing) — IMC 507.13 / ASHRAE 154
// หน่วย: CFM ต่อความยาวฮู้ด 1 ฟุต
const HOOD_RATES = {
	wall_canopy:   { th: 'ฮู้ดติดผนัง (Wall Canopy)',      light: 200, medium: 300, heavy: 400, extra: 550 },
	island_single: { th: 'ฮู้ดเกาะกลาง แถวเดียว (Island)',  light: 400, medium: 500, heavy: 600, extra: 700 },
	island_double: { th: 'ฮู้ดเกาะกลาง สองแถว (Double)',    light: 250, medium: 300, heavy: 400, extra: 550 },
	backshelf:     { th: 'ฮู้ดหลังเตา (Backshelf/Proximity)', light: 250, light_medium: 300, medium: 350, heavy: 430, extra: null },
};

const DUTY_TH = {
	light: 'Light Duty (เตาอบ, เตานึ่ง)',
	light_medium: 'Light-Medium Duty (เตาต้ม, เตานึ่ง)',
	medium: 'Medium Duty (เตาไทยผัด, เตาทอด)',
	heavy: 'Heavy Duty (เตาผัดไฟแรง, กระทะจีน, ชาร์บรอยล์)',
	extra: 'Extra-Heavy Duty (เตาถ่าน, ฟืน)',
};

// ASHRAE 62.1 Air Class ของอากาศที่ดูด (1 = สะอาด นำกลับได้, 4 = ห้ามหมุนเวียน ต้องทิ้งนอกอาคาร)
const AIR_CLASS = {
	toilet: 2, locker: 2, laundry: 2, parking: 2, gym: 2,
	machine: 2, factory: 2,
	kitchen: 4, lab: 4,
	// อื่นๆ = Class 1
};
const AIR_CLASS_TH = {
	1: 'Class 1 — อากาศปนเปื้อนต่ำ นำกลับมาหมุนเวียนได้',
	2: 'Class 2 — ปนเปื้อนปานกลาง/มีกลิ่น ห้ามหมุนเวียนไปพื้นที่อื่น ควรทิ้งนอกอาคาร',
	3: 'Class 3 — ปนเปื้อนสูง ห้ามหมุนเวียน ต้องทิ้งนอกอาคาร',
	4: 'Class 4 — อันตราย/ไขมัน-ไอสารเคมี ห้ามหมุนเวียนเด็ดขาด ท่อแยกอิสระถึงจุดทิ้ง',
};

// ค่าความดันสถิตองค์ประกอบ (in.wg) — ค่าออกแบบทั่วไป
// ฟิลเตอร์ / อุปกรณ์เสริม — ค่าความดันตกคร่อมออกแบบ (in.wg)
// default = ค่าออกแบบแนะนำ (กึ่งกลางระหว่างสะอาด–สกปรก), hint = ช่วงสะอาด–สกปรก
const FILTER_TYPES = [
	{ id: 'prefilter', th: 'Pre-filter (G4 แผง)',            def: 0.25, hint: 'สะอาด 0.10–0.20, เปลี่ยนที่ 0.50' },
	{ id: 'synthetic', th: 'ใยสังเคราะห์ (Synthetic Media)',  def: 0.15, hint: 'สะอาด 0.08–0.15, เปลี่ยนที่ 0.30' },
	{ id: 'aluminum',  th: 'อลูมิเนียม/ตะแกรงล้างได้ (Washable)', def: 0.12, hint: 'สะอาด 0.05–0.10, ล้างที่ 0.25' },
	{ id: 'grease_baffle', th: 'Grease Baffle Filter (ดักไขมัน)', def: 0.50, hint: 'สะอาด 0.25–0.40, ล้างที่ 0.625 — สแตนเลส/อลูมิเนียม' },
	{ id: 'esp_unit', th: 'เครื่อง ESP (Electrostatic Precipitator)', def: 0.30, hint: 'เซลล์สะอาด 0.15–0.25, ก่อนล้าง ~0.40–0.50 — ดักควัน/ละอองไขมัน ตรวจสเปคผู้ผลิต' },
	{ id: 'bag',       th: 'Bag Filter (F7–F8)',              def: 0.40, hint: 'สะอาด 0.25–0.35, เปลี่ยนที่ 0.60' },
	{ id: 'hepa',      th: 'HEPA (H13–H14)',                  def: 1.50, hint: 'สะอาด ~1.0 (250 Pa), เปลี่ยนที่ ~2.0' },
	{ id: 'carbon',    th: 'Carbon Filter (ดูดกลิ่น)',         def: 0.40, hint: 'ทั่วไป 0.25–0.60 ตามความหนา' },
];

const SP_COMPONENTS = {
	hood_entry: 0.375,      // ฮู้ด + baffle filter สะอาด ~0.25–0.5
	filter_dirty_allow: 0.25, // เผื่อฟิลเตอร์สกปรก
	exhaust_cap: 0.15,      // หัวจ่าย/ตะแกรงปล่อยทิ้ง
	fitting_each: 0.08,     // ข้องอ 90° ต่อจุด (โดยประมาณที่ ~1500-1800 fpm)
	grille: 0.10,           // หน้ากากดูด/จ่าย (ระบบระบายอากาศทั่วไป)
};

const CFM_PER_M2 = 10.7639; // ft² ต่อ m²
const M_TO_FT = 3.28084;

/* ---------------- Page Class ---------------- */

class HVACCalculator {
	constructor(page) {
		this.page = page;
		this.$body = $(page.body);
		this.make();
	}

	make() {
		this.$body.html(this.template());
		this.bind();
		this.render_room_options();
		this.render_hood_options();
		this.render_filter_options();
		this.switch_mode('room');
	}

	template() {
		return `
		<div class="hvac-calc" style="max-width: 980px; margin: 0 auto;">
			<div class="frappe-card p-4 mb-4">
				<div class="btn-group w-100 mb-2" role="group">
					<button type="button" class="btn btn-primary hvac-mode" data-mode="room">คำนวณจากพื้นที่ห้อง</button>
					<button type="button" class="btn btn-default hvac-mode" data-mode="hood">คำนวณจากขนาดฝาชี (Hood)</button>
					<button type="button" class="btn btn-default hvac-mode" data-mode="duct">ดูดอากาศผ่านท่อ (หลายจุด)</button>
				</div>
				<p class="text-muted small mb-0">อ้างอิง ASHRAE 62.1 / ASHRAE 154 / IMC 507 / AMCA 210 &nbsp;•&nbsp; ผลลัพธ์เป็นการประเมินเบื้องต้นสำหรับงานเสนอราคา/ออกแบบขั้นต้น</p>
			</div>

			<!-- โหมดพื้นที่ห้อง -->
			<div class="frappe-card p-4 mb-4 hvac-panel" id="panel-room">
				<h5 class="mb-3">ข้อมูลห้อง</h5>
				<div class="row">
					<div class="col-sm-6 mb-3">
						<label>ประเภทห้อง</label>
						<select class="form-control" id="room_type"></select>
						<small class="text-muted" id="room_ref"></small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>กว้าง (m)</label>
						<input type="number" class="form-control" id="room_w" value="5" step="0.1" min="0.5">
					</div>
					<div class="col-sm-2 mb-3">
						<label>ยาว (m)</label>
						<input type="number" class="form-control" id="room_l" value="10" step="0.1" min="0.5">
						<small class="text-muted" id="area_hint"></small>
					</div>
					<div class="col-sm-3 mb-3">
						<label>ความสูงฝ้า (m)</label>
						<input type="number" class="form-control" id="room_height" value="2.7" step="0.1" min="2">
					</div>
					<div class="col-sm-3 mb-3">
						<label>จำนวนคน (0 = ใช้ค่ามาตรฐาน)</label>
						<input type="number" class="form-control" id="room_people" value="0" min="0">
					</div>
					<div class="col-sm-3 mb-3">
						<label>ACH ที่ใช้ออกแบบ</label>
						<input type="number" class="form-control" id="room_ach" value="6" step="0.5" min="0.5">
						<small class="text-muted" id="ach_hint"></small>
					</div>
					<div class="col-sm-3 mb-3">
						<label>ความร้อนที่ปล่อย (kW)</label>
						<input type="number" class="form-control" id="room_heat" value="0" step="0.5" min="0">
						<small class="text-muted">เครื่องจักร/อุปกรณ์ — 0 = ไม่ใช้วิธีนี้</small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>ΔT ยอมรับ (°C)</label>
						<input type="number" class="form-control" id="room_heat_dt" value="5" step="0.5" min="1">
						<small class="text-muted">อุณหภูมิห้องสูงกว่านอกได้กี่องศา</small>
					</div>
				</div>
			</div>

			<!-- โหมดฮู้ด -->
			<div class="frappe-card p-4 mb-4 hvac-panel" id="panel-hood" style="display:none;">
				<h5 class="mb-3">ข้อมูลฝาชี (Kitchen Hood)</h5>
				<div class="row">
					<div class="col-sm-4 mb-3">
						<label>ชนิดฮู้ด</label>
						<select class="form-control" id="hood_type"></select>
					</div>
					<div class="col-sm-4 mb-3">
						<label>ระดับความหนักของการปรุง (Duty)</label>
						<select class="form-control" id="hood_duty"></select>
					</div>
					<div class="col-sm-2 mb-3">
						<label>ยาว (m)</label>
						<input type="number" class="form-control" id="hood_length" value="2.0" step="0.1" min="0.3">
					</div>
					<div class="col-sm-2 mb-3">
						<label>กว้าง/ลึก (m)</label>
						<input type="number" class="form-control" id="hood_width" value="1.0" step="0.1" min="0.3">
					</div>
				</div>
				<div class="row align-items-end">
					<div class="col-sm-4 mb-2">
						<label class="mb-1"><b>สัมประสิทธิ์ทางเข้าฮู้ด (C)</b></label>
						<div class="input-group input-group-sm">
							<input type="number" class="form-control" id="hood_entry_c" value="0.5" step="0.05" min="0.1" max="2">
							<div class="input-group-append"><span class="input-group-text">× VP</span></div>
						</div>
						<small class="text-muted">แรงดันทางเข้า = C × VP คำนวณอัตโนมัติจากความเร็วลมจริง — ออกแบบดี 0.25, ทั่วไป 0.5, ตื้น/เลี้ยวแรง 0.75–1.0 (ACGIH)</small>
					</div>
					<div class="col-sm-4 mb-2">
						<div class="checkbox mb-1">
							<label class="mb-0">
								<input type="checkbox" id="hood_baffle_check" checked> <b>ฮู้ดมี Baffle Filter (ดักไขมันที่ตัวฮู้ด)</b>
							</label>
						</div>
						<div class="input-group input-group-sm">
							<input type="number" class="form-control" id="hood_baffle_sp" value="0.25" step="0.05" min="0">
							<div class="input-group-append"><span class="input-group-text">in.wg</span></div>
						</div>
						<small class="text-muted">เผื่อสกปรกก่อนล้าง — ไม่ติ๊กถ้าเป็นฮู้ดเปล่า/water wash</small>
					</div>
				</div>
				<small class="text-muted">อัตราดูดคิดจาก CFM ต่อความยาวฮู้ด (ฟุต) ตาม IMC 507.13 / ASHRAE 154 สำหรับฮู้ดไม่มี UL listing — ฮู้ดที่มี listing ให้ใช้ค่าจากผู้ผลิต</small>
			</div>

			<!-- โหมดดูดอากาศผ่านท่อ (หลายจุด) -->
			<div class="frappe-card p-4 mb-4 hvac-panel" id="panel-duct" style="display:none;">
				<h5 class="mb-3">ดูดอากาศผ่านท่อ — หัวดูดหลายจุด</h5>
				<div class="row">
					<div class="col-sm-4 mb-3">
						<label>ประเภทห้อง / อากาศที่ดูด</label>
						<select class="form-control" id="dt_room_type"></select>
						<small class="text-muted" id="dt_room_ref"></small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>กว้าง (m)</label>
						<input type="number" class="form-control" id="dt_w" value="5" step="0.1" min="0.5">
					</div>
					<div class="col-sm-2 mb-3">
						<label>ยาว (m)</label>
						<input type="number" class="form-control" id="dt_l" value="10" step="0.1" min="0.5">
						<small class="text-muted" id="dt_area_hint"></small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>ความสูงฝ้า (m)</label>
						<input type="number" class="form-control" id="dt_h" value="2.7" step="0.1" min="2">
					</div>
					<div class="col-sm-2 mb-3">
						<label>จำนวนคน (0 = มาตรฐาน)</label>
						<input type="number" class="form-control" id="dt_people" value="0" min="0">
					</div>
					<div class="col-sm-2 mb-3">
						<label>ACH ออกแบบ</label>
						<input type="number" class="form-control" id="dt_ach" value="6" step="0.5" min="0.5">
						<small class="text-muted" id="dt_ach_hint"></small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>ความร้อนปล่อย (kW)</label>
						<input type="number" class="form-control" id="dt_heat" value="0" step="0.5" min="0">
						<small class="text-muted">0 = ไม่ใช้วิธีนี้</small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>ΔT ยอมรับ (°C)</label>
						<input type="number" class="form-control" id="dt_heat_dt" value="5" step="0.5" min="1">
					</div>
					<div class="col-sm-2 mb-3">
						<label>จำนวนหัวดูด (จุด)</label>
						<input type="number" class="form-control" id="dt_n" value="4" min="1" max="30">
					</div>
					<div class="col-sm-3 mb-3">
						<label>ความเร็วหน้าหัวดูด (m/s)</label>
						<input type="number" class="form-control" id="dt_face_v" value="2.5" step="0.1" min="0.5">
						<small class="text-muted">≤ 2.5–3 m/s กันเสียงดัง (ASHRAE)</small>
					</div>
					<div class="col-sm-3 mb-3">
						<label>ระยะเครื่องดูดจากห้อง (m)</label>
						<input type="number" class="form-control" id="dt_fan_dist" value="3" step="0.5" min="0">
						<small class="text-muted">ท่อเมนจากขอบห้องถึงพัดลม — ระบบจะรวมเข้าความยาวท่อ</small>
					</div>
				</div>
				<small class="text-muted">ความยาวท่อรวมคำนวณอัตโนมัติ = ท่อเมนตามความยาวห้อง + ระยะถึงเครื่องดูด (ช่อง "ความยาวท่อรวม" ด้านล่างไม่ถูกใช้ในโหมดนี้) — ขนาดท่อและข้องอยังใช้จากการ์ดท่อลม</small>
			</div>

			<!-- ท่อลม & ความดันสถิต -->
			<div class="frappe-card p-4 mb-4">
				<h5 class="mb-3">ขนาดท่อลม & ความดันสถิต (External Static Pressure)</h5>
				<div class="row">
					<div class="col-sm-3 mb-3">
						<label>รูปทรงท่อ</label>
						<select class="form-control" id="duct_shape">
							<option value="round">ท่อกลม (Round)</option>
							<option value="rect">ท่อเหลี่ยม (Rectangular)</option>
						</select>
					</div>
					<div class="col-sm-2 mb-3">
						<label>หน่วยขนาดท่อ</label>
						<select class="form-control" id="duct_unit">
							<option value="in">นิ้ว (in)</option>
							<option value="cm">เซนติเมตร (cm)</option>
						</select>
					</div>
					<div class="col-sm-3 mb-3 duct-round">
						<label>เส้นผ่านศูนย์กลาง Ø <span class="duct-unit-label">(in)</span></label>
						<input type="number" class="form-control" id="duct_dia" value="12" step="0.5" min="1">
					</div>
					<div class="col-sm-2 mb-3 duct-rect" style="display:none;">
						<label>กว้าง <span class="duct-unit-label">(in)</span></label>
						<input type="number" class="form-control" id="duct_w" value="12" step="0.5" min="1">
					</div>
					<div class="col-sm-2 mb-3 duct-rect" style="display:none;">
						<label>สูง <span class="duct-unit-label">(in)</span></label>
						<input type="number" class="form-control" id="duct_h" value="10" step="0.5" min="1">
					</div>
				</div>
				<div class="row">
					<div class="col-sm-3 mb-3">
						<label>ความยาวท่อรวม (m)</label>
						<input type="number" class="form-control" id="duct_length" value="10" min="0">
					</div>
					<div class="col-sm-3 mb-3">
						<label>จำนวนข้องอ 90°</label>
						<input type="number" class="form-control" id="duct_elbows" value="3" min="0">
					</div>
					<div class="col-sm-3 mb-3">
						<label>ความเร็วลมพัดลม (m/s)</label>
						<input type="number" class="form-control" id="fan_velocity" value="8" step="0.5" min="1">
						<small class="text-muted">ความเร็วลมที่จุดทำงานของพัดลม — ใช้คำนวณขนาดท่อแนะนำและรูเจาะฝาชี</small>
					</div>
				</div>
				<small class="text-muted">ความเร็วจริงและแรงเสียดทานคำนวณจากขนาดท่อที่ระบุ (สมการ ASHRAE Friction Chart, ท่อสังกะสี) — ท่อเหลี่ยมแปลงเป็น Equivalent Diameter ตามสูตร Huebscher</small>
			</div>

			<!-- อุปกรณ์เสริม -->
			<div class="frappe-card p-4 mb-4">
				<h5 class="mb-1">อุปกรณ์เสริม (Optional)</h5>
				<p class="text-muted small mb-3">เลือกฟิลเตอร์/อุปกรณ์ที่มีในระบบ ปรับค่าความดันตกได้ตามสเปคผู้ผลิต — แนะนำใช้ค่า "สกปรก/ก่อนเปลี่ยน" เพื่อเลือกพัดลมให้พอตลอดอายุฟิลเตอร์</p>
				<div class="row" id="filter_list"></div>
				<hr>
				<div class="row">
					<div class="col-sm-3 mb-2">
						<label>ESP เพิ่มเติม ทางเข้า (in.wg)</label>
						<input type="number" class="form-control" id="esp_inlet" value="0" step="0.05" min="0">
						<small class="text-muted">เช่น louver, damper, ท่อฝั่งดูดอื่นๆ</small>
					</div>
					<div class="col-sm-3 mb-2">
						<label>ESP เพิ่มเติม ทางออก (in.wg)</label>
						<input type="number" class="form-control" id="esp_outlet" value="0" step="0.05" min="0">
						<small class="text-muted">เช่น silencer, ท่อฝั่งจ่าย, coil</small>
					</div>
				</div>
				<small class="text-muted d-none" id="hood_filter_note">หมายเหตุ: โหมดฝาชีรวมค่า baffle filter ของฮู้ดไว้แล้ว — เลือกเพิ่มเฉพาะฟิลเตอร์ที่ติดตั้งเพิ่มในแนวท่อ</small>
			</div>

			<div class="text-center mb-4">
				<button class="btn btn-primary btn-lg px-5" id="btn_calc">คำนวณ</button>
			</div>

			<div id="hvac_result"></div>
		</div>`;
	}

	bind() {
		this.$body.on('click', '.hvac-mode', (e) => this.switch_mode($(e.currentTarget).data('mode')));
		this.$body.on('click', '#btn_calc', () => this.calculate());
		this.$body.on('change', '#room_type', () => this.update_room_hint());
		this.$body.on('change', '#hood_type', () => this.render_duty_options());
		this.$body.on('input', '#room_w, #room_l', () => this.update_area_hint());
		this.$body.on('change', '#dt_room_type', () => this.update_dt_hint());
		this.$body.on('input', '#dt_w, #dt_l', () => this.update_dt_area_hint());
		this.$body.on('click', '#btn_print', () => this.print_result());
		this.$body.on('click', '#btn_add_hole', () => this.add_custom_hole());
		this.$body.on('change', '#duct_shape', () => this.toggle_duct_shape());
		this.$body.on('change', '#duct_unit', () => this.update_duct_unit());
	}

	toggle_duct_shape() {
		const round = this.$body.find('#duct_shape').val() === 'round';
		this.$body.find('.duct-round').toggle(round);
		this.$body.find('.duct-rect').toggle(!round);
	}

	update_duct_unit() {
		const unit = this.$body.find('#duct_unit').val();
		this.$body.find('.duct-unit-label').text(`(${unit})`);
		// แปลงค่าที่กรอกไว้ให้อัตโนมัติ
		const f = unit === 'cm' ? 2.54 : 1 / 2.54;
		['duct_dia', 'duct_w', 'duct_h'].forEach(id => {
			const $el = this.$body.find('#' + id);
			const v = parseFloat($el.val());
			if (v) $el.val((v * f).toFixed(1));
		});
	}

	render_filter_options() {
		const $list = this.$body.find('#filter_list');
		FILTER_TYPES.forEach(f => {
			$list.append(`
			<div class="col-sm-4 mb-2">
				<div class="border rounded p-2">
					<div class="checkbox mb-1">
						<label class="mb-0">
							<input type="checkbox" class="filter-check" data-id="${f.id}"> <b>${f.th}</b>
						</label>
					</div>
					<div class="input-group input-group-sm">
						<input type="number" class="form-control filter-sp" id="filter_sp_${f.id}"
							value="${f.def}" step="0.05" min="0">
						<div class="input-group-append"><span class="input-group-text">in.wg</span></div>
					</div>
					<small class="text-muted">${f.hint}</small>
				</div>
			</div>`);
		});
	}

	switch_mode(mode) {
		this.mode = mode;
		this.$body.find('.hvac-mode').removeClass('btn-primary').addClass('btn-default');
		this.$body.find(`.hvac-mode[data-mode="${mode}"]`).removeClass('btn-default').addClass('btn-primary');
		this.$body.find('#panel-room').toggle(mode === 'room');
		this.$body.find('#panel-hood').toggle(mode === 'hood');
		this.$body.find('#panel-duct').toggle(mode === 'duct');
		this.$body.find('#hood_filter_note').toggleClass('d-none', mode !== 'hood');
		this.$body.find('#hvac_result').empty();
	}

	render_room_options() {
		const $sel = this.$body.find('#room_type');
		const $sel2 = this.$body.find('#dt_room_type');
		ROOM_TYPES.forEach(r => {
			$sel.append(`<option value="${r.id}">${r.th}</option>`);
			$sel2.append(`<option value="${r.id}">${r.th}</option>`);
		});
		this.update_room_hint();
		this.update_dt_hint();
	}

	update_room_hint() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#room_type').val());
		if (!r) return;
		this.$body.find('#room_ref').text(r.ref);
		this.$body.find('#ach_hint').text(`ช่วงแนะนำ ${r.ach[0]}–${r.ach[1]} ACH`);
		this.$body.find('#room_ach').val(((r.ach[0] + r.ach[1]) / 2).toFixed(1));
	}

	update_dt_hint() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#dt_room_type').val());
		if (!r) return;
		const cls = AIR_CLASS[r.id] || 1;
		this.$body.find('#dt_room_ref').text(`${r.ref} • Air Class ${cls}`);
		this.$body.find('#dt_ach_hint').text(`ช่วงแนะนำ ${r.ach[0]}–${r.ach[1]} ACH`);
		this.$body.find('#dt_ach').val(((r.ach[0] + r.ach[1]) / 2).toFixed(1));
	}

	update_dt_area_hint() {
		const a = this.num('dt_w') * this.num('dt_l');
		this.$body.find('#dt_area_hint').text(a > 0 ? `พื้นที่ = ${a.toFixed(1)} m²` : '');
	}

	render_hood_options() {
		const $sel = this.$body.find('#hood_type');
		Object.entries(HOOD_RATES).forEach(([k, v]) => $sel.append(`<option value="${k}">${v.th}</option>`));
		this.render_duty_options();
	}

	render_duty_options() {
		const hood = HOOD_RATES[this.$body.find('#hood_type').val()];
		const $sel = this.$body.find('#hood_duty').empty();
		Object.entries(DUTY_TH).forEach(([k, label]) => {
			if (hood[k] != null) $sel.append(`<option value="${k}">${label} — ${hood[k]} CFM/ft</option>`);
		});
	}

	num(id) { return parseFloat(this.$body.find('#' + id).val()) || 0; }

	/* ---------- คำนวณ ---------- */

	calculate() {
		const res = this.mode === 'room' ? this.calc_room()
			: this.mode === 'hood' ? this.calc_hood()
			: this.calc_duct();
		if (!res) return;
		const sp = this.calc_sp(res.design_cfm, res.duct_len_m, res.manifold);
		if (!sp) return;
		this.render_result(res, sp);
	}

	update_area_hint() {
		const a = this.num('room_w') * this.num('room_l');
		this.$body.find('#area_hint').text(a > 0 ? `พื้นที่ = ${a.toFixed(1)} m²` : '');
	}

	calc_room() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#room_type').val());
		const room_w = this.num('room_w');
		const room_l = this.num('room_l');
		const height_m = this.num('room_height');
		const ach = this.num('room_ach');
		if (room_w <= 0 || room_l <= 0) { frappe.msgprint(__('กรุณากรอกความกว้างและความยาวห้อง')); return null; }
		const area_m2 = room_w * room_l;

		const area_ft2 = area_m2 * CFM_PER_M2;
		const volume_ft3 = area_ft2 * height_m * M_TO_FT;

		// วิธี 1: ACH
		const cfm_ach = volume_ft3 * ach / 60;

		// วิธี 2: ASHRAE 62.1 Ventilation Rate Procedure
		let people = this.num('room_people');
		if (!people && r.density) people = Math.ceil(area_ft2 * r.density / 1000);
		const cfm_621 = people * r.rp + area_ft2 * r.ra;

		// วิธี 3: Exhaust rate (ถ้ามี)
		let cfm_exhaust = 0, exhaust_note = '';
		if (r.exhaust_ra) {
			cfm_exhaust = area_ft2 * r.exhaust_ra;
			exhaust_note = `${r.exhaust_ra} cfm/ft² × ${Math.round(area_ft2)} ft²`;
		}

		// วิธี 4: ระบายความร้อน Q = H/(ρ·Cp·ΔT) → CFM ≈ 1756 × kW ÷ ΔT(°C)
		const heat_kw = this.num('room_heat');
		const heat_dt = this.num('room_heat_dt') || 5;
		const cfm_heat = heat_kw > 0 ? 1756 * heat_kw / heat_dt : 0;

		const design_cfm = Math.max(cfm_ach, cfm_621, cfm_exhaust, cfm_heat);

		return {
			mode_th: 'จากพื้นที่ห้อง',
			room: r, room_w, room_l, area_m2, area_ft2, volume_ft3, ach, people,
			rows: [
				{ label: `วิธี ACH (${ach} ACH × ${Math.round(volume_ft3).toLocaleString()} ft³ ÷ 60)`, cfm: cfm_ach },
				{ label: `วิธี ASHRAE 62.1 (${people} คน × ${r.rp} + ${Math.round(area_ft2)} ft² × ${r.ra})`, cfm: cfm_621 },
				...(cfm_exhaust ? [{ label: `Exhaust ขั้นต่ำ ASHRAE 62.1 Table 6-2 (${exhaust_note})`, cfm: cfm_exhaust }] : []),
				...(cfm_heat ? [{ label: `วิธีระบายความร้อน (${heat_kw} kW ÷ ρ·Cp·ΔT ${heat_dt}°C — ASHRAE Fundamentals)`, cfm: cfm_heat }] : []),
			],
			design_cfm,
			design_note: 'ใช้ค่ามากที่สุดของทุกวิธีเป็นค่าออกแบบ',
		};
	}

	calc_hood() {
		const hood = HOOD_RATES[this.$body.find('#hood_type').val()];
		const duty = this.$body.find('#hood_duty').val();
		const L_m = this.num('hood_length');
		const W_m = this.num('hood_width');
		if (L_m <= 0 || W_m <= 0) { frappe.msgprint(__('กรุณากรอกขนาดฮู้ด')); return null; }

		const L_ft = L_m * M_TO_FT;
		const W_ft = W_m * M_TO_FT;
		const rate = hood[duty];

		// วิธี 1: CFM ต่อฟุตความยาว (IMC / ASHRAE 154)
		const cfm_linear = L_ft * rate;

		// วิธี 2: Face velocity 85 fpm บนพื้นที่หน้าฮู้ด (ตรวจสอบขั้นต่ำ)
		const face_v = 85;
		const cfm_face = L_ft * W_ft * face_v;

		const design_cfm = Math.max(cfm_linear, cfm_face);

		// Makeup air ~80% ของ exhaust
		const makeup_cfm = design_cfm * 0.8;

		// รูเจาะฝาชี (duct collar) — เปรียบเทียบทางเลือก
		const holes = this.calc_hood_holes(design_cfm, L_m, W_m);

		return {
			mode_th: 'จากขนาดฝาชี',
			hood_th: hood.th, duty_th: DUTY_TH[duty],
			L_m, W_m, L_ft, W_ft, rate,
			rows: [
				{ label: `วิธี Linear (${L_ft.toFixed(1)} ft × ${rate} CFM/ft) — IMC 507.13`, cfm: cfm_linear },
				{ label: `วิธี Face Velocity (${L_ft.toFixed(1)} × ${W_ft.toFixed(1)} ft × ${face_v} fpm)`, cfm: cfm_face },
			],
			design_cfm,
			makeup_cfm,
			holes,
			design_note: 'ใช้ค่ามากที่สุด + จัดลมชดเชย (Makeup Air) ~80% ของลมดูด',
		};
	}

	/* โหมดดูดอากาศผ่านท่อ — หัวดูดหลายจุดกระจายตามความยาวห้อง เครื่องดูดอยู่ห่างออกไป */
	calc_duct() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#dt_room_type').val());
		const room_w = this.num('dt_w');
		const room_l = this.num('dt_l');
		const height_m = this.num('dt_h');
		const ach = this.num('dt_ach');
		if (room_w <= 0 || room_l <= 0) { frappe.msgprint(__('กรุณากรอกความกว้างและความยาวห้อง')); return null; }
		const n = Math.max(1, parseInt(this.$body.find('#dt_n').val()) || 1);
		const face_ms = this.num('dt_face_v') || 2.5;
		const fan_dist = this.num('dt_fan_dist');

		const area_m2 = room_w * room_l;
		const area_ft2 = area_m2 * CFM_PER_M2;
		const volume_ft3 = area_ft2 * height_m * M_TO_FT;

		// ปริมาณลม 3 วิธี (เหมือนโหมดพื้นที่ห้อง)
		const cfm_ach = volume_ft3 * ach / 60;
		let people = this.num('dt_people');
		if (!people && r.density) people = Math.ceil(area_ft2 * r.density / 1000);
		const cfm_621 = people * r.rp + area_ft2 * r.ra;
		let cfm_exhaust = 0, exhaust_note = '';
		if (r.exhaust_ra) {
			cfm_exhaust = area_ft2 * r.exhaust_ra;
			exhaust_note = `${r.exhaust_ra} cfm/ft² × ${Math.round(area_ft2)} ft²`;
		}
		// วิธีระบายความร้อน Q = H/(ρ·Cp·ΔT) → CFM ≈ 1756 × kW ÷ ΔT(°C)
		const heat_kw = this.num('dt_heat');
		const heat_dt = this.num('dt_heat_dt') || 5;
		const cfm_heat = heat_kw > 0 ? 1756 * heat_kw / heat_dt : 0;
		const design_cfm = Math.max(cfm_ach, cfm_621, cfm_exhaust, cfm_heat);

		// ---- กระจายลมผ่านหัวดูด n จุด ----
		const q = design_cfm / n;
		const face_fpm = face_ms * 196.85;
		const a_req_ft2 = q / face_fpm;
		let side_in = Math.sqrt(a_req_ft2) * 12;
		side_in = Math.ceil(side_in / 2) * 2;              // ปัดขึ้นเป็นขนาดมาตรฐานทุก 2 นิ้ว
		const a_act_ft2 = Math.pow(side_in / 12, 2);
		const v_act_ms = (q / a_act_ft2) / 196.85;

		// ตำแหน่งหัวดูด: กระจายเท่ากันตามความยาวห้อง (แนวท่อเมน)
		const spacing = room_l / n;
		const positions = [];
		for (let i = 0; i < n; i++) positions.push((spacing / 2 + i * spacing).toFixed(2));

		// ความยาวท่อรวม = ท่อเมนในห้อง (ยาวห้อง) + ระยะถึงเครื่องดูด
		const duct_len_m = room_l + fan_dist;

		// ---- Critical Path: แรงดันท่อเมนสะสมลมจริงทีละช่วง + ขนาดหัวดูดรายจุด (self-balancing) ----
		const g = this.get_duct_geometry();
		if (!g) return null;
		const Cg = 2.5; // สัมประสิทธิ์ความดันตกหัวดูด (register + core, อิงความเร็วหน้าหัว)
		const VP_face = Math.pow(face_fpm / 4005, 2);
		const dPg_far = Cg * VP_face; // หัวไกลสุดกำหนดที่ความเร็วเป้าหมาย

		// หัวที่ 1 = ไกลพัดลมสุด → หัวที่ n = ใกล้สุด; ช่วงหลังหัวที่ k มีลมสะสม k×q
		const grilles = [];
		let cum_duct = 0; // แรงดันท่อสะสมจากหัวไกลสุดมาถึงจุดปัจจุบัน
		for (let k = 1; k <= n; k++) {
			const suction_k = dPg_far + cum_duct;        // แรงดูดที่ junction หัวที่ k
			const v_req_fpm = 4005 * Math.sqrt(suction_k / Cg); // ความเร็วหน้าหัวที่ทำให้ดูดได้ q พอดี
			const a_req = q / v_req_fpm;
			const side = Math.max(4, Math.round(Math.sqrt(a_req) * 12)); // ปัดเป็นนิ้ว
			const v_act = (q / Math.pow(side / 12, 2)) / 196.85;
			grilles.push({ i: k, pos: positions[k - 1], dp: suction_k, side, v_ms: v_act });
			// ช่วงท่อถัดไป: ระหว่างหัว (spacing) หรือช่วงสุดท้ายถึงพัดลม (spacing/2 + fan_dist)
			const Lk_m = (k < n) ? spacing : (spacing / 2 + fan_dist);
			const Qk = k * q;
			const f100 = 0.109136 * Math.pow(Qk, 1.9) / Math.pow(g.De_in, 5.02);
			cum_duct += f100 * (Lk_m * M_TO_FT / 100);
		}
		const manifold = {
			sp_main: cum_duct,        // ท่อเมนสะสมจริง (critical path หัวไกลสุด→พัดลม)
			dPg_far, Cg,
			uniformity: dPg_far / Math.max(0.0001, cum_duct), // อัตราส่วน ΔPหัว : ΔPท่อ
		};

		const air_class = AIR_CLASS[r.id] || 1;

		return {
			mode_th: 'ดูดอากาศผ่านท่อ (หลายจุด)',
			room: r, room_w, room_l, area_m2, ach, people,
			rows: [
				{ label: `วิธี ACH (${ach} ACH × ${Math.round(volume_ft3).toLocaleString()} ft³ ÷ 60)`, cfm: cfm_ach },
				{ label: `วิธี ASHRAE 62.1 (${people} คน × ${r.rp} + ${Math.round(area_ft2)} ft² × ${r.ra})`, cfm: cfm_621 },
				...(cfm_exhaust ? [{ label: `Exhaust ขั้นต่ำ ASHRAE 62.1 Table 6-2 (${exhaust_note})`, cfm: cfm_exhaust }] : []),
				...(cfm_heat ? [{ label: `วิธีระบายความร้อน (${heat_kw} kW ÷ ρ·Cp·ΔT ${heat_dt}°C — ASHRAE Fundamentals)`, cfm: cfm_heat }] : []),
			],
			design_cfm,
			design_note: 'ใช้ค่ามากที่สุดของทุกวิธีเป็นค่าออกแบบ',
			duct_len_m,
			manifold,
			dist: { n, q, side_in, face_ms, v_act_ms, spacing, positions, fan_dist, duct_len_m, air_class, grilles, manifold, room_w, room_l },
		};
	}

	render_duct_dist(d) {
		const sp_warn = d.spacing > 3
			? `<div class="alert alert-warning small py-2">⚠️ ระยะห่างหัวดูด ${d.spacing.toFixed(2)} m เกิน ~3 m — การดูดอาจไม่สม่ำเสมอ พิจารณาเพิ่มจำนวนหัวดูด</div>` : '';
		const v_warn = d.v_act_ms > 3
			? `<div class="alert alert-warning small py-2">⚠️ ความเร็วหน้าหัวดูด ${d.v_act_ms.toFixed(1)} m/s เกิน 3 m/s อาจมีเสียงดัง — เพิ่มขนาดหัวดูดหรือจำนวนจุด</div>` : '';
		return `
			<h6 class="mt-3">การกระจายหัวดูด (${d.n} จุด)</h6>
			<table class="table table-sm table-bordered">
				<tbody>
					<tr><td>ลมต่อหัวดูด</td><td class="text-right"><b>${Math.round(d.q).toLocaleString()} CFM</b> (≈ ${Math.round(d.q * 1.699).toLocaleString()} m³/h)</td></tr>
					<tr><td>ขนาดหัวดูดแนะนำ (คอ)</td><td class="text-right"><b>${d.side_in}" × ${d.side_in}"</b> (≈ ${(d.side_in * 2.54).toFixed(0)} × ${(d.side_in * 2.54).toFixed(0)} cm)</td></tr>
					<tr><td>ความเร็วหน้าหัวดูดจริง</td><td class="text-right">${d.v_act_ms.toFixed(1)} m/s (เป้าหมาย ${d.face_ms} m/s)</td></tr>
					<tr><td>ระยะห่างหัวดูด (ตามแนวยาวห้อง)</td><td class="text-right">${d.spacing.toFixed(2)} m — หัวแรก/สุดท้ายห่างขอบ ${(d.spacing / 2).toFixed(2)} m</td></tr>
					<tr><td>ตำแหน่งหัวดูดจากขอบห้อง (m)</td><td class="text-right">${d.positions.join(', ')}</td></tr>
					<tr><td>ความยาวท่อรวมถึงเครื่องดูด</td><td class="text-right">${d.duct_len_m.toFixed(1)} m (ในห้อง ${(d.duct_len_m - d.fan_dist).toFixed(1)} + ถึงพัดลม ${d.fan_dist.toFixed(1)})</td></tr>
				</tbody>
			</table>
			${v_warn}${sp_warn}
			${this.duct_layout_svg(d)}
			${this.render_grille_balance(d)}
			<div class="alert alert-secondary small">
				<b>ประเภทอากาศ (ASHRAE 62.1):</b> ${AIR_CLASS_TH[d.air_class]}<br>
				<b>ข้อแนะนำ:</b>
				ติด Volume Damper ทุก branch เพื่อปรับสมดุลลมแต่ละหัว •
				ท่อตรงก่อนเข้าพัดลมอย่างน้อย 2–3 เท่าของ Ø ท่อ ลด System Effect (AMCA 201) •
				ความเร็วหน้าหัวดูด ≤ 2.5–3 m/s และในท่อเมน 4–6 m/s เพื่อควบคุมเสียง •
				จุดทิ้งอากาศห่างจากช่องรับอากาศเข้า (OA intake) ตามระยะขั้นต่ำ ASHRAE 62.1 Table 5-1
			</div>`;
	}

	// ผังท่อคร่าวๆ (มุมมองด้านบน): ห้อง + ท่อเมน + หัวดูด n จุด + เครื่องดูด (วาดตามสัดส่วน)
	duct_layout_svg(d) {
		const W = 700, mg = 45;
		const fan_w_px = 46; // พื้นที่สัญลักษณ์พัดลม
		const innerW = W - 2 * mg - fan_w_px;
		const total_m = d.room_l + Math.max(0.5, d.fan_dist);
		const scale = innerW / total_m;
		const room_y = 40;
		const room_h = Math.max(50, d.room_w * scale);
		const cy = room_y + room_h / 2;
		const H = Math.ceil(room_y + room_h + 66);
		const x0 = mg;
		const room_x1 = x0 + d.room_l * scale;
		const fan_x = room_x1 + Math.max(0.5, d.fan_dist) * scale;
		const duct_h = 12;

		// หัวดูด: ตำแหน่งวัดจากฝั่งไกลพัดลม (ซ้าย)
		let grille_svg = '', pos_labels = '';
		d.positions.forEach((p, i) => {
			const cx = x0 + parseFloat(p) * scale;
			grille_svg += `<rect x="${(cx - 8).toFixed(1)}" y="${(cy - 8).toFixed(1)}" width="16" height="16"
				fill="#fff" stroke="#0a6" stroke-width="1.5"/>
				<line x1="${(cx - 5).toFixed(1)}" y1="${cy}" x2="${(cx + 5).toFixed(1)}" y2="${cy}" stroke="#0a6" stroke-width="1"/>
				<line x1="${cx.toFixed(1)}" y1="${(cy - 5).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(cy + 5).toFixed(1)}" stroke="#0a6" stroke-width="1"/>`;
			pos_labels += `<line x1="${cx.toFixed(1)}" y1="${(room_y + room_h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(room_y + room_h + 12).toFixed(1)}"
				stroke="#888" stroke-width="0.8" stroke-dasharray="3,2"/>
				<text x="${cx.toFixed(1)}" y="${(room_y + room_h + 24).toFixed(1)}" text-anchor="middle" font-size="10">${p}</text>`;
		});

		const first_x = x0 + parseFloat(d.positions[0]) * scale;

		return `
		<h6 class="mt-3">ผังท่อคร่าวๆ — มุมมองด้านบน (มาตราส่วนตามจริง)</h6>
		<div style="margin-bottom:12px; page-break-inside:avoid;">
			<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
				style="border:1px solid #ddd; background:#fff; max-width:100%;">
				<!-- ห้อง -->
				<rect x="${x0}" y="${room_y}" width="${(room_x1 - x0).toFixed(1)}" height="${room_h.toFixed(1)}"
					fill="#f8f8f8" stroke="#333" stroke-width="1.5"/>
				<text x="${x0 + 5}" y="${room_y - 6}" font-size="11" fill="#666">ห้อง ${d.room_w} × ${d.room_l} m (ฝั่งซ้าย = ไกลพัดลม)</text>
				<!-- ท่อเมน: หัวไกลสุด → พัดลม -->
				<rect x="${first_x.toFixed(1)}" y="${(cy - duct_h / 2).toFixed(1)}" width="${(fan_x - first_x).toFixed(1)}" height="${duct_h}"
					fill="#e8f0fe" stroke="#36c" stroke-width="1.2"/>
				<text x="${((first_x + room_x1) / 2).toFixed(1)}" y="${(cy - duct_h / 2 - 5).toFixed(1)}" text-anchor="middle" font-size="10" fill="#36c">ท่อเมน</text>
				<!-- หัวดูด -->
				${grille_svg}
				${pos_labels}
				<!-- เครื่องดูด -->
				<rect x="${fan_x.toFixed(1)}" y="${(cy - 20).toFixed(1)}" width="40" height="40" fill="#fff" stroke="#c33" stroke-width="1.5"/>
				<circle cx="${(fan_x + 20).toFixed(1)}" cy="${cy.toFixed(1)}" r="12" fill="none" stroke="#c33" stroke-width="1.2"/>
				<path d="M ${(fan_x + 20).toFixed(1)} ${(cy - 12).toFixed(1)} A 12 12 0 0 1 ${(fan_x + 32).toFixed(1)} ${cy.toFixed(1)}" fill="none" stroke="#c33" stroke-width="1.2"/>
				<text x="${(fan_x + 20).toFixed(1)}" y="${(cy + 34).toFixed(1)}" text-anchor="middle" font-size="10" fill="#c33">เครื่องดูด</text>
				<!-- เส้นบอกระยะถึงพัดลม -->
				<line x1="${room_x1.toFixed(1)}" y1="${(cy + duct_h / 2 + 8).toFixed(1)}" x2="${fan_x.toFixed(1)}" y2="${(cy + duct_h / 2 + 8).toFixed(1)}" stroke="#c33" stroke-width="0.8"/>
				<text x="${((room_x1 + fan_x) / 2).toFixed(1)}" y="${(cy + duct_h / 2 + 20).toFixed(1)}" text-anchor="middle" font-size="10" fill="#c33">${d.fan_dist} m</text>
				<!-- เส้นบอกความยาวห้อง -->
				<line x1="${x0}" y1="${(H - 18).toFixed(1)}" x2="${room_x1.toFixed(1)}" y2="${(H - 18).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<line x1="${x0}" y1="${(H - 23).toFixed(1)}" x2="${x0}" y2="${(H - 13).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<line x1="${room_x1.toFixed(1)}" y1="${(H - 23).toFixed(1)}" x2="${room_x1.toFixed(1)}" y2="${(H - 13).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<text x="${((x0 + room_x1) / 2).toFixed(1)}" y="${(H - 5).toFixed(1)}" text-anchor="middle" font-size="10">ยาวห้อง ${d.room_l} m — ตัวเลขใต้หัวดูด = ตำแหน่งจากฝั่งไกล (m)</text>
			</svg>
		</div>`;
	}

	// ตารางขนาดหัวดูดรายจุดแบบ self-balancing: ทุกหัวได้ลม q เท่ากันโดยไม่พึ่ง damper
	render_grille_balance(d) {
		if (!d.grilles || !d.grilles.length) return '';
		const m = d.manifold;
		const ratio = m.uniformity;
		const ratio_note = ratio >= 10
			? `✅ ΔP หัวดูด : ΔP ท่อเมน = ${ratio.toFixed(1)} : 1 (≥10:1) — ใช้ขนาดเท่ากันทุกหัวได้ ลมเพี้ยนน้อย แค่มี damper ปรับละเอียด`
			: `⚠️ ΔP หัวดูด : ΔP ท่อเมน = ${ratio.toFixed(1)} : 1 (<10:1) — ขนาดเท่ากันทุกหัวจะทำให้หัวใกล้พัดลมดูดแรงเกิน แนะนำใช้ขนาดรายจุดตามตารางนี้ หรือพึ่ง damper มากขึ้น`;

		const rows = d.grilles.map(o => `<tr>
			<td>หัวที่ ${o.i}${o.i === 1 ? ' (ไกลพัดลมสุด)' : (o.i === d.grilles.length ? ' (ใกล้พัดลมสุด)' : '')}</td>
			<td class="text-right">${o.pos}</td>
			<td class="text-right">${o.dp.toFixed(3)}</td>
			<td class="text-right"><b>${o.side}" × ${o.side}"</b> (${(o.side * 2.54).toFixed(0)} cm)</td>
			<td class="text-right">${o.v_ms.toFixed(1)}</td>
		</tr>`).join('');

		return `
			<h6 class="mt-3">ขนาดหัวดูดรายจุด — Self-balancing เพื่อลมสม่ำเสมอ</h6>
			<table class="table table-sm table-bordered">
				<thead><tr>
					<th>หัวดูด</th><th class="text-right">ตำแหน่งจากฝั่งไกลพัดลม (m)</th>
					<th class="text-right">แรงดูดที่จุด (in.wg)</th>
					<th class="text-right">ขนาดคอแนะนำ</th><th class="text-right">ความเร็วหน้าหัว (m/s)</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			<p class="small text-muted mb-1">
				หลักการ: หัวใกล้พัดลมเจอแรงดูดสูงกว่า จึงลดขนาดหัวให้ความต้านทานชดเชยพอดี →
				ทุกหัวดูดได้ ${Math.round(d.q).toLocaleString()} CFM เท่ากันโดยไม่ต้องหรี่ damper มาก
				(ΔP หัวดูดคิดจาก C=${m.Cg} × VP หน้าหัว, ท่อเมนคิดแบบ Critical Path สะสมลมทีละช่วง)
			</p>
			<p class="small mb-2">${ratio_note}</p>`;
	}

	/* รูเจาะฝาชี (จุดต่อท่อดูด/Duct Collar) — เปรียบเทียบทางเลือก
	 * - ขนาดรูเลือกให้ความเร็วผ่านรูใกล้ความเร็วลมพัดลมที่กำหนดมากที่สุด
	 * - เพดานความเร็วผ่านรูไม่เกิน 10 m/s เพื่อไม่ให้เกิดเสียงดัง
	 * - ระยะห่างรูไม่เกิน ~2 m ต่อรู → ดูดสม่ำเสมอตลอดความยาวฮู้ด
	 * - รูต้องไม่ใหญ่กว่าขนาดท่อลมที่กำหนด
	 */
	calc_hood_holes(cfm, L_m, W_m) {
		const STD_IN = [4, 5, 6, 8, 10, 12, 14, 16, 18, 20];
		const fan_ms = this.num('fan_velocity') || 8;
		const V_NOISE = 10;                              // เพดานเสียงดัง (m/s)
		const V_MAX = Math.min(fan_ms * 1.2, V_NOISE);   // เพดานความเร็วผ่านรู
		const V_LO = fan_ms * 0.875;
		const V_HI = Math.min(fan_ms * 1.125, V_NOISE);  // แถบ ±12.5% รอบความเร็วพัดลม แต่ไม่เกิน 10 m/s
		const SPACING_MAX = 2.0; // m
		const n_max = Math.min(8, Math.max(4, Math.ceil(L_m / 1.0)));

		// ข้อจำกัด: รูเจาะต้องไม่ใหญ่กว่าขนาดท่อลมที่กำหนด
		const duct_limit_in = this.get_duct_limit_in();
		const usable_std = duct_limit_in > 0 ? STD_IN.filter(d => d <= duct_limit_in) : STD_IN;

		const v_of = (q_cfm, d_in) => {
			const a = Math.PI / 4 * Math.pow(d_in / 12, 2); // ft²
			return (q_cfm / a) / 196.85; // m/s
		};

		const options = [];
		for (let n = 1; n <= n_max; n++) {
			const q = cfm / n;
			// เลือกขนาดมาตรฐาน (≤ ขนาดท่อ) ที่ให้ความเร็วใกล้ความเร็วลมพัดลมที่สุด โดยไม่เกิน V_MAX
			let best_d = null, best_v = null;
			usable_std.forEach(d => {
				const v = v_of(q, d);
				if (v > V_MAX) return;
				if (best_v === null || Math.abs(v - fan_ms) < Math.abs(best_v - fan_ms)) { best_d = d; best_v = v; }
			});
			if (best_d === null) continue; // ลมต่อรูแรงเกินทุกขนาดที่ท่อรองรับ
			const spacing = L_m / n;
			const VP = Math.pow(best_v * 196.85 / 4005, 2);
			const collar_loss = 0.5 * VP; // C≈0.5 ต่อรู (plain collar entry)
			const pass_v = best_v >= V_LO && best_v <= V_HI;
			const pass_sp = spacing <= SPACING_MAX;
			options.push({ n, d_in: best_d, q, v: best_v, spacing, collar_loss, pass_v, pass_sp });
		}

		return { options, duct_limit_in, fan_ms, V_LO, V_HI, V_MAX, cfm, L_m, W_m };
	}

	// วาดผังตำแหน่งรูเจาะ: สี่เหลี่ยม = ฝาชีมองจากด้านบน (วาดตามสัดส่วนจริง)
	// รูปทรงรูตามท่อลม: ท่อกลม → รูกลม, ท่อเหลี่ยม → รูเหลี่ยมพื้นที่เท่ากัน
	hole_position_svg(cfg, ctx, duct_shape) {
		const W = 700, mg = 45;
		const innerW = W - 2 * mg;
		const scale = innerW / ctx.L_m;          // px ต่อเมตร — ใช้สเกลเดียวทั้งภาพ
		const hood_y = 42;
		const hood_h = ctx.W_m * scale;          // ความกว้างฝาชีตามสัดส่วนจริง
		const cy = hood_y + hood_h / 2;
		const label_y = hood_y + hood_h;         // จุดเริ่มเส้นบอกระยะใต้ฝาชี
		const H = Math.ceil(label_y + 62);       // ความสูง SVG ปรับตามขนาดฝาชี
		const is_rect = duct_shape === 'rect';

		// รูเหลี่ยม: ด้านจัตุรัสที่พื้นที่เท่ารูกลม Ø d → s = d × √(π)/2
		const s_in = cfg.d_in * Math.sqrt(Math.PI) / 2;
		const d_m = cfg.d_in * 0.0254;
		const s_m = s_in * 0.0254;
		const r = Math.max(2, (d_m / 2) * scale);   // รัศมีรูกลมตามสเกลจริง (px)
		const hs = Math.max(2, (s_m / 2) * scale);  // ครึ่งด้านรูเหลี่ยมตามสเกลจริง (px)
		const cross = Math.min(4, r * 0.5);         // ขนาดกากบาทกึ่งกลาง

		let shapes = '', labels = '';
		const positions = [];
		for (let i = 0; i < cfg.n; i++) {
			const pos_m = cfg.spacing / 2 + i * cfg.spacing;
			positions.push(pos_m.toFixed(2));
			const cx = mg + pos_m * scale;
			if (is_rect) {
				shapes += `<rect x="${(cx - hs).toFixed(1)}" y="${(cy - hs).toFixed(1)}"
					width="${(hs * 2).toFixed(1)}" height="${(hs * 2).toFixed(1)}"
					fill="none" stroke="#333" stroke-width="1.5"/>`;
			} else {
				shapes += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${r.toFixed(1)}"
					fill="none" stroke="#333" stroke-width="1.5"/>`;
			}
			shapes += `<line x1="${cx.toFixed(1)}" y1="${(cy - cross).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(cy + cross).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<line x1="${(cx - cross).toFixed(1)}" y1="${cy.toFixed(1)}" x2="${(cx + cross).toFixed(1)}" y2="${cy.toFixed(1)}" stroke="#333" stroke-width="0.8"/>`;
			labels += `<line x1="${cx.toFixed(1)}" y1="${label_y.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(label_y + 14).toFixed(1)}"
				stroke="#888" stroke-width="0.8" stroke-dasharray="3,2"/>
				<text x="${cx.toFixed(1)}" y="${(label_y + 26).toFixed(1)}" text-anchor="middle" font-size="11">${pos_m.toFixed(2)}</text>`;
		}

		const size_desc = is_rect
			? `รูเหลี่ยม ${s_in.toFixed(1)}" × ${s_in.toFixed(1)}" (≈ ${(s_in * 2.54).toFixed(0)} × ${(s_in * 2.54).toFixed(0)} cm)
				— พื้นที่เทียบเท่ารูกลม Ø ${cfg.d_in % 1 ? cfg.d_in.toFixed(1) : cfg.d_in}"`
			: `รูกลม Ø ${cfg.d_in % 1 ? cfg.d_in.toFixed(1) : cfg.d_in}" (≈ ${(cfg.d_in * 2.54).toFixed(0)} cm)`;

		return `
		<div style="margin-bottom:14px; page-break-inside:avoid;">
			<div style="font-size:12px; margin-bottom:2px;">
				<b>${cfg.n} รู × ${size_desc}</b>
				— ระยะห่างรู ${cfg.spacing.toFixed(2)} m, รูแรก/สุดท้ายห่างขอบ ${(cfg.spacing / 2).toFixed(2)} m
				• ตำแหน่ง (m): ${positions.join(', ')}
			</div>
			<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
				style="border:1px solid #ddd; background:#fff;">
				<rect x="${mg}" y="${hood_y}" width="${innerW}" height="${hood_h.toFixed(1)}"
					fill="#f8f8f8" stroke="#333" stroke-width="1.5"/>
				${shapes}
				${labels}
				<line x1="${mg}" y1="${(H - 22).toFixed(1)}" x2="${W - mg}" y2="${(H - 22).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<line x1="${mg}" y1="${(H - 27).toFixed(1)}" x2="${mg}" y2="${(H - 17).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<line x1="${W - mg}" y1="${(H - 27).toFixed(1)}" x2="${W - mg}" y2="${(H - 17).toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<text x="${W / 2}" y="${(H - 8).toFixed(1)}" text-anchor="middle" font-size="11">ความยาวฮู้ด ${ctx.L_m} m</text>
				<text x="${mg - 8}" y="${cy.toFixed(1)}" text-anchor="end" font-size="11">กว้าง ${ctx.W_m} m</text>
				<text x="${mg}" y="${hood_y - 8}" font-size="11" fill="#666">ขอบซ้าย (จุดอ้างอิง 0.00) • รูปทรงรูตามท่อ${is_rect ? 'เหลี่ยม' : 'กลม'} • มาตราส่วนตามจริง</text>
			</svg>
		</div>`;
	}

	// อ่านขนาดท่อจากการ์ดท่อลม: คืน Equivalent Diameter, พื้นที่หน้าตัด, ข้อความ
	get_duct_geometry() {
		const shape = this.$body.find('#duct_shape').val();
		const unit = this.$body.find('#duct_unit').val();
		const to_in = unit === 'cm' ? 1 / 2.54 : 1;
		if (shape === 'round') {
			const D = this.num('duct_dia') * to_in;
			if (D <= 0) { frappe.msgprint(__('กรุณากรอกขนาดท่อ')); return null; }
			return { De_in: D, area_ft2: Math.PI / 4 * Math.pow(D / 12, 2), size_txt: `ท่อกลม Ø ${this.fmt_size(D)}` };
		}
		const w = this.num('duct_w') * to_in;
		const h = this.num('duct_h') * to_in;
		if (w <= 0 || h <= 0) { frappe.msgprint(__('กรุณากรอกขนาดท่อ')); return null; }
		// Huebscher equivalent diameter (ASHRAE Fundamentals)
		const De = 1.30 * Math.pow(w * h, 0.625) / Math.pow(w + h, 0.25);
		return { De_in: De, area_ft2: (w / 12) * (h / 12), size_txt: `ท่อเหลี่ยม ${this.fmt_size(w)} × ${this.fmt_size(h)} (De ≈ ${De.toFixed(1)}")` };
	}

	// ขนาดรูสูงสุดที่เจาะได้ตามท่อที่กำหนด: ท่อกลม = Ø ท่อ, ท่อเหลี่ยม = ด้านที่แคบกว่า
	get_duct_limit_in() {
		const unit = this.$body.find('#duct_unit').val();
		const to_in = unit === 'cm' ? 1 / 2.54 : 1;
		if (this.$body.find('#duct_shape').val() === 'round') {
			return (parseFloat(this.$body.find('#duct_dia').val()) || 0) * to_in;
		}
		const w = (parseFloat(this.$body.find('#duct_w').val()) || 0) * to_in;
		const h = (parseFloat(this.$body.find('#duct_h').val()) || 0) * to_in;
		return Math.min(w, h);
	}

	calc_sp(cfm, len_m_override, manifold) {
		const len_m = (len_m_override != null) ? len_m_override : this.num('duct_length');
		const len_ft = len_m * M_TO_FT;
		const elbows = this.num('duct_elbows');
		const fan_ms = this.num('fan_velocity') || 8;
		const is_hood = this.mode === 'hood';

		// ---- ขนาดท่อจริง ----
		const g = this.get_duct_geometry();
		if (!g) return null;
		const { De_in, area_ft2, size_txt } = g;

		// ---- ความเร็วจริงในท่อ ----
		const v_fpm = cfm / area_ft2;
		const v_ms = v_fpm / 196.85;
		const VP = Math.pow(v_fpm / 4005, 2); // Velocity Pressure (in.wg)

		// ---- แรงเสียดทานท่อ: สมการ ASHRAE Friction Chart (ท่อสังกะสี) ----
		// ΔP = 0.109136 × Q^1.9 / De^5.02 (in.wg ต่อ 100 ft)
		const friction_per100 = 0.109136 * Math.pow(cfm, 1.9) / Math.pow(De_in, 5.02);
		const sp_duct = manifold ? manifold.sp_main : (len_ft / 100) * friction_per100;
		const duct_label = manifold
			? `ท่อเมน Critical Path ${size_txt} — สะสมลมจริงทีละช่วง (หัวไกลสุด→พัดลม ${len_m.toFixed(1)} m)`
			: `แรงเสียดทานท่อ ${size_txt} — ${friction_per100.toFixed(2)} in.wg/100ft × ${len_ft.toFixed(0)} ft`;

		// ---- Fitting: ข้องอ 90° C ≈ 0.3 × VP ต่อจุด ----
		const sp_fittings = elbows * 0.3 * VP;

		const has_baffle = is_hood && this.$body.find('#hood_baffle_check').is(':checked');
		const baffle_sp = has_baffle ? (parseFloat(this.$body.find('#hood_baffle_sp').val()) || 0) : 0;
		// แรงดันทางเข้าฮู้ด = C × VP โดยใช้ความเร็วที่สูงกว่าระหว่างในท่อกับผ่านรูเจาะ (จุดคอขวดจริง)
		const entry_c = parseFloat(this.$body.find('#hood_entry_c').val()) || 0.5;
		const fan_ms_entry = this.num('fan_velocity') || 8;
		const v_entry_fpm = Math.max(v_fpm, fan_ms_entry * 196.85);
		const VP_entry = Math.pow(v_entry_fpm / 4005, 2);
		const hood_entry = entry_c * VP_entry;
		const entry_governs = v_entry_fpm > v_fpm + 1 ? 'ความเร็วผ่านรู' : 'ความเร็วในท่อ';
		const sp_entry = is_hood ? hood_entry + baffle_sp
			: manifold ? manifold.dPg_far
			: SP_COMPONENTS.grille;

		// โหมดฝาชี: ความดันตกผ่านรูเจาะ (collar) — รูถูกกำหนดขนาดให้ความเร็วใกล้ความเร็วลมพัดลม
		const VP_hole = Math.pow((fan_ms * 196.85) / 4005, 2);
		const sp_collar = is_hood ? 0.5 * VP_hole : 0;
		const entry_label = is_hood
			? `ทางเข้าฮู้ด C=${entry_c} × VP ${VP_entry.toFixed(3)} (${entry_governs}) = ${hood_entry.toFixed(2)}`
				+ (has_baffle ? ` + Baffle filter ${baffle_sp.toFixed(2)}` : ' (ไม่มี baffle filter)')
			: manifold ? `หัวดูดไกลสุด C=${manifold.Cg} × VP หน้าหัว (ตัวกำหนดระบบ)`
			: 'หน้ากากดูด/จ่าย';
		const sp_cap = SP_COMPONENTS.exhaust_cap;

		// ---- อุปกรณ์เสริม: ฟิลเตอร์ที่เลือก + ESP เพิ่มเติมทางเข้า/ออก ----
		const extra_rows = [];
		let sp_extra = 0;
		this.$body.find('.filter-check:checked').each((_, el) => {
			const id = $(el).data('id');
			const f = FILTER_TYPES.find(x => x.id === id);
			const v = parseFloat(this.$body.find('#filter_sp_' + id).val()) || 0;
			if (v > 0) { extra_rows.push({ label: `ฟิลเตอร์: ${f.th}`, sp: v }); sp_extra += v; }
		});
		const esp_in = this.num('esp_inlet');
		const esp_out = this.num('esp_outlet');
		if (esp_in > 0) { extra_rows.push({ label: 'ESP เพิ่มเติม ทางเข้า (louver/damper/อื่นๆ)', sp: esp_in }); sp_extra += esp_in; }
		if (esp_out > 0) { extra_rows.push({ label: 'ESP เพิ่มเติม ทางออก (silencer/coil/อื่นๆ)', sp: esp_out }); sp_extra += esp_out; }

		const subtotal = sp_duct + sp_fittings + sp_entry + sp_collar + sp_cap + sp_extra;
		const safety = subtotal * 0.15; // เผื่อ System Effect ตาม AMCA 201
		const total = subtotal + safety;

		// ---- ขนาดท่อแนะนำ ที่ความเร็วลมพัดลม ----
		const fan_fpm = fan_ms * 196.85;
		const rec_area = cfm / fan_fpm;
		const rec_dia_in = Math.sqrt(4 * rec_area / Math.PI) * 12;

		// ---- คำเตือนความเร็ว ----
		const warnings = [];
		if (is_hood && v_ms < 2.54)
			warnings.push(`ความเร็วในท่อ ${v_ms.toFixed(1)} m/s ต่ำกว่าขั้นต่ำของท่อดูดควันครัว 2.54 m/s (500 fpm, IMC 506.3.4) — ควรลดขนาดท่อ`);
		if (is_hood && v_ms >= 2.54 && v_ms < 7.6)
			warnings.push(`ความเร็ว ${v_ms.toFixed(1)} m/s ผ่านขั้นต่ำ IMC แต่ต่ำกว่าช่วงแนะนำ 7.6–9 m/s สำหรับพาไขมัน — พิจารณาลดขนาดท่อ`);
		if (!is_hood && v_ms > 10)
			warnings.push(`ความเร็ว ${v_ms.toFixed(1)} m/s สูง อาจมีเสียงดัง — แนะนำ 4–6 m/s สำหรับท่อทั่วไป`);
		if (v_ms > 15)
			warnings.push(`ความเร็วสูงมาก แรงเสียดทานเพิ่มเป็นกำลังสอง — ควรเพิ่มขนาดท่อ`);

		return {
			rows: [
				{ label: entry_label, sp: sp_entry },
				{ label: duct_label, sp: sp_duct },
				{ label: `ข้องอ 90° × ${elbows} จุด (C=0.3 × VP ${VP.toFixed(3)})`, sp: sp_fittings },
				{ label: 'หัวปล่อยทิ้ง/Exhaust cap', sp: sp_cap },
				...extra_rows,
				{ label: 'เผื่อ System Effect 15% (AMCA 201)', sp: safety },
			],
			total, v_ms, VP, size_txt, De_in, friction_per100,
			rec_dia_in, fan_ms, warnings,
		};
	}

	render_holes(holes) {
		this.last_holes_ctx = holes; // เก็บบริบทไว้คำนวณแถวกำหนดเอง
		const limit_txt = holes.duct_limit_in > 0
			? `รูเจาะจำกัดไม่เกินขนาดท่อที่กำหนด: Ø ≤ ${holes.duct_limit_in.toFixed(1)}" (≈ ${(holes.duct_limit_in * 2.54).toFixed(0)} cm)`
			: '';
		const rows = holes.options.map(o => this.hole_row_html(o, false)).join('');

		return `
			<h6 class="mt-3">รูเจาะฝาชี (จุดต่อท่อดูด) — เปรียบเทียบทางเลือก</h6>
			${!holes.options.length ? `<div class="alert alert-warning small">
				⚠️ ไม่มีขนาดรูมาตรฐานที่เจาะได้ภายใต้ข้อจำกัดขนาดท่อ (${limit_txt}) —
				ลมต่อรูแรงเกินไป กรุณาเพิ่มขนาดท่อลม แยกเป็นหลายท่อ หรือเพิ่มแถวกำหนดเองเพื่อเปรียบเทียบ
			</div>` : ''}
			<table class="table table-sm table-bordered" id="holes_table">
				<thead><tr>
					<th class="hole-print-col text-center">พิมพ์</th>
					<th>จำนวนรู</th><th class="text-right">ขนาดรูกลม</th>
					<th class="text-right">CFM/รู</th><th class="text-right">ความเร็ว (m/s)</th>
					<th class="text-right">ระยะห่าง (m)</th><th class="text-right">ΔP/รู (in.wg)</th><th>สถานะ</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			<div class="form-inline mb-2 hole-custom-form">
				<label class="mr-2">กำหนดเอง:</label>
				<input type="number" class="form-control form-control-sm mr-1" id="custom_hole_n" value="2" min="1" max="20" style="width:70px" title="จำนวนรู"> รู ×
				<input type="number" class="form-control form-control-sm mx-1" id="custom_hole_d" value="10" step="0.5" min="1" style="width:80px" title="ขนาดรู">
				<select class="form-control form-control-sm mr-2" id="custom_hole_unit" style="width:70px">
					<option value="in">in</option><option value="cm">cm</option>
				</select>
				<button class="btn btn-default btn-sm" id="btn_add_hole">➕ เพิ่มเปรียบเทียบ</button>
				<label class="ml-3 mb-0 small">
					<input type="checkbox" id="show_hole_positions" checked> แสดงตำแหน่งรูเจาะเมื่อพิมพ์
				</label>
			</div>
			<p class="small text-muted mb-2">
				ขนาดรูเลือกให้ความเร็วผ่านรูใกล้ความเร็วลมพัดลม ${holes.fan_ms} m/s ที่สุด
				โดยไม่เกิน 10 m/s เพื่อป้องกันเสียงดัง
				(✅ = อยู่ในช่วง ${holes.V_LO.toFixed(1)}–${holes.V_HI.toFixed(1)} m/s และระยะห่างรู ≤ 2 m)
				• ΔP ต่อรูคิดจาก C=0.5 × VP (plain collar)
				${limit_txt ? '• ' + limit_txt : ''}
				• ติ๊กช่อง "พิมพ์" เฉพาะแถวที่ต้องการให้แสดงในรายงาน
			</p>`;
	}

	hole_row_html(o, is_custom) {
		const ctx = this.last_holes_ctx;
		let status;
		if (ctx.duct_limit_in > 0 && o.d_in > ctx.duct_limit_in + 0.01) {
			status = '⚠️ รูใหญ่กว่าท่อ';
		} else if (o.v > 10) {
			status = '🔊 เกิน 10 m/s เสียงดัง';
		} else if (o.v > ctx.V_MAX) {
			status = '⚠️ ความเร็วสูงเกิน';
		} else {
			status = (o.pass_v && o.pass_sp) ? '✅'
				: (!o.pass_sp ? '⚠️ รูห่างเกิน 2 m'
					: (o.v < ctx.V_LO ? '⚠️ ความเร็วต่ำกว่าพัดลม' : '⚠️ ความเร็วสูงกว่าพัดลม'));
		}
		return `<tr data-n="${o.n}" data-d="${o.d_in}" data-spacing="${o.spacing}">
			<td class="hole-print-col text-center"><input type="checkbox" class="hole-print" checked></td>
			<td>${o.n} รู${is_custom ? ' (กำหนดเอง)' : ''}</td>
			<td class="text-right">Ø ${o.d_in % 1 ? o.d_in.toFixed(1) : o.d_in}" (${(o.d_in * 2.54).toFixed(0)} cm)</td>
			<td class="text-right">${Math.round(o.q).toLocaleString()}</td>
			<td class="text-right">${o.v.toFixed(1)}</td>
			<td class="text-right">${o.spacing.toFixed(2)}</td>
			<td class="text-right">${o.collar_loss.toFixed(2)}</td>
			<td>${status}</td>
		</tr>`;
	}

	add_custom_hole() {
		const ctx = this.last_holes_ctx;
		if (!ctx) return;
		const n = parseInt(this.$body.find('#custom_hole_n').val()) || 0;
		let d_in = parseFloat(this.$body.find('#custom_hole_d').val()) || 0;
		if (this.$body.find('#custom_hole_unit').val() === 'cm') d_in = d_in / 2.54;
		if (n <= 0 || d_in <= 0) { frappe.msgprint(__('กรุณากรอกจำนวนและขนาดรู')); return; }

		const q = ctx.cfm / n;
		const a = Math.PI / 4 * Math.pow(d_in / 12, 2);
		const v = (q / a) / 196.85;
		const spacing = ctx.L_m / n;
		const VP = Math.pow(v * 196.85 / 4005, 2);
		const collar_loss = 0.5 * VP;
		const o = {
			n, d_in, q, v, spacing, collar_loss,
			pass_v: v >= ctx.V_LO && v <= ctx.V_HI,
			pass_sp: spacing <= 2.0,
		};
		this.$body.find('#holes_table tbody').append(this.hole_row_html(o, true));
	}

	fmt_size(inches) {
		const unit = this.$body.find('#duct_unit').val();
		return unit === 'cm' ? `${(inches * 2.54).toFixed(0)} cm` : `${inches.toFixed(1)}"`;
	}

	print_result() {
		// sync สถานะ checkbox ปัจจุบันลง attribute ก่อน clone
		this.$body.find('.hole-print').each(function () {
			this.checked ? $(this).attr('checked', 'checked') : $(this).removeAttr('checked');
		});
		const $result = this.$body.find('#hvac_result .frappe-card').clone();
		$result.find('#btn_print').remove();
		// เอาเฉพาะแถวรูเจาะที่ติ๊ก "พิมพ์" + ตัดคอลัมน์ checkbox และฟอร์มกำหนดเองออก
		$result.find('.hole-print:not([checked])').closest('tr').remove();
		$result.find('.hole-print-col').remove();
		$result.find('.hole-custom-form').remove();

		// แผนผังตำแหน่งรูเจาะ (เฉพาะแถวที่ติ๊กพิมพ์ และเปิดตัวเลือกไว้)
		let positions_html = '';
		if (this.mode === 'hood' && this.last_holes_ctx
			&& this.$body.find('#show_hole_positions').is(':checked')) {
			const ctx = this.last_holes_ctx;
			const configs = [];
			this.$body.find('#holes_table tbody tr').each(function () {
				if ($(this).find('.hole-print').is(':checked')) {
					configs.push({
						n: parseInt($(this).data('n')),
						d_in: parseFloat($(this).data('d')),
						spacing: parseFloat($(this).data('spacing')),
					});
				}
			});
			if (configs.length) {
				const duct_shape = this.$body.find('#duct_shape').val();
				positions_html = `<h6 style="margin-top:16px;">ตำแหน่งรูเจาะฝาชี — มุมมองด้านบน (วัดถึงกึ่งกลางรู จากขอบซ้าย)</h6>`
					+ configs.map(c => this.hole_position_svg(c, ctx, duct_shape)).join('');
			}
		}
		const now = frappe.datetime.now_datetime();
		const user = frappe.session.user_fullname || frappe.session.user;

		const html = `<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<title>HVAC Air Calculation Report</title>
<style>
	body { font-family: 'Sarabun', 'Tahoma', 'Segoe UI', sans-serif; font-size: 13px; color: #222; margin: 24px; }
	h5 { font-size: 17px; margin: 0 0 4px; }
	h6 { font-size: 14px; margin: 14px 0 6px; }
	table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
	th, td { border: 1px solid #999; padding: 5px 8px; }
	th { background: #f0f0f0; text-align: left; }
	.text-right { text-align: right; }
	.text-muted, .small { color: #666; font-size: 12px; }
	.row { display: flex; text-align: center; margin: 14px 0; }
	.col-4 { flex: 1; }
	.h3 { font-size: 24px; font-weight: bold; margin: 0; }
	.alert { border: 1px solid #999; background: #f7f7f7; padding: 8px 10px; font-size: 12px; margin-top: 8px; }
	.alert-warning { background: #fff8e1; border-color: #e0a800; }
	.font-weight-bold { font-weight: bold; }
	.report-header { border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 14px;
		display: flex; justify-content: space-between; align-items: flex-end; }
	.report-footer { border-top: 1px solid #999; margin-top: 18px; padding-top: 8px;
		font-size: 11px; color: #666; }
	.d-flex { display: block; }
	@media print { body { margin: 10mm; } }
</style>
</head>
<body>
	<div class="report-header">
		<div>
			<div style="font-size:18px; font-weight:bold;">รายงานการคำนวณระบบระบายอากาศ</div>
			<div class="text-muted">HVAC Air Calculation Report (CFM / Static Pressure)</div>
		</div>
		<div class="text-muted" style="text-align:right;">
			วันที่: ${now}<br>ผู้คำนวณ: ${user}
		</div>
	</div>
	${$result.html()}
	${positions_html}
	<div class="report-footer">
		มาตรฐานอ้างอิง: ASHRAE 62.1, ASHRAE 154, IMC 507, AMCA 210/201 —
		ผลการคำนวณนี้เป็นการประเมินเบื้องต้นสำหรับงานออกแบบขั้นต้น/เสนอราคา
		วิศวกรผู้ออกแบบต้องตรวจสอบกับมาตรฐานฉบับล่าสุดและกฎหมายท้องถิ่นก่อนใช้งานจริง
	</div>
	<script>window.onload = function () { window.print(); };<\/script>
</body>
</html>`;

		const w = window.open('', '_blank');
		if (!w) { frappe.msgprint(__('เบราว์เซอร์บล็อกหน้าต่างใหม่ กรุณาอนุญาต pop-up')); return; }
		w.document.write(html);
		w.document.close();
	}

	fan_recommendation(cfm, sp) {
		if (this.mode === 'hood') return 'พัดลมหอยโข่ง Backward/Upblast Kitchen Exhaust Fan (ทนไขมัน, UL 762) — เลือกจากกราฟที่ผ่านการทดสอบ AMCA 210';
		if (sp < 0.5) return 'พัดลมแบบ Axial / Wall Fan เพียงพอ (SP ต่ำ)';
		if (sp < 1.5) return 'พัดลม Inline / Cabinet Fan หรือหอยโข่ง Forward Curved';
		return 'พัดลมหอยโข่ง Backward Inclined — SP สูง เลือกจากกราฟ AMCA 210 พร้อมเช็ค Fan Class';
	}



	/* ---------- แสดงผล ---------- */

	render_result(res, sp) {
		const cmh = res.design_cfm * 1.699;
		const rows_cfm = res.rows.map(r =>
			`<tr><td>${r.label}</td><td class="text-right">${Math.round(r.cfm).toLocaleString()}</td></tr>`).join('');
		const rows_sp = sp.rows.map(r =>
			`<tr><td>${r.label}</td><td class="text-right">${r.sp.toFixed(2)}</td></tr>`).join('');

		const head = this.mode === 'room'
			? `${res.room.th} • ${res.room_w} × ${res.room_l} m (${res.area_m2.toFixed(1)} m²) • ${res.ach} ACH`
			: this.mode === 'duct'
				? `${res.room.th} • ${res.room_w} × ${res.room_l} m (${res.area_m2.toFixed(1)} m²) • ${res.dist.n} หัวดูด • เครื่องดูดห่าง ${res.dist.fan_dist} m`
				: `${res.hood_th} • ${res.duty_th} • ${res.L_m}×${res.W_m} m`;

		this.$body.find('#hvac_result').html(`
		<div class="frappe-card p-4 mb-4">
			<div class="d-flex justify-content-between align-items-center">
				<h5 class="mb-0">ผลการคำนวณ — ${res.mode_th}</h5>
				<button class="btn btn-default btn-sm" id="btn_print">🖨️ พิมพ์ผล</button>
			</div>
			<p class="text-muted small">${head}</p>

			<div class="row text-center mb-4">
				<div class="col-4">
					<div class="h3 mb-0 text-primary">${Math.round(res.design_cfm).toLocaleString()}</div>
					<div class="text-muted">CFM (ออกแบบ)</div>
					<div class="small text-muted">≈ ${Math.round(cmh).toLocaleString()} m³/h</div>
				</div>
				<div class="col-4">
					<div class="h3 mb-0 text-primary">${sp.total.toFixed(2)}</div>
					<div class="text-muted">in.wg (ESP)</div>
					<div class="small text-muted">≈ ${Math.round(sp.total * 249).toLocaleString()} Pa</div>
				</div>
				<div class="col-4">
					<div class="h3 mb-0 text-primary">${sp.v_ms.toFixed(1)} m/s</div>
					<div class="text-muted">ความเร็วจริงในท่อ</div>
					<div class="small text-muted">${sp.size_txt}</div>
				</div>
			</div>

			${sp.warnings.map(w => `<div class="alert alert-warning small py-2">⚠️ ${w}</div>`).join('')}

			<p class="small text-muted mb-3">
				ท่อกลมแนะนำที่ความเร็วลมพัดลม ${sp.fan_ms} m/s:
				<b>Ø ${sp.rec_dia_in.toFixed(0)}" (≈ ${(sp.rec_dia_in * 2.54).toFixed(0)} cm)</b>
				&nbsp;•&nbsp; อัตราเสียดทานที่คำนวณได้ ${sp.friction_per100.toFixed(2)} in.wg/100ft
			</p>

			<h6>ปริมาณลม (เปรียบเทียบแต่ละวิธี)</h6>
			<table class="table table-sm table-bordered">
				<thead><tr><th>วิธีคำนวณ</th><th class="text-right">CFM</th></tr></thead>
				<tbody>${rows_cfm}
					<tr class="font-weight-bold"><td>ค่าออกแบบ (${res.design_note})</td>
					<td class="text-right">${Math.round(res.design_cfm).toLocaleString()}</td></tr>
				</tbody>
			</table>
			${res.makeup_cfm ? `<p class="small">ลมชดเชย (Makeup Air) แนะนำ ≈ <b>${Math.round(res.makeup_cfm).toLocaleString()} CFM</b></p>` : ''}

			${res.holes ? this.render_holes(res.holes) : ''}

			${res.dist ? this.render_duct_dist(res.dist) : ''}

			<h6 class="mt-3">ความดันสถิต (External Static Pressure)</h6>
			<table class="table table-sm table-bordered">
				<thead><tr><th>องค์ประกอบ</th><th class="text-right">in.wg</th></tr></thead>
				<tbody>${rows_sp}
					<tr class="font-weight-bold"><td>รวม ESP</td><td class="text-right">${sp.total.toFixed(2)}</td></tr>
				</tbody>
			</table>

			<div class="alert alert-info small mb-0">
				<b>คำแนะนำพัดลม:</b> ${this.fan_recommendation(res.design_cfm, sp.total)}<br>
				เลือกพัดลมที่จุดทำงาน ${Math.round(res.design_cfm).toLocaleString()} CFM @ ${sp.total.toFixed(2)} in.wg
				จากกราฟสมรรถนะที่ทดสอบตาม <b>AMCA 210</b> (มีตรา AMCA Certified Ratings Seal)
			</div>
		</div>`);

		frappe.utils.scroll_to(this.$body.find('#hvac_result'));
	}
}
