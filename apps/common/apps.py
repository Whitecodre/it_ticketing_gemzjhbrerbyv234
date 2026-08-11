from django.apps import AppConfig
from django.conf import settings


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.common'

    def ready(self):
        import apps.common.signals

        if settings.DEBUG:
            self._disable_static_file_caching()

    def _disable_static_file_caching(self):
        """
        `manage.py runserver` serves /static/ via StaticFilesHandler, which
        overrides get_response() to call its serve() directly — bypassing
        the whole middleware chain, not just skipping it for that path. So
        a middleware can't add cache headers here; the actual FileResponse
        has to be patched at the source. Combined with development.py's
        plain (unhashed) STATICFILES_STORAGE and no Cache-Control header
        otherwise, a browser was free to keep serving a stale cached
        global.js/theme.css indefinitely per its own heuristics — edits
        only showed up after a hard refresh, never on normal navigation.
        Dev-only: gated on settings.DEBUG, never touches production.
        """
        from django.views import static as static_view

        original_serve = static_view.serve

        def serve_without_cache(request, path, document_root=None, show_indexes=False):
            response = original_serve(request, path, document_root=document_root, show_indexes=show_indexes)
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            return response

        static_view.serve = serve_without_cache