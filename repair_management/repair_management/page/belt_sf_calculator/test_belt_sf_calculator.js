/* Calculation tests for the Belt SF Calculator page. No site or database is touched.
 * Run from this folder: node --test test_belt_sf_calculator.js
 *
 * Expected values come from Bando Data Edition p.308-309 (tension formula, worked
 * example) and the Bando V-Belt Tension Gauge chart. The stage factors X = 1.0 / 0.8 / 0.7
 * are set values, not Bando's 1.5 / 1.3 / 1.0. The US design manual's HP rating
 * tables were not available, so rating values are checked for behaviour only.
 */
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const context = vm.createContext({
	frappe: { pages: { "belt-sf-calculator": {} } },
	__: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, i) => args[i]),
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "belt_sf_calculator.js"), "utf8"), context);
const { compute_belt_drive, deflection_load } = context;
const BELT_DATA = vm.runInContext("BELT_DATA", context);

const LBF = 4.44822;
const drive = (overrides) => ({
	power_kw: 7.5,
	rpm: 1450,
	belts: 3,
	length_mm: 1800,
	sf: 1.4,
	d_driver: 125,
	d_driven: 280,
	...overrides,
});
const near = (actual, expected, tolerance, message) =>
	assert.ok(
		Math.abs(actual - expected) <= tolerance,
		`${message || ""} expected ${expected}, got ${actual}`
	);

test("Bando's worked example: 9 × 8V3150, To = 18664 N, new belt = 200.5 N", () => {
	near(deflection_load(1.5, 18664 / 9, 98), 200.5, 0.05);
});

test("tension follows Bando Steps 2-5 with the set X at all three stages", () => {
	const r = compute_belt_drive(drive(), "SPA");
	const V = (Math.PI * 125 * 1450) / 60000;
	const Pd = 7.5 * 1.4 * 1000;
	const Tt = (1.25 * Pd) / (r.FA * V) + 3 * 0.12 * V * V;
	const Ts = (((1.25 - r.FA) / r.FA) * Pd) / V + 3 * 0.12 * V * V;
	const To = (0.9 * (Tt + Ts)) / 2;
	[1.0, 0.8, 0.7].forEach((x, i) => {
		assert.strictEqual(r.stages[i].x, x);
		near(r.stages[i].force, (x * (To / 3) + 15) / 16, 1e-6, `X=${x} force`);
		near(r.stages[i].tension, x * (To / 3), 1e-6, `X=${x} tension`);
		assert.strictEqual(r.stages[i].at_minimum, false);
	});
});

test("new belt tension is above the later re-tension value", () => {
	const [first, , later] = compute_belt_drive(drive(), "SPA").stages;
	near(first.tension / later.tension, 1.0 / 0.7, 1e-9);
	assert.ok(first.force > later.force);
});

test("light drives are held at the Tension Gauge chart Min × X", () => {
	// SPZ ≈ 3V, 100 mm = 3.94 in, chart row 3.65-4.12 in: Min 4.4 lbf
	const r = compute_belt_drive(
		drive({ power_kw: 0.05, sf: 1, belts: 1, d_driver: 100, d_driven: 100, length_mm: 1000 }),
		"SPZ"
	);
	[4.4 * 1.0, 4.4 * 0.8, 4.4 * 0.7].forEach((lbf, i) => {
		near(r.stages[i].force, lbf * LBF, 1e-6);
		assert.strictEqual(r.stages[i].at_minimum, true);
	});
});

test("geometry and capacity for a normal SPA drive", () => {
	const r = compute_belt_drive(drive(), "SPA");
	const L = 2 * r.C + (Math.PI * (280 + 125)) / 2 + Math.pow(280 - 125, 2) / (4 * r.C);
	near(L, 1800, 1e-6, "belt length from C");
	assert.strictEqual(r.rate.valid, true);
	near(r.rate.corrected_hp, 5.06, 0.01);
	assert.strictEqual(r.belts_needed, 3);
});

test("capacity is withheld outside the rating table", () => {
	const cases = [
		["SPB under the 5V table", { d_driver: 140, length_mm: 2000 }, "SPB"],
		["RPM under the table", { d_driver: 100, d_driven: 200, length_mm: 1500, rpm: 300 }, "A"],
		["pulley over the AX table", { d_driver: 200, d_driven: 400, length_mm: 2500 }, "SPA"],
		[
			"no published rating (3V, 14 in, 2850 RPM)",
			{ d_driver: 355, d_driven: 400, length_mm: 3000, rpm: 2850 },
			"SPZ",
		],
	];
	cases.forEach(([name, overrides, profile]) => {
		const r = compute_belt_drive(drive(overrides), profile);
		assert.strictEqual(r.rate.valid, false, name);
		assert.strictEqual(r.belts_needed, null, name);
		assert.strictEqual(r.actual_sf, null, name);
		assert.ok(r.stages[0].tension > 0, `${name}: tension still available`);
	});
});

test("standard sizes at a table edge are not rejected", () => {
	assert.strictEqual(
		compute_belt_drive(drive({ d_driver: 180, length_mm: 2000 }), "SPB").rate.valid,
		true
	);
	assert.strictEqual(
		compute_belt_drive(drive({ d_driver: 76, d_driven: 150, length_mm: 1500 }), "A").rate
			.valid,
		true
	);
});

test("overlapping pulleys are rejected", () => {
	assert.match(
		compute_belt_drive(drive({ d_driver: 90, d_driven: 400, length_mm: 1300 }), "SPA").error,
		/พูลเลย์ชนกัน/
	);
	assert.match(
		compute_belt_drive(drive({ d_driver: 200, d_driven: 200, length_mm: 800 }), "SPA").error,
		/พูลเลย์ชนกัน/
	);
});

test("belt length outside the FL table warns", () => {
	const warned = (length_mm) =>
		compute_belt_drive(drive({ d_driver: 100, d_driven: 200, length_mm }), "A").warns.some(
			(w) => w.includes("ตาราง FL")
		);
	assert.strictEqual(warned(5000), true);
	assert.strictEqual(warned(1800), false);
});

test("invalid inputs are rejected", () => {
	assert.match(compute_belt_drive(drive({ sf: 0.5 }), "SPA").error, /Service Factor/);
	assert.match(compute_belt_drive(drive({ belts: 1.5 }), "SPA").error, /จำนวนเต็ม/);
	assert.match(compute_belt_drive(drive({ rpm: NaN }), "SPA").error, /กรอกข้อมูล/);
});

test("the SPZ default pulley is a listed size with a valid rating", () => {
	assert.ok(BELT_DATA.SPZ.std_dia.includes(BELT_DATA.SPZ.default_dia));
	const r = compute_belt_drive(drive({ d_driver: 71, d_driven: 71, length_mm: 1000 }), "SPZ");
	assert.strictEqual(r.rate.valid, true);
});

test("pulley lists start at the profile minimum", () => {
	Object.values(BELT_DATA).forEach((belt) => {
		assert.strictEqual(belt.std_dia[0], belt.min_dia);
	});
});
