frappe.pages['serial-rate-repair'].on_page_load = function(wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: __('Serial Rate Repair'),
    single_column: true
  });

  const state = { rows: [] };
  const $body = $(page.body);
  $body.html(`
    <div class="spr-wrap">
      <div class="spr-filters row">
        <div class="col-md-3"><div class="spr-serial"></div></div>
        <div class="col-md-3"><div class="spr-item"></div></div>
        <div class="col-md-3"><div class="spr-warehouse"></div></div>
        <div class="col-md-3"><div class="spr-pr"></div></div>
      </div>
      <div class="mt-3 d-flex gap-2">
        <button class="btn btn-primary spr-preview">${__('Preview')}</button>
        <button class="btn btn-danger spr-repair" disabled>${__('Repair Selected')}</button>
      </div>
      <div class="spr-summary mt-3"></div>
      <div class="spr-table mt-3"></div>
    </div>
  `);

  const serial = frappe.ui.form.make_control({ parent: $body.find('.spr-serial'), df: { fieldtype: 'Data', label: __('Serial No'), fieldname: 'serial_no' }, render_input: true });
  const item = frappe.ui.form.make_control({ parent: $body.find('.spr-item'), df: { fieldtype: 'Link', options: 'Item', label: __('Item'), fieldname: 'item_code' }, render_input: true });
  const warehouse = frappe.ui.form.make_control({ parent: $body.find('.spr-warehouse'), df: { fieldtype: 'Link', options: 'Warehouse', label: __('Warehouse'), fieldname: 'warehouse' }, render_input: true });
  const pr = frappe.ui.form.make_control({ parent: $body.find('.spr-pr'), df: { fieldtype: 'Link', options: 'Purchase Receipt', label: __('Purchase Receipt'), fieldname: 'purchase_receipt' }, render_input: true });

  function render_table(rows) {
    state.rows = rows || [];
    const safe = frappe.utils.escape_html;
    let html = `<div class="table-responsive"><table class="table table-bordered table-hover">
      <thead><tr>
        <th style="width:40px"><input type="checkbox" class="spr-check-all"></th>
        <th>${__('Serial No')}</th><th>${__('Item')}</th><th>${__('Warehouse')}</th>
        <th>${__('Current Rate')}</th><th>${__('Suggested Rate')}</th>
        <th>${__('Source')}</th><th>${__('Status')}</th>
      </tr></thead><tbody>`;

    for (const r of state.rows) {
      const disabled = r.can_repair ? '' : 'disabled';
      html += `<tr>
        <td><input type="checkbox" class="spr-row" data-serial="${safe(r.serial_no)}" ${disabled}></td>
        <td>${safe(r.serial_no || '')}</td>
        <td>${safe(r.item_code || '')}</td>
        <td>${safe(r.warehouse || '')}</td>
        <td class="text-right">${format_currency(r.current_rate || 0)}</td>
        <td class="text-right">${format_currency(r.suggested_rate || 0)}</td>
        <td>${safe(r.source || '')}</td>
        <td>${safe(r.status || '')}</td>
      </tr>`;
    }
    html += '</tbody></table></div>';
    $body.find('.spr-table').html(html);
    $body.find('.spr-summary').html(`<div class="alert alert-info">${__('Found')} ${state.rows.length} ${__('record(s)')}</div>`);
    $body.find('.spr-repair').prop('disabled', !state.rows.some(r => r.can_repair));
  }

  $body.on('change', '.spr-check-all', function() {
    $body.find('.spr-row:not(:disabled)').prop('checked', this.checked);
  });

  $body.find('.spr-preview').on('click', function() {
    frappe.call({
      method: 'repair_management.repair_management.page.serial_rate_repair.serial_rate_repair.preview',
      freeze: true,
      args: {
        serial_no: serial.get_value(),
        item_code: item.get_value(),
        warehouse: warehouse.get_value(),
        purchase_receipt: pr.get_value()
      },
      callback: r => render_table(r.message || [])
    });
  });

  $body.find('.spr-repair').on('click', function() {
    const selected = [];
    $body.find('.spr-row:checked').each(function() { selected.push($(this).data('serial')); });
    if (!selected.length) {
      frappe.msgprint(__('Select at least one Serial No.'));
      return;
    }
    frappe.confirm(__('Update purchase rate for {0} serial number(s)?', [selected.length]), function() {
      frappe.call({
        method: 'repair_management.repair_management.page.serial_rate_repair.serial_rate_repair.repair',
        freeze: true,
        args: { serial_nos: selected },
        callback: r => {
          frappe.msgprint(__('Updated {0} serial number(s).', [r.message?.updated || 0]));
          $body.find('.spr-preview').trigger('click');
        }
      });
    });
  });
};
