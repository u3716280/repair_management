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
const POLICY_COLORS = {
	STOCKED: "green-600",
	INTERMITTENT: "blue-500",
	SLOW_CRITICAL: "orange-500",
	REVIEW: "yellow-700",
	BUY_TO_ORDER: "gray-500",
	ONE_TIME: "gray-500",
	NO_HISTORY: "gray-500",
	MANUAL: "gray-500",
	EXCLUDE: "gray-500",
};
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
		this.make_backtest_section();
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
			label: "บริษัท",
			reqd: 1,
		});
		this.planning_warehouse_field = this.make_control(row1, "col-md-3", {
			fieldtype: "Link",
			options: "Warehouse",
			fieldname: "warehouse",
			label: "คลังวางแผน (Planning Warehouse)",
			reqd: 1,
			description: "ต้องเลือกคลังกลุ่ม (Group Warehouse) เท่านั้น — ระบบจะรวมคลังย่อยทั้งหมดเป็นแถวเดียวต่อสินค้า",
			get_query: () => ({ filters: { is_group: 1 } }),
		});
		this.analysis_period_field = this.make_control(row1, "col-md-2", {
			fieldtype: "Int",
			fieldname: "analysis_period",
			label: "ช่วงเวลาวิเคราะห์ (เดือน)",
			min: 1,
		});
		this.item_group_field = this.make_control(row1, "col-md-2", {
			fieldtype: "Link",
			options: "Item Group",
			fieldname: "item_group",
			label: "กลุ่มสินค้า",
		});
		this.item_field = this.make_control(row1, "col-md-2", {
			fieldtype: "Link",
			options: "Item",
			fieldname: "item_code",
			label: "สินค้า",
		});

		this.status_checks = {};
		const status_wrapper = $('<div class="col-md-8"></div>').appendTo(row2);
		$('<label style="display:block; margin-bottom: 4px;">สถานะ</label>').appendTo(status_wrapper);
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

		this.analyze_btn = $('<button class="btn btn-primary btn-sm">วิเคราะห์</button>').appendTo(col_btn);
		this.analyze_btn.on("click", () => this.analyze());

		this.export_btn = $('<button class="btn btn-default btn-sm">ส่งออก CSV</button>').appendTo(col_export);
		this.export_btn.on("click", () => this.export_csv());
		this.export_btn.hide();

		this.explain_btn = $(
			'<button class="btn btn-default btn-sm" title="แต่ละคอลัมน์หมายความว่าอย่างไร">? อธิบาย</button>'
		).appendTo(col_explain);
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
		const row = this.make_collapsible_section("ตัวกรองเพิ่มเติม");

		this.supplier_field = this.make_control(row, "col-md-3", {
			fieldtype: "Link",
			options: "Supplier",
			fieldname: "supplier",
			label: "ผู้จำหน่าย",
		});
		this.policy_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "policy",
			label: "นโยบายการเติมสต็อก (Policy)",
			options:
				"\nSTOCKED\nINTERMITTENT\nSLOW_CRITICAL\nBUY_TO_ORDER\nONE_TIME\nNO_HISTORY\nMANUAL\nREVIEW\nEXCLUDE",
			description:
				"ค่าเริ่มต้น (ไม่เลือก) จะแสดงเฉพาะ STOCKED/INTERMITTENT/SLOW_CRITICAL เว้นแต่จะเลือกสินค้าเจาะจงหนึ่งรายการ หรือเลือกนโยบายอื่นตรงนี้",
		});
		this.demand_type_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "demand_type",
			label: "ประเภทความต้องการ",
			options: "\nRegular\nIntermittent\nSlow\nNo History",
		});
		this.confidence_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "confidence",
			label: "ความเชื่อมั่น",
			options: "\nHigh\nMedium\nLow",
		});
	}

	make_planning_parameters() {
		const row = this.make_collapsible_section(
			"พารามิเตอร์การวางแผน",
			"ค่าพารามิเตอร์นี้จะมีผลต่อการคำนวณโดยตรง — ต่างจากตัวกรองด้านบนซึ่งมีผลแค่การแสดงผลเท่านั้น"
		);

		this.planning_lead_time_field = this.make_control(row, "col-md-3", {
			fieldtype: "Int",
			fieldname: "planning_lead_time",
			label: "เวลานำที่ใช้วางแผน (วัน)",
			min: 0,
			description:
				"เว้นว่างไว้เพื่อใช้ค่า Lead Time (Days) ของสินค้าแต่ละตัวเอง (จะใช้ค่ากลาง 120 วัน เฉพาะสินค้าที่ยังไม่ได้ตั้งค่านี้ไว้) หรือกรอกตัวเลขเพื่อบังคับใช้ค่าเดียวกันกับทุกสินค้าในการวิเคราะห์ครั้งนี้แทน",
		});
		this.review_period_field = this.make_control(row, "col-md-3", {
			fieldtype: "Int",
			fieldname: "review_period",
			label: "รอบตรวจสอบ (วัน)",
			min: 0,
		});
		this.extra_coverage_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "extra_coverage",
			label: "ระยะเวลาสำรองเพิ่มเติม (วัน)",
			options: "30\n45\n60\n90",
		});
		this.service_level_field = this.make_control(row, "col-md-3", {
			fieldtype: "Select",
			fieldname: "service_level",
			label: "ระดับการให้บริการ",
			options: "Auto\nP85\nP95",
			description: "Auto = P85 สำหรับนโยบายทั่วไป, P95 เฉพาะ SLOW_CRITICAL",
		});
	}

	make_backtest_section() {
		const row = this.make_collapsible_section(
			"ทดสอบย้อนหลัง (Backtest)",
			"ทดสอบแบบจำลองนี้กับประวัติข้อมูลจริงแบบ Walk-forward เพื่อดูว่าถ้าใช้แบบจำลองนี้มาตลอด ผลลัพธ์จะเป็นอย่างไร — ไม่มีการสร้างเอกสารซื้อจริงใดๆ ทั้งสิ้น ต้องกด \"วิเคราะห์\" ด้านบนก่อน แล้วเลือกสินค้าจากผลลัพธ์ด้านล่างนี้จึงจะรันได้"
		);

		const item_row = $('<div class="row"></div>').appendTo($('<div class="col-md-12"></div>').appendTo(row));
		this.backtest_item_field = this.make_control(item_row, "col-md-4", {
			fieldtype: "Select",
			fieldname: "backtest_item_code",
			label: "สินค้า (จากผลการวิเคราะห์)",
			options: [{ value: "", label: '-- กรุณากด "วิเคราะห์" ก่อน --' }],
		});

		const params_row = $('<div class="row" style="margin-top: 8px;"></div>').appendTo(
			$('<div class="col-md-12"></div>').appendTo(row)
		);
		this.backtest_training_field = this.make_control(params_row, "col-md-2", {
			fieldtype: "Int",
			fieldname: "training_window_days",
			label: "Training Window (วัน)",
			min: 1,
		});
		this.backtest_validation_field = this.make_control(params_row, "col-md-2", {
			fieldtype: "Int",
			fieldname: "validation_window_days",
			label: "Validation Window (วัน)",
			min: 1,
		});
		this.backtest_step_field = this.make_control(params_row, "col-md-2", {
			fieldtype: "Int",
			fieldname: "step_days",
			label: "Step Size (วัน)",
			min: 1,
		});

		const col_btn = $('<div class="col-md-3" style="padding-top: 22px;"></div>').appendTo(params_row);
		const col_matrix_btn = $('<div class="col-md-3" style="padding-top: 22px;"></div>').appendTo(params_row);

		this.run_backtest_btn = $('<button class="btn btn-primary btn-sm">รัน Backtest</button>').appendTo(col_btn);
		this.run_backtest_btn.on("click", () => this.run_backtest());

		this.run_policy_matrix_btn = $(
			'<button class="btn btn-default btn-sm">รัน Policy Matrix (8 แบบ)</button>'
		).appendTo(col_matrix_btn);
		this.run_policy_matrix_btn.on("click", () => this.run_policy_matrix());

		this.backtest_result_area = $('<div style="margin-bottom: 15px;"></div>').appendTo(this.page.body);
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
		this.extra_coverage_field.set_value("30");
		this.service_level_field.set_value("Auto");
		this.backtest_training_field.set_value(180);
		this.backtest_validation_field.set_value(90);
		this.backtest_step_field.set_value(7);
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

	// Small horizontal bar showing current Planning Position against the
	// Reorder Point and Target reference lines, so a row's urgency is visible
	// without opening its drill-down. The exact numbers are still in the title
	// tooltip and in the plain numeric columns next to it -- the bar never
	// replaces them, only supplements them for quick scanning.
	build_gauge_html(rop, target, position, status) {
		rop = Number(rop) || 0;
		target = Number(target) || 0;
		position = Number(position) || 0;
		const scale_max = Math.max(rop, target, position, 1) * 1.1;
		const is_critical = position <= 0;
		const fill_color = is_critical ? "red-600" : STATUS_COLORS[status] || "gray-500";
		const position_pct = is_critical ? 100 : Math.max(0, Math.min(100, (position / scale_max) * 100));
		const rop_pct = Math.max(0, Math.min(100, (rop / scale_max) * 100));
		const target_pct = Math.max(0, Math.min(100, (target / scale_max) * 100));
		const title = `ตำแหน่งวางแผน: ${this.fmt(position)} | จุดสั่งซื้อ: ${this.fmt(rop)} | เป้าหมาย: ${this.fmt(target)}`;
		return `<div style="position:relative; width:120px; height:14px; background:var(--gray-100); border-radius:3px; overflow:hidden;" title="${frappe.utils.escape_html(title)}">
			<div style="position:absolute; left:0; top:0; height:100%; width:${position_pct}%; background:var(--${fill_color});"></div>
			<div style="position:absolute; left:${rop_pct}%; top:0; height:100%; width:2px; background:var(--gray-800);"></div>
			<div style="position:absolute; left:${target_pct}%; top:0; height:100%; width:2px; background:var(--gray-400);"></div>
		</div>`;
	}

	analyze() {
		const company = this.company_field.get_value();
		const warehouse = this.planning_warehouse_field.get_value();
		if (!company || !warehouse) {
			frappe.msgprint("กรุณาระบุบริษัทและคลังวางแผน");
			return;
		}

		const statuses = this.get_selected_statuses();
		this.last_params = {
			company,
			warehouse,
			item_group: this.item_group_field.get_value() || null,
			item_code: this.item_field.get_value() || null,
			supplier: this.supplier_field.get_value() || null,
			policy: this.policy_field.get_value() || null,
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

		frappe.dom.freeze("กำลังวิเคราะห์...");
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
		this.update_backtest_item_options(data);
		if (!data.length) {
			this.summary_area.html("ไม่พบสินค้าที่ตรงกับเงื่อนไขที่เลือก");
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
			`วิเคราะห์ทั้งหมด: ${data.length} &nbsp;|&nbsp; ` +
				ALL_STATUSES.map(
					(status) =>
						`<span style="color: var(--${STATUS_COLORS[status]}); font-weight: 600; margin-right: 14px;">${status}: ${counts[status]}</span>`
				).join("")
		);

		const columns = [
			{
				name: "สินค้า",
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
				name: "ระดับสต็อก",
				editable: false,
				width: 140,
				sortable: false,
				format: (value, row, column, data) => {
					const v = data[1];
					return this.build_gauge_html(v.rop, v.target, v.position, v.status);
				},
			},
			{
				name: "นโยบาย",
				editable: false,
				width: 130,
				sortable: false,
				format: (value) => this.badge(value, POLICY_COLORS),
			},
			{
				name: "เวลานำ",
				editable: false,
				width: 140,
				sortable: false,
				format: (value, row, column, data) => {
					const v = data[3];
					return `${v.planning} วัน (ตั้งค่า ${v.configured} วัน)`;
				},
			},
			{ name: "จุดสั่งซื้อ (ROP)", editable: false, width: 100, format: (value) => this.fmt(value) },
			{ name: "สต็อกกลุ่ม", editable: false, width: 90, format: (value) => this.fmt(value) },
			{ name: "จองไว้", editable: false, width: 80, format: (value) => this.fmt(value) },
			{
				name: "ออกPOแล้ว",
				editable: false,
				width: 170,
				sortable: false,
				format: (value, row, column, data) => {
					const v = data[7];
					const title = `มาตรงเวลา ${this.fmt(v.reliable)} + ค้างส่ง ${this.fmt(v.late)}`;
					return `<span title="${frappe.utils.escape_html(title)}">${this.fmt(v.total)}</span>`;
				},
			},
			{ name: "ตำแหน่งวางแผน", editable: false, width: 110, format: (value) => this.fmt(value) },
			{ name: "เป้าหมาย", editable: false, width: 90, format: (value) => this.fmt(value) },
			{ name: "แนะนำสั่ง", editable: false, width: 100, format: (value) => this.fmt(value) },
			{
				name: "สถานะ",
				editable: false,
				width: 110,
				sortable: false,
				format: (value) => this.badge(value, STATUS_COLORS),
			},
			{
				name: "ความเชื่อมั่น",
				editable: false,
				width: 110,
				sortable: false,
				format: (value) => this.badge(value, CONFIDENCE_COLORS),
			},
		];

		const rows = data.map((d) => [
			{ item_code: d.item_code, item_name: d.item_name },
			{ rop: d.reorder_point, target: d.target_stock, position: d.planning_position, status: d.status },
			d.policy,
			{ planning: d.planning_lead_time, configured: d.configured_lead_time },
			d.reorder_point,
			d.actual_qty,
			d.reserved_qty,
			{ total: d.total_outstanding_qty, reliable: d.reliable_incoming, late: d.late_incoming },
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
			"รหัสสินค้า", "ชื่อสินค้า", "คลังสินค้า", "นโยบาย", "ประเภทความต้องการ", "จำนวนครั้งที่เบิกใช้",
			"เวลานำที่ใช้วางแผน", "เวลานำที่ตั้งค่าไว้", "จุดสั่งซื้อ (ROP)", "สต็อกกลุ่ม", "จองไว้",
			"ของเข้าทั้งหมด", "ของเข้าที่เชื่อถือได้", "ของเข้าที่ค้างส่ง", "ตำแหน่งวางแผน", "เป้าหมาย",
			"แนะนำสั่ง", "สถานะ", "ความเชื่อมั่น",
		];

		const lines = [header.map((value) => this.csv_escape(value)).join(",")];
		this.current_data.forEach((d) => {
			lines.push(
				[
					d.item_code, d.item_name, d.warehouse, d.policy, d.demand_type, d.demand_events,
					d.planning_lead_time, d.configured_lead_time, d.reorder_point, d.actual_qty,
					d.reserved_qty, d.total_outstanding_qty, d.reliable_incoming, d.late_incoming,
					d.planning_position, d.target_stock, d.recommended_qty, d.status, d.confidence,
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

	// ---- backtest -----------------------------------------------------

	// Backtest/Policy Matrix must run against exactly one item from the
	// current analysis result set -- populated as a Select (not free typing)
	// so the user can only pick an item that was actually just analyzed.
	update_backtest_item_options(data) {
		const seen = new Set();
		const options = [{ value: "", label: '-- เลือกสินค้า --' }];
		(data || []).forEach((d) => {
			if (seen.has(d.item_code)) return;
			seen.add(d.item_code);
			options.push({ value: d.item_code, label: `${d.item_code} — ${d.item_name || ""}` });
		});
		if (options.length === 1) {
			options[0] = { value: "", label: '-- ไม่พบสินค้า กรุณากด "วิเคราะห์" ใหม่ --' };
		}
		this.backtest_item_field.df.options = options;
		this.backtest_item_field.set_options();
	}

	run_backtest() {
		const item_code = this.backtest_item_field.get_value();
		const warehouse = this.planning_warehouse_field.get_value();
		if (!item_code || !warehouse) {
			frappe.msgprint('กรุณากด "วิเคราะห์" แล้วเลือกสินค้าหนึ่งรายการจากรายการผลลัพธ์ก่อนรัน Backtest');
			return;
		}

		const args = {
			item_code,
			warehouse,
			company: this.company_field.get_value(),
			training_window_days: Number(this.backtest_training_field.get_value() || 180),
			validation_window_days: Number(this.backtest_validation_field.get_value() || 90),
			step_days: Number(this.backtest_step_field.get_value() || 7),
			planning_lead_time: this.planning_lead_time_field.get_value()
				? Number(this.planning_lead_time_field.get_value())
				: null,
			review_period: Number(this.review_period_field.get_value() || 1),
			extra_coverage: Number(this.extra_coverage_field.get_value() || 30),
			service_level: this.service_level_field.get_value() || "Auto",
		};

		frappe.dom.freeze("กำลังรัน Backtest...");
		frappe
			.call({ method: `${API}.run_backtest`, args })
			.then((r) => {
				frappe.dom.unfreeze();
				this.render_backtest_result(r.message);
			})
			.catch(() => frappe.dom.unfreeze());
	}

	render_backtest_result(result) {
		const m = result.metrics;
		const pct = (value) => (value !== null && value !== undefined ? `${(value * 100).toFixed(1)}%` : "N/A");
		const stability = (cv, stable) => (cv !== null && cv !== undefined ? `${cv.toFixed(3)} (${stable ? "เสถียร" : "ไม่เสถียร"})` : "N/A");

		this.backtest_result_area.html(`
			<div style="padding: 10px 14px; background: rgba(128,128,128,0.08); border-radius: 6px;">
				<div style="font-size:12px; color: var(--text-muted); margin-bottom: 8px;">${frappe.utils.escape_html(result.config.reserved_qty_note)}</div>
				<table class="table table-condensed" style="max-width: 620px;"><tbody>
					<tr><td>ช่วงทดสอบ</td><td>${result.config.backtest_start_date} ถึง ${result.config.backtest_end_date}</td></tr>
					<tr><td>Stockout (วัน)</td><td>${m.stockout_days}</td></tr>
					<tr><td>Stockout Qty</td><td>${this.fmt(m.stockout_qty)}</td></tr>
					<tr><td>Fill Rate</td><td>${pct(m.fill_rate)}</td></tr>
					<tr><td>Cycle Service Level</td><td>${pct(m.cycle_service_level)}</td></tr>
					<tr><td>สต็อกเฉลี่ย / สูงสุด / ต่ำสุด</td><td>${this.fmt(m.average_inventory)} / ${this.fmt(m.max_inventory)} / ${this.fmt(m.min_inventory)}</td></tr>
					<tr><td>จำนวนวันสต็อกเกินเป้าหมาย</td><td>${m.excess_stock_days}</td></tr>
					<tr><td>จำนวนครั้งที่สั่งซื้อ (จำลอง)</td><td>${m.number_of_orders}</td></tr>
					<tr><td>จำนวนสั่งซื้อเฉลี่ย / สูงสุด</td><td>${this.fmt(m.average_order_qty)} / ${this.fmt(m.max_order_qty)}</td></tr>
					<tr><td>มูลค่าสต็อกเฉลี่ยโดยประมาณ</td><td>${this.fmt(m.average_inventory_value)}</td></tr>
					<tr><td>ความเสถียรของ ROP (CV)</td><td>${stability(m.stability.rop_cv, m.stability.rop_stable)}</td></tr>
					<tr><td>ความเสถียรของ Target (CV)</td><td>${stability(m.stability.target_cv, m.stability.target_stable)}</td></tr>
				</tbody></table>
			</div>
			${this.render_baseline_comparison(result.baselines, m)}
		`);
	}

	render_baseline_comparison(baselines, model_metrics) {
		if (!baselines) return "";
		const pct = (value) => (value !== null && value !== undefined ? `${(value * 100).toFixed(1)}%` : "N/A");
		const native = baselines.native_erpnext;

		let native_row = `<tr><td>ERPNext (native reorder level)</td><td colspan="4" style="color: var(--text-muted);">ไม่ได้ตั้งค่า Item Reorder ไว้สำหรับสินค้า/คลังนี้ — ไม่มีข้อมูลเปรียบเทียบ</td></tr>`;
		if (native) {
			const nm = native.result.metrics;
			const ambiguous = native.config.multiple_rows_found
				? ` <span style="color: var(--orange-600);">(พบหลายแถว ใช้แถวแรก: ${frappe.utils.escape_html(native.config.warehouse)})</span>`
				: "";
			native_row = `<tr>
				<td>ERPNext (native): level ${this.fmt(native.config.warehouse_reorder_level)} / qty ${this.fmt(native.config.warehouse_reorder_qty)}${ambiguous}</td>
				<td>${nm.stockout_days}</td>
				<td>${pct(nm.fill_rate)}</td>
				<td>${this.fmt(nm.average_inventory)}</td>
				<td>${nm.number_of_orders}</td>
			</tr>`;
		}

		return `
			<div style="padding: 10px 14px; background: rgba(128,128,128,0.08); border-radius: 6px; margin-top: 10px;">
				<div style="font-weight: 600; margin-bottom: 6px;">เปรียบเทียบกับวิธีอื่น (Baseline Comparison)</div>
				<table class="table table-condensed" style="max-width: 720px;">
					<thead><tr><th>วิธี</th><th>Stockout วัน</th><th>Fill Rate</th><th>สต็อกเฉลี่ย</th><th>จำนวนสั่งซื้อ</th></tr></thead>
					<tbody>
						<tr>
							<td>โมเดลนี้ (Policy-based)</td>
							<td>${model_metrics.stockout_days}</td>
							<td>${pct(model_metrics.fill_rate)}</td>
							<td>${this.fmt(model_metrics.average_inventory)}</td>
							<td>${model_metrics.number_of_orders}</td>
						</tr>
						${native_row}
					</tbody>
				</table>
				<div style="font-size:12px; color: var(--text-muted);">
					ROP อย่างง่าย (เฉลี่ยความต้องการ x เวลานำ) = ${this.fmt(baselines.avg_demand_lead_time_rop)} ·
					Min/Max อย่างง่าย = ${this.fmt(baselines.min_max.min)} / ${this.fmt(baselines.min_max.max)}
					— ใช้เป็นข้อมูลอ้างอิงเท่านั้น ไม่ได้จำลองแบบวันต่อวัน
				</div>
			</div>
		`;
	}

	run_policy_matrix() {
		const item_code = this.backtest_item_field.get_value();
		const warehouse = this.planning_warehouse_field.get_value();
		if (!item_code || !warehouse) {
			frappe.msgprint('กรุณากด "วิเคราะห์" แล้วเลือกสินค้าหนึ่งรายการจากรายการผลลัพธ์ก่อนรัน Policy Matrix');
			return;
		}

		const args = {
			item_code,
			warehouse,
			company: this.company_field.get_value(),
			training_window_days: Number(this.backtest_training_field.get_value() || 180),
			validation_window_days: Number(this.backtest_validation_field.get_value() || 90),
			step_days: Number(this.backtest_step_field.get_value() || 7),
			planning_lead_time: this.planning_lead_time_field.get_value()
				? Number(this.planning_lead_time_field.get_value())
				: null,
			review_period: Number(this.review_period_field.get_value() || 1),
		};

		frappe.dom.freeze("กำลังรัน Policy Matrix...");
		frappe
			.call({ method: `${API}.run_policy_matrix`, args })
			.then((r) => {
				frappe.dom.unfreeze();
				this.render_policy_matrix_result(r.message);
			})
			.catch(() => frappe.dom.unfreeze());
	}

	render_policy_matrix_result(results) {
		const pct = (value) => (value !== null && value !== undefined ? `${(value * 100).toFixed(1)}%` : "N/A");
		const rows = results
			.map((r) => {
				const m = r.metrics;
				return `<tr>
					<td>${r.service_level}</td>
					<td>${r.extra_coverage}</td>
					<td>${m.stability.rop_cv !== null ? m.stability.rop_cv.toFixed(3) : "N/A"}</td>
					<td>${m.stability.target_cv !== null ? m.stability.target_cv.toFixed(3) : "N/A"}</td>
					<td>${m.stockout_days}</td>
					<td>${pct(m.fill_rate)}</td>
					<td>${m.number_of_orders}</td>
				</tr>`;
			})
			.join("");
		this.backtest_result_area.html(`
			<div style="overflow-x:auto;">
				<table class="table table-condensed"><thead><tr>
					<th>Service Level</th><th>Extra Coverage</th><th>ROP CV</th><th>Target CV</th>
					<th>Stockout วัน</th><th>Fill Rate</th><th>จำนวนสั่งซื้อ</th>
				</tr></thead><tbody>${rows}</tbody></table>
			</div>
		`);
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
					<td>ตำแหน่งวางแผนสต็อก (สต็อกจริง + ของเข้าทั้งหมด − ของที่จองไว้) น้อยกว่าหรือเท่ากับ 0 — ถือว่าของหมดแล้ว</td></tr>
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
			</div>
			<div style="color: var(--text-muted); font-size: 12px; margin-top: 6px;">
				แถบสี "ระดับสต็อก" ในตาราง และข้อความสรุปด้านบนของหน้ารายละเอียดแต่ละสินค้า สรุปสถานะเดียวกันนี้ให้เห็น
				ได้เร็วขึ้น โดยไม่ต้องอ่านตัวเลขทั้งหมดก่อน
			</div>`
		);

		const policy = section(
			"นโยบายการเติมสต็อก (Policy)",
			`<table class="table table-condensed"><tbody>
				<tr><td>${this.badge("STOCKED", POLICY_COLORS)}</td><td>ความต้องการสม่ำเสมอ (Regular) — คำนวณ ROP/เป้าหมายด้วย P85</td></tr>
				<tr><td>${this.badge("INTERMITTENT", POLICY_COLORS)}</td><td>ความต้องการเป็นช่วงๆ — คำนวณด้วย P85 เช่นกัน</td></tr>
				<tr><td>${this.badge("SLOW_CRITICAL", POLICY_COLORS)}</td><td>ความต้องการน้อยแต่ยังพอวิเคราะห์ได้ — ถือว่าสำคัญ/วิกฤต จึงใช้ P95 (เข้มงวดกว่า)</td></tr>
				<tr><td>${this.badge("ONE_TIME", POLICY_COLORS)}</td><td>มีการเบิกใช้เพียง 1 ครั้งในช่วงที่วิเคราะห์ — อาจเป็นสินค้าเฉพาะโครงการ ไม่ใช่สต็อกประจำ</td></tr>
				<tr><td>${this.badge("NO_HISTORY", POLICY_COLORS)}</td><td>ไม่มีประวัติการเบิกใช้เลย</td></tr>
				<tr><td>${this.badge("REVIEW", POLICY_COLORS)}</td><td>ข้อมูลน้อยเกินกว่าจะคำนวณแบบ Rolling Window ได้ ต้องตรวจสอบเอง</td></tr>
				<tr><td>${this.badge("BUY_TO_ORDER", POLICY_COLORS)} / ${this.badge("MANUAL", POLICY_COLORS)} / ${this.badge("EXCLUDE", POLICY_COLORS)}</td>
					<td>ไม่มีการกำหนดอัตโนมัติจากข้อมูล — ใช้เฉพาะเมื่อกำหนดเองรายสินค้าเท่านั้น (ยังไม่รองรับการบันทึกค่านี้ถาวรในเวอร์ชันนี้)</td></tr>
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				เฉพาะ STOCKED/INTERMITTENT/SLOW_CRITICAL เท่านั้นที่จะแสดงในรายการเมื่อไม่ได้เลือกสินค้าหรือ Policy เจาะจง
				— นโยบายอื่นจะไม่แสดงเป็นค่าเริ่มต้น เพราะไม่ควรสั่งซื้ออัตโนมัติโดยไม่มีคนตรวจสอบก่อน
			</div>`
		);

		const lead_time = section(
			"เวลานำ (Lead Time)",
			`<div>
				คอลัมน์ "เวลานำ" แสดงจำนวนวันที่ใช้จริงในการคำนวณ (ใช้วางแผน) เทียบกับค่าที่ตั้งไว้ใน Item (ตั้งค่า)
			</div>
			<div style="color: var(--text-muted); font-size: 12px;">
				ถ้าไม่ได้กรอกช่อง "เวลานำที่ใช้วางแผน" ใน พารามิเตอร์การวางแผน ระบบจะใช้ค่า Lead Time (Days) ของ
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
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				นี่คือสถิติพื้นฐานที่ใช้คำนวณ "นโยบายการเติมสต็อก" (Policy) ด้านบนอีกที — Policy คือคำแนะนำเชิงธุรกิจที่ลึกกว่านี้
			</div>`
		);

		const incoming = section(
			"สินค้าที่กำลังเข้า (Incoming) และการติดตามการสั่งซื้อ",
			`<div>นับเฉพาะจำนวนที่ <b>ยังไม่ได้รับ</b> (คงเหลือ) จากใบสั่งซื้อที่ยังเปิดอยู่เท่านั้น — ใบสั่งซื้อที่ยกเลิก ปิด หรือรับครบแล้วจะไม่ถูกนับ</div>
			<div style="color: var(--text-muted); font-size: 12px; margin-top: 6px;">
				"ของเข้าทั้งหมด" ในตารางหลักนับรวมทั้ง${this.badge("RELIABLE", RELIABILITY_COLORS)}(กำหนดส่งวันนี้หรืออนาคต)
				และ ${this.badge("LATE", RELIABILITY_COLORS)}(เกินกำหนดส่งแล้ว) เข้าด้วยกันเสมอ — ของที่ค้างส่งยังถือว่าจะได้รับแน่นอน
				จึงนับรวมในตำแหน่งวางแผนสต็อกเต็มจำนวน ไม่ได้ถูกตัดออก เพราะวันที่กำหนดส่งอาจไม่ตรงกับความเป็นจริงเสมอไป
				และไม่ควรทำให้ระบบแนะนำให้สั่งซ้ำเพียงเพราะ PO ดูเหมือนจะล่าช้า
			</div>
			<div style="color: var(--text-muted); font-size: 12px; margin-top: 6px;">
				รายการที่ค้างส่งจะแยกแสดงในหัวข้อ "ติดตามการสั่งซื้อ" ของหน้ารายละเอียดแต่ละสินค้า — ไว้ใช้ติดตามผู้จำหน่าย
				เท่านั้น ไม่มีผลย้อนกลับไปยังการคำนวณ
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

		const backtest = section(
			"ทดสอบย้อนหลัง (Backtest)",
			`<div>
				จำลองว่า "ถ้าใช้แบบจำลองนี้คำนวณ ROP/เป้าหมายมาตลอดในอดีต" จะเกิดอะไรขึ้น โดยใช้ประวัติการเบิกใช้จริง
				— ไม่มีการมองข้อมูลล่วงหน้า (No Look-Ahead): ทุกจุดตรวจสอบจะคำนวณจากข้อมูลก่อนหน้าวันนั้นเท่านั้น
			</div>
			<div style="color: var(--text-muted); font-size: 12px; margin-top: 6px;">
				Training Window = จำนวนวันย้อนหลังที่ใช้คำนวณ ROP/เป้าหมายในแต่ละจุดตรวจสอบ · Validation Window = ช่วงเวลา
				ทั้งหมดที่จำลอง · Step Size = ความถี่ในการคำนวณ ROP/เป้าหมายใหม่ (ระหว่างนั้นค่าจะคงที่)
			</div>
			<div style="color: var(--text-muted); font-size: 12px; margin-top: 6px;">
				ค่า "จองไว้" (Reserved) จะถูกตรึงไว้ที่ค่าปัจจุบันตลอดการจำลอง เนื่องจากระบบไม่มีประวัติย้อนหลังของยอดจอง —
				เป็นข้อจำกัดที่ทราบอยู่แล้ว ไม่ใช่ความคลาดเคลื่อนที่ซ่อนไว้
			</div>`
		);

		return status + policy + demand_type + lead_time + incoming + confidence + backtest;
	}

	// ---- drill-down -----------------------------------------------------

	open_drill_down(row) {
		const dialog = new frappe.ui.Dialog({
			title: `${row.item_code} · ${row.warehouse}`,
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
		});
		dialog.fields_dict.body.$wrapper.html(
			'<div style="padding: 20px 0; text-align: center; color: var(--text-muted);">กำลังโหลด...</div>'
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
					'<div style="padding: 20px 0; color: var(--red-600);">โหลดข้อมูลไม่สำเร็จ</div>'
				);
			});
	}

	// One-sentence, plain-language conclusion shown before any of the detail
	// tables -- the reader shouldn't have to work through the ROP/Target
	// arithmetic themselves just to know whether to act.
	build_verdict_html(detail) {
		const status = detail.status;
		const color = STATUS_COLORS[status] || "gray-500";
		const lines = [];

		if (status === "Critical") {
			lines.push(`⚠ สินค้าหมดแล้ว ควรสั่งซื้อด่วน ${this.fmt(detail.recommended_qty)} หน่วย`);
		} else if (status === "Reorder") {
			lines.push(`ควรสั่งซื้อตอนนี้ ${this.fmt(detail.recommended_qty)} หน่วย — ตำแหน่งสต็อกต่ำกว่าจุดสั่งซื้อแล้ว`);
			const avg_daily = (detail.average_monthly_demand || 0) / 30;
			if (avg_daily > 0 && detail.planning_position > 0) {
				const days = Math.floor(detail.planning_position / avg_daily);
				lines.push(`สต็อกจะหมดในประมาณ ${days} วัน ที่อัตราการใช้เฉลี่ยปัจจุบัน`);
			}
		} else if (status === "Review") {
			lines.push("ความเชื่อมั่นของข้อมูลอยู่ในระดับต่ำ — ควรตรวจสอบด้วยตนเองก่อนตัดสินใจ");
		} else if (status === "No History") {
			lines.push("ยังไม่มีประวัติการเบิกใช้เพียงพอ จึงยังแนะนำไม่ได้");
		} else {
			lines.push("สต็อกเพียงพอ ไม่ต้องสั่งซื้อตอนนี้");
		}

		return `<div style="padding: 10px 14px; margin-bottom: 16px; border-radius: 6px; background: rgba(128,128,128,0.08); border-left: 4px solid var(--${color});">
			${lines.map((line) => `<div style="font-weight: 600; color: var(--${color});">${frappe.utils.escape_html(line)}</div>`).join("")}
		</div>`;
	}

	render_drill_down(detail, demand, incoming) {
		const section = (title, body) =>
			`<div style="margin-bottom: 18px;"><h6 style="margin-bottom: 8px;">${title}</h6>${body}</div>`;

		const na = (value) => (value === null || value === undefined ? "N/A" : this.fmt(value));

		const verdict = this.build_verdict_html(detail);

		const item_info = section(
			"ข้อมูลสินค้า",
			`<div>${frappe.utils.escape_html(detail.item_code)} — ${frappe.utils.escape_html(detail.item_name)}</div>
			<div style="color: var(--text-muted); font-size: 12px;">
				คลังวางแผน: ${frappe.utils.escape_html(detail.warehouse)} · หน่วยนับ: ${frappe.utils.escape_html(detail.stock_uom)} ·
				นโยบาย: ${this.badge(detail.policy, POLICY_COLORS)}
				${detail.leaf_warehouses && detail.leaf_warehouses.length > 1 ? `<br>รวมคลังย่อย: ${detail.leaf_warehouses.map((w) => frappe.utils.escape_html(w)).join(", ")}` : ""}
			</div>
			${(detail.policy_reasons || []).length ? `<ul style="font-size:12px; color: var(--text-muted); margin-top:4px;">${detail.policy_reasons.map((r) => `<li>${frappe.utils.escape_html(r)}</li>`).join("")}</ul>` : ""}`
		);

		const demand_analysis = section(
			"วิเคราะห์ความต้องการ",
			`<table class="table table-condensed" style="max-width: 480px;"><tbody>
				<tr><td>ประเภทความต้องการ</td><td>${frappe.utils.escape_html(detail.demand_type)}</td></tr>
				<tr><td>จำนวนครั้งที่เบิกใช้</td><td>${detail.demand_events}</td></tr>
				<tr><td>ความต้องการรวม (สุทธิ)</td><td>${this.fmt(detail.total_demand)}</td></tr>
				<tr><td>เฉลี่ยต่อครั้ง</td><td>${this.fmt(detail.average_demand_per_event)}</td></tr>
				<tr><td>เฉลี่ยต่อเดือน</td><td>${this.fmt(detail.average_monthly_demand)}</td></tr>
				<tr><td>ค่าเฉลี่ยเคลื่อนที่ (Rolling Mean)</td><td>${na(detail.rolling_mean)}</td></tr>
				<tr><td>มัธยฐานเคลื่อนที่ (Rolling Median)</td><td>${na(detail.rolling_median)}</td></tr>
				<tr><td>P80 (Rolling)</td><td>${na(detail.rolling_p80)}</td></tr>
				<tr><td>P90 (Rolling)</td><td>${na(detail.rolling_p90)}</td></tr>
				<tr><td>P95 (Rolling)</td><td>${na(detail.rolling_p95)}</td></tr>
				<tr><td>สูงสุด (Rolling Max)</td><td>${na(detail.rolling_max)}</td></tr>
			</tbody></table>`
		);

		const lead_time_source_label = {
			override: "ถูกกำหนดเองในพารามิเตอร์การวางแผน",
			item_master: "มาจากค่า Lead Time (Days) ของสินค้านี้เอง",
			system_default: "ค่าเริ่มต้นของระบบ — สินค้านี้ยังไม่ได้ตั้งค่า Lead Time (Days)",
		}[detail.lead_time_source] || detail.lead_time_source;

		const lead_time = section(
			"เวลานำ",
			`<table class="table table-condensed" style="max-width: 480px;"><tbody>
				<tr><td>ตั้งค่าไว้ใน Item</td><td>${detail.configured_lead_time} วัน</td></tr>
				<tr><td>ใช้ในการคำนวณ</td><td>${detail.planning_lead_time} วัน</td></tr>
				<tr><td>เฉลี่ยจริง</td><td>${na(detail.actual_lead_time_avg)}</td></tr>
				<tr><td>P90 จริง</td><td>${na(detail.actual_lead_time_p90)}</td></tr>
				<tr><td>จำนวนตัวอย่าง PO</td><td>${detail.lead_time_sample_count}</td></tr>
			</tbody></table>
			<div style="color: var(--text-muted); font-size: 12px;">
				เวลานำที่ใช้วางแผนคือค่าที่${frappe.utils.escape_html(lead_time_source_label)}
			</div>`
		);

		const position = section(
			"ตำแหน่งสต็อก",
			`<div>${this.fmt(detail.actual_qty)} + ${this.fmt(detail.total_outstanding_qty)} − ${this.fmt(detail.reserved_qty)} = <b>${this.fmt(detail.planning_position)}</b></div>
			<div style="color: var(--text-muted); font-size: 12px;">
				ของเข้าทั้งหมด ${this.fmt(detail.total_outstanding_qty)} หน่วย = มาตรงเวลา ${this.fmt(detail.reliable_incoming)} +
				ค้างส่ง ${this.fmt(detail.late_incoming)} — ของค้างส่งยังนับรวมด้วยเต็มจำนวน เพราะถือว่าจะได้รับแน่นอน
				(ดูรายการที่ต้องติดตามได้ที่หัวข้อ "ติดตามการสั่งซื้อ" ด้านล่าง)
			</div>`
		);

		const recommendation = section(
			"คำอธิบายคำแนะนำ",
			`<div>จุดสั่งซื้อ (ROP) = P${this.fmt(detail.service_percentile)} ของยอดเบิกใช้แบบ Rolling ${detail.protection_period} วัน = <b>${this.fmt(detail.reorder_point)}</b>${detail.rop_method === "average_fallback" ? " (ประมาณการจากค่าเฉลี่ย — ข้อมูลย้อนหลังไม่พอสำหรับ Rolling Window เต็มรูปแบบ)" : ""}</div>
			<div>เป้าหมาย = P${this.fmt(detail.service_percentile)} ของยอดเบิกใช้แบบ Rolling ${detail.target_horizon} วัน = <b>${this.fmt(detail.target_stock)}</b></div>
			<div>ตำแหน่งวางแผน (${this.fmt(detail.planning_position)}) ${detail.planning_position <= detail.reorder_point ? "≤" : ">"} จุดสั่งซื้อ (${this.fmt(detail.reorder_point)}) → <b>${frappe.utils.escape_html(detail.status)}</b></div>
			<div>แนะนำสั่ง = max(0, ${this.fmt(detail.target_stock)} − ${this.fmt(detail.planning_position)}) = <b>${this.fmt(detail.recommended_qty)}</b></div>
			<div style="color: var(--text-muted); font-size: 12px;">
				Service Level ที่ใช้: P${this.fmt(detail.service_percentile)}
				(${detail.service_level === "Auto" ? `อัตโนมัติตามนโยบาย ${frappe.utils.escape_html(detail.policy)}` : "กำหนดเอง"})
			</div>`
		);

		const confidence = section(
			"ความเชื่อมั่น",
			`<div>${this.badge(detail.confidence, CONFIDENCE_COLORS)}</div>
			<ul>${(detail.confidence_reason || []).map((r) => `<li>${frappe.utils.escape_html(r)}</li>`).join("")}</ul>`
		);

		const exceptions = section(
			"ข้อยกเว้น",
			detail.exceptions && detail.exceptions.length
				? `<table class="table table-condensed"><thead><tr><th>รหัส</th><th>ระดับ</th><th>ข้อความ</th></tr></thead><tbody>${detail.exceptions
						.map(
							(e) =>
								`<tr><td>${frappe.utils.escape_html(e.code)}</td><td>${frappe.utils.escape_html(e.severity)}</td><td>${frappe.utils.escape_html(e.message)}</td></tr>`
						)
						.join("")}</tbody></table>`
				: '<div style="color: var(--text-muted);">ไม่มี</div>'
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
			"รายการเบิกใช้",
			`<div style="max-height: 220px; overflow-y: auto;">
				<table class="table table-condensed"><thead><tr><th>วันที่</th><th>เอกสาร</th><th>ประเภท</th><th>การจำแนก</th><th style="text-align:right;">จำนวน</th></tr></thead>
				<tbody>${demand_rows || '<tr><td colspan="5" style="color: var(--text-muted);">ไม่มีรายการในช่วงเวลานี้</td></tr>'}</tbody></table>
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
			"ใบสั่งซื้อที่ยังไม่ได้รับ",
			`<div style="color: var(--text-muted); font-size: 12px; margin-bottom: 4px;">รวมทั้งมาตรงเวลาและค้างส่ง — ตัวเลขนี้คือส่วนหนึ่งของสูตรตำแหน่งวางแผนสต็อกด้านบน</div>
			<div style="max-height: 220px; overflow-y: auto;">
				<table class="table table-condensed"><thead><tr><th>ใบสั่งซื้อ</th><th>ผู้จำหน่าย</th><th>วันที่กำหนดส่ง</th><th style="text-align:right;">คงเหลือ</th><th>สถานะ</th><th>วันเกินกำหนด</th></tr></thead>
				<tbody>${incoming_rows || '<tr><td colspan="6" style="color: var(--text-muted);">ไม่มีใบสั่งซื้อที่ยังเปิดอยู่</td></tr>'}</tbody></table>
			</div>`
		);

		const follow_up_rows = (incoming.follow_up || [])
			.map(
				(r) =>
					`<tr><td><a href="/app/purchase-order/${encodeURIComponent(r.purchase_order)}" target="_blank">${frappe.utils.escape_html(r.purchase_order)}</a></td>` +
					`<td>${frappe.utils.escape_html(r.supplier)}</td>` +
					`<td>${frappe.utils.escape_html(r.schedule_date || "")}</td>` +
					`<td>${r.days_overdue}</td>` +
					`<td style="text-align:right;">${this.fmt(r.remaining_qty)}</td></tr>`
			)
			.join("");
		const purchase_follow_up = section(
			"ติดตามการสั่งซื้อ (Purchase Follow-up)",
			`<div style="font-size:12px; color: var(--text-muted); margin-bottom:6px;">
				ข้อมูลติดตามผู้จำหน่ายเท่านั้น — ไม่ส่งผลต่อการคำนวณตำแหน่งวางแผนสต็อกด้านบน (ของค้างส่งนับรวมอยู่แล้วในตาราง
				"ใบสั่งซื้อที่ยังไม่ได้รับ")
			</div>
			<div style="max-height: 180px; overflow-y: auto; background: rgba(234,88,12,0.06); border-radius:4px; padding:4px;">
				<table class="table table-condensed"><thead><tr><th>ใบสั่งซื้อ</th><th>ผู้จำหน่าย</th><th>วันที่กำหนดส่ง</th><th>วันเกินกำหนด</th><th style="text-align:right;">คงเหลือ</th></tr></thead>
				<tbody>${follow_up_rows || '<tr><td colspan="5" style="color: var(--text-muted);">ไม่มีรายการค้างส่ง</td></tr>'}</tbody></table>
			</div>`
		);

		return (
			verdict +
			item_info +
			demand_analysis +
			lead_time +
			position +
			recommendation +
			confidence +
			exceptions +
			demand_transactions +
			incoming_po +
			purchase_follow_up
		);
	}
}
