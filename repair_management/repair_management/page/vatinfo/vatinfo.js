frappe.pages["vatinfo"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "VATinfo",
		single_column: true,
	});

	new VatInfoPage(page);
};

const VATINFO_SEARCH = "repair_management.rd_vat.search";
const VATINFO_SYNC = "repair_management.rd_vat.sync";
const VATINFO_PARTY = "repair_management.rd_vat.party";
const VATINFO_SOAP = "repair_management.repair_management.page.vatinfo.vatinfo";
const VATINFO_RD_URL = "https://vsinter.rd.go.th/rd-webcontent-web/#/vatsearch";
const VATINFO_UPLOAD_CHUNK = 8 * 1024 * 1024;
const VATINFO_BRANCH_LABEL = "เลขที่สาขา (เว้นว่าง = ทุกสาขา, 00000 = สำนักงานใหญ่)";
const VATINFO_DATASETS = {
	Bangkok: "กรุงเทพมหานคร",
	"Other Provinces": "ทุกจังหวัดยกเว้นกรุงเทพมหานคร",
};
const VATINFO_LOG_STATUS = {
	Running: ["กำลังนำเข้า", "blue"],
	Success: ["สำเร็จ", "green"],
	"Needs Review": ["ต้องตรวจสอบ", "orange"],
	Failed: ["ไม่สำเร็จ", "red"],
	Skipped: ["ไม่เปลี่ยนแปลง", "gray"],
};

const vatinfo_esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
const vatinfo_num = (value) => Number(value || 0).toLocaleString("en-US");
const vatinfo_tin = (tin) =>
	/^[0-9]{13}$/.test(tin || "")
		? `${tin[0]}-${tin.slice(1, 5)}-${tin.slice(5, 10)}-${tin.slice(10, 12)}-${tin[12]}`
		: tin || "";

// Gregorian ISO date from the server, shown in the Buddhist Era as the RD site does.
function vatinfo_be_date(value) {
	const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
	return match ? `${match[3]}/${match[2]}/${Number(match[1]) + 543}` : "";
}

class VatInfoPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);
		this.request_id = 0;
		this.current_page = 1;
		this.status_timer = null;

		this.render();
		this.bind();
		this.load_status();
		this.load_options(this.$province);
	}

	render() {
		this.wrapper.html(`
			<div class="vatinfo-tabs" role="tablist" aria-label="VATinfo" hidden>
				<button type="button" class="vatinfo-tab" role="tab" id="vatinfo-tab-search" aria-controls="vatinfo-panel-search" aria-selected="true" data-tab="search">ค้นหาข้อมูล</button>
				<button type="button" class="vatinfo-tab" role="tab" id="vatinfo-tab-import" aria-controls="vatinfo-panel-import" aria-selected="false" tabindex="-1" data-tab="import">นำเข้าและอัปเดตข้อมูล</button>
			</div>

			<div class="vatinfo-panel" role="tabpanel" id="vatinfo-panel-search" aria-labelledby="vatinfo-tab-search">
				<form class="vatinfo-card vatinfo-form" novalidate>
					<h5 class="vatinfo-heading">ระบบค้นหาข้อมูลผู้ประกอบการจดทะเบียนภาษีมูลค่าเพิ่ม</h5>

					<div class="vatinfo-mode" role="radiogroup" aria-label="ค้นหาจาก">
						<label><input type="radio" name="vatinfo-mode" value="tin" checked> เลขประจำตัวผู้เสียภาษีอากร</label>
						<label><input type="radio" name="vatinfo-mode" value="name"> ชื่อผู้ประกอบการ</label>
					</div>

					<div class="vatinfo-fields" data-mode="tin">
						<div class="vatinfo-wide">
							<label for="vatinfo-tin">เลขประจำตัวผู้เสียภาษีอากร (13 หลัก)</label>
							<input id="vatinfo-tin" class="form-control" inputmode="numeric" maxlength="17" autocomplete="off">
						</div>
						<div>
							<label for="vatinfo-tin-branch">${VATINFO_BRANCH_LABEL}</label>
							<input id="vatinfo-tin-branch" class="form-control" inputmode="numeric" maxlength="5" autocomplete="off">
						</div>
					</div>

					<div data-mode="name" hidden>
						<div class="vatinfo-fields">
							<div class="vatinfo-wide">
								<label for="vatinfo-name">ชื่อ (อย่างน้อย 3 ตัวอักษร เช่น เอกไทย)</label>
								<input id="vatinfo-name" class="form-control" maxlength="200" autocomplete="off">
							</div>
							<div>
								<label for="vatinfo-scope">ค้นหาใน</label>
								<select id="vatinfo-scope" class="form-control">
									<option value="all">ทั้งสองชื่อ</option>
									<option value="taxpayer_name">ชื่อผู้ประกอบการ</option>
									<option value="establishment_name">ชื่อสถานประกอบการ</option>
								</select>
							</div>
						</div>
						<details class="vatinfo-more">
							<summary>กรองเพิ่มเติม (จังหวัด อำเภอ ตำบล สาขา)</summary>
							<div class="vatinfo-fields">
								<div>
									<label for="vatinfo-province">จังหวัด</label>
									<select id="vatinfo-province" class="form-control"><option value="">ทั้งหมด</option></select>
								</div>
								<div>
									<label for="vatinfo-district">อำเภอ / เขต</label>
									<select id="vatinfo-district" class="form-control" disabled><option value="">ทั้งหมด</option></select>
								</div>
								<div>
									<label for="vatinfo-subdistrict">ตำบล / แขวง</label>
									<select id="vatinfo-subdistrict" class="form-control" disabled><option value="">ทั้งหมด</option></select>
								</div>
								<div>
									<label for="vatinfo-branch">${VATINFO_BRANCH_LABEL}</label>
									<input id="vatinfo-branch" class="form-control" inputmode="numeric" maxlength="5" autocomplete="off">
								</div>
							</div>
						</details>
					</div>

					<div class="vatinfo-actions">
						<button type="submit" class="btn btn-primary btn-sm vatinfo-search">ค้นหาข้อมูล</button>
						<button type="button" class="btn btn-default btn-sm vatinfo-clear">ล้างข้อความ</button>
					</div>
					<div class="vatinfo-banner"></div>
				</form>
				<div class="vatinfo-card vatinfo-results" aria-live="polite" hidden></div>
			</div>

			<div class="vatinfo-panel" role="tabpanel" id="vatinfo-panel-import" aria-labelledby="vatinfo-tab-import" hidden>
				<div class="vatinfo-admin"></div>
			</div>
		`);

		this.$tabs = this.wrapper.find(".vatinfo-tabs");
		this.$banner = this.wrapper.find(".vatinfo-banner");
		this.$form = this.wrapper.find(".vatinfo-form");
		this.$results = this.wrapper.find(".vatinfo-results");
		this.$admin = this.wrapper.find(".vatinfo-admin");
		this.$search = this.wrapper.find(".vatinfo-search");
		this.$tin = this.wrapper.find("#vatinfo-tin");
		this.$tin_branch = this.wrapper.find("#vatinfo-tin-branch");
		this.$name = this.wrapper.find("#vatinfo-name");
		this.$scope = this.wrapper.find("#vatinfo-scope");
		this.$branch = this.wrapper.find("#vatinfo-branch");
		this.$province = this.wrapper.find("#vatinfo-province");
		this.$district = this.wrapper.find("#vatinfo-district");
		this.$subdistrict = this.wrapper.find("#vatinfo-subdistrict");
		this.mode = "tin";
		this.sort = "name";
		this.page_length = 20;
	}

	bind() {
		this.$form.on("submit", (e) => {
			e.preventDefault();
			this.current_page = 1;
			this.search();
		});
		this.wrapper.find(".vatinfo-clear").on("click", () => this.clear());
		this.wrapper
			.find('input[name="vatinfo-mode"]')
			.on("change", (e) => this.set_mode(e.target.value));
		this.$tabs.on("click", ".vatinfo-tab", (e) => this.set_tab(e.currentTarget.dataset.tab));
		this.$tabs.on("keydown", ".vatinfo-tab", (e) => {
			if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
			e.preventDefault();
			const next = e.currentTarget.dataset.tab === "search" ? "import" : "search";
			this.set_tab(next);
			this.$tabs.find(`[data-tab="${next}"]`).trigger("focus");
		});
		this.$province.on("change", () => {
			this.reset_select(this.$subdistrict);
			if (this.$province.val()) {
				this.load_options(this.$district, { province: this.$province.val() });
			} else {
				this.reset_select(this.$district);
			}
		});
		this.$district.on("change", () => {
			if (this.$district.val()) {
				this.load_options(this.$subdistrict, {
					province: this.$province.val(),
					district: this.$district.val(),
				});
			} else {
				this.reset_select(this.$subdistrict);
			}
		});
		this.$results.on("click", ".vatinfo-row", (e) => {
			this.open_detail($(e.currentTarget).data("index"));
		});
		this.$results.on("keydown", ".vatinfo-row", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				this.open_detail($(e.currentTarget).data("index"));
			}
		});
		this.$results.on("click", ".vatinfo-prev", () => this.go_to_page(this.current_page - 1));
		this.$results.on("click", ".vatinfo-next", () => this.go_to_page(this.current_page + 1));
		this.$results.on("change", ".vatinfo-sort", (e) => {
			this.sort = e.target.value;
			this.go_to_page(1);
		});
		this.$results.on("change", ".vatinfo-page-length", (e) => {
			this.page_length = Number(e.target.value);
			this.go_to_page(1);
		});
	}

	set_tab(tab) {
		this.$tabs.find(".vatinfo-tab").each(function () {
			const active = this.dataset.tab === tab;
			this.setAttribute("aria-selected", active ? "true" : "false");
			this.tabIndex = active ? 0 : -1;
		});
		this.wrapper.find("#vatinfo-panel-search").prop("hidden", tab !== "search");
		this.wrapper.find("#vatinfo-panel-import").prop("hidden", tab !== "import");
	}

	set_mode(mode) {
		this.mode = mode;
		this.$form.find("[data-mode]").each(function () {
			this.hidden = this.dataset.mode !== mode;
		});
		this.reset_results();
		(mode === "tin" ? this.$tin : this.$name).trigger("focus");
	}

	reset_select($select) {
		$select.html('<option value="">ทั้งหมด</option>').prop("disabled", true);
	}

	load_options($select, args = {}) {
		frappe.call({
			method: `${VATINFO_SEARCH}.get_locations`,
			args,
			callback: (r) => {
				const options = (r.message || []).map(
					(value) =>
						`<option value="${vatinfo_esc(value)}">${vatinfo_esc(value)}</option>`
				);
				$select
					.html(`<option value="">ทั้งหมด</option>${options.join("")}`)
					.prop("disabled", false);
			},
		});
	}

	reset_results() {
		this.request_id++;
		this.$search.prop("disabled", false);
		this.$results.empty().prop("hidden", true);
	}

	clear() {
		this.$tin.val("");
		this.$tin_branch.val("");
		this.$name.val("");
		this.$scope.val("all");
		this.$branch.val("");
		this.$province.val("");
		this.reset_select(this.$district);
		this.reset_select(this.$subdistrict);
		this.reset_results();
		(this.mode === "tin" ? this.$tin : this.$name).trigger("focus");
	}

	go_to_page(page) {
		this.current_page = Math.max(page, 1);
		this.search();
	}

	is_valid_tin(tin) {
		if (!/^[0-9]{13}$/.test(tin)) return false;
		let total = 0;
		for (let i = 0; i < 12; i++) total += Number(tin[i]) * (13 - i);
		return (11 - (total % 11)) % 10 === Number(tin[12]);
	}

	reject(message) {
		frappe.msgprint({ title: "ข้อความปฏิเสธ", indicator: "red", message });
		return null;
	}

	// Same rules and wording as the RD site.
	search_args() {
		if (this.mode === "tin") {
			const tin = this.$tin.val().replace(/[-\s]/g, "");
			const branch = this.$tin_branch.val().trim();
			if (!tin) return this.reject("กรุณาระบุเลขประจำตัวผู้เสียภาษีอากร (13 หลัก)");
			if (tin.length !== 13) {
				return this.reject(
					"กรอกข้อมูลไม่ครบถ้วน กรุณาระบุเลขประจำตัวผู้เสียภาษีอากรให้ครบ 13 หลัก"
				);
			}
			if (!this.is_valid_tin(tin)) {
				return this.reject(
					"เลขประจำตัวผู้เสียภาษีอากร (13 หลัก) ที่บันทึกไม่ถูกต้องตามหลักเกณฑ์ กรุณาตรวจสอบหรือทำรายการใหม่"
				);
			}
			if (branch && (!/^[0-9]+$/.test(branch) || Number(branch) > 99998)) {
				return this.reject("เลขที่สาขา จะต้องเป็นตัวเลขและมีค่าไม่เกินเลขสาขาที่ 99998");
			}
			return { query: tin, search_by: "tax_id", branch };
		}

		const name = this.$name.val().trim();
		const province = this.$province.val();
		if (!name && !province) return this.reject("กรุณาระบุข้อมูลชื่อผู้ประกอบการ");
		if (name && name.replace(/\s/g, "").length < 3) {
			return this.reject("กรุณากรอกตัวอักษร 3 ตัวอักษรขึ้นไปจึงจะสามารถทำการค้นหาได้");
		}
		return {
			query: name,
			search_by: this.$scope.val(),
			province,
			district: this.$district.val(),
			subdistrict: this.$subdistrict.val(),
			branch: this.$branch.val().trim(),
		};
	}

	search() {
		const args = this.search_args();
		if (!args) return;

		const request_id = ++this.request_id;
		this.$search.prop("disabled", true);
		this.show_message("กำลังค้นหาข้อมูล...");

		frappe.call({
			method: `${VATINFO_SEARCH}.search`,
			args: {
				...args,
				sort: this.sort,
				page: this.current_page,
				page_length: this.page_length,
			},
			callback: (r) => {
				if (request_id !== this.request_id) return;
				this.$search.prop("disabled", false);
				this.show_result(r.message || {});
			},
			error: () => {
				if (request_id !== this.request_id) return;
				this.$search.prop("disabled", false);
				this.$results.empty().prop("hidden", true);
			},
		});
	}

	rd_link() {
		return `<a href="${VATINFO_RD_URL}" target="_blank" rel="noopener noreferrer">เว็บไซต์กรมสรรพากร</a>`;
	}

	show_result(data) {
		this.rows = data.rows || [];
		if (data.source === "online") return this.show_online_result(data);

		if (data.status === "timeout") {
			return this.show_message(
				"การค้นหาใช้เวลานานเกินไป กรุณาลองใหม่ หรือเลือกจังหวัดในตัวกรองเพิ่มเติมเพื่อให้ค้นหาได้เร็วขึ้น"
			);
		}
		if (data.status === "error") {
			return this.show_message("ค้นหาไม่สำเร็จ กรุณาลองใหม่อีกครั้ง");
		}
		if (!this.rows.length) {
			return this.show_message(
				`ไม่พบข้อมูลในฐานข้อมูล ลองใช้คำที่สั้นลง หรือตรวจสอบที่${this.rd_link()}`
			);
		}
		this.show_rows(data);
	}

	show_online_result(data) {
		const offline = data.offline_failed
			? "ค้นหาในฐานข้อมูลไม่สำเร็จ"
			: "ไม่พบเลขนี้ในฐานข้อมูล";
		if (data.status === "ok") {
			const ignored = data.filters_ignored
				? " (ไม่ได้ใช้ตัวกรองพื้นที่กับการค้นหาออนไลน์)"
				: "";
			return this.show_rows(
				data,
				`${offline} ผลลัพธ์นี้เป็นข้อมูลออนไลน์จากกรมสรรพากร${ignored}`
			);
		}
		const detail =
			{
				not_found: vatinfo_esc(data.message || "กรมสรรพากรไม่พบข้อมูลนี้"),
				empty: "กรมสรรพากรไม่ส่งผลลัพธ์กลับมา",
				unavailable: "ไม่สามารถเชื่อมต่อบริการของกรมสรรพากรได้ในขณะนี้",
			}[data.status] || "ไม่สามารถตรวจสอบกับกรมสรรพากรได้";
		this.show_message(`${offline} และ${detail} ตรวจสอบเพิ่มเติมได้ที่${this.rd_link()}`);
	}

	show_rows(data, note = "") {
		const first = (data.page - 1) * data.page_length + 1;
		const body = this.rows
			.map((row, index) => {
				const missing =
					row.source === "offline" && !row.in_latest_dataset
						? '<div class="vatinfo-sub"><span class="indicator-pill orange">ไม่พบในชุดข้อมูลล่าสุด</span></div>'
						: "";
				const establishment =
					row.establishment_name && row.establishment_name !== row.taxpayer_name
						? `<div class="vatinfo-sub">${vatinfo_esc(row.establishment_name)}</div>`
						: "";
				return `
					<tr class="vatinfo-row" data-index="${index}" tabindex="0">
						<td class="vatinfo-nowrap">${vatinfo_num(first + index)}</td>
						<td class="vatinfo-nowrap">${vatinfo_esc(vatinfo_tin(row.tax_id))}</td>
						<td class="vatinfo-nowrap">${vatinfo_esc(row.branch_label)}</td>
						<td>${vatinfo_esc(row.taxpayer_name)}${establishment}${missing}</td>
						<td>${vatinfo_esc(row.address)}</td>
						<td class="vatinfo-nowrap">${vatinfo_esc(row.registered_date)}</td>
					</tr>`;
			})
			.join("");

		const total = data.capped ? `มากกว่า ${vatinfo_num(data.total)}` : vatinfo_num(data.total);
		const last = first + this.rows.length - 1;
		const has_next = data.capped || last < data.total;
		const is_online = data.source === "online";
		const pager =
			is_online || (data.page === 1 && !has_next)
				? ""
				: `<div class="vatinfo-pager">
				<button type="button" class="btn btn-default btn-xs vatinfo-prev" ${
					data.page > 1 ? "" : "disabled"
				}>ก่อนหน้า</button>
				<span>หน้า ${vatinfo_num(data.page)}</span>
				<button type="button" class="btn btn-default btn-xs vatinfo-next" ${
					has_next ? "" : "disabled"
				}>ถัดไป</button>
			</div>`;
		const sort_options = [
			["name", "ชื่อ"],
			["tax_id", "เลขประจำตัวผู้เสียภาษี"],
			["province", "จังหวัด"],
		]
			.map(
				([value, label]) =>
					`<option value="${value}" ${
						this.sort === value ? "selected" : ""
					}>${label}</option>`
			)
			.join("");
		const length_options = [20, 50, 100]
			.map(
				(value) =>
					`<option ${this.page_length === value ? "selected" : ""}>${value}</option>`
			)
			.join("");
		const controls =
			is_online || this.mode === "tin"
				? ""
				: `<span class="vatinfo-result-controls">
				<label for="vatinfo-sort">เรียงตาม</label>
				<select id="vatinfo-sort" class="form-control input-xs vatinfo-sort">${sort_options}</select>
				<label for="vatinfo-page-length">ต่อหน้า</label>
				<select id="vatinfo-page-length" class="form-control input-xs vatinfo-page-length">${length_options}</select>
			</span>`;

		this.$results
			.html(
				`
				${note ? `<div class="vatinfo-note">${vatinfo_esc(note)}</div>` : ""}
				<div class="vatinfo-count">
					<span>พบ ${total} รายการ แสดงรายการที่ ${vatinfo_num(first)}-${vatinfo_num(
					last
				)} · คลิกรายการเพื่อดูรายละเอียด</span>
					${controls}
				</div>
				<div class="vatinfo-table-wrap">
					<table class="table table-bordered vatinfo-table">
						<thead>
							<tr>
								<th>ลำดับ</th>
								<th>เลขประจำตัวผู้เสียภาษีอากร</th>
								<th>สาขา</th>
								<th>ชื่อผู้ประกอบการ / ชื่อสถานประกอบการ</th>
								<th>ที่อยู่</th>
								<th>วันที่จดทะเบียน</th>
							</tr>
						</thead>
						<tbody>${body}</tbody>
					</table>
				</div>
				${pager}
			`
			)
			.prop("hidden", false);
	}

	show_message(html) {
		this.$results.html(`<div>${html}</div>`).prop("hidden", false);
	}

	// -----------------------------------------------------------------------
	// Detail
	// -----------------------------------------------------------------------

	open_detail(index) {
		const row = this.rows[index];
		if (!row) return;

		const items = [
			["เลขประจำตัวผู้เสียภาษี", vatinfo_tin(row.tax_id)],
			["สาขา", row.branch_label],
			["ชื่อผู้ประกอบการ", row.taxpayer_name],
			["ชื่อสถานประกอบการ", row.establishment_name],
			["ชื่ออาคาร", row.building_name],
			["ห้อง", row.room_no],
			["ชั้น", row.floor_no],
			["หมู่บ้าน", row.village],
			["บ้านเลขที่", row.house_no],
			["หมู่", row.moo],
			["ซอย", row.soi],
			["แยก", row.yaek],
			["ถนน", row.road],
			["ตำบล/แขวง", row.subdistrict],
			["อำเภอ/เขต", row.district],
			["จังหวัด", row.province],
			["รหัสไปรษณีย์", row.postcode],
			["วันที่ได้รับอนุมัติจดทะเบียน VAT", row.registered_date],
		];
		if (row.source === "offline") {
			items.push(
				["แหล่งข้อมูล", VATINFO_DATASETS[row.source_dataset] || row.source_dataset],
				["วันที่ของไฟล์ต้นทาง", vatinfo_be_date(row.source_file_date)],
				["วันที่นำเข้า", vatinfo_be_date(row.imported_on)],
				["ชุดข้อมูลล่าสุดที่พบ", row.last_seen_import]
			);
		} else {
			items.push(["แหล่งข้อมูล", "ข้อมูลออนไลน์จากกรมสรรพากร (ไม่ได้บันทึก)"]);
		}

		const list = items
			.filter(([, value]) => value)
			.map(
				([label, value]) => `<dt>${vatinfo_esc(label)}</dt><dd>${vatinfo_esc(value)}</dd>`
			)
			.join("");

		let notes = "";
		if (row.source === "offline" && !row.in_latest_dataset) {
			notes += `<div class="vatinfo-note">ไม่พบรายการนี้ในชุดข้อมูลล่าสุดตั้งแต่ ${vatinfo_esc(
				vatinfo_be_date(row.missing_since)
			)} ซึ่งไม่ได้หมายความว่าถูกยกเลิกทะเบียน VAT</div>`;
		}
		if (row.data_incomplete) {
			notes += '<div class="vatinfo-note">ข้อมูลรายการนี้ในไฟล์ต้นทางไม่ครบถ้วน</div>';
		}

		const dialog = new frappe.ui.Dialog({
			title: row.taxpayer_name || vatinfo_tin(row.tax_id),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
			primary_action_label: "ใช้กับ Customer",
			primary_action: () => {
				dialog.hide();
				this.open_party("Customer", row);
			},
			secondary_action_label: "ใช้กับ Supplier",
			secondary_action: () => {
				dialog.hide();
				this.open_party("Supplier", row);
			},
		});
		const live_button =
			row.source === "offline"
				? `<div class="vatinfo-actions vatinfo-compare">
				<button type="button" class="btn btn-default btn-sm vatinfo-live">ตรวจสอบกับกรมสรรพากร</button>
				<span class="vatinfo-live-result"></span>
			</div>`
				: "";
		const $body = dialog.fields_dict.body.$wrapper;
		$body.html(`${notes}<dl class="vatinfo-detail">${list}</dl>${live_button}`);
		$body
			.find(".vatinfo-live")
			.on("click", (e) => this.live_check(row, $body, e.currentTarget));
		dialog.show();
	}

	live_check(row, $body, button) {
		const $result = $body.find(".vatinfo-live-result");
		button.disabled = true;
		$result.text("กำลังตรวจสอบ...");
		frappe.call({
			method: `${VATINFO_SOAP}.live_lookup`,
			args: { tax_id: row.tax_id, branch: row.branch_number },
			callback: (r) => {
				button.disabled = false;
				const data = r.message || {};
				const live = (data.rows || [])[0];
				if (data.status === "ok" && live) {
					const same =
						live.address === row.address && live.taxpayer_name === row.taxpayer_name;
					$result.text(
						same
							? "กรมสรรพากรพบข้อมูล และตรงกับข้อมูลในระบบ"
							: `กรมสรรพากรพบข้อมูล แต่แตกต่างจากในระบบ: ${live.taxpayer_name} ${live.address}`
					);
				} else if (data.status === "not_found") {
					$result.text(data.message || "กรมสรรพากรไม่พบข้อมูลนี้");
				} else {
					$result.text("ไม่สามารถตรวจสอบกับกรมสรรพากรได้ในขณะนี้");
				}
			},
			error: () => {
				button.disabled = false;
				$result.text("");
			},
		});
	}

	// -----------------------------------------------------------------------
	// Customer / Supplier
	// -----------------------------------------------------------------------

	source_args(row) {
		return row.source === "online"
			? { online: 1, tax_id: row.tax_id, branch: row.branch_number }
			: { online: 0, key: row.key };
	}

	open_party(party_type, row) {
		frappe.call({
			method: `${VATINFO_PARTY}.get_preview`,
			args: { party_type, ...this.source_args(row) },
			freeze: true,
			callback: (r) => new VatInfoPartyDialog(party_type, this.source_args(row), r.message),
		});
	}

	// -----------------------------------------------------------------------
	// Status and admin
	// -----------------------------------------------------------------------

	load_status() {
		frappe.call({
			method: `${VATINFO_SEARCH}.get_status`,
			callback: (r) => {
				const status = r.message || {};
				this.render_banner(status);
				if (status.is_admin) this.render_admin(status);
				this.schedule_status(status);
			},
		});
	}

	schedule_status(status) {
		clearTimeout(this.status_timer);
		if (!status.running) return;
		this.status_timer = setTimeout(() => {
			if (frappe.get_route()[0] === "vatinfo") {
				this.load_status();
			} else {
				this.schedule_status(status);
			}
		}, 5000);
	}

	render_banner(status) {
		const datasets = (status.datasets || [])
			.map((item) => {
				const label = vatinfo_esc(VATINFO_DATASETS[item.dataset] || item.dataset);
				return item.file_date
					? `${label} ณ ${vatinfo_esc(vatinfo_be_date(item.file_date))}`
					: `${label} ยังไม่มีข้อมูล`;
			})
			.join(" · ");
		this.$banner.html(
			`ข้อมูล: ${datasets}. เฉพาะผู้ประกอบการที่ยังประกอบกิจการอยู่ ณ วันที่ของไฟล์ ถ้าไม่พบเลขประจำตัวผู้เสียภาษี ระบบจะตรวจสอบกับกรมสรรพากรออนไลน์ให้`
		);
	}

	render_admin(status) {
		if (!this.admin_ready) {
			this.admin_ready = true;
			this.$tabs.prop("hidden", false);
			this.$admin.html(`
				<section class="vatinfo-card">
					<h5 class="vatinfo-heading">ข้อมูลในระบบ</h5>
					<div class="vatinfo-datasets"></div>
				</section>

				<section class="vatinfo-card">
					<h5 class="vatinfo-heading">อัปเดตจากกรมสรรพากร</h5>
					<p class="vatinfo-help">ตรวจสอบและดาวน์โหลดไฟล์ทั้งสองชุด แล้วนำเข้าในเบื้องหลัง ไฟล์ที่ไม่เปลี่ยนแปลงจะไม่ถูกนำเข้าซ้ำ</p>
					<div class="vatinfo-actions">
						<button type="button" class="btn btn-primary btn-sm vatinfo-update">ดาวน์โหลดและนำเข้าอัตโนมัติ</button>
						<label class="vatinfo-check"><input type="checkbox" class="vatinfo-force"> นำเข้าซ้ำแม้ไฟล์ไม่เปลี่ยนแปลง</label>
					</div>
					<p class="vatinfo-help vatinfo-auto"></p>
				</section>

				<section class="vatinfo-card">
					<h5 class="vatinfo-heading">อัปโหลด CSV ด้วยตนเอง</h5>
					<div class="vatinfo-fields">
						<div>
							<label for="vatinfo-upload-dataset">ชุดข้อมูล</label>
							<select id="vatinfo-upload-dataset" class="form-control">
								<option value="Bangkok">${VATINFO_DATASETS.Bangkok}</option>
								<option value="Other Provinces">${VATINFO_DATASETS["Other Provinces"]}</option>
							</select>
						</div>
						<div>
							<label for="vatinfo-upload-date">วันที่ของข้อมูลในไฟล์</label>
							<input id="vatinfo-upload-date" type="date" class="form-control">
						</div>
						<div class="vatinfo-wide">
							<label for="vatinfo-upload-file">ไฟล์ CSV</label>
							<input id="vatinfo-upload-file" type="file" accept=".csv,text/csv" class="form-control">
						</div>
					</div>
					<div class="vatinfo-actions">
						<button type="button" class="btn btn-default btn-sm vatinfo-upload">อัปโหลดและนำเข้า</button>
						<span class="vatinfo-upload-progress" aria-live="polite"></span>
					</div>
				</section>

				<section class="vatinfo-card">
					<div class="vatinfo-section-head">
						<h5 class="vatinfo-heading">ประวัติการนำเข้าล่าสุด</h5>
						<span class="vatinfo-actions">
							<a class="btn btn-default btn-xs" href="/app/rd-vat-import-log">ประวัติทั้งหมด</a>
							<a class="btn btn-default btn-xs" href="/app/rd-vat-import-settings">ตั้งค่า</a>
						</span>
					</div>
					<div class="vatinfo-table-wrap vatinfo-logs"></div>
				</section>
			`);
			this.$admin.find(".vatinfo-update").on("click", () => this.trigger_update());
			this.$admin.find(".vatinfo-upload").on("click", () => this.upload());
		}

		this.$admin.find(".vatinfo-update, .vatinfo-upload").prop("disabled", !!status.running);
		this.$admin
			.find(".vatinfo-auto")
			.text(
				status.running
					? "กำลังนำเข้าข้อมูล ทำงานอื่นหรือปิดหน้านี้ได้"
					: status.auto_update
					? "อัปเดตอัตโนมัติ: เปิด ทุกวันที่ 1 ของเดือน เวลา 02:00 น."
					: "อัปเดตอัตโนมัติ: ปิด"
			);
		this.render_datasets(status.datasets || []);
		this.render_logs(status.logs || []);
	}

	render_datasets(datasets) {
		const rows = datasets
			.map(
				(item) => `
				<tr>
					<td>${vatinfo_esc(VATINFO_DATASETS[item.dataset] || item.dataset)}</td>
					<td class="vatinfo-nowrap">${
						item.file_date
							? vatinfo_esc(vatinfo_be_date(item.file_date))
							: "ยังไม่ได้นำเข้า"
					}</td>
					<td class="vatinfo-nowrap">${item.file_date ? vatinfo_num(item.valid_rows) : ""}</td>
					<td class="vatinfo-nowrap">${
						item.finished_at
							? `${vatinfo_esc(vatinfo_be_date(item.finished_at))} ${vatinfo_esc(
									String(item.finished_at).slice(11, 16)
							  )}`
							: ""
					}</td>
				</tr>`
			)
			.join("");
		this.$admin.find(".vatinfo-datasets").html(`
			<div class="vatinfo-table-wrap">
				<table class="table table-bordered vatinfo-table">
					<thead><tr><th>ชุดข้อมูล</th><th>วันที่ของไฟล์</th><th>รายการ</th><th>นำเข้าเมื่อ</th></tr></thead>
					<tbody>${rows}</tbody>
				</table>
			</div>
		`);
	}

	render_logs(logs) {
		const body = logs
			.map((log) => {
				const [label, color] = VATINFO_LOG_STATUS[log.status] || [log.status, "gray"];
				const progress =
					log.status === "Running" && log.total_rows
						? ` ${vatinfo_num(log.processed_rows)}/${vatinfo_num(log.total_rows)}`
						: "";
				const message = log.message
					? `<div class="vatinfo-sub">${vatinfo_esc(log.message)}</div>`
					: "";
				return `
					<tr>
						<td class="vatinfo-nowrap"><a href="/app/rd-vat-import-log/${encodeURIComponent(
							log.name
						)}">${vatinfo_esc(vatinfo_be_date(log.started_at))} ${vatinfo_esc(
					(log.started_at || "").slice(11, 16)
				)}</a></td>
						<td>${vatinfo_esc(VATINFO_DATASETS[log.dataset] || log.dataset)}${message}</td>
						<td class="vatinfo-nowrap"><span class="indicator-pill ${color}">${vatinfo_esc(
					label
				)}${vatinfo_esc(progress)}</span></td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.total_rows)}</td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.rows_new)}</td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.rows_updated)}</td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.rows_unchanged)}</td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.rows_superseded)}</td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.rows_missing)}</td>
						<td class="vatinfo-nowrap">${vatinfo_num(log.rows_error)}</td>
					</tr>`;
			})
			.join("");
		this.$admin.find(".vatinfo-logs").html(
			logs.length
				? `<table class="table table-bordered vatinfo-table">
					<thead><tr>
						<th>เวลา</th><th>ชุดข้อมูล</th><th>สถานะ</th><th>ทั้งหมด</th><th>ใหม่</th>
						<th>ปรับปรุง</th><th>ไม่เปลี่ยน</th><th>มีข้อมูลใหม่กว่า</th><th>ไม่พบ</th><th>ผิดพลาด</th>
					</tr></thead>
					<tbody>${body}</tbody>
				</table>`
				: "<div>ยังไม่มีประวัติการนำเข้า</div>"
		);
	}

	trigger_update() {
		frappe.call({
			method: `${VATINFO_SYNC}.trigger_update`,
			args: { force: this.$admin.find(".vatinfo-force").prop("checked") ? 1 : 0 },
			callback: (r) => {
				frappe.show_alert({
					message:
						r.message && r.message.started
							? "เริ่มดาวน์โหลดและนำเข้าแล้ว ทำงานต่อได้เลย"
							: "กำลังมีการนำเข้าข้อมูลอยู่",
					indicator: "blue",
				});
				this.load_status();
			},
		});
	}

	async upload() {
		const file = this.$admin.find("#vatinfo-upload-file")[0].files[0];
		const file_date = this.$admin.find("#vatinfo-upload-date").val();
		const $progress = this.$admin.find(".vatinfo-upload-progress");
		const $button = this.$admin.find(".vatinfo-upload");

		if (!file) return frappe.msgprint("กรุณาเลือกไฟล์ CSV");
		if (!file_date) return frappe.msgprint("กรุณาระบุวันที่ของข้อมูลในไฟล์");

		$button.prop("disabled", true);
		try {
			const started = await frappe.xcall(`${VATINFO_SYNC}.start_upload`, {
				dataset: this.$admin.find("#vatinfo-upload-dataset").val(),
				file_name: file.name,
				file_date,
				size: file.size,
			});
			for (let offset = 0; offset < file.size; offset += VATINFO_UPLOAD_CHUNK) {
				await this.send_chunk(
					started.upload_id,
					offset,
					file.slice(offset, offset + VATINFO_UPLOAD_CHUNK)
				);
				const sent = Math.min(offset + VATINFO_UPLOAD_CHUNK, file.size);
				$progress.text(`กำลังอัปโหลด ${Math.floor((sent / file.size) * 100)}%`);
			}
			await frappe.xcall(`${VATINFO_SYNC}.finish_upload`, {
				upload_id: started.upload_id,
				force: this.$admin.find(".vatinfo-force").prop("checked") ? 1 : 0,
			});
			$progress.text("อัปโหลดสำเร็จ กำลังนำเข้าในเบื้องหลัง");
			this.load_status();
		} catch (e) {
			$progress.text(
				e.message && e.message.startsWith("อัปโหลด")
					? e.message
					: "อัปโหลดไม่สำเร็จ กรุณาเริ่มใหม่"
			);
			$button.prop("disabled", false);
		}
	}

	async send_chunk(upload_id, offset, blob) {
		const form = new FormData();
		form.append("upload_id", upload_id);
		form.append("offset", offset);
		form.append("chunk", blob, "chunk");
		const response = await fetch(`/api/method/${VATINFO_SYNC}.upload_chunk`, {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token, Accept: "application/json" },
			body: form,
		});
		if (!response.ok) throw new Error("อัปโหลดไม่สำเร็จ กรุณาเริ่มใหม่");
	}
}

