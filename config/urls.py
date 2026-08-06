from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from apps.accounts.views import dashboard
from apps.common.views import service_worker
from apps.form_builder.views import form_redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('tickets/', include('apps.tickets.urls')),
    path('notifications/', include('apps.common.urls')),
    path('kb/', include('apps.knowledge_base.urls')),
    path('maintenance/', include('apps.maintenance.urls')),
    path('form-builder/', include('apps.form_builder.urls')),
    path('organogram/', include('apps.organogram.urls')),

    # Dynamic form redirects (for backward compatibility)
    path('incident/new/', form_redirect, {'slug': 'incident-report'}, name='incident_new'),
    path('service-request/new/', form_redirect, {'slug': 'service-request'}, name='service_request_new'),
    path('job-mobilization/new/', form_redirect, {'slug': 'job-mobilization'}, name='job_mobilization_new'),
    path('job-return/new/', form_redirect, {'slug': 'job-return'}, name='job_return_new'),
    path('feedback/new/', form_redirect, {'slug': 'feedback'}, name='feedback_new'),
    
    path('', dashboard, name='dashboard'),
    path('sw.js', service_worker, name='sw'),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)