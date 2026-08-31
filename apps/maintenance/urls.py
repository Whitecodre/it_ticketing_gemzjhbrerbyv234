# apps/maintenance/urls.py
from django.urls import path
from . import views

app_name = 'maintenance'

urlpatterns = [
    # Main views
    path('', views.schedule_list, name='list'),
    path('create/', views.schedule_create, name='create'),
    path('<int:pk>/', views.schedule_detail, name='detail'),
    path('<int:pk>/edit/', views.schedule_edit, name='edit'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('calendar/day-events/', views.calendar_day_events, name='calendar_day_events'),
    path('checklist-templates/', views.checklist_templates_partial, name='checklist_templates_partial'),
    path('target-assets/', views.target_assets_partial, name='target_assets_partial'),

    # Status updates (HTMX)
    path('<int:pk>/status-modal/', views.schedule_status_modal, name='status_modal'),
    path('<int:pk>/update-status/', views.schedule_update_status, name='update_status'),
    
    # Per-asset owner confirmation (HTMX)
    path('<int:pk>/asset/<int:asset_pk>/confirm-modal/', views.asset_confirm_modal, name='asset_confirm_modal'),
    path('<int:pk>/asset/<int:asset_pk>/confirm/', views.asset_confirm, name='asset_confirm'),

    # OS backup status (Admin/Superadmin only, current-state, no schedule involved)
    path('assets/<int:asset_pk>/backup-status/', views.asset_backup_status_update, name='asset_backup_status_update'),
]