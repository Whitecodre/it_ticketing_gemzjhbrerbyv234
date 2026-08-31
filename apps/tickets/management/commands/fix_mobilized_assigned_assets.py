from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.tickets.models import Asset, AssetLog, MobilizationItem

User = get_user_model()


class Command(BaseCommand):
    """One-off data fix for a bug in the mobilization asset picker: before
    it excluded assets with `assigned_to` set, an admin could mobilize an
    asset that was still permanently assigned to someone (e.g. their office
    printer), leaving it showing as 'Mobilized' on that person's My Assets
    page even though it isn't with them anymore.

    The asset really is out at the job (a real admin action, real physical
    state) — so the fix is to clear assigned_to, not to undo the
    mobilization. status and the MobilizationItem are left untouched.
    """

    help = 'Clear assigned_to on assets that are mobilized to a job while still permanently assigned to someone'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually make the change. Without this flag, only reports what would change.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']

        affected_asset_ids = (
            MobilizationItem.objects
            .filter(demobilized_at__isnull=True, asset__assigned_to__isnull=False)
            .values_list('asset_id', flat=True)
            .distinct()
        )
        assets = Asset.objects.filter(pk__in=affected_asset_ids).select_related('assigned_to')

        if not assets:
            self.stdout.write(self.style.SUCCESS('No affected assets found.'))
            return

        system_user = User.objects.filter(is_superuser=True).first()

        for asset in assets:
            previous_holder = asset.assigned_to
            self.stdout.write(
                f'{"Would clear" if not apply_changes else "Clearing"} assigned_to on '
                f'{asset.tracking_id} ({asset.name}) — currently assigned to '
                f'{previous_holder.get_full_name() or previous_holder.email}'
            )
            if apply_changes:
                asset.assigned_to = None
                asset.save(update_fields=['assigned_to'])
                AssetLog.objects.create(
                    asset=asset,
                    action=AssetLog.Action.UNASSIGNED,
                    actor=system_user,
                    details={
                        'from': previous_holder.get_full_name() or previous_holder.email,
                        'reason': 'Data fix: asset was mobilized to a job while still permanently assigned '
                                  '(picker now excludes assigned assets from mobilization going forward)',
                    },
                )

        count = assets.count()
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f'\nFixed {count} asset(s).'))
        else:
            self.stdout.write(self.style.WARNING(f'\n{count} asset(s) would be fixed. Re-run with --apply to commit.'))
