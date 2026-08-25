from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from apps.accounts.views import dashboard
from apps.common.views import service_worker
from django.http import HttpResponse

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('tickets/', include('apps.tickets.urls')),
    path('notifications/', include('apps.common.urls')),
    path('kb/', include('apps.knowledge_base.urls')),
    path('maintenance/', include('apps.maintenance.urls')),
    path('organogram/', include('apps.organogram.urls')),
    path('documents_display/', include('apps.documents_display.urls')),
    path('tinymce/', include('tinymce.urls')),
    path('health/', lambda request: HttpResponse('OK'), name='health'),

    path('', dashboard, name='dashboard'),
    path('sw.js', service_worker, name='sw'),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)