// Override the PrintView class to add custom buttons
(function() {
    // Store the original setup_toolbar method
    const originalSetupToolbar = frappe.ui.form.PrintView.prototype.setup_toolbar;

    // Override setup_toolbar
    frappe.ui.form.PrintView.prototype.setup_toolbar = function() {
        // Call the original method first
        originalSetupToolbar.call(this);

        // Add JPG button
        this.page.add_button(__("JPG"), () => this.render_jpg(), {
            icon: "image"
        });

        // Add LINE button
        this.page.add_button(__("LINE"), () => this.send_to_line(), {
            icon: "share"
        });
    };

    frappe.ui.form.PrintView.prototype.render_jpg = function() {
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

    // Add custom export_jpg method
    frappe.ui.form.PrintView.prototype.export_jpg = function() {
        const me = this;

        frappe.require('https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js', () => {
            const iframe = me.print_wrapper.find('iframe.print-format-container')[0];
            if (!iframe?.contentDocument?.body) {
                frappe.msgprint(__('Print preview not ready'));
                return;
            }

            html2canvas(iframe.contentDocument.body, {
                scale: 2,
                useCORS: true,
                backgroundColor: '#ffffff'
            }).then(canvas => {
                me.show_jpg_dialog(canvas);
            }).catch(err => {
                frappe.msgprint(__('Error generating JPG'));
                console.error(err);
            });
        });
    };

    frappe.ui.form.PrintView.prototype.show_jpg_dialog = function(canvas) {
        const filename = this.frm.docname || 'document';
        const dataUrl = canvas.toDataURL('image/jpeg', 0.95);

        const d = new frappe.ui.Dialog({
            title: __('JPG Preview'),
            size: 'extra-large',
            fields: [{
                fieldtype: 'HTML',
                options: `<div style="text-align:center;padding:20px;">
                    <img src="${dataUrl}" style="max-width:100%;border:1px solid #d1d8dd;border-radius:4px;">
                </div>`
            }],
            primary_action_label: __('Download'),
            primary_action: () => {
                canvas.toBlob(blob => {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.download = `${filename}.jpg`;
                    a.href = url;
                    a.click();
                    URL.revokeObjectURL(url);
                    d.hide();
                }, 'image/jpeg', 0.95);
            }
        });

        d.show();
    };

    // Send to LINE functionality - uses LINE Messaging API
    frappe.ui.form.PrintView.prototype.send_to_line = function() {
        const me = this;
        let print_format = this.get_print_format();
        
        // Show user selection dialog first
        frappe.call({
            method: 'repair_management.line_send.get_line_user_selection',
            callback: function(r) {
                if (r.message && r.message.length > 0) {
                    me.show_line_user_dialog(r.message, print_format);
                } else {
                    // No users configured, send to default
                    me.send_line_message(null, print_format);
                }
            }
        });
    };

    frappe.ui.form.PrintView.prototype.show_line_user_dialog = function(users, print_format) {
        const me = this;
        
        // Create options for select field
        let user_options = users.map(u => {
            return {
                label: u.display_name || u.line_user_id,
                value: u.line_user_id
            };
        });
        
        const d = new frappe.ui.Dialog({
            title: __('Send to LINE'),
            fields: [
                {
                    fieldtype: 'Select',
                    label: __('Select Recipient'),
                    fieldname: 'user_id',
                    options: user_options.map(u => u.label).join('\n'),
                    reqd: 1
                },
                {
                    fieldtype: 'HTML',
                    options: '<div class="text-muted small mt-2">' + 
                             __('The document will be sent as an image to the selected LINE user') +
                             '</div>'
                }
            ],
            primary_action_label: __('Send to LINE'),
            primary_action: (values) => {
                // Find the selected user ID from the label
                let selected_label = values.user_id;
                let selected_user = user_options.find(u => u.label === selected_label);
                let user_id = selected_user ? selected_user.value : null;
                
                d.hide();
                me.send_line_message(user_id, print_format);
            }
        });
        
        d.show();
    };

    frappe.ui.form.PrintView.prototype.send_line_message = function(user_id, print_format) {
        const me = this;
        
        // Show loading message
        frappe.show_alert({
            message: __('Preparing to send to LINE...'),
            indicator: 'blue'
        });
        
        frappe.call({
            method: 'repair_management.line_send.send_image_to_line',
            args: {
                doctype: me.frm.doc.doctype,
                name: me.frm.doc.name,
                format_name: print_format.name,
                letterhead: me.get_letterhead(),
                no_letterhead: print_format.show_letterhead === 0 ? 1 : 0,
                user_id: user_id
            },
            freeze: true,
            freeze_message: __('Sending to LINE...'),
            callback: function(r) {
                if (r.message && r.message.success) {
                    frappe.show_alert({
                        message: __('Image sent to LINE successfully!'),
                        indicator: 'green'
                    }, 5);
                }
            },
            error: function(r) {
                frappe.show_alert({
                    message: __('Failed to send to LINE. Please check your LINE settings.'),
                    indicator: 'red'
                }, 7);
            }
        });
    };
})();
