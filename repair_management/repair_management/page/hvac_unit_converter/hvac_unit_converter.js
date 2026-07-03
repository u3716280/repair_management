frappe.pages["hvac-unit-converter"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "HVAC Unit Converter",
		single_column: true
	});

	new HVACUnitConverter(page);
};

class HVACUnitConverter {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);

		this.airflow_units = {
			cfm: {
				label: "CFM",
				name: "Cubic Feet per Minute",
				to_base: 0.00047194745 // m3/s
			},
			cmh: {
				label: "CMH",
				name: "Cubic Meter per Hour",
				to_base: 1 / 3600 // m3/s
			},
			cms: {
				label: "CMS",
				name: "Cubic Meter per Second",
				to_base: 1 // m3/s
			},
			lps: {
				label: "L/s",
				name: "Liter per Second",
				to_base: 0.001 // m3/s
			}
		};

		this.pressure_units = {
			inwg: {
				label: "in.wg",
				name: "Inch of Water Gauge",
				to_base: 249.08891 // Pa
			},
			pa: {
				label: "Pa",
				name: "Pascal",
				to_base: 1 // Pa
			},
			mmwg: {
				label: "mm.Wg",
				name: "Millimeter of Water Gauge",
				to_base: 9.80665 // Pa
			},
			nm2: {
				label: "N/m²",
				name: "Newton per Square Meter",
				to_base: 1 // Pa
			}
		};

		this.make();
		this.bind_events();
		this.calculate_airflow();
		this.calculate_pressure();
	}

	make() {
		this.wrapper.html(`
			<div class="hvac-unit-converter">
				<div class="row">
					<div class="col-md-12">
						<div class="converter-header">
							<h3>HVAC Unit Converter</h3>
							<p class="text-muted">
								แปลงค่าหน่วยปริมาณลมและแรงดันลม สำหรับงาน HVAC
							</p>
						</div>
					</div>
				</div>

				<div class="row">
					<!-- Airflow Converter -->
					<div class="col-md-6">
						<div class="converter-card">
							<div class="card-title">
								<span class="indicator blue"></span>
								ปริมาณลม
							</div>

							<div class="form-group">
								<label>ค่าตั้งต้น</label>
								<input type="number" class="form-control airflow-value" value="1000" step="any">
							</div>

							<div class="form-group">
								<label>หน่วยตั้งต้น</label>
								<select class="form-control airflow-unit">
									<option value="cfm">CFM</option>
									<option value="cmh">CMH</option>
									<option value="cms">CMS</option>
									<option value="lps">L/s</option>
								</select>
							</div>

							<div class="result-box airflow-result"></div>
						</div>
					</div>

					<!-- Pressure Converter -->
					<div class="col-md-6">
						<div class="converter-card">
							<div class="card-title">
								<span class="indicator orange"></span>
								แรงดันลม
							</div>

							<div class="form-group">
								<label>ค่าตั้งต้น</label>
								<input type="number" class="form-control pressure-value" value="1" step="any">
							</div>

							<div class="form-group">
								<label>หน่วยตั้งต้น</label>
								<select class="form-control pressure-unit">
									<option value="inwg">in.wg</option>
									<option value="pa">Pa</option>
									<option value="mmwg">mm.Wg</option>
									<option value="nm2">N/m²</option>
								</select>
							</div>

							<div class="result-box pressure-result"></div>
						</div>
					</div>
				</div>

				<div class="row">
					<div class="col-md-12">
						<div class="note-box">
							<b>หมายเหตุ:</b>
							แรงดันใช้ค่ามาตรฐานโดยประมาณ:
							1 in.wg = 249.08891 Pa,
							1 mm.Wg = 9.80665 Pa,
							และ 1 Pa = 1 N/m²
						</div>
					</div>
				</div>
			</div>
		`);

		this.add_style();
	}

	add_style() {
		frappe.dom.set_style(`
			.hvac-unit-converter {
				padding: 20px;
			}

			.converter-header {
				margin-bottom: 20px;
			}

			.converter-header h3 {
				margin-top: 0;
				font-weight: 600;
			}

			.converter-card {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 10px;
				padding: 20px;
				margin-bottom: 20px;
				box-shadow: 0 1px 3px rgba(0,0,0,0.06);
			}

			.card-title {
				font-size: 18px;
				font-weight: 600;
				margin-bottom: 18px;
				display: flex;
				align-items: center;
				gap: 8px;
			}

			.result-box {
				margin-top: 18px;
			}

			.result-row {
				display: flex;
				justify-content: space-between;
				align-items: center;
				padding: 10px 12px;
				border-bottom: 1px solid var(--border-color);
			}

			.result-row:last-child {
				border-bottom: none;
			}

			.result-unit {
				font-weight: 600;
			}

			.result-value {
				font-family: monospace;
				font-size: 15px;
			}

			.note-box {
				background: var(--control-bg);
				border: 1px solid var(--border-color);
				border-radius: 8px;
				padding: 12px 15px;
				color: var(--text-muted);
			}

			.indicator.blue {
				background: #2490ef;
			}

			.indicator.orange {
				background: #f59e0b;
			}
		`);
	}

	bind_events() {
		this.wrapper.find(".airflow-value, .airflow-unit").on("input change", () => {
			this.calculate_airflow();
		});

		this.wrapper.find(".pressure-value, .pressure-unit").on("input change", () => {
			this.calculate_pressure();
		});

		this.page.add_inner_button("Reset", () => {
			this.wrapper.find(".airflow-value").val(1000);
			this.wrapper.find(".airflow-unit").val("cfm");

			this.wrapper.find(".pressure-value").val(1);
			this.wrapper.find(".pressure-unit").val("inwg");

			this.calculate_airflow();
			this.calculate_pressure();
		});
	}

	calculate_airflow() {
		const value = flt(this.wrapper.find(".airflow-value").val());
		const from_unit = this.wrapper.find(".airflow-unit").val();

		const base_value = value * this.airflow_units[from_unit].to_base;
		const html = this.render_results(base_value, this.airflow_units);

		this.wrapper.find(".airflow-result").html(html);
	}

	calculate_pressure() {
		const value = flt(this.wrapper.find(".pressure-value").val());
		const from_unit = this.wrapper.find(".pressure-unit").val();

		const base_value = value * this.pressure_units[from_unit].to_base;
		const html = this.render_results(base_value, this.pressure_units);

		this.wrapper.find(".pressure-result").html(html);
	}

	render_results(base_value, units) {
		let html = "";

		Object.keys(units).forEach((key) => {
			const unit = units[key];
			const converted_value = base_value / unit.to_base;

			html += `
				<div class="result-row">
					<div>
						<div class="result-unit">${unit.label}</div>
						<div class="text-muted small">${unit.name}</div>
					</div>
					<div class="result-value">${this.format_number(converted_value)}</div>
				</div>
			`;
		});

		return html;
	}

	format_number(value) {
		if (!isFinite(value)) {
			return "0";
		}

		if (Math.abs(value) >= 1000) {
			return value.toLocaleString(undefined, {
				maximumFractionDigits: 2
			});
		}

		if (Math.abs(value) >= 1) {
			return value.toLocaleString(undefined, {
				maximumFractionDigits: 4
			});
		}

		return value.toLocaleString(undefined, {
			maximumFractionDigits: 8
		});
	}
}
