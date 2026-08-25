# apps/tickets/report_exporters.py
"""
Format writers shared by every report type in the Exportables feature.
Each report type's queryset/row-builder (report_registry.py) is generic
over these — adding a new export format means adding one function here and
registering it in EXPORTERS, not touching every report type.
"""
import csv
import json
import os
from io import BytesIO

import requests
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from playwright.sync_api import sync_playwright
from xhtml2pdf import pisa

PRIMARY_RGB = RGBColor(0x0D, 0x94, 0x88)
META_GRAY_RGB = RGBColor(0x47, 0x55, 0x69)


def _filename(base):
    return f"{base}_{timezone.now().strftime('%Y%m%d_%H%M%S')}"


def _pdf_link_callback(uri, rel):
    """Resolve /media/ and /static/ URLs in the PDF template to absolute
    filesystem paths — xhtml2pdf can't fetch relative URLs itself (it has
    no request context), so without this the letterhead logo silently
    fails to render."""
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, '', 1))
    elif uri.startswith(settings.STATIC_URL):
        static_root = settings.STATIC_ROOT or os.path.join(settings.BASE_DIR, 'static')
        path = os.path.join(static_root, uri.replace(settings.STATIC_URL, '', 1))
    else:
        return uri
    return path if os.path.isfile(path) else uri


def _csv_safe(value):
    """Neutralize spreadsheet formula injection: a string value starting
    with =, +, -, or @ is interpreted as a live formula by Excel/Sheets
    when the exported file is later opened by another admin. Leaves
    non-string values (numbers, None, ...) untouched so exports keep their
    real type in Excel rather than becoming text."""
    if isinstance(value, str) and value and value[0] in ('=', '+', '-', '@'):
        return "'" + value
    return value


def export_csv(rows, columns, title, filename_base, **kwargs):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.csv"'
    writer = csv.DictWriter(response, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(value) for key, value in row.items()})
    return response


def export_excel(rows, columns, title, filename_base, **kwargs):
    wb = Workbook()
    ws = wb.active
    ws.title = (title or 'Report')[:31]
    for col, header in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, key in enumerate(columns, 1):
            ws.cell(row=row_idx, column=col_idx, value=_csv_safe(row_data.get(key, '')))

    # Auto-size each column from its header/content length so the sheet is
    # readable without the user manually resizing every column first.
    for col_idx, header in enumerate(columns, 1):
        letter = ws.cell(row=1, column=col_idx).column_letter
        max_len = len(str(header))
        for row_data in rows[:500]:
            value = row_data.get(header, '')
            max_len = max(max_len, len(str(value)) if value is not None else 0)
        ws.column_dimensions[letter].width = min(max_len + 2, 50)

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.xlsx"'
    wb.save(response)
    return response


