# apps/documents_display/urls.py

from django.urls import path
from . import views

app_name = 'documents_display'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Categories
    path('category/<slug:slug>/', views.category_detail, name='category_detail'),
    
    # Documents
    path('document/<slug:slug>/', views.document_detail, name='document_detail'),
    path('document/<slug:slug>/viewer/', views.document_viewer, name='document_viewer'),
    path('document/<slug:slug>/edit/', views.document_edit, name='document_edit'),
    path('document/<slug:slug>/download/', views.document_download, name='document_download'),
    path('document/<slug:slug>/delete/', views.document_delete, name='document_delete'),
    path('document/<slug:slug>/history/', views.document_history, name='document_history'),
    path('document/<slug:slug>/serve/', views.document_serve_file, name='document_serve_file'),

    # Sharing
    path('document/<slug:slug>/share/', views.document_share, name='document_share'),
    path('document/<slug:slug>/share/<int:share_id>/revoke/', views.document_share_revoke, name='document_share_revoke'),
    path('share/<str:token>/', views.document_share_open, name='document_share_open'),

    # Create
    path('create/', views.document_create, name='document_create'),
]