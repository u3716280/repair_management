// Reorder Point Calculator - Frappe Page SPA
const REORDER_METHOD =
	"repair_management.repair_management.page.reorder_point_calcul.reorder_point_calcul.get_reorder_data";

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
		this.set_defaults();
	}

	set_defaults() {
		const to_date = frappe.datetime.get_today();
		this.from_date_field.set_value(frappe.datetime.add_days(to_date, -90));
		this.to_date_field.set_value(to_date);
		this.order_cycle_field.set_value(30);
	}

	make_filters() {
		const filter_row = $('<div class="row" style="margin-bottom: 10px;"></div>').appendTo(
			this.page.body
		);
		const action_row = $('<div class="row" style="margin-bottom: 15px;"></div>').appendTo(
			this.page.body
		);

		this.item_group_field = this.make_control(filter_row, "col-md-3", {
			fieldtype: "Link",
			options: "Item Group",
			fieldname: "item_group",
			label: "Item Group",
		});
		this.warehouse_field = this.make_control(filter_row, "col-md-3", {
			fieldtype: "Link",
			options: "Warehouse",
			fieldname: "warehouse",
			label: "Warehouse / Warehouse Group",
		});
		this.from_date_field = this.make_control(filter_row, "col-md-2", {
			fieldtype: "Date",
			fieldname: "from_date",
			label: "จากวันที่",
		});
		this.to_date_field = this.make_control(filter_row, "col-md-2", {
			fieldtype: "Date",
			fieldname: "to_date",
			label: "ถึงวันที่",
		});
		this.order_cycle_field = this.make_control(filter_row, "col-md-2", {
			fieldtype: "Int",
			fieldname: "order_cycle_days",
			label: "Order Cycle (วัน)",
			min: 0,
		});

		const col_btn = $('<div class="col-md-2" style="padding-top: 22px;"></div>').appendTo(
			action_row
		);
		const col_export = $('<div class="col-md-2" style="padding-top: 22px;"></div>').appendTo(
			action_row
		);

		this.calc_btn = $('<button class="btn btn-primary btn-sm">คำนวณ</button>').appendTo(col_btn);
		this.calc_btn.on("click", () => this.calculate());

		this.export_btn = $('<button class="btn btn-default btn-sm">Export CSV</button>').appendTo(
			col_export
		);
		this.export_btn.on("click", () => this.export_csv());
		this.export_btn.hide();
	}

	make_control(row, column_class, df) {
		const parent = $(`<div class="${column_class}"></div>`).appendTo(row);
		return frappe.ui.form.make_control({ parent, df, render_input: true });
	}

	make_table_area() {
		this.summary_area = $('<div style="margin-bottom: 10px; color: var(--text-muted);"></div>').appendTo(
			this.page.body
		);
		this.table_wrapper = $('<div style="overflow-x: auto;"></div>').appendTo(this.page.body);
	}

	calculate() {
		const from_date = this.from_date_field.get_value();
		const to_date = this.to_date_field.get_value();
		const order_cycle_days = Number(this.order_cycle_field.get_value() || 0);

		if (!from_date || !to_date) {
			frappe.msgprint("กรุณาระบุช่วงวันที่ให้ครบถ้วน");
			return;
		}
		if (order_cycle_days < 0) {
			frappe.msgprint("Order Cycle ต้องไม่น้อยกว่า 0 วัน");
			return;
		}

		frappe.dom.freeze("กำลังคำนวณ...");
		frappe
			.call({
				method: REORDER_METHOD,
				args: {
					from_date,
					to_date,
					item_group: this.item_group_field.get_value() || null,
					warehouse: this.warehouse_field.get_value() || null,
					order_cycle_days,
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
			this.summary_area.html("ไม่พบ Item หรือข้อมูลการใช้ในเงื่อนไขที่เลือก");
			this.table_wrapper.empty();
			this.datatable = null;
			this.export_btn.hide();
			return;
		}

		const order_count = data.filter((d) => d.suggested_order_qty > 0).length;
		const missing_lead = data.filter((d) => d.lead_time <= 0).length;
		this.summary_area.html(
			`พบ ${data.length} รายการ | ` +
				`<span style="color: var(--red-500); font-weight: 600;">ต้องสั่งซื้อ ${order_count} รายการ</span> | ` +
				`<span style="color: var(--orange-500); font-weight: 600;">ไม่มี Lead Time ${missing_lead} รายการ</span>`
		);

		const columns = [
			{
				name: "Item Code",
				editable: false,
				width: 130,
				format: (value) => {
					const escaped = frappe.utils.escape_html(value);
					return `<a href="/app/item/${encodeURIComponent(value)}" target="_blank">${escaped}</a>`;
				},
			},
			{ name: "Item Name", editable: false, width: 180 },
			{ name: "Warehouse", editable: false, width: 160 },
			{ name: "Avg Usage/Day", editable: false, width: 110 },
			{ name: "Max Usage/Day", editable: false, width: 110 },
			{ name: "Lead Time", editable: false, width: 90 },
			{ name: "Safety Stock", editable: false, width: 105 },
			{ name: "Safety Source", editable: false, width: 110 },
			{ name: "Reorder Point", editable: false, width: 110 },
			{ name: "Order Cycle", editable: false, width: 95 },
			{ name: "Target Stock", editable: false, width: 105 },
			{ name: "Actual", editable: false, width: 85 },
			{ name: "Reserved", editable: false, width: 85 },
			{ name: "Available", editable: false, width: 90 },
			{ name: "Waiting Qty", editable: false, width: 100 },
			{ name: "MOQ", editable: false, width: 75 },
			{ name: "Suggested Order", editable: false, width: 125 },
			{ name: "สถานะ", editable: false, width: 145 },
		];

		const rows = data.map((d) => [
			d.item_code,
			d.item_name,
			d.warehouse,
			d.avg_daily_usage,
			d.max_daily_usage,
			d.lead_time,
			d.safety_stock,
			d.safety_stock_source,
			d.reorder_point,
			d.order_cycle_days,
			d.target_stock,
			d.actual_stock,
			d.reserved_stock,
			d.available_stock,
			d.waiting_stock,
			d.minimum_order_qty,
			d.suggested_order_qty,
			d.status,
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
			"Item Code",
			"Item Name",
			"Warehouse",
			"Avg Daily Usage",
			"Max Daily Usage",
			"Lead Time",
			"Safety Stock",
			"Safety Stock Source",
			"Reorder Point",
			"Order Cycle Days",
			"Cycle Demand",
			"Target Stock",
			"Actual Stock",
			"Reserved Stock",
			"Available Stock",
			"Waiting Stock",
			"Minimum Order Qty",
			"Raw Order Qty",
			"Suggested Order Qty",
			"Status",
		];

		const lines = [header.map((value) => this.csv_escape(value)).join(",")];
		this.current_data.forEach((d) => {
			lines.push(
				[
					d.item_code,
					d.item_name,
					d.warehouse,
					d.avg_daily_usage,
					d.max_daily_usage,
					d.lead_time,
					d.safety_stock,
					d.safety_stock_source,
					d.reorder_point,
					d.order_cycle_days,
					d.cycle_demand,
					d.target_stock,
					d.actual_stock,
					d.reserved_stock,
					d.available_stock,
					d.waiting_stock,
					d.minimum_order_qty,
					d.raw_order_qty,
					d.suggested_order_qty,
					d.status,
				]
					.map((value) => this.csv_escape(value))
					.join(",")
			);
		});

		const blob = new Blob(["\ufeff" + lines.join("\n")], {
			type: "text/csv;charset=utf-8;",
		});
		const link = document.createElement("a");
		const object_url = URL.createObjectURL(blob);
		link.href = object_url;
		link.download = `reorder_point_${frappe.datetime.get_today()}.csv`;
		link.click();
		URL.revokeObjectURL(object_url);
	}

	csv_escape(value) {
		const text = value === null || value === undefined ? "" : String(value);
		return `"${text.replace(/"/g, '""')}"`;
	}
}