def export_json(rows, columns, title, filename_base, **kwargs):
    response = HttpResponse(json.dumps(rows, indent=2, default=str), content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.json"'
    return response


def export_pdf(rows, columns, title, filename_base, request=None, filter_summary='', **kwargs):
    html = render_to_string('reports/report_pdf.html', {
        'title': title,
        'columns': columns,
        'rows': rows,
        'generated_at': timezone.now(),
        'filter_summary': filter_summary,
        'record_count': len(rows),
    }, request=request)

    pdf_bytes = _html_to_pdf(html, request, paginate=True)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.pdf"'
    return response


def _render_form_pdf(template_name, context, request, filename_base):
    html = render_to_string(template_name, {**context, 'generated_at': timezone.now()}, request=request)
    result = BytesIO()
    pisa.CreatePDF(src=html, dest=result, encoding='utf-8', link_callback=_pdf_link_callback)
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.pdf"'
    return response


_PAGE_NUMBER_FOOTER = """
<div style="width:100%; font-size:7.5pt; color:#94A3B8; text-align:center; font-family:Arial,Helvetica,sans-serif;">
  Page <span class="pageNumber"></span> of <span class="totalPages"></span>
</div>
"""


def _html_to_pdf(html, request, paginate=False):
    """Render HTML to PDF bytes via headless Chromium (Playwright), so
    templates can rely on real JS/CSS execution (Tailwind CDN, flexbox)
    instead of xhtml2pdf's limited/buggy renderer. `page.set_content()`
    doesn't carry page origin like `page.goto()`, so a <base href> pointing
    at this request's host must already be present in the template's <head>
    for relative /media//static/ URLs to resolve. `paginate=True` adds a
    Chromium-native "Page X of Y" footer — useful for multi-page tabular
    reports where the page count isn't known until render time."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until='networkidle')
            pdf_kwargs = {'prefer_css_page_size': True, 'print_background': True}
            if paginate:
                # An explicit `margin` here overrides the template's own
                # @page margin (Chromium ignores CSS page-margins once this
                # option is passed), so all four sides must be restated —
                # matching report_pdf.html's own @page margin, with extra
                # bottom room reserved for the page-number footer.
                pdf_kwargs.update(
                    display_header_footer=True,
                    header_template='<span></span>',
                    footer_template=_PAGE_NUMBER_FOOTER,
                    margin={'top': '1.6cm', 'left': '1.6cm', 'right': '1.6cm', 'bottom': '1.9cm'},
                )
            pdf_bytes = page.pdf(**pdf_kwargs)
        finally:
            browser.close()
    return pdf_bytes


def _render_form_pdf_chromium(template_name, context, request, filename_base):
    html = render_to_string(template_name, {**context, 'generated_at': timezone.now()}, request=request)
    pdf_bytes = _html_to_pdf(html, request)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.pdf"'
    return response


def _docx_heading(doc, text):
    heading = doc.add_heading(text, level=2)
    for run in heading.runs:
        run.font.color.rgb = PRIMARY_RGB
    return heading


def _docx_simple_table(doc, headers, rows, placeholder='To be completed by the IT team'):
    """Bordered table with a bold header row, matching the "blank form
    section" tables the paper-form PDFs ship (Systems Affected,
    Recommendations, etc.) — used so the DOCX has a real table there too
    instead of a placeholder sentence. `rows` empty renders one italic
    placeholder row spanning all columns, same as the PDF's blank row."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = 'Table Grid'
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = ''
        run = cell.paragraphs[0].add_run(header)
        run.bold = True
    if rows:
        for row_values in rows:
            row_cells = table.add_row().cells
            for cell, value in zip(row_cells, row_values):
                cell.text = str(value) if value not in (None, '') else ''
    else:
        row_cells = table.add_row().cells
        row_cells[0].merge(row_cells[-1])
        row_cells[0].paragraphs[0].add_run(placeholder).italic = True
    doc.add_paragraph()
    return table


def _docx_field(doc, label, value):
    p = doc.add_paragraph()
    p.add_run(f'{label}: ').bold = True
    p.add_run(str(value) if value not in (None, '') else '—')


