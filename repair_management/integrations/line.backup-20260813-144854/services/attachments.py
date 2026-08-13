import frappe
from frappe.utils.file_manager import save_file

def save(content,filename,doctype,name,is_private=True):return save_file(filename,content,doctype,name,is_private=int(is_private),decode=False)
def relink(file_name,doctype,name):
    f=frappe.get_doc("File",file_name);f.db_set({"attached_to_doctype":doctype,"attached_to_name":name,"attached_to_field":None});return f
