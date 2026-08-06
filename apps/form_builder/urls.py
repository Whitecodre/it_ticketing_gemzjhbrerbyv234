# apps/form_builder/urls.py

from django.urls import path
from . import views

app_name = 'form_builder'

urlpatterns = [
    # Form management
    path('', views.form_list, name='list'),
    path('builder/', views.form_builder, name='builder'),
    path('builder/<int:pk>/', views.form_builder, name='builder'),
    path('save/', views.form_save, name='save'),
    path('preview/<int:pk>/', views.form_preview, name='preview'),
    path('delete/<int:pk>/', views.form_delete, name='delete'),
    path('duplicate/<int:pk>/', views.form_duplicate, name='duplicate'),

    path('settings/<int:pk>/', views.form_settings, name='settings'),
    path('settings/<int:pk>/save/', views.form_settings_save, name='settings_save'),
    
    # Create modal
    path('create-modal/', views.form_create_modal, name='create_modal'),
    
    # Public form render
    path('render/<slug:slug>/', views.form_render, name='render'),

    path('redirect/<slug:slug>/', views.form_redirect, name='form_redirect'),
]