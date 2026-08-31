# Accessibility Remediation Plan — Deferred from the 2026-08-25 Audit

Two findings from `AUDIT_REPORT.md` were deliberately **not** fixed during the same-day remediation pass, per the user's own answer to OQ-8 ("should this be its own project?" → yes):

- **H-10** — zero ARIA semantics (`aria-expanded`, `aria-selected`, `aria-haspopup`, `role="dialog"`, `aria-modal`) on any custom modal, accordion, dropdown, or popover, app-wide.
- **L-9 (remainder)** — inputs that already have a *visible* `<label>` nearby but no `for`/`id` association, so a screen reader can't connect the two. (L-9 itself is fixed for the narrower case of inputs with *no* label at all — see AUDIT_REPORT.md.)

Both share the same root cause (no accessibility pass has ever been done on this codebase), the same testing method (keyboard-only + screen reader walkthrough), and overlapping surface area (many modals also contain the unlabeled-but-visible-label inputs), so they're planned as one project, not two.

This document is the plan only — no code has been touched for either item.

---

## Current state (confirmed by re-reading the code, 2026-08-25)

**Shared JS, single-point-of-leverage components** — fixing these three covers a large fraction of the app in one change each, before touching any individual template:

| Component | File | What it needs |
|---|---|---|
| `createActionDropdown()` | `static/js/global.js:119-166` | Every action dropdown in the app (ticket table row actions, asset table actions, etc.) is built through this one factory function. Add `aria-haspopup="true"` (static, on the trigger button in each template) and toggle `aria-expanded` inside `toggle()`/`close()`. |
| Sidebar accordion (`openSection`/`closeAllSections`/`handleSectionToggle`) | `static/js/global.js:299-544` | One shared state machine drives every role's sidebar. Toggle `aria-expanded` on `.sidebar-section-toggle` buttons inside `openSection()`/`closeAllSections()`. |
| `searchableSelect()` Alpine component | `static/js/searchable_select.js` | Drives every vessel/dive-system/job-number/vendor picker. Add `role="combobox"`, `aria-expanded`, `aria-controls`, `aria-activedescendant` to the single component definition. |
| Date-range popover | `static/js/date_range_filter.js` | One shared component behind every date-range filter across list/report pages. Add `aria-expanded`/`aria-haspopup` to its trigger. |

**Per-template modal overlays** — these are *not* built through one shared constructor; each page hand-rolls its own show/hide + close function, so each needs its own `role="dialog" aria-modal="true"` + `aria-labelledby` + focus management. Confirmed list (16 templates, ~20 individual modals, via the `onclick="if(event.target===this)..."` convention every one of them already shares from the M-13 fix):

`knowledge_base/management.html`, `team_lead/escalated_tickets.html` (reassign + return), `admin/user_management.html` (password + impersonate), `agent/ticket_conversation.html` (resolve + attachment), `tickets/procurement_list.html`, `dashboards/system_settings.html`, `tickets/asset_detail.html`, `tickets/asset_list.html` (2 modals), `tickets/macro_management.html`, `organogram/system.html`, `documents_display/document_detail.html` (2 modals), `tickets/pending_asset_returns_list.html`, `tickets/my_assets.html`, `team_lead/manager_review_ticket.html`, `knowledge_base/article_content_edit.html` (2 modals), `tickets/mobilization_detail.html`, plus `partials/mobilization_demobilize_modal.html`, `partials/mobilization_demobilize_all_modal.html`, `partials/procurement_receive_modal.html`, and `partials/popovers/assign_popover.html` (this last one uses a different dismiss convention, `onclick="this.remove()"`, not the shared one — handle separately).

**Label/`for`-`id` gap** — known instances so far (a full grep pass is Phase 0 below, since this list is only what surfaced incidentally during the L-9 work, not an exhaustive search):
- `admin/user_management.html` — first name / last name / email / position / password fields all have a visible `<label>` immediately above with no `for`, and the input has no `id` to target.
- `tickets/asset_detail.html` — the "Vendor (optional)" field in the mobilize-asset modal.
- `requester/service_request_form.html` — the vessel/dive-system/job-number `searchableSelect` pickers (label present, but the underlying input is an Alpine `x-model` field, not a real named form field, so it has no `id` to associate with).

