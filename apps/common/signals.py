# apps/common/signals.py
import json
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings
from .models import Notification
from .utils import send_push_notification, notification_role_q, role_of

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Notification)
def broadcast_notification(sender, instance, created, **kwargs):
    if not created:
        return

    # A role-tagged notification only pops a live toast in the recipient's
    # browser while they're actively wearing the matching hat — the DB row
    # still exists for when they switch back (badge/dropdown/list already
    # filter on this via notification_role_q, which is why they're not
    # touched here). Push notifications are left unconditional below since
    # those are meant to reach the person out-of-band regardless of which
    # hat is on-screen right now.
    role_matches_active_hat = instance.role is None or instance.role == role_of(instance.recipient)

    # --- WebSocket broadcast (always attempt, handle errors) ---
    if role_matches_active_hat:
        try:
            channel_layer = get_channel_layer()
            group_name = f"user_{instance.recipient.pk}"

            # Scoped to the recipient's active role at push time, matching the
            # REST-polled badge count (unread_count in apps/common/views.py) so
            # the live-pushed number and the one you'd get from a refresh agree.
            unread_count = Notification.objects.filter(
                notification_role_q(instance.recipient),
                recipient=instance.recipient,
                is_read=False
            ).count()

            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    'type': 'send_notification',
                    'message': instance.message,
                    'url': instance.url,
                    'notification_id': instance.pk,
                    'notification_type': instance.type or 'general',
                    'unread_count': unread_count,
                }
            )
        except Exception as e:
            # Log error but don't break the flow (Redis may not be running)
            logger.warning(f"WebSocket broadcast skipped: {e}")

    # --- Push notifications (send always, but can be conditionally skipped) ---
    # By default, skip push in DEBUG unless TEST_PUSH=True
    send_push = True
    if settings.DEBUG and not getattr(settings, 'TEST_PUSH', False):
        send_push = False

    if send_push:
        try:
            result = send_push_notification(instance)
            if result['sent'] > 0:
                logger.info(f"Push sent to {result['sent']} devices for notification {instance.pk}")
            if result['expired'] > 0:
                logger.info(f"Removed {result['expired']} expired push subscriptions")
        except Exception as e:
            logger.error(f"Push notification failed: {e}")