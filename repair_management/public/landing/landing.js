(function () {
	"use strict";

	// Staff menu
	const menu = document.querySelector("[data-staff-menu]");
	const toggle = menu.querySelector("button");
	const list = menu.querySelector("ul");
	const setOpen = (open) => {
		toggle.setAttribute("aria-expanded", String(open));
		list.hidden = !open;
	};
	toggle.addEventListener("click", () => setOpen(list.hidden));
	document.addEventListener("click", (e) => {
		if (!menu.contains(e.target)) setOpen(false);
	});
	menu.addEventListener("keydown", (e) => {
		if (e.key === "Escape" && !list.hidden) {
			setOpen(false);
			toggle.focus();
		}
	});
	menu.addEventListener("focusout", (e) => {
		if (e.relatedTarget && !menu.contains(e.relatedTarget)) setOpen(false);
	});

	// Quote form
	const form = document.querySelector("[data-quote-form]");
	const status = form.querySelector("[data-form-status]");
	const button = form.querySelector("button[type=submit]");
	const success = document.querySelector("[data-quote-success]");
	const FALLBACK = "ส่งคำขอไม่สำเร็จ ตรวจสอบอินเทอร์เน็ตแล้วลองส่งอีกครั้ง";
	const TOO_MANY = "ส่งคำขอครบจำนวนที่กำหนดแล้ว ลองอีกครั้งในอีก 1 ชั่วโมง";

	const serverMessage = (data) => {
		try {
			return JSON.parse(JSON.parse(data._server_messages)[0]).message;
		} catch (err) {
			return null;
		}
	};

	form.addEventListener("submit", async (e) => {
		e.preventDefault();
		status.textContent = "";
		if (!form.reportValidity()) return;

		button.disabled = true;
		const body = new URLSearchParams(new FormData(form));
		const headers = { Accept: "application/json" };
		if (form.dataset.csrf) headers["X-Frappe-CSRF-Token"] = form.dataset.csrf;

		try {
			const res = await fetch(
				"/api/method/repair_management.landing_enquiry.submit_enquiry",
				{
					method: "POST",
					headers,
					body,
				}
			);
			const data = await res.json().catch(() => ({}));
			if (res.ok) {
				form.hidden = true;
				success.hidden = false;
				success.focus();
				return;
			}
			status.textContent = res.status === 429 ? TOO_MANY : serverMessage(data) || FALLBACK;
		} catch (err) {
			status.textContent = FALLBACK;
		}
		button.disabled = false;
	});
})();
