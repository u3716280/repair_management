frappe.pages['belt-sf-calculator'].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Belt SF Calculator (Bando)'),
		single_column: true,
	});
	new BeltSFCalculator(wrapper);
};

/* =========================================================
 *  Belt data — Bando V-Belt Design Manual (bandousa.com)
 * ========================================================= */
const BELT_DATA = {
	SPZ: { mass: 0.07, min_dia: 63,  max_speed: 42, rating: '3V',
		std_dia: [63, 71, 80, 90, 100, 112, 125, 140, 160, 180, 200, 224, 250, 280, 315] },
	SPA: { mass: 0.12, min_dia: 90,  max_speed: 42, rating: 'AX',
		std_dia: [90, 100, 112, 125, 140, 160, 180, 200, 224, 250, 280, 315, 355, 400] },
	SPB: { mass: 0.20, min_dia: 140, max_speed: 42, rating: '5V',
		std_dia: [140, 160, 180, 200, 224, 250, 280, 315, 355, 400, 450, 500] },
	A:   { mass: 0.11, min_dia: 76,  max_speed: 30, rating: 'A',
		std_dia: [76, 81, 86, 91, 97, 102, 107, 117, 122, 127, 132, 142, 147, 152,
			157, 163, 168, 178, 208, 229, 269, 305, 381, 457, 498] },
	B:   { mass: 0.19, min_dia: 137, max_speed: 30, rating: 'B',
		std_dia: [137, 142, 147, 152, 163, 173, 178, 188, 203, 218, 239, 279, 315,
			345, 391, 406, 467, 508, 635, 762, 965] },
};

/* Bando Table 1 — Typical Service Factors */
const SF_TABLE = [
	{ label: __('เครื่องกวนของเหลว, โบลเวอร์, ปั๊ม/คอมเพรสเซอร์แบบแรงเหวี่ยง, พัดลม ≤10 HP, สายพานลำเลียงเบา'),
		sf_normal: [1.0, 1.1, 1.2], sf_high: [1.1, 1.2, 1.3] },
	{ label: __('สายพานลำเลียงทราย/ธัญพืช, เครื่องผสมแป้ง, พัดลม >10 HP, เครื่องกำเนิดไฟฟ้า, เครื่องมือกล, ปั๊มโรตารี, เครื่องพิมพ์, ตะแกรงสั่น'),
		sf_normal: [1.1, 1.2, 1.3], sf_high: [1.2, 1.3, 1.4] },
	{ label: __('เครื่องจักรผลิตอิฐ, กระพ้อลำเลียง, คอมเพรสเซอร์ลูกสูบ, เครื่องบดละเอียด, โรงเลื่อย/งานไม้, เครื่องจักรสิ่งทอ, สกรูคอนเวเยอร์'),
		sf_normal: [1.2, 1.3, 1.4], sf_high: [1.4, 1.5, 1.6] },
	{ label: __('เครื่องโม่/ย่อยหิน (Crusher), Ball/Rod Mill, รอกยก, เครื่องรีด/อัดยาง'),
		sf_normal: [1.3, 1.4, 1.5], sf_high: [1.5, 1.6, 1.8] },
	{ label: __('อุปกรณ์ที่อุดตันได้ (Chokable Equipment)'),
		sf_normal: [2.0, 2.0, 2.0], sf_high: [2.0, 2.0, 2.0] },
];
const SF_HOURS = [
	__('เป็นครั้งคราว<br>3–5 ชม./วัน'),
	__('ปกติ<br>8–10 ชม./วัน'),
	__('ต่อเนื่อง<br>16–24 ชม./วัน'),
];

/* Bando Table 4 / 19 — Coefficient of Arc of Contact FA, step 0.10 of (D-d)/C */
const BANDO_FA = [1.00, 0.99, 0.97, 0.96, 0.94, 0.93, 0.91, 0.89,
	0.87, 0.85, 0.82, 0.80, 0.77, 0.73, 0.70, 0.65];

function bando_arc_factor(x) {
	const t = Math.min(Math.max(x, 0), 1.5) / 0.1;
	const i = Math.floor(t);
	if (i >= BANDO_FA.length - 1) return BANDO_FA[BANDO_FA.length - 1];
	return BANDO_FA[i] + (BANDO_FA[i + 1] - BANDO_FA[i]) * (t - i);
}

/* =========================================================
 *  Bando HP RATING TABLES (base HP per belt, small-sheave
 *  diameter in inches × faster-sheave RPM) + speed ratio
 *  adders + belt length coefficients.
 *  Source: Bando V-Belt Design Manual Tables 5,7-10,20,22-25,32-33
 *  SPZ→3V, SPB→5V (dimensionally equivalent sections),
 *  SPA→AX (closest section published in the manual; approx.)
 * ========================================================= */
const RPM_ROWS = [485, 575, 690, 725, 870, 950, 1160, 1425, 1750, 2850, 3450];

