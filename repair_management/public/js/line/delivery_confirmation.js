// Delivery Confirmation (POD) form script.
// Renders a Google Static Map for the captured latitude/longitude and opens the
// interactive Google Maps view in a new tab when clicked.
frappe.provide("repair_management.delivery_confirmation");

(() => {
	"use strict";

	const MAP_ZOOM = 17;
	const MAP_SIZE = "640x320";

	// The Maps browser key lives in site_config; cache the single fetch per page load.
	let key_promise = null;
	function google_maps_api_key() {
		if (!key_promise) {
			key_promise = frappe
				.xcall("repair_management.api.get_google_maps_api_key")
				.catch(() => "");
		}
		return key_promise;
	}

	function static_map_url(latitude, longitude, api_key) {
		const center = `${latitude},${longitude}`;
		const params = new URLSearchParams({
			center: center,
			zoom: MAP_ZOOM,
			size: MAP_SIZE,
			scale: "2",
			maptype: "roadmap",
			markers: `color:red|${center}`,
			key: api_key,
		});
		return `https://maps.googleapis.com/maps/api/staticmap?${params.toString()}`;
	}

	function google_maps_url(latitude, longitude) {
		const query = encodeURIComponent(`${latitude},${longitude}`);
		return `https://www.google.com/maps/search/?api=1&query=${query}`;
	}

	async function render_location_map(frm) {
		const field = frm.get_field("location_map");
		if (!field) return;

		const $wrapper = field.$wrapper.empty();
		const latitude = frm.doc.latitude;
		const longitude = frm.doc.longitude;
		if (!latitude || !longitude) {
			$wrapper.append(
				`<div class="text-muted">${__("No location captured for this delivery.")}</div>`
			);
			return;
		}

		const map_url = google_maps_url(latitude, longitude);
		const api_key = await google_maps_api_key();

		const $link = $("<a>", {
			class: "pod-location-map",
			href: map_url,
			target: "_blank",
			rel: "noopener noreferrer",
			title: __("Open in Google Maps"),
			css: { display: "block", "max-width": "640px" },
		});

		// Without a key the Static Maps image would render as a broken tile, so the
		// link degrades to a plain text link instead of showing a dead image.
		if (api_key) {
			$link.append(
				$("<img>", {
					src: static_map_url(latitude, longitude, api_key),
					alt: __("Delivery location map"),
					loading: "lazy",
					css: {
						width: "100%",
						height: "auto",
						border: "1px solid var(--border-color)",
						"border-radius": "var(--border-radius-md)",
						cursor: "pointer",
						display: "block",
					},
				})
			);
		}

		$link.append(
			$("<div>", {
				class: "text-muted small",
				css: { "margin-top": "4px" },
				text: `${latitude}, ${longitude} · ${__("Open in Google Maps")} ↗`,
			})
		);

		$wrapper.append($link);
	}

	repair_management.delivery_confirmation.render_location_map = render_location_map;

	frappe.ui.form.on("Delivery Confirmation", {
		refresh(frm) {
			render_location_map(frm);
		},
	});
})();
