// Inventory Reorder Analysis - Frappe Page SPA
const API = "repair_management.repair_management.inventory.reorder.api";

const STATUS_COLORS = {
	Critical: "red-600",
	Reorder: "orange-500",
	Review: "yellow-700",
	OK: "green-600",
	"No History": "gray-500",
};
const CONFIDENCE_COLORS = { High: "green-600", Medium: "yellow-700", Low: "red-600" };
const RELIABILITY_COLORS = { RELIABLE: "green-600", LATE: "red-600" };
const ALL_STATUSES = ["Critical", "Reorder", "Review", "OK", "No History"];

frappe.pages["inventory-reorder-analysis"].on_page_load = function (wrapper) {
	new InventoryReorderAnalysis(wrapper);
};

class InventoryReorderAnalysis {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Inventory Reorder Analysis",
			single_column: true,
		});

		this.make_primary_filters();
		this.make_advanced_filters();
		this.make_planning_parameters();
		this.make_summary_area();
		this.make_table_area();
		this.set_defaults();
	}

	make_control(row, column_class, df) {
		const parent = $(`<div class="${column_class}"></div>`).appendTo(row);
		return frappe.ui.form.make_control({ parent, df, render_input: true });
	}

	make_primary_filters() {
		const row1 = $('<div class="row" style="margin-bottom: 10px;"></div>').appendTo(this.page.body);
		const row2 = $('<div class="row" style="margin-bottom: 15px;"></div>').appendTo(this.page.body);

		this.company_field = this.make_control(row1, "col-md-3", {
			fieldtype: "Link",
			options: "Company",
			fieldname: "company",
			label: "Company",
			reqd: 1,
		});
		this.warehouse_field = this.make_control(row1, "col-md-3", {
			fieldtype: "Link",
			options: "Warehouse",
			fieldname: "warehouse",
			label: "Warehouse",
			reqd: 1,
		});
		this.analysis_period_field = this.make_control(row1, "col-md-2", {
			fieldtype: "Int",
			fieldname: "analysis_period",
			label: "Analysis Period (Months)",
			min: 1,
		});
		this.item_group_field = this.make_control(row1, "col-md-2", {
			fieldtype: "Link",
			options: "Item Group",
			fieldname: "item_group",
			label: "Item Group",
		});
		this.item_field = this.make_control(row1, "col-md-2", {
			fieldtype: "Link",
			options: "Item",
			fieldname: "item_code",
			label: "Item",
		});

		this.status_checks = {};
		const status_wrapper = $('<div class="col-md-8"></div>').appendTo(row2);
		$('<label style="display:block; margin-bottom: 4px;">Status</label>').appendTo(status_wrapper);
		const status_row = $("<div></div>").appendTo(status_wrapper);
		ALL_STATUSES.forEach((status) => {
			const wrap = $(
				`<label class="checkbox-inline" style="margin-right: 12px; font-weight: normal;">
					<input type="checkbox" value="${status}"> ${status}
				</label>`
			).appendTo(status_row);
			this.status_checks[status] = wrap.find("input");
		});

		const col_btn = $('<div class="col-md-1" style="padding-top: 22px;"></div>').appendTo(row2);
		const col_export = $('<div class="col-md-2" style="padding-top: 22px;"></div>').appendTo(row2);
		const col_explain = $('<div class="col-md-1" style="padding-top: 22px;"></div>').appendTo(row2);

		this.analyze_btn = $('<button class="btn btn-primary btn-sm">Analyze</button>').appendTo(col_btn);
		this.analyze_btn.on("click", () => this.analyze());

		this.export_btn = $('<button class="btn btn-default btn-sm">Export CSV</button>').appendTo(col_export);
		this.export_btn.on("click", () => this.export_csv());
		this.export_btn.hide();

		this.explain_btn = $('<button class="btn btn-default btn-sm" title="What do these columns mean?">? Explain</button>').appendTo(
			col_explain
		);
		this.explain_btn.on("click", () => this.open_explanation_dialog());
	}

	make_collapsible_section(label, description) {
		const toggle = $(
			`<div style="margin-bottom: 8px; cursor: pointer; color: var(--text-muted); font-size: 12px;">▸ ${label}</div>`
		).appendTo(this.page.body);
		let description_el = null;
		if (description) {
			description_el = $(
				`<div style="margin-bottom: 8px; font-size: 12px; color: var(--text-muted); display:none;">${description}</div>`
			).appendTo(this.page.body);
		}
		const row = $('<div class="row" style="margin-bottom: 15px; display:none;"></div>').appendTo(this.page.body);

		let expanded = false;
		toggle.on("click", () => {
			expanded = !expanded;
			row.slideToggle();
			if (description_el) description_el.slideToggle();
			toggle.text((expanded ? "▾ " : "▸ ") + label);
		});
		return row;
	}

	make_advanced_filters() {
		const row = this.make_collapsible_section("Advanced Filters");

		this.supplier_field = this.make_control(row, "col-md-3", {
			fieldtype: "Link",
			options: "Supplier",
			fieldname: "supplier",
			label: "Supplier",
		});
		this.demand_type_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "demand_type",
			label: "Demand Type",
			options: "\nRegular\nIntermittent\nSlow\nNo History",
		});
		this.confidence_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "confidence",
			label: "Confidence",
			options: "\nHigh\nMedium\nLow",
		});
	}

	make_planning_parameters() {
		const row = this.make_collapsible_section(
			"Planning Parameters",
			"These override the calculation itself — unlike the filters above, which only control what's displayed."
		);

		this.planning_lead_time_field = this.make_control(row, "col-md-3", {
			fieldtype: "Int",
			fieldname: "planning_lead_time",
			label: "Planning Lead Time (Days)",
			min: 0,
			description: "Leave blank to use each item's own Lead Time (Days) from the Item master (falling back to 120 days for items with none set). Fill in a number to force that lead time for every item in this analysis instead.",
		});
		this.review_period_field = this.make_control(row, "col-md-3", {
			fieldtype: "Int",
			fieldname: "review_period",
			label: "Review Period (Days)",
			min: 0,
		});
		this.extra_coverage_field = this.make_control(row, "col-md-3", {
			fieldtype: "Int",
			fieldname: "extra_coverage",
			label: "Extra / Economic Coverage (Days)",
			min: 0,
		});
		this.service_level_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "service_level",
			label: "Service Level",
			options: "Auto\nP80\nP90\nP95\nP99",
		});
	}

	make_summary_area() {
		this.summary_area = $('<div style="margin-bottom: 10px;"></div>').appendTo(this.page.body);
	}

	make_table_area() {
		this.table_wrapper = $('<div style="overflow-x: auto;"></div>').appendTo(this.page.body);
		this.table_wrapper.on("click", ".dt-cell", (e) => {
			const cell = e.target.closest(".dt-cell");
			if (!cell) return;
			const row_index = Number(cell.dataset.rowIndex);
			if (Number.isInteger(row_index) && this.current_data && this.current_data[row_index]) {
				this.open_drill_down(this.current_data[row_index]);
			}
		});
	}

	set_defaults() {
		this.company_field.set_value(frappe.defaults.get_default("company"));
		this.analysis_period_field.set_value(24);
		// Left blank on purpose: an empty Planning Lead Time tells the backend
		// to use each item's own Item.lead_time_days (falling back to 120 only
		// for items with none set), rather than forcing one uniform value.
		this.review_period_field.set_value(1);
		this.extra_coverage_field.set_value(30);
		this.service_level_field.set_value("Auto");
		["Critical", "Reorder", "Review"].forEach((status) => this.status_checks[status].prop("checked", true));
	}

	get_selected_statuses() {
		return Object.keys(this.status_checks).filter((status) => this.status_checks[status].prop("checked"));
	}

	fmt(value) {
		if (value === null || value === undefined) return "N/A";
		const num = Number(value);
		if (Number.isNaN(num)) return frappe.utils.escape_html(String(value));
		return (Math.round(num * 100) / 100).toString();
	}

	badge(value, colors) {
		const color = colors[value] || "gray-500";
		return `<span style="color: var(--${color}); font-weight: 600;">${frappe.utils.escape_html(value)}</span>`;
	}

	analyze() {
		const company = this.company_field.get_value();
		const warehouse = this.warehouse_field.get_value();
		if (!company || !warehouse) {
			frappe.msgprint("Company and Warehouse are required");
			return;
		}

		const statuses = this.get_selected_statuses();
		this.last_params = {
			company,
			warehouse,
			item_group: this.item_group_field.get_value() || null,
			item_code: this.item_field.get_value() || null,
			supplier: this.supplier_field.get_value() || null,
			demand_type: this.demand_type_field.get_value() || null,
			status: statuses.length ? statuses.join(",") : null,
			confidence: this.confidence_field.get_value() || null,
			analysis_period: Number(this.analysis_period_field.get_value() || 24),
			// blank -> null: let the backend fall back to each item's own
			// configured lead time instead of forcing one value on everything
			planning_lead_time: this.planning_lead_time_field.get_value()
				? Number(this.planning_lead_time_field.get_value())
				: null,
			review_period: Number(this.review_period_field.get_value() || 1),
			extra_coverage: Number(this.extra_coverage_field.get_value() || 30),
			service_level: this.service_level_field.get_value() || "Auto",
		};

		frappe.dom.freeze("Analyzing...");
		frappe
			.call({ method: `${API}.get_reorder_analysis`, args: this.last_params })
			.then((r) => {
				frappe.dom.unfreeze();
				this.render_table(r.message || []);
			})
			.catch(() => {
				frappe.dom.unfreeze();
			});
	}

	render_table(data) {
		this.current_data = data;
		if (!data.length) {
			this.summary_area.html("No items matched the selected filters.");
			this.table_wrapper.empty();
			this.datatable = null;
			this.export_btn.hide();
			return;
		}

		const counts = {};
		ALL_STATUSES.forEach((status) => {
			counts[status] = data.filter((d) => d.status === status).length;
		});
		this.summary_area.html(
			`Items Analyzed: ${data.length} &nbsp;|&nbsp; ` +
				ALL_STATUSES.map(
					(status) =>
						`<span style="color: var(--${STATUS_COLORS[status]}); font-weight: 600; margin-right: 14px;">${status}: ${counts[status]}</span>`
				).join("")
		);

		const columns = [
			{
				name: "Item",
				editable: false,
				width: 220,
				sortable: false,
				// frappe-datatable stringifies non-primitive cell content before
				// calling format() as `value` -- the untouched raw row is only
				// available via the 4th ("data") argument, so compound-object
				// columns must read from there instead of `value`.
				format: (value, row, column, data) => {
					const v = data[0];
					return (
						`<a href="/app/item/${encodeURIComponent(v.item_code)}" target="_blank">${frappe.utils.escape_html(v.item_code)}</a>` +
						`<br><span style="color: var(--text-muted); font-size: 11px;">${frappe.utils.escape_html(v.item_name || "")}</span>`
					);
				},
			},
			{
				name: "Demand",
				editable: false,
				width: 150,
				sortable: false,
				format: (value, row, column, data) => {
					const v = data[1];
					return `${frappe.utils.escape_html(v.type)} · ${v.events} events`;
				},
			},
			{
				name: "Lead Time",
				editable: false,
				width: 130,
				sortable: false,
				format: (value, row, column, data) => {
					const v = data[2];
					return `${v.planning}d (cfg ${v.configured}d)`;
				},
			},
			{ name: "ROP", editable: false, width: 90, format: (value) => this.fmt(value) },
			{ name: "Stock", editable: false, width: 90, format: (value) => this.fmt(value) },
			{ name: "Reserved", editable: false, width: 90, format: (value) => this.fmt(value) },
			{
				name: "Incoming",
				editable: false,
				width: 160,
				sortable: false,
				format: (value, row, column, data) => {
					const v = data[6];
					return `${this.fmt(v.reliable)} reliable / ${this.fmt(v.late)} late`;
				},
			},
			{ name: "Position", editable: false, width: 90, format: (value) => this.fmt(value) },
			{ name: "Target", editable: false, width: 90, format: (value) => this.fmt(value) },
			{ name: "Recommend", editable: false, width: 100, format: (value) => this.fmt(value) },
			{
				name: "Status",
				editable: false,
				width: 110,
				sortable: false,
				format: (value) => this.badge(value, STATUS_COLORS),
			},
			{
				name: "Confidence",
				editable: false,
				width: 100,
				sortable: false,
				format: (value) => this.badge(value, CONFIDENCE_COLORS),
			},
		];

		const rows = data.map((d) => [
			{ item_code: d.item_code, item_name: d.item_name },
			{ type: d.demand_type, events: d.demand_events },
			{ planning: d.planning_lead_time, configured: d.configured_lead_time },
			d.reorder_point,
			d.actual_qty,
			d.reserved_qty,
			{ reliable: d.reliable_incoming, late: d.late_incoming },
			d.planning_position,
			d.target_stock,
			d.recommended_qty,
			d.status,
			d.confidence,
		]);

		if (!this.datatable) {
			this.table_wrapper.empty();
			this.datatable = new frappe.DataTable(this.table_wrapper.get(0), {
				columns,
				data: rows,
				layout: "fixed",
				serialNoColumn: true,
				checkboxColumn: false,
			});
		} else {
			this.datatable.refresh(rows, columns);
		}
		this.export_btn.show();
	}

	export_csv() {
		if (!this.current_data?.length) return;

		const header = [
			"Item Code", "Item Name", "Warehouse", "Demand Type", "Demand Events",
			"Planning Lead Time", "Configured Lead Time", "ROP", "Actual Qty", "Reserved Qty",
			"Reliable Incoming", "Late Incoming", "Planning Position", "Target Stock",
			"Recommended Qty", "Status", "Confidence",
		];

		const lines = [header.map((value) => this.csv_escape(value)).join(",")];
		this.current_data.forEach((d) => {
			lines.push(
				[
					d.item_code, d.item_name, d.warehouse, d.demand_type, d.demand_events,
					d.planning_lead_time, d.configured_lead_time, d.reorder_point, d.actual_qty,
					d.reserved_qty, d.reliable_incoming, d.late_incoming, d.planning_position,
					d.target_stock, d.recommended_qty, d.status, d.confidence,
				]
					.map((value) => this.csv_escape(value))
					.join(",")
			);
		});

		const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
		const link = document.createElement("a");
		const object_url = URL.createObjectURL(blob);
		link.href = object_url;
		link.download = `inventory_reorder_analysis_${frappe.datetime.get_today()}.csv`;
		link.click();
		URL.revokeObjectURL(object_url);
	}

	csv_escape(value) {
		const text = value === null || value === undefined ? "" : String(value);
		return `"${text.replace(/"/g, '""')}"`;
	}

	// ---- explanation ------------------------------------------------------

	open_explanation_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: "คำอธิบายความหมายของแต่ละค่า",
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
		});
		dialog.fields_dict.body.$wrapper.html(this.explanation_content());
		dialog.show();
	}

	explanation_content() {
		const section = (title, body) =>
			`<div style="margin-bottom: 18px;"><h6 style="margin-bottom: 8px;">${title}</h6>${body}</div>`;

		const status = section(
			"สถานะ (Status)",
			`<table class="table table-condensed"><tbody>
				<tr><td>${this.badge("Critical", STATUS_COLORS)}</td>
					<td>ตำแหน่งวางแผนสต็อก (สต็อกจริง + ของเข้าที่เชื่อถือได้ − ของที่จองไว้) น้อยกว่าหรือเท่ากับ 0 — ถือว่าของหมดแล้ว</td></tr>
				<tr><td>${this.badge("No History", STATUS_COLORS)}</td>
					<td>ไม่พบการเบิกใช้ในช่วงเวลาที่วิเคราะห์ จึงยังไม่มีข้อมูลพอที่จะบอกได้ว่าต้องสั่งซื้อหรือไม่</td></tr>
				<tr><td>${this.badge("Review", STATUS_COLORS)}</td>
					<td>ความเชื่อมั่นของตัวเลขอยู่ในระดับต่ำ (ดูหัวข้อ "ความเชื่อมั่น" ด้านล่าง) — ควรตรวจสอบด้วยตัวเองก่อนนำไปใช้จริง</td></tr>
				<tr><td>${this.badge("Reorder", STATUS_COLORS)}</td>
					<td>ตำแหน่งวางแผนสต็อกต่ำกว่าหรือเท่ากับจุดสั่งซื้อ (ROP) — ถึงเวลาสั่งซื้อตามจำนวนที่แนะนำ</td></tr>
				<tr><td>${this.badge("OK", STATUS_COLORS)}</td>
					<td>ตำแหน่งวางแผนสต็อกสูงกว่าจุดสั่งซื้อ — ยังไม่ต้องดำเนินการอะไรตอนนี้</td></tr>
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				ระบบตรวจตามลำดับนี้ — เงื่อนไขแรกที่ตรงจะถูกใช้ก่อนเสมอ เช่น สินค้าที่สต็อกหมด (Critical) จะแสดงเป็น
				Critical เสมอ แม้จะมีประวัติการใช้งานน้อยเกินไปด้วยก็ตาม
			</div>`
		);

		const lead_time = section(
			"เวลานำ (Lead Time)",
			`<div>
				คอลัมน์ "Lead Time" แสดงจำนวนวันที่ใช้จริงในการคำนวณ (Planning) เทียบกับค่าที่ตั้งไว้ใน Item (cfg)
			</div>
			<div style="color: var(--text-muted); font-size: 12px;">
				ถ้าไม่ได้กรอกช่อง "Planning Lead Time" ใน Planning Parameters ระบบจะใช้ค่า Lead Time (Days) ของ
				แต่ละสินค้าเองเป็นค่าเริ่มต้นก่อน และจะใช้ค่ากลาง 120 วัน เฉพาะสินค้าที่ยังไม่ได้ตั้งค่านี้ไว้เท่านั้น
				หากกรอกตัวเลขในช่องนั้น ระบบจะบังคับใช้ค่าเดียวกันกับทุกสินค้าในการวิเคราะห์ครั้งนี้แทน
			</div>`
		);

		const demand_type = section(
			"ประเภทความต้องการ (Demand Type)",
			`<table class="table table-condensed"><tbody>
				<tr><td><b>No History</b></td><td>ไม่มีการเบิกใช้เลยในช่วงเวลาที่วิเคราะห์</td></tr>
				<tr><td><b>Slow</b></td><td>มีการเบิกใช้น้อยกว่า 5 ครั้งในช่วงเวลาที่วิเคราะห์ (น้อยเกินกว่าจะเชื่อถือทางสถิติได้) หรือมีช่วงห่างเฉลี่ยระหว่างการเบิกใช้มากกว่า 60 วัน</td></tr>
				<tr><td><b>Regular</b></td><td>มีการเบิกใช้อย่างน้อย 5 ครั้ง โดยเฉลี่ยห่างกันไม่เกิน 7 วัน</td></tr>
				<tr><td><b>Intermittent</b></td><td>มีการเบิกใช้อย่างน้อย 5 ครั้ง โดยเฉลี่ยห่างกันระหว่าง 7 ถึง 60 วัน</td></tr>
			</tbody></table>`
		);

		const incoming = section(
			"สินค้าที่กำลังเข้า (Incoming: Reliable / Late)",
			`<div>นับเฉพาะจำนวนที่ <b>ยังไม่ได้รับ</b> (คงเหลือ) จากใบสั่งซื้อที่ยังเปิดอยู่เท่านั้น — ใบสั่งซื้อที่ยกเลิก ปิด หรือรับครบแล้วจะไม่ถูกนับ</div>
			<table class="table table-condensed"><tbody>
				<tr><td>${this.badge("RELIABLE", RELIABILITY_COLORS)}</td><td>วันที่กำหนดส่งของ PO อยู่ในวันนี้หรือในอนาคต — คาดว่าจะมาตรงเวลา</td></tr>
				<tr><td>${this.badge("LATE", RELIABILITY_COLORS)}</td><td>วันที่กำหนดส่งของ PO ผ่านไปแล้ว — ของค้างส่ง (เกินกำหนด)</td></tr>
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				ของที่ค้างส่ง (Late Incoming) จะแสดงให้เห็น แต่จะไม่ถูกนำไปรวมในตำแหน่งวางแผนสต็อก เพราะยังไม่ถือว่าเป็นสต็อก
				ที่พร้อมใช้จนกว่าจะได้รับของจริง
			</div>`
		);

		const confidence = section(
			"ความเชื่อมั่น (Confidence)",
			`<div>บอกว่าตัวเลขข้างต้นน่าเชื่อถือแค่ไหน โดยพิจารณาจากปริมาณและคุณภาพของประวัติข้อมูลที่มี:</div>
			<table class="table table-condensed"><tbody>
				<tr><td>${this.badge("High", CONFIDENCE_COLORS)}</td><td>มีประวัติการเบิกใช้เพียงพอ และไม่มีปัญหาข้อมูล</td></tr>
				<tr><td>${this.badge("Medium", CONFIDENCE_COLORS)}</td><td>มีข้อมูลพอใช้ได้แต่ค่อนข้างน้อย เช่น รูปแบบการใช้แบบ Intermittent/Slow, มีการเบิกใช้น้อยกว่า 5 ครั้ง หรือช่วงเวลาที่วิเคราะห์สั้นเมื่อเทียบกับ Target Horizon</td></tr>
				<tr><td>${this.badge("Low", CONFIDENCE_COLORS)}</td><td>ประวัติข้อมูลไม่พอสำหรับคำนวณแบบ Rolling Window จริง (ต้องใช้ค่าเฉลี่ยประมาณการแทน) หรือมีบาง Transaction ที่ไม่สามารถจำแนกประเภทได้อย่างมั่นใจ</td></tr>
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				ข้อผิดพลาด/ข้อสังเกตของข้อมูลทุกจุด (Transaction ที่จำแนกไม่ได้, สต็อกติดลบ, การแปลงหน่วยที่ขาดหายไป ฯลฯ)
				จะลดระดับความเชื่อมั่นลงหนึ่งขั้นเสมอ กดที่แถวของสินค้านั้นเพื่อเปิดดูรายละเอียด จะเห็นเหตุผลที่แท้จริงของ
				แต่ละรายการ
			</div>`
		);

		return status + demand_type + lead_time + incoming + confidence;
	}

	// ---- drill-down -----------------------------------------------------

	open_drill_down(row) {
		const dialog = new frappe.ui.Dialog({
			title: `${row.item_code} · ${row.warehouse}`,
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
		});
		dialog.fields_dict.body.$wrapper.html(
			'<div style="padding: 20px 0; text-align: center; color: var(--text-muted);">Loading...</div>'
		);
		dialog.show();

		const params = this.last_params || {};
		Promise.all([
			frappe.call({
				method: `${API}.get_reorder_analysis_detail`,
				args: {
					item_code: row.item_code,
					warehouse: row.warehouse,
					company: params.company,
					analysis_period: params.analysis_period,
					planning_lead_time: params.planning_lead_time,
					review_period: params.review_period,
					extra_coverage: params.extra_coverage,
					service_level: params.service_level,
				},
			}),
			frappe.call({
				method: `${API}.get_demand_history`,
				args: {
					item_code: row.item_code,
					warehouse: row.warehouse,
					company: params.company,
					analysis_period: params.analysis_period,
				},
			}),
			frappe.call({ method: `${API}.get_incoming_detail`, args: { item_code: row.item_code, warehouse: row.warehouse } }),
		])
			.then(([detail_r, demand_r, incoming_r]) => {
				dialog.fields_dict.body.$wrapper.html(
					this.render_drill_down(detail_r.message, demand_r.message, incoming_r.message)
				);
			})
			.catch(() => {
				dialog.fields_dict.body.$wrapper.html(
					'<div style="padding: 20px 0; color: var(--red-600);">Failed to load details.</div>'
				);
			});
	}

	render_drill_down(detail, demand, incoming) {
		const section = (title, body) =>
			`<div style="margin-bottom: 18px;"><h6 style="margin-bottom: 8px;">${title}</h6>${body}</div>`;

		const na = (value) => (value === null || value === undefined ? "N/A" : this.fmt(value));

		const item_info = section(
			"Item Information",
			`<div>${frappe.utils.escape_html(detail.item_code)} — ${frappe.utils.escape_html(detail.item_name)}</div>
			<div style="color: var(--text-muted); font-size: 12px;">
				Warehouse: ${frappe.utils.escape_html(detail.warehouse)} · UOM: ${frappe.utils.escape_html(detail.stock_uom)} ·
				Criticality used: ${frappe.utils.escape_html(detail.criticality_used)}${detail.is_default_criticality ? " (default — no Criticality set on this Item)" : ""}
			</div>`
		);

		const demand_analysis = section(
			"Demand Analysis",
			`<table class="table table-condensed" style="max-width: 480px;"><tbody>
				<tr><td>Demand Type</td><td>${frappe.utils.escape_html(detail.demand_type)}</td></tr>
				<tr><td>Demand Events</td><td>${detail.demand_events}</td></tr>
				<tr><td>Total Demand (net)</td><td>${this.fmt(detail.total_demand)}</td></tr>
				<tr><td>Average / Event</td><td>${this.fmt(detail.average_demand_per_event)}</td></tr>
				<tr><td>Average / Month</td><td>${this.fmt(detail.average_monthly_demand)}</td></tr>
				<tr><td>Rolling Mean</td><td>${na(detail.rolling_mean)}</td></tr>
				<tr><td>Rolling Median</td><td>${na(detail.rolling_median)}</td></tr>
				<tr><td>Rolling P80</td><td>${na(detail.rolling_p80)}</td></tr>
				<tr><td>Rolling P90</td><td>${na(detail.rolling_p90)}</td></tr>
				<tr><td>Rolling P95</td><td>${na(detail.rolling_p95)}</td></tr>
				<tr><td>Rolling Max</td><td>${na(detail.rolling_max)}</td></tr>
			</tbody></table>`
		);

		const lead_time_source_label = {
			override: "manually overridden in Planning Parameters",
			item_master: "from this Item's own Lead Time (Days)",
			system_default: "system default — this Item has no Lead Time (Days) set",
		}[detail.lead_time_source] || detail.lead_time_source;

		const lead_time = section(
			"Lead Time",
			`<table class="table table-condensed" style="max-width: 480px;"><tbody>
				<tr><td>Configured (Item master)</td><td>${detail.configured_lead_time} days</td></tr>
				<tr><td>Planning (used in calculation)</td><td>${detail.planning_lead_time} days</td></tr>
				<tr><td>Actual Average</td><td>${na(detail.actual_lead_time_avg)}</td></tr>
				<tr><td>Actual P90</td><td>${na(detail.actual_lead_time_p90)}</td></tr>
				<tr><td>PO Sample Count</td><td>${detail.lead_time_sample_count}</td></tr>
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				Planning Lead Time is ${frappe.utils.escape_html(lead_time_source_label)}.
			</div>`
		);

		const position = section(
			"Inventory Position",
			`<div>${this.fmt(detail.actual_qty)} + ${this.fmt(detail.reliable_incoming)} − ${this.fmt(detail.reserved_qty)} = <b>${this.fmt(detail.planning_position)}</b></div>
			<div style="color: var(--text-muted); font-size: 12px;">Late Incoming (${this.fmt(detail.late_incoming)}) is not counted as available supply.</div>`
		);

		const recommendation = section(
			"Recommendation Explanation",
			`<div>ROP = P${this.fmt(detail.service_percentile)} of rolling ${detail.protection_period}-day demand = <b>${this.fmt(detail.reorder_point)}</b>${detail.rop_method === "average_fallback" ? " (average-based estimate — insufficient history for a full rolling window)" : ""}</div>
			<div>Target = P${this.fmt(detail.service_percentile)} of rolling ${detail.target_horizon}-day demand = <b>${this.fmt(detail.target_stock)}</b></div>
			<div>Planning Position (${this.fmt(detail.planning_position)}) ${detail.planning_position <= detail.reorder_point ? "≤" : ">"} ROP (${this.fmt(detail.reorder_point)}) → <b>${frappe.utils.escape_html(detail.status)}</b></div>
			<div>Recommended = max(0, ${this.fmt(detail.target_stock)} − ${this.fmt(detail.planning_position)}) = <b>${this.fmt(detail.recommended_qty)}</b></div>`
		);

		const confidence = section(
			"Confidence",
			`<div>${this.badge(detail.confidence, CONFIDENCE_COLORS)}</div>
			<ul>${(detail.confidence_reason || []).map((r) => `<li>${frappe.utils.escape_html(r)}</li>`).join("")}</ul>`
		);

		const exceptions = section(
			"Exceptions",
			detail.exceptions && detail.exceptions.length
				? `<table class="table table-condensed"><thead><tr><th>Code</th><th>Severity</th><th>Message</th></tr></thead><tbody>${detail.exceptions
						.map(
							(e) =>
								`<tr><td>${frappe.utils.escape_html(e.code)}</td><td>${frappe.utils.escape_html(e.severity)}</td><td>${frappe.utils.escape_html(e.message)}</td></tr>`
						)
						.join("")}</tbody></table>`
				: '<div style="color: var(--text-muted);">None</div>'
		);

		const demand_rows = (demand.rows || [])
			.map(
				(r) =>
					`<tr><td>${frappe.utils.escape_html(r.posting_date)}</td>` +
					`<td><a href="/app/${frappe.router.slug(r.voucher_type)}/${encodeURIComponent(r.voucher_no)}" target="_blank">${frappe.utils.escape_html(r.voucher_no)}</a></td>` +
					`<td>${frappe.utils.escape_html(r.voucher_type)}</td>` +
					`<td>${frappe.utils.escape_html(r.classification)}</td>` +
					`<td style="text-align:right;">${this.fmt(r.demand_qty)}</td></tr>`
			)
			.join("");
		const demand_transactions = section(
			"Demand Transactions",
			`<div style="max-height: 220px; overflow-y: auto;">
				<table class="table table-condensed"><thead><tr><th>Date</th><th>Voucher</th><th>Type</th><th>Classification</th><th style="text-align:right;">Qty</th></tr></thead>
				<tbody>${demand_rows || '<tr><td colspan="5" style="color: var(--text-muted);">No transactions in this period</td></tr>'}</tbody></table>
			</div>`
		);

		const incoming_rows = (incoming.rows || [])
			.map(
				(r) =>
					`<tr><td><a href="/app/purchase-order/${encodeURIComponent(r.purchase_order)}" target="_blank">${frappe.utils.escape_html(r.purchase_order)}</a></td>` +
					`<td>${frappe.utils.escape_html(r.supplier)}</td>` +
					`<td>${frappe.utils.escape_html(r.schedule_date || "")}</td>` +
					`<td style="text-align:right;">${this.fmt(r.remaining_qty)}</td>` +
					`<td>${this.badge(r.reliability, RELIABILITY_COLORS)}</td>` +
					`<td>${r.days_overdue}</td></tr>`
			)
			.join("");
		const incoming_po = section(
			"Incoming PO",
			`<div style="max-height: 220px; overflow-y: auto;">
				<table class="table table-condensed"><thead><tr><th>PO</th><th>Supplier</th><th>Schedule Date</th><th style="text-align:right;">Remaining</th><th>Status</th><th>Days Overdue</th></tr></thead>
				<tbody>${incoming_rows || '<tr><td colspan="6" style="color: var(--text-muted);">No open purchase orders</td></tr>'}</tbody></table>
			</div>`
		);

		return item_info + demand_analysis + lead_time + position + recommendation + confidence + exceptions + demand_transactions + incoming_po;
	}
}
