# apps/form_builder/urls.py

from django.urls import path
from . import views_deprecated

app_name = 'form_builder'

urlpatterns = [
    # All Form Builder URLs now show deprecation message
    path('', views_deprecated.form_builder_deprecated, name='list'),
    path('create/', views_deprecated.form_builder_deprecated, name='create'),
    path('<int:pk>/', views_deprecated.form_builder_deprecated, name='detail'),
    path('<int:pk>/edit/', views_deprecated.form_builder_deprecated, name='edit'),
    path('<int:pk>/delete/', views_deprecated.form_builder_deprecated, name='delete'),
    path('<int:pk>/preview/', views_deprecated.form_builder_deprecated, name='preview'),
    path('builder/', views_deprecated.form_builder_deprecated, name='builder'),
    path('builder/<int:pk>/', views_deprecated.form_builder_deprecated, name='builder_edit'),
    path('submissions/', views_deprecated.form_builder_deprecated, name='submissions'),
    path('submissions/<int:pk>/', views_deprecated.form_builder_deprecated, name='submission_detail'),
    path('render/<slug:slug>/', views_deprecated.form_redirect_deprecated, name='render'),
    path('redirect/<slug:slug>/', views_deprecated.form_redirect_deprecated, name='redirect'),
]