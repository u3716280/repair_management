import frappe

def search(config,kind,keyword):
    fields=["name","item_name","item_group","stock_uom"];filters={"disabled":0};or_filters=[];serial=None
    if kind=="any":serial=frappe.db.get_value("Serial No",keyword,["name","item_code","warehouse"],as_dict=True)
    if kind=="item_code":or_filters=[["Item","name","like",f"%{keyword}%"]]
    elif kind=="item_name":or_filters=[["Item","item_name","like",f"%{keyword}%"]]
    elif kind=="item_group":filters["item_group"]=keyword
    else:or_filters=[["Item","name","like",f"%{keyword}%"],["Item","item_name","like",f"%{keyword}%"],["Item","item_group","like",f"%{keyword}%"]]
    rows=frappe.get_all("Item",filters=filters,or_filters=or_filters,fields=fields,limit=int(config.maximum_search_results or 10));return rows,serial

def detail(config,item_code):
    item=frappe.get_doc("Item",item_code);wf={"is_group":0,"disabled":0};
    if config.company:wf["company"]=config.company
    allowed=[x.warehouse for x in config.allowed_warehouses if x.warehouse]
    if allowed:wf["name"]=["in",allowed]
    wh=frappe.get_all("Warehouse",filters=wf,pluck="name");bins=frappe.get_all("Bin",filters={"item_code":item_code,"warehouse":["in",wh or [""]]},fields=["warehouse","actual_qty"])
    return {"item_code":item.name,"item_name":item.item_name,"item_group":item.item_group,"stock_uom":item.stock_uom,"warehouses":[dict(x) for x in bins],"total_actual_qty":sum(float(x.actual_qty or 0) for x in bins),"purchase_rate":(item.last_purchase_rate or item.valuation_rate) if config.show_purchase_price else None,"selling_rate":frappe.db.get_value("Item Price",{"item_code":item_code,"price_list":config.selling_price_list,"selling":1},"price_list_rate") if config.show_selling_price and config.selling_price_list else None}
