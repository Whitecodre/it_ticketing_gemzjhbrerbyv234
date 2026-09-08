from django.core.management.base import BaseCommand

from apps.tickets.models import SLA, EscalationRule, BusinessCalendar, Ticket


class Command(BaseCommand):
    help = (
        'Seeds/enforces standard SLA response/resolution targets, a default '
        'Mon-Fri business calendar, and default escalation rules for every '
        'priority (P1-P4). Unlike a typical get_or_create seed script, this '
        'always re-links every SLA to the standard calendar and resets its '
        'response/resolution minutes and escalation-rule ladder back to the '
        'canonical values below — SLA policy here is meant to be config-as-'
        'code, not something drifted via ad-hoc System Settings edits during '
        'testing. Any escalation rule not part of the canonical ladder for a '
        'priority (e.g. a stray one added by hand) is removed. Safe to run '
        'repeatedly.'
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
            self.stdout.write(self.style.SUCCESS('[OK] Created "Standard Business Hours" calendar (Mon-Fri, 08:00-18:00)'))
        else:
            self.stdout.write('[INFO] "Standard Business Hours" calendar already exists, leaving its own fields as configured')

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
                    f'[OK] Created SLA for {priority}: {response_minutes}m response / {resolution_minutes}m resolution, linked to {calendar.name}'
                ))
            else:
                changed = []
                if sla.calendar_id != calendar.id:
                    sla.calendar = calendar
                    changed.append('calendar')
                if sla.response_minutes != response_minutes:
                    sla.response_minutes = response_minutes
                    changed.append('response_minutes')
                if sla.resolution_minutes != resolution_minutes:
                    sla.resolution_minutes = resolution_minutes
                    changed.append('resolution_minutes')
                if changed:
                    sla.save(update_fields=changed)
                    self.stdout.write(self.style.SUCCESS(
                        f'[OK] SLA for {priority}: reset {", ".join(changed)} to canonical values '
                        f'({response_minutes}m response / {resolution_minutes}m resolution, {calendar.name})'
                    ))
                else:
                    self.stdout.write(f'[INFO] SLA for {priority} already matches canonical values')

            for timer_type, rules in (('response', self.RESPONSE_RULES), ('resolution', self.RESOLUTION_RULES)):
                canonical_thresholds = {threshold_percent for threshold_percent, *_ in rules}

                # Drop any rule for this priority/timer that isn't part of
                # the canonical ladder (e.g. a stray one-off rule added by
                # hand during testing).
                stray = EscalationRule.objects.filter(
                    priority=priority, timer_type=timer_type,
                ).exclude(threshold_percent__in=canonical_thresholds)
                stray_count = stray.count()
                if stray_count:
                    stray.delete()
                    self.stdout.write(
                        f'   [OK] {priority} {timer_type}: removed {stray_count} non-canonical escalation rule(s)'
                    )

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
                            f'   [OK] {priority} {timer_type} @ {threshold_percent}%: {action_type}'
                            f'{" -> " + notify_role if notify_role else ""}{" -> " + reassign_to_role if reassign_to_role else ""}'
                        )
                    elif (rule.action_type, rule.notify_role, rule.reassign_to_role) != (action_type, notify_role, reassign_to_role):
                        rule.action_type = action_type
                        rule.notify_role = notify_role
                        rule.reassign_to_role = reassign_to_role
                        rule.save(update_fields=['action_type', 'notify_role', 'reassign_to_role'])
                        self.stdout.write(
                            f'   [OK] {priority} {timer_type} @ {threshold_percent}%: reset to canonical action'
                        )

        self.stdout.write(self.style.SUCCESS('[OK] SLA seeding complete'))
