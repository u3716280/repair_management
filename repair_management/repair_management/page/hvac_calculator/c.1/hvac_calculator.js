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
	{ id: 'parking',     th: 'ที่จอดรถในอาคาร (Enclosed Parking)', rp: 0,    ra: 0,    density: 0,   ach: [6, 10],  exhaust_ra: 0.75, ref: 'ASHRAE 62.1 Table 6-2 (0.75 cfm/ft²)' },
	{ id: 'laundry',     th: 'ห้องซักรีด (Laundry)',              rp: 0,    ra: 0,    density: 0,   ach: [10, 15], exhaust_ra: 0.50, ref: 'ASHRAE 62.1 Table 6-2' },
];

// อัตราดูดอากาศฮู้ดครัว (ฮู้ดไม่มี listing) — IMC 507.13 / ASHRAE 154
// หน่วย: CFM ต่อความยาวฮู้ด 1 ฟุต
const HOOD_RATES = {
	wall_canopy:   { th: 'ฮู้ดติดผนัง (Wall Canopy)',      light: 200, medium: 300, heavy: 400, extra: 550 },
	island_single: { th: 'ฮู้ดเกาะกลาง แถวเดียว (Island)',  light: 400, medium: 500, heavy: 600, extra: 700 },
	island_double: { th: 'ฮู้ดเกาะกลาง สองแถว (Double)',    light: 250, medium: 300, heavy: 400, extra: 550 },
	backshelf:     { th: 'ฮู้ดหลังเตา (Backshelf/Proximity)', light: 250, medium: 300, heavy: 400, extra: null },
	eyebrow:       { th: 'ฮู้ดคิ้ว (Eyebrow)',              light: 250, medium: 250, heavy: null, extra: null },
};

const DUTY_TH = {
	light: 'Light Duty (เตาอบ, เตานึ่ง)',
	medium: 'Medium Duty (เตาแก๊ส, เตาทอดตื้น)',
	heavy: 'Heavy Duty (เตาผัดไฟแรง, กระทะจีน, ชาร์บรอยล์)',
	extra: 'Extra-Heavy Duty (เตาถ่าน, ฟืน)',
};

