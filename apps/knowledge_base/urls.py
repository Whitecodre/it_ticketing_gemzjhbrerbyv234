from django.urls import path
from . import views

app_name = 'kb'

urlpatterns = [
    path('manage/', views.kb_management, name='management'),
    path('create/', views.article_create, name='create'),
    path('<int:pk>/edit/', views.article_edit, name='edit'),
    path('<int:pk>/submit-review/', views.article_submit_review, name='submit_review'),
    path('<int:pk>/publish/', views.article_publish, name='publish'),
    path('<int:pk>/archive/', views.article_archive, name='archive'),
    path('', views.kb_portal, name='portal'),
    path('article/<slug:slug>/', views.kb_article_detail, name='article_detail'),
    path('<int:pk>/feedback/', views.kb_feedback, name='feedback'),
    path('convert/<int:ticket_pk>/', views.convert_ticket_to_kb, name='convert_ticket'),

    # NEW: KB suggestions for ticket creation
    path('suggestions/', views.kb_suggestions_ajax, name='suggestions'),

    # Version history & revert
    path('<int:pk>/history/', views.article_history, name='history'),
    path('<int:pk>/version/<int:version_pk>/', views.article_version_detail, name='version_detail'),
    path('<int:pk>/revert/<int:version_pk>/', views.article_revert, name='revert'),
    # Autocomplete
    path('tag-autocomplete/', views.tag_autocomplete, name='tag_autocomplete'),
]