(function() {
	// Extend PrintView toolbar
	const _setup_toolbar = frappe.ui.form.PrintView.prototype.setup_toolbar;

	frappe.ui.form.PrintView.prototype.setup_toolbar = function() {
		_setup_toolbar.call(this);
		this.page.add_button(__("JPG"), () => this.export_jpg(), { icon: "image" });
	};

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
})();
