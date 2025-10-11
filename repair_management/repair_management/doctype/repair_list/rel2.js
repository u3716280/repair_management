frappe.ui.form.on('Repair List', {
  refresh(frm) {
    if (frm.doc.docstatus === 1 && ['In Repair', 'Partial Returned'].includes(frm.doc.status)) {
      frm.add_custom_button(__('Receive Return'), async function () {

        const child_status_options = ['In Progress', 'Free', 'Charge', 'No Repair']; // จาก child:contentReference[oaicite:3]{index=3}

        const rowsHtml = (frm.doc.items || []).map((it, idx0) => {
          const idx = idx0 + 1;
          const qty = flt(it.qty || 0);
          const ret = flt(it.returned_qty || 0);
          const remaining = Math.max(qty - ret, 0);
          const serial_raw = (it.serial_no || '').trim();
          const serial_html = frappe.utils.escape_html(serial_raw).replace(/\n/g, '<br>');

          const perRowSel = `
            <select class="per-row-status" data-idx="${idx}" style="min-width:140px;">
              ${child_status_options.map(o => `<option value="${o}" ${it.status===o?'selected':''}>${o}</option>`).join('')}
            </select>`;

          // textarea สำหรับเลือก serial เฉพาะตัว (แก้ไขได้)
          const serialInput = `
            <textarea class="serial-input" data-idx="${idx}" rows="3" style="width:100%;" placeholder="${__('ใส่ Serial ที่จะรับคืน ทีละบรรทัด (ปล่อยว่าง = ใช้โหมดจำนวน)')}"></textarea>
            <div class="text-muted" style="font-size:11px; margin-top:2px;">
              ${__('Serial ทั้งหมดที่ผูกกับแถวนี้ตอนนี้:')}<br>${serial_html || '-'}
            </div>`;

          return `
            <tr>
              <td style="text-align:center;">
                <input type="checkbox" class="pick-row" data-idx="${idx}" ${remaining>0?'checked':''} ${remaining<=0?'disabled':''}>
              </td>
              <td>${idx}</td>
              <td>${frappe.utils.escape_html(it.item_code || '')}</td>
              <td>${frappe.utils.escape_html(it.item_name || '')}</td>
              <td style="text-align:right;">${format_number(qty, null, 2)}</td>
              <td style="text-align:right;">${format_number(ret, null, 2)}</td>
              <td style="text-align:right;" class="remaining" data-idx="${idx}">${format_number(remaining, null, 2)}</td>
              <td style="text-align:right;">
                <input type="number" step="1" min="0" class="receive-qty input-with-feedback" data-idx="${idx}" value="${remaining}">
                <div class="text-muted" style="font-size:11px;">${__('หรือใส่ Serial ด้านล่าง')}</div>
              </td>
              <td>${perRowSel}</td>
            </tr>
            <tr>
              <td></td>
              <td colspan="8">${serialInput}</td>
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
            <div style="max-height:480px; overflow:auto; border:1px solid #e5e5e5; border-radius:6px;">
              <table class="table table-bordered" style="width:100%;">
                <thead>
                  <tr>
                    <th style="width:48px; text-align:center;"><input type="checkbox" id="pick-all" checked></th>
                    <th style="width:48px;">#</th>
                    <th>${__('Item Code')}</th>
                    <th>${__('Item Name')}</th>
                    <th style="width:90px; text-align:right;">${__('Qty')}</th>
                    <th style="width:110px; text-align:right;">${__('Returned Qty')}</th>
                    <th style="width:110px; text-align:right;">${__('Remaining')}</th>
                    <th style="width:160px; text-align:right;">${__('Receive Qty')}</th>
                    <th style="width:170px;">${__('Per-Row Status')}</th>
                  </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
              </table>
            </div>
            <div class="text-muted" style="margin-top:6px;">
              ${__('ถ้ากรอก Serial ในแถวใด ระบบจะ “ใช้จำนวนเท่ากับจำนวน Serial ที่กรอก” และเพิกเฉย Receive Qty ของแถวนั้น')}
            </div>
          </div>
        `;

        const d = new frappe.ui.Dialog({
          title: __('Receive Return'),
          fields: [{ fieldname: 'items_html', fieldtype: 'HTML' }],
          primary_action_label: __('Receive'),
          primary_action: async () => {
            const wrap = d.get_field('items_html').$wrapper;
            const useGlobal = wrap.find('#use-global').is(':checked');
            const globalStatus = wrap.find('#global-status').val();

            const selected_idx = [];
            const qty_map = {};
            const serial_map = {};
            wrap.find('.pick-row:checked').each((_, el) => {
              const idx = cint($(el).data('idx'));
              selected_idx.push(idx);

              const serialText = (wrap.find(`.serial-input[data-idx="${idx}"]`).val() || '').trim();
              if (serialText) {
                serial_map[String(idx)] = serialText;
              } else {
                const remaining = flt(wrap.find(`.remaining[data-idx="${idx}"]`).text() || 0);
                let v = flt(wrap.find(`.receive-qty[data-idx="${idx}"]`).val() || 0);
                v = Math.max(Math.min(v, remaining), 0);
                qty_map[String(idx)] = v;
              }
            });

            if (!selected_idx.length) {
              frappe.msgprint(__('ไม่ได้เลือกแถวใดเลย'));
              return;
            }

            let item_status_map = {};
            if (!useGlobal) {
              wrap.find('.per-row-status').each((_, el) => {
                const idx = String($(el).data('idx'));
                const val = $(el).val();
                if (selected_idx.includes(cint(idx))) item_status_map[idx] = val;
              });
            }

            await frappe.call({
              method: 'repair_management.repair_management.doctype.repair_list.repair_list.receive_return',
              args: {
                docname: frm.doc.name,
                selected_idx: JSON.stringify(selected_idx),
                qty_map: JSON.stringify(qty_map),
                item_status_map: JSON.stringify(item_status_map),
                use_global_status: useGlobal ? 1 : 0,
                global_status: useGlobal ? globalStatus : null,
                serial_map: JSON.stringify(serial_map),
              },
            });
            d.hide();
            await frm.reload_doc();
          }
        });

        d.get_field('items_html').$wrapper.html(html);

        const wrap = d.get_field('items_html').$wrapper;
        wrap.on('change', '#pick-all', function() {
          const checked = $(this).is(':checked');
          wrap.find('.pick-row:not(:disabled)').prop('checked', checked);
        });

        // ถ้าผู้ใช้กรอก serial ในแถว → ล็อก receive-qty ให้เป็นจำนวน serial ที่กรอก (เพื่อ UI สอดคล้อง)
        wrap.on('input', '.serial-input', function() {
          const idx = cint($(this).data('idx'));
          const lines = ($(this).val() || '').split('\n').map(s => s.trim()).filter(Boolean);
          const count = lines.length;
          const rem = flt(wrap.find(`.remaining[data-idx="${idx}"]`).text() || 0);
          if (count > rem) {
            frappe.show_alert({ message: __(`Serial ที่กรอก (${count}) เกิน Remaining (${rem})`), indicator: 'orange' });
          }
          wrap.find(`.receive-qty[data-idx="${idx}"]`).val(count || 0);
        });

        // Clamp qty manual
        wrap.on('input', '.receive-qty', function() {
          const idx = cint($(this).data('idx'));
          if ((wrap.find(`.serial-input[data-idx="${idx}"]`).val() || '').trim()) {
            // ถ้ามี serial list แล้ว ให้จำนวนมาจาก serial เท่านั้น
            const lines = (wrap.find(`.serial-input[data-idx="${idx}"]`).val() || '').split('\n').map(s => s.trim()).filter(Boolean);
            $(this).val(lines.length || 0);
            return;
          }
          const remaining = flt(wrap.find(`.remaining[data-idx="${idx}"]`).text() || 0);
          let v = flt($(this).val() || 0);
          if (v < 0) v = 0;
          if (v > remaining) v = remaining;
          $(this).val(v);
        });

        d.show();
      }, __('Actions'));
    }
  }
});
