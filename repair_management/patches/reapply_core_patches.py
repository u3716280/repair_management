from __future__ import annotations

import frappe

DEFAULT_PUBLIC_BASE_URL = "https://house147.eakthai.com"


def after_migrate() -> None:
	"""Re-apply idempotent core-file patches that `bench update` silently wipes.

	`google_redirect_base_url`, `public_form_link_base_url` (and the now-superseded
	`delete_doc_public_link`) edit installed Frappe core files directly. A
	`bench update` (or reinstalling the frappe app) overwrites those files back
	to stock via git, but plain `bench migrate` does not re-run these ad-hoc
	patches on its own - they're intentionally not wired into patches.txt (see
	each patch's howto.txt). This hook re-applies them on every migrate instead.

	Each apply() call is idempotent (no-ops if already patched), so running
	this on every migrate is cheap and safe.
	"""
	_reapply_google_redirect_base_url()
	_reapply_public_form_link_base_url()


def _reapply_google_redirect_base_url() -> None:
	from repair_management.patches.google_redirect_base_url import apply

	# Preserve whatever public_url is already configured instead of clobbering
	# it back to the hardcoded default on every migrate.
	public_url = frappe.conf.get("google_redirect_base_url") or DEFAULT_PUBLIC_BASE_URL

	try:
		result = apply(public_url=public_url)
		frappe.logger("repair_management").info(
			f"[reapply_core_patches] google_redirect_base_url: {result.get('status')}"
		)
	except Exception:
		frappe.log_error(
			title="reapply_core_patches: google_redirect_base_url failed",
			message=frappe.get_traceback(),
		)


def _reapply_public_form_link_base_url() -> None:
	from repair_management.patches.public_form_link_base_url import apply

	try:
		result = apply()
		frappe.logger("repair_management").info(
			f"[reapply_core_patches] public_form_link_base_url: {result.get('status')}"
		)
	except Exception:
		frappe.log_error(
			title="reapply_core_patches: public_form_link_base_url failed",
			message=frappe.get_traceback(),
		)
