from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # apps/common/urls.py
    path('push/test/', views.test_push, name='test_push'),      
    path('unread-count/', views.unread_count, name='unread_count'),
    path('list/', views.list_notifications, name='list'),
    path('all/', views.notifications_page, name='page'),
    path('mark-read/<int:pk>/', views.mark_read, name='mark_read'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
    path('ws-init/', views.websocket_init_data, name='ws_init'),
    path('push/save/', views.save_push_subscription, name='save_push_subscription'),
    path('push/delete/', views.delete_push_subscription, name='delete_push_subscription'),
]