def _set_cell_border(cell, **edges):
    """python-docx has no high-level cell-border API — draws thin borders
    on a table cell via direct OXML manipulation. edges: top/bottom/left/
    right, each a dict like {'sz': 8, 'val': 'single', 'color': '0F172A'}."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = tcPr.find(qn('w:tcBorders'))
    if tcBorders is None:
        tcBorders = OxmlElement('w:tcBorders')
        tcPr.append(tcBorders)
    for edge_name, edge_data in edges.items():
        if not edge_data:
            continue
        tag = f'w:{edge_name}'
        element = tcBorders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            tcBorders.append(element)
        for key, value in edge_data.items():
            element.set(qn(f'w:{key}'), str(value))


def _box_cell(cell, sz=8, color='0F172A'):
    edge = {'sz': sz, 'val': 'single', 'color': color, 'space': '0'}
    _set_cell_border(cell, top=edge, bottom=edge, left=edge, right=edge)


def _docx_image_source(field):
    """Returns something doc.add_picture()/run.add_picture() can consume
    for a Django ImageField, regardless of storage backend: a local path
    in dev (FileSystemStorage), or fetched bytes in production (Cloudinary,
    which has no filesystem path). Returns None on any failure so callers
    can gracefully fall back to text — never let a bad/missing image crash
    an export."""
    if not field:
        return None
    try:
        return field.path
    except NotImplementedError:
        pass
    except Exception:
        return None
    try:
        resp = requests.get(field.url, timeout=5)
        resp.raise_for_status()
        return BytesIO(resp.content)
    except Exception:
        return None


def _docx_letterhead(doc, form_code, rev, form_date, title, page):
    """Boxed 3-column header matching the paper forms' layout: logo box,
    centered form title + code, and a Page/Rev/Date meta box."""
    from apps.accounts.models import ClientSettings

    table = doc.add_table(rows=1, cols=3)
    table.autofit = False
    logo_cell, title_cell, meta_cell = table.rows[0].cells
    for cell, width in zip((logo_cell, title_cell, meta_cell), (Inches(1.3), Inches(3.4), Inches(1.8))):
        cell.width = width
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _box_cell(cell)

    client_settings = ClientSettings.objects.first()
    logo_p = logo_cell.paragraphs[0]
    logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    logo_source = _docx_image_source(client_settings.logo) if client_settings and client_settings.logo else None
    if logo_source:
        logo_p.add_run().add_picture(logo_source, width=Inches(1.1))
    else:
        brand_run = logo_p.add_run(client_settings.company_name if client_settings else 'My Company')
        brand_run.bold = True
        brand_run.font.color.rgb = PRIMARY_RGB

    title_p = title_cell.paragraphs[0]
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(title)
    title_run.bold = True
    title_run.font.size = Pt(14)
    code_p = title_cell.add_paragraph()
    code_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    code_run = code_p.add_run(form_code)
    code_run.font.size = Pt(8)
    code_run.font.color.rgb = META_GRAY_RGB

    meta_rows = [('Page:', page), ('Rev.:', rev), ('Date:', form_date)]
    for index, (label, value) in enumerate(meta_rows):
        meta_p = meta_cell.paragraphs[0] if index == 0 else meta_cell.add_paragraph()
        meta_p.paragraph_format.space_after = Pt(0)
        label_run = meta_p.add_run(f'{label} ')
        label_run.bold = True
        label_run.font.size = Pt(8)
        value_run = meta_p.add_run(str(value))
        value_run.font.size = Pt(8)

    doc.add_paragraph()


def _docx_report_letterhead(doc, title, generated_at, filter_summary, record_count, usable_width_in=7.8):
    """Boxed letterhead for the generic tabular exports (group/batch report
    exports), matching the same visual language as `_docx_letterhead` but
    with Generated/Filters/Records meta instead of a numbered paper form's
    Page/Rev/Date. Spans `usable_width_in` so its border aligns with the
    data table beneath it."""
    from apps.accounts.models import ClientSettings

    logo_w, title_w = 1.6, 3.6
    meta_w = max(usable_width_in - logo_w - title_w, 2.0)

    table = doc.add_table(rows=1, cols=3)
    table.autofit = False
    logo_cell, title_cell, meta_cell = table.rows[0].cells
    for cell, width in zip((logo_cell, title_cell, meta_cell), (Inches(logo_w), Inches(title_w), Inches(meta_w))):
        cell.width = width
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _box_cell(cell)

    client_settings = ClientSettings.objects.first()
    logo_p = logo_cell.paragraphs[0]
    logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    logo_source = _docx_image_source(client_settings.logo) if client_settings and client_settings.logo else None
    if logo_source:
        logo_p.add_run().add_picture(logo_source, width=Inches(1.3))
    else:
        brand_run = logo_p.add_run(client_settings.company_name if client_settings else 'My Company')
        brand_run.bold = True
        brand_run.font.color.rgb = PRIMARY_RGB

    title_p = title_cell.paragraphs[0]
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run((title or 'Report').upper())
    title_run.bold = True
    title_run.font.size = Pt(13)
    subtitle_p = title_cell.add_paragraph()
    subtitle_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_run = subtitle_p.add_run('DATA EXPORT REPORT')
    subtitle_run.font.size = Pt(8)
    subtitle_run.font.color.rgb = META_GRAY_RGB

    meta_rows = [
        ('Generated:', generated_at.strftime('%B %d, %Y %H:%M')),
        ('Filters:', filter_summary or 'None applied'),
        ('Records:', f'{record_count} record{"s" if record_count != 1 else ""}'),
    ]
    for index, (label, value) in enumerate(meta_rows):
        meta_p = meta_cell.paragraphs[0] if index == 0 else meta_cell.add_paragraph()
        meta_p.paragraph_format.space_after = Pt(0)
        label_run = meta_p.add_run(f'{label} ')
        label_run.bold = True
        label_run.font.size = Pt(8)
        value_run = meta_p.add_run(str(value))
        value_run.font.size = Pt(8)

    doc.add_paragraph()


def _docx_signoff_table(doc, headers, rows):
    """Role | Name & Signature | Date table matching the paper form's
    Sign-off & Approvals table — each row a (role_label, signoff) pair, an
    uploaded signature embedded as an image in the signature cell when
    present, else the 'captured digitally' text fallback ('Pending' when
    nobody has signed off yet)."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = 'Table Grid'
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = ''
        run = cell.paragraphs[0].add_run(header)
        run.bold = True
    for role_label, signoff in rows:
        role_cell, sig_cell, date_cell = table.add_row().cells
        role_cell.paragraphs[0].add_run(role_label).bold = True

        sig_p = sig_cell.paragraphs[0]
        if not signoff['captured_text']:
            sig_p.add_run('Pending').italic = True
        elif signoff['signature_url'] and signoff['user']:
            src = _docx_image_source(signoff['user'].signature)
            if src:
                sig_p.add_run().add_picture(src, height=Inches(0.3))
            else:
                sig_p.add_run(signoff['captured_text']).italic = True
        else:
            sig_p.add_run(signoff['captured_text']).italic = True

        date_cell.text = signoff['date'].strftime('%Y-%m-%d') if signoff['date'] else ''
    doc.add_paragraph()
    return table


