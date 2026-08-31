#!/usr/bin/env python
# scheduler.py - Production entry point for Azure

import os
import time
import schedule
from datetime import datetime

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

# Initialize Django
import django
django.setup()

from apps.tickets.periodic_tasks import run_periodic_jobs

if __name__ == '__main__':
    print('🔄 Periodic task runner started. Processing every 5 minutes...')
    print(f'📅 Started at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # Run immediately on start
    run_periodic_jobs()

    # Schedule every 5 minutes
    schedule.every(5).minutes.do(run_periodic_jobs)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n🛑 Scheduler stopped by user.')