const RATING = {
	'3V': {
		dia: [2.65, 2.80, 3.00, 3.15, 3.35, 3.65, 4.12, 4.50, 4.75, 5.00, 5.30, 5.60, 6.00, 6.50, 6.90, 8.00, 10.60, 14.00, 19.00],
		rpm: RPM_ROWS,
		base: [
			[0.63,0.72,0.82,0.92,1.03,1.19,1.43,1.67,1.76,1.95,2.06,2.28,2.49,2.75,2.92,3.57,4.90,6.60,8.96],
			[0.73,0.83,0.94,1.07,1.21,1.37,1.67,1.94,2.05,2.26,2.40,2.66,2.90,3.21,3.41,4.16,5.70,7.69,10.43],
			[0.81,0.94,1.07,1.22,1.37,1.58,1.92,2.24,2.37,2.63,2.79,3.08,3.38,3.73,3.96,4.86,6.67,8.99,12.20],
			[0.85,0.98,1.11,1.27,1.43,1.64,2.00,2.34,2.47,2.75,2.92,3.23,3.54,3.91,4.15,5.08,6.97,9.40,12.76],
			[0.98,1.13,1.30,1.47,1.68,1.92,2.34,2.75,2.90,3.23,3.42,3.79,4.15,4.59,4.87,5.97,8.19,11.00,14.93],
			[1.05,1.22,1.39,1.60,1.80,2.07,2.52,2.97,3.13,3.49,3.70,4.09,4.49,4.97,5.27,6.45,8.82,11.85,16.08],
			[1.22,1.43,1.65,1.88,2.13,2.45,3.00,3.53,3.73,4.15,4.40,4.88,5.35,5.91,6.27,7.67,10.47,13.95,18.94],
			[1.44,1.69,1.94,2.23,2.53,2.92,3.57,4.21,4.45,4.95,5.24,5.82,6.38,7.05,7.49,9.13,12.39,16.36,22.20],
			[1.70,1.97,2.28,2.63,2.99,3.46,4.25,5.01,5.28,5.89,6.24,6.91,7.58,8.37,8.88,10.78,14.50,18.84,25.57],
			[2.40,2.84,3.31,3.83,4.38,5.07,6.27,7.37,7.78,8.65,9.17,10.10,11.01,12.10,12.85,15.11,17.79,null,null],
			[2.70,3.23,3.78,4.40,5.03,5.83,7.18,8.44,8.91,9.86,10.45,11.46,12.42,13.58,14.42,16.49,null,null,null],
		],
		bands: [1.02, 1.06, 1.12, 1.19, 1.27, 1.39, 1.58, 1.95, 3.39],
		adder: [
			[0,0.01,0.03,0.04,0.07,0.08,0.08,0.09,0.11,0.11],
			[0,0.01,0.03,0.05,0.07,0.09,0.11,0.12,0.12,0.13],
			[0,0.01,0.04,0.07,0.09,0.11,0.12,0.13,0.15,0.16],
			[0,0.01,0.04,0.07,0.09,0.11,0.13,0.15,0.16,0.17],
			[0,0.01,0.04,0.08,0.11,0.13,0.16,0.17,0.19,0.20],
			[0,0.01,0.05,0.09,0.12,0.15,0.17,0.19,0.21,0.23],
			[0,0.03,0.07,0.11,0.15,0.17,0.21,0.23,0.25,0.27],
			[0,0.03,0.08,0.13,0.17,0.21,0.25,0.28,0.31,0.34],
			[0,0.04,0.09,0.16,0.21,0.27,0.31,0.35,0.39,0.40],
			[0,0.05,0.15,0.27,0.36,0.44,0.51,0.58,0.63,0.67],
			[0,0.07,0.19,0.32,0.44,0.52,0.62,0.70,0.76,0.80],
		],
		len: [[25,0.83],[30,0.86],[35.5,0.89],[40,0.92],[50,0.96],[63,1.00],[75,1.03],[90,1.07],[106,1.10],[125,1.13],[140,1.15]],
	},
	'5V': {
		dia: [7.1, 7.5, 8.0, 8.5, 9.0, 9.25, 9.75, 10.3, 10.9, 11.8, 12.5, 13.2, 14.0, 15.0, 16.0],
		rpm: RPM_ROWS.slice(0, 9), // 485..1750
		base: [
			[6.38,7.00,7.72,8.49,9.25,9.76,10.54,11.30,12.29,13.52,14.61,15.73,16.85,18.31,19.71],
			[7.20,7.93,8.77,9.67,10.55,11.14,12.06,12.95,14.10,15.51,16.79,18.10,19.39,21.06,22.68],
			[8.41,9.27,10.26,11.32,12.35,13.05,14.13,15.17,16.52,18.17,19.66,21.18,22.68,24.62,26.49],
			[8.77,9.68,10.70,11.79,12.90,13.61,14.74,15.84,17.23,18.95,20.51,22.09,23.65,25.67,27.61],
			[10.22,11.28,12.49,13.77,15.06,15.89,17.21,18.48,20.11,22.12,23.90,25.71,27.51,29.81,32.03],
			[11.00,12.14,13.44,14.83,16.21,17.11,18.52,19.90,21.63,23.79,25.68,27.61,29.53,31.97,34.31],
			[12.93,14.29,15.83,17.46,19.08,20.14,21.79,23.39,25.40,27.94,30.06,32.21,34.39,37.11,39.71],
			[15.19,16.79,18.59,20.50,22.39,23.62,25.51,27.35,29.62,32.59,34.87,37.22,39.57,42.44,45.18],
			[17.66,19.52,21.60,23.79,25.95,27.32,29.43,31.48,33.94,37.34,39.55,41.81,44.22,46.93,49.49],
		],
		bands: [1.02, 1.06, 1.12, 1.19, 1.27, 1.39, 1.58, 1.95, 3.39],
		adder: [
			[0,0.05,0.15,0.25,0.35,0.42,0.50,0.55,0.60,0.64],
			[0,0.07,0.17,0.31,0.42,0.50,0.59,0.66,0.71,0.76],
			[0,0.08,0.21,0.36,0.50,0.60,0.70,0.79,0.86,0.91],
			[0,0.08,0.21,0.38,0.52,0.63,0.74,0.83,0.90,0.95],
			[0,0.09,0.27,0.46,0.62,0.75,0.88,0.99,1.09,1.15],
			[0,0.11,0.28,0.50,0.68,0.82,0.97,1.09,1.18,1.25],
			[0,0.13,0.35,0.60,0.83,1.01,1.18,1.33,1.45,1.53],
			[0,0.16,0.43,0.75,1.02,1.23,1.45,1.62,1.77,1.88],
			[0,0.19,0.52,0.92,1.25,1.51,1.78,2.00,2.17,2.31],
		],
		len: [[50,0.86],[63,0.89],[75,0.92],[90,0.95],[106,0.97],[125,1.00],[150,1.03],[180,1.06],[212,1.09],[250,1.11],[300,1.14],[355,1.17]],
	},
	'A': {
		dia: [3.0,3.2,3.4,3.6,3.8,4.0,4.2,4.4,4.6,4.8,5.0,5.2,5.4,5.6,5.8,6.0,6.4,7.0],
		rpm: RPM_ROWS,
		base: [
			[0.68,0.79,0.91,1.04,1.14,1.27,1.39,1.51,1.63,1.70,1.84,1.97,2.10,2.18,2.34,2.43,2.59,2.83],
			[0.76,0.91,1.05,1.18,1.32,1.46,1.61,1.74,1.88,1.97,2.12,2.27,2.43,2.52,2.71,2.81,2.99,3.28],
			[0.87,1.04,1.20,1.36,1.53,1.69,1.86,2.02,2.19,2.29,2.47,2.64,2.82,2.93,3.15,3.28,3.50,3.83],
			[0.91,1.08,1.25,1.42,1.58,1.76,1.93,2.11,2.28,2.38,2.57,2.75,2.94,3.05,3.28,3.41,3.64,3.98],
			[1.04,1.23,1.43,1.63,1.82,2.03,2.24,2.45,2.65,2.77,2.98,3.21,3.43,3.55,3.82,3.98,4.25,4.64],
			[1.09,1.31,1.53,1.74,1.96,2.17,2.40,2.62,2.84,2.96,3.20,3.43,3.68,3.81,4.10,4.27,4.55,4.98],
			[1.25,1.51,1.77,2.03,2.27,2.53,2.81,3.06,3.33,3.48,3.76,4.04,4.32,4.48,4.81,5.02,5.36,5.86],
			[1.43,1.74,2.04,2.34,2.66,2.96,3.28,3.60,3.90,4.07,4.41,4.73,5.07,5.26,5.65,5.89,6.28,6.87],
			[1.61,1.97,2.34,2.71,3.06,3.42,3.80,4.19,4.55,4.75,5.15,5.53,5.92,6.14,6.60,6.87,7.32,8.01],
			[2.03,2.57,3.11,3.64,4.15,4.66,5.21,5.74,6.25,6.52,7.05,7.56,8.08,8.38,9.00,9.28,9.90,10.83],
			[2.12,2.74,3.35,3.95,4.54,5.09,5.71,6.29,6.84,7.13,7.69,8.22,8.73,9.06,9.73,9.91,10.57,11.56],
		],
		bands: [1.02, 1.04, 1.07, 1.09, 1.13, 1.17, 1.23, 1.33, 1.51],
		adder: [
			[0,0.01,0.03,0.04,0.05,0.07,0.07,0.08,0.09,0.11],
			[0,0.01,0.03,0.04,0.05,0.07,0.08,0.09,0.12,0.13],
			[0,0.01,0.04,0.05,0.07,0.08,0.11,0.12,0.13,0.16],
			[0,0.01,0.04,0.05,0.07,0.09,0.11,0.12,0.15,0.16],
			[0,0.03,0.04,0.07,0.08,0.11,0.13,0.15,0.17,0.20],
			[0,0.03,0.05,0.07,0.09,0.12,0.15,0.16,0.19,0.21],
			[0,0.03,0.05,0.08,0.12,0.15,0.17,0.20,0.23,0.25],
			[0,0.04,0.07,0.11,0.15,0.17,0.21,0.25,0.28,0.32],
			[0,0.04,0.09,0.13,0.17,0.21,0.27,0.31,0.35,0.39],
			[0,0.07,0.15,0.21,0.28,0.35,0.43,0.50,0.56,0.64],
			[0,0.08,0.17,0.25,0.35,0.43,0.51,0.60,0.68,0.78],
		],
		len: [[26,0.75],[31,0.79],[35,0.82],[38,0.85],[42,0.87],[46,0.90],[51,0.92],[56,0.94],[60,0.97],[68,1.00],[75,1.03],[80,1.04],[85,1.06],[90,1.08],[95,1.09],[105,1.12],[112,1.13],[120,1.15],[128,1.17]],
	},
	'B': {
		dia: [4.6,4.8,5.0,5.2,5.4,5.6,5.8,6.0,6.2,6.4,6.6,6.8,7.0,7.4,8.0,8.6,9.4,11.0],
		rpm: RPM_ROWS.slice(0, 9), // 485..1750
		base: [
			[1.79,2.01,2.23,2.45,2.55,2.64,2.97,3.07,3.25,3.35,3.60,3.70,3.54,4.28,4.74,5.22,5.94,7.41],
			[2.04,2.30,2.55,2.81,2.92,3.02,3.41,3.53,3.73,3.85,4.14,4.26,4.08,4.93,5.46,6.02,6.85,8.56],
			[2.35,2.64,2.94,3.24,3.36,3.49,3.95,4.09,4.31,4.45,4.80,4.94,4.74,5.73,6.35,7.00,7.96,9.94],
			[2.43,2.75,3.04,3.36,3.49,3.62,4.10,4.24,4.50,4.64,4.98,5.13,4.94,5.97,6.60,7.29,8.29,10.35],
			[2.77,3.14,3.51,3.88,4.03,4.18,4.74,4.90,5.18,5.35,5.76,5.94,5.70,6.90,7.65,8.44,9.60,11.97],
			[2.96,3.35,3.74,4.15,4.31,4.47,5.07,5.25,5.55,5.73,6.17,6.36,6.12,7.40,8.20,9.05,10.28,12.83],
			[3.38,3.86,4.32,4.81,4.99,5.18,5.90,6.10,6.46,6.67,7.19,7.41,7.12,8.62,9.55,10.54,11.96,14.87],
			[3.88,4.43,4.98,5.55,5.76,5.98,6.83,7.06,7.49,7.74,8.34,8.59,8.27,10.00,11.07,12.20,13.81,17.09],
			[4.37,5.03,5.67,6.34,6.58,6.82,7.82,8.09,8.59,8.87,9.56,9.85,9.46,11.43,12.65,13.89,15.65,19.18],
		],
		bands: [1.02, 1.04, 1.07, 1.09, 1.13, 1.17, 1.23, 1.33, 1.51],
		adder: [
			[0,0.03,0.05,0.08,0.11,0.13,0.16,0.19,0.21,0.24],
			[0,0.03,0.07,0.09,0.13,0.16,0.19,0.23,0.25,0.28],
			[0,0.04,0.08,0.12,0.15,0.19,0.23,0.27,0.31,0.35],
			[0,0.04,0.08,0.12,0.16,0.20,0.24,0.28,0.32,0.36],
			[0,0.05,0.09,0.15,0.19,0.24,0.29,0.34,0.39,0.43],
			[0,0.05,0.11,0.16,0.21,0.27,0.32,0.38,0.43,0.47],
			[0,0.07,0.13,0.19,0.25,0.32,0.39,0.46,0.51,0.58],
			[0,0.08,0.16,0.24,0.32,0.40,0.47,0.55,0.63,0.71],
			[0,0.09,0.20,0.29,0.39,0.48,0.59,0.68,0.78,0.87],
		],
		len: [[35,0.77],[38,0.79],[42,0.81],[46,0.83],[51,0.86],[55,0.88],[60,0.90],[68,0.93],[75,0.95],[81,0.97],[85,0.99],[90,1.00],[97,1.02],[105,1.04],[112,1.05],[120,1.07],[128,1.09],[144,1.12],[158,1.14],[173,1.16],[180,1.17],[195,1.19],[210,1.21],[240,1.24],[270,1.27],[300,1.30]],
	},
	'AX': { // ใช้ประมาณค่าให้ SPA (หน้าตัดใกล้เคียงที่สุดที่ Bando USA ตีพิมพ์)
		dia: [2.2,2.4,2.6,2.8,3.0,3.2,3.4,3.6,3.8,4.0,4.2,4.4,4.6,4.8,5.0,5.2,5.4,5.6,5.8],
		rpm: RPM_ROWS,
		base: [
			[0.66,0.75,0.86,0.95,1.06,1.21,1.32,1.43,1.55,1.66,1.77,1.89,2.01,2.08,2.19,2.29,2.42,2.51,2.62],
			[0.72,0.84,0.96,1.08,1.21,1.38,1.51,1.63,1.77,1.89,2.02,2.16,2.29,2.37,2.51,2.63,2.76,2.86,3.01],
			[0.82,0.97,1.10,1.24,1.38,1.58,1.73,1.88,1.91,2.18,2.32,2.48,2.65,2.74,2.89,3.03,3.19,3.31,3.46],
			[0.84,0.99,1.12,1.28,1.42,1.63,1.80,1.95,2.11,2.26,2.41,2.57,2.75,2.84,3.00,3.15,3.31,3.43,3.60],
			[0.95,1.12,1.28,1.45,1.63,1.87,2.06,2.23,2.41,2.59,2.76,2.96,3.16,3.27,3.44,3.62,3.81,3.95,4.14],
			[1.01,1.18,1.35,1.54,1.73,1.99,2.19,2.38,2.57,2.76,2.95,3.16,3.38,3.49,3.69,3.87,4.07,4.22,4.43],
			[1.13,1.33,1.53,1.75,1.97,2.28,2.52,2.75,2.97,3.19,3.43,3.66,3.91,4.04,4.27,4.49,4.73,4.90,5.15],
			[1.26,1.51,1.74,1.99,2.26,2.63,2.90,3.17,3.43,3.69,3.96,4.23,4.53,4.68,4.96,5.21,5.47,5.68,5.96],
			[1.39,1.69,1.95,2.25,2.55,3.00,3.31,3.62,3.93,4.23,4.56,4.88,5.21,5.39,5.70,5.99,6.29,6.52,6.85],
			[1.63,2.06,2.43,2.86,3.28,3.93,4.38,4.82,5.24,5.65,6.08,6.50,6.95,7.19,7.58,7.95,8.31,8.62,8.94],
			[1.66,2.14,2.56,3.04,3.52,4.26,4.75,5.24,5.70,6.15,6.61,7.06,7.53,7.78,8.18,8.55,8.90,9.23,9.46],
		],
		bands: [1.02, 1.05, 1.08, 1.11, 1.15, 1.21, 1.28, 1.40, 1.65],
		adder: [
			[0,0.01,0.03,0.03,0.04,0.05,0.07,0.08,0.08,0.09],
			[0,0.01,0.03,0.04,0.05,0.07,0.08,0.09,0.11,0.11],
			[0,0.01,0.03,0.04,0.07,0.08,0.09,0.11,0.12,0.13],
			[0,0.01,0.03,0.05,0.07,0.08,0.09,0.11,0.13,0.15],
			[0,0.01,0.04,0.05,0.08,0.09,0.12,0.13,0.15,0.17],
			[0,0.03,0.04,0.07,0.08,0.11,0.12,0.15,0.16,0.19],
			[0,0.03,0.05,0.08,0.11,0.13,0.15,0.17,0.20,0.23],
			[0,0.03,0.07,0.09,0.12,0.16,0.19,0.21,0.25,0.28],
			[0,0.04,0.08,0.12,0.15,0.19,0.23,0.27,0.31,0.35],
			[0,0.07,0.12,0.19,0.25,0.31,0.38,0.44,0.50,0.56],
			[0,0.08,0.15,0.23,0.31,0.38,0.46,0.54,0.60,0.68],
		],
		len: [[26,0.75],[31,0.79],[35,0.82],[38,0.85],[42,0.87],[46,0.90],[51,0.92],[56,0.94],[60,0.97],[68,1.00],[75,1.03],[80,1.04],[85,1.06],[90,1.08],[95,1.09],[105,1.12],[112,1.13],[120,1.15],[128,1.17]],
	},
};

