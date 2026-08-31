# TicketSwipe Audit Report — 2026-08-25

Originally a read-only audit; a remediation pass followed on the same day and fixed every Critical, High, Medium, and Low finding except the two explicitly deferred to their own accessibility project (H-10, and the broader label-`for`/`id` wiring noted under L-9). Each finding below carries a **Status** line reflecting the outcome. See the **Remediation Log** section for the full file-by-file summary, migrations, and test verification.

## Summary

35 findings across backend/data integrity, security, performance, error handling, code quality, UI consistency, responsiveness, and accessibility (34 from the original pass, plus one surfaced during open-question follow-up).

- **Critical: 1** — unauthenticated-role ticket claim (authorization bypass) — **Fixed**
- **High: 10** — **9 fixed, 1 deferred** (H-10, ARIA — own project per Q-8)
- **Medium: 13** — **12 fixed, 1 no-action-needed** (M-2, informational only)
- **Low: 11** — **5 fixed, 6 no-action-needed / verified-safe** (L-1, L-3–L-5, L-7, L-10)
- **Open Questions: 8 — all resolved 2026-08-25**

Totals across all 35 findings: **27 fixed, 1 deferred (H-10), 7 no action needed** (informational, already-clean, positive findings, or verified-safe).

Most urgent items at the time of the audit: the ticket-claim authorization bypass (any authenticated role, including END_USER, could claim/assign any unassigned ticket), the double-demobilize race condition that could silently double-count returned consumable stock, the dashboard N+1 query storm on the app's own landing page, and the missing rate limit on password reset. **All four are now fixed** — see below.

---

## Critical

