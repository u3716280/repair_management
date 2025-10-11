// file: repair_management/repair_management/doctype/repair_list/repair_list.js
frappe.ui.form.on('Repair List', {
  refresh(frm) {
    //if (frm.doc.docstatus === 1 && ['In Repair', 'Partial Returned'].includes(frm.doc.status)) {
      frm.add_custom_button(__('Receive Return (One Page)'), () => open_recv_dialog(frm), __('Actions'));
    //}
  }
});
function open_recv_dialog(frm) {
  let d = new frappe.ui.Dialog({
      title: __('ระบุข้อมูลใหม่'),
      fields: [
          {
              label: __('ชื่อลูกค้า'),
              fieldname: 'customer_name',
              fieldtype: 'Link',
              options: 'Customer',
              reqd: 1
          },
          {
              label: __('จำนวน'),
              fieldname: 'quantity',
              fieldtype: 'Int',
              reqd: 1
          }
      ],
      primary_action_label: __('บันทึก'),
      primary_action(values) {
          console.log(values);
          frappe.msgprint(__('บันทึกข้อมูลเรียบร้อยแล้ว!'));
          d.hide();
      }
  });
  d.show();  
}

function open_receive_dialog(frm) {
  // สถานะของ child.status (อิง Repair Item List):contentReference[oaicite:4]{index=4}
  const CHILD_STATUSES = ['In Progress','Free','Charge','No Repair'];

  const d = new frappe.ui.Dialog({
    title: __('Receive Return'),
    size: 'large',
    fields: [
      { fieldname: 'use_global', fieldtype: 'Check', label: __('ใช้สถานะเดียวทั้งชุด'), default: 1 },
      { fieldname: 'global_status', fieldtype: 'Select', label: __('Global Status'), options: CHILD_STATUSES.join('\n'), default: 'Free' },
      { fieldname: 'divider1', fieldtype: 'Section Break' },
      { fieldname: 'toolbar', fieldtype: 'HTML' },
      { fieldname: 'items_html', fieldtype: 'HTML' },
    ],
    primary_action_label: __('Receive'),
    async primary_action(values) {
      const wrap = d.get_field('items_html').$wrapper;

      // เก็บรายการที่เลือก
      const selected_idx = [];
      const qty_map = {};
      const serial_map = {};
      const item_status_map = {};

      wrap.find('.row-pick:checked').each((_, el) => {
        const idx = cint($(el).data('idx'));
        selected_idx.push(idx);

        const serialText = (wrap.find(`.row-serial[data-idx="${idx}"]`).val() || '').trim();
        if (serialText) {
          serial_map[String(idx)] = serialText; // ถ้ามี serial → โหมด serial picker
        } else {
          const rem = flt(wrap.find(`.row-remaining[data-idx="${idx}"]`).text() || 0);
          let v = flt(wrap.find(`.row-recvqty[data-idx="${idx}"]`).val() || 0);
          v = Math.max(Math.min(v, rem), 0);
          qty_map[String(idx)] = v;
        }

        if (!values.use_global) {
          const perRowStatus = wrap.find(`.row-status[data-idx="${idx}"]`).val();
          if (perRowStatus) item_status_map[String(idx)] = perRowStatus;
        }
      });

      if (!selected_idx.length) {
        frappe.msgprint(__('ไม่ได้เลือกแถวใดเลย'));
        return;
      }

      await frappe.call({
        method: 'repair_management.repair_management.doctype.repair_list.repair_list.receive_return',
        args: {
          docname: frm.doc.name,
          selected_idx: JSON.stringify(selected_idx),
          qty_map: JSON.stringify(qty_map),
          item_status_map: JSON.stringify(item_status_map),
          use_global_status: values.use_global ? 1 : 0,
          global_status: values.use_global ? values.global_status : null,
          serial_map: JSON.stringify(serial_map),
        },
      });

      d.hide();
      await frm.reload_doc();
    },
  });

  // ---------- Toolbar (หน้าเดียวควบคุมได้หมด) ----------
  const toolbar_html = `
    <div class="flex items-center gap-2" style="margin-bottom:8px;">
      <button class="btn btn-xs btn-default" data-action="pick-all">${__('เลือกทั้งหมด')}</button>
      <button class="btn btn-xs btn-default" data-action="unpick-all">${__('ยกเลิกทั้งหมด')}</button>
      <span class="text-muted" style="margin-left:8px;">|</span>
      <button class="btn btn-xs btn-default" data-action="fill-remaining">${__('ใส่ Receive Qty = Remaining')}</button>
      <button class="btn btn-xs btn-default" data-action="apply-global">${__('ตั้ง Per-Row Status = Global')}</button>
    </div>
  `;
  d.get_field('toolbar').$wrapper.html(toolbar_html);

  // ---------- Items Table ----------
  const rows_html = (frm.doc.items || []).map((it, i) => {
    const idx = i + 1;
    const qty = flt(it.qty || 0);
    const returned = flt(it.returned_qty || 0);
    const remaining = Math.max(qty - returned, 0);

    const serial_all = (it.serial_no || '').trim();
    const serial_all_html = frappe.utils.escape_html(serial_all).replace(/\n/g, '<br>');

    const per_row_status = `
      <select class="row-status" data-idx="${idx}" style="min-width:140px;">
        ${['', ...CHILD_STATUSES].map(o => `<option value="${o}" ${it.status===o?'selected':''}>${o}</option>`).join('')}
      </select>`;

    return `
      <tr>
        <td class="text-center">
          <input type="checkbox" class="row-pick" data-idx="${idx}" ${remaining>0?'checked':''} ${remaining<=0?'disabled':''}>
        </td>
        <td>${idx}</td>
        <td>${frappe.utils.escape_html(it.item_code || '')}</td>
        <td>${frappe.utils.escape_html(it.item_name || '')}</td>
        <td class="text-right">${format_number(qty, null, 2)}</td>
        <td class="text-right">${format_number(returned, null, 2)}</td>
        <td class="text-right row-remaining" data-idx="${idx}">${format_number(remaining, null, 2)}</td>
        <td class="text-right">
          <input type="number" step="0.0001" min="0" class="row-recvqty input-with-feedback" data-idx="${idx}" value="${remaining}">
          <div class="text-muted" style="font-size:11px;">${__('หรือกรอก Serial ด้านล่าง')}</div>
        </td>
        <td>${per_row_status}</td>
      </tr>
      <tr>
        <td></td>
        <td colspan="8">
          <textarea rows="3" class="row-serial" data-idx="${idx}" style="width:100%;" placeholder="${__('Serial ที่จะรับคืน ทีละบรรทัด (ปล่อยว่าง = ใช้จำนวน)')}"></textarea>
          <div class="text-muted" style="font-size:11px; margin-top:4px;">
            ${__('Serial ทั้งหมดในแถวนี้ (อ้างอิงปัจจุบันของเอกสาร):')}<br>${serial_all_html || '-'}
          </div>
        </td>
      </tr>`;
  }).join('');

  const table_html = `
    <div style="max-height:510px; overflow:auto; border:1px solid #e5e5e5; border-radius:6px;">
      <table class="table table-bordered" style="width:100%;">
        <thead>
          <tr>
            <th style="width:48px; text-align:center;">
              <input type="checkbox" class="pick-all" ${has_remaining(frm) ? 'checked' : ''}>
            </th>
            <th style="width:48px;">#</th>
            <th>${__('Item Code')}</th>
            <th>${__('Item Name')}</th>
            <th style="width:100px; text-align:right;">${__('Qty')}</th>
            <th style="width:120px; text-align:right;">${__('Returned Qty')}</th>
            <th style="width:120px; text-align:right;">${__('Remaining')}</th>
            <th style="width:170px; text-align:right;">${__('Receive Qty')}</th>
            <th style="width:170px;">${__('Per-Row Status')}</th>
          </tr>
        </thead>
        <tbody>${rows_html}</tbody>
      </table>
    </div>
    <div class="text-muted" style="margin-top:6px;">
      ${__('ถ้ากรอก Serial ในแถว ระบบจะใช้ “จำนวน = จำนวน Serial ที่กรอก” และเพิกเฉย Receive Qty ของแถว')}
    </div>
  `;
  d.get_field('items_html').$wrapper.html(table_html);

  // ----- Behaviors -----
  const wrap = d.get_field('items_html').$wrapper;
  const toolbar = d.get_field('toolbar').$wrapper;

  // pick-all in header
  wrap.on('change', '.pick-all', function() {
    const checked = $(this).is(':checked');
    wrap.find('.row-pick:not(:disabled)').prop('checked', checked);
  });

  // clamp Receive Qty
  wrap.on('input', '.row-recvqty', function() {
    const idx = cint($(this).data('idx'));
    if ((wrap.find(`.row-serial[data-idx="${idx}"]`).val() || '').trim()) {
      // มี serial → จำนวนต้องเท่ากับจำนวน serial
      const count = serial_count(wrap, idx);
      $(this).val(count || 0);
      return;
    }
    const rem = flt(wrap.find(`.row-remaining[data-idx="${idx}"]`).text() || 0);
    let v = flt($(this).val() || 0);
    if (v < 0) v = 0;
    if (v > rem) v = rem;
    $(this).val(v);
  });

  // serial textarea → sync qty
  wrap.on('input', '.row-serial', function() {
    const idx = cint($(this).data('idx'));
    const count = serial_count(wrap, idx);
    const rem = flt(wrap.find(`.row-remaining[data-idx="${idx}"]`).text() || 0);
    if (count > rem) {
      frappe.show_alert({ message: __(`Serial (${count}) > Remaining (${rem})`), indicator: 'orange' });
    }
    wrap.find(`.row-recvqty[data-idx="${idx}"]`).val(count || 0);
  });

  // toolbar actions
  toolbar.on('click', 'button[data-action="pick-all"]', () => {
    wrap.find('.row-pick:not(:disabled)').prop('checked', true);
  });
  toolbar.on('click', 'button[data-action="unpick-all"]', () => {
    wrap.find('.row-pick:not(:disabled)').prop('checked', false);
  });
  toolbar.on('click', 'button[data-action="fill-remaining"]', () => {
    wrap.find('.row-pick:checked').each((_, el) => {
      const idx = cint($(el).data('idx'));
      if ((wrap.find(`.row-serial[data-idx="${idx}"]`).val() || '').trim()) return; // ถ้ามี serial → ข้าม
      const rem = flt(wrap.find(`.row-remaining[data-idx="${idx}"]`).text() || 0);
      wrap.find(`.row-recvqty[data-idx="${idx}"]`).val(rem);
    });
  });
  toolbar.on('click', 'button[data-action="apply-global"]', () => {
    const use_global = d.get_value('use_global');
    const g = d.get_value('global_status');
    if (!use_global) {
      frappe.show_alert({ message: __('กรุณาติ๊ก "ใช้สถานะเดียวทั้งชุด" ก่อน'), indicator: 'orange' });
      return;
    }
    wrap.find('.row-pick:checked').each((_, el) => {
      const idx = cint($(el).data('idx'));
      wrap.find(`.row-status[data-idx="${idx}"]`).val(g);
    });
  });

  d.show();

  // --- helpers ---
  function serial_count(w, idx) {
    const lines = (w.find(`.row-serial[data-idx="${idx}"]`).val() || '')
      .split('\n').map(s => s.trim()).filter(Boolean);
    return lines.length;
  }
  function has_remaining(frm) {
    return (frm.doc.items || []).some(it => (flt(it.qty || 0) - flt(it.returned_qty || 0)) > 0);
  }
}