/* ซ่อมค่าที่ผิด monotonic จากการสแกน PDF (เช่น คอลัมน์ 7.0" ของตาราง B) */
(function sanitize_rating_tables() {
	Object.values(RATING).forEach(tbl => {
		tbl.base.forEach(row => {
			for (let i = 1; i < row.length; i++) {
				if (row[i] == null || row[i - 1] == null) continue;
				if (row[i] < row[i - 1]) {
					row[i] = (i + 1 < row.length && row[i + 1] != null && row[i + 1] > row[i - 1])
						? (row[i - 1] + row[i + 1]) / 2
						: row[i - 1];
				}
			}
		});
	});
})();

/* 1-D linear interpolation over sorted [x, y] pairs, clamped */
function interp_pairs(pairs, x) {
	if (x <= pairs[0][0]) return pairs[0][1];
	if (x >= pairs[pairs.length - 1][0]) return pairs[pairs.length - 1][1];
	for (let i = 1; i < pairs.length; i++) {
		if (x <= pairs[i][0]) {
			const [x0, y0] = pairs[i - 1], [x1, y1] = pairs[i];
			return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
		}
	}
	return pairs[pairs.length - 1][1];
}

/* interpolate over axis array with clamping; returns {t: index-fraction, clamped} */
function axis_pos(axis, x) {
	if (x <= axis[0]) return { t: 0, clamped: x < axis[0] };
	const last = axis.length - 1;
	if (x >= axis[last]) return { t: last, clamped: x > axis[last] };
	for (let i = 1; i <= last; i++) {
		if (x <= axis[i]) {
			return { t: i - 1 + (x - axis[i - 1]) / (axis[i] - axis[i - 1]), clamped: false };
		}
	}
	return { t: last, clamped: true };
}

