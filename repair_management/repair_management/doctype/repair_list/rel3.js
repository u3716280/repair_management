frappe.ui.form.on('Repair List', {
  refresh(frm) {
    if (frm.doc.docstatus === 1 && ['In Repair','Partial Returned'].includes(frm.doc.status)) {
      frm.add_custom_button(__('Receive Return'), () => open_pick_dialog(frm), __('Actions'));
    }
  }
});

function open_pick_dialog(frm) {
  const child_status_options = ['In Progress','Free','Charge','No Repair'];

  // เตรียม options ของ MultiCheck จากแถวที่ยังเหลือ
  const options = (frm.doc.items || []).map((it, i) => {
    const idx = i + 1;
    const qty = flt(it.qty || 0);
    const ret = flt(it.returned_qty || 0);
    const rem = Math.max(qty - ret, 0);
    return {
      label: `${idx}. ${it.item_code || ''} — remain: ${rem}`,
      value: String(idx),
      checked: rem > 0,
      disabled: rem <= 0
    };
  });

  const d = new frappe.ui.Dialog({
    title: __('Receive Return — Select Rows'),
    fields: [
      { fieldname: 'use_global', label: __('Use one status for all'), fieldtype: 'Check', default: 1 },
      { fieldname: 'global_status', label: __('Global Status'), fieldtype: 'Select',
        options: child_status_options.join('\n'),
        depends_on: 'eval:doc.use_global==1'
      },
      { fieldname: 'pick_rows', label: __('Rows'), fieldtype: 'MultiCheck', options },
      { fieldname: 'note', fieldtype: 'HTML', options:
        `<div class="text-muted" style="margin-top:6px">
           ${__('ถ้าต้องการกำหนดสถานะ/จำนวน/Serial รายแถว จะทำในสเต็ปถัดไป')}
         </div>` }
    ],
    primary_action_label: __('Next'),
    primary_action: (values) => {
      const selected = (values.pick_rows || []).filter(o => o.checked).map(o => cint(o.value));
      if (!selected.length) return frappe.msgprint(__('ไม่ได้เลือกแถวใดเลย'));
      d.hide();
      open_row_detail_dialog(frm, selected, values.use_global, values.global_status, child_status_options);
    }
  });

  d.show();
}

function open_row_detail_dialog(frm, selected_idx, use_global, global_status, child_status_options) {
  // สร้าง fields แบบไดนามิก
  const fields = [];

  // ถ้าไม่ใช้ Global ให้ขึ้นหัวข้อสถานะรวมไว้ด้วย (ปิดไว้เฉยๆ)
  fields.push({
    fieldname: 'info',
    fieldtype: 'HTML',
    options: `<div class="text-muted" style="margin-bottom:8px">
      ${use_global
        ? __('โหมดสถานะ: ใช้สถานะเดียวทั้งชุด → {0}', [frappe.utils.escape_html(global_status || '')])
        : __('โหมดสถานะ: กำหนดสถานะรายแถว')}
    </div>`
  });

  selected_idx.forEach((rowIdx) => {
    const it = frm.doc.items[rowIdx - 1];
    const qty = flt(it.qty || 0);
    const ret = flt(it.returned_qty || 0);
    const rem = Math.max(qty - ret, 0);

    fields.push({ fieldtype: 'Section Break', label: `${rowIdx}. ${it.item_code || ''}` });
    fields.push({ fieldtype: 'Read Only', label: __('Item Name'), default: it.item_name || '' });
    fields.push({ fieldtype: 'Read Only', label: __('Remaining'), default: rem });

    // จำนวนที่จะรับ (ถ้าใส่ Serial ด้านล่าง จำนวนจะถูก override ให้เท่าจำนวน Serial)
    fields.push({
      fieldname: `qty_${rowIdx}`,
      label: __('Receive Qty'),
      fieldtype: 'Float',
      default: rem,
      precision: 4
    });

    // ระบุ Serial เฉพาะ (ทีละบรรทัด) — ใช้ได้ทั้งมี/ไม่มี Serial เดิม
    fields.push({
      fieldname: `serial_${rowIdx}`,
      label: __('Serial to receive (one per line)'),
      fieldtype: 'Small Text'
    });

    // สถานะรายแถว (โชว์เฉพาะเมื่อไม่ใช้ Global)
    fields.push({
      fieldname: `status_${rowIdx}`,
      label: __('Row Status'),
      fieldtype: 'Select',
      options: child_status_options.join('\n'),
      depends_on: 'eval:' + (use_global ? 'false' : 'true'),
      default: it.status || child_status_options[0]
    });

    fields.push({ fieldtype: 'Column Break' }); // แค่จัดเลย์เอาต์
  });

  const d2 = new frappe.ui.Dialog({
    title: __('Receive Return — Details'),
    fields,
    primary_action_label: __('Receive'),
    primary_action: async (values) => {
      // รวบรวม qty_map / serial_map / item_status_map จาก dialog
      const qty_map = {};
      const serial_map = {};
      const item_status_map = {};

      for (const rowIdx of selected_idx) {
        const qty = flt(values[`qty_${rowIdx}`] || 0);
        const serial_text = (values[`serial_${rowIdx}`] || '').trim();
        if (serial_text) {
          serial_map[String(rowIdx)] = serial_text; // ใช้โหมด serial list → จำนวนจะเท่ากับจำนวนบรรทัด
        } else {
          qty_map[String(rowIdx)] = qty;
        }

        if (!use_global) {
          const st = values[`status_${rowIdx}`];
          if (st) item_status_map[String(rowIdx)] = st;
        }
      }

      await frappe.call({
        method: 'repair_management.repair_management.doctype.repair_list.repair_list.receive_return',
        args: {
          docname: frm.doc.name,
          selected_idx: JSON.stringify(selected_idx),
          qty_map: JSON.stringify(qty_map),
          serial_map: JSON.stringify(serial_map),
          item_status_map: JSON.stringify(item_status_map),
          use_global_status: use_global ? 1 : 0,
          global_status: use_global ? (global_status || null) : null
        }
      });

      d2.hide();
      await frm.reload_doc();
    }
  });

  d2.show();
}
