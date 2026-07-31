frappe.pages['belt-length-calculator'].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Belt Length Calculator',
        single_column: true
    });

    new BeltLengthCalculator(wrapper, page);
};

class BeltLengthCalculator {

    static MM_PER_INCH = 25.4;

    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page = page;
        this.$body = $(this.wrapper).find('.layout-main-section');

        // เก็บหน่วยก่อนหน้า เพื่อใช้แปลงค่าจริงตอนสลับหน่วย
        this.prev_pulley_unit = 'mm';
        this.prev_center_unit = 'mm';

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
                        ใช้คำนวณความยาวสายพาน (V-belt แบบ Open Belt) จากขนาด Pulley และระยะห่างศูนย์กลาง
                    </p>

                    <h5 class="diagram-title">แผนภาพประกอบการวัด</h5>
                    <div class="belt-diagram-box" id="belt_diagram"></div>
                </div>

                <div class="belt-calc-card mt-3">
                    <h4>หน่วยและการปัดเศษ</h4>
                    <div class="row">
                        <div class="col-md-3">
                            <label>หน่วย Pulley (D1, D2)</label>
                            <select class="form-control" id="pulley_unit">
                                <option value="mm">mm</option>
                                <option value="inch">inch</option>
                            </select>
                        </div>

                        <div class="col-md-3">
                            <label>หน่วย Center Distance</label>
                            <select class="form-control" id="center_unit">
                                <option value="mm">mm</option>
                                <option value="inch">inch</option>
                            </select>
                        </div>

                        <div class="col-md-3">
                            <label>หน่วยผลลัพธ์</label>
                            <select class="form-control" id="result_unit">
                                <option value="mm">mm</option>
                                <option value="inch">inch</option>
                            </select>
                        </div>

                        <div class="col-md-3">
                            <label>ปัดเศษทศนิยม</label>
                            <select class="form-control" id="rounding">
                                <option value="2">2 ตำแหน่ง</option>
                                <option value="1">1 ตำแหน่ง</option>
                                <option value="0">ไม่มีทศนิยม</option>
                            </select>
                        </div>
                    </div>

                    <hr>

                    <div class="row">
                        <div class="col-md-4">
                            <label>Large Pulley Diameter (D1) — <span class="unit-tag" id="pulley_unit_label1">mm</span></label>
                            <input type="number" class="form-control calc-input" id="large_diameter" value="200" min="0" step="0.01">
                        </div>

                        <div class="col-md-4">
                            <label>Small Pulley Diameter (D2) — <span class="unit-tag" id="pulley_unit_label2">mm</span></label>
                            <input type="number" class="form-control calc-input" id="small_diameter" value="100" min="0" step="0.01">
                        </div>

                        <div class="col-md-4">
                            <label>Center Distance (C) — <span class="unit-tag" id="center_unit_label">mm</span></label>
                            <input type="number" class="form-control calc-input" id="center_distance" value="500" min="0" step="0.01">
                        </div>
                    </div>

                    <div class="belt-result-box">
                        <div class="result-label">Belt Length</div>
                        <div class="result-value" id="belt_length">-</div>
                        <div class="result-unit" id="result_unit_display">mm</div>
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

                .diagram-title {
                    margin-top: 10px;
                    margin-bottom: 10px;
                }

                .belt-diagram-box {
                    background: var(--bg-light-gray);
                    border: 1px solid var(--border-color);
                    border-radius: 8px;
                    padding: 10px;
                    text-align: center;
                }

                .belt-diagram-box svg {
                    max-width: 85%;
                    height: auto;
                }