function grid_value(rows, tr, tc) {
	const r0 = Math.floor(tr), r1 = Math.min(r0 + 1, rows.length - 1);
	const c0 = Math.floor(tc), c1 = Math.min(c0 + 1, rows[0].length - 1);
	const v = (r, c) => {
		let x = rows[r][c];
		if (x == null) { // null cells at high rpm/large dia: fall back down-left
			for (let cc = c; cc >= 0; cc--) if (rows[r][cc] != null) return rows[r][cc];
			for (let rr = r; rr >= 0; rr--) if (rows[rr][c] != null) return rows[rr][c];
		}
		return x;
	};
	const fr = tr - r0, fc = tc - c0;
	const top = v(r0, c0) + (v(r0, c1) - v(r0, c0)) * fc;
	const bot = v(r1, c0) + (v(r1, c1) - v(r1, c0)) * fc;
	return top + (bot - top) * fr;
}

/* Bando Procedure 6–7: per-belt corrected transmission HP */
function bando_belt_rating(rating_key, d_small_in, rpm_fast, ratio, belt_len_in, FA) {
	const tbl = RATING[rating_key];
	const dp = axis_pos(tbl.dia, d_small_in);
	const rp = axis_pos(tbl.rpm, rpm_fast);
	const base = grid_value(tbl.base, rp.t, dp.t);

	// speed-ratio adder: pick band column, interp on rpm only
	let col = 0;
	for (let i = 0; i < tbl.bands.length; i++) if (ratio >= tbl.bands[i]) col = i + 1;
	const adder = grid_value(tbl.adder, rp.t, col);

	const FL = interp_pairs(tbl.len, belt_len_in);
	return {
		base_hp: base,
		adder_hp: adder,
		FL: FL,
		corrected_hp: (base + adder) * FA * FL,
		clamped_dia: dp.clamped,
		clamped_rpm: rp.clamped,
	};
}

