import hashlib,json
import frappe
from frappe.utils import now_datetime
from repair_management.integrations.line.api.client import LineClient
from repair_management.integrations.line.utils.files import resolve_file_path

def build_payload(doc):
    areas=[]
    for a in sorted([x for x in doc.areas if x.enabled],key=lambda x:x.sort_order or x.idx):
        if a.action_type=="Postback":
            act={"type":"postback","label":a.area_label,"data":a.postback_data or f"action={a.action_key}"}
            if a.display_text:
                act["displayText"]=a.display_text
            if a.input_option:
                act["inputOption"]=a.input_option
                if a.input_option=="openKeyboard" and a.fill_in_text:
                    act["fillInText"]=a.fill_in_text
        elif a.action_type=="Message":act={"type":"message","label":a.area_label,"text":a.message_text or a.area_label}
        else:act={"type":"uri","label":a.area_label,"uri":a.uri}
        if a.x+a.width>doc.width or a.y+a.height>doc.height:frappe.throw(f"Area {a.idx} exceeds menu bounds")
        areas.append({"bounds":{"x":int(a.x),"y":int(a.y),"width":int(a.width),"height":int(a.height)},"action":act})
    if not areas:frappe.throw("At least one enabled area is required")
    return {"size":{"width":int(doc.width),"height":int(doc.height)},"selected":bool(doc.selected),"name":doc.menu_name,"chatBarText":doc.chat_bar_text,"areas":areas}

@frappe.whitelist()
def validate_draft(definition_name):return build_payload(frappe.get_doc("LINE Rich Menu Definition",definition_name))

@frappe.whitelist()
def deploy(definition_name):
    doc=frappe.get_doc("LINE Rich Menu Definition",definition_name);payload=build_payload(doc);path=resolve_file_path(doc.rich_menu_image);image=path.read_bytes();text=json.dumps(payload,ensure_ascii=False,separators=(",",":"));version=frappe.db.count("LINE Rich Menu Deployment",{"rich_menu_definition":doc.name})+1
    dep=frappe.get_doc({"doctype":"LINE Rich Menu Deployment","line_channel":doc.line_channel,"rich_menu_definition":doc.name,"version":version,"scope":doc.scope,"payload_snapshot":text,"image_snapshot":doc.rich_menu_image,"payload_sha256":hashlib.sha256(text.encode()).hexdigest(),"image_sha256":hashlib.sha256(image).hexdigest(),"deployment_status":"Validated"}).insert()
    client=LineClient(doc.line_channel)
    try:
        rid=client.create_rich_menu(payload);dep.db_set({"line_rich_menu_id":rid,"deployment_status":"Created"});client.upload_image(rid,image,path.name);dep.db_set("deployment_status","Image Uploaded")
        if doc.scope=="Default":client.set_default(rid)
        dep.db_set({"deployment_status":"Active","activated_at":now_datetime()});doc.db_set("current_active_deployment",dep.name);return {"deployment":dep.name,"rich_menu_id":rid}
    except Exception as e:dep.db_set({"deployment_status":"Failed","error_response":str(e)});raise

@frappe.whitelist()
def sync_recipient(assignment_name):
    a=frappe.get_doc("LINE Rich Menu Recipient Assignment",assignment_name);client=LineClient(a.line_channel);dep=a.direct_deployment_override or (a.audience and frappe.db.get_value("LINE Rich Menu Audience",a.audience,"active_deployment"))
    if not a.enabled or not dep:client.unlink_user(a.line_user_id);a.db_set("sync_status","Unlinked");return {"status":"Unlinked"}
    d=frappe.get_doc("LINE Rich Menu Deployment",dep);client.link_user(a.line_user_id,d.line_rich_menu_id);actual=client.get_user_menu(a.line_user_id);status="Verified" if actual==d.line_rich_menu_id else "Mismatch";a.db_set({"desired_rich_menu_id":d.line_rich_menu_id,"actual_rich_menu_id":actual,"sync_status":status,"last_verified_at":now_datetime()});return {"status":status}
