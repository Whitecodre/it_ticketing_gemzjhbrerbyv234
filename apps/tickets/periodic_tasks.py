# apps/tickets/periodic_tasks.py
"""Single source of truth for the periodic background job list — previously
duplicated verbatim between apps/tickets/management/commands/run_periodic_tasks.py
(local/Windows dev) and scheduler.py (the Azure WebJob entry point), which
meant adding or changing a job required remembering to edit both or they'd
silently drift apart.

Despite the historical name "run_sla_scheduler", this loop runs several
unrelated jobs, not just SLA processing — process_sla was just the first
one, and everything else (maintenance reminders, remote session expiry,
renewal reminders, document/folder share expiry reminders) got tacked onto
the same already-running long-lived process rather than standing up
separate infrastructure for each.
"""
from datetime import datetime
from django.core.management import call_command


def run_periodic_jobs(stdout=None, stderr=None):
    """Runs every periodic job once, isolating failures so one job crashing
    doesn't block the others. `stdout`/`stderr` are optional file-like
    writers (e.g. a management Command's self.stdout) — defaults to print()
    so this also works from a plain script like scheduler.py."""
    write_out = stdout.write if stdout else print
    write_err = stderr.write if stderr else print

    jobs = ['process_sla', 'send_maintenance_reminders', 'process_remote_session_expiry', 'process_asset_renewals', 'send_renewal_reminders', 'send_share_expiry_reminders']
    for job in jobs:
        try:
            start_time = datetime.now()
            write_out(f'⏳ [{start_time.strftime("%H:%M:%S")}] Running {job}...')
            call_command(job, verbosity=0)
            duration = (datetime.now() - start_time).total_seconds()
            write_out(f'✅ [{datetime.now().strftime("%H:%M:%S")}] {job} completed in {duration:.2f}s')
        except Exception as e:
            write_err(f'❌ [{datetime.now().strftime("%H:%M:%S")}] {job} failed: {str(e)}')
            import traceback
            write_err(traceback.format_exc())
