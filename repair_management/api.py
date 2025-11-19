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

import frappe

@frappe.whitelist()
def get_customer_addresses(customer_name):
    """Get all addresses linked to a customer"""
    
    # Get address names linked to this customer
    address_links = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer_name,
            "parenttype": "Address"
        },
        fields=["parent"],
        ignore_permissions=True  # Run with elevated permissions
    )
    
    address_names = [link.parent for link in address_links]
    
    if not address_names:
        return []
    
    # Get full address details
    addresses = frappe.get_all(
        "Address",
        filters={"name": ["in", address_names]},
        fields=[
            "name",
            "address_title",
            "address_line1",
            "city",
            "country",
            "latitude",
            "longitude"
        ]
    )
    
    return addresses
