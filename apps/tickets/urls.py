from django.urls import path
from . import views

app_name = 'tickets'

urlpatterns = [
    path('new/', views.create_ticket, name='create'),
    path('<int:pk>/cancel/', views.cancel_ticket, name='cancel_ticket'),
    path('my/', views.my_ticket_list, name='my_list'),
    path('<int:pk>/', views.ticket_detail, name='detail'),
    path('unassigned/', views.unassigned_queue, name='unassigned'),
    path('assigned/', views.assigned_to_me, name='assigned_to_me'),
    path('claim/<int:pk>/', views.claim_ticket, name='claim_ticket'),
    path('<int:pk>/slideover/', views.agent_ticket_detail, name='slideover'),
    path('<int:pk>/conversation/', views.agent_ticket_conversation, name='conversation'),
    path('<int:pk>/comment-conversation/', views.add_comment_conversation, name='add_comment_conversation'),
    path('<int:pk>/update-status/', views.update_status, name='update_status'),
    path('<int:pk>/details-panel/', views.ticket_details_panel, name='details_panel'),
    path('<int:pk>/edit-subject/', views.edit_subject, name='edit_subject'),
    path('<int:pk>/assign-popover/', views.assign_popover, name='assign_popover'),
    path('<int:pk>/assign-to-me/', views.assign_to_me, name='assign_to_me'),
    path('<int:pk>/assign/<int:user_pk>/', views.assign_specific, name='assign_specific'),
    path('<int:ticket_pk>/followers/remove/<int:user_pk>/', views.remove_follower, name='remove_follower'),
    path('<int:ticket_pk>/followers/add-popover/', views.add_follower_popover, name='add_follower_popover'),
    path('<int:pk>/edit-group-popover/', views.edit_group_popover, name='edit_group_popover'),
    path('<int:pk>/edit-type-popover/', views.edit_type_popover, name='edit_type_popover'),
    path('<int:pk>/edit-priority-popover/', views.edit_priority_popover, name='edit_priority_popover'),
    path('<int:pk>/add-tag-popover/', views.add_tag_popover, name='add_tag_popover'),
    path('<int:pk>/remove-tag/<int:tag_pk>/', views.remove_tag, name='remove_tag'),
    path('macros/', views.macro_list, name='macro_list'),
    # path('bulk-action/', views.bulk_action, name='bulk_action'),
    path('team/queue/', views.team_queue, name='team_queue'),
    path('team/reassign/<int:pk>/', views.team_reassign, name='team_reassign'),
    path('audit/', views.audit_log, name='audit_log'),
    path('reports/', views.reports_dashboard, name='reports'),
    path('attachment/<int:pk>/preview/', views.attachment_preview, name='attachment_preview'),
    path('attachment/<int:pk>/', views.attachment_download, name='attachment_download'),
    # Resolution Confirmation & Feedback
    path('<int:pk>/resolve/', views.resolve_ticket, name='resolve_ticket'),
    path('<int:pk>/confirm-resolution/', views.confirm_resolution, name='confirm_resolution'),
    path('<int:pk>/feedback/', views.submit_feedback, name='submit_feedback'),

    path('catalogue/', views.catalogue, name='catalogue'),
    path('connectors/', views.connectors, name='connectors'),
    path('connectors/edit/<int:pk>/', views.connector_edit, name='connector_edit'),
    path('assets/', views.assets, name='assets'),
    path('assets/create-page/', views.asset_create_page, name='asset_create_page'),
    path('assets/<int:pk>/edit-page/', views.asset_edit_page, name='asset_edit_page'),
    path('assets/<int:pk>/reassign/', views.asset_reassign, name='asset_reassign'),
    path('assets/<int:pk>/reassign-modal/', views.asset_reassign_modal, name='asset_reassign_modal'),
    path('assets/<int:pk>/detail/', views.asset_detail, name='asset_detail'),
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
    # External trigger (optional - for cron jobs)
    # path('sla/trigger-external/', views.trigger_sla_processing_external, name='trigger_sla_external'),
    path('calendar/create/', views.calendar_create, name='calendar_create'),
    path('rule/create/', views.rule_create, name='rule_create'),
    path('rule/<int:pk>/delete/', views.rule_delete, name='rule_delete'),
    path('calendar/<int:pk>/delete/', views.calendar_delete, name='calendar_delete'),

    # MANAGER URLS
    path('manager/review/', views.manager_review_queue, name='manager_review_queue'),
    path('manager/review/<int:pk>/', views.manager_review_ticket, name='manager_review_ticket'),
    path('manager/review/count/', views.manager_review_count, name='manager_review_count'),

    # ASSET EXPORT AND IMPORT
    path('assets/export/', views.asset_export, name='asset_export'),
    path('assets/import/', views.asset_import, name='asset_import'),
    
    # ASSET FULFILLMENT
    path('assets/fulfill/<int:pk>/', views.fulfill_asset_request, name='fulfill_asset_request'),
    path('assets/available/', views.available_assets_for_fulfillment, name='available_assets_for_fulfillment'),
    path('assets/fulfill-modal/<int:pk>/', views.fulfill_asset_modal, name='fulfill_asset_modal'),

    # EXPORTABLES
    path('exportables/', views.exportables, name='exportables'),
    path('export/service-requests/', views.export_service_requests, name='export_service_requests'),
    path('export/incidents/', views.export_incidents, name='export_incidents'),

    # apps/tickets/urls.py - Add these to urlpatterns
    path('assets/<int:pk>/checkout-modal/', views.asset_checkout_modal, name='asset_checkout_modal'),
    path('assets/<int:pk>/checkout/', views.asset_checkout, name='asset_checkout'),
    path('assets/<int:pk>/checkin-modal/', views.asset_checkin_modal, name='asset_checkin_modal'),
    path('assets/<int:pk>/checkin/', views.asset_checkin, name='asset_checkin'),
    path('assets/<int:pk>/checkout-history/', views.asset_checkout_history, name='asset_checkout_history'),

]