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
from django.core.cache import cache
from django.core.management import call_command


PERIODIC_JOBS_LOCK_KEY = 'tickets:periodic_jobs:lock'

# process_sla can be triggered two ways in production: as the first job in
# the batch below, or directly via trigger_sla_processing_external (a
# separate, faster-interval cron endpoint some deployments use so SLA
# breach checks run more often than the other jobs need to). This lock is
# keyed separately from PERIODIC_JOBS_LOCK_KEY and shared by both entry
# points, so the two crons can never run process_sla concurrently even
# though they're otherwise on independent schedules with independent locks.
SLA_JOB_LOCK_KEY = 'tickets:process_sla:lock'
SLA_JOB_LOCK_TIMEOUT = 180  # generous multiple of a normal run; just a deadlock backstop


def run_sla_job_locked(write_out=None, write_err=None):
    """Runs process_sla under SLA_JOB_LOCK_KEY, skipping (not blocking) if
    another trigger is already mid-run. Returns True if it ran, False if
    skipped. Shared by run_periodic_jobs below and
    trigger_sla_processing_external so both respect the same lock."""
    write_out = write_out or print
    write_err = write_err or print
    if not cache.add(SLA_JOB_LOCK_KEY, 'running', timeout=SLA_JOB_LOCK_TIMEOUT):
        write_out(f'[SKIP] [{datetime.now().strftime("%H:%M:%S")}] process_sla already running via another trigger; skipping.')
        return False
    try:
        start_time = datetime.now()
        write_out(f'[RUN] [{start_time.strftime("%H:%M:%S")}] Running process_sla...')
        call_command('process_sla', verbosity=0)
        duration = (datetime.now() - start_time).total_seconds()
        write_out(f'[OK] [{datetime.now().strftime("%H:%M:%S")}] process_sla completed in {duration:.2f}s')
        return True
    except Exception as e:
        write_err(f'[FAIL] [{datetime.now().strftime("%H:%M:%S")}] process_sla failed: {str(e)}')
        import traceback
        write_err(traceback.format_exc())
        return True
    finally:
        cache.delete(SLA_JOB_LOCK_KEY)


def run_periodic_jobs(stdout=None, stderr=None):
    """Runs every periodic job once, isolating failures so one job crashing
    doesn't block the others. A short-lived cache lock prevents overlapping
    external triggers from running the same job list simultaneously.

    `stdout`/`stderr` are optional file-like writers (e.g. a management
    Command's self.stdout) — defaults to print() so this also works from a
    plain script like scheduler.py."""
    write_out = stdout.write if stdout else print
    write_err = stderr.write if stderr else print

    # If another instance is already running the periodic job set, skip this
    # invocation rather than piling up duplicate SLA/renewal/expiry work.
    if not cache.add(PERIODIC_JOBS_LOCK_KEY, 'running', timeout=300):
        write_out(f'[SKIP] [{datetime.now().strftime("%H:%M:%S")}] Periodic jobs already running; skipping duplicate trigger.')
        return

    try:
        run_sla_job_locked(write_out, write_err)

        jobs = ['send_maintenance_reminders', 'process_remote_session_expiry', 'process_asset_renewals', 'send_renewal_reminders', 'send_share_expiry_reminders']
        for job in jobs:
            try:
                start_time = datetime.now()
                write_out(f'[RUN] [{start_time.strftime("%H:%M:%S")}] Running {job}...')
                call_command(job, verbosity=0)
                duration = (datetime.now() - start_time).total_seconds()
                write_out(f'[OK] [{datetime.now().strftime("%H:%M:%S")}] {job} completed in {duration:.2f}s')
            except Exception as e:
                write_err(f'[FAIL] [{datetime.now().strftime("%H:%M:%S")}] {job} failed: {str(e)}')
                import traceback
                write_err(traceback.format_exc())
    finally:
        cache.delete(PERIODIC_JOBS_LOCK_KEY)
