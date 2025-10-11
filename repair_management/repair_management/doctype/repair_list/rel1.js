// Copyright (c) 2025, Chirayut D. and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Repair List", {
// 	refresh(frm) {

// 	},
// });
//frappe.ui.form.on("Repair List", {
//	supplier : function(frm) {

//});

frappe.ui.form.on('Repair List', {
  refresh(frm) {
    if (frm.doc.docstatus === 1 && ['In Repair', 'Partial Returned'].includes(frm.doc.status)) {
      frm.add_custom_button(__('Receive Return'), async function () {

        const child_status_options = [
          'In Progress', 'Free', 'Charge', 'No Repair' // จาก Repair Item List:contentReference[oaicite:6]{index=6}
        ];

        // สร้าง HTML ของรายการแถวแบบ checkbox + per-row status select
        const rowsHtml = (frm.doc.items || []).map((it, idx0) => {
          const idx = idx0 + 1;
          const serial = it.serial_no ? frappe.utils.escape_html(it.serial_no).replace(/\n/g, '<br>') : '';
          const sel = `
            <select class="per-row-status" data-idx="${idx}" style="min-width:140px;">
              ${child_status_options.map(o => `<option value="${o}" ${it.status===o?'selected':''}>${o}</option>`).join('')}
            </select>`;
          return `
            <tr>
              <td style="text-align:center;"><input type="checkbox" class="pick-row" data-idx="${idx}" checked></td>
              <td>${idx}</td>
              <td>${frappe.utils.escape_html(it.item_code || '')}</td>
              <td>${frappe.utils.escape_html(it.item_name || '')}</td>
              <td>${frappe.utils.escape_html(String(it.qty||0))}</td>
              <td>${serial}</td>
              <td>${sel}</td>
            </tr>`;
        }).join('');

        const html = `
          <div>
            <div class="flex items-center gap-2" style="margin-bottom:8px;">
              <input type="checkbox" id="use-global" checked>
              <label for="use-global">${__('ใช้สถานะเดียวทั้งชุด')}</label>
              <select id="global-status" style="min-width:160px; margin-left:8px;">
                ${child_status_options.map(o => `<option value="${o}">${o}</option>`).join('')}
              </select>
            </div>
            <div style="max-height:360px; overflow:auto; border:1px solid #e5e5e5; border-radius:6px;">
              <table class="table table-bordered" style="width:100%;">
                <thead>
                  <tr>
                    <th style="width:48px; text-align:center;">
                      <input type="checkbox" id="pick-all" checked>
                    </th>
                    <th style="width:48px;">#</th>
                    <th>${__('Item Code')}</th>
                    <th>${__('Item Name')}</th>
                    <th style="width:80px; text-align:right;">${__('Qty')}</th>
                    <th style="width:220px;">${__('Serial')}</th>
                    <th style="width:170px;">${__('Per-Row Status')}</th>
                  </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
              </table>
            </div>
            <div class="text-muted" style="margin-top:6px;">
              ${__('ติ๊กเลือกแถวที่จะรับกลับ หากปิด "ใช้สถานะเดียวทั้งชุด" ระบบจะใช้สถานะจากคอลัมน์ Per-Row Status ของแต่ละแถว')}
            </div>
          </div>
        `;

        const d = new frappe.ui.Dialog({
          title: __('Receive Return'),
          fields: [
            { fieldname: 'items_html', fieldtype: 'HTML' },
          ],
          primary_action_label: __('Receive'),
          primary_action: async () => {
            const wrapper = d.get_field('items_html').$wrapper;
            const useGlobal = wrapper.find('#use-global').is(':checked');
            const globalStatus = wrapper.find('#global-status').val();

            // เก็บ selected idx
            const selected_idx = [];
            wrapper.find('.pick-row:checked').each((_, el) => {
              selected_idx.push(cint($(el).data('idx')));
            });
            if (!selected_idx.length) {
              frappe.msgprint(__('ไม่ได้เลือกแถวใดเลย')); return;
            }

            // เก็บ per-row status (ถ้าใช้รายแถว)
            let item_status_map = {};
            if (!useGlobal) {
              wrapper.find('.per-row-status').each((_, el) => {
                const idx = String($(el).data('idx'));
                const val = $(el).val();
                // บันทึกเฉพาะแถวที่ถูกเลือก
                if (selected_idx.includes(cint(idx))) {
                  item_status_map[idx] = val;
                }
              });
            }

            await frappe.call({
              method: 'repair_management.repair_management.doctype.repair_list.repair_list.receive_return',
              args: {
                docname: frm.doc.name,
                selected_idx: JSON.stringify(selected_idx),
                item_status_map: JSON.stringify(item_status_map),
                use_global_status: useGlobal ? 1 : 0,
                global_status: useGlobal ? globalStatus : null,
              },
            });
            d.hide();
            await frm.reload_doc();
          }
        });

        d.get_field('items_html').$wrapper.html(html);

        // behaviors
        const wrap = d.get_field('items_html').$wrapper;
        wrap.on('change', '#pick-all', function() {
          const checked = $(this).is(':checked');
          wrap.find('.pick-row').prop('checked', checked);
        });
        d.show();
      }, __('Actions'));
    }
  }
});
