# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`repair_management` is a custom Frappe/ERPNext app (bench app), installed into the bench at
`/home/chang/frappe-bench` on site **`local.147`**. Its nominal purpose is "Return Repair Item to
Supplier and Accept Repair Item" (see `repair_list`, `repair_item_list`, `repair_sympton` doctypes),
but in practice the app has grown into a grab-bag of unrelated features for one company (Eakthai):
a LINE messaging-platform integration, HVAC/belt engineering calculator pages, a stock "portfolio"
tracker, and payroll (Additional Salary / Salary Slip) payment automation. Treat it as several
loosely related subsystems sharing one app, not one cohesive product.

This is a real production app tied to a live site (`local.147`) — there is no separate dev/staging
site in this bench. Be careful with anything that touches the database directly.

## Commands

All commands run from the bench root (`/home/chang/frappe-bench`), not from this app directory,
unless noted.

```bash
# Run this app's Python tests against the real site
bench --site local.147 run-tests --app repair_management

# Run a single test file / class / method
bench --site local.147 run-tests --module repair_management.repair_management.doctype.repair_list.test_repair_list
bench --site local.147 run-tests --module repair_management.repair_management.doctype.repair_list.test_repair_list --test test_method_name

# Apply doctype/schema changes after editing a .json doctype definition or hooks.py
bench --site local.147 migrate

# Rebuild JS/CSS bundles after editing anything under public/ or a page's .js/.vue
bench build --app repair_management

# Console for ad-hoc inspection
bench --site local.147 console

# Execute a one-off function (used heavily for the LINE "patches" — see below)
bench --site local.147 execute repair_management.<dotted.path.to.function>
```

Linting/formatting is via `pre-commit` (ruff, ruff-format, eslint, prettier — configured in
`.pre-commit-config.yaml` and `pyproject.toml`). Run `pre-commit run --all-files` from this app
directory before committing if hooks aren't installed as a git hook.

Ruff config (`pyproject.toml`) targets py310, tabs for indentation, double quotes, line-length 110
(unenforced — `E501` is ignored). Unused-import and star-import lint rules are also disabled
(`F401`/`F403`/`F405`) — don't rely on ruff to catch dead imports here.

## Repo hygiene — read before touching files

This repo does **not** delete superseded code; it copies it sideways. You will constantly find:

- Sibling directories/files named `org/`, `org1/`, `org2/`, `h.old/`, `claude.1/`, `c.1/` next to the
  "live" file — these are manual backups of earlier versions, not alternate implementations in use.
- Files suffixed `.orig`, `.bak`, `.bak-<timestamp>`, `.old`, `.edit`, `.save`, `.save.1` sitting next
  to the real source file (e.g. `repair_management/api.py.orig`, `hooks.py.orig`,
  `line_send.py.edit`, `webhook/endpoint.py.bak-20260806-213618`).
- Doctype folders with extra non-standard controller files alongside the real one, e.g.
  `doctype/repair_list/old_repair.py`, `orig_repair_list.py`, `org_repair_list_dashboard.py`,
  `rel1.js`..`rel4.js` next to the actual `repair_list.js`/`repair_list.py`.

**When making changes, only edit the canonically-named file Frappe actually loads**
(`<doctype_name>.py`/`.json`/`.js` matching the folder name, or the module referenced by
`hooks.py`/an import). Never assume a `*_v2`, `org*`, or `*.old` file is dead weight to silently
delete — leave cleanup of these to the user unless explicitly asked. When grepping/exploring, filter
these out first (`grep -E '\.orig$|\.bak|\.old$|orig\.|\.edit$'` is already allow-listed in
`.claude/settings.local.json` for this reason).