def _docx_signoff_field(doc, label, signoff):
    """Renders a sign-off line: the user's uploaded signature image when
    available, else the existing 'captured digitally' text fallback."""
    p = doc.add_paragraph()
    p.add_run(f'{label}: ').bold = True
    if not signoff['captured_text']:
        p.add_run('Pending')
        return
    if signoff['signature_url'] and signoff['user']:
        src = _docx_image_source(signoff['user'].signature)
        if src:
            doc.add_picture(src, height=Inches(0.35))
    caption = doc.add_paragraph()
    caption.add_run(signoff['captured_text']).italic = True


def export_incident_pdf(ticket, request):
    from .report_registry import incident_form_sections
    context = incident_form_sections(ticket)
    return _render_form_pdf_chromium('reports/incident_form_pdf.html', context, request, f'incident_{ticket.number}')


def export_incident_docx(ticket):
    from .report_registry import incident_form_sections
    ctx = incident_form_sections(ticket)

    doc = Document()
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(10)

    _docx_letterhead(doc, 'HDG-IT-FRM-086', 'A01', timezone.now().strftime('%d %B %Y'), 'IT INCIDENT REPORT FORM', page='1 of 4')

    title = doc.add_heading(f'IT Incident Report — {ticket.number}', level=1)
    for run in title.runs:
        run.font.color.rgb = PRIMARY_RGB
    doc.add_paragraph(ticket.title).runs[0].italic = True

    _docx_heading(doc, 'Section 1 — Incident Details')
    _docx_field(doc, 'Incident Reference No.', ticket.number)
    _docx_field(doc, 'Date & Time of Incident', ticket.incident_datetime.strftime('%Y-%m-%d %H:%M') if ticket.incident_datetime else None)
    _docx_field(doc, 'Incident Category', ctx['incident_category_display'])
    _docx_field(doc, 'Severity', ticket.get_urgency_display())
    _docx_field(doc, 'Business Impact', ticket.get_business_impact_display() if ticket.business_impact else None)
    _docx_field(doc, 'How Discovered', ctx['how_discovered_display'])
    _docx_field(doc, 'Location / IP / Hostname', ticket.location_hostname)
    _docx_field(doc, 'System / Service / Asset Affected', ticket.location_hostname)

    _docx_heading(doc, 'Section 2 — Reporter Information')
    _docx_field(doc, 'Reported By', ticket.requester.get_full_name() or ticket.requester.email)
    _docx_field(doc, 'Department / Unit', ticket.requester.get_department_display())
    _docx_field(doc, 'Job Title / Role', ticket.requester.position)
    _docx_field(doc, 'Email', ticket.requester.email)
    _docx_field(doc, 'Submitted', ticket.created_at.strftime('%Y-%m-%d %H:%M'))

    _docx_heading(doc, 'Section 3 — Detailed Incident Description')
    doc.add_paragraph(ticket.description)
    if ticket.immediate_actions:
        _docx_field(doc, 'Immediate/Initial Actions', ticket.immediate_actions)

    _docx_heading(doc, 'Section 5 — Root Cause Analysis')
    _docx_field(doc, 'Root Cause Category', ', '.join(ctx['root_cause_category_display']) or None)
    _docx_field(doc, 'Detailed Root Cause / Contributing Factors', ctx['resolution_root_cause'])

    _docx_heading(doc, 'Section 4 — Systems / Users Affected')
    _docx_simple_table(doc, ['System / Application / Device', 'No. of Users / Devices Impacted', 'Nature of Impact'], [])

    _docx_heading(doc, 'Section 6 — Resolution & Corrective Actions')
    resolved = ticket.status in ('RESOLVED', 'CLOSED')
    _docx_field(doc, 'Resolution Status', 'Fully Resolved' if resolved else 'Pending / Escalated')
    _docx_field(doc, 'Date & Time of Resolution', ticket.resolution_confirmed_at.strftime('%Y-%m-%d %H:%M') if ticket.resolution_confirmed_at else 'Pending')
    _docx_field(doc, 'Steps Taken to Resolve the Incident', ctx['resolution_steps'])

    _docx_heading(doc, 'Section 7 — Recommendations & Preventive Actions')
    _docx_simple_table(doc, ['Recommended Action', 'Responsible Person', 'Target Date', 'Status'], [])

    _docx_heading(doc, 'Section 8 — Communication & Distribution')
    _docx_field(doc, 'Report Communicated To', 'IT Manager')
    _docx_field(doc, 'Method of Communication', 'IT Helpdesk Ticket')

    _docx_heading(doc, 'Section 9 — Supporting Documentation Attached')
    if ctx['attachments'] or ctx['image_attachments']:
        for a in ctx['attachments']:
            doc.add_paragraph(f'• {a.filename}')
        for a in ctx['image_attachments']:
            doc.add_paragraph(f'{a.filename}:')
            image_source = _docx_image_source(a.file)
            if image_source:
                doc.add_picture(image_source, width=Inches(6))
                doc.add_page_break()
            else:
                doc.add_paragraph('(image could not be embedded)').runs[0].italic = True
    else:
        doc.add_paragraph('No attachments.').runs[0].italic = True

    _docx_heading(doc, 'Section 10 — Sign-off & Approvals')
    _docx_signoff_table(doc, ['Role', 'Name & Signature', 'Date'], [
        ('Prepared By (Reporter)', ctx['prepared_by_signoff']),
        ('Reviewed & Approved By (IT Manager / Head of IT)', ctx['it_manager_signoff']),
        ('Confirmed Resolved By', ctx['confirmed_resolved_signoff']),
    ])

    buf = BytesIO()
    doc.save(buf)
    response = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="{_filename("incident_" + ticket.number)}.docx"'
    return response