/* ========================================================= */
class BeltSFCalculator {
	constructor(wrapper) {
		this.$page = $(wrapper).find('.layout-main-section');
		this.state = {
			power_unit: 'kW',
			length_unit: 'mm',
			profile: 'SPA',
			driver_class: 'normal',
			driver_mode: 'standard',
			driven_mode: 'standard',
		};
		this.render();
		this.bind();
		this.fill_std_diameters();
	}

	/* ---------------- UI ---------------- */
	render() {
		this.$page.html(`
		<div class="belt-sf-app">
			<div class="bsf-intro">
				<b>Tension</b> – ${__('กรอกข้อมูลขั้นต่ำเพื่อคำนวณแรงตึงติดตั้งและจำนวนเส้นสายพานที่แนะนำ (ตาม Bando V-Belt Design Manual) ทุกช่องจำเป็นต้องกรอก')}
			</div>

			<div class="bsf-toolbar">
				<button class="btn bsf-btn-back">← ${__('Back to Menu')}</button>
				<button class="btn bsf-btn-calc">🖩 ${__('Calculate')}</button>
			</div>

			<div class="bsf-card">
				<div class="bsf-card-title">${__('Input - Driver')}</div>
				<div class="bsf-card-body">
					<div class="bsf-row">
						<span class="bsf-label">${__('Power')}</span>
						<input type="number" class="bsf-input" data-field="power" placeholder="${__('Motor Power')}" min="0" step="0.1">
						<span class="bsf-toggle" data-toggle="power_unit">
							<button data-val="HP">HP</button><button data-val="kW" class="active">kW</button>
						</span>
					</div>
					<div class="bsf-row">
						<span class="bsf-label">${__('Driver')}</span>
						<input type="number" class="bsf-input" data-field="rpm" placeholder="${__('Input RPM')}" min="0" step="1">
						<span class="bsf-unit">RPM</span>
					</div>
					<div class="bsf-stack">
						<span class="bsf-label wide">${__('ชนิดต้นกำลัง (Bando DriveR class)')}</span>
						<select class="bsf-input" data-field="driver_class">
							<option value="normal" selected>${__('มอเตอร์ AC ทั่วไป / DC Shunt / เครื่องยนต์หลายสูบ')}</option>
							<option value="high">${__('มอเตอร์แรงบิดสูง-สลิปสูง / DC Series / เครื่องยนต์สูบเดียว / คลัตช์')}</option>
						</select>
					</div>
				</div>
			</div>

			<div class="bsf-card">
				<div class="bsf-card-title">${__('Belt Info')}</div>
				<div class="bsf-card-body">
					<div class="bsf-row">
						<span class="bsf-label"># ${__('Belts')}</span>
						<input type="number" class="bsf-input" data-field="belts" min="1" step="1" value="1">
					</div>
					<div class="bsf-stack">
						<span class="bsf-label wide">${__('Belt Length')}</span>
						<div class="bsf-row">
							<input type="number" class="bsf-input" data-field="length" min="0" step="1">
							<span class="bsf-toggle" data-toggle="length_unit">
								<button data-val="inch">Inch</button><button data-val="mm" class="active">mm</button>
							</span>
						</div>
					</div>
					<div class="bsf-stack">
						<span class="bsf-label wide">${__('Service Factor')}</span>
						<div class="bsf-row">
							<input type="number" class="bsf-input" data-field="sf" value="1.40" min="1" step="0.05">
							<button class="btn bsf-btn-sf">⧉ ${__('Select SF')}</button>
						</div>
					</div>
					<div class="bsf-row">
						<span class="bsf-label">${__('Belt Profile')}</span>
						<select class="bsf-input" data-field="profile">
							${Object.keys(BELT_DATA).map(p =>
								`<option ${p === 'SPA' ? 'selected' : ''}>${p}</option>`).join('')}
						</select>
					</div>
				</div>
			</div>

			<div class="bsf-card">
				<div class="bsf-card-title">${__('Pulleys')}</div>
				<div class="bsf-card-body">
					${this.pulley_block('driver', __('Driver Pulley'))}
					${this.pulley_block('driven', __('Driven Pulley'))}
				</div>
			</div>

			<div class="bsf-card bsf-results" style="display:none">
				<div class="bsf-card-title">${__('Results')}</div>
				<div class="bsf-card-body bsf-result-body"></div>
			</div>
		</div>`);
	}

