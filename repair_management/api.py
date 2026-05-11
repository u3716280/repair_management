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

import frappe
from frappe.utils import getdate, cint, get_datetime

@frappe.whitelist()
def get_customer_purchase_heatmap(customer, year=None):
    year = cint(year) or getdate().year

    rows = frappe.db.sql("""
        SELECT
            posting_date,
            COUNT(name) AS invoice_count,
            SUM(grand_total) AS total_amount
        FROM `tabSales Invoice`
        WHERE
            customer = %(customer)s
            AND docstatus = 1
            AND YEAR(posting_date) = %(year)s
        GROUP BY posting_date
        ORDER BY posting_date
    """, {
        "customer": customer,
        "year": year
    }, as_dict=True)

    data_points = {}

    for r in rows:
        ts = int(get_datetime(r.posting_date).timestamp())
        data_points[ts] = r.invoice_count

    return {
        "year": year,
        "dataPoints": data_points,
        "total_invoice_days": len(rows),
        "total_invoices": sum(r.invoice_count for r in rows),
        "total_amount": sum(r.total_amount or 0 for r in rows)
    }


# Custom Serial No.
import frappe


@frappe.whitelist()
def sync_stock_entry_serial_text(stock_entry):
    if not stock_entry:
        frappe.throw("Missing Stock Entry name")

    doc = frappe.get_doc("Stock Entry", stock_entry)

    if not doc.has_permission("write"):
        frappe.throw("Not permitted")

    updated_rows = 0

    for row in doc.items:
        serials = []

        # 1) กรณี serial อยู่ใน Stock Entry Detail.serial_no
        if row.serial_no:
            serials.extend([
                sn.strip()
                for sn in row.serial_no.replace(",", "\n").split("\n")
                if sn.strip()
            ])

        # 2) กรณีมี serial_and_batch_bundle ใน row
        if row.serial_and_batch_bundle:
            bundle_serials = frappe.db.sql("""
                SELECT serial_no
                FROM `tabSerial and Batch Entry`
                WHERE parent = %s
                  AND serial_no IS NOT NULL
                  AND serial_no != ''
                ORDER BY idx
            """, row.serial_and_batch_bundle, as_dict=True)

            serials.extend([
                d.serial_no.strip()
                for d in bundle_serials
                if d.serial_no
            ])

        # 3) fallback: หา bundle จาก voucher_detail_no = row.name
        if not serials:
            bundle_serials = frappe.db.sql("""
                SELECT sbe.serial_no
                FROM `tabSerial and Batch Entry` sbe
                INNER JOIN `tabSerial and Batch Bundle` sbb
                    ON sbb.name = sbe.parent
                WHERE sbb.voucher_detail_no = %s
                  AND sbe.serial_no IS NOT NULL
                  AND sbe.serial_no != ''
                ORDER BY sbe.idx
            """, row.name, as_dict=True)

            serials.extend([
                d.serial_no.strip()
                for d in bundle_serials
                if d.serial_no
            ])

        # 4) fallback สุดท้าย: หาโดย voucher_no + item_code
        # ใช้ในกรณี ERPNext ไม่ผูก voucher_detail_no
        if not serials:
            bundle_serials = frappe.db.sql("""
                SELECT sbe.serial_no
                FROM `tabSerial and Batch Entry` sbe
                INNER JOIN `tabSerial and Batch Bundle` sbb
                    ON sbb.name = sbe.parent
                WHERE sbb.voucher_no = %s
                  AND sbb.item_code = %s
                  AND sbe.serial_no IS NOT NULL
                  AND sbe.serial_no != ''
                ORDER BY sbe.idx
            """, (doc.name, row.item_code), as_dict=True)

            serials.extend([
                d.serial_no.strip()
                for d in bundle_serials
                if d.serial_no
            ])

        # ลบ serial ซ้ำ แต่คงลำดับเดิม
        clean_serials = []
        seen = set()

        for sn in serials:
            if sn and sn not in seen:
                clean_serials.append(sn)
                seen.add(sn)

        serial_text = "\n".join(clean_serials)

        frappe.db.set_value(
            "Stock Entry Detail",
            row.name,
            "custom_serial_no_text",
            serial_text,
            update_modified=False
        )

        if serial_text:
            updated_rows += 1

    frappe.db.commit()

    return {
        "updated_rows": updated_rows,
        "message": f"Synced serial text for {updated_rows} row(s)"
    }
