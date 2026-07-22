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
	{ id: 'server',      th: 'ห้อง Server / Electrical',          rp: 0,    ra: 0.06, density: 0,   ach: [15, 20], ref: 'ควรออกแบบหลักจาก sensible heat load ของอุปกรณ์ (กรอกช่อง "ความร้อนที่ปล่อย") — ACH/VRP เป็นเพียงค่าประมาณสำรอง' },
	{ id: 'lab',         th: 'ห้องปฏิบัติการ (Laboratory)',       rp: 10,   ra: 0.18, density: 25,  ach: [6, 12],  ref: 'ASHRAE 62.1 / Lab guide' },
	{ id: 'machine',     th: 'ห้องเครื่องจักรปล่อยความร้อน (Machine/Equipment)', rp: 0, ra: 0.06, density: 0, ach: [15, 25], ref: 'แนวปฏิบัติ heat-driven — ควรตรวจสอบจากภาระความร้อนจริง (Q = H/(ρ·Cp·ΔT))' },
	{ id: 'factory',     th: 'โรงงาน (Factory / Manufacturing)', rp: 10, ra: 0.18, density: 7, ach: [6, 10], ref: 'ASHRAE 62.1 Table 6-1 (Manufacturing, ไม่ใช้สารอันตราย)' },
	{ id: 'dusty',       th: 'ห้องที่มีฝุ่น (Dusty/Particulate)', rp: 0,  ra: 0.30, density: 0, ach: [10, 15], exhaust_ra: 0.75, ref: 'แนวปฏิบัติ — งานฝุ่น/ขัด/เจียร ควรมี local exhaust ที่แหล่งกำเนิดร่วมด้วย ไม่พึ่งเจือจางอย่างเดียว' },
	{ id: 'odor',        th: 'ห้องที่มีกลิ่น (Odor-generating)', rp: 5,  ra: 0.24, density: 0, ach: [8, 12],  exhaust_ra: 0.50, ref: 'แนวปฏิบัติ — เช่น ห้องเก็บสารเคมี/สี/ขยะ ควรพิจารณา Carbon filter ก่อนทิ้ง' },
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
	odor: 3, dusty: 3,
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
	grille: 0.10, // หน้ากากดูด/จ่าย (ระบบระบายอากาศทั่วไป)
};

const CFM_PER_M2 = 10.7639; // ft² ต่อ m²
const M_TO_FT = 3.28084;

/* ---------------- Page Class ---------------- */

class HVACCalculator {
	constructor(page) {
		this.page = page;
		this.$body = $(page.body);
		this.custom_holes = []; // { n, d_in, selected } — คงอยู่ข้ามการคำนวณซ้ำ เพื่อให้ ESP อ้างอิงรูที่เลือกจริง
		// สถานะเปรียบเทียบพัดลมที่เลือก — คงอยู่ข้ามการคำนวณซ้ำ (แสดงในผลลัพธ์ เลือกเปิด/ปิดได้)
		this.fan_sel = { enabled: false, model: '', cfm_raw: 0, cfm_unit: 'cfm', sp_raw: 0, sp_unit: 'inwg', v: 0 };
		this.make();
	}

	make() {
		this.bind();
		this.render_form();
	}

	// วาดฟอร์มทั้งหมดเป็นค่าเริ่มต้น — ใช้ทั้งตอนเปิดหน้าและตอนกดล้างข้อมูล (event เป็น delegated บน $body จึงไม่ต้อง bind ซ้ำ)
	render_form() {
		this.$body.html(this.template());
		this.render_room_options();
		this.render_hood_options();
		this.render_filter_options();
		this.toggle_hood_shape();
		this.switch_mode('room');
	}

