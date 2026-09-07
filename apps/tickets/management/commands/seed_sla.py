from django.core.management.base import BaseCommand

from apps.tickets.models import SLA, EscalationRule, BusinessCalendar, Ticket


class Command(BaseCommand):
    help = (
        'Seeds standard SLA response/resolution targets, a default Mon-Fri '
        'business calendar, and default escalation rules for every '
        'priority (P1-P4) — get_or_create throughout, so re-running this '
        'never duplicates or clobbers values someone has already tuned via '
        'System Settings. Run after a fresh database (see start.sh) so a '
        'new deploy is testable without manually configuring SLA policy '
        'from scratch first.'
    )

    # (response_minutes, resolution_minutes) per priority — standard ITSM-style
    # targets: P1 fastest/tightest, P4 most relaxed. Business-hours-aware via
    # the calendar attached below, so these are working-time budgets, not
    # wall-clock.
    SLA_TARGETS = {
        Ticket.Priority.P1: (15, 240),      # 15m response / 4h resolution
        Ticket.Priority.P2: (30, 480),      # 30m response / 8h resolution
        Ticket.Priority.P3: (60, 1440),     # 1h response / 1 business day
        Ticket.Priority.P4: (120, 4320),    # 2h response / 3 business days
    }

    # threshold_percent -> (action_type, notify_role, reassign_to_role) per
    # timer_type. Mirrors process_sla.py's own create_default_escalation_rules
    # (response only) plus the resolution-side equivalents it doesn't create
    # on its own, so every priority gets the same graduated notify/reassign
    # ladder on both timers without needing a live breach to lazily create it.
    RESPONSE_RULES = [
        (75, 'notify', 'TEAM_LEAD', None),
        (90, 'notify', 'ADMIN', None),
        (100, 'reassign', None, 'TEAM_LEAD'),
    ]
    RESOLUTION_RULES = [
        (75, 'notify', 'TEAM_LEAD', None),
        (90, 'notify', 'ADMIN', None),
    ]

    def handle(self, *args, **options):
        calendar, cal_created = BusinessCalendar.objects.get_or_create(
            name='Standard Business Hours',
            defaults={
                'workdays': [0, 1, 2, 3, 4],  # Mon-Fri
                'holidays': [],
            }
        )
        if cal_created:
            self.stdout.write(self.style.SUCCESS('✅ Created "Standard Business Hours" calendar (Mon-Fri, 08:00-18:00)'))
        else:
            self.stdout.write('ℹ️  Business calendar already exists, leaving it as configured')

        for priority, (response_minutes, resolution_minutes) in self.SLA_TARGETS.items():
            sla, created = SLA.objects.get_or_create(
                priority=priority,
                defaults={
                    'response_minutes': response_minutes,
                    'resolution_minutes': resolution_minutes,
                    'calendar': calendar,
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'✅ Created SLA for {priority}: {response_minutes}m response / {resolution_minutes}m resolution'
                ))
            else:
                self.stdout.write(f'ℹ️  SLA for {priority} already exists, leaving it as configured')

            for timer_type, rules in (('response', self.RESPONSE_RULES), ('resolution', self.RESOLUTION_RULES)):
                for threshold_percent, action_type, notify_role, reassign_to_role in rules:
                    rule, rule_created = EscalationRule.objects.get_or_create(
                        priority=priority, timer_type=timer_type, threshold_percent=threshold_percent,
                        defaults={
                            'action_type': action_type,
                            'notify_role': notify_role,
                            'reassign_to_role': reassign_to_role,
                        }
                    )
                    if rule_created:
                        self.stdout.write(
                            f'   ✅ {priority} {timer_type} @ {threshold_percent}%: {action_type}'
                            f'{" -> " + notify_role if notify_role else ""}{" -> " + reassign_to_role if reassign_to_role else ""}'
                        )

        self.stdout.write(self.style.SUCCESS('✅ SLA seeding complete'))
