frappe.pages['belt-length-calculator'].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Belt Length Calculator',
        single_column: true
    });

    new BeltLengthCalculator(wrapper, page);
};

class BeltLengthCalculator {
    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page = page;
        this.$body = $(this.wrapper).find('.layout-main-section');

        this.render();
        this.bind_events();
        this.calculate();
    }

    render() {
        this.$body.html(`
            <div class="belt-calc-container">
                <div class="belt-calc-card">
                    <h3>Belt Length Calculator</h3>
                    <p class="text-muted">
                        ใช้คำนวณความยาวสายพานจากขนาด Pulley และระยะห่างศูนย์กลาง
                    </p>

                    <div class="row">
                        <div class="col-md-4">
                            <label>Drive Type</label>
                            <select class="form-control" id="drive_type">
                                <option value="open">Open Belt</option>
                                <option value="cross">Cross Belt</option>
                            </select>
                        </div>

                        <div class="col-md-4">
                            <label>Unit</label>
                            <select class="form-control" id="unit">
                                <option value="mm">mm</option>
                                <option value="inch">inch</option>
                            </select>
                        </div>

                        <div class="col-md-4">
                            <label>Round Result</label>
                            <select class="form-control" id="rounding">
                                <option value="2">2 Decimal</option>
                                <option value="1">1 Decimal</option>
                                <option value="0">No Decimal</option>
                            </select>
                        </div>
                    </div>

                    <hr>

                    <div class="row">
                        <div class="col-md-4">
                            <label>Large Pulley Diameter</label>
                            <input type="number" class="form-control calc-input" id="large_diameter" value="200" min="0" step="0.01">
                        </div>

                        <div class="col-md-4">
                            <label>Small Pulley Diameter</label>
                            <input type="number" class="form-control calc-input" id="small_diameter" value="100" min="0" step="0.01">
                        </div>

                        <div class="col-md-4">
                            <label>Center Distance</label>
                            <input type="number" class="form-control calc-input" id="center_distance" value="500" min="0" step="0.01">
                        </div>
                    </div>

                    <div class="belt-result-box">
                        <div class="result-label">Belt Length</div>
                        <div class="result-value" id="belt_length">-</div>
                        <div class="result-unit" id="result_unit">mm</div>
                    </div>

                    <div class="belt-warning text-danger" id="warning_message"></div>

                    <hr>

                    <div class="row">
                        <div class="col-md-6">
                            <button class="btn btn-primary" id="copy_result">
                                Copy Result
                            </button>

                            <button class="btn btn-default" id="reset_value">
                                Reset
                            </button>
                        </div>

                        <div class="col-md-6 text-right">
                            <button class="btn btn-default" id="create_note">
                                Create Repair Note
                            </button>
                        </div>
                    </div>
                </div>

                <div class="belt-calc-card mt-3">
                    <h4>Formula</h4>
                    <pre id="formula_text"></pre>
                </div>
            </div>
        `);

        this.add_styles();
    }

    add_styles() {
        if ($('#belt-calc-style').length) return;

        $('head').append(`
            <style id="belt-calc-style">
                .belt-calc-container {
                    max-width: 1100px;
                    margin: 0 auto;
                    padding: 15px;
                }

                .belt-calc-card {
                    background: var(--card-bg);
                    border: 1px solid var(--border-color);
                    border-radius: 10px;
                    padding: 20px;
                    box-shadow: var(--shadow-sm);
                }

                .belt-calc-card label {
                    font-weight: 600;
                    margin-bottom: 6px;
                }

                .belt-result-box {
                    margin-top: 25px;
                    padding: 25px;
                    border-radius: 10px;
                    text-align: center;
                    background: var(--bg-light-gray);
                    border: 1px solid var(--border-color);
                }

                .result-label {
                    font-size: 14px;
                    color: var(--text-muted);
                }

                .result-value {
                    font-size: 42px;
                    font-weight: 700;
                    margin-top: 5px;
                }

                .result-unit {
                    font-size: 18px;
                    color: var(--text-muted);
                }

                .belt-warning {
                    margin-top: 15px;
                    font-weight: 600;
                }

                #formula_text {
                    background: var(--bg-light-gray);
                    padding: 15px;
                    border-radius: 8px;
                    border: 1px solid var(--border-color);
                }
            </style>
        `);
    }

    bind_events() {
        this.$body.on('input change', '.calc-input, #drive_type, #unit, #rounding', () => {
            this.calculate();
        });

        this.$body.on('click', '#copy_result', () => {
            this.copy_result();
        });

        this.$body.on('click', '#reset_value', () => {
            this.reset_value();
        });

        this.$body.on('click', '#create_note', () => {
            this.create_repair_note();
        });
    }

    get_value(id) {
        return flt(this.$body.find(`#${id}`).val());
    }

    calculate() {
        const drive_type = this.$body.find('#drive_type').val();
        const unit = this.$body.find('#unit').val();
        const rounding = cint(this.$body.find('#rounding').val());

        const D1 = this.get_value('large_diameter');
        const D2 = this.get_value('small_diameter');
        const C = this.get_value('center_distance');

        const $warning = this.$body.find('#warning_message');
        const $result = this.$body.find('#belt_length');
        const $unit = this.$body.find('#result_unit');
        const $formula = this.$body.find('#formula_text');

        $warning.text('');
        $unit.text(unit);

        if (!D1 || !D2 || !C) {
            $result.text('-');
            return;
        }

        if (D1 <= 0 || D2 <= 0 || C <= 0) {
            $warning.text('ค่าทุกตัวต้องมากกว่า 0');
            $result.text('-');
            return;
        }

        if (drive_type === 'open' && C <= Math.abs(D1 - D2) / 2) {
            $warning.text('Center Distance สั้นเกินไปเมื่อเทียบกับขนาด Pulley');
            $result.text('-');
            return;
        }

        let L = 0;
        let formula = '';

        if (drive_type === 'open') {
            L = (2 * C) + ((Math.PI / 2) * (D1 + D2)) + (Math.pow(D1 - D2, 2) / (4 * C));

            formula =
`Open Belt:
L = 2C + π/2(D1 + D2) + (D1 - D2)² / 4C

D1 = ${D1} ${unit}
D2 = ${D2} ${unit}
C  = ${C} ${unit}

L = ${L.toFixed(rounding)} ${unit}`;
        }

        if (drive_type === 'cross') {
            L = (2 * C) + ((Math.PI / 2) * (D1 + D2)) + (Math.pow(D1 + D2, 2) / (4 * C));

            formula =
`Cross Belt:
L = 2C + π/2(D1 + D2) + (D1 + D2)² / 4C

D1 = ${D1} ${unit}
D2 = ${D2} ${unit}
C  = ${C} ${unit}

L = ${L.toFixed(rounding)} ${unit}`;
        }

        $result.text(L.toFixed(rounding));
        $formula.text(formula);
    }

    copy_result() {
        const result = this.$body.find('#belt_length').text();
        const unit = this.$body.find('#unit').val();

        if (!result || result === '-') {
            frappe.msgprint('ยังไม่มีผลลัพธ์ให้ copy');
            return;
        }

        const text = `Belt Length = ${result} ${unit}`;

        navigator.clipboard.writeText(text).then(() => {
            frappe.show_alert({
                message: __('Copied'),
                indicator: 'green'
            });
        });
    }

    reset_value() {
        this.$body.find('#drive_type').val('open');
        this.$body.find('#unit').val('mm');
        this.$body.find('#rounding').val('2');
        this.$body.find('#large_diameter').val(200);
        this.$body.find('#small_diameter').val(100);
        this.$body.find('#center_distance').val(500);
        this.calculate();
    }

    create_repair_note() {
        const result = this.$body.find('#belt_length').text();
        const unit = this.$body.find('#unit').val();

        if (!result || result === '-') {
            frappe.msgprint('กรุณาคำนวณก่อนสร้าง Note');
            return;
        }

        const D1 = this.get_value('large_diameter');
        const D2 = this.get_value('small_diameter');
        const C = this.get_value('center_distance');
        const drive_type = this.$body.find('#drive_type option:selected').text();

        const note = `
Belt Length Calculation

Drive Type: ${drive_type}
Large Pulley Diameter: ${D1} ${unit}
Small Pulley Diameter: ${D2} ${unit}
Center Distance: ${C} ${unit}

Calculated Belt Length: ${result} ${unit}
        `.trim();

        frappe.msgprint({
            title: __('Repair Note'),
            message: `<pre>${frappe.utils.escape_html(note)}</pre>`,
            wide: true
        });
    }
}
