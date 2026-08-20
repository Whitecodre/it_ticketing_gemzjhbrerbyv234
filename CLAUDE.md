# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working style

When fixing an issue or implementing a request, use the most token-efficient approach that does not reduce the quality of the outcome. Concretely: read only the files/sections you actually need (targeted Grep/Read over wholesale file reads, especially for the large files like `apps/tickets/views.py` or `apps/tickets/models.py`), avoid re-reading files you just edited, skip exploratory detours once you have enough context to act, and keep explanations/summaries terse. Never cut corners on correctness, testing, or thoroughness to save tokens — efficiency is about cutting wasted steps, not cutting rigor.

When a full test suite run is warranted after a change (not a small targeted test), do not run it yourself in the background. Instead, give the user the exact `python manage.py test ...` command to run in their own terminal, and wait for them to report back the results. A small, targeted test (e.g. a single new test class) to verify an implementation works is still fine to run directly.

## Project

Django IT service management / helpdesk platform, developed by **Gemz Software** (also referred to as "TicketSwipe" in some templates) as a **white-label, multi-tenant product**. The current pilot client is Hydrodive (a marine/offshore logistics company), but code should stay data-driven and multi-tenant-friendly (via `ClientSettings` and similar per-org config) rather than hardcoding client-specific values, department lists, or branding.

## Commands

Windows dev environment; venv at `venv/`.

```
# Activate venv (PowerShell)
venv\Scripts\Activate.ps1

# Run dev server (defaults to config.settings.development)
python manage.py runserver

# Run tests (Django test runner, not pytest, despite pytest-cov in requirements)
python manage.py test
python manage.py test apps.tickets                      # single app
python manage.py test apps.tickets.tests.TicketModelTest # single test case
python manage.py test apps.tickets.tests.TicketModelTest.test_sla_breach  # single test

# Migrations
python manage.py makemigrations
python manage.py migrate

# Seed data (also run by start.sh on deploy)
python manage.py seed_categories
python manage.py seed_connectors
python manage.py seed_macros
python manage.py seed_assets
python manage.py seed_roles

# SLA background processing (must run continuously; not triggered by request cycle)
python manage.py run_sla_scheduler --interval=5   # or run_sla_scheduler.bat on Windows
python manage.py process_sla                       # single pass, used by scheduler.py on Azure

# Tailwind (theme app, django-tailwind)
python manage.py tailwind start   # watch mode during development
python manage.py tailwind build   # production build
```

Settings module is chosen via `DJANGO_SETTINGS_MODULE`; `manage.py` defaults to `config.settings.development`, Procfile/start.sh use `config.settings.production`. Both read secrets from `.env` (see `.env` for the full variable list — DB, email/Brevo, Cloudinary, VAPID push keys, `SLA_TRIGGER_SECRET`).

## Architecture

**Stack:** Django 4.2 + Channels (ASGI via Daphne, WebSocket notifications), PostgreSQL (uses `ArrayField`/other Postgres-specific features — don't switch to sqlite/mysql), Redis (cache backend + rate limiting + channel layer in production), DRF, django-tailwind, TinyMCE (rich text), django-webpush (push notifications), Cloudinary (production media storage).

**Entry points:** `config/asgi.py` is the real application entry point (not just `wsgi.py`) — it routes `ws/notifications/` to `apps.common.consumers.NotificationConsumer` alongside normal HTTP. Both Procfile and `start.sh` run Daphne, not gunicorn/wsgi, even for plain HTTP traffic.

**Apps** (`apps/`):
- `accounts` — custom email-based `User` model (`AUTH_USER_MODEL = accounts.User`, no username field, `EmailBackend` auth backend). Dual role system in transition: a legacy single `role` CharField (`Role` TextChoices: SUPERADMIN/ADMIN/TEAM_LEAD/AGENT/END_USER) kept for backward compatibility, plus a newer M2M `Role` model (`apps.accounts.models.Role`, separate from the enum) with per-user `active_role` FK — `dashboard()` in `apps/accounts/views/__init__.py` reads `active_role` to pick which dashboard template and context to render, falling back to highest-priority assigned role. Also owns: department field (fixed choices, currently Hydrodive-specific — see multi-tenancy note above), manager/subordinate org hierarchy, audited user impersonation (`ImpersonationLog`/`ImpersonationToken`, gated by `ImpersonationMiddleware` in `apps/common/middleware.py`), and `ClientSettings` for white-label branding (company name/logo).
- `tickets` — the core domain: `Ticket` (Incident/Service Request types, multi-stage status workflow, impact/urgency/priority P1-P4), `SLA`/`EscalationRule`/`BusinessCalendar` for response/resolution breach tracking, `Asset`/`AssetCategory`/`AssetCheckoutHistory`/`AssetMaintenanceLog` for IT asset management, `RemoteConnector`/`RemoteSession`. SLA breach checking is NOT computed on request — it's driven by the standalone `run_sla_scheduler`/`process_sla` management commands, meant to run as a separate long-lived process (Windows: `run_sla_scheduler.bat`; Azure: `scheduler.py` as a WebJob, see `ReadMe-Making SLA SCHEDULER WORK WITH AZURE.txt`). `views.py` here is very large (~150KB) — search for the specific view rather than reading it wholesale.
- `common` — cross-cutting concerns: `SecurityHeadersMiddleware` and `ImpersonationMiddleware`, `NotificationConsumer` (WebSocket), `Notification`/`PushSubscription` models, shared `Category`/`Tag`, context processors (`vapid_keys`, `impersonation_context`, `client_settings`, `active_role_context` — all globally available in templates).
- `documents_display` — newest app, in-progress document approval workflow with PDF/Office preview (LibreOffice conversion via `LIBREOFFICE_BINARY_PATH`). Has its own `permissions.py`. `SecurityHeadersMiddleware` special-cases this app's viewer/serve URLs and `/media/display_docs/` to allow framing (needed for embedded PDF/Office previews) and skips `X-Frame-Options: DENY` for PDF responses generally.
- `form_builder` — **mid-refactor / mostly deprecated.** Its URLs are commented out in `config/urls.py`, and `views_deprecated.py` exists alongside `views.py`. The formio.js-based dynamic form builder (`static/js/formio/`, `static/lib/formiojs/`) referenced by `package.json` has been removed from the repo (see git status) — don't reintroduce dependencies on it without confirming with the user first.
- `knowledge_base`, `maintenance`, `organogram` — supporting apps (KB articles via TinyMCE, maintenance scheduling/calendar, org chart).

**Role-based UI:** Templates under `templates/dashboards/`, `templates/admin/`, `templates/agent/`, `templates/approver/`, `templates/requester/`, `templates/team_lead/` — separate dashboard/sidebar per role rather than one generic view with conditionals. When adding role-gated features, follow this per-role template split rather than branching heavily inside shared templates.

**Real-time/push:** Two parallel notification channels — WebSocket (Channels, `NotificationConsumer`, `InMemoryChannelLayer` in dev / `RedisChannelLayer` in production) and Web Push (`django-webpush`, VAPID keys, `apps/common/management/commands/send_push_notification.py`). Both are driven off the same `Notification` model in `apps/common/models.py`.

**Settings layout:** `config/settings/base.py` (shared) → `development.py` / `production.py`. Production enforces HSTS/SSL/secure-cookie settings and raises at import time if `DATABASE_URL`, `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` are missing — don't add new required env vars to `base.py` without defaults, since both environments import it.
