# ============================================
# File: custom_print_button/api.py
# ============================================
import frappe

@frappe.whitelist()
def custom_print_action(doctype, docname):
    '''
    Custom server-side action triggered from print preview
    '''
    try:
        # Verify user has read permission
        if not frappe.has_permission(doctype, "read", docname):
            frappe.throw("No permission to access this document")

        # Get the document
        doc = frappe.get_doc(doctype, docname)

        # Perform custom action
        # Example: Log the print action
        frappe.logger().info(f"Custom print action for {doctype} - {docname}")

        # Example: Add a comment
        doc.add_comment("Info", f"Document previewed by {frappe.session.user}")

        return {
            "success": True,
            "message": f"Custom action completed for {docname}"
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Custom Print Action Error")
        frappe.throw(str(e))