	pulley_block(key, title) {
		return `
		<div class="bsf-pulley" data-pulley="${key}">
			<div class="bsf-pulley-title">${title}:</div>
			<div class="bsf-pulley-mode">
				<button class="mode-std active" data-mode="standard">${__('Standard')}</button>
				<button class="mode-custom" data-mode="custom">${__('Custom')}</button>
			</div>
			<div class="bsf-stack std-block">
				<span class="bsf-label wide">${__('Diameter')} (mm)</span>
				<select class="bsf-input" data-field="${key}_dia_std"></select>
			</div>
			<div class="bsf-stack custom-block" style="display:none">
				<span class="bsf-label wide">${__('Diameter')} (mm)</span>
				<input type="number" class="bsf-input" data-field="${key}_dia_custom" min="0" step="1">
			</div>
		</div>`;
	}

	bind() {
		const me = this;
		this.$page.on('click', '.bsf-toggle button', function () {
			const $t = $(this).closest('.bsf-toggle');
			$t.find('button').removeClass('active');
			$(this).addClass('active');
			me.state[$t.data('toggle')] = $(this).data('val');
		});
		this.$page.on('click', '.bsf-pulley-mode button', function () {
			const $p = $(this).closest('.bsf-pulley');
			$p.find('.bsf-pulley-mode button').removeClass('active');
			$(this).addClass('active');
			const mode = $(this).data('mode');
			me.state[$p.data('pulley') + '_mode'] = mode;
			$p.find('.std-block').toggle(mode === 'standard');
			$p.find('.custom-block').toggle(mode === 'custom');
		});
		this.$page.on('change', '[data-field="profile"]', function () {
			me.state.profile = $(this).val();
			me.fill_std_diameters();
		});
		this.$page.on('change', '[data-field="driver_class"]', function () {
			me.state.driver_class = $(this).val();
		});
		this.$page.find('.bsf-btn-sf').on('click', () => this.open_sf_dialog());
		this.$page.find('.bsf-btn-calc').on('click', () => this.calculate());
		this.$page.find('.bsf-btn-back').on('click', () => frappe.set_route('app'));
	}

