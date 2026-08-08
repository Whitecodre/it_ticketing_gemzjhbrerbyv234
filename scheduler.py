#!/usr/bin/env python
# scheduler.py - Production entry point for Azure

import os
import sys
import time
import schedule
from datetime import datetime
from django.core.management import call_command

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

# Initialize Django
import django
django.setup()

def process_sla():
    """Run the SLA processing command."""
    try:
        start_time = datetime.now()
        print(f'⏳ [{start_time.strftime("%H:%M:%S")}] Running SLA processing...')
        call_command('process_sla', verbosity=0)
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f'✅ [{end_time.strftime("%H:%M:%S")}] SLA processing completed in {duration:.2f}s')
    except Exception as e:
        print(f'❌ [{datetime.now().strftime("%H:%M:%S")}] SLA processing failed: {str(e)}')
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print(f'🔄 SLA Scheduler started. Processing every 5 minutes...')
    print(f'📅 Started at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    
    # Run immediately on start
    process_sla()
    
    # Schedule every 5 minutes
    schedule.every(5).minutes.do(process_sla)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n🛑 Scheduler stopped by user.')