// Read-only preview first. Nothing is written until the user confirms.
class VatInfoPartyDialog {
	constructor(party_type, source_args, preview) {
		this.party_type = party_type;
		this.source_args = source_args;
		this.preview = preview;
		this.dialog = new frappe.ui.Dialog({
			title: `ใช้ข้อมูลกับ ${party_type}`,
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
			primary_action_label: "ตรวจสอบและยืนยัน",
			primary_action: () => this.confirm(),
		});
		this.$body = this.dialog.fields_dict.body.$wrapper;
		this.render();
		this.dialog.show();
	}

	render() {
		const { preview } = this;
		const source = preview.source;
		const can_any = preview.can_create || preview.matches.some((match) => match.can_write);

		const warnings = [];
		if (preview.matches.length > 1) {
			warnings.push(
				`เลขประจำตัวผู้เสียภาษีนี้มี ${this.party_type} อยู่แล้ว ${preview.matches.length} รายการ กรุณาเลือกให้ถูกต้อง`
			);
		}
		if (preview.same_name.length) {
			const names = preview.same_name.map((row) => row.name).join(", ");
			warnings.push(
				`มี ${this.party_type} ชื่อเดียวกันแต่เลขประจำตัวผู้เสียภาษีต่างกันหรือไม่มี: ${names}`
			);
		}
		if (!can_any) warnings.push(`คุณไม่มีสิทธิ์สร้างหรือแก้ไข ${this.party_type}`);

		const create_option = preview.can_create
			? `<label class="vatinfo-party-option">
				<input type="radio" name="vatinfo-target" value="" ${preview.matches.length ? "" : "checked"}>
				สร้าง ${vatinfo_esc(this.party_type)} ใหม่
			</label>`
			: "";
		const match_options = preview.matches
			.map(
				(match, index) => `
				<label class="vatinfo-party-option">
					<input type="radio" name="vatinfo-target" value="${vatinfo_esc(match.name)}" ${
					match.can_write ? "" : "disabled"
				} ${index === 0 && match.can_write ? "checked" : ""}>
					อัปเดต ${vatinfo_esc(match.name)} (${vatinfo_esc(match.party_name)})${
					match.disabled ? " (ปิดใช้งาน)" : ""
				}${match.can_write ? "" : " (ไม่มีสิทธิ์แก้ไข)"}
				</label>`
			)
			.join("");

		this.$body.html(`
			${warnings.map((text) => `<div class="vatinfo-note">${vatinfo_esc(text)}</div>`).join("")}
			<dl class="vatinfo-detail vatinfo-compare">
				<dt>ข้อมูลจากกรมสรรพากร</dt><dd>${vatinfo_esc(source.taxpayer_name)}</dd>
				<dt>เลขประจำตัวผู้เสียภาษี</dt><dd>${vatinfo_esc(vatinfo_tin(source.tax_id))} (${vatinfo_esc(
			source.branch_label
		)})</dd>
				<dt>ที่อยู่</dt><dd>${vatinfo_esc(preview.address_text)}</dd>
			</dl>
			${create_option}${match_options}
			<div class="vatinfo-create-options vatinfo-compare"></div>
			<div class="vatinfo-party-compare"></div>
			<div class="vatinfo-address-options"></div>
		`);
		this.$body.on("change", 'input[name="vatinfo-target"]', () => this.render_target());
		this.$body.on("change", 'input[name="vatinfo-address"]', () =>
			this.render_address_compare()
		);
		this.render_target();
		if (!can_any) this.dialog.get_primary_btn().prop("disabled", true);
	}

