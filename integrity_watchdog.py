# ruff: noqa
"""
integrity_watchdog.py — Real-time filesystem watcher for vault_uploads/.

Detects unauthorised on-disk modifications (outside the normal upload/delete
flow) and immediately triggers an integrity check + alert pipeline.
"""
import os
import queue
import threading

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------

class FIMEventHandler(FileSystemEventHandler):
    """
    Pushes (event_type, stored_filename) tuples into a queue.
    Only non-directory modify / delete / move events are forwarded.
    New-file creation is intentionally ignored — uploads go through the
    normal app route and capture_baseline() handles them.
    """

    def __init__(self, event_queue: queue.Queue) -> None:
        super().__init__()
        self._q = event_queue

    def on_modified(self, event):
        if not event.is_directory:
            self._q.put(('modified', os.path.basename(event.src_path)))

    def on_deleted(self, event):
        if not event.is_directory:
            self._q.put(('deleted', os.path.basename(event.src_path)))

    def on_moved(self, event):
        # Treat a rename / move out of the watched dir as a deletion
        if not event.is_directory:
            self._q.put(('deleted', os.path.basename(event.src_path)))


# ---------------------------------------------------------------------------
# Observer factory
# ---------------------------------------------------------------------------

def start_watchdog(watch_path: str, event_queue: queue.Queue) -> Observer:
    """
    Schedule a non-recursive watchdog Observer on *watch_path*.
    The Observer thread is marked daemon so it exits with the process.
    Returns the started Observer instance.
    """
    handler  = FIMEventHandler(event_queue)
    observer = Observer()
    observer.schedule(handler, watch_path, recursive=False)
    observer.daemon = True
    observer.start()
    return observer


# ---------------------------------------------------------------------------
# Event-consumer worker
# ---------------------------------------------------------------------------

def _event_worker(event_queue: queue.Queue, app_instance) -> None:
    """
    Background daemon thread.
    Drains the event queue and runs check_single_file() + run_alert_pipeline()
    for every filesystem event.  Runs until the process exits.
    """
    from integrity_engine import check_single_file, run_alert_pipeline

    while True:
        try:
            event_type, stored_name = event_queue.get(timeout=2)
        except queue.Empty:
            continue

        with app_instance.app_context():
            try:
                from app import db, File

                file_rec = File.query.filter_by(
                    stored_name=stored_name,
                    monitoring_enabled=True,
                ).first()

                if file_rec is None:
                    continue  # file not in DB or monitoring disabled

                result = check_single_file(
                    file_id=file_rec.id,
                    triggered_by='watchdog',
                )

                if result['status'] not in ('ok', 'skip'):
                    run_alert_pipeline(file_rec, result)

                db.session.commit()

            except Exception as exc:
                app_instance.logger.error(
                    '[watchdog-worker] %s %s — %s',
                    event_type, stored_name, exc,
                )
                try:
                    from app import db as _db
                    _db.session.rollback()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Public bootstrap
# ---------------------------------------------------------------------------

def start_event_worker(app_instance) -> tuple:
    """
    Create the event queue, spin up the watchdog Observer, and start the
    consumer daemon thread.  Returns (Observer, Queue).
    Safe to call once at application startup.
    """
    eq       = queue.Queue()
    observer = start_watchdog(app_instance.config['UPLOAD_FOLDER'], eq)

    worker = threading.Thread(
        target=_event_worker,
        args=(eq, app_instance),
        name='fim-watchdog-worker',
        daemon=True,
    )
    worker.start()

    app_instance.logger.info(
        '[FIM] Watchdog watching: %s', app_instance.config['UPLOAD_FOLDER']
    )
    return observer, eq
