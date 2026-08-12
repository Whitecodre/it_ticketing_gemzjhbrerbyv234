#!/usr/bin/env bash
set -e

echo "=== Running database migrations ==="
python manage.py migrate --noinput

echo "=== Seeding ticket categories ==="
python manage.py seed_categories

echo "=== Seeding Remote Connectors ==="
python manage.py seed_connectors

echo "=== Seeding Macros ==="
python manage.py seed_macros

echo "=== Seeding Assets ==="
python manage.py seed_assets

echo "=== Seeding Document Categories ==="
python manage.py seed_document_categories

# start.sh
echo "=== Checking npm version ==="
npm --version || echo "npm not found"


# Optional: create a superuser if it doesn't exist (requires env vars)
if [ -n "$SUPERUSER_EMAIL" ] && [ -n "$SUPERUSER_PASSWORD" ]; then
  echo "=== Ensuring superuser exists ==="
  python manage.py ensure_superuser
fi

echo "=== Starting Daphne ASGI Server ==="
# Use Daphne for ASGI/WebSocket support
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application