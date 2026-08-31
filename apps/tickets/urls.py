from django.urls import path
from . import views
from . import views_reports
from . import views_drafts
from . import views_settings
from . import views_macros

app_name = 'tickets'

urlpatterns = [
    path('new/', views.create_ticket, name='create'),
    path('draft/save/', views_drafts.save_draft, name='save_draft'),
    path('draft/get/', views_drafts.get_draft, name='get_draft'),
    path('draft/discard/', views_drafts.discard_draft, name='discard_draft'),
    path('<int:pk>/cancel/', views.cancel_ticket, name='cancel_ticket'),
    path('my/', views.my_ticket_list, name='my_list'),
    path('<int:pk>/', views.ticket_detail, name='detail'),
    path('unassigned/', views.unassigned_queue, name='unassigned'),
    path('unassigned/pending-count/', views.unassigned_pending_count, name='unassigned_pending_count'),
    path('assigned/', views.assigned_to_me, name='assigned_to_me'),
    path('claim/<int:pk>/', views.claim_ticket, name='claim_ticket'),
    path('<int:pk>/slideover/', views.agent_ticket_detail, name='slideover'),
    path('<int:pk>/conversation/', views.agent_ticket_conversation, name='conversation'),
    path('<int:pk>/comment-conversation/', views.add_comment_conversation, name='add_comment_conversation'),
    path('<int:pk>/details-panel/', views.ticket_details_panel, name='details_panel'),
    path('<int:pk>/edit-subject/', views.edit_subject, name='edit_subject'),
    path('<int:pk>/assign-popover/', views.assign_popover, name='assign_popover'),
    path('<int:pk>/assign-to-me/', views.assign_to_me, name='assign_to_me'),
    path('<int:pk>/assign/<int:user_pk>/', views.assign_specific, name='assign_specific'),
    path('macros/', views.macro_list, name='macro_list'),
    # path('bulk-action/', views.bulk_action, name='bulk_action'),
    path('team/queue/', views.team_queue, name='team_queue'),
    path('team/reassign/<int:pk>/', views.team_reassign, name='team_reassign'),
    path('audit/', views.audit_log, name='audit_log'),
    path('reports/', views.reports_dashboard, name='reports'),
    path('reports/tickets/', views.reports_ticket_list, name='reports_ticket_list'),
    path('admin/resolved-requests/', views.resolved_service_requests, name='resolved_service_requests'),
    path('attachment/<int:pk>/preview/', views.attachment_preview, name='attachment_preview'),
    path('attachment/<int:pk>/', views.attachment_download, name='attachment_download'),
    path('requester/<int:pk>/profile-modal/', views.requester_profile_modal, name='requester_profile_modal'),
    # Resolution Confirmation & Feedback
    path('<int:pk>/resolve/', views.resolve_ticket, name='resolve_ticket'),
    path('<int:pk>/approve-incident-report/', views.approve_incident_report, name='approve_incident_report'),
    path('<int:pk>/confirm-resolution/', views.confirm_resolution, name='confirm_resolution'),
    path('<int:pk>/feedback/', views.submit_feedback, name='submit_feedback'),

    path('catalogue/', views.catalogue, name='catalogue'),
    path('connectors/', views.connectors, name='connectors'),
    path('connectors/edit/<int:pk>/', views.connector_edit, name='connector_edit'),
    path('assets/', views.assets, name='assets'),
    path('my-assets/', views.my_assets, name='my_assets'),
    path('my-assets/pending-count/', views.my_assets_pending_count, name='my_assets_pending_count'),
    path('assets/create-page/', views.asset_create_page, name='asset_create_page'),
    path('assets/<int:pk>/edit-page/', views.asset_edit_page, name='asset_edit_page'),
    path('assets/<int:pk>/reassign/', views.asset_reassign, name='asset_reassign'),
    path('assets/<int:pk>/reassign-modal/', views.asset_reassign_modal, name='asset_reassign_modal'),
    path('assets/<int:pk>/detail/', views.asset_detail, name='asset_detail'),
    path('assets/<int:pk>/mark-renewed/', views.asset_mark_renewed, name='asset_mark_renewed'),
    path('assets/<int:pk>/adjust-stock/', views.asset_adjust_stock, name='asset_adjust_stock'),
    path('assets/<int:pk>/attachments/upload/', views.asset_attachment_upload, name='asset_attachment_upload'),
    path('assets/attachments/<int:pk>/delete/', views.asset_attachment_delete, name='asset_attachment_delete'),
    path('assets/<int:pk>/scrap-request/', views.asset_scrap_request, name='asset_scrap_request'),
    path('assets/<int:pk>/scrap-request-modal/', views.scrap_request_modal, name='scrap_request_modal'),
    path('assets/<int:pk>/scrap-approve/', views.asset_scrap_approve, name='asset_scrap_approve'),
    path('assets/<int:pk>/scrap-approve-modal/', views.scrap_approve_modal, name='scrap_approve_modal'),
    path('assets/calculate-warranty/', views.asset_calculate_warranty, name='asset_calculate_warranty'),
    path('<int:pk>/request-remote-session/', views.request_remote_session, name='request_remote_session'),
    path('remote-session/<int:session_pk>/', views.remote_session_detail, name='remote_session_detail'),
    path('remote-sessions/pending-count/', views.remote_session_pending_count, name='remote_session_pending_count'),
    path('remote-sessions/', views.remote_sessions_list, name='remote_sessions_list'),
    path('escalated/', views.escalated_tickets, name='escalated_tickets'),
    path('escalated/pending-count/', views.escalated_pending_count, name='escalated_pending_count'),
    path('escalated/<int:pk>/reassign/', views.reassign_escalated, name='reassign_escalated'),
    path('escalated/<int:pk>/reassign-modal/', views.escalated_reassign_modal, name='escalated_reassign_modal'),
    path('escalated/<int:pk>/return-to-pool/', views.return_escalated_to_pool, name='return_escalated_to_pool'),
    # future: detail, list

    # SLA URLS
    path('sla/', views.sla_list, name='sla_management'),
    path('sla/create/', views.sla_create, name='sla_create'),
    path('<int:pk>/sla-badge/', views.sla_badge, name='sla_badge'),
    path('sla/<int:pk>/delete/', views.sla_delete, name='sla_delete'),
    path('sla/trigger/', views.trigger_sla_processing, name='trigger_sla'),
    path('sla/cleanup/', views.trigger_cleanup, name='trigger_cleanup'),
    # External triggers for a scheduled caller with no long-lived process of
    # its own (e.g. a Cloudflare Cron Trigger) — see the views' docstrings
    # for the shared-secret auth pattern (SLA_TRIGGER_SECRET env var).
    path('cron/trigger-sla/', views.trigger_sla_processing_external, name='trigger_sla_external'),
    path('cron/trigger-periodic-jobs/', views.trigger_periodic_jobs_external, name='trigger_periodic_jobs_external'),
    path('calendar/create/', views.calendar_create, name='calendar_create'),
    path('calendar/add-modal/', views.calendar_add_modal, name='calendar_add_modal'),
    path('calendar/<int:pk>/edit-modal/', views.calendar_edit_modal, name='calendar_edit_modal'),
    path('calendar/<int:pk>/edit/', views.calendar_edit, name='calendar_edit'),
    path('rule/create/', views.rule_create, name='rule_create'),
    path('rule/add-modal/', views.rule_add_modal, name='rule_add_modal'),
    path('rule/<int:pk>/edit-modal/', views.rule_edit_modal, name='rule_edit_modal'),
    path('rule/<int:pk>/edit/', views.rule_edit, name='rule_edit'),
    path('rule/<int:pk>/delete/', views.rule_delete, name='rule_delete'),
    path('calendar/<int:pk>/delete/', views.calendar_delete, name='calendar_delete'),

    # MANAGER URLS
    path('manager/review/', views.manager_review_queue, name='manager_review_queue'),
    path('manager/review/<int:pk>/', views.manager_review_ticket, name='manager_review_ticket'),
    path('manager/review/count/', views.manager_review_count, name='manager_review_count'),
    path('manager/review/history/', views.manager_review_history, name='manager_review_history'),

    # ASSET IMPORT (upload -> preview -> commit)
    path('assets/import/', views.asset_import, name='asset_import'),
    path('assets/import/<int:pk>/preview/', views.asset_import_preview, name='asset_import_preview'),
    path('assets/import/<int:pk>/commit/', views.asset_import_commit, name='asset_import_commit'),
    path('assets/import/<int:pk>/discard/', views.asset_import_discard, name='asset_import_discard'),

    # ASSET FULFILLMENT
    path('assets/pending-fulfillment/', views.pending_asset_fulfillment_list, name='pending_asset_fulfillment'),
    path('assets/pending-fulfillment-count/', views.pending_asset_fulfillment_count, name='pending_asset_fulfillment_count'),
    path('assets/fulfill/<int:pk>/', views.fulfill_asset_request, name='fulfill_asset_request'),
    path('assets/available/', views.available_assets_for_fulfillment, name='available_assets_for_fulfillment'),
    path('assets/fulfill-modal/<int:pk>/', views.fulfill_asset_modal, name='fulfill_asset_modal'),

    # VENDOR PROCUREMENT (assets not yet in inventory)
    path('procurement/', views.procurement_list, name='procurement_list'),
    path('procurement/ticket/<int:pk>/request/', views.procurement_request_create, name='procurement_request_create'),
    path('procurement/reorder/<int:asset_pk>/', views.procurement_reorder_create, name='procurement_reorder_create'),
    path('procurement/<int:pk>/mark-ordered/', views.procurement_mark_ordered, name='procurement_mark_ordered'),
    path('procurement/<int:pk>/cancel/', views.procurement_cancel, name='procurement_cancel'),
    path('procurement/<int:pk>/receive-modal/', views.procurement_receive_modal, name='procurement_receive_modal'),
    path('procurement/<int:pk>/receive/', views.procurement_receive, name='procurement_receive'),
    path('procurement/<int:pk>/export/', views.procurement_export_pdf, name='procurement_export_pdf'),

    # EXPORTABLES (enterprise report builder — one page + one export endpoint
    # per data type, generic over apps.tickets.report_registry.REPORT_TYPES).
    # Deliberately NOT under /reports/ — the Analytics "Reports" sidebar link
    # active-checks on '/reports/' in request.path, so sharing that prefix
    # made it light up on every Exportables page too.
    path('exportables/', views_reports.report_hub, name='report_hub'),
    path('exportables/<slug:report_type>/', views_reports.report_builder, name='report_builder'),
    path('exportables/<slug:report_type>/download/', views_reports.export_report, name='export_report'),
    path('exportables/<slug:report_type>/<int:pk>/', views_reports.report_record_detail, name='report_record_detail'),
    path('exportables/<slug:report_type>/<int:pk>/download/', views_reports.export_report_record, name='export_report_record'),

    # SYSTEM SETTINGS
    path('settings/', views_settings.system_settings, name='system_settings'),
    path('settings/<slug:resource>/create/', views_settings.settings_resource_create, name='settings_resource_create'),
    path('settings/<slug:resource>/<int:pk>/update/', views_settings.settings_resource_update, name='settings_resource_update'),
    path('settings/<slug:resource>/<int:pk>/delete/', views_settings.settings_resource_delete, name='settings_resource_delete'),
    path('settings/<slug:resource>/<int:pk>/activate/', views_settings.settings_resource_activate, name='settings_resource_activate'),
    path('settings/pending-count/', views.pending_settings_approvals_count, name='pending_settings_approvals_count'),
    path('settings/branding/', views_settings.branding_update, name='branding_update'),

    # MACROS
    path('macros/manage/', views_macros.macro_management, name='macro_management'),
    path('macros/create/', views_macros.macro_create, name='macro_create'),
    path('macros/<int:pk>/update/', views_macros.macro_update, name='macro_update'),
    path('macros/<int:pk>/delete/', views_macros.macro_delete, name='macro_delete'),
    path('macros/bulk-delete/', views_macros.macro_bulk_delete, name='macro_bulk_delete'),

    # apps/tickets/urls.py - Add these to urlpatterns
    path('assets/<int:pk>/checkout-modal/', views.asset_checkout_modal, name='asset_checkout_modal'),
    path('assets/<int:pk>/checkout/', views.asset_checkout, name='asset_checkout'),
    path('assets/<int:pk>/checkin-modal/', views.asset_checkin_modal, name='asset_checkin_modal'),
    path('assets/<int:pk>/checkin/', views.asset_checkin, name='asset_checkin'),
    path('assets/<int:pk>/checkout-history/', views.asset_checkout_history, name='asset_checkout_history'),

    # ASSET CUSTODY TWO-STEP CONFIRMATION (My Assets side)
    path('assets/<int:pk>/checkout/accept/', views.asset_checkout_accept, name='asset_checkout_accept'),
    path('assets/<int:pk>/checkout/dispute/', views.asset_checkout_dispute, name='asset_checkout_dispute'),
    path('assets/<int:pk>/request-return-modal/', views.asset_request_return_modal, name='asset_request_return_modal'),
    path('assets/<int:pk>/request-return/', views.asset_request_return, name='asset_request_return'),
    path('assets/<int:pk>/cancel-return-request/', views.asset_cancel_return_request, name='asset_cancel_return_request'),
    path('assets/pending-returns/', views.pending_asset_returns_list, name='pending_asset_returns'),
    path('assets/pending-returns-count/', views.pending_asset_returns_count, name='pending_asset_returns_count'),

    # MOBILIZATION / DEMOBILIZATION
    path('mobilizations/', views.mobilizations, name='mobilizations'),
    path('mobilizations/new/', views.mobilization_create_page, name='mobilization_create_page'),
    path('mobilizations/create/', views.mobilization_create, name='mobilization_create'),
    path('mobilizations/available-assets/', views.mobilization_available_assets, name='mobilization_available_assets'),
    path('mobilizations/autopick-assets/', views.mobilization_autopick_assets, name='mobilization_autopick_assets'),
    path('mobilizations/job-lookup/', views.job_mobilization_lookup, name='job_mobilization_lookup'),
    path('mobilizations/<int:pk>/', views.mobilization_detail, name='mobilization_detail'),
    path('mobilizations/<int:pk>/audit/', views.mobilization_audit_report, name='mobilization_audit_report'),
    path('mobilizations/<int:pk>/audit/export/', views.mobilization_audit_export, name='mobilization_audit_export'),
    path('mobilizations/items/<int:item_pk>/demobilize-modal/', views.mobilization_item_demobilize_modal, name='mobilization_item_demobilize_modal'),
    path('mobilizations/items/<int:item_pk>/demobilize/', views.mobilization_item_demobilize, name='mobilization_item_demobilize'),

    # MOBILIZATION REQUESTER RECEIPT TWO-STEP CONFIRMATION
    path('mobilizations/items/<int:item_pk>/accept/', views.mobilization_item_accept, name='mobilization_item_accept'),
    path('mobilizations/items/<int:item_pk>/dispute/', views.mobilization_item_dispute, name='mobilization_item_dispute'),
    path('<int:pk>/receipt-confirm-modal/', views.receipt_confirm_modal, name='receipt_confirm_modal'),
    path('<int:pk>/receipt-confirm-batch/', views.mobilization_items_confirm_batch, name='mobilization_items_confirm_batch'),
    path('mobilizations/<int:pk>/demobilize-all-modal/', views.mobilization_demobilize_all_modal, name='mobilization_demobilize_all_modal'),
    path('mobilizations/<int:pk>/demobilize-all/', views.mobilization_demobilize_all, name='mobilization_demobilize_all'),
    path('mobilizations/<int:pk>/extend-date-modal/', views.mobilization_extend_date_modal, name='mobilization_extend_date_modal'),
    path('mobilizations/<int:pk>/extend-date/', views.mobilization_extend_date, name='mobilization_extend_date'),

    # DEMOBILIZATION (requester self-report handshake)
    path('demobilizations/', views.demobilization_list, name='demobilization_list'),
    path('demobilizations/pending-count/', views.demobilization_pending_count, name='demobilization_pending_count'),
    path('demobilizations/request-batch/', views.mobilization_items_request_demobilize_batch, name='mobilization_items_request_demobilize_batch'),
    path('mobilizations/items/<int:item_pk>/cancel-demobilize-request/', views.mobilization_item_cancel_demobilize_request, name='mobilization_item_cancel_demobilize_request'),
    path('mobilizations/pending/', views.pending_demobilizations_list, name='pending_demobilizations_list'),
    path('mobilizations/pending/count/', views.pending_demobilizations_count, name='pending_demobilizations_count'),

]