	selected_target() {
		return this.$body.find('input[name="vatinfo-target"]:checked').val();
	}

	selected_match() {
		const target = this.selected_target();
		return this.preview.matches.find((match) => match.name === target);
	}

	compare_table(rows, css_class) {
		const body = rows
			.map(
				(row) => `
				<tr>
					<td><input type="checkbox" class="${css_class}" value="${vatinfo_esc(
					row.field
				)}" aria-label="${vatinfo_esc(row.label)}" ${row.differs ? "" : "disabled"}></td>
					<td>${vatinfo_esc(row.label)}</td>
					<td>${vatinfo_esc(row.current)}</td>
					<td class="${row.differs ? "vatinfo-differs" : ""}">${vatinfo_esc(row.proposed)}</td>
				</tr>`
			)
			.join("");
		return `<div class="vatinfo-table-wrap vatinfo-compare">
			<table class="table table-bordered vatinfo-table">
				<thead><tr><th>ใช้</th><th>ฟิลด์</th><th>ค่าปัจจุบัน</th><th>ข้อมูลกรมสรรพากร</th></tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>`;
	}

	render_target() {
		const match = this.selected_match();
		const $create = this.$body.find(".vatinfo-create-options");
		const $compare = this.$body.find(".vatinfo-party-compare");

		if (match) {
			$create.empty();
			$compare.html(
				`<h6>เลือกฟิลด์ที่ต้องการอัปเดต</h6>${this.compare_table(
					match.compare,
					"vatinfo-party-field"
				)}`
			);
		} else {
			const options = this.preview.groups
				.map(
					(group) =>
						`<option ${
							group === this.preview.default_group ? "selected" : ""
						}>${vatinfo_esc(group)}</option>`
				)
				.join("");
			$create.html(`
				<label for="vatinfo-group">${
					this.party_type === "Customer" ? "Customer Group" : "Supplier Group"
				}</label>
				<select id="vatinfo-group" class="form-control">${options}</select>
			`);
			$compare.empty();
		}
		this.render_address_options();
	}