def export_service_request_pdf(ticket, request):
    from .report_registry import service_request_form_sections
    context = service_request_form_sections(ticket)
    return _render_form_pdf_chromium('reports/service_request_form_pdf2.html', context, request, f'service_request_{ticket.number}')


def export_service_request_docx(ticket):
    from .report_registry import service_request_form_sections
    ctx = service_request_form_sections(ticket)

    doc = Document()
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(10)

    _docx_letterhead(doc, 'HDG-IT-FRM-081', '1', timezone.now().strftime('%d %B %Y'), 'SERVICE REQUEST FORM', page='1 of 1')

    title = doc.add_heading(f'Service Request — {ticket.number}', level=1)
    for run in title.runs:
        run.font.color.rgb = PRIMARY_RGB
    doc.add_paragraph(ticket.title).runs[0].italic = True

    _docx_field(doc, "Requester's Name", ctx['requester_name'])
    _docx_field(doc, 'Date', ticket.created_at.strftime('%Y-%m-%d'))
    _docx_field(doc, 'Department', ctx['requester_department'])
    _docx_field(doc, 'Location', ctx['location']['display'] or 'Not available')
    _docx_field(doc, 'Reported To', ctx['reported_to'] or 'Unassigned')
    _docx_field(doc, 'Service Category', ctx['service_category_name'] or '—')
    _docx_field(doc, 'Purpose', ctx['purpose'] or '—')
    for label, value in ctx['dynamic_fields']:
        _docx_field(doc, label, value)

    _docx_heading(doc, 'Description of Work Order Request')
    doc.add_paragraph(ticket.description)

    if ctx['vessels'] or ctx['job_number'] or ctx['dive_systems']:
        if ctx['vessels']:
            _docx_field(doc, 'Vessel(s)', ', '.join(v.name for v in ctx['vessels']))
        if ctx['job_number']:
            _docx_field(doc, 'Job Number', ctx['job_number'].number)
        if ctx['dive_systems']:
            _docx_field(doc, 'Dive System(s)', ', '.join(s.name for s in ctx['dive_systems']))

    _docx_heading(doc, 'Confirmation & Sign-off')
    _docx_signoff_field(doc, "Requester's Confirmation", ctx['requester_signoff'])
    _docx_signoff_field(doc, 'IT Officer Signature', ctx['it_officer_signoff'])

    _docx_heading(doc, "Requester's Feedback")
    if ctx['feedback_comment'] or ctx['feedback_rating']:
        rating = f' (Rating: {ctx["feedback_rating"]}/5)' if ctx['feedback_rating'] else ''
        doc.add_paragraph(f'{ctx["feedback_comment"] or "—"}{rating}')
    else:
        doc.add_paragraph('No feedback submitted yet.').runs[0].italic = True

    _docx_signoff_field(doc, "Requester's Signature", ctx['requester_feedback_signoff'])
    _docx_signoff_field(doc, 'IT Manager Signature', ctx['it_manager_signoff'])

    buf = BytesIO()
    doc.save(buf)
    response = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="{_filename("service_request_" + ticket.number)}.docx"'
    return response


