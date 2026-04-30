frappe.ui.form.on("Customer", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button("Purchase Heatmap", () => {
            show_customer_purchase_heatmap(frm);
        });
    }
});


function show_customer_purchase_heatmap(frm) {
    const year = new Date().getFullYear();

    frappe.call({
        method: "repair_management.api.get_customer_purchase_heatmap",
        args: {
            customer: frm.doc.name,
            year: year
        },
        freeze: true,
        freeze_message: "Loading purchase heatmap...",
        callback(r) {
            const res = r.message;

            if (!res) {
                frappe.msgprint("No response from server");
                return;
            }

            show_heatmap_dialog(frm, res);
        },
        error(err) {
            console.error("Heatmap Error:", err);
            frappe.msgprint("Error loading heatmap. Please check Console.");
        }
    });
}


function show_heatmap_dialog(frm, res) {
    const dialog = new frappe.ui.Dialog({
        title: `Purchase Heatmap - ${frm.doc.customer_name || frm.doc.name}`,
        size: "extra-large",
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "heatmap_html"
            }
        ]
    });

    dialog.show();

    dialog.$wrapper.find(".modal-dialog").css({
        "max-width": "1150px",
        "width": "92vw"
    });

    dialog.$wrapper.find(".modal-body").css({
        "overflow-x": "hidden"
    });

    const chart_id = `customer-purchase-heatmap-${frappe.utils.get_random(8)}`;
    const total_amount = format_currency(res.total_amount || 0);

    dialog.fields_dict.heatmap_html.$wrapper.html(`
        <div style="padding: 10px 5px;">
            <div style="
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
                margin-bottom: 18px;
            ">
                <div style="background:#f8f9fa; padding:10px 14px; border-radius:8px; min-width:110px;">
                    <div style="font-size:12px; color:#6c757d;">Year</div>
                    <div style="font-size:18px; font-weight:600;">${res.year}</div>
                </div>

                <div style="background:#f8f9fa; padding:10px 14px; border-radius:8px; min-width:130px;">
                    <div style="font-size:12px; color:#6c757d;">Total Invoices</div>
                    <div style="font-size:18px; font-weight:600;">${res.total_invoices}</div>
                </div>

                <div style="background:#f8f9fa; padding:10px 14px; border-radius:8px; min-width:160px;">
                    <div style="font-size:12px; color:#6c757d;">Active Purchase Days</div>
                    <div style="font-size:18px; font-weight:600;">${res.total_invoice_days}</div>
                </div>

                <div style="background:#f8f9fa; padding:10px 14px; border-radius:8px; min-width:150px;">
                    <div style="font-size:12px; color:#6c757d;">Total Amount</div>
                    <div style="font-size:18px; font-weight:600;">${total_amount}</div>
                </div>
            </div>

            <div style="
                width:100%;
                overflow-x:auto;
                overflow-y:hidden;
                padding-bottom:12px;
            ">
                <div id="${chart_id}" style="
                    min-height:220px;
                    min-width:980px;
                    width:980px;
                "></div>
            </div>
        </div>
    `);

    if (!res.dataPoints || Object.keys(res.dataPoints).length === 0) {
        dialog.fields_dict.heatmap_html.$wrapper.find(`#${chart_id}`).html(`
            <div style="padding:30px; text-align:center; color:#888;">
                No purchase data found for ${res.year}
            </div>
        `);
        return;
    }

    setTimeout(() => {
        new frappe.Chart(`#${chart_id}`, {
            type: "heatmap",
            data: {
                dataPoints: res.dataPoints,
                start: new Date(`${res.year}-01-01`),
                end: new Date(`${res.year}-12-31`)
            },
            height: 175,
            radius: 2,
            discreteDomains: 1
        });
    }, 300);
}
