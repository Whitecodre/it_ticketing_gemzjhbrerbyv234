# apps/organogram/urls.py
from django.urls import path
from . import views, api_views

app_name = 'organogram'

urlpatterns = [
    # System organogram (auto-generated from users)
    path('system/', views.system_org, name='system'),
    
    # Organization organogram (customizable with approval)
    path('organization/', views.org_view, name='org_view'),
    path('organization/list/', views.org_list, name='org_list'),
    path('organization/builder/', views.org_builder, name='org_builder'),
    path('organization/builder/<int:pk>/', views.org_builder, name='org_builder'),
    path('organization/preview/<int:pk>/', views.org_preview, name='org_preview'),
    path('organization/approvals/', views.org_approvals, name='org_approvals'),
    path('organization/history/', views.org_publish_history, name='org_history'),
    
    # API endpoints
    path('api/save-structure/', api_views.api_save_structure, name='api_save_structure'),
    path('api/submit-approval/', api_views.api_submit_approval, name='api_submit_approval'),
    path('api/approve/', api_views.api_approve, name='api_approve'),
    path('api/publish/', api_views.api_publish, name='api_publish'),
    path('api/pending-count/', views.api_pending_count, name='api_pending_count'),  # ✅ ADD THIS
]