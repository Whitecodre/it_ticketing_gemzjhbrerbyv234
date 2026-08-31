# apps/tickets/management/commands/process_asset_renewals.py
"""Single-pass command, run on the same schedule as process_sla/
send_renewal_reminders, that auto-renews renewable assets flagged
auto_renews=True once their next_renewal_date arrives — no admin action
needed. Assets with auto_renews=False are left alone; an admin actions
those manually via the "Mark as Renewed" button on the asset detail page,
which calls Asset.mark_renewed() the same way this command does."""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import role_of, notify_recipients_by_email
from apps.common.permissions import effective_role_name
from apps.tickets.models import Asset


class Command(BaseCommand):
    help = 'Auto-renew renewable assets flagged auto_renews=True whose next_renewal_date has arrived.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        due = Asset.objects.filter(
            category__is_renewable=True,
            auto_renews=True,
            next_renewal_date__isnull=False,
            next_renewal_date__lte=today,
        )

        candidates = User.objects.filter(
            Q(role__in=['ADMIN', 'SUPERADMIN']) | Q(roles__name__in=['ADMIN', 'SUPERADMIN']),
            is_active=True,
        ).distinct()
        recipients = [u for u in candidates if effective_role_name(u) in ('ADMIN', 'SUPERADMIN')]

        renewed_count = 0
        for asset in due:
            previous_date = asset.next_renewal_date
            cost_display = asset.renewal_cost if asset.renewal_cost is not None else "cost not set"
            asset.mark_renewed(actor=None, auto=True)
            renewed_count += 1

            if recipients:
                message = (
                    f'🔁 "{asset.name}" auto-renewed (was due {previous_date}) — {cost_display}. '
                    f'Next renewal {asset.next_renewal_date}.'
                )
                url = f'/tickets/assets/{asset.pk}/detail/'
                for recipient in recipients:
                    Notification.objects.create(
                        recipient=recipient,
                        role=role_of(recipient),
                        message=message,
                        url=url,
                        type=Notification.Type.GENERAL,
                    )
                notify_recipients_by_email(recipients, f'Auto-renewed: {asset.name}', message, url)

        if renewed_count:
            self.stdout.write(self.style.SUCCESS(f'Auto-renewed {renewed_count} asset(s).'))
        else:
            self.stdout.write('No assets due for auto-renewal.')
