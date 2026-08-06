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
    
    # Status updates (HTMX)
    path('<int:pk>/status-modal/', views.schedule_status_modal, name='status_modal'),
    path('<int:pk>/update-status/', views.schedule_update_status, name='update_status'),
    
    # Confirmation (HTMX)
    path('<int:pk>/confirm-modal/', views.schedule_confirm_modal, name='confirm_modal'),
    path('<int:pk>/confirm/', views.schedule_confirm, name='confirm'),
]