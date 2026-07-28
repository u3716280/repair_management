// Reorder Point Calculator - Frappe Page SPA
const REORDER_METHOD =
	"repair_management.page.reorder_point_calcul.reorder_point_calcul.get_reorder_data";

frappe.pages["reorder-point-calcul"].on_page_load = function (wrapper) {
	new ReorderPointCalculator(wrapper);
};

class ReorderPointCalculator {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "คำนวณจุดสั่งซื้อ (Reorder Point Calculator)",
			single_column: true,
		});

		this.make_filters();
		this.make_table_area();
		this.set_default_dates();
	}

	set_default_dates() {
		const to_date = frappe.datetime.get_today();
		const from_date = frappe.datetime.add_days(to_date, -90);
		this.from_date_field.set_value(from_date);
		this.to_date_field.set_value(to_date);
	}

	make_filters() {
		const filter_row = $(
			'<div class="row" style="margin-bottom: 15px;"></div>'
		).appendTo(this.page.body);

		const col_item_group = $('<div class="col-md-3"></div>').appendTo(filter_row);
		const col_from = $('<div class="col-md-2"></div>').appendTo(filter_row);
		const col_to = $('<div class="col-md-2"></div>').appendTo(filter_row);
		const col_btn = $('<div class="col-md-2" style="padding-top: 22px;"></div>').appendTo(
			filter_row
		);
		const col_export = $('<div class="col-md-2" style="padding-top: 22px;"></div>').appendTo(
			filter_row
		);

		this.item_group_field = frappe.ui.form.make_control({
			parent: col_item_group,
			df: {
				fieldtype: "Link",
				options: "Item Group",
				fieldname: "item_group",
				label: "Item Group",
			},
			render_input: true,
		});

		this.from_date_field = frappe.ui.form.make_control({
			parent: col_from,
			df: {
				fieldtype: "Date",
				fieldname: "from_date",
				label: "จากวันที่",
			},
			render_input: true,
		});

		this.to_date_field = frappe.ui.form.make_control({
			parent: col_to,
			df: {
				fieldtype: "Date",
				fieldname: "to_date",
				label: "ถึงวันที่",
			},
			render_input: true,
		});

		this.calc_btn = $(
			'<button class="btn btn-primary btn-sm">คำนวณ</button>'
		).appendTo(col_btn);
		this.calc_btn.on("click", () => this.calculate());

		this.export_btn = $(
			'<button class="btn btn-default btn-sm">Export CSV</button>'
		).appendTo(col_export);
		this.export_btn.on("click", () => this.export_csv());
		this.export_btn.hide();
	}

	make_table_area() {
		this.summary_area = $('<div style="margin-bottom: 10px; color: #8D99A6;"></div>').appendTo(
			this.page.body
		);
		this.table_wrapper = $('<div></div>').appendTo(this.page.body);
	}

	calculate() {
		const item_group = this.item_group_field.get_value();
		const from_date = this.from_date_field.get_value();
		const to_date = this.to_date_field.get_value();

		if (!from_date || !to_date) {
			frappe.msgprint("กรุณาระบุช่วงวันที่ให้ครบถ้วน");
			return;
		}

		frappe.dom.freeze("กำลังคำนวณ...");
		frappe
			.call({
				method: REORDER_METHOD,
				args: {
					from_date: from_date,
					to_date: to_date,
					item_group: item_group || null,
				},
			})
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
			this.summary_area.html("ไม่พบข้อมูลการใช้ในช่วงวันที่ที่เลือก");
			this.table_wrapper.empty();
			this.export_btn.hide();
			return;
		}

		const below_count = data.filter((d) => d.below_reorder_point).length;
		this.summary_area.html(
			`พบ ${data.length} รายการ | <span style="color: #e24c4c; font-weight: bold;">ต่ำกว่าจุดสั่งซื้อ ${below_count} รายการ</span>`
		);

		const columns = [
			{ name: "Item Code", editable: false, width: 130 },
			{ name: "Item Name", editable: false, width: 180 },
			{ name: "Avg Daily Usage", editable: false, width: 120 },
			{ name: "Max Daily Usage", editable: false, width: 120 },
			{ name: "Avg Lead Time (d)", editable: false, width: 130 },
			{ name: "Max Lead Time (d)", editable: false, width: 130 },
			{ name: "Safety Stock", editable: false, width: 110 },
			{ name: "Reorder Point", editable: false, width: 120 },
			{ name: "Current Stock", editable: false, width: 120 },
			{ name: "สถานะ", editable: false, width: 140 },
		];

		const rows = data.map((d) => [
			d.item_code,
			d.item_name,
			d.avg_daily_usage,
			d.max_daily_usage,
			d.avg_lead_time,
			d.max_lead_time,
			d.safety_stock,
			d.reorder_point,
			d.current_stock,
			d.below_reorder_point ? "ต่ำกว่าจุดสั่งซื้อ" : "ปกติ",
		]);

		this.table_wrapper.empty();

		if (!this.datatable) {
			this.datatable = new frappe.DataTable(this.table_wrapper.get(0), {
				columns: columns,
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
		if (!this.current_data || !this.current_data.length) return;

		const header = [
			"Item Code",
			"Item Name",
			"Avg Daily Usage",
			"Max Daily Usage",
			"Avg Lead Time",
			"Max Lead Time",
			"Safety Stock",
			"Reorder Point",
			"Current Stock",
			"Status",
		];

		const lines = [header.join(",")];
		this.current_data.forEach((d) => {
			lines.push(
				[
					d.item_code,
					`"${d.item_name}"`,
					d.avg_daily_usage,
					d.max_daily_usage,
					d.avg_lead_time,
					d.max_lead_time,
					d.safety_stock,
					d.reorder_point,
					d.current_stock,
					d.below_reorder_point ? "Below Reorder Point" : "OK",
				].join(",")
			);
		});

		const csv_content = lines.join("\n");
		const blob = new Blob([csv_content], { type: "text/csv;charset=utf-8;" });
		const link = document.createElement("a");
		link.href = URL.createObjectURL(blob);
		link.download = `reorder_point_${frappe.datetime.get_today()}.csv`;
		link.click();
	}
}
