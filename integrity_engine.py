# ruff: noqa
"""
integrity_engine.py — Core FIM functions.
Imported by integrity_scheduler.py and integrity_watchdog.py.
All functions that touch the database must be called inside a Flask app context.
"""
import hashlib
import os
import time
import threading
from datetime import datetime, timezone, timedelta

HASH_BUFFER = 65536  # 64 KB chunks

# ---------------------------------------------------------------------------
# Low-level hashing
# ---------------------------------------------------------------------------

def hash_file(filepath: str) -> tuple[str, int, int]:
    """
    Compute SHA-256 of a file in streaming chunks.
    Returns (hex_digest, size_bytes, duration_ms).
    Raises FileNotFoundError, PermissionError, OSError.
    """
    sha = hashlib.sha256()
    total = 0
    t0 = time.monotonic()
    with open(filepath, 'rb') as fh:
        while chunk := fh.read(HASH_BUFFER):
            sha.update(chunk)
            total += len(chunk)
    ms = int((time.monotonic() - t0) * 1000)
    return sha.hexdigest(), total, ms


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

_SEVERITY_SCORES = {'info': 0, 'low': 1, 'medium': 2, 'high': 3, 'critical': 4}

_CRITICAL_EXTS = {'.exe', '.dll', '.so', '.sh', '.bat', '.ps1',
                  '.vbs', '.cmd', '.py', '.php', '.rb', '.pl', '.jar'}
_HIGH_EXTS     = {'.docx', '.xlsx', '.pdf', '.zip', '.rar',
                  '.db', '.sql', '.env', '.config', '.key', '.pem', '.pfx'}
_LOW_EXTS      = {'.txt', '.csv', '.log', '.md', '.png',
                  '.jpg', '.jpeg', '.gif', '.mp3', '.mp4', '.bmp'}


def classify_severity(file_rec, check, result: dict) -> str:
    """
    Multi-factor severity scoring.
    file_rec : File ORM object
    check    : IntegrityCheck ORM object
    result   : dict from check_single_file()
    Returns one of: 'info'|'low'|'medium'|'high'|'critical'
    """
    # Lazy import to avoid circular dependency at module load time
    from app import IntegrityAlert, db

    score = 0
    ext = ('.' + file_rec.original_name.rsplit('.', 1)[-1].lower()
           if '.' in file_rec.original_name else '')

    # Factor 1: file type risk
    if ext in _CRITICAL_EXTS:
        score += 4
    elif ext in _HIGH_EXTS:
        score += 2
    elif ext not in _LOW_EXTS:
        score += 1

    # Factor 2: double extension attack (.report.pdf.exe)
    parts = file_rec.original_name.split('.')
    if len(parts) > 2 and parts[-1].lower() in {'exe', 'bat', 'sh', 'ps1', 'cmd', 'vbs'}:
        score += 4

    # Factor 3: real-time detection (watchdog is faster than scheduler)
    if check.triggered_by == 'watchdog':
        score += 1

    # Factor 4: check status
    if check.status == 'missing':
        score += 3
    elif check.status == 'tampered':
        score += 2

    # Factor 5: repeat offender
    if file_rec.alert_count >= 3:
        score += 3
    elif file_rec.alert_count >= 1:
        score += 1

    # Factor 6: bulk event (3+ alerts raised in last 5 min)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    try:
        recent = IntegrityAlert.query.filter(
            IntegrityAlert.raised_at >= cutoff
        ).count()
        if recent >= 5:
            score += 4
        elif recent >= 3:
            score += 2
    except Exception:
        pass

    # Factor 7: size delta
    exp = result.get('expected_size') or 0
    fnd = result.get('current_size')  or 0
    if exp > 0:
        delta_pct = abs(fnd - exp) / exp * 100
        if delta_pct > 50:
            score += 2
        elif delta_pct > 10:
            score += 1

    if score >= 8:
        severity = 'critical'
    elif score >= 5:
        severity = 'high'
    elif score >= 3:
        severity = 'medium'
    elif score >= 1:
        severity = 'low'
    else:
        severity = 'info'

    # Policy minimum override
    try:
        policy = file_rec.policy
        if policy:
            pol_min = _SEVERITY_SCORES.get(policy.severity_default, 3)
            if _SEVERITY_SCORES[severity] < pol_min:
                severity = policy.severity_default
    except Exception:
        pass

    return severity


