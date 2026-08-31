# apps/tickets/management/commands/run_periodic_tasks.py
"""Renamed from run_sla_scheduler — despite the old name, this loop always
ran 4 unrelated jobs (process_sla, send_maintenance_reminders,
process_remote_session_expiry, send_renewal_reminders), not just SLA
processing. See apps/tickets/periodic_tasks.py for the shared job list,
also used by scheduler.py (the Azure WebJob entry point) so both stay
in sync."""

import time
import logging
from datetime import datetime
from django.core.management.base import BaseCommand
import schedule
import sys

from apps.tickets.periodic_tasks import run_periodic_jobs

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run periodic background jobs (SLA processing, maintenance reminders, remote session expiry, renewal reminders) on a schedule'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=1,
            help='Interval in minutes between processing runs (default: 5)'
        )
        parser.add_argument(
            '--once',
            action='store_true',
            help='Run once and exit (for testing)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        run_once = options['once']

        self.stdout.write(self.style.SUCCESS(
            f'🔄 Periodic task runner started. Processing every {interval} minutes...'
        ))
        self.stdout.write(f'📅 Started at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

        def process():
            run_periodic_jobs(stdout=self.stdout, stderr=self.stderr)

        if run_once:
            process()
            return

        # Run immediately on start
        process()

        schedule.every(interval).minutes.do(process)

        self.stdout.write(self.style.SUCCESS(
            '✅ Scheduler running. Press Ctrl+C to stop.'
        ))

        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n🛑 Scheduler stopped by user.'))
            sys.exit(0)
