@echo off
:: run_periodic_tasks.bat - For Windows development

echo Starting periodic task runner...
python manage.py run_periodic_tasks --interval=5
pause