def classify_alert_type(file_rec, check) -> str:
    if check.status == 'missing':
        return 'file_missing'
    parts = file_rec.original_name.split('.')
    if len(parts) > 2 and parts[-1].lower() in {'exe', 'bat', 'sh', 'ps1', 'cmd'}:
        return 'double_extension'
    if file_rec.alert_count >= 2:
        return 'repeated_tampering'
    return 'hash_mismatch'


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------

def capture_baseline(file_rec, user, reason: str = 'upload'):
    """
    Compute hash and write an IntegrityBaseline row.
    Supersedes any existing current baseline for this file.
    Must be called inside Flask app context.
    Returns the new IntegrityBaseline instance (not yet committed).
    """
    from app import db, IntegrityBaseline, app as flask_app

    filepath = os.path.join(flask_app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    try:
        hex_digest, size_bytes, _ = hash_file(filepath)
    except Exception as exc:
        flask_app.logger.error('baseline capture failed for %s: %s', file_rec.stored_name, exc)
        return None

    # Supersede old baseline
    old = IntegrityBaseline.query.filter_by(
        file_id=file_rec.id, is_current=True
    ).first()
    if old:
        old.supersede(user, note=f'Superseded by new {reason}')

    baseline = IntegrityBaseline(
        file_id         = file_rec.id,
        sha256_hash     = hex_digest,
        file_size_bytes = size_bytes,
        is_current      = True,
        captured_by_id  = user.id if user else None,
        capture_reason  = reason,
    )
    db.session.add(baseline)

    # Stamp the file record
    now = datetime.now(timezone.utc)
    policy   = file_rec.policy
    interval = policy.check_interval_mins if policy else 60
    file_rec.current_status  = 'ok'
    file_rec.last_checked_at = now
    file_rec.next_check_at   = now + timedelta(minutes=interval)
    file_rec.file_hash       = hex_digest  # keep legacy column in sync

    return baseline


# ---------------------------------------------------------------------------
# Core check function (used by both scheduler and watchdog)
# ---------------------------------------------------------------------------

def check_single_file(file_id: int, triggered_by: str = 'scheduler',
                      triggered_by_user_id: int = None) -> dict:
    """
    Re-hash a file and compare against its current baseline.
    Writes an IntegrityCheck row and updates File columns.
    Does NOT commit — caller must commit.
    Returns a result dict; call run_alert_pipeline() if status != 'ok'.
    """
    from app import db, File, IntegrityBaseline, IntegrityCheck, app as flask_app

    file_rec = File.query.get(file_id)
    if not file_rec:
        return {'status': 'skip', 'reason': 'not_in_db'}

    baseline = IntegrityBaseline.query.filter_by(
        file_id=file_id, is_current=True
    ).first()
    if not baseline:
        return {'status': 'skip', 'reason': 'no_baseline'}

    filepath = os.path.join(flask_app.config['UPLOAD_FOLDER'], file_rec.stored_name)

    # Compute hash
    computed_hash  = None
    current_size   = None
    duration_ms    = 0
    check_status   = 'ok'
    error_msg      = None

    try:
        computed_hash, current_size, duration_ms = hash_file(filepath)
        if computed_hash != baseline.sha256_hash:
            check_status = 'tampered'
    except FileNotFoundError:
        check_status = 'missing'
        error_msg    = 'File not found on disk'
    except PermissionError:
        check_status = 'permission_denied'
        error_msg    = 'Permission denied reading file'
    except OSError as exc:
        check_status = 'error'
        error_msg    = str(exc)[:200]

    # Write check record
    chk = IntegrityCheck(
        file_id              = file_id,
        baseline_id          = baseline.id,
        computed_sha256      = computed_hash,
        file_size_at_check   = current_size,
        status               = check_status,
        triggered_by         = triggered_by,
        triggered_by_user_id = triggered_by_user_id,
        check_duration_ms    = duration_ms,
        error_message        = error_msg,
    )
    db.session.add(chk)

    # Update file record
    now = datetime.now(timezone.utc)
    file_rec.last_checked_at = now
    file_rec.check_count    += 1

    policy   = file_rec.policy
    interval = policy.check_interval_mins if policy else 60
    file_rec.next_check_at   = now + timedelta(minutes=interval)
    file_rec.current_status  = check_status

    db.session.flush()  # get chk.id

    return {
        'status':        check_status,
        'check_id':      chk.id,
        'file_id':       file_id,
        'computed_hash': computed_hash,
        'baseline_hash': baseline.sha256_hash,
        'expected_size': baseline.file_size_bytes,
        'current_size':  current_size,
        'error_msg':     error_msg,
    }


# ---------------------------------------------------------------------------
# Alert pipeline
# ---------------------------------------------------------------------------

def run_alert_pipeline(file_rec, result: dict):
    """
    Called after check_single_file() when status != 'ok'.
    Creates IntegrityAlert, emits SocketIO, queues email.
    Caller must commit after this returns.
    """
    from app import (db, IntegrityCheck, IntegrityBaseline, IntegrityAlert,
                     ActivityLog, socketio, mail, app as flask_app,
                     _get_real_ip)
    from flask import render_template
    from flask_login import current_user

    status   = result['status']
    check_id = result['check_id']

    if status in ('ok', 'skip'):
        return

    chk = IntegrityCheck.query.get(check_id)
    if not chk:
        return

    # Deduplication: one open alert per file at a time
    existing = IntegrityAlert.query.filter_by(
        file_id=file_rec.id, status='open'
    ).first()
    if existing:
        # Already open — just increment counter
        file_rec.alert_count += 1
        return

    severity   = classify_severity(file_rec, chk, result)
    alert_type = classify_alert_type(file_rec, chk)

    baseline = IntegrityBaseline.query.filter_by(
        file_id=file_rec.id, is_current=True
    ).first()

    title = {
        'hash_mismatch':      f'File tampered: {file_rec.original_name}',
        'file_missing':       f'File deleted from disk: {file_rec.original_name}',
        'double_extension':   f'Double-extension attack: {file_rec.original_name}',
        'repeated_tampering': f'Repeated tampering: {file_rec.original_name}',
    }.get(alert_type, f'Integrity violation: {file_rec.original_name}')

    desc_lines = [
        f'File: {file_rec.original_name}',
        f'Expected hash: {(result.get("baseline_hash") or "N/A")[:32]}...',
        f'Found hash:    {(result.get("computed_hash")  or "N/A")[:32]}...',
    ]
    if result.get('expected_size') and result.get('current_size') is not None:
        delta = (result['current_size'] or 0) - result['expected_size']
        desc_lines.append(f'Size delta: {delta:+d} bytes')
    desc_lines.append(f'Detected by: {chk.triggered_by}  ({chk.check_duration_ms} ms)')

    alert = IntegrityAlert(
        file_id       = file_rec.id,
        check_id      = chk.id,
        severity      = severity,
        alert_type    = alert_type,
        title         = title,
        description   = '\n'.join(desc_lines),
        expected_hash = baseline.sha256_hash if baseline else '',
        found_hash    = result.get('computed_hash'),
        expected_size = result.get('expected_size'),
        found_size    = result.get('current_size'),
    )
    db.session.add(alert)
    file_rec.alert_count += 1
    db.session.flush()

    # Activity log
    entry = ActivityLog(
        user_id    = None,
        action     = 'tamper_detected',
        detail     = f'[{severity.upper()}] {title}',
        ip_address = '',
    )
    db.session.add(entry)

    # SocketIO broadcast
    payload = {
        'alert_id':  alert.id,
        'type':      alert_type,
        'severity':  severity,
        'title':     title,
        'filename':  file_rec.original_name,
        'file_uuid': file_rec.uuid,
        'raised_at': alert.raised_at.isoformat(),
        'sound':     severity == 'critical',
    }
    try:
        socketio.emit('integrity_alert', payload)
        alert.socket_emitted = True
    except Exception as exc:
        flask_app.logger.error('SocketIO emit failed: %s', exc)

    # Email (async thread so we don't block the check loop)
    policy = file_rec.policy
    send_email = policy.email_alert if policy else (severity in ('medium', 'high', 'critical'))
    if send_email:
        _send_alert_email_async(alert, file_rec, flask_app)


def _send_alert_email_async(alert, file_rec, flask_app):
    """Fire alert email in a background thread."""
    from app import User, mail, db
    from flask_mail import Message

    def _send():
        with flask_app.app_context():
            try:
                from app import User, mail
                admins = User.query.filter(User.role == 'super_admin').all()
                recipients = [u.email for u in admins if u.email]
                owner = User.query.get(file_rec.user_id)
                if owner and owner.email not in recipients:
                    recipients.append(owner.email)
                if not recipients:
                    return

                subject = f'[FIM {alert.severity.upper()}] {alert.title}'
                body = (
                    f'FileVault FIM Alert\n\n'
                    f'Severity: {alert.severity.upper()}\n'
                    f'File:     {file_rec.original_name}\n'
                    f'Status:   {alert.alert_type.replace("_", " ").title()}\n\n'
                    f'{alert.description}\n\n'
                    f'Raised at: {alert.raised_at.strftime("%Y-%m-%d %H:%M:%S UTC")}\n'
                    f'Review this alert in the Alerts Center.\n'
                )
                msg = Message(subject=subject, recipients=recipients, body=body)
                mail.send(msg)
                # Update flag inside a fresh context
                from app import db, IntegrityAlert
                a = IntegrityAlert.query.get(alert.id)
                if a:
                    a.email_sent = True
                    db.session.commit()
            except Exception as exc:
                flask_app.logger.error('Alert email failed: %s', exc)

    threading.Thread(target=_send, daemon=True).start()


def accept_new_baseline(file_rec, accepting_user, note: str = '') -> bool:
    """
    Super Admin action: accept current (tampered) file state as new baseline.
    Closes open alerts for this file.
    Caller must commit.
    """
    from app import db, IntegrityBaseline, IntegrityAlert

    filepath = os.path.join(
        __import__('app').app.config['UPLOAD_FOLDER'],
        file_rec.stored_name
    )
    try:
        new_hash, new_size, _ = hash_file(filepath)
    except Exception:
        return False

    # Supersede old baseline
    old = IntegrityBaseline.query.filter_by(file_id=file_rec.id, is_current=True).first()
    if old:
        old.supersede(accepting_user, note=note)

    new_baseline = IntegrityBaseline(
        file_id         = file_rec.id,
        sha256_hash     = new_hash,
        file_size_bytes = new_size,
        is_current      = True,
        captured_by_id  = accepting_user.id,
        capture_reason  = 'admin_override',
    )
    db.session.add(new_baseline)

    file_rec.current_status = 'ok'
    file_rec.file_hash      = new_hash

    # Close open alerts
    open_alerts = IntegrityAlert.query.filter_by(
        file_id=file_rec.id, status='open'
    ).all()
    for a in open_alerts:
        a.resolve(accepting_user, 'baseline_updated', note)

    return True
