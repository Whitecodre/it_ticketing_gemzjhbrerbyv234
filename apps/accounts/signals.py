from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from .models import UserProfile, LoginHistory, ClientSettings

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(user=instance)
    else:
        instance.profile.save()


def _client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@receiver(user_logged_in)
def record_login_history(sender, request, user, **kwargs):
    LoginHistory.objects.create(
        user=user,
        ip_address=_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        # An admin-created account has no password until the user sets one
        # on their first sign-in, so that first login row is effectively
        # their sign-up moment, not just another sign-in.
        is_first_login=not LoginHistory.objects.filter(user=user).exists(),
    )
    user.has_active_session = True
    user.save(update_fields=['has_active_session'])


@receiver(user_logged_out)
def clear_active_session(sender, request, user, **kwargs):
    # user is None if someone hits /logout/ while already logged out.
    if user is not None:
        user.has_active_session = False
        user.save(update_fields=['has_active_session'])


@receiver([post_save, post_delete], sender=ClientSettings)
def clear_client_settings_cache(sender, **kwargs):
    # Keeps apps.common.context_processors.client_settings' cache (which
    # serves every request) from showing stale branding after an edit.
    from apps.common.context_processors import CLIENT_SETTINGS_CACHE_KEY
    cache.delete(CLIENT_SETTINGS_CACHE_KEY)