#!/usr/bin/env bash
set -e

echo "=== Running database migrations ==="
python manage.py migrate --noinput

echo "=== Collecting static files ==="
python manage.py collectstatic --noinput

echo "=== Seeding ticket categories ==="
python manage.py seed_categories

echo "=== Seeding Remote Connectors ==="
python manage.py seed_connectors

echo "=== Seeding Macros ==="
python manage.py seed_macros

echo "=== Seeding Asset Categories ==="
python manage.py seed_asset_categories

# TEMPORARY — sample vendor data for the current testing phase only
# (get_or_create keyed on name, so re-running never duplicates). Remove
# this step once real vendor data is in place.
echo "=== Seeding Vendors (testing only — remove before production) ==="
python manage.py seed_vendors

echo "=== Seeding Assets ==="
python manage.py seed_assets

echo "=== Seeding Document Categories ==="
python manage.py seed_document_categories

echo "=== Seeding Roles (dual-role system) ==="
python manage.py seed_roles

echo "=== Seeding Service Categories ==="
python manage.py seed_service_categories

# start.sh
# echo "=== Checking npm version ==="
# npm --version || echo "npm not found"


# Optional: create a superuser if it doesn't exist (requires env vars)
if [ -n "$SUPERUSER_EMAIL" ] && [ -n "$SUPERUSER_PASSWORD" ]; then
  echo "=== Ensuring superuser exists ==="
  python manage.py ensure_superuser
fi

echo "=== Starting Daphne ASGI Server ==="
# Use Daphne for ASGI/WebSocket support
# Render supplies PORT at runtime.  Retaining 8000 as the fallback keeps
# local Docker usage unchanged.
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" config.asgi:application
