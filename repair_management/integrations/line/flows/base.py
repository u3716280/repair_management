import json,frappe
from frappe.utils import add_to_date,now_datetime

def create_session(channel,user,flow,state,context=None):return frappe.get_doc({"doctype":"LINE Flow Session","line_channel":channel,"line_user_id":user,"business_flow":flow.name,"action_key":flow.action_key,"current_state":state,"context_json":json.dumps(context or {},ensure_ascii=False),"expires_at":add_to_date(now_datetime(),minutes=int(flow.session_expiry_minutes or 15)),"status":"Active"}).insert()
def active(channel,user):
    n=frappe.db.get_value("LINE Flow Session",{"line_channel":channel,"line_user_id":user,"status":"Active","expires_at":[">",now_datetime()]},"name",order_by="creation desc");return frappe.get_doc("LINE Flow Session",n) if n else None
def context(s):
    try:return json.loads(s.context_json or "{}")
    except:return {}
def set_context(s,c,state=None):
    v={"context_json":json.dumps(c,ensure_ascii=False)}
    if state:v["current_state"]=state
    s.db_set(v)
