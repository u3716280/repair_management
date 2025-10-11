frappe.listview_settings['Repair List'] = {
  add_fields: ['status', 'supplier', 'posting_date', 'company'],

  get_indicator: function(doc) {
    const map = {
      "Draft":           ["Draft", "gray",   "status,=,Draft"],
      "In Repair":       ["In Repair", "orange", "status,=,In Repair"],
      "Partial Returned":["Partial Returned", "yellow", "status,=,Partial Returned"],
      "Returned":        ["Returned", "green",  "status,=,Returned"],
      "Cancelled":       ["Cancelled", "red",   "status,=,Cancelled"],
    };
    if (doc.status && map[doc.status]) {
      return map[doc.status];
    }
    return [doc.status || __("Unknown"), "gray", `status,=,${doc.status || ""}`];
  },

  onload(listview) {
    const addQuick = (label, value, color='blue') => {
      listview.page.add_inner_button(label, () => {
        listview.filter_area.add([['Repair List', 'status', '=', value]]);
        listview.refresh();
      }, color);
    };

//    addQuick(__('In Repair'), 'In Repair', 'orange');
//    addQuick(__('Partial Returned'), 'Partial Returned', 'yellow');
//    addQuick(__('Returned'), 'Returned', 'green');

    // เปิดมาดูงานที่ยังไม่เสร็จเป็นค่าเริ่มต้น
//    if (!listview.filter_area.get_filter('status')) {
//      listview.filter_area.add([['Repair List', 'status', 'in', ['In Repair','Partial Returned']]]);
//    }
  }
};