def export_procurement_request_pdf(procurement_request, request):
    context = {'procurement_request': procurement_request}
    return _render_form_pdf_chromium(
        'reports/procurement_request_form_pdf.html', context, request,
        f'procurement_request_{procurement_request.pk}'
    )


def export_maintenance_pdf(schedule, request):
    from .report_registry import maintenance_form_sections
    context = maintenance_form_sections(schedule)
    return _render_form_pdf_chromium('reports/maintenance_form_pdf.html', context, request, f'maintenance_{context["schedule_code"]}')


def export_maintenance_docx(schedule):
    from .report_registry import maintenance_form_sections
    ctx = maintenance_form_sections(schedule)

    doc = Document()
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(10)

    _docx_letterhead(doc, 'HDG-IT-FRM-090', '1', timezone.now().strftime('%d %B %Y'), 'MAINTENANCE SCHEDULE REPORT', page='1 of 1')

    title = doc.add_heading(f'Maintenance Schedule — {ctx["schedule_code"]}', level=1)
    for run in title.runs:
        run.font.color.rgb = PRIMARY_RGB
    doc.add_paragraph(schedule.title).runs[0].italic = True

    _docx_heading(doc, 'Section 1 — Schedule Details')
    _docx_field(doc, 'Target Department(s)', ctx['department_display'])
    _docx_field(doc, 'Status', ctx['status_display'])
    _docx_field(doc, 'Scheduled Date', schedule.scheduled_date.strftime('%Y-%m-%d'))
    if schedule.start_time:
        _docx_field(doc, 'Time', f'{schedule.start_time.strftime("%H:%M")}' + (f' – {schedule.end_time.strftime("%H:%M")}' if schedule.end_time else ''))
    _docx_field(doc, 'Facility / Location', schedule.facility_location)
    if ctx['target_assets']:
        _docx_field(doc, 'Target Asset(s)', ', '.join(f'{a.name} ({a.tracking_id})' for a in ctx['target_assets']))
    if ctx['vendors']:
        _docx_field(doc, 'Third-Party Vendor(s)', ', '.join(v.name for v in ctx['vendors']))

    _docx_heading(doc, 'Section 2 — Description')
    doc.add_paragraph(schedule.description or '—')

    _docx_heading(doc, 'Section 3 — Assigned Personnel')
    if ctx['assignees']:
        for person in ctx['assignees']:
            doc.add_paragraph(f'• {person.get_full_name() or person.email}')
    else:
        doc.add_paragraph('Unassigned').runs[0].italic = True

    _docx_heading(doc, f'Section 4 — Checklist ({ctx["checklist_progress"]}% complete)')
    if ctx['checklist']:
        for item, done in ctx['checklist']:
            doc.add_paragraph(f'{"☑" if done else "☐"} {item}')
    else:
        doc.add_paragraph('No checklist items.').runs[0].italic = True

    _docx_heading(doc, 'Section 5 — Timeline')
    timeline_rows = [
        ('Created', schedule.created_at.strftime('%Y-%m-%d %H:%M')),
        ('Started', ctx['started_at'].strftime('%Y-%m-%d %H:%M') if ctx['started_at'] else 'Not started'),
        ('Completed', schedule.completed_at.strftime('%Y-%m-%d %H:%M') if schedule.completed_at else 'Not completed'),
    ]
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Table Grid'
    header_cells = table.rows[0].cells
    for cell, label in zip(header_cells, ('Stage', 'Timestamp')):
        cell.text = ''
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
    for stage, timestamp in timeline_rows:
        row_cells = table.add_row().cells
        row_cells[0].paragraphs[0].add_run(stage).bold = True
        row_cells[1].text = timestamp
    doc.add_paragraph()

    doc.add_page_break()
    multi_department = len(ctx['department_sections']) > 1
    _docx_heading(doc, 'Section 6 — Owner Confirmation by Department' if multi_department else 'Section 6 — Owner Confirmation')
    if ctx['department_sections']:
        for section in ctx['department_sections']:
            if multi_department:
                doc.add_paragraph(section['department_display']).runs[0].bold = True
            if section['confirmations']:
                conf_table = doc.add_table(rows=1, cols=4)
                conf_table.style = 'Table Grid'
                for cell, label in zip(conf_table.rows[0].cells, ('Asset', 'Status', 'Confirmed By', 'Confirmed At')):
                    cell.text = ''
                    run = cell.paragraphs[0].add_run(label)
                    run.bold = True
                for c in section['confirmations']:
                    row_cells = conf_table.add_row().cells
                    row_cells[0].text = f'{c.asset.name} ({c.asset.tracking_id})'
                    row_cells[1].text = c.get_status_display()
                    row_cells[2].text = c.confirmed_by.get_full_name() if c.confirmed_by else '—'
                    row_cells[3].text = c.confirmed_at.strftime('%Y-%m-%d %H:%M') if c.confirmed_at else '—'
                    if c.status == 'DISPUTED' and c.dispute_reason:
                        note_row = conf_table.add_row().cells
                        note_row[0].merge(note_row[3])
                        note_row[0].text = f'Dispute reason: {c.dispute_reason}'
                    elif c.notes:
                        note_row = conf_table.add_row().cells
                        note_row[0].merge(note_row[3])
                        note_row[0].text = f'Notes: {c.notes}'
                doc.add_paragraph()
            else:
                doc.add_paragraph('No target assets in this department.').runs[0].italic = True
    else:
        doc.add_paragraph('No target assets recorded for this schedule.').runs[0].italic = True

    buf = BytesIO()
    doc.save(buf)
    response = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="{_filename("maintenance_" + ctx["schedule_code"])}.docx"'
    return response