`hooks.py` is a standard Frappe boilerplate file: most of it is commented-out template text from
`bench new-app`. Only a handful of active hooks matter — `app_include_js`, `web_include_js`,
`page_js`, `doctype_js`, `fixtures`, and a block of manually appended `doc_events`/`after_migrate`
wiring for the Additional Salary Payment feature (search for `# BEGIN ADDITIONAL SALARY PAYMENT` /
`# BEGIN SALARY SLIP PAYMENT`). New hooks should generally be added by extending those same
`doctype_js`/`doc_events` dicts rather than introducing a second ad-hoc registration pattern.

## Architecture

### Module layout (`repair_management/`)

- `repair_management/repair_management/` — the actual Frappe module (doctypes, pages, reports,
  workspace) registered in `modules.txt`. Core repair-flow doctypes live under
  `doctype/repair_list`, `doctype/repair_item_list`, `doctype/repair_sympton`. Also home to the bulk
  of the **LINE doctypes** (`doctype/line_*`) and several standalone Desk **pages** that are
  self-contained engineering calculators (`belt_length_calculator`, `belt_sf_calculator`,
  `hvac_calculator`, `hvac_selection`, `hvac_unit_converter`, `reorder_point_calcul`,
  `serial_rate_repair`) — each is independent client-side JS/HTML with no shared framework.
- `repair_management/portfolio/` — a second, unrelated "Portfolio" module (`modules.txt` lists it
  separately) for tracking stock trades: `portfolio_stock_name`, `portfolio_stock_event`.
- `repair_management/additional_salary_payment/` — payroll automation bolted on via hooks
  (`setup.py` creates custom fields on `Additional Salary`/`Payment Entry`/`Salary Slip` via
  `create_custom_fields`; `events.py` implements the doc-event handlers wired in `hooks.py`). There's
  a near-duplicate `org/` subfolder mirroring `api.py`/`events.py` — that's a backup, not a used
  package (see hygiene note above).
- `repair_management/integrations/line/` — the LINE Messaging API integration (the largest, most
  actively developed subsystem — see below).
- `repair_management/api.py` — grab-bag of `@frappe.whitelist()` endpoints unrelated to any single
  doctype (custom print button action, customer address lookup, customer purchase heatmap for the
  `customer_heatmap.js` doctype_js, and Stock Entry serial-number text sync). Despite the name this
  is not "the" API surface — the LINE integration and additional_salary_payment each have their own
  `api.py` files under their own package.
- `repair_management/line_send.py` — an older, standalone LINE "send as image" whitelisted method
  (PDF→JPG→LINE push) that predates and is independent of `integrations/line/`; it reads LINE
  credentials from `site_config.json` (`line_channel_access_token[_<user>]`,
  `line_user_id[_<user>]`) rather than from the `LINE Channel`/`LINE Account` doctypes the newer
  integration uses. Don't conflate the two credential sources when debugging LINE send issues.
- `repair_management/patches/` — see "Patches" below.
- `repair_management/www/`, `templates/` — website routes/Jinja templates (mostly legacy/unused
  scaffolding: `home.html`, `index.html`, `repair-list.html`, etc).

### LINE integration (`integrations/line/`)

This is an inbound-webhook + outbound-push messaging platform built on top of several doctypes
(`LINE Channel`, `LINE Webhook Request`, `LINE Webhook Event`, `LINE Recipient`, `LINE Action
Registry`, `LINE Business Flow`, `LINE Flow Session`, `LINE Media File`, `LINE Rich Menu *`, `LINE
Stock *`, `LINE Document *`). Request flow:

1. **`webhook/endpoint.py`** (`handle`, whitelisted+guest) — verifies the `X-Line-Signature` HMAC
   against the resolved `LINE Channel`'s secret, persists the raw request as a `LINE Webhook Request`,
   fans each event out into a `LINE Webhook Event` row (deduped by `event_key`), then
   `frappe.enqueue`s `webhook.router.process` per event on the `short` queue (async — the HTTP
   response returns before events are processed).
