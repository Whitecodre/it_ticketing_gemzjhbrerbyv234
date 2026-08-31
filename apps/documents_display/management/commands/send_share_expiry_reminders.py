# apps/documents_display/management/commands/send_share_expiry_reminders.py
"""Single-pass command, meant to run on the same schedule as
run_periodic_tasks, that reminds a share's creator (`shared_by`) 3 days
before a DocumentShare/FolderShare they granted is about to expire - so
they can extend or re-share it before the recipient silently loses access.
One-shot per share (expiry_reminder_sent), mirroring the renewal-reminder
pattern in apps/tickets/management/commands/send_renewal_reminders.py."""
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from apps.common.models import Notification
from apps.common.utils import role_of, notify_recipients_by_email
from apps.documents_display.models import DocumentShare, FolderShare, ShareAuditLog, log_share_event

REMINDER_WINDOW_DAYS = 3

# (model, target attr on the share, target's display-name attr, url name, url kwarg)
SHARE_KINDS = [
    (DocumentShare, 'document', 'title', 'documents_display:document_share', 'slug'),
    (FolderShare, 'folder', 'name', 'documents_display:folder_share', 'slug'),
]


class Command(BaseCommand):
    help = "Remind share creators 3 days before their document/folder shares expire."

    def handle(self, *args, **options):
        now = timezone.now()
        cutoff = now + timedelta(days=REMINDER_WINDOW_DAYS)
        sent_count = 0

        for model, target_attr, name_attr, url_name, url_kwarg in SHARE_KINDS:
            due = model.objects.filter(
                revoked_at__isnull=True,
                expiry_reminder_sent=False,
                expires_at__isnull=False,
                expires_at__gt=now,
                expires_at__lte=cutoff,
                shared_by__isnull=False,
            ).select_related('shared_by', target_attr)

            for share in due:
                target = getattr(share, target_attr)
                target_name = getattr(target, name_attr)
                url = reverse(url_name, kwargs={url_kwarg: getattr(target, url_kwarg)})
                message = (
                    f'Your share of "{target_name}" with {share.display_target} '
                    f'expires on {timezone.localtime(share.expires_at).strftime("%b %d, %Y")}.'
                )

                Notification.objects.create(
                    recipient=share.shared_by,
                    role=role_of(share.shared_by),
                    message=message,
                    url=url,
                    type=Notification.Type.GENERAL,
                )
                notify_recipients_by_email([share.shared_by], f'Share expiring soon: "{target_name}"', message, url)
                log_share_event(share, ShareAuditLog.Event.EXPIRY_REMINDER_SENT, detail=f'expires {share.expires_at.isoformat()}')

                share.expiry_reminder_sent = True
                share.save(update_fields=['expiry_reminder_sent'])
                sent_count += 1

        if sent_count:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} share expiry reminder(s).'))
        else:
            self.stdout.write('No share expiry reminders due.')
