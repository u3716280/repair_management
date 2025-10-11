frappe.ui.form.on('Repair List', {
  refresh(frm) {
    // เงื่อนไขแสดงปุ่ม: ต้องเป็นเอกสาร Submit และสถานะอยู่ในช่วงรับกลับ
    const can_return =
      frm.doc.docstatus === 1 &&
      ["In Repair", "Partial Returned"].includes(frm.doc.status);

    if (!can_return) return;

    // กันปุ่มซ้ำเมื่อ refresh หลายรอบ
    if (frm.__return_btn_added) return;
    frm.__return_btn_added = true;

    frm.add_custom_button(
      __('Return'),
      async () => {
        // ---------- เตรียมข้อมูลแถว ----------
        const items = (frm.doc.items || []).slice();
        const rows = [];

        items.forEach((it) => {
          const qty = Number(it.qty || 0);
          const returned = Number(it.returned_qty || 0);
          const remaining = Math.max(qty - returned, 0);
          if (remaining <= 0) return;

          const pct = qty ? Math.round((returned / qty) * 100) : 0;
          rows.push({
            __idx: Number(it.idx),            // สำคัญ: index 1-based
            select_row: 1,                    // default เลือก
            item_code: it.item_code,
            item_name: it.item_name || "",
            uom: it.uom || "",
            serial_no: it.serial_no || "",
            qty,
            remaining,
            return_qty: remaining,            // default รับเต็ม remaining
            row_status: it.status || "",
            progress_text: `${returned}/${qty} (${pct}%)`
          });
        });

        if (!rows.length) {
          frappe.msgprint(__("All items are fully returned."));
          return;
        }

        const statusOptions = ["", "Free", "Charge", "No Repair"]; // ปรับตามธุรกิจคุณ

        // ---------- สร้าง Dialog ----------
        const d = new frappe.ui.Dialog({
          title: `${frm.doc.name} : ${__('Receive Return')}`,
          fields: [
            { fieldtype: "Section Break", label: __("Options") },
            {
              fieldtype: "Check",
              fieldname: "use_global_status",
              label: __("Use Global Status"),
              default: 1
            },
            {
              fieldtype: "Select",
              fieldname: "global_status",
              label: __("Global Status"),
              options: statusOptions.join("\n"),
              depends_on: "eval:doc.use_global_status==1",
              default: "Free"
            },
            {
              fieldtype: "Check",
              fieldname: "show_details",
              label: __("Show details (Name/UOM/Serial)"),
              default: 0
            },

            { fieldtype: "Section Break", label: __("Items to Receive") },
            {
              fieldtype: "Table",
              fieldname: "return_table",
              in_place_edit: 1,
              cannot_add_rows: 1,
              cannot_delete_rows: 1,
              data: rows,
              fields: [
                {
                  label: __("Sel"),
                  fieldname: "select_row",
                  fieldtype: "Check",
                  in_list_view: 1,
                  width: "30px"
                },
                {
                  label: __("Item"),
                  fieldname: "item_code",
                  fieldtype: "Link",
                  options: "Item",
                  in_list_view: 1,
                  read_only: 1,
                  width: "120px"
                },
                // ใช้ Progress แทน Returned Qty เพื่อลดความซ้ำซ้อน
                {
                  label: __("Progress"),
                  fieldname: "progress_text",
                  fieldtype: "Data",
                  in_list_view: 0,
                  read_only: 1,
                  width: "30px"
                },
                {
                  label: __("Qty"),
                  fieldname: "qty",
                  fieldtype: "Float",
                  read_only: 1,
                  in_list_view: 1,
                  width: "90px"
                },
                {
                  label: __("Return Qty"),
                  fieldname: "return_qty",
                  fieldtype: "Float",
                  read_only: 0,
                  in_list_view: 1,
                  width: "120px"
                },
                {
                  label: __("Remaining"),
                  fieldname: "remaining",
                  fieldtype: "Float",
                  read_only: 1,
                  in_list_view: 1,
                  width: "110px"
                },
                // รายละเอียด เปิด/ปิดด้วยสวิตช์
                {
                  label: __("Name"),
                  fieldname: "item_name",
                  fieldtype: "Data",
                  in_list_view: 0,
                  read_only: 1,
                  width: "180px"
                },
                {
                  label: __("UOM"),
                  fieldname: "uom",
                  fieldtype: "Data",
                  in_list_view: 0,
                  read_only: 1,
                  width: "90px"
                },
                {
                  label: __("Serial No"),
                  fieldname: "serial_no",
                  fieldtype: "Small Text",
                  in_list_view: 0,
                  read_only: 1,
                  width: "180px"
                },

                {
                  label: __("Row Status"),
                  fieldname: "row_status",
                  fieldtype: "Select",
                  options: statusOptions.join("\n"),
                  in_list_view: 1,
                  width: "140px"
                },

                { fieldname: "__idx", fieldtype: "Int", hidden: 1 }
              ]
            }
          ],
          size: "extra-large",
          primary_action_label: __("Receive Return"),
          primary_action: async function () {
            const values = d.get_values();
            if (!values) return;

            const use_global = values.use_global_status ? 1 : 0;
            const global_status = values.global_status || null;
            const table = values.return_table || [];

            const selected_idx = [];
            const qty_map = {};
            const item_status_map = {};

            for (const r of table) {
              if (!r.select_row) continue;

              const remain = Number(r.remaining || 0);
              let rq = Number(r.return_qty || 0);

              // ถ้ามี Serial → บังคับรับเต็ม remaining
              const has_serial = !!(r.serial_no && String(r.serial_no).trim().length > 0);
              if (has_serial) rq = remain;

              if (rq <= 0 || remain <= 0) continue;

              const row_idx = Number(r.__idx); // 1-based
              selected_idx.push(row_idx);
              qty_map[String(row_idx)] = rq;

              if (!use_global && r.row_status) {
                item_status_map[String(row_idx)] = r.row_status;
              }
            }

            if (!selected_idx.length) {
              frappe.msgprint(__("Please select at least one row with Return Qty > 0"));
              return;
            }

            // ปรับ path ให้ตรงกับแอป/โมดูลของคุณ
            const method_path =
              "repair_management.repair_management.doctype.repair_list.repair_list.receive_return";

            try {
              const { message } = await frappe.call({
                method: method_path,
                args: {
                  docname: frm.doc.name,
                  selected_idx: JSON.stringify(selected_idx),
                  qty_map: JSON.stringify(qty_map),
                  item_status_map: JSON.stringify(item_status_map),
                  use_global_status: use_global,
                  global_status: global_status
                },
                freeze: true,
                freeze_message: __("Receiving returns...")
              });

              frappe.show_alert({
                message: __("Stock Entry created: {0}", [message?.stock_entry || ""]),
                indicator: "green"
              });

              d.hide();
              await frm.reload_doc();
            } catch (e) {
              console.error(e);
              frappe.msgprint({
                title: __("Error"),
                message: e.message || e,
                indicator: "red"
              });
            }
          },
          secondary_action_label: __("Close"),
          secondary_action() { d.hide(); }
        });

        // ---------- ทำให้แก้ไขได้จริง + จัดเลย์เอาต์ ----------
        const grid = d.fields_dict.return_table.grid;

        // บังคับ inline edit
        grid.df.in_place_edit = 1;
        grid.editable_fields = [
          { fieldname: "select_row" },
          { fieldname: "return_qty" },
          { fieldname: "row_status" },
        ];
        grid.update_docfield_property("return_qty", "read_only", 0);
        grid.update_docfield_property("row_status", "read_only", 0);
        grid.refresh();

        // Toggle “Show details” → เปิด/ปิดคอลัมน์ยิบย่อย
        const toggle_details = (show) => {
          const meta = ["item_name", "uom", "serial_no"];
          meta.forEach(fn => grid.toggle_display(fn, !!show));
          grid.refresh();
        };
        d.fields_dict.show_details.$input.on("change", () => toggle_details(d.get_value("show_details")));
        toggle_details(0); // default compact

        // ล็อคแถวที่มี serial: return_qty = remaining (ไม่ตั้ง read_only รายแถว)
        (() => {
          const data = d.get_value("return_table") || [];
          data.forEach(r => {
            const is_serial = !!(r.serial_no && String(r.serial_no).trim());
            if (is_serial) r.return_qty = r.remaining;
          });
          grid.refresh();
        })();

        // ฉีด CSS ให้ตารางเลื่อนแนวนอนได้ และขยาย dialog กว้างขึ้น
        d.$wrapper.addClass("repair-return-dialog");
        frappe.dom.set_style(`
          .repair-return-dialog .modal-dialog { max-width: 92vw; }
          .repair-return-dialog .form-grid, 
          .repair-return-dialog .grid-body {
            overflow-x: auto !important;
          }
          .repair-return-dialog .form-grid { min-width: 1100px; }
        `);

        d.show();
      },
      __("Actions")
    );
  }
});
