from __future__ import annotations
import requests,time,mimetypes
import frappe
class LineClient:
    def __init__(self,channel):
        self.channel=frappe.get_doc("LINE Channel",channel);self.token=self.channel.get_password("channel_access_token",raise_exception=False)
        if not self.token:frappe.throw("Missing LINE Channel Access Token")
    def request(self,method,path,api_data=False,json_data=None,data=None,content_type=None,accepted=(200,201,202,204),timeout=30):
        h={"Authorization":"Bearer "+self.token};
        if content_type:h["Content-Type"]=content_type
        base="https://api-data.line.me" if api_data else "https://api.line.me"
        r=requests.request(method,base+path,headers=h,json=json_data,data=data,timeout=timeout)
        if r.status_code not in accepted:raise RuntimeError(f"LINE API {r.status_code}: {r.text[:500]}")
        return r
    def reply(self,token,messages):
        if token:self.request("POST","/v2/bot/message/reply",json_data={"replyToken":token,"messages":messages[:5]})
    def push(self,user,messages):self.request("POST","/v2/bot/message/push",json_data={"to":user,"messages":messages[:5]})
    def get_content(self,message_id):
        for i in range(5):
            r=self.request("GET",f"/v2/bot/message/{message_id}/content",api_data=True,accepted=(200,202),timeout=120)
            if r.status_code==200:return r.content,r.headers.get("Content-Type","application/octet-stream")
            time.sleep(3*(i+1))
        raise RuntimeError("Content not ready")
    def verify(self):return self.request("GET","/v2/bot/richmenu/list").json()
    def create_rich_menu(self,payload):return self.request("POST","/v2/bot/richmenu",json_data=payload).json()["richMenuId"]
    def upload_image(self,rid,data,filename):self.request("POST",f"/v2/bot/richmenu/{rid}/content",api_data=True,data=data,content_type=mimetypes.guess_type(filename)[0] or "image/jpeg",timeout=120)
    def set_default(self,rid):self.request("POST",f"/v2/bot/user/all/richmenu/{rid}")
    def link_user(self,user,rid):self.request("POST",f"/v2/bot/user/{user}/richmenu/{rid}")
    def unlink_user(self,user):self.request("DELETE",f"/v2/bot/user/{user}/richmenu",accepted=(200,204,404))
    def get_user_menu(self,user):
        r=self.request("GET",f"/v2/bot/user/{user}/richmenu",accepted=(200,404));return None if r.status_code==404 else r.json().get("richMenuId")
    def get_profile(self,user_id):
        return self.request("GET",f"/v2/bot/profile/{user_id}").json()
