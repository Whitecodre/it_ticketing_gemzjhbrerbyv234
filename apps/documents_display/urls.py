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
    path('document/<slug:slug>/versions/<int:version_id>/download/', views.document_version_download, name='document_version_download'),
    path('document/<slug:slug>/delete/', views.document_delete, name='document_delete'),
    path('document/<slug:slug>/history/', views.document_history, name='document_history'),
    path('document/<slug:slug>/serve/', views.document_serve_file, name='document_serve_file'),

    # Sharing
    path('document/<slug:slug>/share/', views.document_share, name='document_share'),
    path('document/<slug:slug>/share/<int:share_id>/revoke/', views.document_share_revoke, name='document_share_revoke'),
    path('share/<str:token>/', views.document_share_open, name='document_share_open'),
    path('share/<str:token>/external/', views.document_share_external, name='document_share_external'),
    path('share/<str:token>/external/serve/', views.document_share_external_serve, name='document_share_external_serve'),
    path('share/<str:token>/external/download/', views.document_share_external_download, name='document_share_external_download'),

    # Create
    path('create/', views.document_create, name='document_create'),
    path('bulk-upload/', views.document_bulk_create, name='document_bulk_create'),

    # Folders
    path('folders/', views.folder_list, name='folder_list'),
    path('folder/<slug:slug>/', views.folder_detail, name='folder_detail'),
    path('folder/<slug:slug>/add-documents/', views.folder_add_documents, name='folder_add_documents'),
    path('folder/<slug:slug>/remove-document/<int:document_id>/', views.folder_remove_document, name='folder_remove_document'),
    path('folder/<slug:slug>/delete/', views.folder_delete, name='folder_delete'),
    path('folder/<slug:slug>/share/', views.folder_share, name='folder_share'),
    path('folder/<slug:slug>/share/<int:share_id>/revoke/', views.folder_share_revoke, name='folder_share_revoke'),
    path('folder-share/<str:token>/', views.folder_share_open, name='folder_share_open'),
    path('folder-share/<str:token>/view/', views.folder_shared_view, name='folder_shared_view'),
    path('folder-share/<str:token>/external/', views.folder_share_external, name='folder_share_external'),
    path('folder-share/<str:token>/external/document/<int:document_id>/serve/', views.folder_share_external_serve, name='folder_share_external_serve'),
    path('folder-share/<str:token>/external/document/<int:document_id>/download/', views.folder_share_external_download, name='folder_share_external_download'),
]