2. **`webhook/router.py`** (`process`, runs as a background job) — switches to the channel's
   `integration_user`, then routes by event type: `postback` events are parsed into
   `action=...` params and dispatched either to hardcoded handlers for the stock-query and
   document-media-upload flows (`flows/stock_query.py`, `flows/document_media_upload.py`) or, for
   any other action key, to **`actions/registry.py::dispatch`**, which looks up a `LINE Action
   Registry` row → `LINE Business Flow` → calls `flow.handler_path` dynamically via
   `frappe.get_attr`. This registry is the extension point for adding new LINE postback actions
   without touching the router.
3. **`flows/base.py`** manages `LINE Flow Session` state (multi-step conversational flows per
   channel+user, with expiry) — `active()` checks for a live session.
4. Outbound sending goes through **`client.py`** (`push_messages` etc., the low-level Messaging API
   HTTP client) and **`forwarding.py`** (auto-forwards "delivery confirmation" style events to
   configured recipients via `LINE Forward Route`/`LINE Forward Log`).

**Known inconsistency:** `forwarding.py` and `migration.py` reference doctypes — `LINE Settings`
(single), `LINE Account`, `LINE Delivery Confirmation`, `LINE Forward Route`, `LINE Forward Log` —
that do **not exist** anywhere in this bench (no matching doctype JSON in this app or any other
installed app). These modules appear to be leftover from an earlier design that was migrated to the
current `LINE Channel`-based model without being fully cleaned up. Don't assume code under
`integrations/line/` is live just because it's imported somewhere — check that the doctypes it
references actually exist (`bench --site local.147 console` → `frappe.db.exists("DocType", "...")`)
before building on top of it.

The `rich_menu/` subfolder has standalone bash scripts (`create_line_rich_menu.sh`,
`update_line_rich_menu.sh`, `link_rich_user.sh`) that call the LINE Rich Menu HTTP API directly with
`curl`, driven by `richmenu.json`/`richmenu_user.json` and a `LINE_CHANNEL_ACCESS_TOKEN` env var —
these are operational tooling, not imported by the Frappe app.

### Patches (`repair_management/patches/`)

Two different patch mechanisms coexist:

- **Framework patches** (`patches.txt`, `pre_model_sync`/`post_model_sync`) — the standard Frappe
  migration mechanism, run automatically by `bench migrate`. Currently empty/unused.
- **Ad-hoc "LINE" patches** — one-off directories named `line_<feature>_v<n>/` (e.g.
  `line_workspace_v1_1`, `line_clean_rebuild_v1_2`, `line_media_item_burnin_v1_7`,
  `line_document_selection_flex_v1_6`) each containing an `apply.py` (and often `check.py`/
  `revert.py`) with a single top-level function, **not** registered in `patches.txt` and **not**
  run by `bench migrate`. These are invoked manually, one at a time, via:
  ```bash
  bench --site local.147 execute repair_management.patches.<patch_dir>.apply.<function_name>
  bench --site local.147 execute repair_management.patches.<patch_dir>.check.<function_name>
  bench --site local.147 execute repair_management.patches.<patch_dir>.revert.<function_name>
  ```
  (see `patches/google_redirect_base_url/howto.txt` for the pattern). The version suffix in the
  directory name is meaningful — newer `_v1_1`/`_v1_2`/etc. directories are follow-up fixes to an
  earlier patch, applied in sequence, not alternatives to pick from. When adding a new one-off data
  migration for the LINE feature, follow this same `apply.py`/`check.py`/`revert.py` convention
  rather than adding to `patches.txt`.

### Doctype conventions

Standard Frappe doctype layout applies (`doctype/<name>/<name>.json` + `.py` controller + `.js` form
script). Thai-language UI strings and error messages appear throughout controllers (e.g.
`repair_list.py`) — preserve/match this when editing user-facing text in that area. Test files exist
for only a few doctypes (`repair_list`, `repair_sympton`, `portfolio_stock_name`,
`portfolio_stock_event`); most doctypes have no tests.