	render_address_options() {
		const match = this.selected_match();
		const addresses = match ? match.addresses : [];
		const duplicate = addresses.find((address) => address.is_duplicate);
		const can_create = this.preview.can_create_address;
		const default_action = duplicate || !can_create ? "none" : "create";
		const updates = addresses
			.map(
				(address) => `
				<label class="vatinfo-party-option">
					<input type="radio" name="vatinfo-address" value="${vatinfo_esc(address.name)}" ${
					address.can_write ? "" : "disabled"
				}>
					อัปเดต ${vatinfo_esc(address.name)}${address.is_duplicate ? " (น่าจะเป็นที่อยู่เดียวกัน)" : ""}
				</label>`
			)
			.join("");
		this.$body.find(".vatinfo-address-options").html(`
			<h6>ที่อยู่</h6>
			${
				duplicate
					? `<div class="vatinfo-note">พบที่อยู่ที่น่าจะซ้ำ: ${vatinfo_esc(
							duplicate.name
					  )}</div>`
					: ""
			}
			<label class="vatinfo-party-option"><input type="radio" name="vatinfo-address" value="__none" ${
				default_action === "none" ? "checked" : ""
			}> ไม่ต้องจัดการที่อยู่</label>
			<label class="vatinfo-party-option"><input type="radio" name="vatinfo-address" value="__create" ${
				default_action === "create" ? "checked" : ""
			} ${can_create ? "" : "disabled"}> สร้างที่อยู่ใหม่</label>
			${updates}
			<div class="vatinfo-address-compare"></div>
		`);
		this.render_address_compare();
	}