---

## Phased plan

### Phase 0 — Full inventory (don't skip this)
Before writing any fix, run two greps that weren't run to completion during the original audit or the L-9 remediation:
1. Every `<label` in `templates/` cross-referenced against whether the *next* `id`-bearing input actually matches its (absent) `for`. This needs a short script or careful manual pass — a plain grep can't do the cross-reference — since L-9's grep only found placeholder-driven inputs, not the full population of visually-labeled-but-unassociated ones.
2. Confirm the 16-template modal list above is complete by re-running `grep -r 'onclick="if(event.target===this)' templates/` at the start of the work (it may have grown since 2026-08-25).

Output: a definitive checklist, not estimates. Everything below assumes Phase 0 has already narrowed the actual scope.

### Phase 1 — Shared-component fixes (highest leverage, lowest risk)
Fix the four shared JS components listed above. Each is a single, isolated change:
1. `createActionDropdown()` — `aria-expanded` toggle in `toggle()`/`close()`; add `aria-haspopup="true"` to each trigger button template (small, mechanical, but each template needs the attribute added since the button markup itself lives per-page).
2. Sidebar accordion — `aria-expanded` toggle in `openSection()`/`closeAllSections()`; the trigger buttons already share one CSS class (`.sidebar-section-toggle`) across all role sidebars, so this only touches the JS, not every sidebar template.
3. `searchableSelect()` — `role="combobox"` + `aria-expanded`/`aria-controls`/`aria-activedescendant` inside the one component file. This also closes the `requester/service_request_form.html` label-association gap for these three fields at the same time, since it's the same input.
4. Date-range popover — `aria-expanded`/`aria-haspopup` on the trigger inside the one component file.

This phase alone gives every dropdown, accordion section, and autocomplete field in the app correct ARIA state with four file changes, not dozens.

### Phase 2 — Modal dialogs (bulk of the manual work)
For each of the ~20 modals identified in Phase 0:
1. Add `role="dialog"` and `aria-modal="true"` to the modal's inner content container (not the backdrop div — the backdrop is the dismiss target, the dialog role belongs on what it frames).
2. Add `aria-labelledby="<id>"` pointing at the modal's own heading (`<h3>`/`<h4>`), adding an `id` to that heading where missing.
3. Add basic focus management: move focus to the modal (or its first focusable element) on open, and return focus to the triggering button on close. Given every modal already calls a `closeXModal()`-style function (per the M-13 fix, which already hooks Escape into these), the open-side focus move is the only new behavior needed — store `document.activeElement` before opening and restore it in the existing close function.

Do this template-by-template; each is isolated and low-regression-risk since it only adds attributes and a small focus-management snippet, without touching existing show/hide logic.

### Phase 3 — Remaining label associations
For each item surfaced in Phase 0's label audit:
- Where the input is a real named form field: add a unique `id` and wire the label's `for` to it.
- Where the input is a JS-driven field with no real `id` semantics (Alpine `x-model` fields, etc.): add `aria-label` directly on the input instead, mirroring the approach already used for L-9's placeholder-only fixes — a `for`/`id` pair doesn't fit a widget that isn't a plain form control.

### Phase 4 — Verification
1. Keyboard-only walkthrough: Tab through every page touched in Phase 1–3 with the mouse untouched — every dropdown, accordion section, modal, and combobox must be operable (open, navigate, select, close/Escape) without a pointer.
2. Screen reader spot-check (NVDA or VoiceOver) on a representative sample: one modal, one dropdown, one accordion section, one combobox, one now-labeled form.
3. Automated pass (axe-core browser extension or Lighthouse accessibility audit) on the dashboard, ticket list, asset list, and mobilization detail pages to catch anything Phases 1–3 missed.

---

## Sequencing note

Phase 1 should land first and alone — it's the highest-value, lowest-risk change and immediately fixes every dropdown/accordion/combobox app-wide. Phases 2 and 3 can then proceed incrementally, template-by-template, without blocking on each other or on Phase 1's review. Phase 4 gates calling the project done, not any individual phase.

No timeline/effort estimate is given here since that depends on how much Phase 0's inventory turns up — this plan should be revisited once Phase 0 is complete to size the remaining work.