                .unit-tag {
                    font-weight: 700;
                    color: var(--text-muted);
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
        this.$body.on('input change', '.calc-input, #result_unit, #rounding', () => {
            this.calculate();
        });

        this.$body.on('change', '#pulley_unit', (e) => {
            this.convert_unit_group(
                ['large_diameter', 'small_diameter'],
                this.prev_pulley_unit,
                e.target.value
            );
            this.prev_pulley_unit = e.target.value;
            this.calculate();
        });

        this.$body.on('change', '#center_unit', (e) => {
            this.convert_unit_group(
                ['center_distance'],
                this.prev_center_unit,
                e.target.value
            );
            this.prev_center_unit = e.target.value;
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

    // ---------- unit helpers ----------

    to_mm(value, unit) {
        return unit === 'inch' ? value * BeltLengthCalculator.MM_PER_INCH : value;
    }

    from_mm(value_mm, unit) {
        return unit === 'inch' ? value_mm / BeltLengthCalculator.MM_PER_INCH : value_mm;
    }

    // แปลงค่าตัวเลขในช่อง input จริง เมื่อผู้ใช้สลับหน่วย (ไม่ใช่แค่เปลี่ยน label)
    convert_unit_group(field_ids, old_unit, new_unit) {
        if (old_unit === new_unit) return;

        field_ids.forEach((id) => {
            const raw = this.get_value(id);
            if (!raw) return;
            const value_mm = this.to_mm(raw, old_unit);
            const converted = this.from_mm(value_mm, new_unit);
            this.$body.find(`#${id}`).val(this.round_clean(converted));
        });
    }

    round_clean(value) {
        // ปัดเศษให้อ่านง่ายตอนแปลงหน่วย โดยไม่ตัดความแม่นยำเกินจำเป็น
        return Math.round(value * 10000) / 10000;
    }

    get_value(id) {
        return flt(this.$body.find(`#${id}`).val());
    }

    clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    // ---------- calculation ----------

    calculate() {
        const pulley_unit = this.$body.find('#pulley_unit').val();
        const center_unit = this.$body.find('#center_unit').val();
        const result_unit = this.$body.find('#result_unit').val();
        const rounding = cint(this.$body.find('#rounding').val());

        // อัปเดตป้ายหน่วยข้าง label และผลลัพธ์
        this.$body.find('#pulley_unit_label1').text(pulley_unit);
        this.$body.find('#pulley_unit_label2').text(pulley_unit);
        this.$body.find('#center_unit_label').text(center_unit);
        this.$body.find('#result_unit_display').text(result_unit);

        const D1 = this.get_value('large_diameter');
        const D2 = this.get_value('small_diameter');
        const C = this.get_value('center_distance');

        const $warning = this.$body.find('#warning_message');
        const $result = this.$body.find('#belt_length');
        const $formula = this.$body.find('#formula_text');

        $warning.text('');

        // คำนวณทุกอย่างเป็น mm ภายใน เพื่อให้ผสมหน่วยกันได้ถูกต้องเสมอ
        const D1_mm = this.to_mm(D1, pulley_unit);
        const D2_mm = this.to_mm(D2, pulley_unit);
        const C_mm = this.to_mm(C, center_unit);

        // วาดแผนภาพเสมอ แม้ยังไม่มีค่าที่ใช้งานได้ (ใช้ค่าตัวอย่างแทน)
        const diagram_valid = D1_mm > 0 && D2_mm > 0 && C_mm > 0;
        this.render_diagram(
            diagram_valid ? D1_mm : 200,
            diagram_valid ? D2_mm : 100,
            diagram_valid ? C_mm : 500,
            diagram_valid ? `${D1.toFixed(2)} ${pulley_unit}` : '-',
            diagram_valid ? `${D2.toFixed(2)} ${pulley_unit}` : '-',
            diagram_valid ? `${C.toFixed(2)} ${center_unit}` : '-'
        );

        if (!D1 || !D2 || !C) {
            $result.text('-');
            $formula.text('');
            return;
        }

        if (D1 <= 0 || D2 <= 0 || C <= 0) {
            $warning.text('ค่าทุกตัวต้องมากกว่า 0');
            $result.text('-');
            $formula.text('');
            return;
        }

        // Pulley สองลูกจะชนกันทางกายภาพถ้า C <= (D1+D2)/2 (ตรวจในหน่วย mm เสมอ)
        if (C_mm <= (D1_mm + D2_mm) / 2) {
            $warning.text('Center Distance สั้นเกินไป — Pulley ทั้งสองลูกจะชนกันทางกายภาพ (ต้องมากกว่า (D1+D2)/2)');
            $result.text('-');
            $formula.text('');
            return;
        }

        const L_mm = (2 * C_mm) + ((Math.PI / 2) * (D1_mm + D2_mm)) + (Math.pow(D1_mm - D2_mm, 2) / (4 * C_mm));
        const L_result = this.from_mm(L_mm, result_unit);

        const formula =
`Open Belt (V-belt):
L = 2C + π/2(D1 + D2) + (D1 - D2)² / 4C

D1 = ${D1_mm.toFixed(2)} mm  (${D1} ${pulley_unit})
D2 = ${D2_mm.toFixed(2)} mm  (${D2} ${pulley_unit})
C  = ${C_mm.toFixed(2)} mm  (${C} ${center_unit})

L = ${L_mm.toFixed(2)} mm = ${L_result.toFixed(rounding)} ${result_unit}`;

        $result.text(L_result.toFixed(rounding));
        $formula.text(formula);
    }

    // ---------- diagram ----------

    render_diagram(D1_mm, D2_mm, C_mm, d1_label, d2_label, c_label) {
        const svgW = 600;
        const svgH = 280;
        const padding = 100;
        const drawableW = svgW - (padding * 2);

        const r1_mm = D1_mm / 2;
        const r2_mm = D2_mm / 2;
        const world_span = C_mm + r1_mm + r2_mm;
        const scale = world_span > 0 ? drawableW / world_span : 1;

        const MIN_R = 14;
        const MAX_R = 95;
        const radius1 = this.clamp(r1_mm * scale, MIN_R, MAX_R);
        const radius2 = this.clamp(r2_mm * scale, MIN_R, MAX_R);

        const centerY = 130;
        const x1 = padding + radius1;
        const x2 = x1 + (C_mm * scale);
        const d_px = x2 - x1;

        const raw_alpha = d_px > 0 ? (radius1 - radius2) / d_px : 0;
        const alpha = Math.asin(this.clamp(raw_alpha, -1, 1));

        const p1_up = { x: x1 + radius1 * Math.sin(alpha), y: centerY - radius1 * Math.cos(alpha) };
        const p2_up = { x: x2 + radius2 * Math.sin(alpha), y: centerY - radius2 * Math.cos(alpha) };
        const p1_dn = { x: x1 - radius1 * Math.sin(alpha), y: centerY + radius1 * Math.cos(alpha) };
        const p2_dn = { x: x2 - radius2 * Math.sin(alpha), y: centerY + radius2 * Math.cos(alpha) };

        const dimY = centerY + Math.max(radius1, radius2) + 40;

        const svg = `
<svg viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
    <defs>
        <marker id="arrow_start" markerWidth="8" markerHeight="8" refX="1" refY="4" orient="auto">
            <path d="M7,1 L1,4 L7,7" fill="none" stroke="#555" stroke-width="1.2"/>
        </marker>
        <marker id="arrow_end" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M1,1 L7,4 L1,7" fill="none" stroke="#555" stroke-width="1.2"/>
        </marker>
    </defs>

    <!-- เส้นศูนย์กลาง (reference) -->
    <line x1="${x1}" y1="${centerY}" x2="${x2}" y2="${centerY}" stroke="#bbb" stroke-width="1" stroke-dasharray="4,3"/>

    <!-- สายพาน (Belt) -->
    <line x1="${p1_up.x.toFixed(2)}" y1="${p1_up.y.toFixed(2)}" x2="${p2_up.x.toFixed(2)}" y2="${p2_up.y.toFixed(2)}" stroke="#c0392b" stroke-width="4"/>
    <line x1="${p1_dn.x.toFixed(2)}" y1="${p1_dn.y.toFixed(2)}" x2="${p2_dn.x.toFixed(2)}" y2="${p2_dn.y.toFixed(2)}" stroke="#c0392b" stroke-width="4"/>

    <!-- Pulley ใหญ่ (D1) -->
    <circle cx="${x1}" cy="${centerY}" r="${radius1.toFixed(2)}" fill="#eef3fa" stroke="#2c3e50" stroke-width="3"/>
    <circle cx="${x1}" cy="${centerY}" r="3" fill="#2c3e50"/>

    <!-- Pulley เล็ก (D2) -->
    <circle cx="${x2.toFixed(2)}" cy="${centerY}" r="${radius2.toFixed(2)}" fill="#eef3fa" stroke="#2c3e50" stroke-width="3"/>
    <circle cx="${x2.toFixed(2)}" cy="${centerY}" r="3" fill="#2c3e50"/>

    <!-- Dimension D1 (ซ้ายของวงกลมใหญ่) -->
    <line x1="${(x1 - radius1 - 18).toFixed(2)}" y1="${(centerY - radius1).toFixed(2)}" x2="${(x1 - radius1 - 18).toFixed(2)}" y2="${(centerY + radius1).toFixed(2)}"
        stroke="#555" stroke-width="1.2" marker-start="url(#arrow_start)" marker-end="url(#arrow_end)"/>
    <text x="${(x1 - radius1 - 24).toFixed(2)}" y="${(centerY - 6).toFixed(2)}" text-anchor="end" font-size="11" font-weight="600" fill="#2c3e50">D1</text>
    <text x="${(x1 - radius1 - 24).toFixed(2)}" y="${(centerY + 9).toFixed(2)}" text-anchor="end" font-size="11" fill="#2c3e50">${d1_label}</text>

    <!-- Dimension D2 (ขวาของวงกลมเล็ก) -->
    <line x1="${(x2 + radius2 + 18).toFixed(2)}" y1="${(centerY - radius2).toFixed(2)}" x2="${(x2 + radius2 + 18).toFixed(2)}" y2="${(centerY + radius2).toFixed(2)}"
        stroke="#555" stroke-width="1.2" marker-start="url(#arrow_start)" marker-end="url(#arrow_end)"/>
    <text x="${(x2 + radius2 + 24).toFixed(2)}" y="${(centerY - 6).toFixed(2)}" text-anchor="start" font-size="11" font-weight="600" fill="#2c3e50">D2</text>
    <text x="${(x2 + radius2 + 24).toFixed(2)}" y="${(centerY + 9).toFixed(2)}" text-anchor="start" font-size="11" fill="#2c3e50">${d2_label}</text>

    <!-- Dimension C (ระยะห่างศูนย์กลาง) -->
    <line x1="${x1}" y1="${centerY.toFixed(2)}" x2="${x1}" y2="${dimY.toFixed(2)}" stroke="#bbb" stroke-width="1"/>
    <line x1="${x2.toFixed(2)}" y1="${centerY.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${dimY.toFixed(2)}" stroke="#bbb" stroke-width="1"/>
    <line x1="${x1}" y1="${dimY.toFixed(2)}" x2="${x2.toFixed(2)}" y2="${dimY.toFixed(2)}"
        stroke="#555" stroke-width="1.2" marker-start="url(#arrow_start)" marker-end="url(#arrow_end)"/>
    <text x="${((x1 + x2) / 2).toFixed(2)}" y="${(dimY + 18).toFixed(2)}" text-anchor="middle" font-size="11" fill="#2c3e50">
        C: ${c_label}
    </text>

    <!-- Legend -->
    <line x1="20" y1="${svgH - 16}" x2="45" y2="${svgH - 16}" stroke="#c0392b" stroke-width="4"/>
    <text x="50" y="${svgH - 12}" font-size="12" fill="#555">= แนวสายพาน (Belt)</text>
</svg>`;

        this.$body.find('#belt_diagram').html(svg);
    }

    // ---------- actions ----------

    copy_result() {
        const result = this.$body.find('#belt_length').text();
        const unit = this.$body.find('#result_unit').val();

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
        }).catch(() => {
            frappe.msgprint('ไม่สามารถ copy ได้ กรุณาคัดลอกด้วยตนเอง: ' + text);
        });
    }

    reset_value() {
        this.$body.find('#pulley_unit').val('mm');
        this.$body.find('#center_unit').val('mm');
        this.$body.find('#result_unit').val('mm');
        this.$body.find('#rounding').val('2');
        this.$body.find('#large_diameter').val(200);
        this.$body.find('#small_diameter').val(100);
        this.$body.find('#center_distance').val(500);

        this.prev_pulley_unit = 'mm';
        this.prev_center_unit = 'mm';

        this.calculate();
    }

    create_repair_note() {
        const result = this.$body.find('#belt_length').text();
        const result_unit = this.$body.find('#result_unit').val();

        if (!result || result === '-') {
            frappe.msgprint('กรุณาคำนวณก่อนสร้าง Note');
            return;
        }

        const D1 = this.get_value('large_diameter');
        const D2 = this.get_value('small_diameter');
        const C = this.get_value('center_distance');
        const pulley_unit = this.$body.find('#pulley_unit').val();
        const center_unit = this.$body.find('#center_unit').val();

        const note = `
Belt Length Calculation (Open Belt)

Large Pulley Diameter (D1): ${D1} ${pulley_unit}
Small Pulley Diameter (D2): ${D2} ${pulley_unit}
Center Distance (C): ${C} ${center_unit}

Calculated Belt Length: ${result} ${result_unit}
        `.trim();

        frappe.msgprint({
            title: __('Repair Note'),
            message: `<pre>${frappe.utils.escape_html(note)}</pre>`,
            wide: true
        });
    }
}