	fill_std_diameters() {
		const dias = BELT_DATA[this.state.profile].std_dia;
		['driver', 'driven'].forEach(k => {
			const $sel = this.$page.find(`[data-field="${k}_dia_std"]`);
			const cur = $sel.val();
			$sel.html(dias.map(d => `<option value="${d}">${d} mm</option>`).join(''));
			if (dias.includes(Number(cur))) $sel.val(cur);
		});
	}

	open_sf_dialog() {
		const cls = this.state.driver_class === 'high' ? 'sf_high' : 'sf_normal';
		const d = new frappe.ui.Dialog({ title: __('เลือก Service Factor — Bando Table 1'), size: 'large' });
		let html = `<p class="text-muted">${
			this.state.driver_class === 'high'
				? __('ต้นกำลัง: มอเตอร์แรงบิดสูง / DC Series / เครื่องยนต์สูบเดียว')
				: __('ต้นกำลัง: มอเตอร์ AC ทั่วไป / DC Shunt / เครื่องยนต์หลายสูบ')
		} (${__('เปลี่ยนได้ที่ช่อง "ชนิดต้นกำลัง"')})</p>`;
		html += `<table class="table table-bordered bsf-sf-table"><thead><tr>
			<th>${__('เครื่องจักรตาม (DriveN Machine)')}</th>
			${SF_HOURS.map(h => `<th class="text-center">${h}</th>`).join('')}</tr></thead><tbody>`;
		SF_TABLE.forEach(row => {
			html += `<tr><td>${row.label}</td>` +
				row[cls].map(v =>
					`<td><button class="btn btn-sm btn-default sf-pick" data-sf="${v}">${v.toFixed(2)}</button></td>`
				).join('') + '</tr>';
		});
		html += '</tbody></table>';
		d.$body.html(html);
		d.$body.on('click', '.sf-pick', (e) => {
			this.$page.find('[data-field="sf"]').val(Number($(e.currentTarget).data('sf')).toFixed(2));
			d.hide();
		});
		d.show();
	}

	/* ---------------- calculation ---------------- */
	read_inputs() {
		const g = (f) => parseFloat(this.$page.find(`[data-field="${f}"]`).val());
		const s = this.state;
		let power = g('power');
		if (s.power_unit === 'HP') power *= 0.7457;
		let length = g('length');
		if (s.length_unit === 'inch') length *= 25.4;
		const dia = (k) => s[k + '_mode'] === 'custom' ? g(k + '_dia_custom') : g(k + '_dia_std');
		return {
			power_kw: power, rpm: g('rpm'), belts: g('belts'),
			length_mm: length, sf: g('sf'),
			d_driver: dia('driver'), d_driven: dia('driven'),
		};
	}

	calculate() {
		const v = this.read_inputs();
		const missing = Object.entries(v).filter(([k, x]) => !x || x <= 0).map(([k]) => k);
		if (missing.length) {
			frappe.msgprint(__('กรุณากรอกข้อมูลให้ครบทุกช่อง (ต้องมากกว่า 0)'));
			return;
		}

		const belt = BELT_DATA[this.state.profile];
		const d = Math.min(v.d_driver, v.d_driven);
		const D = Math.max(v.d_driver, v.d_driven);

		const PB = v.power_kw * v.sf;                 // design power (kW)
		const speed = Math.PI * v.d_driver * v.rpm / 60000;

		// center distance (Bando): C = (b + sqrt(b² − 8(D−d)²))/8, b = 2L − π(D+d)
		const b = 2 * v.length_mm - Math.PI * (D + d);
		const disc = b * b - 8 * Math.pow(D - d, 2);
		if (b <= 0 || disc <= 0) {
			frappe.msgprint(__('ความยาวสายพานสั้นเกินไปสำหรับขนาดพูลเลย์ที่เลือก'));
			return;
		}
		const C = (b + Math.sqrt(disc)) / 8;

		const theta = 180 - 57.3 * (D - d) / C;
		const FA = bando_arc_factor((D - d) / C);

		// Bando tension (metric form of T1 = 41,250·HP/(FA·V))
		const Pe = 1000 * PB / speed;
		const T1 = 1.25 * 1000 * PB / (FA * speed);
		const T2 = T1 - Pe;
		const Ts = (T1 + T2) / 2 / v.belts + belt.mass * speed * speed;

		const span = Math.sqrt(C * C - Math.pow((D - d) / 2, 2));
		const defl_mm = span * 0.016;
		const defl_force = 0.064 * Ts;

		const ratio = D / d; // speed ratio ≥ 1
		const rpm_out = v.rpm * v.d_driver / v.d_driven;
		// faster sheave = small pulley
		const rpm_fast = (v.d_driver <= v.d_driven) ? v.rpm : rpm_out;

		// ---- Bando HP rating → recommended number of belts ----
		const rate = bando_belt_rating(
			belt.rating,
			d / 25.4,                 // small sheave dia (in)
			rpm_fast,
			ratio,
			v.length_mm / 25.4,       // belt length (in)
			FA
		);
		const design_hp = PB / 0.7457;
		const belts_needed = Math.max(1, Math.ceil(design_hp / rate.corrected_hp));

		const warns = [];
		if (d < belt.min_dia)
			warns.push(__('พูลเลย์เล็กกว่าค่าต่ำสุดของ Bando รุ่น {0} ({1} mm)', [this.state.profile, belt.min_dia]));
		if (speed > belt.max_speed)
			warns.push(__('ความเร็วสายพาน {0} m/s เกินขีดจำกัด {1} m/s', [speed.toFixed(1), belt.max_speed]));
		if (theta < 120)
			warns.push(__('มุมโอบพูลเลย์เล็ก ({0}°) ต่ำกว่า 120° ควรเพิ่มระยะห่างแกน', [theta.toFixed(0)]));
		if (rate.clamped_dia || rate.clamped_rpm)
			warns.push(__('เส้นผ่านศูนย์กลาง/RPM อยู่นอกช่วงตาราง HP rating ของ Bando — ใช้ค่าขอบตารางในการประมาณ'));
		if (v.belts < belts_needed)
			warns.push(__('จำนวนเส้นที่ใส่ ({0}) น้อยกว่าที่ Bando แนะนำ ({1} เส้น)', [v.belts, belts_needed]));
		if (this.state.profile === 'SPA')
			warns.push(__('SPA ประมาณจากตาราง AX ซึ่งเป็นหน้าตัดใกล้เคียงที่สุดในคู่มือ Bando USA — ตรวจสอบกับแคตตาล็อก Bando SP ก่อนใช้จริง'));

		this.show_results(v, {
			PB, speed, C, theta, FA, T1, T2, Ts, span, defl_mm, defl_force,
			ratio, rpm_out, rate, design_hp, belts_needed, warns,
		});
	}

