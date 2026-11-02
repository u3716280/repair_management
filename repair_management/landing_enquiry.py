"""Quote requests from the public landing page (www/home.html)."""

import re

import frappe
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.rate_limiter import rate_limit
from frappe.utils import cstr, escape_html, now_datetime, validate_email_address

SYSTEMS = {
	"kitchen": "ระบบดูดควันครัว",
	"makeup": "ระบบลมชดเชย",
	"fresh": "ระบบอากาศบริสุทธิ์",
	"dust": "ระบบดูดฝุ่นและมลพิษ",
	"other": "ยังไม่แน่ใจ",
}
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s\-()]{7,18}$")
ALERT_ROLE = "Sales Manager"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60)
def submit_enquiry(
	full_name=None,
	phone=None,
	email=None,
	company=None,
	system=None,
	details=None,
	consent=None,
	website=None,
):
	# Real visitors never see the "website" field, so a value means a bot.
	# Answer as usual so the bot learns nothing, and save nothing.
	if cstr(website).strip():
		return {"ok": True}

	full_name = cstr(full_name).strip()[:140]
	phone = cstr(phone).strip()
	email = cstr(email).strip()[:140]
	company = cstr(company).strip()[:140]
	details = cstr(details).strip()[:2000]

	if not full_name:
		frappe.throw("กรอกชื่อผู้ติดต่อ")
	if not PHONE_PATTERN.match(phone):
		frappe.throw("กรอกเบอร์โทรศัพท์ให้ถูกต้อง เช่น 081 234 5678")
	if email and not validate_email_address(email):
		frappe.throw("กรอกอีเมลให้ถูกต้อง หรือเว้นว่างไว้")
	if system not in SYSTEMS:
		frappe.throw("เลือกระบบที่ต้องการ")
	if cstr(consent) not in ("1", "true", "on"):
		frappe.throw("ยินยอมให้ติดต่อกลับก่อนส่งคำขอ")

	note = _note_html(SYSTEMS[system], company, details)
	existing = frappe.db.get_value("Lead", {"email_id": email}) if email else None
	if existing:
		# ERPNext allows one Lead per email, so a repeat enquiry joins the first.
		lead = frappe.get_doc("Lead", existing)
	else:
		lead = frappe.new_doc("Lead")
		lead.update(
			{
				"first_name": full_name,
				"mobile_no": phone,
				"email_id": email,
				"company_name": company,
				"source": "Website",
				"request_type": "Product Enquiry",
			}
		)

	lead.append("notes", {"note": note, "added_on": now_datetime()})
	lead.save(ignore_permissions=True)

	_alert_staff(lead, full_name, phone, SYSTEMS[system], details)
	return {"ok": True}


def _note_html(system_label, company, details):
	lines = [f"<b>คำขอใบเสนอราคาจากเว็บไซต์:</b> {escape_html(system_label)}"]
	if company:
		lines.append(f"<b>บริษัท/ร้าน:</b> {escape_html(company)}")
	if details:
		lines.append(f"<b>รายละเอียด:</b> {escape_html(details)}")
	return "<br>".join(lines)


def _alert_staff(lead, full_name, phone, system_label, details):
	"""Tell sales staff in Desk and by email. A failed alert must never lose the saved Lead."""
	try:
		users = frappe.get_all(
			"Has Role",
			filters={"role": ALERT_ROLE, "parenttype": "User"},
			pluck="parent",
			distinct=True,
		)
		users = [
			user
			for user in users
			if user not in ("Administrator", "Guest") and frappe.db.get_value("User", user, "enabled")
		]
		if not users:
			return

		name_html = escape_html(full_name)
		system_html = escape_html(system_label)
		subject = f"คำขอใบเสนอราคาใหม่จากเว็บไซต์: {name_html} ({system_html})"
		enqueue_create_notification(
			users,
			{"type": "Alert", "document_type": "Lead", "document_name": lead.name, "subject": subject},
		)

		# Frappe never emails "Alert" notifications, so send the email separately.
		# No link to the Lead: site_config host_name points at 127.0.0.1.
		lines = [
			f"<b>Lead:</b> {escape_html(lead.name)}",
			f"<b>ชื่อผู้ติดต่อ:</b> {name_html}",
			f"<b>เบอร์โทรศัพท์:</b> {escape_html(phone)}",
			f"<b>ระบบที่ต้องการ:</b> {system_html}",
		]
		if details:
			lines.append(f"<b>รายละเอียด:</b> {escape_html(details)}")
		frappe.sendmail(
			recipients=users, subject=f"คำขอใบเสนอราคาใหม่จากเว็บไซต์: {full_name}", message="<br>".join(lines)
		)
	except Exception:
		frappe.log_error(
			title="Landing page enquiry alert failed", reference_doctype="Lead", reference_name=lead.name
		)
