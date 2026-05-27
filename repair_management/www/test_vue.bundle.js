import { createApp } from 'vue';
import TestVue from './TestVue.vue';

// A simple function to mount your Vue app
function setup_vue(wrapper) {
  const app = createApp(TestVue);
  app.mount(wrapper.get(0));
  return app;
}

// We'll call this function from the generated test_vue.js file
frappe.ui.setup_vue = setup_vue;
export default setup_vue;