	show_results(v, r) {
		const row = (l, val) => `<div class="bsf-res-row"><span>${l}</span><b>${val}</b></div>`;
		const kgf = (n) => (n / 9.80665).toFixed(1);
		let html = '';
		html += row(__('กำลังออกแบบ (P × SF)'), `${r.PB.toFixed(2)} kW (${r.design_hp.toFixed(2)} HP)`);
		html += row(__('อัตราทด'), `1 : ${r.ratio.toFixed(2)} (${r.rpm_out.toFixed(0)} RPM ขาออก)`);
		html += row(__('ความเร็วสายพาน'), `${r.speed.toFixed(2)} m/s`);
		html += row(__('ระยะห่างแกน (คำนวณ)'), `${r.C.toFixed(0)} mm`);
		html += row(__('มุมโอบพูลเลย์เล็ก (θ)'), `${r.theta.toFixed(1)}° — FA = ${r.FA.toFixed(3)}`);

		// HP rating block (Bando Procedure 6–7)
		html += row(__('Base HP + Speed Ratio Adder (ต่อเส้น)'),
			`${r.rate.base_hp.toFixed(2)} + ${r.rate.adder_hp.toFixed(2)} HP`);
		html += row(__('Coefficient of Belt Length (FL)'), r.rate.FL.toFixed(2));
		html += row(__('กำลังส่งได้ต่อเส้น (× FA × FL)'),
			`${r.rate.corrected_hp.toFixed(2)} HP (${(r.rate.corrected_hp * 0.7457).toFixed(2)} kW)`);

		html += `<div class="bsf-res-highlight">
			<div>${__('จำนวนเส้นที่แนะนำ (Bando)')}</div>
			<div class="big">${r.belts_needed} ${__('เส้น')}</div>
			<div>${__('Design HP ÷ (HP ต่อเส้น × FA × FL) = {0}',
				[(r.design_hp / r.rate.corrected_hp).toFixed(2)])}</div>
		</div>`;

		html += `<div class="bsf-res-highlight alt">
			<div>${__('แรงตึงติดตั้งสถิตต่อเส้น (ที่ {0} เส้น)', [v.belts])}</div>
			<div class="big">${r.Ts.toFixed(0)} N <small>(${kgf(r.Ts)} kgf)</small></div>
			<div>T1/T2 ${__('รวมทุกเส้น')}: ${r.T1.toFixed(0)} / ${r.T2.toFixed(0)} N</div>
		</div>`;
		html += row(__('ระยะกดทดสอบ (16 mm / 1 m ของช่วงสายพาน)'), `${r.defl_mm.toFixed(1)} mm`);
		html += row(__('แรงกดทดสอบต่อเส้น'), `${r.defl_force.toFixed(1)} N (${kgf(r.defl_force)} kgf)`);

		if (r.warns.length) {
			html += `<div class="bsf-warn">${r.warns.map(w => '⚠ ' + w).join('<br>')}</div>`;
		}
		html += `<div class="bsf-note">${__('สูตร, ตาราง SF, FA, FL และ HP Ratings อ้างอิง Bando V-Belt Design Manual (bandousa.com): A=Table 22/23, B=24/25, SPZ≈3V=7/8, SPB≈5V=9/10, SPA≈AX=32/33 — ค่าเป็นการประมาณด้วย interpolation ควรเทียบกับคู่มือก่อนใช้งานจริง')}</div>`;

		const $res = this.$page.find('.bsf-results');
		$res.find('.bsf-result-body').html(html);
		$res.show();
		$res[0].scrollIntoView({ behavior: 'smooth' });
	}
}
