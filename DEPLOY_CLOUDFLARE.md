# Deploying to Cloudflare (Containers/Workers — Option B)

## Read this first

You asked for a same-day deployment. Being straight with you: the **code side** of this is genuinely doable today — most of it is already done below. The parts I *cannot* guarantee finish today are the parts that aren't code: creating/verifying a Cloudflare account with Workers Paid enabled, provisioning an external Postgres + Redis instance, DNS propagation, and `wrangler`'s exact current container syntax (Cloudflare Containers is a newer product and its `wrangler.toml` schema has changed more than once — verify Phase 4 against `https://developers.cloudflare.com/containers/` at deploy time, don't trust it blindly). Those are dashboard/CLI steps only you can execute, gated by third-party services outside my control. Everything I can do without your Cloudflare/DB/Redis credentials, I've already done in this repo.

Also — per the feasibility notes this project already had (now removed at your request, but the technical facts still apply): Option B has no built-in load balancer like your old Azure App Service gave you for free, and container disk is ephemeral. Both are covered below.

---

## Phase 0 — Accounts & services you need to provision

1. **Cloudflare account** with the **Workers Paid plan** ($5/mo minimum) — required for Containers.
2. **External PostgreSQL** — Cloudflare does not host Postgres. Pick one reachable over the public internet with SSL: Neon, Supabase, Render Postgres, Aiven, or similar. Get its connection string.
3. **External Redis** — Cloudflare does not host Redis either. Upstash Redis (serverless, pay-per-request, popular for exactly this use case) or Redis Cloud. Get its `rediss://` (TLS) URL.
4. **`wrangler` CLI** installed and logged in: `npm install -g wrangler && wrangler login`.
5. Your domain's DNS either already on Cloudflare, or ready to be moved there.

---

## Phase 1 — Code changes (done in this session)

These are already committed to the working tree, not yet pushed:

1. **Real client IP behind Cloudflare** — added `CloudflareRealIPMiddleware` ([apps/common/middleware.py](apps/common/middleware.py)), first in `MIDDLEWARE` ([config/settings/base.py](config/settings/base.py)). Rewrites `REMOTE_ADDR` from Cloudflare's `CF-Connecting-IP` header. Without this, rate limiting, `ImpersonationLog`, and `LoginHistory` would all see Cloudflare's edge IP instead of the real client — silently breaking per-IP rate limits and making audit logs useless.
2. **Scheduler → HTTP-triggerable endpoint** — added `trigger_periodic_jobs_external` view ([apps/tickets/views.py](apps/tickets/views.py)) and wired it at `POST /tickets/cron/trigger-periodic-jobs/` ([apps/tickets/urls.py](apps/tickets/urls.py)). It calls the same `run_periodic_jobs()` used by `run_periodic_tasks`/`scheduler.py` (`apps/tickets/periodic_tasks.py`) — runs all 5 jobs (`process_sla`, `send_maintenance_reminders`, `process_remote_session_expiry`, `send_renewal_reminders`, `send_share_expiry_reminders`) in one call, isolating failures per job. Auth: `X-SLA-Trigger-Secret` header matching the `SLA_TRIGGER_SECRET` env var. This replaces the long-lived `run_periodic_tasks` loop — a Cloudflare Cron Trigger hits this URL on an interval instead (Phase 6).
   - **Note:** this endpoint always returns `{"status": "ok"}` if it ran at all — individual job failures are logged, not raised (matches `run_periodic_jobs`'s existing "one job failing shouldn't block the others" design). Watch your log aggregator for `❌` lines, not just HTTP status.
3. **DB connection reuse** — `CONN_MAX_AGE: 60` added to both `development.py` and `production.py`. Matters more in a container that may serve many requests per instance lifetime.
4. **Session reads via Redis, not DB** — `SESSION_ENGINE = cached_db` in `base.py`. **Depends on Redis actually being reachable** — if `REDIS_URL` is wrong/unset in production, this breaks logins app-wide (see Phase 3 checklist).
5. **Dockerfile already exists and is already container-correct** ([Dockerfile](Dockerfile)) — bundles LibreOffice (Writer/Calc/Impress) for document preview conversion and Playwright+Chromium for PDF report export. `start.sh` runs migrations/seeding/collectstatic then execs Daphne. **No changes needed here.**
6. **Ephemeral-disk audit** — checked `apps/documents_display/utils.py` (LibreOffice conversion) and `apps/tickets/report_exporters.py` (Playwright PDF export): both already use `tempfile`/in-memory buffers scoped to a single request, not a fixed local path expected to persist. **Safe as-is** for Containers' ephemeral disk — no code change needed.
7. Production media already goes to Cloudinary (`DEFAULT_FILE_STORAGE`), not local disk — already ephemeral-disk-safe.

**Still to do in code, not started (say the word if you want these too):**
- None required for a functional deploy. Everything above covers the concrete gaps identified.

---

## Phase 2 — Provision Postgres + Redis

1. Create the Postgres instance. Run migrations against it once reachable (you'll do this via `start.sh` on first container boot, or manually: `DATABASE_URL=... python manage.py migrate`).
2. Create the Redis instance. Cloudflare Containers has normal outbound networking, so a TLS Redis URL (`rediss://...`) works like from any other host — no Cloudflare-specific Redis config needed.
3. Sanity-check both are reachable from your machine before wiring them into Cloudflare, to isolate "is it Cloudflare" from "is it my DB/Redis" if something breaks later:
   ```
   psql "postgresql://user:pass@host:port/db" -c "select 1;"
   redis-cli -u "rediss://default:pass@host:port" ping
   ```

---

## Phase 3 — Environment variables / secrets checklist

Every one of these must be set as a Cloudflare secret (`wrangler secret put NAME`) or plain var (`wrangler.toml` `[vars]`) before first deploy. Pulled directly from `.env.example` — nothing here is guessed:

| Variable | Secret or plain? | Notes |
|---|---|---|
| `SECRET_KEY` | secret | Generate fresh — don't reuse the dev one. |
| `DEBUG` | plain | `False` |
| `DATABASE_URL` | secret | From Phase 2. Required — `production.py` raises at startup if missing. |
| `ALLOWED_HOSTS` | plain | Your Cloudflare-fronted domain(s), comma-separated. |
| `CSRF_TRUSTED_ORIGINS` | plain | `https://` + same domain(s). |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | secret | Required — `production.py` raises without them. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | secret (creds) / plain (rest) | `EMAIL_HOST_USER`/`PASSWORD` required — raises without them. |
| `BREVO_API_KEY` | secret | |
| `REDIS_URL` | secret | From Phase 2. **Double-check this is actually set** — silent fallback to `127.0.0.1` would break sessions/cache/rate-limiting/Channels entirely in production (see Phase 1 item 4). |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIM_EMAIL` | secret (private) / plain (public/email) | Push notifications. |
| `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | plain | Defaults in `production.py` are already sane (HSTS on, SSL redirect on) — only override if you have a reason to. |
| `SLA_TRIGGER_SECRET` | secret | Generate fresh, random. Used by the Cron Trigger in Phase 6. |
| `LIBREOFFICE_BINARY_PATH` | plain | Leave unset — Dockerfile installs it at the default `soffice` path. |

---

## Phase 4 — `wrangler.toml` + container config

**Verify this against current Cloudflare docs before running it** — Containers is a fast-moving product and I can't guarantee this schema matches what's live today. Starting point:

```toml
name = "it-ticketing"
main = "worker/router.js"          # Worker script that routes requests to the container
compatibility_date = "2026-08-01"

[[containers]]
class_name = "AppContainer"
image = "./Dockerfile"             # wrangler builds + pushes this on deploy
max_instances = 3                  # tune to your expected concurrency/budget

[durable_objects]
bindings = [
  { name = "APP_CONTAINER", class_name = "AppContainer" }
]

[[migrations]]
tag = "v1"
new_classes = ["AppContainer"]
```

You also need a minimal Worker script (`worker/router.js`) that receives every request and forwards it to the container instance — Cloudflare's own `@cloudflare/containers` package provides the `Container` class to extend for this; check `https://github.com/cloudflare/containers` for the current minimal example, since writing this by hand without seeing their current API would be guessing.

**WebSocket note:** `ws/notifications/` (Channels/Daphne) needs the Worker to proxy the upgrade request through untouched — Cloudflare Containers proxies HTTP(S) including WS upgrades to the container automatically; verify this specific path with a real browser connection after first deploy (Phase 8), don't assume.

---

## Phase 5 — Build & deploy

```
wrangler deploy
```

This builds the image from the `Dockerfile` (already correct — Phase 1.5), pushes it to Cloudflare's registry, and deploys the Worker + container. First build will be slow (LibreOffice + Playwright/Chromium install) — expect several minutes, not seconds.

After deploy, run migrations once against the live DB if `start.sh` didn't already handle it on container boot (it does — `python manage.py migrate --noinput` runs at container start, so this is usually automatic; just confirm in the deploy logs).

---

## Phase 6 — Cron Trigger for periodic jobs

In `wrangler.toml`:
```toml
[triggers]
crons = ["*/5 * * * *"]   # every 5 minutes — adjust to your SLA granularity needs
```
And a scheduled handler in your Worker that does:
```js
export default {
  async scheduled(event, env, ctx) {
    await fetch("https://your-domain.com/tickets/cron/trigger-periodic-jobs/", {
      method: "POST",
      headers: { "X-SLA-Trigger-Secret": env.SLA_TRIGGER_SECRET },
    });
  },
};
```
This replaces the old always-on `run_periodic_tasks`/`scheduler.py` loop with a Cron Trigger hitting the endpoint from Phase 1.2.

---

## Phase 7 — DNS cutover

Point your domain's DNS to the Worker route in Cloudflare (proxied/orange-clouded). If the domain is new to Cloudflare, this also means an actual nameserver change — allow for propagation time, which is the one step here truly outside anyone's control timeline-wise.

---

## Phase 8 — Full functionality smoke test (do this before calling it done)

Go through every one of these against the live URL — don't skip any, each exercises a different part of the stack that changed:

- [ ] **Login/logout** — exercises Postgres + the new `cached_db` session backend (Redis). If this fails, check `REDIS_URL` first.
- [ ] **Create a ticket, add a comment, upload an attachment** — exercises Postgres writes + Cloudinary media storage.
- [ ] **WebSocket notification** — open two browser sessions, trigger a notification (e.g. assign a ticket), confirm the other session gets it live via `ws/notifications/`. This is the highest-risk item under Option B's routing model.
- [ ] **Remote session accept/reject flow** — exercises the WS-adjacent remote session state.
- [ ] **Document preview (PDF/Office)** in `documents_display` — exercises the LibreOffice conversion path and confirms the container has the binary and enough memory/CPU to run it.
- [ ] **Export an Incident/Service Request report to PDF** — exercises Playwright+Chromium inside the container.
- [ ] **Password reset email** — exercises SMTP/Brevo config.
- [ ] **Push notification** (if a device is registered) — exercises VAPID keys.
- [ ] **Rate limiting** — hit the login endpoint with wrong credentials several times fast; confirm it actually blocks (and check the IP it logs is the real client IP, not Cloudflare's — validates `CloudflareRealIPMiddleware`).
- [ ] **Impersonation** (as admin) — exercises `ImpersonationMiddleware` + audit logging with the corrected client IP.
- [ ] **Wait 5+ minutes, then check a ticket's SLA timer moved / a maintenance reminder fired** — confirms the Cron Trigger → `trigger-periodic-jobs` path is actually running (check logs for the `✅`/`❌` lines from `run_periodic_jobs`).
- [ ] **Asset checkout/mobilization flow** — exercises a large, DB-heavy code path end-to-end.

---

## Phase 9 — Rollback plan

Keep your current host (wherever it's running today) live and untouched until every item in Phase 8 passes. DNS cutover in Phase 7 is the only irreversible-feeling step, and it isn't — repointing DNS back to the old host is a few-minutes fix if something's broken in production. Don't decommission the old environment until you've run Phase 8 against real traffic for at least a day.

---

## Known standing risks with Option B (not fixable by config, inherent to the architecture)

- **No built-in load balancer** — the Worker router owns routing/health-checking across container instances; a normal PaaS gives you this for free. Watch instance health manually until you've built confidence in the router.
- **Ephemeral container disk** — anything not already audited in Phase 1.6 that starts writing to local disk in the future needs the same scrutiny (temp-file-only, request-scoped, never assumed to survive a restart).
- **WebSocket-to-instance pinning** — a client's WS connection is pinned to one container instance while unrelated REST calls may route elsewhere. Watch for this specifically in Phase 8's WebSocket test if you ever run more than one instance concurrently.