	render_address_compare() {
		const selected = this.$body.find('input[name="vatinfo-address"]:checked').val();
		const match = this.selected_match();
		const address = match && match.addresses.find((item) => item.name === selected);
		this.$body
			.find(".vatinfo-address-compare")
			.html(address ? this.compare_table(address.compare, "vatinfo-address-field") : "");
	}

	checked_values(css_class) {
		return this.$body
			.find(`.${css_class}:checked`)
			.map((_, input) => input.value)
			.get();
	}

	confirm() {
		const match = this.selected_match();
		const has_target = this.$body.find('input[name="vatinfo-target"]:checked').length > 0;
		if (!has_target) return frappe.msgprint("กรุณาเลือกการดำเนินการ");

		const address_choice = this.$body.find('input[name="vatinfo-address"]:checked').val();
		const args = {
			party_type: this.party_type,
			...this.source_args,
			action: match ? "update" : "create",
			target: match ? match.name : "",
			fields: JSON.stringify(this.checked_values("vatinfo-party-field")),
			group: this.$body.find("#vatinfo-group").val() || "",
			address_action:
				address_choice === "__none"
					? "none"
					: address_choice === "__create"
					? "create"
					: "update",
			address_target:
				address_choice && !address_choice.startsWith("__") ? address_choice : "",
			address_fields: JSON.stringify(this.checked_values("vatinfo-address-field")),
			confirmed: 1,
		};

		const nothing_to_do =
			match &&
			!JSON.parse(args.fields).length &&
			(args.address_action === "none" ||
				(args.address_action === "update" && !JSON.parse(args.address_fields).length));
		if (nothing_to_do)
			return frappe.msgprint("กรุณาเลือกอย่างน้อยหนึ่งรายการที่ต้องการอัปเดต");

		const party = match
			? `อัปเดต ${match.name}`
			: `สร้าง ${this.party_type} ใหม่: ${this.preview.proposed.party_name}`;
		const address = {
			none: "ไม่แก้ไขที่อยู่",
			create: "สร้างที่อยู่ใหม่",
			update: `อัปเดตที่อยู่ ${args.address_target}`,
		}[args.address_action];

		frappe.confirm(
			`${vatinfo_esc(party)}<br>${vatinfo_esc(address)}<br><br>ยืนยันการบันทึกหรือไม่?`,
			() => {
				frappe.call({
					method: `${VATINFO_PARTY}.apply`,
					args,
					freeze: true,
					callback: (r) => {
						const result = r.message || {};
						this.dialog.hide();
						frappe.show_alert({ message: "บันทึกเรียบร้อย", indicator: "green" });
						frappe.set_route("Form", this.party_type, result.party);
					},
				});
			}
		);
	}
}
