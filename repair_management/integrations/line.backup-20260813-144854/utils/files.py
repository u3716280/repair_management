from pathlib import Path
from urllib.parse import urlparse
import frappe

def resolve_file_path(url):
    path=urlparse(url or "").path
    if path.startswith("/private/files/"):return Path(frappe.get_site_path("private","files",path.split("/private/files/",1)[1]))
    if path.startswith("/files/"):return Path(frappe.get_site_path("public","files",path.split("/files/",1)[1]))
    raise ValueError("Unsupported file URL")
