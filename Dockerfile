# syntax=docker/dockerfile:1
FROM python:3.12.7-slim

# System dependencies:
# - libreoffice-{writer,calc,impress}: headless DOCX/XLSX/PPTX -> PDF preview
#   conversion for apps.documents_display (apps/documents_display/utils.py,
#   convert_office_to_pdf). Installing the specific Writer/Calc/Impress
#   packages instead of the full `libreoffice` metapackage covers every
#   extension actually converted (doc/docx, xls/xlsx, ppt/pptx) at a
#   fraction of the image size.
# - fonts-liberation / fonts-dejavu-core: common Office-doc font substitutes
#   so converted PDFs don't fall back to missing-glyph boxes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright needs its own downloaded browser binary + matching OS libs -
# used by apps/tickets/report_exporters.py to render Incident/Service
# Request PDF reports via headless Chromium (not xhtml2pdf).
RUN playwright install --with-deps chromium

COPY . .

ENV PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

EXPOSE 8000

# Migrations, seeding, collectstatic, and starting Daphne all happen inside
# start.sh at container start, not here at build time - they need runtime
# env vars (DATABASE_URL, email creds) that Render/Cloudflare inject when
# the container starts, not when the image is built. production.py raises
# at import time if those are missing, so running any manage.py command
# against it during `docker build` would fail.
CMD ["bash", "start.sh"]
