frappe.pages['hvac-selection'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'HVAC CFM Selection',
		single_column: true
	});
}