// Override the PrintView class to add custom button
(function() {
    // Store the original setup_toolbar method
    const originalSetupToolbar = frappe.ui.form.PrintView.prototype.setup_toolbar;
    
    // Override setup_toolbar
    frappe.ui.form.PrintView.prototype.setup_toolbar = function() {
        // Call the original method first
        originalSetupToolbar.call(this);
        
        // Add your custom button after JPG button
        this.page.add_button(__("JPG"), () => this.render_jpg(), {
            icon: "small-file"
        });
    };

	frappe.ui.form.PrintView.prototype.render_jpg() = function() {
	    let print_format = this.get_print_format();
	    let params = new URLSearchParams({
	        doctype: this.frm.doc.doctype,
	        name: this.frm.doc.name,
	        format: print_format.name,
	        letterhead: this.get_letterhead(),
	        no_letterhead: print_format.show_letterhead === 0 ? 1 : 0,
	    });

	    let url = `/print_jpg?${params}`;
	    let w = window.open(url);

	    if (!w) {
	        frappe.msgprint(__("Please enable pop-ups"));
	        return;
	    }
	};

    // Add custom export method
    frappe.ui.form.PrintView.prototype.export_to_excel = function() {
        let print_format = this.get_print_format();
        
        let params = new URLSearchParams({
            doctype: this.frm.doc.doctype,
            name: this.frm.doc.name,
            format: this.selected_format(),
            letterhead: this.get_letterhead(),
            no_letterhead: print_format.show_letterhead === 0 ? 1 : 0,
        });
        
        // Open in new window
        let w = window.open(`/api/method/your_app.api.export_excel?${params}`);
        
        if (!w) {
            frappe.msgprint(__("Please enable pop-ups"));
            return;
        }
    };
})();
