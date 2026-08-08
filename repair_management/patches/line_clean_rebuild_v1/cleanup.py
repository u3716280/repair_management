from __future__ import annotations
import json, os, datetime
from pathlib import Path
import frappe, requests

LEGACY=["LINE Sales Order Settings","LINE Upload Session","LINE Upload File","LINE Rich Menu","LINE Rich Menu Area","LINE Rich Menu Policy","LINE Rich Menu Deployment","LINE Rich Menu Log","LINE Rich Menu Recipient Link","LINE Channel","LINE Rich Menu Definition","LINE Rich Menu Audience","LINE Rich Menu Recipient Assignment","LINE Action Registry","LINE Business Flow","LINE Flow Session","LINE Stock Query Configuration","LINE Stock Allowed Warehouse","LINE Stock Allowed Item Group","LINE Document Media Upload Profile","LINE Document Search Field","LINE Document Display Field","LINE Document Filter","LINE Media File","LINE Webhook Event","LINE Integration Log"]

def _token():
    value=os.getenv("LINE_CHANNEL_ACCESS_TOKEN","").strip()
    if value:return value
    for dt in ("LINE Sales Order Settings","LINE Account List","LINE Channel"):
        if not frappe.db.exists("DocType",dt):continue
        meta=frappe.get_meta(dt); fields=[f.fieldname for f in meta.fields if f.fieldname in ("channel_access_token","access_token","long_lived_channel_access_token")]
        names=[dt] if meta.issingle else frappe.get_all(dt,pluck="name")
        for name in names:
            doc=frappe.get_doc(dt,name)
            for field in fields:
                try:v=doc.get_password(field,raise_exception=False) if meta.get_field(field).fieldtype=="Password" else doc.get(field)
                except Exception:v=doc.get(field)
                if v:return v

def _users():
    out=set()
    for dt in ("LINE Recipient","LINE Rich Menu Recipient Link","LINE Rich Menu Recipient Assignment"):
        if not frappe.db.exists("DocType",dt):continue
        meta=frappe.get_meta(dt)
        for field in ("recipient_id","line_user_id","user_id"):
            if meta.get_field(field):
                out.update(v for v in frappe.get_all(dt,pluck=field) if isinstance(v,str) and v.startswith("U"))
    return sorted(out)

def _api(token,method,path):
    r=requests.request(method,"https://api.line.me"+path,headers={"Authorization":"Bearer "+token},timeout=30)
    if r.status_code not in (200,201,202,204,404):raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r

def _save(data,prefix):
    p=Path(frappe.get_site_path("private","backups"));p.mkdir(parents=True,exist_ok=True)
    f=p/(prefix+datetime.datetime.now().strftime("-%Y%m%d-%H%M%S.json"));f.write_text(json.dumps(data,ensure_ascii=False,indent=2));return str(f)

@frappe.whitelist()
def audit():
    token=_token(); remote=[]
    if token:
        r=_api(token,"GET","/v2/bot/richmenu/list");remote=r.json().get("richmenus",[])
    result={"site":frappe.local.site,"existing_doctypes":[d for d in LEGACY if frappe.db.exists("DocType",d)],"known_user_ids":_users(),"remote_richmenus":remote,"token_found":bool(token)}
    result["audit_file"]=_save(result,"line-clean-rebuild-audit");print(json.dumps(result,ensure_ascii=False));return result

@frappe.whitelist()
def remote_cleanup():
    token=_token()
    if not token:frappe.throw("Set LINE_CHANNEL_ACCESS_TOKEN before remote cleanup")
    for user in _users():_api(token,"DELETE",f"/v2/bot/user/{user}/richmenu")
    _api(token,"DELETE","/v2/bot/user/all/richmenu")
    menus=_api(token,"GET","/v2/bot/richmenu/list").json().get("richmenus",[])
    deleted=[]
    for menu in menus:
        rid=menu.get("richMenuId")
        if rid:_api(token,"DELETE",f"/v2/bot/richmenu/{rid}");deleted.append(rid)
    result={"deleted":deleted,"remaining":_api(token,"GET","/v2/bot/richmenu/list").json().get("richmenus",[])}
    result["audit_file"]=_save(result,"line-clean-rebuild-remote");print(json.dumps(result));return result

@frappe.whitelist()
def local_cleanup():
    removed=[]
    if frappe.db.exists("DocType","LINE Recipient"):
        for row in frappe.get_all("Custom Field",filters={"dt":"LINE Recipient"},fields=["name","fieldname"]):
            if (row.fieldname or "").startswith("custom_line_") or row.fieldname in ("custom_allow_secure_rich_menu","custom_rich_menu_sync_status","custom_linked_rich_menu_id","custom_rich_menu_synced_at","custom_rich_menu_sync_error"):
                frappe.delete_doc("Custom Field",row.name,force=True,ignore_permissions=True)
    for dt in LEGACY:
        if frappe.db.exists("DocType",dt):frappe.delete_doc("DocType",dt,force=True,ignore_permissions=True);removed.append(dt)
    if frappe.db.exists("Workspace","LINE"):frappe.delete_doc("Workspace","LINE",force=True,ignore_permissions=True)
    frappe.db.commit();result={"removed_doctypes":removed};print(json.dumps(result));return result
