Part 2: Azure Deployment
Option A: Azure App Service with WebJob (Recommended)
Step 1: Create the WebJob folder structure

text
webjob_sla/
├── run.py
├── settings.job
└── requirements.txt (optional)
Step 2: Create webjob_sla/run.py

python
# webjob_sla/run.py
import os
import sys
import time
import schedule
from datetime import datetime

# Add project to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# Set Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

# Initialize Django
import django
django.setup()

from django.core.management import call_command

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
    print(f'🔄 SLA Scheduler started at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    
    # Run immediately on start
    process_sla()
    
    # Schedule every 5 minutes
    schedule.every(5).minutes.do(process_sla)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print('🛑 Scheduler stopped')
Step 3: Create webjob_sla/settings.job

json
{
    "schedule": "0 */5 * * * *",
    "is_singleton": true
}
Step 4: Deploy WebJob to Azure

Using Azure CLI:

bash
# Zip the webjob
cd webjob_sla
zip -r ../webjob_sla.zip *
cd ..

# Deploy to Azure
az webapp webjob continuous deploy \
  --resource-group "your-resource-group" \
  --name "your-app-name" \
  --webjob-name "sla-processor" \
  --slot-name "production" \
  --source-path "webjob_sla.zip"
Using Azure Portal:

Go to your App Service in Azure Portal

Navigate to WebJobs

Click Add

Name: sla-processor

Upload the webjob_sla.zip file

Type: Continuous

Click OK

Using VS Code:

Install Azure App Service extension

Right-click on your App Service

Select Deploy to WebJob

Choose the webjob_sla folder

Name: sla-processor

Type: Continuous