	// ล้างข้อมูลทั้งหมดกลับค่าเริ่มต้น (ฟอร์มทุกโหมด, รูเจาะกำหนดเอง, พัดลมที่เลือก, ผลลัพธ์)
	reset_all() {
		frappe.confirm('ล้างข้อมูลทั้งหมดและเริ่มใหม่ใช่หรือไม่? ค่าที่กรอกไว้ทุกโหมด รวมถึงรูเจาะกำหนดเองและพัดลมที่เลือกจะถูกล้าง', () => {
			this.custom_holes = [];
			this.fan_sel = { enabled: false, model: '', cfm_raw: 0, cfm_unit: 'cfm', sp_raw: 0, sp_unit: 'inwg', v: 0 };
			this.last_res = null;
			this.last_sp = null;
			this.render_form();
			frappe.show_alert({ message: 'ล้างข้อมูลเรียบร้อย', indicator: 'green' });
		});
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
					<div class="col-sm-3 mb-3 room-fixture-count" style="display:none;">
						<label>จำนวนโถสุขภัณฑ์</label>
						<input type="number" class="form-control" id="room_fixtures" value="4" min="0">
						<small class="text-muted">Exhaust = จำนวนโถ × CFM/โถ (ASHRAE 62.1 Table 6-2)</small>
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
						<label>Makeup Air (%)</label>
						<input type="number" class="form-control" id="hood_makeup_pct" value="80" step="5" min="60" max="90">
						<small class="text-muted">60–90% ของลมดูด — % ต่ำอาจกระทบ hood capture</small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>รูปทรงฝาชี</label>
						<select class="form-control" id="hood_shape">
							<option value="I">ตรง (I)</option>
							<option value="L">รูปตัว L</option>
							<option value="U">รูปตัว U</option>
						</select>
					</div>
					<div class="col-sm-2 mb-3">
						<label><span class="hood-leg-a-label">ยาว</span> A (m)</label>
						<input type="number" class="form-control" id="hood_length" value="2.0" step="0.1" min="0.3">
					</div>
					<div class="col-sm-2 mb-3 hood-leg-b" style="display:none;">
						<label>ด้าน B (m)</label>
						<input type="number" class="form-control" id="hood_len_b" value="1.5" step="0.1" min="0.3">
					</div>
					<div class="col-sm-2 mb-3 hood-leg-c" style="display:none;">
						<label>ด้าน C (m)</label>
						<input type="number" class="form-control" id="hood_len_c" value="1.5" step="0.1" min="0.3">
					</div>
					<div class="col-sm-3 mb-3">
						<label>รูปประกอบ</label>
						<div id="hood_shape_guide"></div>
					</div>
					<div class="col-sm-3 mb-3">
						<div class="checkbox mb-1">
							<label class="mb-0">
								<input type="checkbox" id="hood_plenum" checked> <b>ฝาชีมีท่อทับหลัง (Plenum) หลังฟิลเตอร์</b>
							</label>
						</div>
						<small class="text-muted">รูที่เจาะเป็นช่องเข้าท่อทับหลัง ไม่ใช่ต่อท่อสาขาตรง — ไม่ติ๊กถ้าแต่ละรูต่อท่อสาขาแยกไปท่อเมนโดยตรง</small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>กว้าง/ลึก (m)</label>
						<input type="number" class="form-control" id="hood_width" value="1.0" step="0.1" min="0.3">
					</div>
				</div>
				<div class="row align-items-end">
					<div class="col-sm-4 mb-2">
						<label class="mb-1"><b>สัมประสิทธิ์ทางเข้ารวม (C) — ฮู้ด+รูเจาะ</b></label>
						<div class="input-group input-group-sm">
							<input type="number" class="form-control" id="hood_entry_c" value="0.5" step="0.05" min="0.1" max="2">
							<div class="input-group-append"><span class="input-group-text">× VP</span></div>
						</div>
						<small class="text-muted">ค่าเดียวครอบคลุมทั้งทางเข้าฮู้ดและคอรู (ไม่บวกซ้ำ) — ใช้ความเร็วผ่านรูที่เลือกในตารางด้านล่างเป็นหลัก ถ้ายังไม่เลือกจะประมาณจากความเร็วลมพัดลม — ออกแบบดี 0.25, ทั่วไป 0.5, ตื้น/เลี้ยวแรง 0.75–1.0 (ACGIH)</small>
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
						<label>Air Class (ASHRAE 62.1) <a href="#" id="air_class_info_toggle" title="อธิบาย Air Class">ⓘ</a></label>
						<select class="form-control" id="dt_air_class_override">
							<option value="0">ตามประเภทห้อง (auto)</option>
							<option value="1">Class 1</option>
							<option value="2">Class 2</option>
							<option value="3">Class 3</option>
							<option value="4">Class 4</option>
						</select>
						<small class="text-muted">แก้ได้ถ้าอากาศจริงปนเปื้อนต่างจากชื่อห้อง</small>
					</div>
					<div class="col-12" id="air_class_info_panel" style="display:none;">
						<div class="alert alert-secondary small mb-3">
							<b>Air Class (ASHRAE 62.1) — ระดับการปนเปื้อนของอากาศ กำหนดว่านำกลับมาหมุนเวียนได้หรือต้องทิ้งนอกอาคาร:</b><br>
							<b>Class 1</b> — ปนเปื้อนต่ำ กลิ่น/ระคายเคืองน้อย มาจากคนเป็นหลัก (เช่น ออฟฟิศ ห้องประชุม) — หมุนเวียนได้<br>
							<b>Class 2</b> — ปนเปื้อนปานกลาง มีกลิ่น/ระคายเคืองบ้าง (เช่น ห้องน้ำ ห้องอาหาร ห้องล็อกเกอร์) — ห้ามหมุนเวียนไปโซนอื่น<br>
							<b>Class 3</b> — ปนเปื้อน/ระคายเคืองสูงอย่างมีนัยสำคัญ (เช่น ห้องแล็บ ห้องมีฝุ่น/กลิ่นเฉพาะ) — ห้ามหมุนเวียน ต้องทิ้งนอกอาคาร<br>
							<b>Class 4</b> — อันตราย/ไอสารเคมี-ไขมันรุนแรง (เช่น ครัว ห้องเคมี) — ห้ามหมุนเวียนเด็ดขาด ท่อแยกอิสระถึงจุดทิ้ง<br>
							<span class="text-muted">การจัด Class ในแอปนี้อิงชื่อประเภทห้องเป็นแนวทางเบื้องต้น ควรตรวจสอบองค์ประกอบอากาศจริงกับวิศวกรก่อนกำหนด Class สุดท้าย</span>
						</div>
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
					<div class="col-sm-2 mb-3 dt-fixture-count" style="display:none;">
						<label>จำนวนโถสุขภัณฑ์</label>
						<input type="number" class="form-control" id="dt_fixtures" value="4" min="0">
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
					<div class="col-sm-2 mb-3 dt-rows-field">
						<label>จำนวนแถวท่อเมน</label>
						<input type="number" class="form-control" id="dt_rows" value="1" min="1" max="10">
						<small class="text-muted">เมนขนานหลายแถว รวมกันก่อนถึงพัดลม (ใช้ได้เฉพาะเดินท่อ 1 ด้าน)</small>
					</div>
					<div class="col-sm-3 mb-3 dt-collector-field" style="display:none;">
						<label>ขนาดท่อรวม (Collector) Ø</label>
						<div class="input-group input-group-sm">
							<input type="number" class="form-control" id="dt_collector_d" value="0" step="0.5" min="0">
							<div class="input-group-append"><span class="input-group-text" id="dt_collector_unit_label">in</span></div>
						</div>
						<small class="text-muted" id="dt_collector_hint">0 = ยังไม่ระบุ → ใช้ค่าประมาณอัตโนมัติ (De × √จำนวนแถว) พร้อมคำเตือนให้ยืนยันขนาดจริง</small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>หัวดูดต่อแถว (จุด)</label>
						<input type="number" class="form-control" id="dt_n" value="4" min="1" max="30">
					</div>
					<div class="col-sm-2 mb-3">
						<label>เดินท่อรอบห้อง (กี่ด้าน)</label>
						<select class="form-control" id="dt_sides">
							<option value="1">1 ด้าน (ตรง)</option>
							<option value="2">2 ด้าน (มุมฉาก)</option>
							<option value="3">3 ด้าน (รูปตัว U)</option>
							<option value="4">4 ด้าน (รอบห้อง)</option>
						</select>
						<small class="text-muted">ท่อเมนเลี้ยวตามผนังห้อง เริ่มจากด้านที่เลือกด้านล่าง</small>
					</div>
					<div class="col-sm-2 mb-3">
						<label>แนวท่อเมน <span id="dt_axis_label_extra"></span></label>
						<select class="form-control" id="dt_axis">
							<option value="l">เริ่มด้านยาว</option>
							<option value="w">เริ่มด้านกว้าง</option>
						</select>
						<small class="text-muted">แนวกระจายหัวดูด/ภาพผัง</small>
					</div>
					<div class="col-12 mb-2 dt-rows-disabled-note" style="display:none;">
						<small class="text-muted">⚠️ เมื่อเดินท่อมากกว่า 1 ด้าน จะไม่ใช้ "จำนวนแถวท่อเมนขนาน" ร่วมด้วย (บังคับ 1 เส้นทางตามผนัง) เพื่อความเรียบง่ายของรูปทรง</small>
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
					<div class="col-sm-3 mb-2">
						<div class="checkbox mb-1">
							<label class="mb-0">
								<input type="checkbox" id="has_exhaust_cap" checked> <b>มีหัวจ่ายลมทิ้ง/Exhaust cap</b>
							</label>
						</div>
						<div class="input-group input-group-sm">
							<input type="number" class="form-control" id="exhaust_cap_sp" value="0.15" step="0.05" min="0">
							<div class="input-group-append"><span class="input-group-text">in.wg</span></div>
						</div>
						<small class="text-muted">ไม่ติ๊กถ้าเป็นระบบ Supply หรือปลายท่อไม่มี cap/หัวจ่าย</small>
					</div>
				</div>
				<small class="text-muted d-none" id="hood_filter_note">หมายเหตุ: โหมดฝาชีรวมค่า baffle filter ของฮู้ดไว้แล้ว — เลือกเพิ่มเฉพาะฟิลเตอร์ที่ติดตั้งเพิ่มในแนวท่อ</small>
			</div>

			<div class="text-center mb-4">
				<button class="btn btn-primary btn-lg px-5" id="btn_calc">คำนวณ</button>
				<button class="btn btn-default btn-lg px-4 ml-2" id="btn_reset" title="ล้างค่าที่กรอกทุกโหมดกลับเป็นค่าเริ่มต้น">ล้างข้อมูล (Reset)</button>
			</div>

			<div id="hvac_result"></div>
		</div>`;
	}

	bind() {
		this.$body.on('click', '.hvac-mode', (e) => this.switch_mode($(e.currentTarget).data('mode')));
		this.$body.on('click', '#btn_calc', () => this.calculate());
		this.$body.on('click', '#btn_reset', () => this.reset_all());
		this.$body.on('change', '#room_type', () => this.update_room_hint());
		this.$body.on('change', '#hood_type', () => this.render_duty_options());
		this.$body.on('change', '#hood_shape', () => this.toggle_hood_shape());
		this.$body.on('input', '#room_w, #room_l', () => this.update_area_hint());
		this.$body.on('change', '#dt_room_type', () => this.update_dt_hint());
		this.$body.on('input', '#dt_w, #dt_l', () => this.update_dt_area_hint());
		this.$body.on('input change', '#dt_rows', () => this.toggle_dt_collector());
		this.$body.on('change', '#dt_sides', () => this.toggle_dt_sides());
		this.$body.on('click', '#btn_print', () => this.print_result());
		this.$body.on('click', '#btn_add_hole', () => this.add_custom_hole());
		this.$body.on('click', '.hole-del', (e) => this.remove_custom_hole(parseInt($(e.currentTarget).data('idx'))));
		this.$body.on('change', '#custom_hole_shape', (e) => {
			const is_rect = $(e.target).val() === 'rect';
			this.$body.find('#custom_hole_d').css('display', is_rect ? 'none' : '');
			this.$body.find('#custom_hole_rect_inputs').css('display', is_rect ? 'inline-flex' : 'none');
		});
		this.$body.on('click', '#air_class_info_toggle', (e) => { e.preventDefault(); this.$body.find('#air_class_info_panel').slideToggle(150); });
		this.$body.on('change', '.esp-hole-radio', (e) => this.select_esp_hole(parseInt($(e.target).data('idx'))));
		this.$body.on('change', '#duct_shape', () => this.toggle_duct_shape());
		this.$body.on('change', '#duct_unit', () => this.update_duct_unit());
		this.$body.on('change', '#fan_sel_enable', () => this.update_fan_compare());
		this.$body.on('input change', '.fan-sel-input', () => this.update_fan_compare());
	}

	toggle_duct_shape() {
		const round = this.$body.find('#duct_shape').val() === 'round';
		this.$body.find('.duct-round').toggle(round);
		this.$body.find('.duct-rect').toggle(!round);
	}

	toggle_hood_shape() {
		const s = this.$body.find('#hood_shape').val();
		this.$body.find('.hood-leg-b').toggle(s === 'L' || s === 'U');
		this.$body.find('.hood-leg-c').toggle(s === 'U');
		this.$body.find('.hood-leg-a-label').text(s === 'I' ? 'ยาว' : 'ด้าน');
		this.$body.find('#hood_shape_guide').html(this.hood_shape_guide_svg(s));
	}

	// รูปประกอบเล็กๆ อธิบายว่าด้าน A / B / C / กว้าง อยู่ตรงไหน (มุมมองด้านบน)
	hood_shape_guide_svg(shape) {
		const dim = (x1, y1, x2, y2, txt, tx, ty, color = '#c33') => `
			<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="1" marker-start="url(#arr)" marker-end="url(#arr)"/>
			<text x="${tx}" y="${ty}" font-size="13" font-weight="bold" fill="${color}" text-anchor="middle">${txt}</text>`;
		const defs = `<defs><marker id="arr" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
			<path d="M0,0 L6,3 L0,6 z" fill="#c33"/></marker></defs>`;
		const style = 'fill:#f0f4f8; stroke:#333; stroke-width:1.5';

		if (shape === 'L') {
			// ขา A แนวนอนล่าง + ขา B แนวตั้งขวา
			return `<svg width="220" height="140" viewBox="0 0 220 140" style="border:1px solid #ddd; background:#fff;">${defs}
				<path d="M 20 100 L 20 130 L 180 130 L 180 20 L 140 20 L 140 100 Z" style="${style}"/>
				${dim(20, 112, 180, 112, '', 0, 0)}<text x="90" y="108" font-size="13" font-weight="bold" fill="#c33" text-anchor="middle">A</text>
				${dim(192, 20, 192, 130, '', 0, 0)}<text x="205" y="78" font-size="13" font-weight="bold" fill="#c33">B</text>
				<line x1="20" y1="136" x2="20" y2="124" stroke="#36c" stroke-width="1"/><line x1="20" y1="136" x2="46" y2="136" stroke="#36c" stroke-width="0"/>
				<text x="8" y="120" font-size="10" fill="#36c">กว้าง</text>
				<text x="65" y="55" font-size="10" fill="#888">มุมมองด้านบน</text>
			</svg>`;
		}
		if (shape === 'U') {
			// ขา A ตั้งซ้าย + ขา B นอนล่าง + ขา C ตั้งขวา
			return `<svg width="220" height="140" viewBox="0 0 220 140" style="border:1px solid #ddd; background:#fff;">${defs}
				<path d="M 20 15 L 60 15 L 60 95 L 160 95 L 160 15 L 200 15 L 200 130 L 20 130 Z" style="${style}"/>
				<line x1="8" y1="15" x2="8" y2="130" stroke="#c33" stroke-width="1" marker-start="url(#arr)" marker-end="url(#arr)"/>
				<text x="3" y="78" font-size="13" font-weight="bold" fill="#c33">A</text>
				<line x1="20" y1="138" x2="200" y2="138" stroke="#c33" stroke-width="1" marker-start="url(#arr)" marker-end="url(#arr)"/>
				<text x="110" y="125" font-size="13" font-weight="bold" fill="#c33" text-anchor="middle">B</text>
				<line x1="212" y1="15" x2="212" y2="130" stroke="#c33" stroke-width="1" marker-start="url(#arr)" marker-end="url(#arr)"/>
				<text x="211" y="78" font-size="13" font-weight="bold" fill="#c33">C</text>
				<text x="26" y="28" font-size="10" fill="#36c">กว้าง→</text>
				<text x="80" y="55" font-size="10" fill="#888">มุมมองด้านบน</text>
			</svg>`;
		}
		// I ตรง
		return `<svg width="220" height="140" viewBox="0 0 220 140" style="border:1px solid #ddd; background:#fff;">${defs}
			<rect x="25" y="45" width="170" height="50" style="${style}"/>
			<line x1="25" y1="32" x2="195" y2="32" stroke="#c33" stroke-width="1" marker-start="url(#arr)" marker-end="url(#arr)"/>
			<text x="110" y="26" font-size="13" font-weight="bold" fill="#c33" text-anchor="middle">A (ยาว)</text>
			<line x1="208" y1="45" x2="208" y2="95" stroke="#36c" stroke-width="1"/>
			<text x="204" y="115" font-size="10" fill="#36c" text-anchor="end">กว้าง/ลึก</text>
			<text x="80" y="75" font-size="10" fill="#888">มุมมองด้านบน</text>
		</svg>`;
	}

	update_duct_unit() {
		const unit = this.$body.find('#duct_unit').val();
		this.$body.find('.duct-unit-label').text(`(${unit})`);
		this.$body.find('#dt_collector_unit_label').text(unit);
		// แปลงค่าที่กรอกไว้ให้อัตโนมัติ
		const f = unit === 'cm' ? 2.54 : 1 / 2.54;
		['duct_dia', 'duct_w', 'duct_h', 'dt_collector_d'].forEach(id => {
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
		if (mode !== 'hood') this.custom_holes = []; // เลี่ยงข้อมูลรูเจาะค้างข้ามโหมด
		if (mode === 'duct') this.toggle_dt_sides();
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
		this.$body.find('.room-fixture-count').toggle(!!r.exhaust_fixture);
	}

	update_dt_hint() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#dt_room_type').val());
		if (!r) return;
		const cls = AIR_CLASS[r.id] || 1;
		this.$body.find('#dt_room_ref').text(`${r.ref} • Air Class ${cls}`);
		this.$body.find('#dt_ach_hint').text(`ช่วงแนะนำ ${r.ach[0]}–${r.ach[1]} ACH`);
		this.$body.find('#dt_ach').val(((r.ach[0] + r.ach[1]) / 2).toFixed(1));
		this.$body.find('.dt-fixture-count').toggle(!!r.exhaust_fixture);
	}

	update_dt_area_hint() {
		const a = this.num('dt_w') * this.num('dt_l');
		this.$body.find('#dt_area_hint').text(a > 0 ? `พื้นที่ = ${a.toFixed(1)} m²` : '');
	}

	toggle_dt_collector() {
		const rows_n = Math.max(1, parseInt(this.$body.find('#dt_rows').val()) || 1);
		this.$body.find('.dt-collector-field').toggle(rows_n > 1);
	}

	toggle_dt_sides() {
		const sides = parseInt(this.$body.find('#dt_sides').val()) || 1;
		const multi = sides > 1;
		this.$body.find('.dt-rows-field').toggle(!multi);
		this.$body.find('.dt-rows-disabled-note').toggle(multi);
		if (multi) this.$body.find('#dt_rows').val(1);
		this.toggle_dt_collector();
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
		const sp = this.calc_sp(res.design_cfm, res.duct_len_m, res.manifold, res.holes);
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

		// วิธี 3: Exhaust rate ต่อพื้นที่ (ถ้ามี)
		let cfm_exhaust = 0, exhaust_note = '';
		if (r.exhaust_ra) {
			cfm_exhaust = area_ft2 * r.exhaust_ra;
			exhaust_note = `${r.exhaust_ra} cfm/ft² × ${Math.round(area_ft2)} ft²`;
		}

		// วิธี 3b: Exhaust ต่อจำนวนโถสุขภัณฑ์ (ห้องน้ำ) — ASHRAE 62.1 Table 6-2
		let cfm_fixture = 0;
		const fixtures = this.num('room_fixtures');
		if (r.exhaust_fixture && fixtures > 0) cfm_fixture = fixtures * r.exhaust_fixture;

		// วิธี 4: ระบายความร้อน Q = H/(ρ·Cp·ΔT) → CFM ≈ 1756 × kW ÷ ΔT(°C)
		const heat_kw = this.num('room_heat');
		const heat_dt = this.num('room_heat_dt') || 5;
		const cfm_heat = heat_kw > 0 ? 1756 * heat_kw / heat_dt : 0;

		const design_cfm = Math.max(cfm_ach, cfm_621, cfm_exhaust, cfm_fixture, cfm_heat);

		return {
			mode_th: 'จากพื้นที่ห้อง',
			room: r, room_w, room_l, area_m2, area_ft2, volume_ft3, ach, people,
			rows: [
				{ label: `วิธี ACH (${ach} ACH × ${Math.round(volume_ft3).toLocaleString()} ft³ ÷ 60)`, cfm: cfm_ach },
				{ label: `วิธี ASHRAE 62.1 — Breathing Zone OA เบื้องต้น, Vbz (${people} คน × ${r.rp} + ${Math.round(area_ft2)} ft² × ${r.ra}) — ยังไม่รวม Ez/system efficiency`, cfm: cfm_621 },
				...(cfm_exhaust ? [{ label: `Exhaust ขั้นต่ำ ASHRAE 62.1 Table 6-2 (${exhaust_note})`, cfm: cfm_exhaust }] : []),
				...(cfm_fixture ? [{ label: `Exhaust ตามจำนวนโถ (${fixtures} โถ × ${r.exhaust_fixture} cfm/โถ) — ASHRAE 62.1 Table 6-2`, cfm: cfm_fixture }] : []),
				...(cfm_heat ? [{ label: `วิธีระบายความร้อน (${heat_kw} kW ÷ ρ·Cp·ΔT ${heat_dt}°C — ASHRAE Fundamentals)`, cfm: cfm_heat }] : []),
			],
			design_cfm,
			design_note: 'ใช้ค่ามากที่สุดของทุกวิธีเพื่อประมาณขนาดพัดลมเบื้องต้น — Outdoor Air / ACH / Exhaust / Heat removal ทำหน้าที่ต่างกัน อาจต้องออกแบบเป็นคนละระบบ (เช่น OA กับ Exhaust) ไม่ใช่ตัวเลขเดียวตอบโจทย์ทุกข้อกำหนดเสมอไป',
		};
	}

	calc_hood() {
		const hood = HOOD_RATES[this.$body.find('#hood_type').val()];
		const duty = this.$body.find('#hood_duty').val();
		const shape = this.$body.find('#hood_shape').val() || 'I';
		const A = this.num('hood_length');
		const B = (shape === 'L' || shape === 'U') ? this.num('hood_len_b') : 0;
		const C = (shape === 'U') ? this.num('hood_len_c') : 0;
		const W_m = this.num('hood_width');
		if (A <= 0 || W_m <= 0 || ((shape === 'L' || shape === 'U') && B <= 0) || (shape === 'U' && C <= 0)) {
			frappe.msgprint(__('กรุณากรอกขนาดฮู้ดให้ครบทุกด้าน')); return null;
		}

		const corners = shape === 'L' ? 1 : shape === 'U' ? 2 : 0;
		const total_len_m = A + B + C;                       // ความยาวรวมทุกด้าน (วัดขอบนอก)
		const centerline_m = total_len_m - corners * W_m;    // เส้นกึ่งกลางจริง (หักมุมทับซ้อน)
		if (centerline_m <= 0) { frappe.msgprint(__('ขนาดด้านสั้นเกินไปเมื่อเทียบความกว้างฮู้ด')); return null; }

		const L_ft = total_len_m * M_TO_FT;
		const rate = hood[duty];

		// วิธี 1: CFM ต่อฟุตความยาวรวมทุกด้าน (IMC / ASHRAE 154) — conservative สำหรับ L/U
		const cfm_linear = L_ft * rate;

		// วิธี 2: Face velocity 85 fpm บนพื้นที่หน้าฮู้ดจริง (หักมุมทับซ้อน ${corners} มุม)
		const face_v = 85;
		const face_area_ft2 = (centerline_m * W_m) * CFM_PER_M2;
		const cfm_face = face_area_ft2 * face_v;

		const design_cfm = Math.max(cfm_linear, cfm_face);

		// Makeup air ~80% ของ exhaust
		// Makeup air — ผู้ใช้กำหนดได้ 60–90% (default 80%) ของลมดูด
		const makeup_pct = Math.min(90, Math.max(60, this.num('hood_makeup_pct') || 80));
		const makeup_cfm = design_cfm * (makeup_pct / 100);
		const makeup_warn = (makeup_pct < 70 || makeup_pct > 85)
			? `⚠️ Makeup Air ${makeup_pct}% อยู่นอกช่วงแนะนำทั่วไป 70–85% — % ต่ำเกินไปอาจทำให้ฮู้ดจับควันไม่หมด (hood capture disruption), % สูงเกินไปอาจดันควันออกนอกฮู้ด`
			: '';

		// รูเจาะ: กระจายตามเส้นกึ่งกลางจริง
		const holes = this.calc_hood_holes(design_cfm, centerline_m, W_m);
		if (holes) { holes.shape = shape; holes.legs = { A, B, C }; }

		const shape_th = shape === 'L' ? 'รูปตัว L' : shape === 'U' ? 'รูปตัว U' : 'ตรง';
		const dims_th = shape === 'I' ? `${A}×${W_m} m`
			: shape === 'L' ? `L: A${A} + B${B} m (กว้าง ${W_m})`
			: `U: A${A} + B${B} + C${C} m (กว้าง ${W_m})`;

		return {
			mode_th: 'จากขนาดฝาชี',
			hood_th: hood.th, duty_th: DUTY_TH[duty],
			L_m: centerline_m, W_m, L_ft, rate,
			shape, dims_th, shape_th,
			rows: [
				{ label: `วิธี Linear (ยาวรวม ${total_len_m.toFixed(1)} m = ${L_ft.toFixed(1)} ft × ${rate} CFM/ft) — IMC 507.13`, cfm: cfm_linear },
				{ label: `วิธี Face Velocity ${face_v} fpm — ตรวจสอบเสริม (พื้นที่จริง ${(centerline_m * W_m).toFixed(1)} m²${corners ? ` หัก ${corners} มุม` : ''}), ไม่ใช่วิธีหลักมาตรฐานสำหรับ Kitchen Canopy Hood`, cfm: cfm_face },
			],
			design_cfm,
			makeup_cfm, makeup_pct, makeup_warn,
			holes,
			design_note: `ใช้ค่ามากที่สุด + จัด Makeup Air ตามค่าที่กำหนด ${makeup_pct}% ของลมดูด`,
		};
	}

	/* โหมดดูดอากาศผ่านท่อ — หัวดูดหลายจุดกระจายตามความยาวห้อง เครื่องดูดอยู่ห่างออกไป */
	// สร้างเส้นทางท่อเมนรอบห้อง (1–4 ด้าน) — คืนความยาวรวม + ฟังก์ชันแปลงระยะสะสม → พิกัด (x,y) ในกรอบห้อง
	// เดินตามผนังตามเข็มนาฬิกา สลับด้าน "แรก" (ตามแกนที่เลือก) กับด้าน "สอง" (ตั้งฉาก) ทุกครั้งที่เลี้ยวมุม
	build_perimeter_path(sides, axis, room_w, room_l) {
		sides = Math.max(1, Math.min(4, sides));
		const first = axis === 'w' ? room_w : room_l;
		const second = axis === 'w' ? room_l : room_w;
		const seg_lengths = [];
		for (let i = 0; i < sides; i++) seg_lengths.push(i % 2 === 0 ? first : second);
		const corner_pts = [[0, 0], [first, 0], [first, second], [0, second], [0, 0]];
		const total_len = seg_lengths.reduce((a, b) => a + b, 0);
		const path_pt = (s) => {
			let acc = 0;
			for (let i = 0; i < sides; i++) {
				const segLen = seg_lengths[i];
				if (s <= acc + segLen + 1e-9 || i === sides - 1) {
					const t = segLen > 0 ? Math.min(1, Math.max(0, (s - acc) / segLen)) : 0;
					const [x0, y0] = corner_pts[i], [x1, y1] = corner_pts[i + 1];
					return [x0 + (x1 - x0) * t, y0 + (y1 - y0) * t];
				}
				acc += segLen;
			}
			return corner_pts[sides];
		};
		return { total_len, path_pt, seg_lengths, corner_pts: corner_pts.slice(0, sides + 1), bb_w: first, bb_h: second };
	}

	calc_duct() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#dt_room_type').val());
		const room_w = this.num('dt_w');
		const room_l = this.num('dt_l');
		const height_m = this.num('dt_h');
		const ach = this.num('dt_ach');
		if (room_w <= 0 || room_l <= 0) { frappe.msgprint(__('กรุณากรอกความกว้างและความยาวห้อง')); return null; }
		const n = Math.max(1, parseInt(this.$body.find('#dt_n').val()) || 1);         // หัวดูดต่อแถว
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
		// Exhaust ต่อจำนวนโถสุขภัณฑ์ (ห้องน้ำ) — ASHRAE 62.1 Table 6-2
		let cfm_fixture = 0;
		const fixtures = this.num('dt_fixtures');
		if (r.exhaust_fixture && fixtures > 0) cfm_fixture = fixtures * r.exhaust_fixture;
		// วิธีระบายความร้อน Q = H/(ρ·Cp·ΔT) → CFM ≈ 1756 × kW ÷ ΔT(°C)
		const heat_kw = this.num('dt_heat');
		const heat_dt = this.num('dt_heat_dt') || 5;
		const cfm_heat = heat_kw > 0 ? 1756 * heat_kw / heat_dt : 0;
		const design_cfm = Math.max(cfm_ach, cfm_621, cfm_exhaust, cfm_fixture, cfm_heat);

		// ---- กระจายลมผ่านหัวดูด: หลายแถวท่อเมนขนาน ----
		// n = หัวดูดต่อแถว, rows = จำนวนแถวท่อเมน → หัวรวม = n × rows
		const rows_n = Math.max(1, parseInt(this.$body.find('#dt_rows').val()) || 1);
		const n_total = n * rows_n;
		const q = design_cfm / n_total;      // ลมต่อหัวดูด
		const row_cfm = design_cfm / rows_n; // ลมต่อแถว

		const face_fpm = face_ms * 196.85;
		const a_req_ft2 = q / face_fpm;
		let side_in = Math.sqrt(a_req_ft2) * 12;
		side_in = Math.ceil(side_in / 2) * 2;              // ปัดขึ้นเป็นขนาดมาตรฐานทุก 2 นิ้ว
		const a_act_ft2 = Math.pow(side_in / 12, 2);
		const v_act_ms = (q / a_act_ft2) / 196.85;

		// แนวท่อเมน: เดินรอบห้อง 1–4 ด้าน (เลี้ยวตามผนัง) เริ่มจากด้านที่เลือก
		const axis = this.$body.find('#dt_axis').val() || 'l';
		const sides = Math.max(1, Math.min(4, parseInt(this.$body.find('#dt_sides').val()) || 1));
		const path = this.build_perimeter_path(sides, axis, room_w, room_l);
		const run_m = path.total_len; // ความยาวรวมเส้นทางท่อเมน (รวมทุกด้านที่เดิน)
		const perp_m = path.bb_h;     // ใช้กำหนดกรอบภาพเท่านั้น (bounding box ของห้อง)

		// ตำแหน่งหัวดูดตามแนวท่อเมน (เหมือนกันทุกแถว)
		const spacing = run_m / n;
		const positions = [];
		for (let i = 0; i < n; i++) positions.push((spacing / 2 + i * spacing).toFixed(2));

		// ตำแหน่งแถวท่อเมน (แนวตั้งฉาก) — แบ่งพื้นที่เท่ากันทุกแถว
		const row_pitch = perp_m / rows_n;
		const row_positions = [];
		for (let i = 0; i < rows_n; i++) row_positions.push((row_pitch / 2 + i * row_pitch).toFixed(2));

		// ความยาวท่อเส้นทางวิกฤตจริง = จากหัวไกลสุด (ห่างขอบ spacing/2) ถึงขอบห้อง + ระยะถึงเครื่องดูด
		// เท่ากับผลรวม segment ที่ใช้จริงใน critical path ด้านล่าง (spacing×(n-0.5) + fan_dist)
		const duct_len_m = spacing * (n - 0.5) + fan_dist;

		// ---- Critical Path: แถวหนึ่ง (ลมสะสม k×q) + ท่อรวมหลังรวมแถว → พัดลม ----
		const g = this.get_duct_geometry();
		if (!g) return null;
		const Cg = 2.5; // สัมประสิทธิ์ความดันตกหัวดูด (register + core)
		const VP_face = Math.pow(face_fpm / 4005, 2);
		const dPg_far = Cg * VP_face; // หัวไกลสุดกำหนดที่ความเร็วเป้าหมาย

		// หัวที่ 1 = ไกลพัดลมสุด → หัวที่ n = ใกล้สุด (ต่อแถว)
		const grilles = [];
		let cum_duct = 0; // แรงดันท่อสะสมภายในแถว
		for (let k = 1; k <= n; k++) {
			const suction_k = dPg_far + cum_duct;
			const v_req_fpm = 4005 * Math.sqrt(suction_k / Cg);
			const a_req = q / v_req_fpm;
			const side = Math.max(4, Math.round(Math.sqrt(a_req) * 12));
			const v_act = (q / Math.pow(side / 12, 2)) / 196.85;
			grilles.push({ i: k, pos: positions[k - 1], dp: suction_k, side, v_ms: v_act });
			// ช่วงท่อถัดไปในแถว: ระหว่างหัว (spacing) หรือช่วงสุดท้ายถึงขอบห้อง (spacing/2)
			const Lk_m = (k < n) ? spacing : spacing / 2;
			const Qk = k * q;
			const f100 = 0.109136 * Math.pow(Qk, 1.9) / Math.pow(g.De_in, 5.02);
			cum_duct += f100 * (Lk_m * M_TO_FT / 100);
		}

		// ท่อรวมหลังรวมทุกแถว → พัดลม: ลมเต็ม CFM
		// ขนาดท่อรวมที่ผู้ใช้ยืนยัน (ถ้ากรอกไว้) — ไม่งั้นใช้ค่าประมาณ De × √แถว (คงความเร็วเดิม) พร้อมคำเตือน
		const to_in_col = this.$body.find('#duct_unit').val() === 'cm' ? 1 / 2.54 : 1;
		const De_col_user = this.num('dt_collector_d') * to_in_col;
		const De_col_suggested = g.De_in * Math.sqrt(rows_n);
		const collector_confirmed = De_col_user > 0;
		const De_col = collector_confirmed ? De_col_user : De_col_suggested;
		const f_col = 0.109136 * Math.pow(design_cfm, 1.9) / Math.pow(De_col, 5.02);
		const sp_collector = f_col * (fan_dist * M_TO_FT / 100);

		const manifold = {
			sp_main: cum_duct + sp_collector, // เส้นทางวิกฤต: ในแถว + ท่อรวมถึงพัดลม
			sp_row: cum_duct, sp_collector,
			dPg_far, Cg, rows_n, De_col, De_col_suggested, collector_confirmed,
			uniformity: dPg_far / Math.max(0.0001, cum_duct + sp_collector),
		};

		const air_class_override = parseInt(this.$body.find('#dt_air_class_override').val()) || 0;
		const air_class = air_class_override || AIR_CLASS[r.id] || 1;

		return {
			mode_th: 'ดูดอากาศผ่านท่อ (หลายจุด)',
			room: r, room_w, room_l, area_m2, ach, people,
			rows: [
				{ label: `วิธี ACH (${ach} ACH × ${Math.round(volume_ft3).toLocaleString()} ft³ ÷ 60)`, cfm: cfm_ach },
				{ label: `วิธี ASHRAE 62.1 — Breathing Zone OA เบื้องต้น, Vbz (${people} คน × ${r.rp} + ${Math.round(area_ft2)} ft² × ${r.ra}) — ยังไม่รวม Ez/system efficiency`, cfm: cfm_621 },
				...(cfm_exhaust ? [{ label: `Exhaust ขั้นต่ำ ASHRAE 62.1 Table 6-2 (${exhaust_note})`, cfm: cfm_exhaust }] : []),
				...(cfm_fixture ? [{ label: `Exhaust ตามจำนวนโถ (${fixtures} โถ × ${r.exhaust_fixture} cfm/โถ) — ASHRAE 62.1 Table 6-2`, cfm: cfm_fixture }] : []),
				...(cfm_heat ? [{ label: `วิธีระบายความร้อน (${heat_kw} kW ÷ ρ·Cp·ΔT ${heat_dt}°C — ASHRAE Fundamentals)`, cfm: cfm_heat }] : []),
			],
			design_cfm,
			design_note: 'ใช้ค่ามากที่สุดของทุกวิธีเพื่อประมาณขนาดพัดลมเบื้องต้น — Outdoor Air / ACH / Exhaust / Heat removal ทำหน้าที่ต่างกัน อาจต้องออกแบบเป็นคนละระบบ (เช่น OA กับ Exhaust) ไม่ใช่ตัวเลขเดียวตอบโจทย์ทุกข้อกำหนดเสมอไป',
			duct_len_m,
			manifold,
			dist: { n, rows_n, n_total, q, row_cfm, side_in, face_ms, v_act_ms, spacing, positions, row_pitch, row_positions, fan_dist, duct_len_m, air_class, air_class_override, grilles, manifold, room_w, room_l, axis, sides, run_m, perp_m },
		};
	}

	render_duct_dist(d) {
		const sp_warn = d.spacing > 3
			? `<div class="alert alert-warning small py-2">⚠️ ระยะห่างหัวดูด ${d.spacing.toFixed(2)} m เกิน ~3 m — การดูดอาจไม่สม่ำเสมอ พิจารณาเพิ่มจำนวนหัวดูด</div>` : '';
		const v_warn = d.v_act_ms > 3
			? `<div class="alert alert-warning small py-2">⚠️ ความเร็วหน้าหัวดูด ${d.v_act_ms.toFixed(1)} m/s เกิน 3 m/s อาจมีเสียงดัง — เพิ่มขนาดหัวดูดหรือจำนวนจุด</div>` : '';
		return `
			<h6 class="mt-3">การกระจายหัวดูด (${d.rows_n > 1 ? `${d.rows_n} แถว × ${d.n} จุด = ${d.n_total} จุด` : `${d.n} จุด`})</h6>
			<table class="table table-sm table-bordered">
				<tbody>
					${d.rows_n > 1 ? `<tr><td>ลมต่อแถวท่อเมน</td><td class="text-right">${Math.round(d.row_cfm).toLocaleString()} CFM/แถว — ระยะห่างแถว ${d.row_pitch.toFixed(2)} m (ตำแหน่งแถว: ${d.row_positions.join(', ')} m)</td></tr>` : ''}
					<tr><td>ลมต่อหัวดูด</td><td class="text-right"><b>${Math.round(d.q).toLocaleString()} CFM</b> (≈ ${Math.round(d.q * 1.699).toLocaleString()} m³/h)</td></tr>
					<tr><td>ขนาดหัวดูดแนะนำ (คอ)</td><td class="text-right"><b>${d.side_in}" × ${d.side_in}"</b> (≈ ${(d.side_in * 2.54).toFixed(0)} × ${(d.side_in * 2.54).toFixed(0)} cm)</td></tr>
					<tr><td>ความเร็วหน้าหัวดูดจริง</td><td class="text-right">${d.v_act_ms.toFixed(1)} m/s (เป้าหมาย ${d.face_ms} m/s)</td></tr>
					<tr><td>ระยะห่างหัวดูด (ตามเส้นทางท่อเมน${d.sides > 1 ? ` — เดินรอบห้อง ${d.sides} ด้าน` : ` — ด้าน${d.axis === 'w' ? 'กว้าง' : 'ยาว'}`} รวม ${d.run_m.toFixed(1)} m)</td><td class="text-right">${d.spacing.toFixed(2)} m — หัวแรก/สุดท้ายห่างขอบ ${(d.spacing / 2).toFixed(2)} m</td></tr>
					<tr><td>ตำแหน่งหัวดูด${d.sides > 1 ? 'ตามเส้นทาง (ระยะสะสมจากจุดเริ่ม)' : 'จากขอบห้อง'} (m)</td><td class="text-right">${d.positions.join(', ')}</td></tr>
					<tr><td>ความยาวท่อ Critical Path ถึงเครื่องดูด</td><td class="text-right">${d.duct_len_m.toFixed(1)} m (หัวไกลสุด→ขอบห้อง ${(d.duct_len_m - d.fan_dist).toFixed(2)} + ถึงพัดลม ${d.fan_dist.toFixed(1)})</td></tr>
				</tbody>
			</table>
			${d.rows_n > 1 ? (d.manifold.collector_confirmed
				? `<div class="alert alert-secondary small py-2">ท่อรวม (Collector) หลังรวม ${d.rows_n} แถว ใช้ขนาดที่ยืนยันแล้ว Ø ${d.manifold.De_col.toFixed(1)}"</div>`
				: `<div class="alert alert-warning small py-2">⚠️ ยังไม่ได้ยืนยันขนาดท่อรวม (Collector) — ระบบประมาณ Ø ≈ ${d.manifold.De_col_suggested.toFixed(0)}" จากสูตร (De ต่อแถว × √${d.rows_n} แถว) เท่านั้น ถ้างานจริงใช้ท่อเล็กกว่านี้ ESP จะสูงกว่าที่คำนวณมาก — กรอกช่อง "ขนาดท่อรวม (Collector)" ด้านบนเพื่อความแม่นยำ</div>`
			) : ''}
			${v_warn}${sp_warn}
			${this.duct_layout_svg(d)}
			${this.render_grille_balance(d)}
			<div class="alert alert-secondary small">
				<b>ประเภทอากาศ (ASHRAE 62.1):</b> ${AIR_CLASS_TH[d.air_class]}${d.air_class_override ? ' <span class="text-muted">(กำหนดเอง — ไม่ได้อิงชื่อห้องอัตโนมัติ)</span>' : ''}<br>
				<b>ข้อแนะนำ:</b>
				ติด Volume Damper ทุก branch เพื่อปรับสมดุลลมแต่ละหัว •
				ท่อตรงก่อนเข้าพัดลมอย่างน้อย 2–3 เท่าของ Ø ท่อ ลด System Effect (AMCA 201) •
				ความเร็วหน้าหัวดูด ≤ 2.5–3 m/s และในท่อเมน 4–6 m/s เพื่อควบคุมเสียง •
				จุดทิ้งอากาศห่างจากช่องรับอากาศเข้า (OA intake) ตามระยะขั้นต่ำ ASHRAE 62.1 Table 5-1
				${d.sides > 1 ? `• ⚠️ เดินท่อ ${d.sides} ด้าน: การคำนวณ ESP ยังไม่รวมความสูญเสียที่มุมเลี้ยว (elbow loss ที่จุดเปลี่ยนด้าน) ควรเผื่อเพิ่มด้วยตนเองตามจำนวนมุมจริง (${d.sides - 1} มุม)` : ''}
			</div>`;
	}

	// ผังท่อคร่าวๆ (มุมมองด้านบน): ห้อง + ท่อเมน + หัวดูด n จุด + เครื่องดูด (วาดตามสัดส่วน)
	// แกนนอนของภาพ = แนวท่อเมน (เลือกได้ว่าด้านกว้างหรือด้านยาว)
	duct_layout_svg(d) {
		if (d.sides > 1) return this.duct_layout_svg_bent(d); // เดินท่อหลายด้าน — ใช้ผังแบบเลี้ยวมุมแยกต่างหาก
		const W = 700, mg = 45;
		const fan_w_px = 46; // พื้นที่สัญลักษณ์พัดลม
		const innerW = W - 2 * mg - fan_w_px;
		const run_m = d.run_m, perp_m = d.perp_m;
		const total_m = run_m + Math.max(0.5, d.fan_dist);
		const scale = innerW / total_m;
		const room_y = 40;
		const room_h = Math.max(50, perp_m * scale);
		const cy = room_y + room_h / 2;
		const H = Math.ceil(room_y + room_h + 66);
		const x0 = mg;
		const room_x1 = x0 + run_m * scale;
		const fan_x = room_x1 + Math.max(0.5, d.fan_dist) * scale;
		const duct_h = 12;
		const axis_th = d.axis === 'w' ? 'กว้าง' : 'ยาว';
		const perp_th = d.axis === 'w' ? 'ยาว' : 'กว้าง';

		// หลายแถวท่อเมน: y ของแต่ละแถวตามตำแหน่งจริง (แนวตั้งฉาก)
		const rows_n = d.rows_n || 1;
		const row_ys = (d.row_positions && rows_n > 1)
			? d.row_positions.map(p => room_y + parseFloat(p) * scale)
			: [cy];
		const first_x = x0 + parseFloat(d.positions[0]) * scale;

		// ท่อเมนแต่ละแถว + หัวดูด
		let duct_rows_svg = '', grille_svg = '', pos_labels = '';
		row_ys.forEach((ry, ri) => {
			duct_rows_svg += `<rect x="${first_x.toFixed(1)}" y="${(ry - duct_h / 2).toFixed(1)}" width="${(room_x1 - first_x).toFixed(1)}" height="${duct_h}"
				fill="#e8f0fe" stroke="#36c" stroke-width="1.2"/>`;
			d.positions.forEach(p => {
				const cx = x0 + parseFloat(p) * scale;
				grille_svg += `<rect x="${(cx - 8).toFixed(1)}" y="${(ry - 8).toFixed(1)}" width="16" height="16"
					fill="#fff" stroke="#0a6" stroke-width="1.5"/>
					<line x1="${(cx - 5).toFixed(1)}" y1="${ry.toFixed(1)}" x2="${(cx + 5).toFixed(1)}" y2="${ry.toFixed(1)}" stroke="#0a6" stroke-width="1"/>
					<line x1="${cx.toFixed(1)}" y1="${(ry - 5).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(ry + 5).toFixed(1)}" stroke="#0a6" stroke-width="1"/>`;
			});
		});
		// ป้ายตำแหน่ง (ใต้ห้อง ครั้งเดียว — ทุกแถวตำแหน่งเดียวกัน)
		d.positions.forEach(p => {
			const cx = x0 + parseFloat(p) * scale;
			pos_labels += `<line x1="${cx.toFixed(1)}" y1="${(room_y + room_h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(room_y + room_h + 12).toFixed(1)}"
				stroke="#888" stroke-width="0.8" stroke-dasharray="3,2"/>
				<text x="${cx.toFixed(1)}" y="${(room_y + room_h + 24).toFixed(1)}" text-anchor="middle" font-size="10">${p}</text>`;
		});
		// ท่อรวมแนวตั้งที่ขอบห้อง (เมื่อหลายแถว) เชื่อมทุกแถวเข้าแนวกลางก่อนไปพัดลม
		const header_svg = rows_n > 1
			? `<rect x="${(room_x1 - duct_h / 2).toFixed(1)}" y="${(Math.min(...row_ys) - duct_h / 2).toFixed(1)}"
				width="${duct_h}" height="${(Math.max(...row_ys) - Math.min(...row_ys) + duct_h).toFixed(1)}"
				fill="#e8f0fe" stroke="#36c" stroke-width="1.2"/>`
			: '';

		return `
		<h6 class="mt-3">ผังท่อคร่าวๆ — มุมมองด้านบน (มาตราส่วนตามจริง)</h6>
		<div style="margin-bottom:12px; page-break-inside:avoid;">
			<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
				style="border:1px solid #ddd; background:#fff; max-width:100%;">
				<!-- ห้อง -->
				<rect x="${x0}" y="${room_y}" width="${(room_x1 - x0).toFixed(1)}" height="${room_h.toFixed(1)}"
					fill="#f8f8f8" stroke="#333" stroke-width="1.5"/>
				<text x="${x0 + 5}" y="${room_y - 6}" font-size="11" fill="#666">ห้อง ${d.room_w} × ${d.room_l} m — ท่อเมนตามด้าน${axis_th} (ฝั่งซ้าย = ไกลพัดลม)</text>
				<!-- ท่อเมนแต่ละแถว + ท่อรวม + ท่อไปพัดลม -->
				${duct_rows_svg}
				${header_svg}
				<rect x="${room_x1.toFixed(1)}" y="${(cy - duct_h / 2).toFixed(1)}" width="${(fan_x - room_x1).toFixed(1)}" height="${duct_h}"
					fill="#e8f0fe" stroke="#36c" stroke-width="1.2"/>
				<text x="${((first_x + room_x1) / 2).toFixed(1)}" y="${(Math.min(...row_ys) - duct_h / 2 - 5).toFixed(1)}" text-anchor="middle" font-size="10" fill="#36c">ท่อเมน${rows_n > 1 ? ` × ${rows_n} แถว` : ''}</text>
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
				<text x="${((x0 + room_x1) / 2).toFixed(1)}" y="${(H - 5).toFixed(1)}" text-anchor="middle" font-size="10">ด้าน${axis_th} ${run_m} m (แนวท่อเมน) • ด้าน${perp_th} ${perp_m} m — ตัวเลขใต้หัวดูด = ตำแหน่งจากฝั่งไกล (m)</text>
			</svg>
		</div>`;
	}


	// ผังท่อเมื่อเดินรอบห้องมากกว่า 1 ด้าน (มุมฉาก/ตัว U/รอบห้อง) — วาดตามเส้นทางจริงพร้อมมุมเลี้ยว
	duct_layout_svg_bent(d) {
		const path = this.build_perimeter_path(d.sides, d.axis, d.room_w, d.room_l);
		const W = 700, mg = 50;
		const fan_room_px = 70; // เผื่อระยะไปเครื่องดูดทางขวา
		const availW = W - 2 * mg - fan_room_px;
		const availH = 300;
		const scale = Math.min(availW / path.bb_w, availH / path.bb_h);
		const ox = mg, oy = 55;
		const X = x => ox + x * scale;
		const Y = y => oy + y * scale;

		const room_outline = `<rect x="${X(0).toFixed(1)}" y="${Y(0).toFixed(1)}" width="${(path.bb_w * scale).toFixed(1)}" height="${(path.bb_h * scale).toFixed(1)}"
			fill="#f8f8f8" stroke="#ccc" stroke-width="1" stroke-dasharray="4,3"/>`;

		const poly_pts = path.corner_pts.map(([x, y]) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(' ');
		const duct_path_svg = `<polyline points="${poly_pts}" fill="none" stroke="#36c" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>`;

		let grille_svg = '', pos_labels = '';
		d.positions.forEach((p) => {
			const [px, py] = path.path_pt(parseFloat(p));
			const cx = X(px), cy = Y(py);
			grille_svg += `<rect x="${(cx - 7).toFixed(1)}" y="${(cy - 7).toFixed(1)}" width="14" height="14"
				fill="#fff" stroke="#0a6" stroke-width="1.5"/>
				<line x1="${(cx - 4).toFixed(1)}" y1="${cy.toFixed(1)}" x2="${(cx + 4).toFixed(1)}" y2="${cy.toFixed(1)}" stroke="#0a6" stroke-width="1"/>
				<line x1="${cx.toFixed(1)}" y1="${(cy - 4).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(cy + 4).toFixed(1)}" stroke="#0a6" stroke-width="1"/>`;
			pos_labels += `<text x="${cx.toFixed(1)}" y="${(cy - 12).toFixed(1)}" text-anchor="middle" font-size="9" fill="#555">${p}</text>`;
		});

		const [ex, ey] = path.path_pt(path.total_len);
		const fanX = X(ex) + Math.max(20, d.fan_dist * scale);
		const fanY = Y(ey);
		const fan_line = `<line x1="${X(ex).toFixed(1)}" y1="${Y(ey).toFixed(1)}" x2="${fanX.toFixed(1)}" y2="${fanY.toFixed(1)}" stroke="#36c" stroke-width="6"/>`;
		const fan_symbol = `
			<rect x="${fanX.toFixed(1)}" y="${(fanY - 20).toFixed(1)}" width="40" height="40" fill="#fff" stroke="#c33" stroke-width="1.5"/>
			<circle cx="${(fanX + 20).toFixed(1)}" cy="${fanY.toFixed(1)}" r="12" fill="none" stroke="#c33" stroke-width="1.2"/>
			<path d="M ${(fanX + 20).toFixed(1)} ${(fanY - 12).toFixed(1)} A 12 12 0 0 1 ${(fanX + 32).toFixed(1)} ${fanY.toFixed(1)}" fill="none" stroke="#c33" stroke-width="1.2"/>
			<text x="${(fanX + 20).toFixed(1)}" y="${(fanY + 34).toFixed(1)}" text-anchor="middle" font-size="10" fill="#c33">เครื่องดูด</text>`;

		const start_mark = `<circle cx="${X(0).toFixed(1)}" cy="${Y(0).toFixed(1)}" r="4" fill="#c33"/>
			<text x="${X(0).toFixed(1)}" y="${(Y(0) - 10).toFixed(1)}" font-size="9" fill="#c33" text-anchor="middle">เริ่ม 0.00 m</text>`;

		const H = Math.max(oy + path.bb_h * scale + 40, fanY + 60);
		const sides_th = { 1: '1 ด้าน (ตรง)', 2: '2 ด้าน (มุมฉาก)', 3: '3 ด้าน (ตัว U)', 4: '4 ด้าน (รอบห้อง)' }[d.sides];

		return `
		<h6 class="mt-3">ผังท่อคร่าวๆ — มุมมองด้านบน (เดินท่อรอบห้อง ${sides_th})</h6>
		<div style="margin-bottom:12px; page-break-inside:avoid;">
			<svg width="${W}" height="${H.toFixed(0)}" viewBox="0 0 ${W} ${H.toFixed(0)}" xmlns="http://www.w3.org/2000/svg"
				style="border:1px solid #ddd; background:#fff; max-width:100%;">
				${room_outline}
				${duct_path_svg}
				${grille_svg}
				${pos_labels}
				${start_mark}
				${fan_line}
				${fan_symbol}
				<text x="${ox}" y="30" font-size="11" fill="#666">ห้อง ${d.room_w} × ${d.room_l} m — เส้นทางท่อรวม ${d.run_m.toFixed(1)} m • ตัวเลขข้างหัวดูด = ระยะสะสมตามเส้นทางจากจุดเริ่ม (m)</text>
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
				หลักการ: หัวใกล้พัดลมเจอแรงดูดสูงกว่า จึงลดขนาดหัวให้ความต้านทานชดเชยบางส่วน →
				ขนาดในตารางเป็น <b>จุดเริ่มต้นที่ช่วยลดความต่างของลมแต่ละหัว</b> ไม่ใช่ค่าที่ยืนยันได้ว่าทุกหัวจะได้ ${Math.round(d.q).toLocaleString()} CFM เท่ากันเป๊ะ
				เพราะขนาดคอถูกปัดเป็นนิ้วเต็มโดยไม่คำนวณย้อนกลับด้วยพื้นที่จริงหลังปัด ไม่ตรวจ convergence และยังไม่รวม branch fitting/takeoff —
				<b>ยังต้องติดตั้ง volume damper ทุกจุดเพื่อทำ TAB (Testing, Adjusting, Balancing) หน้างานจริง</b>
				(ΔP หัวดูดประมาณจาก C=${m.Cg} × VP หน้าหัว, ท่อเมนคิดแบบ Critical Path สะสมลมทีละช่วง${m.rows_n > 1 ? ` — ในแถว ${m.sp_row.toFixed(3)} + ท่อรวมถึงพัดลม ${m.sp_collector.toFixed(3)} in.wg`
					+ (m.collector_confirmed
						? `, คำนวณด้วยขนาดท่อรวมที่ยืนยันแล้ว Ø ${m.De_col.toFixed(1)}"`
						: `, ⚠️ ยังไม่ได้กรอกขนาดท่อรวมจริง — ประมาณจาก Ø ≈ ${m.De_col_suggested.toFixed(0)}" (De ต่อแถว × √${m.rows_n} แถว) กรอกช่อง "ขนาดท่อรวม (Collector)" เพื่อความแม่นยำ`)
					: ''})
			</p>
			<p class="small mb-2">${ratio_note}</p>`;
	}

	/* รูเจาะฝาชี — โหมดกำหนดเองเท่านั้น (ไม่มีตัวเลือกอัตโนมัติ)
	 * เกณฑ์ตรวจแถวที่ผู้ใช้กำหนดเอง (6 ข้อ):
	 * (1) รูไม่เกินขนาดท่อ — บังคับเฉพาะไม่มีท่อทับหลัง (รูต่อท่อสาขาตรง);
	 *     มีท่อทับหลัง: รูเป็นช่องเข้าท่อทับหลัง ไม่ถูกจำกัดด้วยขนาดท่อเมน
	 * (2) ขนาดรู ≤ 60% ของความกว้างฝาชี
	 * (3) จำนวนรูตามช่วงแนะนำของความยาวฝาชี:
	 *     <1.5m→1–2 | 1.5–2.5→2–4 | 2.5–3→3–6 | 3–4→5–8 | 4–5→6–10 | >5m→≥9 รู
	 * (4) ความเร็วผ่านรู 2.54–10 m/s (5) พื้นที่รูรวม > 12% ของพื้นที่ฝาชี
	 * (6) ระยะห่างรู ≤ 2 m
	 * หมายเหตุ: เกณฑ์เดิม "ลม/รู ≤ 1/3 ของลมรวม" และ "ฝาชี > 2 m เริ่ม 3 รู / ≤ 2 m ไม่เกิน 4 รู"
	 * ถูกยกเลิกแล้ว — ใช้ตารางช่วงแนะนำตามความยาวฝาชีเป็นตัวคุมจำนวนรูแทน
	 */
	calc_hood_holes(cfm, L_m, W_m) {
		const V_LO = 2.54, V_HI = 10; // เกณฑ์ความเร็วผ่านรู (IMC 500 fpm – เพดานเสียง)
		const AREA_MIN = 0.12;                // พื้นที่รูรวมต้องมากกว่า 12% ของพื้นที่ฝาชี

		const has_plenum = this.$body.find('#hood_plenum').is(':checked');
		// รูต้องไม่ใหญ่กว่าท่อ — ใช้บังคับเฉพาะกรณีไม่มีท่อทับหลัง (รูต่อท่อสาขาตรง)
		const duct_limit_in = has_plenum ? 0 : this.get_duct_limit_in();

		// ตารางจำนวนรูแนะนำตามความยาวฝาชี (เส้นกึ่งกลาง)
		// < 1.5 m → 1–2 รู | 1.5–2.5 → 2–4 | 2.5–3 → 3–6 | 3–4 → 5–8 | 4–5 → 6–10 | > 5 m → ≥ 9 รู (ไม่จำกัดเพดาน)
		const range_of = L => L < 1.5 ? [1, 2] : L <= 2.5 ? [2, 4] : L <= 3.0 ? [3, 6]
			: L <= 4.0 ? [5, 8] : L <= 5.0 ? [6, 10] : [9, Infinity];
		const [tbl_min, tbl_max] = range_of(L_m);

		return {
			options: [], // ไม่มีตัวเลือกอัตโนมัติ — ผู้ใช้เพิ่มแถวกำหนดเองเท่านั้น
			duct_limit_in, V_LO, V_HI, cfm, L_m, W_m,
			AREA_MIN, has_plenum,
			tbl_min, tbl_max,
			face_area_m2: L_m * W_m,
		};
	}

	// วาดผังตำแหน่งรูเจาะ (มุมมองด้านบน มาตราส่วนจริง) — รองรับฝาชีตรง / L / U
	// รูเจาะกระจายตามเส้นกึ่งกลาง; รูปทรงรูตามที่ผู้ใช้กำหนดต่อแถว (กลม Ø หรือเหลี่ยม w × h ขนาดจริง)
	hole_position_svg(cfg, ctx) {
		const shape = ctx.shape || 'I';
		const legs = ctx.legs || { A: ctx.L_m, B: 0, C: 0 };
		const Wd = ctx.W_m; // ความกว้าง(ลึก)ฝาชี
		const A = legs.A, B = legs.B, C = legs.C;

		// ---- นิยามรูปร่าง (หน่วยเมตร): กรอบสี่เหลี่ยมประกอบ + ฟังก์ชันจุดบนเส้นกึ่งกลางที่ระยะ s ----
		let rects, path_pt, bb_w, bb_h;
		if (shape === 'L') {
			// ขา A แนวนอนล่าง + ขา B แนวตั้งขวา (แชร์มุมขวาล่าง)
			rects = [[0, 0, A, Wd], [A - Wd, 0, Wd, B]];
			bb_w = A; bb_h = Math.max(Wd, B);
			const s1 = A - Wd / 2; // ช่วงแนวนอนบนเส้นกึ่งกลาง
			path_pt = s => s <= s1 ? [s, Wd / 2] : [A - Wd / 2, Wd / 2 + (s - s1)];
		} else if (shape === 'U') {
			// ขา A ตั้งซ้าย + ขา B นอนล่าง + ขา C ตั้งขวา
			rects = [[0, 0, Wd, A], [0, 0, B, Wd], [B - Wd, 0, Wd, C]];
			bb_w = B; bb_h = Math.max(A, C, Wd);
			const s1 = A - Wd / 2;          // ลงขา A
			const s2 = s1 + (B - Wd);       // ผ่านขาล่าง
			path_pt = s => s <= s1 ? [Wd / 2, A - s]
				: s <= s2 ? [Wd / 2 + (s - s1), Wd / 2]
				: [B - Wd / 2, Wd / 2 + (s - s2)];
		} else {
			rects = [[0, 0, A, Wd]];
			bb_w = A; bb_h = Wd;
			path_pt = s => [s, Wd / 2];
		}

		// ---- สเกลภาพ ----
		const Wpx = 700, mg = 45;
		const scale = Math.min((Wpx - 2 * mg) / bb_w, 320 / bb_h);
		const H = Math.ceil(bb_h * scale + mg + 55);
		const ox = mg, oy = 30;
		const X = x => ox + x * scale;
		const Y = y => oy + (bb_h - y) * scale; // กลับแกน y ให้ล่าง = 0

		// รูปทรงรูตามที่ผู้ใช้กำหนดในแถวนั้น — เหลี่ยมวาดขนาดจริง w × h (w ตามแนวยาว, h ตามแนวกว้างฝาชี)
		const is_rect_hole = cfg.shape === 'rect';
		const r = Math.max(2, ((cfg.d_in || 0) * 0.0254 / 2) * scale);
		const hw = Math.max(2, ((cfg.w_in || 0) * 0.0254 / 2) * scale);
		const hh = Math.max(2, ((cfg.h_in || 0) * 0.0254 / 2) * scale);

		const rects_svg = rects.map(rc =>
			`<rect x="${X(rc[0]).toFixed(1)}" y="${Y(rc[1] + rc[3]).toFixed(1)}" width="${(rc[2] * scale).toFixed(1)}" height="${(rc[3] * scale).toFixed(1)}"
				fill="#f8f8f8" stroke="#333" stroke-width="1.5"/>`).join('');

		let shapes = '', labels = '';
		const positions = [];
		for (let i = 0; i < cfg.n; i++) {
			const s = cfg.spacing / 2 + i * cfg.spacing;
			positions.push(s.toFixed(2));
			const [px, py] = path_pt(Math.min(s, ctx.L_m));
			const cx = X(px), cyy = Y(py);
			if (is_rect_hole) {
				shapes += `<rect x="${(cx - hw).toFixed(1)}" y="${(cyy - hh).toFixed(1)}" width="${(hw * 2).toFixed(1)}" height="${(hh * 2).toFixed(1)}"
					fill="#fff" stroke="#333" stroke-width="1.5"/>`;
			} else {
				shapes += `<circle cx="${cx.toFixed(1)}" cy="${cyy.toFixed(1)}" r="${r.toFixed(1)}" fill="#fff" stroke="#333" stroke-width="1.5"/>`;
			}
			const lo = is_rect_hole ? Math.max(hw, hh) : r; // ระยะเว้น label ตามขนาดรู
			shapes += `<line x1="${(cx - 4).toFixed(1)}" y1="${cyy.toFixed(1)}" x2="${(cx + 4).toFixed(1)}" y2="${cyy.toFixed(1)}" stroke="#333" stroke-width="0.8"/>
				<line x1="${cx.toFixed(1)}" y1="${(cyy - 4).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${(cyy + 4).toFixed(1)}" stroke="#333" stroke-width="0.8"/>`;
			labels += `<text x="${(cx + (lo + 6)).toFixed(1)}" y="${(cyy - lo - 4).toFixed(1)}" font-size="10" fill="#555">${s.toFixed(2)}</text>`;
		}

		const size_desc = `${is_rect_hole ? 'รูเหลี่ยม' : 'รูกลม'} ${this.hole_size_txt(cfg)}`;
		const dims_txt = shape === 'L' ? `A=${A}, B=${B}, กว้าง=${Wd} m`
			: shape === 'U' ? `A=${A}, B=${B}, C=${C}, กว้าง=${Wd} m`
			: `ยาว=${A}, กว้าง=${Wd} m`;

		return `
		<div style="margin-bottom:14px; page-break-inside:avoid;">
			<div style="font-size:12px; margin-bottom:2px;">
				<b>${cfg.n} รู × ${size_desc}</b>
				— ระยะห่างรู ${cfg.spacing.toFixed(2)} m ตามเส้นกึ่งกลาง (ยาวรวม ${ctx.L_m.toFixed(2)} m), รูแรก/สุดท้ายห่างปลาย ${(cfg.spacing / 2).toFixed(2)} m
				• ตำแหน่งตามเส้นกึ่งกลางจากปลายด้าน A (m): ${positions.join(', ')}
			</div>
			<svg width="${Wpx}" height="${H}" viewBox="0 0 ${Wpx} ${H}" xmlns="http://www.w3.org/2000/svg"
				style="border:1px solid #ddd; background:#fff; max-width:100%;">
				${rects_svg}
				${shapes}
				${labels}
				<text x="${ox}" y="${oy - 12}" font-size="11" fill="#666">ฝาชี${shape === 'I' ? 'ตรง' : 'รูปตัว ' + shape} ${dims_txt} • ตัวเลขข้างรู = ระยะตามเส้นกึ่งกลาง (m) • รูเจาะ${is_rect_hole ? 'เหลี่ยม (ขนาดจริง)' : 'กลม'} • มาตราส่วนตามจริง</text>
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

	calc_sp(cfm, len_m_override, manifold, holes_ctx) {
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

		// ---- แรงดันทางเข้ารวม (ฮู้ด + รูเจาะ/คอ) = C × VP ----
		// ใช้ความเร็วผ่านรูจริงจากแถวที่ผู้ใช้ "เลือกใช้ ESP" ในตารางรูเจาะ ถ้ามี
		// ไม่มีการบวกซ้ำอีกก้อนสำหรับ collar — ค่า C ตัวเดียวนี้ครอบคลุมทั้งทางเข้าฮู้ดและคอรูแล้ว
		const entry_c = parseFloat(this.$body.find('#hood_entry_c').val()) || 0.5;
		let v_entry_fpm, entry_governs, entry_estimated = false, selected_hole_txt = '';
		if (is_hood) {
			const sel = holes_ctx ? this.custom_holes.find(h => h.selected) : null;
			if (sel) {
				// มีรูที่เลือก → ใช้ความเร็วผ่านรูนั้นโดยตรง (ไม่เทียบ/ไม่ผสมกับความเร็วในท่อเมน
				// เพราะความสูญเสียในท่อเมนถูกคิดแยกผ่าน friction + fittings อยู่แล้ว)
				const o = this.compute_hole_option(sel, holes_ctx);
				v_entry_fpm = o.v * 196.85;
				entry_governs = 'ความเร็วผ่านรูที่เลือก';
				selected_hole_txt = ` (จากรูที่เลือก: ${sel.n} รู ${this.hole_size_txt(o)} @ ${o.v.toFixed(1)} m/s)`;
			} else {
				// ยังไม่ได้เลือกรู → ใช้ความเร็วเป้าหมาย (ลมพัดลม) เป็นค่าประมาณ
				const fan_ms_entry = this.num('fan_velocity') || 8;
				v_entry_fpm = fan_ms_entry * 196.85;
				entry_governs = 'ความเร็วประมาณจากลมพัดลม';
				entry_estimated = true;
			}
		} else {
			v_entry_fpm = v_fpm;
			entry_governs = 'ความเร็วในท่อ';
		}
		const VP_entry = Math.pow(v_entry_fpm / 4005, 2);
		const hood_entry = entry_c * VP_entry;
		const sp_entry = is_hood ? hood_entry + baffle_sp
			: manifold ? manifold.dPg_far
			: SP_COMPONENTS.grille;

		const entry_label = is_hood
			? `ทางเข้ารวม (ฮู้ด+รูเจาะ) C=${entry_c} × VP ${VP_entry.toFixed(3)} (${entry_governs}${entry_estimated ? ' — ยังไม่ได้เลือกรูจากตาราง ใช้ค่าประมาณ' : ''}) = ${hood_entry.toFixed(2)}${selected_hole_txt}`
				+ (has_baffle ? ` + Baffle filter ${baffle_sp.toFixed(2)}` : ' (ไม่มี baffle filter)')
			: manifold ? `หัวดูดไกลสุด C=${manifold.Cg} × VP หน้าหัว (ตัวกำหนดระบบ)`
			: 'หน้ากากดูด/จ่าย';
		const has_cap = this.$body.find('#has_exhaust_cap').is(':checked');
		const sp_cap = has_cap ? (parseFloat(this.$body.find('#exhaust_cap_sp').val()) || 0) : 0;

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

		const subtotal = sp_duct + sp_fittings + sp_entry + sp_cap + sp_extra;
		const safety = subtotal * 0.15; // Design allowance เบื้องต้น (fitting uncertainty) — ไม่ใช่สูตร AMCA 201 โดยตรง ต้องประเมิน System Effect Factor แยกตามรูปแบบติดตั้งจริง
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
				{ label: `ข้องอ 90° × ${elbows} จุด (C=0.3 × VP ${VP.toFixed(3)} — คิดจากความเร็วเต็มของท่อที่ระบุ ถ้าบางข้องออยู่ใน branch ลมน้อยกว่านี้ ค่านี้จะสูงกว่าจริง)`, sp: sp_fittings },
				...(has_cap ? [{ label: 'หัวปล่อยทิ้ง/Exhaust cap', sp: sp_cap }] : []),
				...extra_rows,
				{ label: 'Design allowance 15% (fitting uncertainty — ประเมิน System Effect Factor ตาม AMCA 201 แยกตามรูปแบบติดตั้งจริงเพิ่มเติม)', sp: safety },
			],
			total, v_ms, VP, size_txt, De_in, friction_per100,
			rec_dia_in, fan_ms, warnings,
		};
	}

	// คำนวณค่าทั้งหมดของรู 1 ตัวเลือก จาก ctx ปัจจุบัน — ใช้ทั้งตอนเพิ่มแถวและตอน re-render
	// hole = { n, shape: 'circle'|'rect', d_in (กลม), w_in, h_in (เหลี่ยม: w ตามแนวยาวฝาชี, h ตามแนวกว้าง) }
	compute_hole_option(hole, ctx) {
		const n = hole.n;
		const shape = hole.shape || 'circle';
		const q = ctx.cfm / n;
		const area_ft2 = shape === 'rect'
			? (hole.w_in / 12) * (hole.h_in / 12)
			: Math.PI / 4 * Math.pow(hole.d_in / 12, 2);
		const v = (q / area_ft2) / 196.85;
		const spacing = ctx.L_m / n;
		const VP = Math.pow(v * 196.85 / 4005, 2);
		const collar_loss = 0.5 * VP;
		const hole_area_m2 = area_ft2 * 0.09290304;
		// เส้นผ่านศูนย์กลางเทียบเท่าเชิงพื้นที่ (นิ้ว) — ใช้เทียบกับขนาดท่อสาขา
		const d_eq = shape === 'rect' ? Math.sqrt(4 * area_ft2 / Math.PI) * 12 : hole.d_in;
		// มิติตามแนวกว้างฝาชี — ใช้ตรวจเกณฑ์ 60% ของความกว้าง
		const across_in = shape === 'rect' ? hole.h_in : hole.d_in;
		return {
			n, shape, d_in: hole.d_in, w_in: hole.w_in, h_in: hole.h_in, d_eq,
			q, v, spacing, collar_loss,
			pass_v: v >= ctx.V_LO && v <= ctx.V_HI,
			pass_sp: spacing <= 2.0,
			total_area_m2: n * hole_area_m2,
			area_ratio: ctx.face_area_m2 ? (n * hole_area_m2) / ctx.face_area_m2 : 0,
			d_to_w: ctx.W_m ? (across_in * 0.0254) / ctx.W_m : 0,
		};
	}

	// ข้อความขนาดรูสำหรับแสดงผล เช่น Ø 10" (25 cm) หรือ 10" × 6" (25 × 15 cm)
	hole_size_txt(o) {
		const f = x => x % 1 ? x.toFixed(1) : x;
		return (o.shape || 'circle') === 'rect'
			? `${f(o.w_in)}" × ${f(o.h_in)}" (${(o.w_in * 2.54).toFixed(0)} × ${(o.h_in * 2.54).toFixed(0)} cm)`
			: `Ø ${f(o.d_in)}" (${(o.d_in * 2.54).toFixed(0)} cm)`;
	}

	render_holes(holes) {
		this.last_holes_ctx = holes; // เก็บบริบทไว้คำนวณแถวกำหนดเอง
		const limit_txt = holes.duct_limit_in > 0
			? `รูเจาะจำกัดไม่เกินขนาดท่อที่กำหนด: Ø ≤ ${holes.duct_limit_in.toFixed(1)}" (≈ ${(holes.duct_limit_in * 2.54).toFixed(0)} cm)`
			: '';
		// วนคำนวณใหม่จากรายการที่ผู้ใช้เพิ่มไว้ (this.custom_holes) ด้วย ctx ปัจจุบันเสมอ — กันค่าค้างเมื่อเปลี่ยนขนาดฝาชี/CFM
		const rows = this.custom_holes.map((h, i) => {
			const o = this.compute_hole_option(h, holes);
			return this.hole_row_html(o, i, h.selected);
		}).join('');
		const has_selected = this.custom_holes.some(h => h.selected);

		return `
			<h6 class="mt-3">รูเจาะฝาชี (จุดต่อท่อดูด) — กำหนดเอง</h6>
			<p class="small text-muted mb-2">กรอกจำนวน × ขนาดรู แล้วกด "เพิ่มเปรียบเทียบ" — เลือกวงกลม "ใช้คำนวณ ESP" ที่แถวเดียวที่จะใช้จริง ระบบจะคำนวณความดันสถิตจากขนาดรูของแถวนั้นโดยตรง</p>
			${this.custom_holes.length && !has_selected ? '<div class="alert alert-warning small py-2">⚠️ ยังไม่ได้เลือกแถวที่จะใช้คำนวณ ESP — เลือกวงกลมในคอลัมน์ "ใช้ ESP" ที่แถวที่ต้องการก่อนพิมพ์ผล</div>' : ''}
			${!this.custom_holes.length ? '<div class="alert alert-secondary small py-2">ยังไม่มีแถวรูเจาะ — เพิ่มอย่างน้อย 1 แถวเพื่อให้ ESP คำนวณจากขนาดรูจริง มิฉะนั้นระบบจะใช้ค่าประมาณจากความเร็วลมพัดลมแทน</div>' : ''}
			<table class="table table-sm table-bordered" id="holes_table">
				<thead><tr>
					<th class="text-center">ใช้ ESP</th>
					<th class="hole-print-col text-center">พิมพ์</th>
					<th>จำนวนรู</th><th class="text-right">ขนาดรู</th>
					<th class="text-right">CFM/รู</th><th class="text-right">ความเร็ว (m/s)</th>
					<th class="text-right">ระยะห่าง (m)</th><th class="text-right">พื้นที่รูรวม</th>
					<th class="text-right">ค่าอ้างอิง 0.5×VP (in.wg)</th><th>สถานะ</th>
					<th class="hole-del-col text-center">ลบ</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			<div class="form-inline mb-2 hole-custom-form">
				<label class="mr-2">กำหนดเอง:</label>
				<input type="number" class="form-control form-control-sm mr-1" id="custom_hole_n" value="2" min="1" max="20" style="width:70px" title="จำนวนรู"> รู ×
				<select class="form-control form-control-sm mx-1" id="custom_hole_shape" style="width:95px" title="รูปทรงรู">
					<option value="circle">รูกลม Ø</option><option value="rect">รูเหลี่ยม</option>
				</select>
				<input type="number" class="form-control form-control-sm mx-1" id="custom_hole_d" value="10" step="0.5" min="1" style="width:80px" title="ขนาดรูกลม (เส้นผ่านศูนย์กลาง)">
				<span id="custom_hole_rect_inputs" style="display:none; align-items:center;">
					<input type="number" class="form-control form-control-sm mx-1" id="custom_hole_w" value="10" step="0.5" min="1" style="width:75px" title="ด้านตามแนวยาวฝาชี (กว้างรู)"> ×
					<input type="number" class="form-control form-control-sm mx-1" id="custom_hole_h" value="6" step="0.5" min="1" style="width:75px" title="ด้านตามแนวกว้างฝาชี (สูงรู)">
				</span>
				<select class="form-control form-control-sm mr-2" id="custom_hole_unit" style="width:70px">
					<option value="in">in</option><option value="cm">cm</option>
				</select>
				<button class="btn btn-default btn-sm" id="btn_add_hole">➕ เพิ่มเปรียบเทียบ</button>
				<label class="ml-3 mb-0 small">
					<input type="checkbox" id="show_hole_positions" checked> แสดงตำแหน่งรูเจาะเมื่อพิมพ์
				</label>
			</div>
			<p class="small text-muted mb-2">
				<b>ข้อพิจารณาการเปิดรู (ตรวจอัตโนมัติทุกแถวที่กำหนดเอง):</b>
				<span class="text-muted">— เกณฑ์ด้านล่างเป็นแนวทางออกแบบภายในของแอปนี้ ไม่ใช่ข้อกำหนดที่คัดลอกมาจาก IMC/ASHRAE โดยตรง ควรตรวจสอบกับวิศวกรและมาตรฐานฉบับเต็มก่อนใช้งานจริง</span>
				(1) ${holes.has_plenum ? 'มีท่อทับหลัง — รูเป็นช่องเข้าท่อทับหลัง ไม่จำกัดตามขนาดท่อเมน (ปากต่อท่อทับหลัง→ท่อเมนต้องพอดีกับท่อที่กำหนดแยกต่างหาก)' : `ไม่มีท่อทับหลัง — รูไม่เกินขนาดท่อสาขาที่กำหนด (Ø ≤ ${holes.duct_limit_in ? holes.duct_limit_in.toFixed(1) : '-'}\\")`}
				(2) ขนาดรู ≤ 60% ของความกว้างฝาชี ${holes.W_m} m
				(3) จำนวนรูตามความยาวฝาชี ${holes.L_m.toFixed(1)} m → แนะนำ ${holes.tbl_max === Infinity ? '≥ ' + holes.tbl_min : (holes.tbl_min || '-') + (holes.tbl_max && holes.tbl_max !== holes.tbl_min ? '–' + holes.tbl_max : '')} รู
				(ตาราง: &lt;1.5m→1–2 | 1.5–2.5→2–4 | 2.5–3→3–6 | 3–4→5–8 | 4–5→6–10 | &gt;5m→≥9 รู)
				(4) ความเร็วผ่านรู ${holes.V_LO}–${holes.V_HI} m/s (ขั้นต่ำ IMC 500 fpm ถึงเพดานเสียง)
				(5) พื้นที่รูรวมต่อพื้นที่ฝาชี ${(holes.face_area_m2 || 0).toFixed(1)} m² ต้องมากกว่า ${Math.round(holes.AREA_MIN * 100)}%
				(6) ระยะห่างระหว่างศูนย์กลางรู ≤ 2 m — ป้องกันจุดอับลมกึ่งกลางระหว่างรูที่แรงดูดอ่อน
				&nbsp;&nbsp;&nbsp;(รูแรก/รูสุดท้ายวางห่างขอบฝาชีครึ่งหนึ่งของระยะห่างนี้ เพื่อให้แรงดูดคลุมถึงขอบฝาชีเท่าๆ กัน)
				${limit_txt ? '• ' + limit_txt : ''}
				• ติ๊กช่อง "พิมพ์" เฉพาะแถวที่ต้องการให้แสดงในรายงาน — วงกลม "ใช้ ESP" มีได้แถวเดียวเท่านั้น
			</p>`;
	}

	hole_row_html(o, idx, selected) {
		const ctx = this.last_holes_ctx;
		let status;
		// (1) รูไม่เกินขนาดท่อ — เฉพาะกรณีไม่มีท่อทับหลัง (รูต่อท่อสาขาตรง) — รูเหลี่ยมเทียบด้วย Ø เทียบเท่าเชิงพื้นที่
		if (!ctx.has_plenum && ctx.duct_limit_in > 0 && o.d_eq > ctx.duct_limit_in + 0.01) {
			status = `⚠️ รูใหญ่กว่าท่อ (${o.shape === 'rect' ? `Øเทียบเท่า ${o.d_eq.toFixed(1)}"` : `Ø${o.d_in}"`} > ท่อ Ø${ctx.duct_limit_in.toFixed(1)}") — ไม่มีท่อทับหลัง ต้องต่อท่อสาขาโดยตรง`;
		// (2) ขนาดรู (ด้านตามแนวกว้าง) ≤ 60% ของความกว้างฝาชี
		} else if (o.d_to_w > 0.6) {
			status = `⚠️ รู ${o.shape === 'rect' ? `ด้านกว้าง ${o.h_in % 1 ? o.h_in.toFixed(1) : o.h_in}"` : `Ø${o.d_in}"`} เกิน 60% ของความกว้างฝาชี ${ctx.W_m} m`;
		// (3) จำนวนรูตามความยาวฝาชี
		} else if (ctx.tbl_min && (o.n < ctx.tbl_min || o.n > ctx.tbl_max)) {
			status = `⚠️ นอกช่วงแนะนำ ${ctx.tbl_max === Infinity ? '≥ ' + ctx.tbl_min : ctx.tbl_min + '–' + ctx.tbl_max} รู (ฝาชียาว ${ctx.L_m.toFixed(1)} m)`;
		// (4) ความเร็วผ่านรู 2.54–10 m/s
		} else if (o.v > 10) {
			status = `🔊 ความเร็ว ${o.v.toFixed(1)} m/s เกิน 10 m/s เสียงดัง`;
		} else if (o.v < ctx.V_LO) {
			status = `⚠️ ความเร็ว ${o.v.toFixed(1)} m/s ต่ำกว่าขั้นต่ำ IMC 2.54 m/s`;
		// (5) พื้นที่รูรวม > 12% ของพื้นที่ฝาชี
		} else if (o.area_ratio <= ctx.AREA_MIN + 0.001) {
			status = `⚠️ พื้นที่รูรวม ${(o.area_ratio * 100).toFixed(1)}% ไม่เกิน ${Math.round(ctx.AREA_MIN * 100)}% ของฝาชี`;
		// (6) ระยะห่างระหว่างรู ≤ 2 m
		} else if (!o.pass_sp) {
			status = `⚠️ ระยะห่างรู ${o.spacing.toFixed(2)} m เกิน 2 m (จุดกึ่งกลางระหว่างรูดูดลมอ่อน เสี่ยงจุดอับ)`;
		} else {
			status = '✅';
		}
		const size_txt = this.hole_size_txt(o);
		return `<tr data-idx="${idx}" data-n="${o.n}" data-shape="${o.shape}" data-d="${o.d_in || 0}" data-w="${o.w_in || 0}" data-h="${o.h_in || 0}" data-spacing="${o.spacing}" data-v="${o.v}">
			<td class="text-center"><input type="radio" name="esp_hole_select" class="esp-hole-radio" data-idx="${idx}" ${selected ? 'checked' : ''}></td>
			<td class="hole-print-col text-center"><input type="checkbox" class="hole-print" checked></td>
			<td>${o.n} รู${selected ? ' <span class="badge badge-primary">ใช้คำนวณ ESP</span>' : ''}</td>
			<td class="text-right">${size_txt}</td>
			<td class="text-right">${Math.round(o.q).toLocaleString()}</td>
			<td class="text-right">${o.v.toFixed(1)}</td>
			<td class="text-right">${o.spacing.toFixed(2)}</td>
			<td class="text-right">${(o.total_area_m2 * 10000).toFixed(0)} cm²<br><span class="text-muted small">${(o.area_ratio * 100).toFixed(1)}% ของฝาชี</span></td>
			<td class="text-right" title="ค่าอ้างอิงเท่านั้น — ถ้าแถวนี้ถูกเลือกใช้ ESP ระบบจะคำนวณ Entry loss จาก C ที่กำหนด × VP ของรูนี้โดยตรง ไม่ได้บวกตัวเลขนี้ซ้ำเข้า ESP อีกก้อน">${o.collar_loss.toFixed(2)}</td>
			<td>${status}</td>
			<td class="hole-del-col text-center"><button class="btn btn-xs btn-default hole-del" data-idx="${idx}" title="ลบแถวนี้">−</button></td>
		</tr>`;
	}

	add_custom_hole() {
		const ctx = this.last_holes_ctx;
		if (!ctx) return;
		const n = parseInt(this.$body.find('#custom_hole_n').val()) || 0;
		const shape = this.$body.find('#custom_hole_shape').val() || 'circle';
		const to_in = this.$body.find('#custom_hole_unit').val() === 'cm' ? (x) => x / 2.54 : (x) => x;
		const selected = this.custom_holes.length === 0; // แถวแรกเลือกใช้ ESP ให้อัตโนมัติ

		if (shape === 'rect') {
			const w_in = to_in(parseFloat(this.$body.find('#custom_hole_w').val()) || 0);
			const h_in = to_in(parseFloat(this.$body.find('#custom_hole_h').val()) || 0);
			if (n <= 0 || w_in <= 0 || h_in <= 0) { frappe.msgprint(__('กรุณากรอกจำนวนรูและขนาดรูเหลี่ยม (กว้าง × สูง) ให้ครบ')); return; }
			this.custom_holes.push({ n, shape: 'rect', w_in, h_in, selected });
		} else {
			const d_in = to_in(parseFloat(this.$body.find('#custom_hole_d').val()) || 0);
			if (n <= 0 || d_in <= 0) { frappe.msgprint(__('กรุณากรอกจำนวนและขนาดรู')); return; }
			this.custom_holes.push({ n, shape: 'circle', d_in, selected });
		}
		this.calculate(); // คำนวณใหม่ทั้งชุด — ESP จะสะท้อนแถวที่เพิ่ม/เลือกทันที
	}

	// ลบแถวรูเจาะ — ถ้าลบแถวที่ผูก ESP อยู่ ระบบจะกลับไปประมาณจากลมพัดลม พร้อมเตือนให้เลือกแถวใหม่
	remove_custom_hole(idx) {
		if (idx < 0 || idx >= this.custom_holes.length) return;
		this.custom_holes.splice(idx, 1);
		this.calculate();
	}

	select_esp_hole(idx) {
		this.custom_holes.forEach((h, i) => { h.selected = (i === idx); });
		this.calculate();
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
		$result.find('.hole-del-col').remove(); // ตัดคอลัมน์ปุ่มลบแถวออกจากรายงาน
		$result.find('.hole-custom-form').remove();
		$result.find('.fan-sel-form').remove(); // ตัด checkbox/ฟอร์มกรอกพัดลม — คงเฉพาะตารางผลเปรียบเทียบ (ถ้าเปิดใช้)

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
						shape: $(this).data('shape') || 'circle',
						d_in: parseFloat($(this).data('d')) || 0,
						w_in: parseFloat($(this).data('w')) || 0,
						h_in: parseFloat($(this).data('h')) || 0,
						spacing: parseFloat($(this).data('spacing')),
					});
				}
			});
			if (configs.length) {
				positions_html = `<h6 style="margin-top:16px;">ตำแหน่งรูเจาะฝาชี — มุมมองด้านบน (วัดถึงกึ่งกลางรู จากขอบซ้าย)</h6>`
					+ configs.map(c => this.hole_position_svg(c, ctx)).join('');
			}
		}
		const now = frappe.datetime.now_datetime();
		const user = frappe.session.user_fullname || frappe.session.user;

		const html = `<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<title>HVAC Air Calculation Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;700&display=swap" rel="stylesheet">
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
	tr.table-success td { background: #e6f4ea; }
	tr.table-warning td { background: #fff8e1; }
	tr.table-danger td { background: #fdecea; }
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

	/* ---------- เปรียบเทียบพัดลมที่เลือก (Fan Selection) ---------- */

	// แปลงค่าจาก state กลับเป็น CFM / in.wg — คืน null ถ้ายังไม่กรอกอะไรเลย
	fan_selection_input() {
		const f = this.fan_sel;
		if (f.cfm_raw <= 0 && f.sp_raw <= 0 && f.v <= 0) return null;
		const cfm = f.cfm_unit === 'cmh' ? f.cfm_raw / 1.699 : f.cfm_raw;     // 1 CFM = 1.699 m³/h
		const sp = f.sp_unit === 'pa' ? f.sp_raw / 249.089                    // 1 in.wg = 249.089 Pa
			: f.sp_unit === 'mmaq' ? f.sp_raw / 25.4                          // 1 in.wg = 25.4 mmAq
			: f.sp_raw;
		return { cfm, sp, v: f.v, cfm_raw: f.cfm_raw, sp_raw: f.sp_raw, cfm_unit: f.cfm_unit, sp_unit: f.sp_unit, model: f.model };
	}

	// ส่วน UI ในผลลัพธ์: checkbox เลือกเปรียบเทียบ/ไม่เปรียบเทียบ + ฟอร์มกรอกค่าพัดลม + ตารางเปรียบเทียบ
	render_fan_section(res, sp) {
		const f = this.fan_sel;
		const opt = (v, cur, th) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${th}</option>`;
		return `
			<div class="mt-3" id="fan_compare_section">
				<div class="checkbox mb-2 fan-sel-form">
					<label class="mb-0">
						<input type="checkbox" id="fan_sel_enable" ${f.enabled ? 'checked' : ''}>
						<b>เปรียบเทียบพัดลมที่เลือก (Fan Selection)</b>
						<span class="text-muted small">— เทียบปริมาณลม / แรงดัน / ความเร็วลม กับค่าที่คำนวณได้</span>
					</label>
				</div>
				<div class="fan-sel-form" id="fan_sel_inputs" style="display:${f.enabled ? '' : 'none'};">
					<div class="row">
						<div class="col-sm-3 mb-2">
							<label class="small mb-1">รุ่นพัดลม (ถ้ามี)</label>
							<input type="text" class="form-control input-sm fan-sel-input" id="fan_sel_model"
								value="${frappe.utils.escape_html(f.model)}" placeholder="เช่น Kruger BSB 400">
						</div>
						<div class="col-sm-3 mb-2">
							<label class="small mb-1">ปริมาณลมของพัดลม</label>
							<div class="input-group input-group-sm">
								<input type="number" class="form-control fan-sel-input" id="fan_sel_cfm" value="${f.cfm_raw || 0}" min="0" step="10">
								<div class="input-group-append">
									<select class="form-control fan-sel-input" id="fan_sel_cfm_unit" style="max-width:95px;">
										${opt('cfm', f.cfm_unit, 'CFM')}${opt('cmh', f.cfm_unit, 'm³/h')}
									</select>
								</div>
							</div>
							<small class="text-muted">ที่จุดทำงานจากกราฟ/ตารางผู้ผลิต</small>
						</div>
						<div class="col-sm-3 mb-2">
							<label class="small mb-1">แรงดันสถิตของพัดลม</label>
							<div class="input-group input-group-sm">
								<input type="number" class="form-control fan-sel-input" id="fan_sel_sp" value="${f.sp_raw || 0}" min="0" step="0.05">
								<div class="input-group-append">
									<select class="form-control fan-sel-input" id="fan_sel_sp_unit" style="max-width:95px;">
										${opt('inwg', f.sp_unit, 'in.wg')}${opt('pa', f.sp_unit, 'Pa')}${opt('mmaq', f.sp_unit, 'mmAq')}
									</select>
								</div>
							</div>
							<small class="text-muted">แรงดันสถิตที่จุดทำงานเดียวกัน</small>
						</div>
						<div class="col-sm-3 mb-2">
							<label class="small mb-1">ความเร็วลมของพัดลม (m/s)</label>
							<input type="number" class="form-control input-sm fan-sel-input" id="fan_sel_v" value="${f.v || 0}" min="0" step="0.1">
							<small class="text-muted">เช่น Outlet Velocity จากสเปค</small>
						</div>
					</div>
				</div>
				<div id="fan_compare_out">${f.enabled ? this.render_fan_compare(res, sp) : ''}</div>
			</div>`;
	}

	// อ่านค่าจากฟอร์มในผลลัพธ์ลง state แล้ววาดตารางเปรียบเทียบใหม่ (ไม่ต้องคำนวณทั้งชุด)
	update_fan_compare() {
		const f = this.fan_sel;
		f.enabled = this.$body.find('#fan_sel_enable').is(':checked');
		f.model = (this.$body.find('#fan_sel_model').val() || '').trim();
		f.cfm_raw = this.num('fan_sel_cfm');
		f.cfm_unit = this.$body.find('#fan_sel_cfm_unit').val() || 'cfm';
		f.sp_raw = this.num('fan_sel_sp');
		f.sp_unit = this.$body.find('#fan_sel_sp_unit').val() || 'inwg';
		f.v = this.num('fan_sel_v');
		this.$body.find('#fan_sel_inputs').toggle(f.enabled);
		this.$body.find('#fan_compare_out').html(
			f.enabled && this.last_res && this.last_sp ? this.render_fan_compare(this.last_res, this.last_sp) : ''
		);
	}

	// สร้าง HTML ตารางเปรียบเทียบ ค่าคำนวณ vs พัดลมที่เลือก
	render_fan_compare(res, sp) {
		const fan = this.fan_selection_input();
		if (!fan) return '<div class="alert alert-secondary small py-2 fan-sel-form">กรอกค่าพัดลมอย่างน้อย 1 ช่อง (ปริมาณลม / แรงดัน / ความเร็วลม) เพื่อแสดงตารางเปรียบเทียบ</div>';

		const rows = [];
		const notes = [];
		const pct = (d) => `${d >= 0 ? '+' : '−'}${Math.abs(d * 100).toFixed(0)}%`;

		// 1) ปริมาณลม — พัดลมต้องให้ลม ≥ ค่าออกแบบ, เกิน ~25% ถือว่าโตเกิน
		if (fan.cfm > 0) {
			const need = res.design_cfm;
			const diff = need > 0 ? (fan.cfm - need) / need : 0;
			let status, cls;
			if (fan.cfm < need) {
				status = '❌ ลมไม่พอ'; cls = 'table-danger';
				notes.push(`ปริมาณลมพัดลมต่ำกว่าค่าออกแบบ ${Math.abs(diff * 100).toFixed(0)}% — ควรเลือกพัดลมที่ให้ ≥ ${Math.round(need).toLocaleString()} CFM ที่ ${sp.total.toFixed(2)} in.wg`);
			} else if (diff <= 0.25) {
				status = '✓ เหมาะสม'; cls = 'table-success';
			} else {
				status = '⚠️ เกินมาก'; cls = 'table-warning';
				notes.push(`ปริมาณลมเกินค่าออกแบบ ${(diff * 100).toFixed(0)}% — เปลืองพลังงาน/เสียงดัง พิจารณาลดรอบ (ปรับพูลเลย์/VSD) หรือเลือกรุ่นเล็กลง`);
			}
			const fan_txt = `${Math.round(fan.cfm).toLocaleString()} CFM`
				+ (fan.cfm_unit === 'cmh' ? ` <span class="small text-muted">(${Math.round(fan.cfm_raw).toLocaleString()} m³/h)</span>` : '');
			rows.push({ label: 'ปริมาณลม', need: `${Math.round(need).toLocaleString()} CFM`, fan: fan_txt, diff: pct(diff), status, cls });
		}

		// 2) แรงดันสถิต — พัดลมต้องมี SP ≥ ESP ที่คำนวณ, สูงเกิน ~50% ให้เตือนจุดทำงานเลื่อน
		if (fan.sp > 0) {
			const need = sp.total;
			const diff = need > 0 ? (fan.sp - need) / need : 0;
			let status, cls;
			if (fan.sp < need) {
				status = '❌ แรงดันไม่พอ'; cls = 'table-danger';
				notes.push('แรงดันสถิตของพัดลมต่ำกว่า ESP ที่คำนวณ — จุดทำงานจริงจะเลื่อน ทำให้ลมจริงต่ำกว่าค่าออกแบบ');
			} else if (need <= 0 || diff <= 0.5) {
				status = '✓ เพียงพอ'; cls = 'table-success';
			} else {
				status = '⚠️ สูงเกิน'; cls = 'table-warning';
				notes.push('แรงดันพัดลมสูงกว่า ESP มาก — จุดทำงานจริงจะเลื่อนไปทางลมเกิน/กินไฟเพิ่ม ควรหาจุดตัด system curve กับ fan curve จากกราฟผู้ผลิต');
			}
			const fan_txt = `${fan.sp.toFixed(2)} in.wg`
				+ (fan.sp_unit !== 'inwg' ? ` <span class="small text-muted">(${fan.sp_raw.toLocaleString()} ${fan.sp_unit === 'pa' ? 'Pa' : 'mmAq'})</span>` : '');
			rows.push({ label: 'แรงดันสถิต (ESP)', need: `${need.toFixed(2)} in.wg`, fan: fan_txt, diff: pct(diff), status, cls });
		}

		// 3) ความเร็วลม — เทียบกับความเร็วจริงในท่อ ±20% ถือว่าใกล้เคียง
		if (fan.v > 0) {
			const need = sp.v_ms;
			const diff = need > 0 ? (fan.v - need) / need : 0;
			let status, cls;
			if (Math.abs(diff) <= 0.2) {
				status = '✓ ใกล้เคียง'; cls = 'table-success';
			} else {
				status = '⚠️ ต่างมาก'; cls = 'table-warning';
				notes.push(`ความเร็วลมพัดลมต่างจากความเร็วจริงในท่อ ${pct(diff)} — ขนาดคอพัดลมกับท่อไม่เท่ากัน ควรมีข้อลด/ข้อขยาย (transition) ที่ค่อยเป็นค่อยไป และเผื่อ System Effect ตาม AMCA 201`);
			}
			rows.push({ label: 'ความเร็วลม', need: `${need.toFixed(1)} m/s`, fan: `${fan.v.toFixed(1)} m/s`, diff: pct(diff), status, cls });
		}

		if (!rows.length) return '';

		return `
			<h6 class="mt-2">ผลเปรียบเทียบพัดลมที่เลือก${fan.model ? ` — <span class="text-primary">${frappe.utils.escape_html(fan.model)}</span>` : ''}</h6>
			<table class="table table-sm table-bordered">
				<thead><tr>
					<th>รายการ</th>
					<th class="text-right">ค่าที่คำนวณ (ต้องการ)</th>
					<th class="text-right">พัดลมที่เลือก</th>
					<th class="text-right">ส่วนต่าง</th>
					<th class="text-center">ผลประเมิน</th>
				</tr></thead>
				<tbody>${rows.map(r => `
					<tr class="${r.cls}">
						<td>${r.label}</td>
						<td class="text-right">${r.need}</td>
						<td class="text-right">${r.fan}</td>
						<td class="text-right">${r.diff}</td>
						<td class="text-center">${r.status}</td>
					</tr>`).join('')}
				</tbody>
			</table>
			${notes.map(n => `<div class="alert alert-warning small py-2">⚠️ ${n}</div>`).join('')}
			<p class="small text-muted">หมายเหตุ: เป็นการเปรียบเทียบแบบจุดเดียว (single point) — จุดทำงานจริงต้องหาจากจุดตัดระหว่าง System Curve กับ Fan Curve บนกราฟสมรรถนะที่ทดสอบตาม AMCA 210</p>`;
	}



	/* ---------- แสดงผล ---------- */

	render_result(res, sp) {
		this.last_res = res; // เก็บไว้ให้ส่วนเปรียบเทียบพัดลมอัปเดตตารางได้โดยไม่ต้องคำนวณทั้งชุด
		this.last_sp = sp;
		const cmh = res.design_cfm * 1.699;
		const rows_cfm = res.rows.map(r =>
			`<tr><td>${r.label}</td><td class="text-right">${Math.round(r.cfm).toLocaleString()}</td></tr>`).join('');
		const rows_sp = sp.rows.map(r =>
			`<tr><td>${r.label}</td><td class="text-right">${r.sp.toFixed(2)}</td></tr>`).join('');

		const head = this.mode === 'room'
			? `${res.room.th} • ${res.room_w} × ${res.room_l} m (${res.area_m2.toFixed(1)} m²) • ${res.ach} ACH`
			: this.mode === 'duct'
				? `${res.room.th} • ${res.room_w} × ${res.room_l} m (${res.area_m2.toFixed(1)} m²) • ${res.dist.n_total} หัวดูด${res.dist.sides > 1 ? ` (${res.dist.sides} ด้าน)` : ''} • เครื่องดูดห่าง ${res.dist.fan_dist} m`
				: `${res.hood_th} • ${res.duty_th} • ${res.shape_th} ${res.dims_th}`;

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
			${res.makeup_cfm ? `<p class="small">ลมชดเชย (Makeup Air) ที่ ${res.makeup_pct}% ≈ <b>${Math.round(res.makeup_cfm).toLocaleString()} CFM</b></p>` : ''}
			${res.makeup_warn ? `<div class="alert alert-warning small py-2">${res.makeup_warn}</div>` : ''}

			${res.holes ? this.render_holes(res.holes) : ''}

			${res.dist ? this.render_duct_dist(res.dist) : ''}

			<h6 class="mt-3">ความดันสถิต (External Static Pressure)</h6>
			<table class="table table-sm table-bordered">
				<thead><tr><th>องค์ประกอบ</th><th class="text-right">in.wg</th></tr></thead>
				<tbody>${rows_sp}
					<tr class="font-weight-bold"><td>รวม ESP</td><td class="text-right">${sp.total.toFixed(2)}</td></tr>
				</tbody>
			</table>

			${this.render_fan_section(res, sp)}

			<div class="alert alert-info small mb-0 mt-3">
				<b>คำแนะนำพัดลม:</b> ${this.fan_recommendation(res.design_cfm, sp.total)}<br>
				เลือกพัดลมที่จุดทำงาน ${Math.round(res.design_cfm).toLocaleString()} CFM @ ${sp.total.toFixed(2)} in.wg
				จากกราฟสมรรถนะที่ทดสอบตาม <b>AMCA 210</b> (มีตรา AMCA Certified Ratings Seal)
			</div>
		</div>`);

		frappe.utils.scroll_to(this.$body.find('#hvac_result'));
	}
}