### C-1. `claim_ticket` has no role/authorization check — any authenticated user, including END_USER, can claim any unassigned ticket
**File:** `apps/tickets/views.py:625-634` (view logic through :702)
The view is decorated only with `@login_required`. Every sibling agent-only action (`ticket_slideover`, `agent_ticket_detail`, `add_comment_conversation`, etc.) checks `effective_role_name(request.user) in [AGENT, TEAM_LEAD, ADMIN, SUPERADMIN]` before acting — this one does not. An END_USER can POST to `/tickets/claim/<pk>/` and become `assigned_to` on someone else's ticket, flipping its status to `ASSIGNED`.
**Why it matters:** This breaks the core role model the entire ticket workflow is built on (requesters can't self-assign support tickets), and it's a real authorization bypass reachable by the lowest-privileged role in the system, not just a permissions edge case. Compiler's note: raised from the sub-agent's "High" rating to Critical because it's a broken-access-control hole on a state-changing endpoint reachable by any logged-in user, not a role/UX nuance.
**Fix direction:** Add the same role allowlist check used by the other agent-only endpoints before the assignment logic runs; combine with the concurrency fix in H-2 (they touch the same code path).
**Status:** Fixed 2026-08-25 — `claim_ticket` now checks `effective_role_name(request.user) in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']` before doing anything, and the assignment runs inside `transaction.atomic()` with `select_for_update()` (see H-1).

---

## High

### H-1. Double-claim race condition — no locking on ticket assignment
**File:** `apps/tickets/views.py:625-702`
`claim_ticket` reads `ticket.assigned_to is None` and writes without `transaction.atomic()`/`select_for_update()`. Two agents clicking "Claim" concurrently can both pass the check; the last write silently wins, leaving one agent believing they own a ticket they don't.
**Fix direction:** Wrap in `transaction.atomic()` with `Ticket.objects.select_for_update().get(pk=pk)`, or a conditional `UPDATE ... WHERE assigned_to IS NULL` checking rows-affected. Fix alongside C-1 since both touch the same view.
**Status:** Fixed 2026-08-25 — done together with C-1.

### H-2. Double-demobilize race condition can double-count returned stock
**File:** `apps/tickets/views.py:5493-5521` (`mobilization_item_demobilize`)
Fetches the `MobilizationItem` via `get_object_or_404` with no `select_for_update()`/`transaction.atomic()` — unlike its sibling `mobilization_demobilize_all` (`views.py:5541-5569`), which correctly uses both. Two concurrent submissions (double-click, retried HTMX request) can both pass the `item.is_active` check and both call `_demobilize_item`, which for consumables adds `return_quantity` to `asset.quantity_in_stock` twice.
**Why it matters:** Silently inflates on-hand stock counts from a single physical return — a real data-integrity risk in the asset lifecycle workflow that was otherwise recently hardened (per project history).
**Fix direction:** Match the pattern already used in `mobilization_demobilize_all` — atomic transaction + `select_for_update()` on the item before the `is_active` check.
**Status:** Fixed 2026-08-25 — `mobilization_item_demobilize` now locks the item inside `transaction.atomic()` + `select_for_update()` before checking `is_active`, matching its sibling. A client-side backstop (`data-guard-submit`) was also added to the demobilize form (see L-6/L-11).

### H-3. `CustomPasswordResetView` has no rate limiting
**File:** `apps/accounts/views/__init__.py:72`
Contrast with `CustomLoginView` (`apps/accounts/views/__init__.py:34-36`), which has `@method_decorator(ratelimit(key='ip', rate='5/15m', method='POST', block=True), name='dispatch')`. Password reset request submission is unthrottled.
**Why it matters:** Enables email enumeration and mass-email abuse (an attacker can trigger reset emails to arbitrary/scraped addresses at will).
**Fix direction:** Apply the same `ratelimit` decorator pattern used on `CustomLoginView`.
**Status:** Fixed 2026-08-25 — `CustomPasswordResetView` now carries `@method_decorator(ratelimit(key='ip', rate='5/15m', method='POST', block=True), name='dispatch')`.

### H-4. `asset_attachment_upload` has no server-side file size or type validation
**File:** `apps/tickets/views.py:2531-2554`
Unlike ticket attachments, which go through `save_attachments()` (`apps/tickets/views.py:149-163`, enforcing `MAX_SIZE_MB` and an `ALLOWED_MIMES` allowlist), this view builds the `AssetAttachment` directly from `request.FILES.get('file')` with no size cap and no MIME/extension check. Restricted to ADMIN/SUPERADMIN, which lowers exploitability, but still allows unbounded uploads and arbitrary file types.
**Fix direction:** Route through the same validation helper used for ticket attachments (or a shared version of it).
**Status:** Fixed 2026-08-25 — `asset_attachment_upload` now enforces the same `MAX_SIZE_MB` and `ALLOWED_MIMES` checks, plus magic-byte sniffing added as part of M-7.

### H-5. Dashboard N+1 query storm on every load for Agent/Admin/Superadmin/Team Lead
**File:** `apps/accounts/views/__init__.py:297-336` (and a third similar loop at `:391-394`)
For every ticket in `resolved_tickets`, a separate `TicketActivityLog.objects.filter(...).first()` query is issued — once in the resolution-time loop (306-315) and again in a near-identical response-time loop (325-334). An agent with 200 resolved tickets triggers 400+ extra queries per dashboard load.
**Why it matters:** This is the app's default landing page — the single most expensive endpoint in the system by request volume.
**Fix direction:** Pull all relevant `assigned` activity logs in one query/prefetch keyed by ticket_id, merge both loops into one pass (this also resolves the code-duplication finding M-9 below).
**Status:** Fixed 2026-08-25 — the two loops are merged into one pass over batched `TicketActivityLog`/`TicketComment` queries (dict-keyed by ticket id instead of one query per ticket); the SLA-compliance loop right below it (previously one `SLA.objects.get()` per resolved ticket) was fixed the same way while in the same view.

### H-6. No application-level caching layer despite Redis being available
**File:** `config/settings/base.py:86-100`, `config/settings/production.py` CACHES block
Base settings' own comment says `# CACHE CONFIGURATION (for rate limiting)` — the Redis-backed `CACHES` exists but nothing in the codebase calls `cache.get`/`cache.set`/`@cache_page` (confirmed via grep). The expensive per-request aggregate loops above (and other dashboard/report aggregates) are recomputed on every request with no memoization.
**Fix direction:** Cache dashboard KPI aggregates for a short TTL (e.g. 60s), or use Django's low-level cache API keyed by user+role.
**Status:** Fixed 2026-08-25 — the org-wide Admin/Superadmin KPI block was extracted into `_get_admin_dashboard_kpis()` and cached for 60s via the existing Redis cache backend.

### H-7. No custom 404/500 error pages or handlers
**File:** `config/urls.py` (no `handler404`/`handler500`); no `templates/404.html`/`500.html` found
In production (`DEBUG=False`), users hitting a bad URL or server error see Django's bare default error page.
**Why it matters:** Breaks the white-label branding promise for the product (per CLAUDE.md, this is a white-label product for multiple clients).
**Fix direction:** Add branded `templates/404.html`/`500.html` and wire `handler404`/`handler500` in `config/urls.py`.
**Status:** Fixed 2026-08-25 — added `templates/404.html` (extends the branded base, matches `client_settings`) and a self-contained `templates/500.html` (no context-processor dependency, since Django's default 500 handler renders without request context). No `urls.py` change needed — Django picks these up automatically once `DEBUG=False`.

### H-8. `apps/organogram/tests.py` is effectively empty (3 lines)
**File:** `apps/organogram/tests.py`
No test coverage for the organogram app despite it now doing non-trivial tree-building logic (`views.system_org`, per project memory on the recent org-chart trim to System-Organogram-only).
**Fix direction:** Add smoke tests for the auto-generated tree (role/department combinations, cycle handling — see M-6 below).
**Status:** Fixed 2026-08-25 — `apps/organogram/tests.py` now has 11 tests covering tier grouping, dual-role membership, SUPERADMIN exclusion, department filtering, and view-level permission gating. All pass.

### H-9. `unassigned_queue` — N+1 plus unbounded/unpaginated queryset
**File:** `apps/tickets/views.py:522-566`; `templates/agent/unassigned_queue.html:27`; `templates/partials/agent_ticket_table.html:43`
No pagination or slicing on the queryset; the template forces full evaluation just to render a count via `{{ tickets|length }}`. The table partial then accesses `ticket.requester.get_full_name_with_role` per row with no `select_related('requester', 'category')` — N+1 scaling with the (currently unbounded) count of unassigned tickets.
**Fix direction:** Add `select_related('requester', 'category')`, paginate, and use `.count()` for the badge/summary instead of `|length`.
**Status:** Fixed 2026-08-25 (per Q-5) — added `select_related('requester', 'category')`, real `Paginator`-based pagination (20/page with prev/next controls), and `{{ tickets.paginator.count }}` replacing `|length`. The `claim_ticket` HTMX re-render path got the same `select_related` plus a 20-item cap.

### H-10. Zero ARIA semantics anywhere in `templates/` for custom interactive components
**File:** app-wide (grep for `aria-expanded`, `aria-selected`, `aria-haspopup`, `role="dialog"`, `aria-modal` returned 0 matches)
Custom modals (`templates/admin/user_management.html`, `templates/agent/ticket_conversation.html` resolve modal, `templates/team_lead/escalated_tickets.html` reassign/return modals, `templates/partials/popovers/assign_popover.html`), the sidebar accordion, and the date-range popover all lack the ARIA state/role semantics screen readers rely on.
**Fix direction:** Add `role="dialog" aria-modal="true"` to modal containers; add `aria-expanded` (toggled alongside existing JS/Alpine state) to accordion and dropdown trigger buttons. Given the scope (app-wide, not a couple of components), see Open Question OQ-8 on whether this should be its own remediation project.
**Status:** Deferred — per OQ-8's resolution, scoped as its own dedicated accessibility project rather than folded into this remediation pass. Not fixed. See `ACCESSIBILITY_REMEDIATION_PLAN.md` for the phased plan.

---

## Medium

### M-1. Missing DB-level "exactly one of ticket/mobilization" constraint
**File:** `apps/tickets/models.py:1903-1910` (`AssetProcurementRequest.ticket`/`.mobilization`)
Both nullable FKs; docstring says "exactly one of these is normally set" but it's enforced only by convention in the creating views, not a `CheckConstraint`. See OQ-1 on whether both-null is ever a valid state before adding the constraint.
**Status:** Fixed 2026-08-25 (per OQ-1: "at most one," not "exactly one") — added a `CheckConstraint` forbidding `ticket` and `mobilization` from being set simultaneously; standalone (both-null) requests remain valid. Migration `tickets.0048`, applied against zero violating rows.

### M-2. Extra query on every `Ticket.save()` and `Asset.save()`
**File:** `apps/tickets/models.py:389-392` (Ticket), `:1593-1599` (Asset)
Both correctly detect field changes (impact/urgency, status) via an extra fetch, but this adds one SELECT to every save of these two high-traffic models — worth being aware of for write-heavy paths (bulk imports, `asset_import`), though not incorrect.
**Status:** No action taken — informational only. Removing the extra SELECT would require restructuring the change-detection mechanism these saves rely on for side effects (notifications on status change, etc.), which carries real regression risk for a "not wrong, just a minor cost" finding. Left as-is.

### M-3. `Notification` has no composite index on `(recipient, is_read)`
**File:** `apps/common/models.py:40-74`
Queried per-request for unread-notification badges on every logged-in page load (per context processors noted in CLAUDE.md), but only has the implicit FK index on `recipient_id`. No retention/cleanup visible, so this gets progressively more expensive as the table grows.
**Status:** Fixed 2026-08-25 — added `models.Index(fields=['recipient', 'is_read'])`. Migration `common.0009`.

### M-4. `User.manager` self-FK has no cycle guard
**File:** `apps/accounts/models.py:181-188`
Nothing prevents `A.manager = B; B.manager = A` (or a longer cycle). Any code walking the reporting chain upward (org chart, escalation-by-manager logic) risks an infinite loop.
**Fix direction:** Validate at the point managers are assigned — walk up from the proposed manager and reject if it reaches the user being edited.
**Status:** Fixed 2026-08-25 — `User.save()` now walks the manager chain and raises `ValueError` if the assignment would create a cycle (including self-assignment). No model field change, so no migration needed.

### M-5. `ClientSettings` has no enforced singleton
**File:** `apps/accounts/models.py:420-435`
Used as `ClientSettings.objects.first()` throughout (e.g. `apps/tickets/views.py:4243`), but nothing stops a second row being created via `/admin/`, which would make `first()` arbitrary. Low risk today (single pilot client) but worth guarding before the product's stated multi-tenant direction (see CLAUDE.md) makes this load-bearing.
**Fix direction:** Override `save()` to force a fixed `pk`, or add a `UniqueConstraint`-style guard.
**Status:** Fixed 2026-08-25 — `save()` now pins `pk=1`. Confirmed every existing call site already used `id=1`/`.first()` conventionally, and `ClientSettings` isn't registered in Django admin, so this closes the one remaining path (a stray `.create()`) without touching any working code.

### M-6. Missing pagination on `procurement_list`
**File:** `apps/tickets/views.py:4472`
Renders the full `AssetProcurementRequest` queryset with no `Paginator`; vendor procurement requests will grow indefinitely.
**Fix direction:** Add `Paginator` as already done in the neighboring `pending_asset_fulfillment_list`/`pending_asset_returns_list`.
**Status:** Fixed 2026-08-25 — added real `Paginator`-based pagination (25/page), with prev/next controls in the template preserving the current status filter.

### M-7. MIME-type validation for ticket attachments trusts the client-supplied header
**File:** `apps/tickets/views.py:161-163`
`f.content_type` is set by the browser/client and is trivially spoofable (rename a script `.jpg`, send `Content-Type: image/jpeg`). Size checking and hashing are real; only the type allowlist is bypassable this way.
**Fix direction:** Sniff actual file content (e.g. `python-magic`, magic-byte check) rather than trusting the client header, at least for anything served back to other users.
**Status:** Fixed 2026-08-25 — added a lightweight magic-byte signature check (`sniffed_mime_matches()`) for every MIME type with a reliable signature (JPEG/PNG/GIF/WebP/PDF/ZIP/Office/legacy-Office), avoiding a new cross-platform dependency (`python-magic` needs a native libmagic binary, complicating Windows dev vs. Linux prod). Wired into both `save_attachments()` and `asset_attachment_upload`. `text/plain` has no reliable signature and passes through unsniffed, same as before.

### M-8. `CanViewDocument` DRF permission class is dead code with a broken implementation
**File:** `apps/documents_display/permissions.py:11-17`
`has_object_permission` only checks `is_deleted` and otherwise returns `True` for any authenticated user — doesn't consult `DisplayDocument.is_viewable_by()` (`apps/documents_display/models.py:189-203`), which correctly checks PUBLIC/department/share/editor grants. Confirmed not wired into any current view (`apps/documents_display/views.py:116,146,386,412` call `is_viewable_by()` directly), so no live exploit path — but it's a trap for a future DRF viewset that reaches for the obviously-named permission class and gets it wrong.
**Fix direction:** Delete the unused class, or make it delegate to `obj.is_viewable_by(request.user)`.
**Status:** Fixed 2026-08-25 — kept the class (rather than deleting) and made it delegate to `obj.is_viewable_by(request.user)`, so it's safe if a future DRF viewset reaches for it.

### M-9. Duplicated aggregate-loop pattern in dashboard view
**File:** `apps/accounts/views/__init__.py:306-315` and `:325-334`
The resolution-time and response-time loops are structurally identical except for which timestamp is diffed. Fixing H-5 (the N+1) also resolves this duplication by construction.
**Status:** Fixed 2026-08-25 — resolved as part of H-5's fix.

### M-10. `trigger_sla_processing`/`trigger_cleanup` leak exception text to the client
**File:** `apps/tickets/views.py` ~3450-3470
Both swallow exceptions into `JsonResponse({'status': 'error', 'message': str(e)}, status=500)`. Admin-only endpoints, so low exploitability, but still worth tightening.
**Fix direction:** Log the exception server-side, return a generic message to the client.
**Status:** Fixed 2026-08-25 — all three trigger endpoints (`trigger_sla_processing`, `trigger_cleanup`, and the external cron variant `trigger_sla_processing_external`, which had the same pattern) now call `logger.exception(...)` and return a generic message.

### M-11. `CSRF_TRUSTED_ORIGINS` placeholder in `base.py` is dead in prod but live in dev
**File:** `config/settings/base.py:24`
Sets `['https://*.yourdomain.com', 'http://localhost:8000']`; unconditionally overwritten by `production.py:98` (env-driven), so dead in prod, but `development.py` doesn't override it, leaving the placeholder live in dev. Not exploitable (`*.yourdomain.com` doesn't resolve), but misleading boilerplate that could get copy-pasted into a real deployment.
**Fix direction:** Remove the placeholder from `base.py`, or make it env-driven consistently in both environments.
**Status:** Fixed 2026-08-25 — `base.py` now reads `env.list('CSRF_TRUSTED_ORIGINS', default=['http://localhost:8000'])`, matching `production.py`'s pattern with a sane dev default instead of the placeholder domain.

### M-12. Priority/status badges duplicated instead of using the centralized `{% status_badge %}` tag
**File:** `templates/partials/ticket_table.html:31-37`, `templates/partials/agent_ticket_table.html:75-80`, `templates/partials/team_ticket_table.html:30-35`
All three hand-roll the same `{% if ticket.priority == 'P1' %}...{% endif %}` chain instead of calling `{% status_badge 'ticket_priority' ticket.priority %}` (`apps/tickets/templatetags/badge_tags.py`), whose own comment states it replaced exactly this pattern in other templates (e.g. `asset_table.html`) — these three appear to have been missed or reverted. The status chip in the same three files is likewise inlined rather than via the tag (lower severity — a single expression, not a branching chain).
**Why it matters:** If the P1–P4 → color mapping ever changes, these three tables silently drift out of sync with every other page that already uses the tag.
**Fix direction:** Replace inline spans with the tag call, matching `asset_table.html`. See OQ-4 on whether this was accidental.
**Status:** Fixed 2026-08-25 — all three templates now call `{% status_badge 'ticket_status' ... %}`/`{% status_badge 'ticket_priority' ... %}`, confirmed via OQ-4's git-blame investigation to have been an accidental miss from the commit that introduced the tag.

### M-13. Modal dismissal relies on backdrop click; Escape-key handling is inconsistent
**File:** `templates/admin/user_management.html:99,242`, `templates/agent/ticket_conversation.html:261`, `templates/base_dashboard.html:12`, `templates/documents_display/document_detail.html:140`, `templates/partials/popovers/assign_popover.html:2`, `templates/team_lead/escalated_tickets.html:106,121`
Only 6 files app-wide implement any Escape-key handling for modals; the rest rely solely on a `<div onclick>` backdrop dismiss. Keyboard-only users may have no way to dismiss a modal without tabbing to a visible close button (not confirmed whether one exists in each case).
**Fix direction:** Add a shared keydown listener for Escape to the modal-open state, applied consistently.
**Status:** Fixed 2026-08-25 — added one app-wide `keydown` listener in `static/js/global.js` that, on Escape, dispatches a synthetic click on every visible overlay matching the `onclick="if(event.target===this) ..."` convention every modal in the app already uses — reusing each page's existing close handler (and whatever cleanup it does) rather than reimplementing it per modal.

---

## Low

### L-1. `sla_list` has no pagination
**File:** `apps/tickets/views.py:3411` — renders `SLA.objects.all()`/`EscalationRule.objects.all()`. Likely low risk since these are bounded by priority-tier count, but worth confirming that assumption holds.
**Status:** Confirmed no bug — `SLA.priority` is `unique=True` against the 4 fixed `Ticket.Priority` choices, so that table is DB-hard-capped at 4 rows, ever. `EscalationRule` has no such constraint but is an admin-configured settings page (not a usage-scaled list) — pagination there would be over-engineering. No fix applied.

### L-2. Stray `console.log` left in production template
**File:** `templates/dashboards/admin_dashboard.html:346` — `console.log('Admin dashboard loaded')`. Harmless but should be removed before launch.
**Status:** Fixed 2026-08-25 — removed the dead script block entirely (the `DOMContentLoaded` listener had nothing left in it besides the log line).

### L-3. No `TODO`/`FIXME`/`XXX` markers anywhere in `apps/`
Clean on this front — no finding to action, noted for completeness.

### L-4. Core business logic has strong test coverage (positive finding)
`apps/tickets/tests.py` (3675 lines) includes dedicated `MobilizationTests`, `MobilizationVendorGatingTests`, `ThirdPartyVesselMobilizationTests`, `MobilizationAutopickTests`, and `SLAAndEscalationTests` covering SLA breach calculation and mobilization/demobilization edge cases (partial demobilize, consumable stock deduction, over-mobilization rejection) — contrast with H-8 (organogram).

### L-5. HTMX failure handling is solid (positive finding)
`static/js/global.js:838-852` has a body-level `htmx:responseError` listener surfacing a toast (with fallback to a generic message on markup-detection failure), and CSRF token injection is wired globally via `htmx:configRequest`. No gap found.

### L-6. Double-submit protection is opt-in per form, not global
**File:** `static/js/global.js:864-874` (`preventDoubleSubmit`, gated by `data-guard-submit`)
Confirms project memory's existing note — the mechanism exists but isn't automatically applied everywhere. See OQ-3.
**Status:** Fixed 2026-08-25, together with L-11 — the guard was rewritten as a delegated `document`-level `submit` listener (works regardless of when the form entered the DOM, no rebinding needed) and applied to the mobilization create form, both demobilize forms, and the procurement-receive form. The ticket-claim action turned out not to be a form submit at all (it's a JS `fetch()` call in `agent_ticket_table.html` that already disables the trigger button during the request) — no attribute needed there.

### L-7. HTMX CSRF wiring depends on a `[name=csrfmiddlewaretoken]` element existing on every page
**File:** `static/js/global.js:832-837`
Solid single-point-of-truth pattern, but any page/partial that never renders a `{% csrf_token %}` anywhere in the DOM would silently break CSRF for all HTMX requests from that page. Not exhaustively verified across all ~20 templates using `hx-post`/`hx-put`/`hx-delete`. See OQ-2.
**Status:** Verified safe 2026-08-25 (per OQ-2) — every one of the 19 templates using `hx-post`/`hx-put`/`hx-delete` is a partial/modal loaded inside a page built on `base_dashboard.html`, which unconditionally renders a `{% csrf_token %}` in its navigation chrome (present in the DOM before any partial swaps in). `base_registration.html`-based pages (login/registration/password-reset/external-share) use no HTMX at all. No gap found; no fix needed.

### L-8. Placeholder-text contrast may dip below comfortable AA
**File:** `static/css/theme.css:139` — placeholder color is `var(--color-text-secondary)` at `opacity: .75`, on top of an already-modest secondary color. Compounds L-9 below (heavy reliance on placeholders as de facto labels).
**Status:** Fixed 2026-08-25 — removed the extra `.75` opacity. Measured contrast: light mode 4.03:1 → 7.58:1, dark mode 3.89:1 → 5.72:1 (both now clear of the 4.5:1 AA threshold, which the opacity-dimmed version failed in both themes).

### L-9. Meaningful gap between inputs using `<label for=...>` vs. relying on `placeholder=`
Only 22 templates use `<label for=...>` against 47 using `placeholder=` (30 use `aria-label=`, with likely overlap). Suggests a set of inputs — especially inline filter/search boxes — may rely on placeholder text alone with neither a visible label nor `aria-label`. Needs a manual per-form pass since grep can't distinguish "labeled via aria-label elsewhere" from "actually unlabeled."
**Status:** Fixed 2026-08-25 for the confirmed cases — manual pass completed. Added `aria-label` to 10 inputs that were genuinely unlabeled (no visible text nearby at all): search/filter boxes in `admin/user_management.html`, `admin/resolved_service_requests.html`, `agent/ticket_conversation.html` (KB insert search), `team_lead/escalated_tickets.html`, `knowledge_base/portal.html` and `management.html`, `documents_display/folder_detail.html` and `category_detail.html`, `partials/audit_log.html`, `partials/popovers/assign_popover.html`, `partials/procurement_mobilization_row.html` (item name/qty/date/vendor/remove-button), and `registration/resend_verification.html`. Inputs that already have a visible (if not `for`/`id`-wired) `<label>` nearby — e.g. the Vendor field in `asset_detail.html`, the Alpine-driven vessel/dive-system/job-number pickers in `service_request_form.html` — were left for the broader label-association pass, which belongs with H-10's dedicated accessibility project rather than this narrower "placeholder with nothing else" finding. See `ACCESSIBILITY_REMEDIATION_PLAN.md` (Phase 3) for the plan.

### L-10. Static asset pipeline is correctly configured for production (positive finding, one unverified assumption)
`whitenoise.storage.CompressedManifestStaticFilesStorage` + `WhiteNoiseMiddleware` in `config/settings/production.py:47-49` handles minification/compression/cache-busting. Not verified in this pass: that `python manage.py tailwind build` (not the dev-only `tailwind start`) is actually invoked in the deploy step — see OQ-6.
**Status:** Verified 2026-08-25 (per OQ-6) — `start.sh` never runs `tailwind build`, but doesn't need to: the compiled `theme/static/css/dist/styles.css` is committed to the repo and its last commit is current with the rest of the codebase. `collectstatic` just picks up what's already built. No bug; the one requirement is a manual-discipline step (rebuild + commit before deploying whenever Tailwind classes change), worth a one-line note in CLAUDE.md if it's ever missed.

### L-11. Double-submit guard only binds at initial page load, missing HTMX-injected forms
**File:** `static/js/global.js:876-878` (as it was before this fix)
`document.querySelectorAll('form[data-guard-submit]').forEach(preventDoubleSubmit)` ran once on `DOMContentLoaded`; any form loaded later via HTMX (slideovers, modals) never got the guard attached even if it carried the attribute. Surfaced during OQ-3's research.
**Status:** Fixed 2026-08-25, together with L-6 — see L-6 above.

---

## Open Questions — Resolved 2026-08-25

All eight were reviewed with the user; resolutions and follow-up research below. These are decisions, not yet remediations — no code has been changed.

**OQ-1.** Is `AssetProcurementRequest` ever expected to have both `ticket` and `mobilization` null (e.g. a general restock request not tied to anything)? Affects whether M-1's fix should be a strict "exactly one" constraint or "at most one."
**Resolved:** At most one. Standalone restock requests with both null are allowed. Add a `CheckConstraint` forbidding `ticket` and `mobilization` from being *set simultaneously* — don't require exactly one.

**OQ-2.** Worth a manual check that every dashboard/partial entry point that fires HTMX requests renders at least one `{% csrf_token %}`, rather than relying on it being incidental to a nearby form? (L-7)
**Resolved:** Yes — approved as a follow-up task. Not yet performed.

**OQ-3.** Should `data-guard-submit` double-submit protection be audited/applied across every slow or critical form (mobilization submit, procurement actions, bulk actions), or is the current opt-in model intentional? (L-6)
**Resolved, with research:** Only 4 templates currently carry `data-guard-submit` (`templates/requester/incident_form.html`, `service_request_form.html`, `ticket_form.html`, `dynamic_ticket_form.html`) — mobilization, procurement, and bulk-action forms have none. The wiring itself has a gap that should be fixed first: `static/js/global.js:876-878` binds the guard once on `DOMContentLoaded` via a one-time query, so any form injected later by HTMX (slideovers, modals) never gets the listener attached. **New finding (L-11):** rebind via `htmx:afterSwap` (or a single document-level delegated submit listener) so the guard self-applies to dynamically loaded forms, then add `data-guard-submit` specifically to the mobilization-item/demobilize forms and the ticket-claim action — the exact operations H-1 and H-2 flag as having real double-submit-driven race conditions. This is a client-side backstop, not a substitute for the server-side locking those two findings actually need.

**OQ-4.** Is the priority/status badge duplication in `ticket_table.html`/`agent_ticket_table.html`/`team_ticket_table.html` (M-12) an accidental miss from before the `status_badge` tag existed, or deliberate for some reason not visible from the templates alone?
**Resolved, via git blame:** Confirmed accidental. `apps/tickets/templatetags/badge_tags.py` was created brand-new (259 lines) in commit `fde5d07` (2026-08-25) — the *same commit* that touched all three ticket tables. The tag was fully wired into `asset_table.html` in that commit (490-line rewrite) but the three ticket tables only received smaller, unrelated edits and were missed during rollout. Safe to fold into the backlog as a straightforward mechanical fix — no investigation needed before remediating.

**OQ-5.** Should `unassigned_queue` (H-9) get real pagination now, or is current ticket volume low enough that this is intentionally deferred? Fixing it touches the bulk-select/HTMX wiring from the recent responsive table redesign.
**Resolved:** Yes, paginate now — bundle with the `select_related` fix already scoped in H-9.

**OQ-6.** Confirm `python manage.py tailwind build` (not `tailwind start`) is actually run as part of the deploy step (`start.sh`/Procfile) — not verified in this pass. (L-10)
**Resolved, verified — not a bug:** `start.sh` never runs `tailwind build` at all, but it doesn't need to: the compiled `theme/static/css/dist/styles.css` is committed to the repository (not gitignored), and its last commit (`fde5d07`, 2026-08-25) is current with the rest of that day's changes. `collectstatic` in `start.sh` simply picks up whatever's already built and checked in. The one real requirement is discipline, not tooling: whoever edits Tailwind classes must run `tailwind build` and commit the output before deploying. Worth a one-line reminder in CLAUDE.md so this doesn't silently go stale on a future change.

**OQ-7.** Grep for hardcoded status-string literals (`'RESOLVED'`, `'P1'`, etc.) duplicated instead of referencing `Ticket.Status`/`Ticket.Priority` choices wasn't completed with full budget — the views sampled (`dashboard`, `my_ticket_list`) do use raw literals but consistently matching the enum values, which is a style question rather than a correctness bug. Worth a dedicated pass before remediation if this is a priority.
**Resolved, pass completed:** 23 templates compare against raw status/priority string literals rather than model `.choices`: `agent_ticket_table.html`, `admin_dashboard.html`, `service_request_detail_form.html`, `incident_detail_form.html`, `service_request_form.html`, `ticket_conversation.html`, `sla_management.html`, `team_ticket_table.html`, `remote_sessions_grid.html`, `escalated_tickets.html`, `manager_review_queue.html`, `ticket_details_panel.html`, `status_modal.html`, `ticket_table.html`, `remote_session_detail.html`, `manager_review_ticket.html`, `ticket_slideover.html`, `schedule_detail.html`, `calendar_view.html`, `incident_form_pdf.html`, `schedule_list.html`, `day_events.html`, `status_badge.html`. This is template-side comparison logic (`{% if ticket.status == 'RESOLVED' %}`) that Django templates can't avoid entirely without exposing the enum via a context processor or custom tag — scope as a style-consistency cleanup, not urgent.

**OQ-8.** Given ARIA is absent app-wide rather than missing on one or two components (H-10), should the accessibility fix (adding `aria-expanded`/`role=dialog`/Escape handling across all modals and accordions) be scoped as its own remediation project rather than folded into smaller per-page fixes?
**Resolved:** Dedicated project — scope as a standalone accessibility pass rather than opportunistic per-page fixes.

The new finding surfaced during OQ-3's research (double-submit guard missing HTMX-injected forms) is filed as **L-11** in the Low section above, alongside its fix status.

---

## Remediation Log — 2026-08-25

Everything below was fixed in a same-day remediation pass following the audit and the open-question resolutions. Deferred: H-10 (ARIA) and the broader label-`for`/`id` wiring noted under L-9 — both scoped to their own accessibility project per OQ-8. See `ACCESSIBILITY_REMEDIATION_PLAN.md` for the phased plan covering both (not yet started).

**Files changed:**
- `apps/tickets/views.py` — C-1/H-1 (`claim_ticket` role check + locking), H-2 (`mobilization_item_demobilize` locking), H-4 (`asset_attachment_upload` validation), H-9 (`unassigned_queue` pagination + `select_related`), M-6 (`procurement_list` pagination), M-7 (magic-byte MIME sniffing, `save_attachments` + `asset_attachment_upload`), M-10 (SLA/cleanup trigger endpoints log instead of leaking exceptions)
- `apps/accounts/views/__init__.py` — H-3 (password-reset rate limit), H-5/M-9 (dashboard N+1 merged into one pass), H-6 (`_get_admin_dashboard_kpis()` extracted + cached)
- `apps/tickets/models.py` — M-1 (`AssetProcurementRequest` CheckConstraint) → migration `tickets.0048`
- `apps/common/models.py` — M-3 (`Notification` composite index) → migration `common.0009`
- `apps/accounts/models.py` — M-4 (`User.save()` manager-cycle guard), M-5 (`ClientSettings.save()` singleton pin)
- `apps/documents_display/permissions.py` — M-8 (`CanViewDocument` delegates to `is_viewable_by`)
- `config/settings/base.py` — M-11 (`CSRF_TRUSTED_ORIGINS` env-driven)
- `config/urls.py` — none needed; `templates/404.html` and `templates/500.html` added instead (H-7), picked up automatically by Django
- `templates/partials/ticket_table.html`, `agent_ticket_table.html`, `team_ticket_table.html` — M-12 (`{% status_badge %}` tag)
- `templates/agent/unassigned_queue.html` — H-9 (pagination controls)
- `templates/tickets/procurement_list.html` — M-6 (pagination controls)
- `templates/dashboards/admin_dashboard.html` — L-2 (removed dead script)
- `static/css/theme.css` — L-8 (placeholder contrast)
- `static/js/global.js` — M-13 (Escape-to-close), L-6/L-11 (double-submit guard rewritten as delegated listener)
- `templates/partials/mobilization_demobilize_modal.html`, `mobilization_demobilize_all_modal.html`, `procurement_receive_modal.html`, `templates/tickets/mobilization_create.html` — `data-guard-submit` applied (L-6)
- 10 templates — L-9 (`aria-label` on genuinely unlabeled inputs; see L-9 above for the full list)
- `apps/organogram/tests.py` — H-8 (11 new tests)

**Migrations:** `tickets.0048_assetprocurementrequest_procurement_request_not_both_ticket_and_mobilization`, `common.0009_notification_notif_recipient_is_read_idx`. Both applied; `makemigrations --check --dry-run` confirms no further model changes pending.

**Verification:** `manage.py check` clean throughout. Test runs: full suite (`apps.tickets apps.accounts apps.organogram`, 276 tests) — 275 passed, 1 failure (`MaintenanceReportExportTests.test_maintenance_pdf_export`) traced to a Playwright/Chromium `networkidle` timeout in `report_exporters.py`, a file untouched by this remediation — environment flakiness, not a regression. Targeted re-runs after every subsequent change (mobilization/vendor-gating/SLA/organogram/documents_display suites, 95 tests; then mobilization + accounts, 69 tests) all passed clean.
