frappe.ui.form.on('Repair List', {
  refresh(frm) {
    if (frm.doc.docstatus === 1 && ['In Repair', 'Partial Returned'].includes(frm.doc.status)) {
      frm.add_custom_button(__('Receive Return'), async function () {

        // โหมดง่าย: รับ 'ทุกรายการ'
        const primary = __('Receive ALL Items');
        const secondary = __('Pick Rows');

        const choice = await new Promise(resolve => {
          frappe.msgprint({
            title: __('Receive Return'),
            message: __('คุณต้องการรับกลับทุกรายการเลยหรือเลือกเป็นบางแถว?'),
            primary_action: {
              label: primary,
              action() { resolve('ALL'); cur_dialog.hide(); }
            },
            secondary_action: {
              label: secondary,
              action() { resolve('PICK'); cur_dialog.hide(); }
            }
          });
        });

        let args = { docname: frm.doc.name };

        if (choice === 'PICK') {
          // ให้ผู้ใช้กรอกหมายเลขแถว (1,3,5) แบบรวดเร็ว
          const d = new frappe.ui.Dialog({
            title: __('Select Row Index (1-based)'),
            fields: [
              {
                fieldname: 'idx_list',
                label: __('Row Indexes'),
                fieldtype: 'Data',
                description: __('เช่น 1,3,5 (จะรับกลับเฉพาะแถวดังกล่าว ทั้งจำนวน)')
              }
            ],
            primary_action_label: __('Receive Selected'),
            primary_action: (values) => {
              const raw = (values.idx_list || '').trim();
              let selected_idx = [];
              if (raw) {
                selected_idx = raw.split(',')
                  .map(s => cint(s.trim()))
                  .filter(n => n > 0);
              }
              if (!selected_idx.length) {
                frappe.msgprint(__('ไม่ได้เลือกแถวใดเลย')); return;
              }
              args.selected_idx = selected_idx;
              d.hide();

              frappe.call({
                method: 'repair_management.repair_management.doctype.repair_list.repair_list.receive_return',
                args,
              }).then(() => frm.reload_doc());
            }
          });
          d.show();
          return;
        }

        // โหมด ALL
        await frappe.call({
          method: 'repair_management.repair_management.doctype.repair_list.repair_list.receive_return',
          args,
        });
        await frm.reload_doc();
      }, __('Actions'));
    }
  }
});
