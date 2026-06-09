# ruff: noqa
"""
integrity_scheduler.py — Background threads for periodic FIM scans.

Three daemon threads run independently:
  periodic_scan   every 5 min  — files whose next_check_at has passed
  recovery_scan   every 15 min — files with an open alert
  escalation      every 1 hr   — auto-escalate stale high/critical alerts
"""
import threading
import time
from datetime import datetime, timezone, timedelta


def _periodic_scan(app_instance) -> None:
    with app_instance.app_context():
        try:
            from app import db, File
            from integrity_engine import check_single_file, run_alert_pipeline

            now = datetime.now(timezone.utc)
            files = File.query.filter(
                File.monitoring_enabled == True,
                db.or_(
                    File.next_check_at == None,
                    File.next_check_at <= now,
                ),
            ).all()

            for file_rec in files:
                try:
                    result = check_single_file(file_id=file_rec.id, triggered_by='scheduler')
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


def _recovery_scan(app_instance) -> None:
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
                    result = check_single_file(file_id=file_rec.id, triggered_by='scheduler')
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


def _escalation_check(app_instance) -> None:
    with app_instance.app_context():
        try:
            from app import db, IntegrityAlert

            cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            stale = IntegrityAlert.query.filter(
                IntegrityAlert.status == 'open',
                IntegrityAlert.severity.in_(['high', 'critical']),
                IntegrityAlert.raised_at <= cutoff,
                IntegrityAlert.assigned_to_id == None,
            ).all()

            now = datetime.now(timezone.utc)
            for alert in stale:
                alert.status = 'escalated'
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


def start_scheduler(app_instance) -> None:
    """
    Spawn three daemon threads for FIM background jobs.
    Each thread sleeps first (warm-up), then loops with time.sleep between runs.
    Daemon=True means threads die automatically when the main process exits.
    """

    def periodic_scan_loop():
        time.sleep(30)
        while True:
            try:
                _periodic_scan(app_instance)
            except Exception as exc:
                app_instance.logger.error('[FIM] periodic loop error: %s', exc)
            time.sleep(300)

    def recovery_scan_loop():
        time.sleep(60)
        while True:
            try:
                _recovery_scan(app_instance)
            except Exception as exc:
                app_instance.logger.error('[FIM] recovery loop error: %s', exc)
            time.sleep(900)

    def escalation_loop():
        time.sleep(120)
        while True:
            try:
                _escalation_check(app_instance)
            except Exception as exc:
                app_instance.logger.error('[FIM] escalation loop error: %s', exc)
            time.sleep(3600)

    threading.Thread(target=periodic_scan_loop, daemon=True, name='fim-periodic').start()
    threading.Thread(target=recovery_scan_loop, daemon=True, name='fim-recovery').start()
    threading.Thread(target=escalation_loop, daemon=True, name='fim-escalation').start()
    app_instance.logger.info('[FIM] Scheduler started — 3 background threads')