def _shade_cell(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)


def _weighted_column_widths(columns, rows, usable_width_in, min_in=0.75, max_in=2.3):
    """Word/LibreOffice both render docx tables with naive equal-width
    columns unless widths are stated explicitly — 'autofit' only kicks in
    once a human opens and nudges the table in Word itself. Estimate a
    reasonable width per column from header + a sample of cell content
    lengths, clip to a sane range, then rescale so the row still fills the
    page exactly."""
    sample_rows = rows[:200]
    weights = []
    for col in columns:
        content_len = max((len(str(r.get(col, ''))) for r in sample_rows), default=0)
        weights.append(max(len(col), content_len * 0.6, 6))
    raw = [usable_width_in * w / sum(weights) for w in weights]
    clipped = [min(max(w, min_in), max_in) for w in raw]
    scale = usable_width_in / sum(clipped)
    return [Inches(w * scale) for w in clipped]


def export_docx(rows, columns, title, filename_base, filter_summary='', **kwargs):
    doc = Document()
    normal = doc.styles['Normal']
    normal.font.name = 'Calibri'
    normal.font.size = Pt(9.5)

    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_height = Cm(21.0)
    section.page_width = Cm(29.7)
    section.left_margin = section.right_margin = Cm(1.5)
    section.top_margin = section.bottom_margin = Cm(1.5)
    usable_width_in = (section.page_width - section.left_margin - section.right_margin) / 914400

    generated_at = timezone.now()
    _docx_report_letterhead(doc, title, generated_at, filter_summary, len(rows), usable_width_in)

    table = doc.add_table(rows=1, cols=max(len(columns), 1))
    table.style = 'Table Grid'
    table.autofit = False

    widths = _weighted_column_widths(columns, rows, usable_width_in)

    header_cells = table.rows[0].cells
    for i, col in enumerate(columns):
        header_cells[i].text = col
        header_cells[i].width = widths[i]
        _shade_cell(header_cells[i], '0D9488')
        for p in header_cells[i].paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                r.font.size = Pt(9)

    for row_data in rows:
        cells = table.add_row().cells
        for i, col in enumerate(columns):
            cells[i].text = str(row_data.get(col, '—'))
            cells[i].width = widths[i]

    for i, w in enumerate(widths):
        table.columns[i].width = w

    from apps.accounts.models import ClientSettings
    client_settings = ClientSettings.objects.first()
    company_name = client_settings.company_name if client_settings else 'HydroDive'

    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run(
        f'Generated by {company_name} IT Service Management System — Confidential, for internal use only.'
    )
    footer_run.italic = True
    footer_run.font.size = Pt(7.5)
    footer_run.font.color.rgb = META_GRAY_RGB

    buf = BytesIO()
    doc.save(buf)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="{_filename(filename_base)}.docx"'
    return response


EXPORTERS = {
    'csv': export_csv,
    'excel': export_excel,
    'json': export_json,
    'pdf': export_pdf,
    'docx': export_docx,
}


def build_export_response(report_config, request, export_format, filter_summary=''):
    queryset = report_config.get_queryset(request)
    # Bulk row selection: if the report table's checkboxes selected specific
    # records, export only those — every report type's get_queryset()
    # returns a plain QuerySet keyed on its model's default pk, so pk__in
    # works uniformly here without touching any individual report type.
    ids = request.GET.getlist('ids')
    if ids:
        queryset = queryset.filter(pk__in=ids)
    rows = [report_config.row_from_obj(obj) for obj in queryset]
    columns = report_config.columns

    exporter = EXPORTERS.get(export_format)
    if not exporter:
        return HttpResponse('Invalid format', status=400)

    return exporter(
        rows, columns, report_config.label, report_config.slug,
        request=request, filter_summary=filter_summary,
    )
