import frappe
from frappe import _
import base64
from io import BytesIO

no_cache = 1

def get_context(context):
    """This function is called by Frappe's web page handler"""
    
    # Get parameters
    doctype = frappe.form_dict.doctype
    name = frappe.form_dict.name
    format_name = frappe.form_dict.format
    letterhead = frappe.form_dict.get('letterhead')
    no_letterhead = frappe.form_dict.get('no_letterhead', 0)
    
    # Get and validate document
    doc = frappe.get_doc(doctype, name)
    
    # Validate permissions
    if not frappe.has_permission(doctype, "print", doc):
        frappe.throw(_("No permission to print"), frappe.PermissionError)
    
    # Generate PDF
    pdf_file = frappe.get_print(
        doctype,
        name,
        format_name,
        doc=doc,
        as_pdf=True,
        letterhead=letterhead,
        no_letterhead=no_letterhead,
    )
    
    # Convert PDF to JPG
    from pdf2image import convert_from_bytes
    
    images = convert_from_bytes(pdf_file, first_page=1, last_page=1, dpi=300)
    
    # Convert PIL Image to JPG bytes
    img_byte_arr = BytesIO()
    images[0].save(img_byte_arr, format='JPEG', quality=95)
    jpg_file = img_byte_arr.getvalue()
    
    # Encode to base64
    img_base64 = base64.b64encode(jpg_file).decode('utf-8')
    
    # Pass data to template
    context.doc_name = name
    context.img_base64 = img_base64
    context.no_cache = 1
    
    return context