// ค่าความดันสถิตองค์ประกอบ (in.wg) — ค่าออกแบบทั่วไป
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
		this.switch_mode('room');
	}

	template() {
		return `
		<div class="hvac-calc" style="max-width: 980px; margin: 0 auto;">
			<div class="frappe-card p-4 mb-4">
				<div class="btn-group w-100 mb-2" role="group">
					<button type="button" class="btn btn-primary hvac-mode" data-mode="room">คำนวณจากพื้นที่ห้อง</button>
					<button type="button" class="btn btn-default hvac-mode" data-mode="hood">คำนวณจากขนาดฝาชี (Hood)</button>
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
					<div class="col-sm-3 mb-3">
						<label>พื้นที่ห้อง (m²)</label>
						<input type="number" class="form-control" id="room_area" value="50" min="1">
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
				<small class="text-muted">อัตราดูดคิดจาก CFM ต่อความยาวฮู้ด (ฟุต) ตาม IMC 507.13 / ASHRAE 154 สำหรับฮู้ดไม่มี UL listing — ฮู้ดที่มี listing ให้ใช้ค่าจากผู้ผลิต</small>
			</div>

			<!-- ความดันสถิต -->
			<div class="frappe-card p-4 mb-4">
				<h5 class="mb-3">ประเมินความดันสถิต (External Static Pressure)</h5>
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
						<label>ความเร็วลมในท่อ (fpm)</label>
						<input type="number" class="form-control" id="duct_velocity" value="1600" step="100" min="600">
						<small class="text-muted">ครัว ≥1500 fpm (IMC), ทั่วไป 1000–1200</small>
					</div>
					<div class="col-sm-3 mb-3">
						<label>อัตราเสียดทาน (in.wg/100ft)</label>
						<input type="number" class="form-control" id="friction_rate" value="0.12" step="0.01" min="0.02">
						<small class="text-muted">ทั่วไป 0.08–0.10, ครัว 0.12–0.20</small>
					</div>
				</div>
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
	}

	switch_mode(mode) {
		this.mode = mode;
		this.$body.find('.hvac-mode').removeClass('btn-primary').addClass('btn-default');
		this.$body.find(`.hvac-mode[data-mode="${mode}"]`).removeClass('btn-default').addClass('btn-primary');
		this.$body.find('#panel-room').toggle(mode === 'room');
		this.$body.find('#panel-hood').toggle(mode === 'hood');
		this.$body.find('#hvac_result').empty();
	}

	render_room_options() {
		const $sel = this.$body.find('#room_type');
		ROOM_TYPES.forEach(r => $sel.append(`<option value="${r.id}">${r.th}</option>`));
		this.update_room_hint();
	}

	update_room_hint() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#room_type').val());
		if (!r) return;
		this.$body.find('#room_ref').text(r.ref);
		this.$body.find('#ach_hint').text(`ช่วงแนะนำ ${r.ach[0]}–${r.ach[1]} ACH`);
		this.$body.find('#room_ach').val(((r.ach[0] + r.ach[1]) / 2).toFixed(1));
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
		const res = this.mode === 'room' ? this.calc_room() : this.calc_hood();
		if (!res) return;
		const sp = this.calc_sp(res.design_cfm);
		this.render_result(res, sp);
	}

	calc_room() {
		const r = ROOM_TYPES.find(x => x.id === this.$body.find('#room_type').val());
		const area_m2 = this.num('room_area');
		const height_m = this.num('room_height');
		const ach = this.num('room_ach');
		if (area_m2 <= 0) { frappe.msgprint(__('กรุณากรอกพื้นที่ห้อง')); return null; }

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

		const design_cfm = Math.max(cfm_ach, cfm_621, cfm_exhaust);

		return {
			mode_th: 'จากพื้นที่ห้อง',
			room: r, area_m2, area_ft2, volume_ft3, ach, people,
			rows: [
				{ label: `วิธี ACH (${ach} ACH × ${Math.round(volume_ft3).toLocaleString()} ft³ ÷ 60)`, cfm: cfm_ach },
				{ label: `วิธี ASHRAE 62.1 (${people} คน × ${r.rp} + ${Math.round(area_ft2)} ft² × ${r.ra})`, cfm: cfm_621 },
				...(cfm_exhaust ? [{ label: `Exhaust ขั้นต่ำ ASHRAE 62.1 Table 6-2 (${exhaust_note})`, cfm: cfm_exhaust }] : []),
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
			design_note: 'ใช้ค่ามากที่สุด + จัดลมชดเชย (Makeup Air) ~80% ของลมดูด',
		};
	}

	calc_sp(cfm) {
		const len_ft = this.num('duct_length') * M_TO_FT;
		const elbows = this.num('duct_elbows');
		const velocity = this.num('duct_velocity');
		const friction = this.num('friction_rate');
		const is_hood = this.mode === 'hood';

		const sp_duct = (len_ft / 100) * friction;
		const sp_fittings = elbows * SP_COMPONENTS.fitting_each;
		const sp_entry = is_hood ? SP_COMPONENTS.hood_entry + SP_COMPONENTS.filter_dirty_allow : SP_COMPONENTS.grille;
		const sp_cap = SP_COMPONENTS.exhaust_cap;

		const subtotal = sp_duct + sp_fittings + sp_entry + sp_cap;
		const safety = subtotal * 0.15; // เผื่อ System Effect ตาม AMCA 201
		const total = subtotal + safety;

		// ขนาดท่อแนะนำ
		const area_ft2 = cfm / velocity;
		const dia_in = Math.sqrt(4 * area_ft2 / Math.PI) * 12;

		return {
			rows: [
				{ label: is_hood ? `ฮู้ด + ฟิลเตอร์ (สะอาด+เผื่อสกปรก)` : 'หน้ากากดูด/จ่าย', sp: sp_entry },
				{ label: `แรงเสียดทานท่อ (${(len_ft).toFixed(0)} ft × ${friction}/100ft)`, sp: sp_duct },
				{ label: `ข้องอ 90° × ${elbows} จุด`, sp: sp_fittings },
				{ label: 'หัวปล่อยทิ้ง/Exhaust cap', sp: sp_cap },
				{ label: 'เผื่อ System Effect 15% (AMCA 201)', sp: safety },
			],
			total, velocity, dia_in,
		};
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
			? `${res.room.th} • ${res.area_m2} m² • ${res.ach} ACH`
			: `${res.hood_th} • ${res.duty_th} • ${res.L_m}×${res.W_m} m`;

		this.$body.find('#hvac_result').html(`
		<div class="frappe-card p-4 mb-4">
			<h5>ผลการคำนวณ — ${res.mode_th}</h5>
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
					<div class="h3 mb-0 text-primary">Ø ${sp.dia_in.toFixed(0)}"</div>
					<div class="text-muted">ท่อกลมแนะนำ</div>
					<div class="small text-muted">ที่ ${sp.velocity.toLocaleString()} fpm</div>
				</div>
			</div>

			<h6>ปริมาณลม (เปรียบเทียบแต่ละวิธี)</h6>
			<table class="table table-sm table-bordered">
				<thead><tr><th>วิธีคำนวณ</th><th class="text-right">CFM</th></tr></thead>
				<tbody>${rows_cfm}
					<tr class="font-weight-bold"><td>ค่าออกแบบ (${res.design_note})</td>
					<td class="text-right">${Math.round(res.design_cfm).toLocaleString()}</td></tr>
				</tbody>
			</table>
			${res.makeup_cfm ? `<p class="small">ลมชดเชย (Makeup Air) แนะนำ ≈ <b>${Math.round(res.makeup_cfm).toLocaleString()} CFM</b></p>` : ''}

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
