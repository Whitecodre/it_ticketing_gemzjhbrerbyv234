# apps/organogram/urls.py
from django.urls import path
from . import views

app_name = 'organogram'

urlpatterns = [
    # System organogram (auto-generated from users)
    path('system/', views.system_org, name='system'),
    path('system/print/', views.system_org_print, name='system_print'),
]
