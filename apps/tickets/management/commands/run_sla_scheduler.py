# apps/tickets/management/commands/run_sla_scheduler.py

import time
import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from django.core.management import call_command
import schedule
import sys

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run SLA processing on a schedule (every 5 minutes)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=5,
            help='Interval in minutes between SLA processing runs (default: 5)'
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
            f'🔄 SLA Scheduler started. Processing every {interval} minutes...'
        ))
        self.stdout.write(f'📅 Started at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        
        def process_sla():
            try:
                start_time = datetime.now()
                self.stdout.write(f'⏳ [{start_time.strftime("%H:%M:%S")}] Running SLA processing...')

                # Run the SLA processing command
                call_command('process_sla', verbosity=0)

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                self.stdout.write(self.style.SUCCESS(
                    f'✅ [{end_time.strftime("%H:%M:%S")}] SLA processing completed in {duration:.2f}s'
                ))

            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f'❌ [{datetime.now().strftime("%H:%M:%S")}] SLA processing failed: {str(e)}'
                ))
                # Log the full error for debugging
                import traceback
                self.stderr.write(traceback.format_exc())

            try:
                call_command('send_maintenance_reminders', verbosity=0)
            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f'❌ [{datetime.now().strftime("%H:%M:%S")}] Maintenance reminders failed: {str(e)}'
                ))
        
        # If --once flag, run once and exit
        if run_once:
            process_sla()
            return
        
        # Run immediately on start
        process_sla()
        
        # Schedule the job
        schedule.every(interval).minutes.do(process_sla)
        
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