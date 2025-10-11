frappe.ui.form.on('Repair List', {
  refresh(frm) {
    if (frm.doc.docstatus === 1 && ['In Repair', 'Partial Returned'].includes(frm.doc.status)) {
      frm.add_custom_button(__('Receive Return (Form Dialog)'), () => open_receive_return_dialog(frm), __('Actions'));
    }
  }
});

function open_receive_return_dialog(frm) {
  // ชุดสถานะของ child.status ตาม Repair Item List:contentReference[oaicite:4]{index=4}
  const CHILD_STATUSES = ['In Progress','Free','Charge','No Repair'];

  // เตรียมแถวข้อมูลจาก child table
  const rows = (frm.doc.items || []).map((it, i) => {
    const idx = i + 1;                                           // 1-based index
    const qty = flt(it.qty || 0);
    const returned = flt(it.returned_qty || 0);
    const remaining = Math.max(qty - returned, 0);
    return {
      pick: remaining > 0,                                       // เลือกแถวอัตโนมัติถ้ามีของเหลือรับ
      idx,                                                       // ไว้แมพกลับไป server
      item_code: it.item_code || '',
      item_name: it.item_name || '',
      qty,
      returned_qty: returned,
      remaining,
      receive_qty: remaining,                                    // ค่าเริ่มต้น = เหลือทั้งหมด
      serials: '',                                               // ใส่ serial เฉพาะที่จะรับ (แยกบรรทัด)
      per_row_status: it.status || ''                            // ตั้งค่าเริ่มต้น = status ปัจจุบันแถว
    };
  });

  const d = new frappe.ui.Dialog({
    title: __('Receive Return'),
    size: 'large',
    fields: [
      { fieldname: 'use_global', fieldtype: 'Check', label: __('ใช้สถานะเดียวทั้งชุด'), default: 1 },
      { fieldname: 'global_status', fieldtype: 'Select', label: __('Global Status'), options: CHILD_STATUSES.join('\n'), default: 'Free' },
      { fieldname: 'sb', fieldtype: 'Section Break' },
      {
        fieldname: 'items',
        fieldtype: 'Table',                                      // DataTable ใน Dialog
        label: __('Items to Receive'),
        cannot_add_rows: 1,
        in_place_edit: 1,
        data: rows,
        get_data: () => rows,
        fields: [
          { fieldtype: 'Check', label: __('Pick'),       fieldname: 'pick',         in_list_view: 1, width: '60px' },
          { fieldtype: 'Int',   label: __('#'),          fieldname: 'idx',          in_list_view: 1, read_only: 1, width: '50px' },
          { fieldtype: 'Data',  label: __('Item Code'),  fieldname: 'item_code',    in_list_view: 1, read_only: 1, width: '140px' },
          { fieldtype: 'Data',  label: __('Item Name'),  fieldname: 'item_name',    in_list_view: 1, read_only: 1, width: '200px' },
          { fieldtype: 'Float', label: __('Qty'),        fieldname: 'qty',          in_list_view: 1, read_only: 1, width: '90px' },
          { fieldtype: 'Float', label: __('Returned'),   fieldname: 'returned_qty', in_list_view: 1, read_only: 1, width: '110px' },
          { fieldtype: 'Float', label: __('Remaining'),  fieldname: 'remaining',    in_list_view: 1, read_only: 1, width: '110px' },
          // ถ้าใส่ serials (textarea) → ระบบจะนับจำนวนบรรทัด = qty ที่จะรับ และจะละ receive_qty ของบรรทัดนั้น
          { fieldtype: 'Float',     label: __('Receive Qty'),  fieldname: 'receive_qty',  in_list_view: 1, width: '120px' },
          { fieldtype: 'Small Text',label: __('Serials (1/line)'), fieldname: 'serials', width: '220px' },
          { fieldtype: 'Select',    label: __('Per-Row Status'), fieldname: 'per_row_status', options: [''].concat(CHILD_STATUSES).join('\n'), width: '150px' },
        ]
      },
      { fieldname: 'cb', fieldtype: 'Column Break' },
      {
        fieldname: 'help',
        fieldtype: 'HTML',
        options:
          `<div class="text-muted" style="margin-top:6px;">
            ${__('ถ้ากรอก Serials ในแถว ระบบจะใช้ "จำนวน = จำนวน serial ที่กรอก" และเพิกเฉย Receive Qty ของแถวนั้น')}
           </div>
           <div class="flex items-center gap-2" style="margin-top:8px;">
             <button class="btn btn-xs btn-default" data-action="select-all">${__('เลือกทั้งหมด')}</button>
             <button class="btn btn-xs btn-default" data-action="unselect-all">${__('ยกเลิกทั้งหมด')}</button>
             <button class="btn btn-xs btn-default" data-action="fill-remaining">${__('ใส่ Receive Qty = Remaining')}</button>
             <button class="btn btn-xs btn-default" data-action="apply-global">${__('ตั้ง Per-Row = Global')}</button>
           </div>`
      }
    ],
    primary_action_label: __('Receive'),
    async primary_action(values) {
      // อ่านค่าจากตาราง
      const table = d.get_values().items || [];
      const selected_idx = [];
      const qty_map = {};
      const serial_map = {};
      const item_status_map = {};

      // clamp + สร้าง payload
      for (const r of table) {
        if (!r.pick) continue;

        const idx = cint(r.idx);
        if (!idx) continue;

        const remaining = flt(r.remaining || 0);
        const serial_text = (r.serials || '').trim();

        if (serial_text) {
          // โหมด serial picker: ใช้จำนวนเท่ากับจำนวนบรรทัด serial
          const count = serial_text.split('\n').map(s => s.trim()).filter(Boolean).length;
          if (!count) continue;
          if (count > remaining) {
            frappe.throw(__("Row {0}: จำนวน Serial ({1}) เกิน Remaining ({2})", [idx, count, remaining]));
          }
          serial_map[String(idx)] = serial_text;
        } else {
          // โหมดจำนวน
          let v = flt(r.receive_qty || 0);
          if (v < 0) v = 0;
          if (v > remaining) v = remaining;
          if (!v) continue;
          qty_map[String(idx)] = v;
        }

        selected_idx.push(idx);

        // per-row status (ถ้าไม่ใช้ global ให้ส่งบรรทัดนี้ไป)
        if (!values.use_global && r.per_row_status) {
          item_status_map[String(idx)] = r.per_row_status;
        }
      }

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
          serial_map: JSON.stringify(serial_map),
          item_status_map: JSON.stringify(item_status_map),
          use_global_status: values.use_global ? 1 : 0,
          global_status: values.use_global ? values.global_status : null,
        }
      });

      d.hide();
      await frm.reload_doc();
    }
  });

  // data behaviors (แบบ field-based)
  // 1) ถ้าแก้ไข serials → sync receive_qty ให้เท่าจำนวนบรรทัด (UI สอดคล้อง)
  const tbl = d.fields_dict.items;
  tbl.df.onchange = () => {
    const data = d.get_values().items || [];
    for (const r of data) {
      const serial_text = (r.serials || '').trim();
      if (serial_text) {
        const count = serial_text.split('\n').map(s => s.trim()).filter(Boolean).length;
        r.receive_qty = count || 0;
      } else {
        // ไม่มี serial → ไม่บังคับ แต่ให้คงค่า receive_qty ที่ผู้ใช้กรอกเอง
        // (จะถูก clamp อีกชั้นตอนส่ง)
      }
    }
    // refresh ตาราง
    d.set_value('items', data);
  };

  // toolbar mini actions
  const wrap = d.get_field('help').$wrapper;
  wrap.on('click', 'button[data-action="select-all"]', () => {
    const data = d.get_values().items || [];
    data.forEach(r => { if (r.remaining > 0) r.pick = 1; });
    d.set_value('items', data);
  });
  wrap.on('click', 'button[data-action="unselect-all"]', () => {
    const data = d.get_values().items || [];
    data.forEach(r => { r.pick = 0; });
    d.set_value('items', data);
  });
  wrap.on('click', 'button[data-action="fill-remaining"]', () => {
    const data = d.get_values().items || [];
    data.forEach(r => {
      if (!r.serials?.trim()) r.receive_qty = r.remaining;      // ถ้ามี serials จะถูก sync โดย onchange อยู่แล้ว
    });
    d.set_value('items', data);
  });
  wrap.on('click', 'button[data-action="apply-global"]', () => {
    const use_global = d.get_value('use_global');
    const g = d.get_value('global_status');
    if (!use_global) {
      frappe.show_alert({ message: __('กรุณาติ๊ก "ใช้สถานะเดียวทั้งชุด" ก่อน'), indicator: 'orange' });
      return;
    }
    const data = d.get_values().items || [];
    data.forEach(r => { r.per_row_status = g; });
    d.set_value('items', data);
  });

  d.show();
}
