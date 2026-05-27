frappe.pages['test-vue'].on_page_load = function (wrapper) {
  frappe.ui.make_app_page({
    parent: wrapper,
    title: 'Test Vue',
    single_column: true,
  });

  if (frappe.boot.developer_mode) {
    frappe.hot_update ??= [];
    frappe.hot_update.push(() => load_vue(wrapper));
  }
};

frappe.pages['test-vue'].on_page_show = function (wrapper) {
  load_vue(wrapper);
};

async function load_vue(wrapper) {
  const $parent = $(wrapper).find('.layout-main-section');

  if (frappe.test_vue_app?.unmount) {
    frappe.test_vue_app.unmount();
  }

  $parent.empty();

  await frappe.require('test_vue.bundle.js');

  frappe.test_vue_app = frappe.ui.setup_vue($parent.get(0));
}
