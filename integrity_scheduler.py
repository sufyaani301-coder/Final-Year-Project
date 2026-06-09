# ruff: noqa
"""
integrity_scheduler.py — APScheduler background jobs for periodic FIM scans.

Three jobs run in separate threads inside the APScheduler BackgroundScheduler:

  fim_periodic   (every 5 min)  — check all files whose next_check_at has passed
  fim_recovery   (every 15 min) — re-check files that currently have an open alert
  fim_escalation (every 1 hr)   — auto-escalate stale high/critical alerts
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval    import IntervalTrigger
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Job: periodic scan
# ---------------------------------------------------------------------------

def _periodic_scan(app_instance) -> None:
    """
    Query File rows whose next_check_at <= now (or NULL) and monitoring is on.
    Runs check_single_file() for each, then run_alert_pipeline() if needed.
    """
    with app_instance.app_context():
        try:
            from app import db, File
            from integrity_engine import check_single_file, run_alert_pipeline

            now   = datetime.now(timezone.utc)
            files = File.query.filter(
                File.monitoring_enabled == True,
                db.or_(
                    File.next_check_at == None,
                    File.next_check_at <= now,
                ),
            ).all()

            for file_rec in files:
                try:
                    result = check_single_file(
                        file_id=file_rec.id,
                        triggered_by='scheduler',
                    )
                    if result['status'] not in ('ok', 'skip'):
                        run_alert_pipeline(file_rec, result)
                    db.session.commit()
                except Exception as exc:
                    app_instance.logger.error(
                        '[scheduler] periodic_scan file %d: %s', file_rec.id, exc
                    )
                    db.session.rollback()

        except Exception as exc:
            app_instance.logger.error('[scheduler] periodic_scan fatal: %s', exc)


# ---------------------------------------------------------------------------
# Job: recovery scan
# ---------------------------------------------------------------------------

def _recovery_scan(app_instance) -> None:
    """
    Re-check every file that has at least one open alert.
    If the file has recovered (hash matches again) the alert is not
    auto-closed here — an analyst must do that — but the status is updated.
    """
    with app_instance.app_context():
        try:
            from app import db, File, IntegrityAlert
            from integrity_engine import check_single_file, run_alert_pipeline

            file_ids = (
                db.session.query(IntegrityAlert.file_id)
                .filter(IntegrityAlert.status == 'open')
                .distinct()
                .all()
            )
            file_ids = [r[0] for r in file_ids]

            for fid in file_ids:
                file_rec = File.query.get(fid)
                if not file_rec or not file_rec.monitoring_enabled:
                    continue
                try:
                    result = check_single_file(
                        file_id=file_rec.id,
                        triggered_by='scheduler',
                    )
                    if result['status'] not in ('ok', 'skip'):
                        run_alert_pipeline(file_rec, result)
                    db.session.commit()
                except Exception as exc:
                    app_instance.logger.error(
                        '[scheduler] recovery_scan file %d: %s', fid, exc
                    )
                    db.session.rollback()

        except Exception as exc:
            app_instance.logger.error('[scheduler] recovery_scan fatal: %s', exc)


# ---------------------------------------------------------------------------
# Job: escalation
# ---------------------------------------------------------------------------

def _escalation_check(app_instance) -> None:
    """
    Promote HIGH / CRITICAL alerts to 'escalated' when they have been open
    for more than 1 hour with no analyst assignment.
    """
    with app_instance.app_context():
        try:
            from app import db, IntegrityAlert

            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            stale  = IntegrityAlert.query.filter(
                IntegrityAlert.status == 'open',
                IntegrityAlert.severity.in_(['high', 'critical']),
                IntegrityAlert.raised_at <= cutoff,
                IntegrityAlert.assigned_to_id == None,
            ).all()

            now = datetime.now(timezone.utc)
            for alert in stale:
                alert.status       = 'escalated'
                alert.escalated_at = now

            if stale:
                db.session.commit()
                app_instance.logger.warning(
                    '[scheduler] auto-escalated %d alert(s)', len(stale)
                )

        except Exception as exc:
            app_instance.logger.error('[scheduler] escalation_check fatal: %s', exc)
            try:
                from app import db as _db
                _db.session.rollback()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Public bootstrap
# ---------------------------------------------------------------------------

def start_scheduler(app_instance) -> BackgroundScheduler:
    """
    Build and start an APScheduler BackgroundScheduler with the three FIM jobs.
    Returns the running scheduler (keep a reference to prevent GC).
    Safe to call once at application startup.
    """
    scheduler = BackgroundScheduler(timezone='UTC')

    scheduler.add_job(
        _periodic_scan,
        trigger=IntervalTrigger(minutes=5),
        args=[app_instance],
        id='fim_periodic',
        name='FIM Periodic Scan',
        replace_existing=True,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        _recovery_scan,
        trigger=IntervalTrigger(minutes=15),
        args=[app_instance],
        id='fim_recovery',
        name='FIM Recovery Scan',
        replace_existing=True,
        misfire_grace_time=120,
    )

    scheduler.add_job(
        _escalation_check,
        trigger=IntervalTrigger(hours=1),
        args=[app_instance],
        id='fim_escalation',
        name='FIM Alert Escalation',
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    app_instance.logger.info('[FIM] Scheduler started (periodic/recovery/escalation)')
    return scheduler
