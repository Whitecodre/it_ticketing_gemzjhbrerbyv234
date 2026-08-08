@echo off
:: run_sla_scheduler.bat - For Windows development

echo Starting SLA Scheduler...
python manage.py run_sla_scheduler --interval=5
pause