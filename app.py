# ruff: noqa
# flake8: noqa
# pylint: disable=all
# mypy: ignore-errors
# type: ignore
print("=== app.py: start import ===", flush=True)
import os
import re
import secrets
import uuid
import mimetypes
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import func
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, send_from_directory, send_file, jsonify, abort, session
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import resend
from flask_migrate import Migrate
from cryptography.fernet import Fernet
import pyotp
import qrcode
import io
import base64
from urllib.parse import urlparse, urljoin
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
import json as _json
import hashlib
import csv
import zipfile

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
_secret = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
if _secret == 'dev-key-change-in-production':
    import warnings
    warnings.warn(
        'SECRET_KEY is the insecure default. Set the SECRET_KEY environment variable.',
        stacklevel=2,
    )
app.config['SECRET_KEY'] = _secret
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///vault.db')
if _db_url.startswith('postgres://'):          # Render gives postgres://, SQLAlchemy needs postgresql://
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_size': 2,
    'max_overflow': 3,
    'connect_args': {'connect_timeout': 10},   # fail fast if DB unreachable
}
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'vault_uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024    # 50 MB
app.config['STORAGE_QUOTA_BYTES'] = 500 * 1024 * 1024  # 500 MB per user
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config['WTF_CSRF_TIME_LIMIT'] = 3600
app.config['SESSION_PERMANENT'] = False          # session dies when browser closes
app.config['REMEMBER_COOKIE_DURATION'] = 0       # no "remember me" persistence

# Resend email
resend.api_key = os.environ.get('RESEND_API_KEY', '')
# Address all notifications are delivered to (admin inbox)
app.config['NOTIFICATION_EMAIL'] = os.environ.get('NOTIFICATION_EMAIL', '')
# "From" shown in outgoing emails — use your verified Resend domain, or leave
# as onboarding@resend.dev for the free tier (sends to your own email only)
app.config['RESEND_FROM'] = os.environ.get('RESEND_FROM', 'FileVault <onboarding@resend.dev>')

# WebAuthn / FIDO2
WEBAUTHN_RP_ID     = os.environ.get('WEBAUTHN_RP_ID',     'localhost')
WEBAUTHN_RP_NAME   = 'FileVault'
WEBAUTHN_RP_ORIGIN = os.environ.get('WEBAUTHN_RP_ORIGIN', 'http://localhost:5000')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Import db and all models from models.py (factory pattern — db.init_app below)
from models import (
    db, MonitoringPolicy, User, File, FileShare, ShareToken,
    ActivityLog, IntegrityBaseline, IntegrityCheck, IntegrityAlert,
    AlertComment, FileAccessLog, ActionRequest,
)
db.init_app(app)
migrate  = Migrate(app, db)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')
login_manager = LoginManager(app)
login_manager.login_view = 'auth_login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri='memory://',
    default_limits=[],
)
csrf = CSRFProtect(app)
def _resend_email(to: str, subject: str, text: str, html: str | None = None) -> tuple[bool, str]:
    """Send one email via Resend. Returns (success, error_message)."""
    api_key = resend.api_key or ''
    if not api_key:
        return False, 'RESEND_API_KEY is not set in Railway variables.'
    if not to:
        return False, 'No recipient address configured (NOTIFICATION_EMAIL).'
    try:
        params = {
            'from':    app.config.get('RESEND_FROM', 'FileVault <onboarding@resend.dev>'),
            'to':      [to],
            'subject': subject,
            'text':    text,
        }
        if html:
            params['html'] = html
        resend.Emails.send(params)
        app.logger.info('Resend email sent to %s: %s', to, subject)
        return True, ''
    except Exception as exc:
        app.logger.error('Resend failed to %s: %s', to, exc)
        return False, str(exc)

_enc_key     = os.environ.get('ENCRYPTION_KEY', '')
_enc_key_raw = base64.urlsafe_b64decode(_enc_key.encode()) if _enc_key else None


def _file_fernet(stored_name: str):
    """Return a Fernet instance keyed uniquely to this file via HKDF.
    Each file gets its own AES key derived from the master key + stored filename,
    so a single leaked key cannot decrypt all files at once.
    """
    if not _enc_key_raw:
        return None
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=stored_name.encode(),
    ).derive(_enc_key_raw)
    return Fernet(base64.urlsafe_b64encode(derived))

# Per-email failed login tracking
_login_attempts: dict = defaultdict(lambda: {'count': 0, 'locked_until': None})
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_MINUTES   = 15

# Per-user failed password attempts (for action confirmation modals)
_pw_attempts: dict = defaultdict(lambda: {'count': 0, 'locked_until': None})
_PW_LOCK_THRESHOLD = 5
_PW_LOCK_MINUTES   = 15

def _check_pw_locked(user_id: int) -> tuple[bool, str]:
    rec = _pw_attempts[user_id]
    if rec['locked_until'] and datetime.now(timezone.utc) < rec['locked_until']:
        remaining = int((rec['locked_until'] - datetime.now(timezone.utc)).total_seconds())
        mins, secs = divmod(remaining, 60)
        return True, f'Too many failed attempts. Try again in {mins}m {secs}s.'
    return False, ''

def _record_pw_fail(user_id: int, user_name: str, user_email: str, action_context: str = '') -> bool:
    rec = _pw_attempts[user_id]
    rec['count'] += 1
    if rec['count'] >= _PW_LOCK_THRESHOLD:
        rec['locked_until'] = datetime.now(timezone.utc) + timedelta(minutes=_PW_LOCK_MINUTES)
        rec['count'] = 0
        _notify(
            f'Password Lockout — {user_name}',
            f'User:    {user_name} ({user_email})\n'
            f'Action:  {action_context}\n'
            f'Reason:  {_PW_LOCK_THRESHOLD} consecutive failed password attempts\n'
            f'Locked:  {_PW_LOCK_MINUTES} minutes\n'
            f'IP:      {_get_real_ip()}',
        )
        return True
    return False

ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'json', 'xml', 'zip', 'rar', 'mp4', 'mp3'
}

# Text file types that can be edited in the browser
EDITABLE_EXTENSIONS = {
    # Plain text / data
    'txt', 'csv', 'tsv', 'log', 'md', 'rst',
    # Config / markup
    'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'env',
    # Web
    'html', 'htm', 'css', 'js', 'ts', 'jsx', 'tsx',
    # Programming languages
    'py', 'sh', 'bash', 'sql', 'php', 'rb', 'java',
    'c', 'cpp', 'h', 'rs', 'go', 'swift', 'kt',
}
EDITOR_SIZE_LIMIT   = 512 * 1024  # 512 KB

ACTION_ICONS = {
    'upload':   ('bi-cloud-upload-fill',  'text-primary'),
    'download': ('bi-cloud-download-fill','text-info'),
    'delete':   ('bi-trash-fill',         'text-danger'),
    'share':    ('bi-share-fill',         'text-success'),
    'rename':   ('bi-pencil-fill',        'text-warning'),
    'login':    ('bi-box-arrow-in-right', 'text-secondary'),
    'logout':   ('bi-box-arrow-right',    'text-secondary'),
    'register': ('bi-person-plus-fill',   'text-purple'),
    'profile':  ('bi-person-fill',        'text-teal'),
}

PER_PAGE = 20


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Helpers (models moved to models.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _is_safe_redirect(target):
    host = urlparse(request.host_url)
    dest = urlparse(urljoin(request.host_url, target))
    return dest.scheme in ('http', 'https') and host.netloc == dest.netloc


@app.after_request
def _security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; "
        "font-src 'self' cdn.jsdelivr.net cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.before_request
def _enforce_session_login():
    """Force re-login on every new browser session.
    Flask session cookies have no expiry (browser-session only) because
    SESSION_PERMANENT=False, so this marker disappears when the tab/browser closes.
    """
    if current_user.is_authenticated and not session.get('_logged_in_this_session'):
        logout_user()
        session.clear()
        return redirect(url_for('auth_login'))
    if current_user.is_authenticated:
        session['_logged_in_this_session'] = True


def format_bytes(size):
    size = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024:
            return f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} TB'


def _get_real_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or ''

def log_activity(action, detail='', user_id=None):
    uid = user_id if user_id is not None else (
        current_user.id if current_user.is_authenticated else None)
    entry = ActivityLog(
        user_id=uid,
        action=action,
        detail=str(detail)[:500],
        ip_address=_get_real_ip(),
    )
    db.session.add(entry)


def broadcast_event(event_type, message, filename='', user_name=''):
    socketio.emit('file_event', {
        'type':      event_type,
        'message':   message,
        'filename':  filename,
        'user':      user_name,
        'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
    })


def _notify(subject: str, body: str) -> None:
    """Send a notification email to NOTIFICATION_EMAIL via Resend (background thread)."""
    recipient = app.config.get('NOTIFICATION_EMAIL', '').strip()
    if not recipient or not resend.api_key:
        return
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    html = f'''
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;
            background:#f4f6f9;padding:24px;border-radius:10px">
  <div style="background:#0d1117;padding:14px 24px;border-radius:8px 8px 0 0;text-align:center">
    <span style="color:white;font-size:18px;font-weight:bold">&#128274; FileVault</span>
  </div>
  <div style="background:white;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
    <h3 style="margin:0 0 12px;color:#0d1117">{subject}</h3>
    <p style="white-space:pre-line;color:#333;font-size:14px">{body}</p>
    <p style="margin-top:20px;font-size:11px;color:#aaa">{ts}</p>
  </div>
</div>'''
    import threading
    def _send():
        with app.app_context():
            ok, err = _resend_email(recipient, f'[FileVault] {subject}', f'{body}\n\n---\nFileVault · {ts}', html)
            if not ok:
                app.logger.warning('_notify skipped: %s', err)
    threading.Thread(target=_send, daemon=True, name='notify-email').start()


def _log_file_access(action, file_rec=None, outcome='success', details=None):
    """Write a FileAccessLog entry and emit a real-time SocketIO event to admin monitors."""
    entry = FileAccessLog(
        file_id    = file_rec.id   if file_rec else None,
        user_id    = current_user.id if current_user.is_authenticated else None,
        action     = action,
        outcome    = outcome,
        ip_address = request.remote_addr or '',
        file_name  = file_rec.original_name if file_rec else None,
        user_name  = current_user.full_name if current_user.is_authenticated else 'anonymous',
        details    = details,
    )
    db.session.add(entry)
    # Real-time push to admin event monitor (fire-and-forget — never crash the caller)
    try:
        socketio.emit('access_event', {
            'action':    action,
            'outcome':   outcome,
            'file':      file_rec.original_name if file_rec else '—',
            'user':      current_user.full_name if current_user.is_authenticated else 'anonymous',
            'ip':        request.remote_addr or '',
            'details':   details or '',
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        }, room='admin_monitor')
    except Exception as _sock_err:
        app.logger.debug('access_event emit failed: %s', _sock_err)


def _storage_type_breakdown(files):
    buckets = defaultdict(int)
    for f in files:
        ext = f.original_name.rsplit('.', 1)[-1].lower() if '.' in f.original_name else ''
        if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
            buckets['Images'] += f.size
        elif ext in ('pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'csv', 'json', 'xml'):
            buckets['Documents'] += f.size
        elif ext in ('xls', 'xlsx'):
            buckets['Spreadsheets'] += f.size
        elif ext in ('mp4', 'mp3', 'avi', 'mov', 'wav'):
            buckets['Media'] += f.size
        elif ext in ('zip', 'rar', '7z'):
            buckets['Archives'] += f.size
        else:
            buckets['Other'] += f.size
    return {k: v for k, v in buckets.items() if v > 0}


def _weekly_uploads(user_id):
    now = datetime.now(timezone.utc)
    labels, counts = [], []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        count = db.session.query(func.count(ActivityLog.id)).filter(
            ActivityLog.user_id == user_id,
            ActivityLog.action == 'upload',
            func.date(ActivityLog.created_at) == str(day),
        ).scalar() or 0
        labels.append(day.strftime('%a'))
        counts.append(count)
    return labels, counts


def _validate_password_strength(password):
    if len(password) < 8:
        return 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter.'
    if not re.search(r'\d', password):
        return 'Password must contain at least one number.'
    if not re.search(r'[^A-Za-z0-9]', password):
        return 'Password must contain at least one special character (!@#$%...).'
    return None


def _send_verification_email(user):
    token = secrets.token_urlsafe(32)
    user.verification_token = token
    db.session.commit()
    link  = url_for('verify_email', token=token, _external=True)
    name  = user.full_name
    email = user.email
    text  = (f'Hi {name},\n\nClick here to verify your FileVault email:\n{link}\n\n'
             f'If you did not register, ignore this email.')
    html  = f'''
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;background:#f4f6f9;padding:24px;border-radius:10px">
  <div style="background:#0d1117;padding:14px 24px;border-radius:8px 8px 0 0;text-align:center">
    <span style="color:white;font-size:18px;font-weight:bold">&#128274; FileVault</span>
  </div>
  <div style="background:white;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
    <h3 style="margin:0 0 12px;color:#0d1117">Verify your email</h3>
    <p style="color:#333;font-size:14px">Hi {name},<br><br>Click the button below to verify your FileVault account.</p>
    <a href="{link}" style="display:inline-block;margin:16px 0;padding:12px 24px;background:#0d6efd;color:white;
       border-radius:6px;text-decoration:none;font-weight:bold">Verify Email</a>
    <p style="font-size:12px;color:#aaa">If you did not register, ignore this email.</p>
  </div>
</div>'''
    import threading
    def _send():
        with app.app_context():
            _resend_email(email, '[FileVault] Verify your email', text, html)  # ignore result
    threading.Thread(target=_send, daemon=True).start()



def _is_expired(dt: datetime | None) -> bool:
    if dt is None:
        return False
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > aware


def _apply_sort(q, sort, order):
    col = {'name': File.original_name, 'size': File.size}.get(sort, File.uploaded_at)
    return q.order_by(col.asc() if order == 'asc' else col.desc())


def _apply_type_filter(q, type_filter):
    groups = {
        'images':    ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'],
        'documents': ['pdf', 'doc', 'docx', 'txt', 'csv', 'json', 'xml', 'ppt', 'pptx'],
        'sheets':    ['xls', 'xlsx'],
        'media':     ['mp4', 'mp3'],
        'archives':  ['zip', 'rar'],
    }
    exts = groups.get(type_filter, [])
    if exts:
        q = q.filter(db.or_(*[File.original_name.ilike(f'%.{e}') for e in exts]))
    return q


# ---------------------------------------------------------------------------
# FIM helpers — defined here so db/models are always in scope (no circular import)
# ---------------------------------------------------------------------------
def _send_alert_email(file_rec, alert, severity, title):
    """Send a FIM integrity alert email via Resend (background thread)."""
    recipient = app.config.get('NOTIFICATION_EMAIL', '').strip()
    if not recipient or not resend.api_key:
        return
    fname   = file_rec.original_name
    ts      = alert.raised_at.strftime('%Y-%m-%d %H:%M:%S UTC')
    sev_col = {'critical': '#dc3545', 'high': '#fd7e14', 'medium': '#ffc107'}.get(severity, '#6c757d')
    text = (f'FileVault Integrity Alert\n'
            f'Severity : {severity.upper()}\n'
            f'File     : {fname}\n'
            f'Alert    : {title}\n'
            f'Detected : {ts}\n\n'
            f'Log in to FileVault to review and close this alert.')
    html = f'''
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#f4f6f9;padding:24px;border-radius:10px">
  <div style="background:#0d1117;padding:18px 24px;border-radius:8px 8px 0 0;text-align:center">
    <span style="color:white;font-size:20px;font-weight:bold">&#128274; FileVault</span>
  </div>
  <div style="background:white;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e0e0e0">
    <div style="background:{sev_col};color:white;padding:10px 16px;border-radius:6px;font-weight:bold;margin-bottom:16px">
      {severity.upper()} INTEGRITY ALERT
    </div>
    <h3 style="margin:0 0 16px">{title}</h3>
    <table style="width:100%;font-size:14px;border-collapse:collapse">
      <tr><td style="padding:6px 0;color:#555;width:90px">File</td><td><strong>{fname}</strong></td></tr>
      <tr><td style="padding:6px 0;color:#555">Severity</td><td><strong style="color:{sev_col}">{severity.upper()}</strong></td></tr>
      <tr><td style="padding:6px 0;color:#555">Detected</td><td>{ts}</td></tr>
    </table>
    <p style="margin-top:24px;font-size:12px;color:#999;border-top:1px solid #eee;padding-top:12px">
      Log in to FileVault to review and close this alert.
    </p>
  </div>
</div>'''
    import threading
    def _send():
        with app.app_context():
            _resend_email(recipient, f'[FileVault] {severity.upper()} ALERT — {fname}', text, html)  # ignore result
    threading.Thread(target=_send, daemon=True, name='alert-email').start()


def _fim_capture_baseline(file_rec, user, reason='upload'):
    """Hash the file and write an IntegrityBaseline row. Does NOT commit."""
    from integrity_engine import hash_file as _hash_file
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    try:
        hex_digest, size_bytes, _ = _hash_file(filepath)
    except Exception as exc:
        app.logger.error('baseline capture failed for %s: %s', file_rec.stored_name, exc)
        return None

    old = IntegrityBaseline.query.filter_by(file_id=file_rec.id, is_current=True).first()
    if old:
        old.is_current       = False
        old.superseded_at    = datetime.now(timezone.utc)
        old.superseded_by_id = user.id if user else None
        old.supersede_note   = f'Superseded by new {reason}'

    baseline = IntegrityBaseline(
        file_id         = file_rec.id,
        sha256_hash     = hex_digest,
        file_size_bytes = size_bytes,
        is_current      = True,
        captured_by_id  = user.id if user else None,
        capture_reason  = reason,
    )
    db.session.add(baseline)
    file_rec.current_status  = 'ok'
    file_rec.last_checked_at = datetime.now(timezone.utc)
    file_rec.file_hash       = hex_digest
    return baseline


def _fim_check_file(file_rec, triggered_by='manual', triggered_by_user_id=None):
    """Re-hash file vs baseline, write IntegrityCheck row. Does NOT commit."""
    from integrity_engine import hash_file as _hash_file

    baseline = IntegrityBaseline.query.filter_by(
        file_id=file_rec.id, is_current=True
    ).first()
    if not baseline:
        return {'status': 'skip', 'reason': 'no_baseline'}

    filepath     = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    computed     = None
    cur_size     = None
    duration_ms  = 0
    status       = 'ok'
    error_msg    = None

    try:
        import time as _time
        t0 = _time.monotonic()
        computed, cur_size, duration_ms = _hash_file(filepath)
        if computed != baseline.sha256_hash:
            status = 'tampered'
    except FileNotFoundError:
        status    = 'missing'
        error_msg = 'File not found on disk'
    except Exception as exc:
        status    = 'error'
        error_msg = str(exc)[:200]

    chk = IntegrityCheck(
        file_id              = file_rec.id,
        baseline_id          = baseline.id,
        computed_sha256      = computed,
        file_size_at_check   = cur_size,
        status               = status,
        triggered_by         = triggered_by,
        triggered_by_user_id = triggered_by_user_id,
        check_duration_ms    = duration_ms,
        error_message        = error_msg,
    )
    db.session.add(chk)

    now = datetime.now(timezone.utc)
    file_rec.last_checked_at = now
    file_rec.check_count    += 1
    file_rec.current_status  = status
    interval = file_rec.policy.check_interval_mins if file_rec.policy else 60
    file_rec.next_check_at   = now + timedelta(minutes=interval)
    db.session.flush()

    return {
        'status':        status,
        'check_id':      chk.id,
        'file_id':       file_rec.id,
        'computed_hash': computed,
        'baseline_hash': baseline.sha256_hash,
        'expected_size': baseline.file_size_bytes,
        'current_size':  cur_size,
        'error_msg':     error_msg,
    }


def _fim_raise_alert(file_rec, result):
    """Create IntegrityAlert for a failed check, emit SocketIO. Does NOT commit."""
    from integrity_engine import classify_severity, classify_alert_type

    status   = result['status']
    check_id = result.get('check_id')
    if status in ('ok', 'skip') or not check_id:
        return

    chk = IntegrityCheck.query.get(check_id)
    if not chk:
        return

    existing = IntegrityAlert.query.filter_by(file_id=file_rec.id, status='open').first()
    if existing:
        file_rec.alert_count += 1
        # Still notify by email even if alert record already exists
        _send_alert_email(file_rec, existing, existing.severity, existing.title)
        return

    severity   = classify_severity(file_rec, chk, result)
    alert_type = classify_alert_type(file_rec, chk)
    baseline   = IntegrityBaseline.query.filter_by(file_id=file_rec.id, is_current=True).first()

    title = {
        'hash_mismatch':      f'File tampered: {file_rec.original_name}',
        'file_missing':       f'File deleted from disk: {file_rec.original_name}',
        'double_extension':   f'Double-extension attack: {file_rec.original_name}',
        'repeated_tampering': f'Repeated tampering: {file_rec.original_name}',
    }.get(alert_type, f'Integrity violation: {file_rec.original_name}')

    alert = IntegrityAlert(
        file_id       = file_rec.id,
        check_id      = chk.id,
        severity      = severity,
        alert_type    = alert_type,
        title         = title,
        expected_hash = baseline.sha256_hash if baseline else '',
        found_hash    = result.get('computed_hash'),
        expected_size = result.get('expected_size'),
        found_size    = result.get('current_size'),
    )
    db.session.add(alert)
    file_rec.alert_count += 1
    db.session.flush()

    try:
        socketio.emit('integrity_alert', {
            'alert_id':  alert.id,
            'type':      alert_type,
            'severity':  severity,
            'title':     title,
            'filename':  file_rec.original_name,
            'file_uuid': file_rec.uuid,
            'raised_at': alert.raised_at.isoformat(),
            'sound':     severity == 'critical',
        })
    except Exception as exc:
        app.logger.error('SocketIO emit failed: %s', exc)

    _send_alert_email(file_rec, alert, severity, title)


def _fim_accept_baseline(file_rec, user, note=''):
    """Accept current on-disk state as new trusted baseline. Does NOT commit."""
    from integrity_engine import hash_file as _hash_file
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    try:
        new_hash, new_size, _ = _hash_file(filepath)
    except Exception:
        return False

    old = IntegrityBaseline.query.filter_by(file_id=file_rec.id, is_current=True).first()
    if old:
        old.is_current       = False
        old.superseded_at    = datetime.now(timezone.utc)
        old.superseded_by_id = user.id
        old.supersede_note   = note

    db.session.add(IntegrityBaseline(
        file_id         = file_rec.id,
        sha256_hash     = new_hash,
        file_size_bytes = new_size,
        is_current      = True,
        captured_by_id  = user.id,
        capture_reason  = 'admin_override',
    ))
    file_rec.current_status = 'ok'
    file_rec.file_hash      = new_hash

    for a in IntegrityAlert.query.filter_by(file_id=file_rec.id, status='open').all():
        a.resolve(user, 'baseline_updated', note)

    return True


# ---------------------------------------------------------------------------
# Template context processors
# ---------------------------------------------------------------------------
@app.context_processor
def _fim_nav_context():
    """Inject FIM nav badge counts into every template."""
    if not current_user.is_authenticated:
        return {'fim_open_alerts': 0, 'nav_total_files': 0}
    try:
        if current_user.is_admin:
            open_count   = IntegrityAlert.query.filter_by(status='open').count()
            file_count   = File.query.count()
            pending_reqs = ActionRequest.query.filter_by(status='pending').count()
        else:
            open_count   = IntegrityAlert.query.filter_by(status='open').count()
            file_count   = File.query.count()
            pending_reqs = ActionRequest.query.filter_by(
                requested_by_id=current_user.id, status='approved'
            ).count()
        return {'fim_open_alerts': open_count, 'nav_total_files': file_count,
                'pending_action_requests': pending_reqs}
    except Exception:
        return {'fim_open_alerts': 0, 'nav_total_files': 0, 'pending_action_requests': 0}


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return redirect(url_for('dashboard') if current_user.is_authenticated else url_for('auth_login'))


@app.route('/auth/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute; 50 per hour')
def auth_login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        record = _login_attempts[email]
        if record['locked_until'] and datetime.now(timezone.utc) < record['locked_until']:
            secs = int((record['locked_until'] - datetime.now(timezone.utc)).total_seconds())
            mins, secs = divmod(secs, 60)
            flash(f'Account locked after too many failed attempts. '
                  f'Try again in {mins}m {secs}s.', 'danger')
            return render_template('auth/login.html')

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            _login_attempts.pop(email, None)
            login_user(user, remember=False)
            session['_logged_in_this_session'] = True
            log_activity('login', f'Logged in from {_get_real_ip()}')
            db.session.commit()
            _notify(
                f'User Login — {user.full_name}',
                f'User:       {user.full_name} ({user.email})\n'
                f'Role:       {"Admin" if user.is_admin else "User"}\n'
                f'IP address: {_get_real_ip()}\n'
                f'Time:       {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
            )
            flash(f'Welcome back, {user.full_name.split()[0]}!', 'success')
            nxt = request.args.get('next', '')
            return redirect(nxt if nxt and _is_safe_redirect(nxt) else url_for('dashboard'))

        record['count'] += 1
        remaining = _LOCKOUT_THRESHOLD - record['count']
        if remaining <= 0:
            record['locked_until'] = datetime.now(timezone.utc) + timedelta(minutes=_LOCKOUT_MINUTES)
            flash(f'Too many failed attempts. Account locked for {_LOCKOUT_MINUTES} minutes.', 'danger')
            _notify(
                f'Account Locked — {email}',
                f'Account:         {email}\n'
                f'Reason:          {_LOCKOUT_THRESHOLD} consecutive failed login attempts\n'
                f'Locked for:      {_LOCKOUT_MINUTES} minutes\n'
                f'IP address:      {_get_real_ip()}\n'
                f'Account exists:  {"Yes" if user else "No (unknown email)"}',
            )
        else:
            flash(f'Invalid email or password. {remaining} attempt(s) left before lockout.', 'danger')

        # Log failed attempt and alert admins if threshold reached
        log_activity('login_fail', f'Failed login for {email} from {request.remote_addr}')
        db.session.commit()
        recent_fails = ActivityLog.query.filter(
            ActivityLog.action == 'login_fail',
            ActivityLog.ip_address == request.remote_addr,
            ActivityLog.created_at > datetime.now(timezone.utc) - timedelta(minutes=10)
        ).count()
        if recent_fails >= 5:
            socketio.emit('security_alert', {
                'message': f'{recent_fails} failed login attempts from IP {request.remote_addr}',
                'ip': request.remote_addr,
                'email': email,
                'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
                'level': 'danger',
            })

    return render_template('auth/login.html')


@app.route('/auth/register', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour')
def auth_register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email     = request.form.get('email', '').strip().lower()
        password  = request.form.get('password', '')
        confirm   = request.form.get('confirm_password', '')

        pwd_err = _validate_password_strength(password)
        if not full_name or not email or not password:
            flash('All fields are required.', 'danger')
        elif not email.endswith('@filevault.com'):
            flash('Only @filevault.com email addresses are allowed to register.', 'danger')
        elif password != confirm:
            flash('Passwords do not match.', 'danger')
        elif pwd_err:
            flash(pwd_err, 'danger')
        elif User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
        else:
            is_first = User.query.count() == 0
            user = User(full_name=full_name, email=email,
                        is_admin=is_first,
                        role='super_admin' if is_first else 'user')
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            log_activity('register', f'New account: {email}', user_id=user.id)
            db.session.commit()
            _send_verification_email(user)
            _notify(
                f'New Account Registered — {user.full_name}',
                f'Name:      {user.full_name}\n'
                f'Email:     {email}\n'
                f'Role:      {"Admin (first user)" if is_first else "User"}\n'
                f'IP:        {_get_real_ip()}\n\n'
                f'Log in to FileVault to set their clearance level.',
            )
            login_user(user)
            session['_logged_in_this_session'] = True
            flash('Account created! Check your email to verify your address.', 'success')
            return redirect(url_for('dashboard'))

    return render_template('auth/register.html')


@app.route('/auth/forgot-password', methods=['GET', 'POST'])
def auth_forgot():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user  = User.query.filter_by(email=email).first()
        if not user:
            flash('No account found with that email address.', 'danger')
            return render_template('auth/forgot_password.html')
        if not user.mfa_enabled:
            flash(
                'Your account has no recovery code set up. '
                'Please contact an administrator to reset your password.',
                'warning'
            )
            return render_template('auth/forgot_password.html')
        session['_recovery_user_id'] = user.id
        return redirect(url_for('auth_forgot_totp'))
    return render_template('auth/forgot_password.html')


@app.route('/auth/forgot-totp', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour')
def auth_forgot_totp():
    user_id = session.get('_recovery_user_id')
    if not user_id:
        return redirect(url_for('auth_forgot'))
    user = db.session.get(User, user_id)
    if not user or not user.mfa_enabled:
        session.pop('_recovery_user_id', None)
        return redirect(url_for('auth_forgot'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip().replace(' ', '')
        if pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1):
            session.pop('_recovery_user_id', None)
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=1)
            db.session.commit()
            return redirect(url_for('auth_reset_password', token=token))
        flash('Invalid or expired code. Please try again.', 'danger')

    return render_template('auth/forgot_totp.html')


@app.route('/auth/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash('Invalid or expired verification link.', 'danger')
        return redirect(url_for('auth_login'))
    user.email_verified     = True
    user.verification_token = None
    db.session.commit()
    flash('Email verified! Your account is fully activated.', 'success')
    return redirect(url_for('dashboard') if current_user.is_authenticated else url_for('auth_login'))


@app.route('/auth/reset-password/<token>', methods=['GET', 'POST'])
def auth_reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    expired = user and _is_expired(user.reset_token_expires)
    if not user or expired:
        flash('This reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth_forgot'))

    if request.method == 'POST':
        new_pwd = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        err = _validate_password_strength(new_pwd)
        if err:
            flash(err, 'danger')
        elif new_pwd != confirm:
            flash('Passwords do not match.', 'danger')
        else:
            user.set_password(new_pwd)
            user.reset_token         = None
            user.reset_token_expires = None
            log_activity('profile', 'Password reset via email link', user_id=user.id)
            db.session.commit()
            flash('Password reset successfully. Please log in.', 'success')
            return redirect(url_for('auth_login'))

    return render_template('auth/reset_password.html', token=token)


@app.route('/auth/mfa-verify', methods=['GET', 'POST'])
@limiter.limit('5 per minute; 20 per hour')
def auth_mfa_verify():
    user_id = session.get('_mfa_user_id')
    if not user_id:
        return redirect(url_for('auth_login'))
    user = db.session.get(User, user_id)
    if not user or (not user.mfa_enabled and not user.webauthn_enabled):
        session.pop('_mfa_user_id', None)
        session.pop('_mfa_remember', None)
        return redirect(url_for('auth_login'))

    if request.method == 'POST' and user.mfa_enabled:
        code = request.form.get('code', '').strip().replace(' ', '')
        if pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1):
            remember = session.pop('_mfa_remember', False)
            session.pop('_mfa_user_id', None)
            nxt = session.pop('_mfa_next', None)
            login_user(user, remember=False)
            session['_logged_in_this_session'] = True
            log_activity('login', f'Logged in with MFA from {request.remote_addr}')
            db.session.commit()
            flash(f'Welcome back, {user.full_name.split()[0]}!', 'success')
            return redirect(nxt or url_for('dashboard'))
        flash('Invalid or expired code. Please try again.', 'danger')

    return render_template('auth/mfa_verify.html',
                           totp_available=user.mfa_enabled,
                           webauthn_available=user.webauthn_enabled)


def _make_qr_b64(secret, email):
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name='FileVault')
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


@app.route('/profile/mfa-setup', methods=['GET', 'POST'])
@login_required
def mfa_setup():
    if current_user.mfa_enabled:
        flash('A recovery code is already set up.', 'info')
        return redirect(url_for('profile'))

    if request.method == 'POST':
        secret = session.get('_mfa_pending')
        code   = request.form.get('code', '').strip().replace(' ', '')
        if not secret:
            flash('Session expired. Please start setup again.', 'danger')
            return redirect(url_for('mfa_setup'))
        if pyotp.TOTP(secret).verify(code, valid_window=1):
            current_user.mfa_secret  = secret
            current_user.mfa_enabled = True
            session.pop('_mfa_pending', None)
            log_activity('profile', 'Set up Google Authenticator recovery code')
            db.session.commit()
            flash('Two-factor authentication enabled!', 'success')
            return redirect(url_for('profile'))
        flash('Invalid code. Please try again.', 'danger')
    else:
        secret = pyotp.random_base32()
        session['_mfa_pending'] = secret

    secret = session.get('_mfa_pending', '')
    return render_template('auth/mfa_setup.html',
                           secret=secret,
                           qr_b64=_make_qr_b64(secret, current_user.email))


@app.route('/profile/mfa-disable', methods=['POST'])
@login_required
def mfa_disable():
    current_user.mfa_secret  = None
    current_user.mfa_enabled = False
    log_activity('profile', 'Disabled two-factor authentication')
    db.session.commit()
    flash('Two-factor authentication disabled.', 'info')
    return redirect(url_for('profile'))


@app.route('/auth/logout')
@login_required
def auth_logout():
    name = current_user.full_name.split()[0]
    log_activity('logout', 'Logged out')
    db.session.commit()
    logout_user()
    flash(f'Goodbye, {name}!', 'info')
    return redirect(url_for('auth_login'))


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_profile':
            new_name = request.form.get('full_name', '').strip()
            if not new_name:
                flash('Name cannot be empty.', 'danger')
            else:
                current_user.full_name = new_name
                log_activity('profile', 'Updated profile name')
                db.session.commit()
                flash('Profile updated.', 'success')

        elif action == 'change_password':
            cur = request.form.get('current_password', '')
            new = request.form.get('new_password', '')
            cfm = request.form.get('confirm_password', '')
            err = _validate_password_strength(new)
            if not current_user.check_password(cur):
                flash('Current password is incorrect.', 'danger')
            elif err:
                flash(err, 'danger')
            elif new != cfm:
                flash('Passwords do not match.', 'danger')
            else:
                current_user.set_password(new)
                log_activity('profile', 'Changed password')
                db.session.commit()
                flash('Password changed successfully.', 'success')

        elif action == 'update_notifications':
            current_user.email_alerts_enabled = request.form.get('email_alerts_enabled') == '1'
            alert_email = request.form.get('alert_email', '').strip()
            current_user.alert_email = alert_email if alert_email else None
            log_activity('profile', 'Updated notification settings')
            db.session.commit()
            flash('Notification settings saved.', 'success')

        return redirect(url_for('profile'))

    my_files   = File.query.filter_by(user_id=current_user.id).all()
    total_size = sum(f.size for f in my_files)
    quota      = app.config['STORAGE_QUOTA_BYTES']
    quota_pct  = min(100, round(total_size / quota * 100, 1))
    created = current_user.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    days_joined = (datetime.now(timezone.utc) - created).days

    return render_template('profile.html',
        total_files=len(my_files),
        total_size=format_bytes(total_size),
        quota_pct=quota_pct,
        quota_max=format_bytes(quota),
        days_joined=days_joined,
    )


# ---------------------------------------------------------------------------
# Dashboard — FIM Security Overview
# ---------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    # Legacy file-management section links redirect to monitoring page
    section = request.args.get('section', '')
    if section in ('my_files', 'shared_with_me', 'recent'):
        return redirect(url_for('fim_monitoring'))

    is_admin = current_user.is_admin

    if is_admin:
        file_q  = File.query
        alert_q = IntegrityAlert.query
    else:
        file_q  = File.query
        alert_q = IntegrityAlert.query

    monitored = file_q.filter_by(monitoring_enabled=True)

    stats = dict(
        total_monitored = monitored.count(),
        ok              = monitored.filter_by(current_status='ok').count(),
        tampered        = monitored.filter_by(current_status='tampered').count(),
        missing         = monitored.filter_by(current_status='missing').count(),
        pending         = monitored.filter_by(current_status='pending').count(),
        error           = monitored.filter_by(current_status='error').count(),
        open_alerts     = alert_q.filter_by(status='open').count(),
    )

    sev_counts = {s: alert_q.filter_by(status='open', severity=s).count()
                  for s in ('critical', 'high', 'medium', 'low', 'info')}

    open_alerts = (
        alert_q.filter_by(status='open')
        .order_by(IntegrityAlert.severity.desc(), IntegrityAlert.raised_at.desc())
        .limit(10).all()
    )

    now = datetime.now(timezone.utc)
    trend_labels, trend_counts = [], []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        c   = alert_q.filter(func.date(IntegrityAlert.raised_at) == str(day)).count()
        trend_labels.append(day.strftime('%a'))
        trend_counts.append(c)

    chk_q = IntegrityCheck.query
    recent_checks = chk_q.order_by(IntegrityCheck.checked_at.desc()).limit(8).all()

    return render_template('dashboard.html',
        stats=stats,
        sev_counts=sev_counts,
        open_alerts=open_alerts,
        trend_labels=trend_labels,
        trend_counts=trend_counts,
        recent_checks=recent_checks,
    )


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------
@app.route('/upload', methods=['POST'])
@login_required
@limiter.limit('20 per hour')
def upload_file():
    # Only administrators may upload files.
    if not current_user.is_admin:
        _log_file_access('upload', outcome='denied', details='Non-admin upload attempt blocked')
        return jsonify(success=False, error='Only administrators can upload files.'), 403
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def err(msg, code=400):
        if is_ajax:
            return jsonify(success=False, error=msg), code
        flash(msg, 'warning')
        return redirect(url_for('dashboard'))

    if 'file' not in request.files or request.files['file'].filename == '':
        return err('No file selected.')
    f = request.files['file']
    if not allowed_file(f.filename):
        return err('File type not allowed.')

    all_my = File.query.filter_by(user_id=current_user.id).all()
    used   = sum(fl.size for fl in all_my)
    quota  = app.config['STORAGE_QUOTA_BYTES']
    f.seek(0, 2)
    incoming_size = f.tell()
    f.seek(0)
    if used + incoming_size > quota:
        return err('Storage quota exceeded.')

    original_name = secure_filename(f.filename)
    ext           = original_name.rsplit('.', 1)[-1].lower() if '.' in original_name else ''
    stored_name   = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
    save_path     = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
    raw_data      = f.read()
    sha256_hash   = hashlib.sha256(raw_data).hexdigest()
    _ff           = _file_fernet(stored_name)
    disk_data     = _ff.encrypt(raw_data) if _ff else raw_data
    with open(save_path, 'wb') as fh:
        fh.write(disk_data)
    size = len(raw_data)  # quota uses plaintext size
    mime = mimetypes.guess_type(original_name)[0] or 'application/octet-stream'

    classification = request.form.get('classification', 5, type=int)
    if classification not in (1, 2, 3, 4, 5):
        classification = 5

    try:
        rec = File(original_name=original_name, stored_name=stored_name,
                   size=size, mimetype=mime, user_id=current_user.id,
                   is_encrypted=bool(_enc_key_raw), file_hash=sha256_hash,
                   classification=classification)
        db.session.add(rec)
        log_activity('upload', f'Uploaded "{original_name}" ({format_bytes(size)}) — class {classification}')
        _log_file_access('upload', rec, 'success',
                         f'Classification: {rec.classification_label}')
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.exists(save_path):
            os.remove(save_path)
        return err('Database error, upload cancelled.', 500)

    # Capture FIM baseline immediately after upload
    try:
        _fim_capture_baseline(rec, current_user, reason='upload')
        db.session.commit()
    except Exception as _fim_exc:
        app.logger.warning('FIM baseline capture failed for "%s": %s', original_name, _fim_exc)

    broadcast_event('upload', f'{current_user.full_name} uploaded "{original_name}"',
                    original_name, current_user.full_name)
    _notify(
        f'File Uploaded — {original_name}',
        f'File:           {original_name}\n'
        f'Size:           {format_bytes(size)}\n'
        f'Classification: {rec.classification_label}\n'
        f'Uploaded by:    {current_user.full_name}\n'
        f'IP:             {_get_real_ip()}',
    )

    if is_ajax:
        return jsonify(success=True, file=rec.to_dict())
    flash(f'"{original_name}" uploaded successfully.', 'success')
    return redirect(url_for('fim_monitoring'))


@app.route('/download/<file_uuid>')
@login_required
def download_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    # Admins bypass all checks; non-admins need clearance then an approved ActionRequest
    if not current_user.is_admin:
        if not current_user.can_view_file(rec):
            _log_file_access('download', rec, 'denied',
                             f'Clearance L{current_user.clearance_level} insufficient for L{rec.classification} file')
            db.session.commit()
            _notify(
                f'Access Denied — {rec.original_name}',
                f'User:            {current_user.full_name} ({current_user.email})\n'
                f'File:            {rec.original_name}\n'
                f'Action:          Download\n'
                f'User clearance:  L{current_user.clearance_level} {current_user.clearance_label}\n'
                f'File class.:     L{rec.classification} {rec.classification_label}\n'
                f'Reason:          Clearance level insufficient',
            )
            flash(f'Access denied — your clearance (L{current_user.clearance_level}) is below the required level for this file.', 'danger')
            return redirect(url_for('fim_monitoring'))
        token = request.args.get('token', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=rec.id,
            requested_by_id=current_user.id, action_type='download', status='approved',
        ).first()
        if not ar or ar.is_expired:
            _log_file_access('download', rec, 'denied', 'No approved request or token expired')
            db.session.commit()
            flash('You need an approved download request. Use the Request button.', 'warning')
            return redirect(url_for('fim_monitoring'))
        if rec.is_encrypted:
            flash('This file is encrypted. Use the "Decrypt & Download" button to access it securely.', 'warning')
            return redirect(url_for('fim_monitoring'))
        ar.status     = 'executed'
        ar.executed_at = datetime.now(timezone.utc)
        _log_file_access('download', rec, 'executed', f'Request #{ar.id} executed')
    else:
        if rec.is_encrypted:
            flash('This file is encrypted. Use the "Decrypt & Download" button to access it securely.', 'warning')
            return redirect(url_for('fim_monitoring'))
        _log_file_access('download', rec, 'success')
    log_activity('download', f'Downloaded "{rec.original_name}"')
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_FOLDER'], rec.stored_name,
                               as_attachment=True, download_name=rec.original_name)


@app.route('/decrypt/<file_uuid>', methods=['POST'])
@login_required
@limiter.limit('5 per minute')
def decrypt_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    # Admins can decrypt directly; non-admins need clearance then an approved ActionRequest token
    if not current_user.is_admin:
        if not current_user.can_view_file(rec):
            _log_file_access('download', rec, 'denied',
                             f'Clearance L{current_user.clearance_level} insufficient for L{rec.classification} file')
            db.session.commit()
            _notify(
                f'Access Denied — {rec.original_name}',
                f'User:            {current_user.full_name} ({current_user.email})\n'
                f'File:            {rec.original_name}\n'
                f'Action:          Decrypt & Download\n'
                f'User clearance:  L{current_user.clearance_level} {current_user.clearance_label}\n'
                f'File class.:     L{rec.classification} {rec.classification_label}\n'
                f'Reason:          Clearance level insufficient',
            )
            return jsonify(success=False, error=f'Access denied — your clearance (L{current_user.clearance_level}) is below the required level for this file.'), 403
        token = request.form.get('token', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=rec.id,
            requested_by_id=current_user.id, action_type='download', status='approved',
        ).first()
        if not ar or ar.is_expired:
            _log_file_access('download', rec, 'denied', 'No approved request or token expired')
            db.session.commit()
            return jsonify(success=False, error='No approved download request found or it has expired.'), 403
        ar.status      = 'executed'
        ar.executed_at = datetime.now(timezone.utc)
    locked, lock_msg = _check_pw_locked(current_user.id)
    if locked:
        return jsonify(success=False, error=lock_msg), 429
    password = request.form.get('password', '')
    if not current_user.check_password(password):
        _log_file_access('download', rec, 'denied', 'Wrong password at execution step')
        db.session.commit()
        now_locked = _record_pw_fail(current_user.id, current_user.full_name, current_user.email, f'Decrypt "{rec.original_name}"')
        err = 'Too many failed attempts — you are locked out for 15 minutes.' if now_locked else 'Incorrect password. Use your FileVault login password.'
        return jsonify(success=False, error=err), 401
    _pw_attempts.pop(current_user.id, None)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], rec.stored_name)
    if not os.path.exists(file_path):
        return jsonify(success=False, error='File not found on server. Please re-upload the file.'), 404
    with open(file_path, 'rb') as fh:
        data = fh.read()
    if rec.is_encrypted:
        if not _enc_key_raw:
            return jsonify(success=False, error='Encryption key not configured on server.'), 500
        try:
            data = _file_fernet(rec.stored_name).decrypt(data)
        except Exception:
            return jsonify(success=False, error='Decryption failed — file may be corrupted or key mismatch.'), 500
    log_activity('download', f'Downloaded (decrypted) "{rec.original_name}"')
    _log_file_access('download', rec, 'executed' if not current_user.is_admin else 'success')
    db.session.commit()
    from io import BytesIO
    return send_file(
        BytesIO(data),
        as_attachment=True,
        download_name=rec.original_name,
        mimetype=rec.mimetype or 'application/octet-stream',
    )


@app.route('/preview-auth/<file_uuid>', methods=['POST'])
@login_required
@limiter.limit('10 per minute')
def preview_auth(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if not current_user.is_admin:
        if not current_user.can_view_file(rec):
            _log_file_access('preview', rec, 'denied',
                             f'Clearance L{current_user.clearance_level} insufficient for L{rec.classification} file')
            db.session.commit()
            _notify(
                f'Access Denied — {rec.original_name}',
                f'User:            {current_user.full_name} ({current_user.email})\n'
                f'File:            {rec.original_name}\n'
                f'Action:          Preview\n'
                f'User clearance:  L{current_user.clearance_level} {current_user.clearance_label}\n'
                f'File class.:     L{rec.classification} {rec.classification_label}\n'
                f'Reason:          Clearance level insufficient',
            )
            return jsonify(success=False, error=f'Access denied — your clearance (L{current_user.clearance_level}) is below the required level for this file.'), 403
    data = request.get_json(silent=True) or {}
    password = data.get('password', '')
    if not password or not current_user.check_password(password):
        return jsonify(success=False, error='Incorrect password. Please try again.'), 401
    session[f'pv_{file_uuid}'] = True
    log_activity('preview', f'Opened "{rec.original_name}"')
    return jsonify(success=True,
                   preview_url=url_for('preview_file', file_uuid=file_uuid),
                   mimetype=rec.mimetype or '',
                   filename=rec.original_name)


@app.route('/preview/<file_uuid>')
@login_required
def preview_file(file_uuid):
    if not session.pop(f'pv_{file_uuid}', False):
        abort(403)
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    return send_from_directory(app.config['UPLOAD_FOLDER'], rec.stored_name,
                               mimetype=rec.mimetype or 'application/octet-stream')


@app.route('/delete/<file_uuid>', methods=['POST'])
@login_required
def delete_file(file_uuid):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if not current_user.is_admin:
        # Non-admins must have an approved ActionRequest token + correct password
        token    = request.form.get('token', '')
        password = request.form.get('password', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=rec.id,
            requested_by_id=current_user.id, action_type='delete', status='approved',
        ).first()
        if not ar or ar.is_expired:
            _log_file_access('delete', rec, 'denied', 'No approved request or token expired')
            db.session.commit()
            return (jsonify(success=False, error='Admin approval required before deletion.'), 403) if is_ajax else abort(403)
        locked, lock_msg = _check_pw_locked(current_user.id)
        if locked:
            return (jsonify(success=False, error=lock_msg), 429) if is_ajax else abort(429)
        if not current_user.check_password(password):
            _log_file_access('delete', rec, 'denied', 'Wrong password at execution step')
            db.session.commit()
            now_locked = _record_pw_fail(current_user.id, current_user.full_name, current_user.email, f'Delete "{rec.original_name}"')
            err = 'Too many failed attempts — you are locked out for 15 minutes.' if now_locked else 'Incorrect password.'
            return (jsonify(success=False, error=err), 401) if is_ajax else abort(403)
        _pw_attempts.pop(current_user.id, None)
        ar.status      = 'executed'
        ar.executed_at = datetime.now(timezone.utc)

    name, stored = rec.original_name, rec.stored_name
    was_monitored = rec.monitoring_enabled

    # Emit High-severity alert BEFORE cascade-delete wipes the record
    if was_monitored:
        try:
            socketio.emit('integrity_alert', {
                'alert_id':  None,
                'type':      'file_deleted',
                'severity':  'high',
                'title':     f'Protected file deleted: {name}',
                'filename':  name,
                'file_uuid': rec.uuid,
                'raised_at': datetime.now(timezone.utc).isoformat(),
                'sound':     True,
            })
        except Exception:
            pass

    log_activity('delete', f'Deleted "{name}"')
    db.session.delete(rec)
    db.session.commit()

    disk = os.path.join(app.config['UPLOAD_FOLDER'], stored)
    if os.path.exists(disk):
        os.remove(disk)

    _log_file_access('delete', None, 'success', f'File "{name}" permanently deleted')
    broadcast_event('delete', f'{current_user.full_name} deleted "{name}"',
                    name, current_user.full_name)
    _notify(
        f'File Deleted — {name}',
        f'File:      {name}\n'
        f'Deleted by: {current_user.full_name}\n'
        f'IP:         {_get_real_ip()}',
    )
    if is_ajax:
        return jsonify(success=True)
    flash(f'"{name}" deleted.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/rename/<file_uuid>', methods=['POST'])
@login_required
def rename_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if not current_user.is_admin:
        token    = request.form.get('token', '')
        password = request.form.get('password', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=rec.id,
            requested_by_id=current_user.id, action_type='rename', status='approved',
        ).first()
        if not ar or ar.is_expired:
            _log_file_access('rename', rec, 'denied', 'No approved request')
            db.session.commit()
            return jsonify(success=False, error='Admin approval required before renaming.'), 403
        locked, lock_msg = _check_pw_locked(current_user.id)
        if locked:
            return jsonify(success=False, error=lock_msg), 429
        if not current_user.check_password(password):
            _log_file_access('rename', rec, 'denied', 'Wrong password at execution step')
            db.session.commit()
            now_locked = _record_pw_fail(current_user.id, current_user.full_name, current_user.email, f'Rename "{rec.original_name}"')
            err = 'Too many failed attempts — you are locked out for 15 minutes.' if now_locked else 'Incorrect password.'
            return jsonify(success=False, error=err), 401
        _pw_attempts.pop(current_user.id, None)
        ar.status      = 'executed'
        ar.executed_at = datetime.now(timezone.utc)
    new_name = request.form.get('name', '').strip()
    if not new_name:
        return jsonify(success=False, error='Name cannot be empty'), 400
    ext = rec.original_name.rsplit('.', 1)[-1] if '.' in rec.original_name else ''
    if ext and not new_name.lower().endswith('.' + ext.lower()):
        new_name += '.' + ext
    old_name = rec.original_name
    rec.original_name = secure_filename(new_name)
    log_activity('rename', f'Renamed "{old_name}" → "{rec.original_name}"')
    _log_file_access('rename', rec, 'executed' if not current_user.is_admin else 'success',
                     f'{old_name} → {rec.original_name}')

    # Generate Medium integrity alert for rename event
    alert_generated = False
    if rec.monitoring_enabled:
        try:
            baseline = rec.current_baseline
            chk = IntegrityCheck(
                file_id              = rec.id,
                baseline_id          = baseline.id if baseline else None,
                status               = 'ok',
                triggered_by         = 'user',
                triggered_by_user_id = current_user.id,
                check_duration_ms    = 0,
            )
            db.session.add(chk)
            db.session.flush()
            alert = IntegrityAlert(
                file_id      = rec.id,
                check_id     = chk.id,
                severity     = 'medium',
                alert_type   = 'file_renamed',
                title        = f'File renamed: "{old_name}" → "{rec.original_name}"',
                description  = (
                    f'File was renamed by {current_user.full_name}\n'
                    f'Old name: {old_name}\n'
                    f'New name: {rec.original_name}'
                ),
                expected_hash = baseline.sha256_hash if baseline else '',
                found_hash    = rec.file_hash,
            )
            db.session.add(alert)
            rec.alert_count += 1
            db.session.flush()
            log_activity('tamper_detected', f'[MEDIUM] File renamed: "{old_name}" → "{rec.original_name}"')
            socketio.emit('integrity_alert', {
                'alert_id':  alert.id,
                'type':      'file_renamed',
                'severity':  'medium',
                'title':     alert.title,
                'filename':  rec.original_name,
                'file_uuid': rec.uuid,
                'raised_at': alert.raised_at.isoformat(),
                'sound':     False,
            })
            alert_generated = True
        except Exception as _ren_exc:
            app.logger.error('Rename alert failed: %s', _ren_exc)

    db.session.commit()
    _notify(
        f'File Renamed — {old_name}',
        f'Old name:   {old_name}\n'
        f'New name:   {rec.original_name}\n'
        f'Renamed by: {current_user.full_name}\n'
        f'IP:         {_get_real_ip()}',
    )
    return jsonify(success=True, name=rec.original_name, alert_generated=alert_generated)


@app.route('/share/<file_uuid>', methods=['POST'])
@login_required
def share_file(file_uuid):
    # Only admins control who has access to files
    if not current_user.is_admin:
        return jsonify(success=False, error='Only administrators can grant file access.'), 403
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    target = db.session.get(User, request.form.get('share_with_user_id', type=int))
    if not target:
        flash('User not found.', 'danger')
        return redirect(url_for('dashboard'))
    if target.clearance_level > rec.classification:
        flash(f'{target.full_name} (clearance {target.clearance_level}) does not have clearance for '
              f'a level-{rec.classification} file.', 'danger')
        return redirect(url_for('admin_panel'))
    if FileShare.query.filter_by(file_id=rec.id, shared_with_id=target.id).first():
        flash(f'Already shared with {target.full_name}.', 'info')
        return redirect(url_for('dashboard'))
    db.session.add(FileShare(file_id=rec.id, shared_with_id=target.id,
                             shared_by_id=current_user.id))
    log_activity('share', f'Granted access to "{rec.original_name}" for {target.full_name}')
    _log_file_access('share', rec, 'success',
                     f'Access granted to {target.full_name} (clearance {target.clearance_level})')
    db.session.commit()
    broadcast_event('share',
                    f'Admin granted "{rec.original_name}" access to {target.full_name}',
                    rec.original_name, current_user.full_name)
    _notify(
        f'File Shared — {rec.original_name}',
        f'File:             {rec.original_name}\n'
        f'Classification:   {rec.classification_label}\n'
        f'Shared with:      {target.full_name} ({target.email})\n'
        f'Their clearance:  L{target.clearance_level} {target.clearance_label}\n'
        f'Shared by:        {current_user.full_name}\n'
        f'IP:               {_get_real_ip()}',
    )
    flash(f'Access granted to {target.full_name}.', 'success')
    return redirect(url_for('dashboard'))


# ---------------------------------------------------------------------------
# Action Request workflow (FBI-style: request → approve/reject → password → execute)
# ---------------------------------------------------------------------------

@app.route('/request-action/<file_uuid>', methods=['POST'])
@login_required
@limiter.limit('20 per hour')
def submit_action_request(file_uuid):
    """User requests permission for download/edit/rename/delete. Admin must approve."""
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()

    # Non-admins must have sufficient clearance to request any action
    if not current_user.is_admin and not current_user.can_view_file(rec):
        return jsonify(success=False,
                       error=f'Access denied — your clearance level (L{current_user.clearance_level} {current_user.clearance_label}) '
                             f'is insufficient for this file (L{rec.classification} {rec.classification_label}).'), 403

    action_type   = request.form.get('action_type', '').strip()
    justification = request.form.get('justification', '').strip()
    if action_type not in ('download', 'edit', 'rename', 'delete', 'replace'):
        return jsonify(success=False, error='Invalid action type.'), 400
    if action_type == 'replace' and (current_user.clearance_level or 5) > 2:
        return jsonify(success=False, error='File replacement requests require L1 or L2 clearance.'), 403
    if not justification:
        return jsonify(success=False, error='Justification is required.'), 400

    # Check if there's already a pending request for the same file+action
    existing = ActionRequest.query.filter_by(
        file_id=rec.id, requested_by_id=current_user.id,
        action_type=action_type, status='pending',
    ).first()
    if existing:
        return jsonify(success=False, error='You already have a pending request for this action.'), 409

    ar = ActionRequest(
        file_id         = rec.id,
        requested_by_id = current_user.id,
        action_type     = action_type,
        justification   = justification[:1000],
    )
    db.session.add(ar)
    _log_file_access(action_type, rec, 'requested',
                     f'Requested {action_type} — justification: {justification[:200]}')
    log_activity('request_submitted',
                 f'Submitted {action_type} request for "{rec.original_name}" — {justification[:200]}')
    db.session.commit()

    # Notify admin via SocketIO (real-time) and email
    socketio.emit('action_request_new', {
        'request_id':  ar.id,
        'action':      action_type,
        'file':        rec.original_name,
        'user':        current_user.full_name,
        'clearance':   current_user.clearance_level,
        'timestamp':   ar.requested_at.strftime('%H:%M:%S'),
    })
    _notify(
        f'New {action_type.title()} Request — {rec.original_name}',
        f'User:             {current_user.full_name} ({current_user.email})\n'
        f'File:             {rec.original_name}\n'
        f'Action:           {action_type.title()}\n'
        f'User clearance:   L{current_user.clearance_level} {current_user.clearance_label}\n'
        f'File class.:      L{rec.classification} {rec.classification_label}\n'
        f'Justification:    {justification[:500]}\n\n'
        f'Log in to FileVault to approve or reject this request.',
    )
    return jsonify(success=True, request_id=ar.id,
                   message='Request submitted. You will be notified when the administrator reviews it.')


@app.route('/admin/test-email', methods=['POST'])
@login_required
def admin_test_email():
    """Send a test email synchronously and return the exact result."""
    if not current_user.is_admin:
        abort(403)
    recipient = app.config.get('NOTIFICATION_EMAIL', '').strip()
    api_key   = resend.api_key or ''

    if not api_key:
        return jsonify(success=False, error='RESEND_API_KEY is not set in Railway variables.',
                       config={'RESEND_API_KEY': '(empty)', 'NOTIFICATION_EMAIL': recipient or '(empty)'})
    if not recipient:
        return jsonify(success=False, error='NOTIFICATION_EMAIL is not set in Railway variables.',
                       config={'RESEND_API_KEY': f'(set, length={len(api_key)})', 'NOTIFICATION_EMAIL': '(empty)'})

    ts   = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    text = (f'This is a test notification from FileVault.\n\n'
            f'If you received this, Resend email notifications are working correctly.\n\n'
            f'Sent: {ts}\nTo:   {recipient}')
    ok, err = _resend_email(recipient, '[FileVault] Test email — Resend check', text)
    if ok:
        return jsonify(success=True,
                       message=f'Test email sent to {recipient} via Resend. Check your inbox (and spam folder).')
    return jsonify(success=False, error=err or 'Resend API call failed.',
                   config={'RESEND_API_KEY': f'(set, length={len(api_key)})', 'NOTIFICATION_EMAIL': recipient})


@app.route('/admin/action-requests')
@login_required
def admin_action_requests():
    if not current_user.is_admin:
        abort(403)
    status_filter = request.args.get('status', 'pending')
    q = ActionRequest.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    reqs = q.order_by(ActionRequest.requested_at.desc()).all()
    return render_template('admin/action_requests.html',
                           requests=reqs, status_filter=status_filter)


@app.route('/admin/action-requests/<int:req_id>/approve', methods=['POST'])
@login_required
def admin_approve_action_request(req_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    ar = ActionRequest.query.get_or_404(req_id)
    if ar.status != 'pending':
        return jsonify(success=False, error='Request already reviewed'), 400

    reason = request.form.get('reason', '').strip()
    import secrets as _sec
    ar.status       = 'approved'
    ar.reviewed_by_id = current_user.id
    ar.reviewed_at  = datetime.now(timezone.utc)
    ar.admin_reason = reason or 'Approved.'
    ar.exec_token   = _sec.token_urlsafe(32)
    ar.expires_at   = datetime.now(timezone.utc) + timedelta(minutes=30)
    _log_file_access(ar.action_type, ar.file, 'approved',
                     f'Approved by {current_user.full_name}: {reason}')
    log_activity('request_approved',
                 f'Approved {ar.action_type} request #{ar.id} for "{ar.file.original_name if ar.file else "?"}" '
                 f'by {ar.requested_by.full_name} — {reason or "No note"}')
    db.session.commit()

    _notify(
        f'Request Approved — {ar.action_type.title()} on {ar.file.original_name if ar.file else "file"}',
        f'Admin:      {current_user.full_name}\n'
        f'User:       {ar.requested_by.full_name} ({ar.requested_by.email})\n'
        f'File:       {ar.file.original_name if ar.file else "(deleted)"}\n'
        f'Action:     {ar.action_label}\n'
        f'Note:       {reason or "—"}\n'
        f'Expires in: 30 minutes\n'
        f'Request ID: #{ar.id}',
    )

    # Notify user via SocketIO (real-time) and email
    socketio.emit('action_request_update', {
        'request_id':  ar.id,
        'status':      'approved',
        'reason':      ar.admin_reason,
        'token':       ar.exec_token,
        'expires_at':  ar.expires_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'user_id':     ar.requested_by_id,
        'action_type': ar.action_type,
        'file_uuid':   ar.file.uuid if ar.file else '',
    })
    _resend_email(
        ar.requested_by.email,
        f'[FileVault] Your {ar.action_label} request was APPROVED',
        f'Hello {ar.requested_by.full_name},\n\n'
        f'Your request to {ar.action_label.lower()} "{ar.file.original_name if ar.file else "the file"}" '
        f'has been APPROVED by the administrator.\n\n'
        f'Note: {ar.admin_reason}\n\n'
        f'You have 30 minutes to execute the action. Log in to FileVault now.\n\n'
        f'--- FileVault',
    )
    return jsonify(success=True, message='Request approved. User notified with execution token.')


@app.route('/admin/action-requests/<int:req_id>/reject', methods=['POST'])
@login_required
def admin_reject_action_request(req_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    ar = ActionRequest.query.get_or_404(req_id)
    if ar.status != 'pending':
        return jsonify(success=False, error='Request already reviewed'), 400

    reason = request.form.get('reason', '').strip()
    if not reason:
        return jsonify(success=False, error='Rejection reason is required.'), 400

    ar.status         = 'rejected'
    ar.reviewed_by_id = current_user.id
    ar.reviewed_at    = datetime.now(timezone.utc)
    ar.admin_reason   = reason
    _log_file_access(ar.action_type, ar.file, 'rejected',
                     f'Rejected by {current_user.full_name}: {reason}')
    log_activity('request_rejected',
                 f'Rejected {ar.action_type} request #{ar.id} for "{ar.file.original_name if ar.file else "?"}" '
                 f'by {ar.requested_by.full_name} — {reason}')
    db.session.commit()

    _notify(
        f'Request Rejected — {ar.action_type.title()} on {ar.file.original_name if ar.file else "file"}',
        f'Admin:    {current_user.full_name}\n'
        f'User:     {ar.requested_by.full_name} ({ar.requested_by.email})\n'
        f'File:     {ar.file.original_name if ar.file else "(deleted)"}\n'
        f'Action:   {ar.action_label}\n'
        f'Reason:   {reason}\n'
        f'Request ID: #{ar.id}',
    )

    socketio.emit('action_request_update', {
        'request_id': ar.id,
        'status':     'rejected',
        'reason':     reason,
        'user_id':    ar.requested_by_id,
    })
    _resend_email(
        ar.requested_by.email,
        f'[FileVault] Your {ar.action_label} request was REJECTED',
        f'Hello {ar.requested_by.full_name},\n\n'
        f'Your request to {ar.action_label.lower()} "{ar.file.original_name if ar.file else "the file"}" '
        f'has been REJECTED by the administrator.\n\n'
        f'Reason: {reason}\n\n'
        f'You may submit a new request with a revised justification if needed.\n\n'
        f'--- FileVault',
    )
    return jsonify(success=True, message='Request rejected. User notified.')


@app.route('/admin/event-monitor')
@login_required
def admin_event_monitor():
    if not current_user.is_admin:
        abort(403)
    recent = FileAccessLog.query.order_by(
        FileAccessLog.timestamp.desc()
    ).limit(200).all()
    return render_template('admin/event_monitor.html', recent_events=recent)


@app.route('/api/admin/event-monitor/join', methods=['POST'])
@login_required
def join_monitor_room():
    """Client calls this to subscribe to admin_monitor SocketIO room."""
    if not current_user.is_admin:
        return jsonify(success=False), 403
    from flask_socketio import join_room
    join_room('admin_monitor')
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# Public share links
# ---------------------------------------------------------------------------
@app.route('/share-link/create/<file_uuid>', methods=['POST'])
@login_required
def create_share_link(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id:
        abort(403)
    days = request.form.get('expires_days', type=int)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)) if days else None
    tok = ShareToken(file_id=rec.id, created_by_id=current_user.id, expires_at=expires_at)
    db.session.add(tok)
    log_activity('share', f'Created public link for "{rec.original_name}"')
    db.session.commit()
    link = url_for('public_shared_file', token_str=tok.token, _external=True)
    return jsonify(success=True, link=link, token=tok.token)


@app.route('/share-link/delete/<token_str>', methods=['POST'])
@login_required
def delete_share_link(token_str):
    tok = ShareToken.query.filter_by(token=token_str).first_or_404()
    if tok.created_by_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(tok)
    db.session.commit()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# Sharing API — AJAX endpoints used by the Share modal
# ---------------------------------------------------------------------------
@app.route('/api/share/<file_uuid>', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def api_share_file(file_uuid):
    # Only admins can grant file access
    if not current_user.is_admin:
        return jsonify(success=False, error='Only administrators can grant file access.'), 403
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    email = (request.json or {}).get('email', '').strip().lower() if request.is_json \
            else request.form.get('email', '').strip().lower()
    if not email:
        return jsonify(success=False, error='Enter an email address.'), 400
    target = User.query.filter(db.func.lower(User.email) == email).first()
    if not target:
        return jsonify(success=False, error='No account found with that email.'), 404
    if target.clearance_level > rec.classification:
        return jsonify(success=False,
            error=f'{target.full_name} has clearance level {target.clearance_level} but this file '
                  f'requires level {rec.classification} or higher.'), 403
    if FileShare.query.filter_by(file_id=rec.id, shared_with_id=target.id).first():
        return jsonify(success=False, error=f'Already shared with {target.full_name}.'), 409
    db.session.add(FileShare(file_id=rec.id, shared_with_id=target.id, shared_by_id=current_user.id))
    log_activity('share', f'Granted access to "{rec.original_name}" → {target.full_name}')
    _log_file_access('share', rec, 'success',
                     f'Access granted to {target.full_name} (clearance {target.clearance_level})')
    db.session.commit()
    return jsonify(success=True, message=f'Access granted to {target.full_name}.', user={
        'id': target.id, 'name': target.full_name, 'email': target.email,
    })


@app.route('/api/unshare/<file_uuid>/<int:user_id>', methods=['POST'])
@login_required
def api_unshare_file(file_uuid, user_id):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id and not current_user.is_admin:
        return jsonify(success=False, error='Forbidden'), 403
    share = FileShare.query.filter_by(file_id=rec.id, shared_with_id=user_id).first()
    if not share:
        return jsonify(success=False, error='Share not found.'), 404
    target_name = share.shared_with.full_name
    db.session.delete(share)
    log_activity('share', f'Removed "{rec.original_name}" access for {target_name}')
    db.session.commit()
    return jsonify(success=True)


@app.route('/api/file/<file_uuid>/shares')
@login_required
def api_file_shares(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id and not current_user.is_admin:
        return jsonify(success=False, error='Forbidden'), 403
    return jsonify(success=True, shares=[
        {'user_id': s.shared_with_id, 'name': s.shared_with.full_name, 'email': s.shared_with.email}
        for s in rec.shares
    ])


@app.route('/s/<token_str>')
def public_shared_file(token_str):
    tok = ShareToken.query.filter_by(token=token_str).first_or_404()
    if tok.is_expired:
        abort(410)
    return render_template('shared_link.html', file=tok.file, token=tok)


@app.route('/s/<token_str>/download')
def public_download_file(token_str):
    tok = ShareToken.query.filter_by(token=token_str).first_or_404()
    if tok.is_expired:
        abort(410)
    tok.download_count += 1
    db.session.commit()
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], tok.file.stored_name)
    return send_from_directory(app.config['UPLOAD_FOLDER'], tok.file.stored_name,
                               as_attachment=True, download_name=tok.file.original_name)


# ---------------------------------------------------------------------------
# My Requests (non-admin: view own ActionRequest history)
# ---------------------------------------------------------------------------
@app.route('/my-requests')
@login_required
def my_requests():
    if current_user.is_admin:
        return redirect(url_for('admin_action_requests'))
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    q = ActionRequest.query.filter_by(requested_by_id=current_user.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    reqs = q.order_by(ActionRequest.requested_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('fim/my_requests.html', requests=reqs, status_filter=status_filter)


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------
@app.route('/activity')
@login_required
def activity_log():
    page          = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', '')
    user_filter   = request.args.get('user_id', '', type=str)
    section       = request.args.get('section', 'all' if current_user.is_admin else 'mine')

    if current_user.is_admin:
        if section == 'mine':
            q = ActivityLog.query.filter_by(user_id=current_user.id)
        else:
            q = ActivityLog.query
            if user_filter:
                try:
                    q = q.filter_by(user_id=int(user_filter))
                except ValueError:
                    pass
    else:
        q = ActivityLog.query.filter_by(user_id=current_user.id)
        section = 'mine'

    if action_filter:
        q = q.filter_by(action=action_filter)

    logs  = q.order_by(ActivityLog.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    users = User.query.order_by(User.full_name).all() if current_user.is_admin else []

    return render_template('activity.html', logs=logs,
                           action_filter=action_filter,
                           user_filter=user_filter,
                           section=section,
                           users=users,
                           action_icons=ACTION_ICONS)


@app.route('/activity/export')
@login_required
def export_activity_csv():
    q = ActivityLog.query if current_user.is_admin else \
        ActivityLog.query.filter_by(user_id=current_user.id)
    all_logs = q.order_by(ActivityLog.created_at.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Date', 'User', 'Email', 'Action', 'Details', 'IP Address'])
    for entry in all_logs:
        writer.writerow([
            entry.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            entry.user.full_name if entry.user else 'Unknown',
            entry.user.email     if entry.user else '',
            entry.action,
            entry.detail,
            entry.ip_address or '',
        ])
    output = io.BytesIO(buf.getvalue().encode('utf-8-sig'))
    fname = f'filevault_logs_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.csv'
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name=fname)


@app.route('/bulk-delete', methods=['POST'])
@login_required
def bulk_delete():
    uuids = request.form.getlist('uuids')
    deleted = 0
    for uid in uuids:
        rec = File.query.filter_by(uuid=uid, user_id=current_user.id).first()
        if rec:
            disk = os.path.join(app.config['UPLOAD_FOLDER'], rec.stored_name)
            if os.path.exists(disk):
                os.remove(disk)
            name = rec.original_name
            db.session.delete(rec)
            log_activity('delete', f'Bulk deleted "{name}"')
            deleted += 1
    db.session.commit()
    return jsonify(success=True, deleted=deleted)


@app.route('/bulk-download', methods=['POST'])
@login_required
def bulk_download():
    uuids = request.form.getlist('uuids')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for uid in uuids:
            rec = File.query.filter_by(uuid=uid, user_id=current_user.id).first()
            if not rec:
                continue
            path = os.path.join(app.config['UPLOAD_FOLDER'], rec.stored_name)
            if not os.path.exists(path):
                continue
            with open(path, 'rb') as fh:
                raw = fh.read()
            zf.writestr(rec.original_name, raw)
    buf.seek(0)
    log_activity('download', f'Bulk downloaded {len(uuids)} file(s) as ZIP')
    db.session.commit()
    fname = f'filevault_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.zip'
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=fname)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        abort(403)
    search = request.args.get('q', '').strip()
    q = User.query
    if search:
        q = q.filter(
            db.or_(User.full_name.ilike(f'%{search}%'),
                   User.email.ilike(f'%{search}%')))
    users = q.order_by(User.created_at).all()

    raw_stats = db.session.query(
        File.user_id,
        func.count(File.id),
        func.coalesce(func.sum(File.size), 0)
    ).group_by(File.user_id).all()
    file_stats = {uid: (cnt, total) for uid, cnt, total in raw_stats}

    stats = []
    for u in users:
        count, total = file_stats.get(u.id, (0, 0))
        stats.append({
            'user':       u,
            'file_count': count,
            'total_size': format_bytes(total),
        })
    return render_template('admin.html', user_stats=stats, search=search)


@app.route('/admin/toggle-admin/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        abort(403)
    if user_id == current_user.id:
        flash("You can't change your own admin status.", 'warning')
        return redirect(url_for('admin_panel'))
    user = db.session.get(User, user_id) or abort(404)
    user.is_admin = not user.is_admin
    user.role = 'super_admin' if user.is_admin else 'user'
    db.session.commit()
    flash(f'Admin {"granted to" if user.is_admin else "revoked from"} {user.full_name}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/change-role/<int:user_id>', methods=['POST'])
@login_required
def change_role(user_id):
    # Any admin can assign roles — previously restricted to super_admin only.
    if not current_user.is_admin:
        abort(403)
    if user_id == current_user.id:
        flash("You can't change your own role.", 'warning')
        return redirect(url_for('admin_panel'))
    user = db.session.get(User, user_id) or abort(404)
    new_role = request.form.get('role', 'user')
    if new_role not in ('super_admin', 'user'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('admin_panel'))
    user.role = new_role
    user.is_admin = new_role == 'super_admin'
    db.session.commit()
    log_activity('profile', f'Changed role of {user.full_name} to {new_role}')
    db.session.commit()
    flash(f'Role of {user.full_name} changed to {new_role.replace("_", " ").title()}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/set-clearance/<int:user_id>', methods=['POST'])
@login_required
def set_clearance(user_id):
    if not current_user.is_admin:
        abort(403)
    user = db.session.get(User, user_id) or abort(404)
    level = request.form.get('clearance_level', 5, type=int)
    if level not in (1, 2, 3, 4, 5):
        flash('Invalid clearance level.', 'danger')
        return redirect(url_for('admin_panel'))
    user.clearance_level = level
    db.session.commit()
    log_activity('profile', f'Set clearance of {user.full_name} to L{level} ({user.clearance_label})')
    _log_file_access('copy', None, 'success',
                     f'Admin set clearance of {user.full_name} to L{level}')
    db.session.commit()
    flash(f'Clearance of {user.full_name} set to L{level} {user.clearance_label}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/verify/<file_uuid>')
@login_required
def verify_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if not rec.file_hash:
        return jsonify(intact=None, error='No hash stored for this file (uploaded before integrity feature was added).')
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], rec.stored_name)
    try:
        with open(file_path, 'rb') as fh:
            disk_data = fh.read()
        raw_data = disk_data
    except Exception:
        return jsonify(intact=False, error='Could not read file from disk.')
    current_hash = hashlib.sha256(raw_data).hexdigest()
    intact = current_hash == rec.file_hash
    if not intact:
        log_activity('integrity_fail', f'Hash mismatch for "{rec.original_name}" — possible tampering!')
        db.session.commit()
        socketio.emit('security_alert', {
            'message': f'File integrity FAILED for "{rec.original_name}" (user: {current_user.full_name})',
            'ip': request.remote_addr,
            'timestamp': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            'level': 'danger',
        })
    return jsonify(intact=intact, stored_hash=rec.file_hash, current_hash=current_hash)


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        abort(403)
    if user_id == current_user.id:
        flash("You can't delete your own account here.", 'warning')
        return redirect(url_for('admin_panel'))
    user = db.session.get(User, user_id) or abort(404)
    for f in user.files:
        disk = os.path.join(app.config['UPLOAD_FOLDER'], f.stored_name)
        if os.path.exists(disk):
            os.remove(disk)
    FileShare.query.filter_by(shared_with_id=user_id).delete()
    FileShare.query.filter_by(shared_by_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.full_name} deleted.', 'success')
    return redirect(url_for('admin_panel'))


# ---------------------------------------------------------------------------
# FIM — Monitoring (file list with integrity status)
# ---------------------------------------------------------------------------
@app.route('/fim/monitoring')
@login_required
def fim_monitoring():
    query  = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    sort   = request.args.get('sort', 'date')
    order  = request.args.get('order', 'desc')
    page   = request.args.get('page', 1, type=int)

    if current_user.is_admin:
        q = File.query
    else:
        q = File.query
    if query:
        q = q.filter(File.original_name.ilike(f'%{query}%'))
    if status:
        q = q.filter_by(current_status=status)

    sort_col = {
        'name':       File.original_name,
        'status':     File.current_status,
        'last_check': File.last_checked_at,
        'alerts':     File.alert_count,
        'size':       File.size,
    }.get(sort, File.uploaded_at)
    q = q.order_by(sort_col.asc() if order == 'asc' else sort_col.desc())
    pagination = q.paginate(page=page, per_page=PER_PAGE, error_out=False)

    policies  = MonitoringPolicy.query.filter_by(is_active=True).all()

    file_ids = [f.id for f in pagination.items]

    # Admin: pending requests per file for inline approve/reject
    pending_by_file = {}
    if current_user.is_admin and file_ids:
        for ar in ActionRequest.query.filter(
            ActionRequest.file_id.in_(file_ids),
            ActionRequest.status == 'pending',
        ).all():
            pending_by_file.setdefault(ar.file_id, []).append(ar)

    # Non-admin: their own approved (not yet expired/executed) requests per file
    my_approved_by_file = {}
    if not current_user.is_admin and file_ids:
        now_naive = datetime.utcnow()  # naive UTC — matches db.DateTime storage
        for ar in ActionRequest.query.filter(
            ActionRequest.file_id.in_(file_ids),
            ActionRequest.requested_by_id == current_user.id,
            ActionRequest.status == 'approved',
            ActionRequest.expires_at > now_naive,
        ).order_by(ActionRequest.reviewed_at.desc()).all():
            if ar.file_id not in my_approved_by_file:  # most-recently-approved wins
                my_approved_by_file[ar.file_id] = ar

    return render_template('fim/monitoring.html',
        files=pagination.items,
        pagination=pagination,
        query=query,
        status_filter=status,
        sort=sort,
        order=order,
        policies=policies,
        pending_by_file=pending_by_file,
        my_approved_by_file=my_approved_by_file,
    )


# ---------------------------------------------------------------------------
# FIM — File detail / check history
# ---------------------------------------------------------------------------
@app.route('/fim/file/<int:file_id>')
@login_required
def fim_file_status(file_id):
    file_rec = File.query.get_or_404(file_id)

    page   = request.args.get('page', 1, type=int)
    checks = file_rec.checks.paginate(page=page, per_page=20, error_out=False)
    alerts = file_rec.fim_alerts.all()

    return render_template('fim/integrity_status.html',
        file=file_rec,
        checks=checks,
        alerts=alerts,
        baseline=file_rec.current_baseline,
    )


# ---------------------------------------------------------------------------
# FIM — Manual check
# ---------------------------------------------------------------------------
@app.route('/fim/check/<file_uuid>', methods=['POST'])
@login_required
@limiter.limit('30 per minute')
def fim_manual_check(file_uuid):
    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()

    try:
        result = _fim_check_file(file_rec,
            triggered_by='manual',
            triggered_by_user_id=current_user.id,
        )
        if result['status'] not in ('ok', 'skip'):
            _fim_raise_alert(file_rec, result)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        app.logger.error('fim_manual_check error: %s', exc)
        return jsonify(success=False, error=f'Check failed: {exc}'), 500

    return jsonify(
        success=True,
        status=result['status'],
        check_id=result.get('check_id'),
        message={
            'ok':      'File integrity verified — no changes detected.',
            'tampered':'⚠ Hash mismatch detected! Alert raised.',
            'missing': '⚠ File is missing from disk! Alert raised.',
            'error':   'Check error — see alert details.',
            'skip':    'No baseline yet — use Capture Baseline first.',
        }.get(result['status'], result['status']),
    )


# ---------------------------------------------------------------------------
# FIM — Reset / accept baseline
# ---------------------------------------------------------------------------
@app.route('/fim/baseline/<file_uuid>/capture', methods=['POST'])
@login_required
@limiter.limit('30 per minute')
def fim_capture_baseline(file_uuid):
    """Capture an initial baseline for a PENDING file (no existing baseline required)."""
    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if file_rec.user_id != current_user.id and not current_user.is_admin:
        return jsonify(success=False, error='Forbidden'), 403
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    if not os.path.exists(filepath):
        return jsonify(success=False, error=f'File not found on disk: {file_rec.stored_name}'), 404
    try:
        baseline = _fim_capture_baseline(file_rec, current_user, reason='manual_capture')
        if baseline is None:
            return jsonify(success=False, error='Hash computation failed — check server logs'), 500
        log_activity('baseline_reset', f'Captured initial baseline for "{file_rec.original_name}"')
        db.session.commit()
        return jsonify(success=True,
                       message=f'Baseline captured. SHA-256: {baseline.sha256_hash[:16]}…',
                       hash=baseline.sha256_hash)
    except Exception as exc:
        db.session.rollback()
        app.logger.error('fim_capture_baseline error: %s', exc)
        return jsonify(success=False, error=f'Database error: {exc}'), 500


@app.route('/fim/baseline/<file_uuid>/reset', methods=['POST'])
@login_required
@limiter.limit('30 per minute')
def fim_reset_baseline(file_uuid):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    if not os.path.exists(filepath):
        return jsonify(success=False, error=f'File not found on disk: {file_rec.stored_name}'), 404
    note = request.form.get('note', '').strip()
    try:
        ok = _fim_accept_baseline(file_rec, current_user, note=note or 'Baseline reset by admin')
        if not ok:
            return jsonify(success=False, error='Hash computation failed — check server logs'), 500
        log_activity('baseline_reset', f'Reset baseline for "{file_rec.original_name}"')
        db.session.commit()
        return jsonify(success=True, message='Baseline updated and all open alerts resolved.')
    except Exception as exc:
        db.session.rollback()
        app.logger.error('fim_reset_baseline error: %s', exc)
        return jsonify(success=False, error=f'Database error: {exc}'), 500



# ---------------------------------------------------------------------------
# FIM — Alert actions (acknowledge / resolve / false-positive / escalate /
#        assign / comment)
# ---------------------------------------------------------------------------
def _get_alert_for_action(alert_id):
    alert = IntegrityAlert.query.get_or_404(alert_id)
    return alert


@app.route('/fim/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
def fim_alert_acknowledge(alert_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    alert = _get_alert_for_action(alert_id)
    if alert.status not in ('open', 'escalated'):
        return jsonify(success=False, error='Alert is already closed'), 400
    alert.acknowledge(current_user)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/resolve', methods=['POST'])
@login_required
def fim_alert_resolve(alert_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    alert       = _get_alert_for_action(alert_id)
    res_type    = request.form.get('resolution_type', 'investigated')
    note        = request.form.get('note', '').strip()
    alert.resolve(current_user, res_type, note)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/false-positive', methods=['POST'])
@login_required
def fim_alert_false_positive(alert_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    alert = _get_alert_for_action(alert_id)
    note  = request.form.get('note', '').strip()
    alert.mark_false_positive(current_user, note)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/escalate', methods=['POST'])
@login_required
def fim_alert_escalate(alert_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    alert     = _get_alert_for_action(alert_id)
    to_uid    = request.form.get('to_user_id', type=int)
    to_user   = db.session.get(User, to_uid) if to_uid else None
    if not to_user:
        return jsonify(success=False, error='Target user not found'), 400
    alert.escalate(to_user, current_user)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/assign', methods=['POST'])
@login_required
def fim_alert_assign(alert_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    alert   = IntegrityAlert.query.get_or_404(alert_id)
    to_uid  = request.form.get('to_user_id', type=int)
    to_user = db.session.get(User, to_uid) if to_uid else None
    if not to_user:
        return jsonify(success=False, error='User not found'), 400
    alert.assign(to_user, current_user)
    db.session.commit()
    return jsonify(success=True, assignee=to_user.full_name)


@app.route('/fim/alerts/<int:alert_id>/comment', methods=['POST'])
@login_required
def fim_alert_comment(alert_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    alert   = _get_alert_for_action(alert_id)
    text    = request.form.get('comment', '').strip()
    is_int  = request.form.get('internal', '0') == '1'
    if not text:
        return jsonify(success=False, error='Comment cannot be empty'), 400
    comment = AlertComment(
        alert_id=alert.id,
        user_id=current_user.id,
        comment=text,
        is_internal=is_int,
    )
    db.session.add(comment)
    db.session.commit()
    return jsonify(
        success=True,
        comment_id=comment.id,
        author=current_user.full_name,
        text=text,
        created_at=comment.created_at.strftime('%b %d, %Y %H:%M'),
    )


# ---------------------------------------------------------------------------
# FIM — Analytics
# ---------------------------------------------------------------------------
@app.route('/fim/analytics')
@login_required
def fim_analytics():
    return render_template('fim/analytics.html')


@app.route('/fim/analytics/data')
@login_required
def fim_analytics_data():
    days = request.args.get('days', 30, type=int)
    days = min(max(days, 7), 90)

    if current_user.is_admin:
        alert_q = IntegrityAlert.query
        check_q = IntegrityCheck.query
        file_q  = File.query
    else:
        alert_q = IntegrityAlert.query
        check_q = IntegrityCheck.query
        file_q  = File.query

    now = datetime.now(timezone.utc)

    # Daily alerts over requested period
    labels, counts = [], []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).date()
        labels.append(day.strftime('%b %d'))
        counts.append(alert_q.filter(func.date(IntegrityAlert.raised_at) == str(day)).count())

    # Severity distribution of ALL-TIME open alerts
    sev_dist = {s: alert_q.filter_by(status='open', severity=s).count()
                for s in ('critical', 'high', 'medium', 'low', 'info')}

    # File status distribution
    status_dist = {s: file_q.filter_by(current_status=s).count()
                   for s in ('ok', 'tampered', 'missing', 'pending', 'error')}

    # Alert type breakdown (all-time)
    types = {}
    for t in ('hash_mismatch', 'file_missing', 'double_extension', 'repeated_tampering'):
        types[t] = alert_q.filter_by(alert_type=t).count()

    # Check stats (last 7 days)
    week_ago = now - timedelta(days=7)
    total_chk  = check_q.filter(IntegrityCheck.checked_at >= week_ago).count()
    passed_chk = check_q.filter(IntegrityCheck.checked_at >= week_ago,
                                 IntegrityCheck.status == 'ok').count()
    pass_rate  = round(passed_chk / total_chk * 100, 1) if total_chk else 0

    return jsonify(
        trend_labels=labels,
        trend_counts=counts,
        severity_dist=sev_dist,
        status_dist=status_dist,
        type_dist=types,
        check_pass_rate=pass_rate,
        total_checks_7d=total_chk,
    )


# ---------------------------------------------------------------------------

@app.route('/fim/file/<int:file_id>/toggle-monitoring', methods=['POST'])
@login_required
def fim_toggle_monitoring(file_id):
    file_rec = File.query.get_or_404(file_id)
    if file_rec.user_id != current_user.id and not current_user.is_admin:
        return jsonify(success=False, error='Forbidden'), 403
    file_rec.monitoring_enabled = not file_rec.monitoring_enabled
    if not file_rec.monitoring_enabled:
        file_rec.current_status = 'unmonitored'
    db.session.commit()
    return jsonify(success=True, enabled=file_rec.monitoring_enabled)


# ---------------------------------------------------------------------------
# FIM — Reports export (CSV)
# ---------------------------------------------------------------------------
@app.route('/fim/reports/export')
@login_required
def fim_export_report():
    if current_user.is_admin:
        alerts = IntegrityAlert.query.order_by(IntegrityAlert.raised_at.desc()).all()
    else:
        uid_sub = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
        alerts  = (IntegrityAlert.query
                   .filter(IntegrityAlert.file_id.in_(uid_sub))
                   .order_by(IntegrityAlert.raised_at.desc()).all())

    buf    = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'Alert ID', 'Raised At', 'File', 'Alert Type', 'Severity',
        'Status', 'Expected Hash', 'Found Hash',
        'Expected Size', 'Found Size', 'Resolved At', 'Resolution Note',
    ])
    for a in alerts:
        fname = a.file.original_name if a.file else ''
        writer.writerow([
            a.id,
            a.raised_at.strftime('%Y-%m-%d %H:%M:%S'),
            fname,
            a.alert_type,
            a.severity,
            a.status,
            a.expected_hash or '',
            a.found_hash    or '',
            a.expected_size or '',
            a.found_size    or '',
            a.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if a.resolved_at else '',
            a.resolution_note or '',
        ])
    output = io.BytesIO(buf.getvalue().encode('utf-8-sig'))
    fname  = f'fim_report_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.csv'
    return send_file(output, mimetype='text/csv', as_attachment=True, download_name=fname)


# Change-request approval workflow removed — users act directly on their own files.


# ---------------------------------------------------------------------------
# FIM — Replace file content (real modification for monitoring demo)
# ---------------------------------------------------------------------------
@app.route('/fim/replace/<file_uuid>', methods=['POST'])
@login_required
def fim_replace_file(file_uuid):
    """Upload a new version of the file, overwriting it on disk without updating the baseline.
    The next integrity check will detect the hash mismatch and raise a Critical alert."""
    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if not file_rec.monitoring_enabled:
        return jsonify(success=False, error='Monitoring disabled for this file'), 400

    if not current_user.is_admin:
        # Only L1 / L2 clearance users may replace files (with approval)
        if (current_user.clearance_level or 5) > 2:
            return jsonify(success=False, error='File replacement requires L1 or L2 clearance.'), 403
        if not current_user.can_view_file(file_rec):
            return jsonify(success=False, error='Your clearance level is insufficient for this file.'), 403
        token = request.form.get('token', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=file_rec.id,
            requested_by_id=current_user.id, action_type='replace', status='approved',
        ).first()
        if not ar or ar.is_expired:
            return jsonify(success=False, error='Admin approval required before replacing this file.'), 403
        locked, lock_msg = _check_pw_locked(current_user.id)
        if locked:
            return jsonify(success=False, error=lock_msg), 429
        password = request.form.get('password', '')
        if not current_user.check_password(password):
            now_locked = _record_pw_fail(current_user.id, current_user.full_name, current_user.email, f'Replace "{file_rec.original_name}"')
            err = 'Too many failed attempts — you are locked out for 15 minutes.' if now_locked else 'Incorrect password. Please confirm your FileVault password to replace this file.'
            return jsonify(success=False, error=err), 401
        _pw_attempts.pop(current_user.id, None)
        ar.status = 'executed'
        ar.executed_at = datetime.now(timezone.utc)
    else:
        locked, lock_msg = _check_pw_locked(current_user.id)
        if locked:
            return jsonify(success=False, error=lock_msg), 429
        password = request.form.get('password', '')
        if not current_user.check_password(password):
            now_locked = _record_pw_fail(current_user.id, current_user.full_name, current_user.email, f'Replace "{file_rec.original_name}" (admin)')
            err = 'Too many failed attempts — you are locked out for 15 minutes.' if now_locked else 'Incorrect password. Please confirm your FileVault password to replace this file.'
            return jsonify(success=False, error=err), 401
        _pw_attempts.pop(current_user.id, None)

    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify(success=False, error='No replacement file selected'), 400
    f = request.files['file']
    if not allowed_file(f.filename):
        return jsonify(success=False, error='File type not allowed'), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    raw_data = f.read()
    with open(filepath, 'wb') as fh:
        fh.write(raw_data)
    file_rec.size = len(raw_data)

    try:
        result = _fim_check_file(file_rec,
            triggered_by='manual',
            triggered_by_user_id=current_user.id,
        )
        if result['status'] not in ('ok', 'skip'):
            _fim_raise_alert(file_rec, result)
        log_activity('tamper_simulation',
                     f'Replaced file content: "{file_rec.original_name}" — {result["status"]}')
        db.session.commit()
        _notify(
            f'File Replaced — {file_rec.original_name}',
            f'File:         {file_rec.original_name}\n'
            f'Replaced by:  {current_user.full_name} ({current_user.email})\n'
            f'Result:       {result["status"].upper()}\n'
            f'IP:           {_get_real_ip()}\n\n'
            f'An integrity alert has been raised on the dashboard. '
            f'Please acknowledge, resolve, or reset the baseline.',
        )
    except Exception as exc:
        db.session.rollback()
        app.logger.error('fim_replace_file check error: %s', exc)
        # File was already replaced on disk — report that at least
        return jsonify(
            success = True,
            status  = 'replaced',
            message = f'File replaced on disk. Integrity check failed: {exc}. '
                      f'Use Capture Baseline to initialise monitoring then Check Now.',
        )

    return jsonify(
        success  = True,
        status   = result['status'],
        message  = {
            'tampered': '⚠ Hash mismatch detected — Critical alert raised.',
            'ok':       'Content replaced — hash still matches baseline (same content).',
            'missing':  '⚠ File error after replace.',
            'skip':     'File replaced on disk. No baseline exists yet — click Capture Baseline first.',
        }.get(result['status'], f'File replaced. Status: {result["status"]}'),
    )


# ---------------------------------------------------------------------------
# Inline file editor (text files only)
# ---------------------------------------------------------------------------
@app.route('/file/<file_uuid>/edit', methods=['GET'])
@login_required
def edit_file_page(file_uuid):
    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if not current_user.is_admin:
        token = request.args.get('token', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=file_rec.id,
            requested_by_id=current_user.id, action_type='edit', status='approved',
        ).first()
        if not ar or ar.is_expired:
            flash('You need an approved edit request to access this page.', 'warning')
            return redirect(url_for('fim_monitoring'))

    ext = file_rec.original_name.rsplit('.', 1)[-1].lower() if '.' in file_rec.original_name else ''
    if ext not in EDITABLE_EXTENSIONS:
        flash('This file type cannot be edited in the browser.', 'warning')
        return redirect(url_for('fim_monitoring'))

    if file_rec.size > EDITOR_SIZE_LIMIT:
        flash('File is too large to edit in the browser (limit: 512 KB).', 'warning')
        return redirect(url_for('fim_file_status', file_id=file_rec.id))

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    if not os.path.exists(filepath):
        flash('File not found on disk.', 'danger')
        return redirect(url_for('fim_file_status', file_id=file_rec.id))

    try:
        with open(filepath, 'rb') as fh:
            raw = fh.read()
        if file_rec.is_encrypted and _enc_key_raw:
            raw = _file_fernet(file_rec.stored_name).decrypt(raw)
        content = raw.decode('utf-8', errors='replace')
    except Exception as exc:
        flash(f'Could not read file: {exc}', 'danger')
        return redirect(url_for('fim_file_status', file_id=file_rec.id))

    cm_mode = {
        'json': 'application/json',
        'xml':  'application/xml',
        'html': 'text/html', 'htm': 'text/html',
        'css':  'text/css',
        'js':   'text/javascript', 'jsx': 'text/javascript',
        'ts':   'text/typescript', 'tsx': 'text/typescript',
        'py':   'text/x-python',
        'sh':   'text/x-sh', 'bash': 'text/x-sh',
        'sql':  'text/x-sql',
        'php':  'text/x-php',
        'rb':   'text/x-ruby',
        'java': 'text/x-java',
        'c':    'text/x-csrc', 'cpp': 'text/x-c++src', 'h': 'text/x-csrc',
        'rs':   'text/x-rustsrc',
        'go':   'text/x-go',
        'md':   'text/x-markdown',
        'yaml': 'text/x-yaml', 'yml': 'text/x-yaml',
    }.get(ext, 'text/plain')
    edit_token = request.args.get('token', '')
    return render_template('fim/edit_file.html',
        file=file_rec, content=content, cm_mode=cm_mode, ext=ext, edit_token=edit_token)


@app.route('/file/<file_uuid>/edit', methods=['POST'])
@login_required
def edit_file_save(file_uuid):
    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()

    locked, lock_msg = _check_pw_locked(current_user.id)
    if locked:
        return jsonify(success=False, error=lock_msg), 429

    ar = None
    if not current_user.is_admin:
        token = request.form.get('edit_token', '') or request.args.get('token', '')
        ar = ActionRequest.query.filter_by(
            exec_token=token, file_id=file_rec.id,
            requested_by_id=current_user.id, action_type='edit', status='approved',
        ).first()
        if not ar or ar.is_expired:
            return jsonify(success=False, error='No approved edit request found or token expired.'), 403

    # Password confirmation required from everyone — check BEFORE consuming the token
    password = request.form.get('password', '')
    if not current_user.check_password(password):
        newly_locked = _record_pw_fail(current_user.id, current_user.full_name, current_user.email, 'edit file save')
        msg = 'Incorrect password. Please confirm your FileVault password to save.'
        if newly_locked:
            msg = f'Too many failed attempts. Account locked for {_PW_LOCK_MINUTES} minutes.'
        return jsonify(success=False, error=msg), 401
    _pw_attempts[current_user.id]['count'] = 0

    if ar:
        ar.status      = 'executed'
        ar.executed_at = datetime.now(timezone.utc)

    ext = file_rec.original_name.rsplit('.', 1)[-1].lower() if '.' in file_rec.original_name else ''
    if ext not in EDITABLE_EXTENSIONS:
        return jsonify(success=False, error='File type not editable in browser'), 400

    content  = request.form.get('content', '')
    raw_data = content.encode('utf-8')
    if len(raw_data) > EDITOR_SIZE_LIMIT:
        return jsonify(success=False, error='Content too large (max 512 KB)'), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_rec.stored_name)
    # re-encrypt if file was stored encrypted
    _ff = _file_fernet(file_rec.stored_name)
    disk_data = _ff.encrypt(raw_data) if (_ff and file_rec.is_encrypted) else raw_data
    try:
        with open(filepath, 'wb') as fh:
            fh.write(disk_data)
        file_rec.size = len(raw_data)  # keep plaintext size
    except Exception as exc:
        return jsonify(success=False, error=f'Could not write file: {exc}'), 500

    check_status  = 'ok'
    check_message = 'File saved successfully.'
    try:
        # 1. Run integrity check BEFORE updating baseline — this detects the change
        #    and raises a "File modified" alert that admin must acknowledge.
        fim_result = _fim_check_file(file_rec,
            triggered_by='user_edit',
            triggered_by_user_id=current_user.id,
        )
        if fim_result['status'] not in ('ok', 'skip'):
            _fim_raise_alert(file_rec, fim_result)
            # Relabel the alert so admin knows it was an authorised edit, not a real tamper
            open_alert = IntegrityAlert.query.filter_by(
                file_id=file_rec.id, status='open'
            ).order_by(IntegrityAlert.raised_at.desc()).first()
            if open_alert:
                open_alert.title       = f'File edited by {current_user.full_name}: {file_rec.original_name}'
                open_alert.description = (
                    f'Authorised browser edit via ActionRequest workflow.\n'
                    f'Edited by: {current_user.full_name} ({current_user.email})\n'
                    f'New size: {format_bytes(len(raw_data))}\n'
                    f'Admin: please acknowledge this alert once reviewed.'
                )

        # 2. Now update the baseline so future auto-checks don't re-flag this edit
        _fim_capture_baseline(file_rec, current_user, reason='edit')
        log_activity('edit', f'Edited "{file_rec.original_name}" in browser ({format_bytes(len(raw_data))})')
        _log_file_access('edit', file_rec, 'success',
                         f'Inline edit saved ({format_bytes(len(raw_data))})')
        db.session.commit()
        check_message = 'File saved. Admin has been notified and must acknowledge the change.'
        _notify(
            f'File Modified — {file_rec.original_name}',
            f'File:        {file_rec.original_name}\n'
            f'New size:    {format_bytes(len(raw_data))}\n'
            f'Edited by:   {current_user.full_name} ({current_user.email})\n'
            f'IP:          {_get_real_ip()}\n\n'
            f'An alert has been raised on the dashboard. '
            f'Please acknowledge it to confirm you have reviewed this change.',
        )
    except Exception as exc:
        db.session.rollback()
        app.logger.error('edit_file_save post-write error: %s', exc)
        try:
            log_activity('edit', f'Edited "{file_rec.original_name}" in browser')
            db.session.commit()
        except Exception:
            db.session.rollback()
        check_message = 'File saved on disk. Baseline update failed — run an integrity check to resync.'

    return jsonify(success=True, status=check_status, message=check_message)


# ---------------------------------------------------------------------------
# FIM — PDF report export
# ---------------------------------------------------------------------------
@app.route('/fim/reports/export-pdf')
@login_required
def fim_export_pdf():
    from fpdf import FPDF

    if current_user.is_admin:
        files_q  = File.query
        alert_q  = IntegrityAlert.query
        log_q    = ActivityLog.query
    else:
        files_q = File.query.filter_by(user_id=current_user.id)
        uid_sub = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
        alert_q = IntegrityAlert.query.filter(IntegrityAlert.file_id.in_(uid_sub))
        log_q   = ActivityLog.query.filter_by(user_id=current_user.id)

    all_files   = files_q.all()
    monitored   = [f for f in all_files if f.monitoring_enabled]
    all_alerts  = alert_q.order_by(IntegrityAlert.raised_at.desc()).all()
    open_alerts = [a for a in all_alerts if a.status == 'open']
    sev_counts  = {s: sum(1 for a in open_alerts if a.severity == s)
                   for s in ('critical', 'high', 'medium', 'low', 'info')}
    recent_logs = log_q.order_by(ActivityLog.created_at.desc()).limit(30).all()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # ── Header ──
    pdf.set_font('Helvetica', 'B', 18)
    pdf.cell(0, 12, 'FileVault — Integrity Monitoring Report', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, f'Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
             new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 5, f'Prepared for: {current_user.full_name} ({current_user.role_label})',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # ── Summary stats ──
    pdf.set_font('Helvetica', 'B', 13)
    pdf.cell(0, 9, 'Executive Summary', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 10)

    stat_rows = [
        ('Total Files',              len(all_files)),
        ('Monitored Files',          len(monitored)),
        ('Healthy (OK)',             sum(1 for f in monitored if f.current_status == 'ok')),
        ('Tampered',                 sum(1 for f in monitored if f.current_status == 'tampered')),
        ('Missing from Disk',        sum(1 for f in monitored if f.current_status == 'missing')),
        ('Open Alerts',              len(open_alerts)),
        ('  Critical',               sev_counts.get('critical', 0)),
        ('  High',                   sev_counts.get('high', 0)),
        ('  Medium',                 sev_counts.get('medium', 0)),
        ('  Low / Info',             sev_counts.get('low', 0) + sev_counts.get('info', 0)),
        ('Total Alerts (all time)',  len(all_alerts)),
    ]
    for label, val in stat_rows:
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(110, 7, f'  {label}', border=1, fill=True)
        pdf.cell(0,   7, str(val),     border=1, new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)

    # ── Open alerts table ──
    if open_alerts:
        pdf.set_font('Helvetica', 'B', 13)
        pdf.cell(0, 9, f'Open Alerts ({len(open_alerts)})', new_x='LMARGIN', new_y='NEXT')

        hdrs = ['ID', 'Severity', 'File', 'Owner', 'Type', 'Raised At']
        wids = [12,   22,          55,     38,       38,     25]
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_fill_color(40, 40, 40)
        pdf.set_text_color(255, 255, 255)
        for h, w in zip(hdrs, wids):
            pdf.cell(w, 7, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font('Helvetica', '', 8)
        for i, a in enumerate(open_alerts[:40]):
            pdf.set_fill_color(250, 250, 250) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(0, 0, 0)
            fname  = (a.file.original_name if a.file else 'N/A')[:30]
            fowner = (a.file.owner.full_name if a.file and a.file.owner else 'N/A')[:20]
            atype  = a.alert_type.replace('_', ' ').title()[:20]
            pdf.cell(12, 6, str(a.id), border=1)
            pdf.cell(22, 6, a.severity.upper(), border=1)
            pdf.cell(55, 6, fname,  border=1)
            pdf.cell(38, 6, fowner, border=1)
            pdf.cell(38, 6, atype,  border=1)
            pdf.cell(25, 6, a.raised_at.strftime('%m-%d %H:%M'), border=1,
                     new_x='LMARGIN', new_y='NEXT')
        pdf.ln(5)

    # ── Recent activity ──
    if recent_logs:
        if pdf.get_y() > 220:
            pdf.add_page()
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Helvetica', 'B', 13)
        pdf.cell(0, 9, 'Recent Activity (last 30 events)', new_x='LMARGIN', new_y='NEXT')

        hdrs2 = ['Date/Time', 'User', 'Action', 'Detail']
        wids2 = [38, 40, 32, 80]
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_fill_color(40, 40, 40)
        pdf.set_text_color(255, 255, 255)
        for h, w in zip(hdrs2, wids2):
            pdf.cell(w, 7, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(0, 0, 0)
        for i, lg in enumerate(recent_logs):
            pdf.set_fill_color(250, 250, 250) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            uname  = (lg.user.full_name if lg.user else 'System')[:22]
            detail = (lg.detail or '')[:45]
            pdf.cell(38, 6, lg.created_at.strftime('%Y-%m-%d %H:%M'), border=1)
            pdf.cell(40, 6, uname,  border=1)
            pdf.cell(32, 6, lg.action.replace('_', ' ')[:18], border=1)
            pdf.cell(80, 6, detail, border=1, new_x='LMARGIN', new_y='NEXT')

    # ── Footer ──
    pdf.set_y(-18)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 8, 'FileVault Integrity Monitoring System — Confidential', align='C')

    buf  = io.BytesIO(bytes(pdf.output()))
    fname = f'fim_report_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.pdf'
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=fname)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(410)
def gone(_e):
    return render_template('errors/410.html'), 410


@app.errorhandler(429)
def rate_limited(_e):
    return render_template('errors/429.html'), 429


@app.errorhandler(403)
def forbidden(_e):
    return render_template('errors/403.html'), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template('errors/500.html'), 500


# ---------------------------------------------------------------------------
# WebAuthn / Fingerprint routes
# ---------------------------------------------------------------------------
@app.route('/profile/webauthn-register/begin', methods=['POST'])
@login_required
def webauthn_register_begin():
    data    = request.get_json() or {}
    wa_type = data.get('type', 'fingerprint')
    if wa_type not in ('fingerprint', 'face_id'):
        wa_type = 'fingerprint'
    session['_wa_reg_type'] = wa_type
    opts = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=str(current_user.id).encode(),
        user_name=current_user.email,
        user_display_name=current_user.full_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    session['_wa_reg_challenge'] = base64.b64encode(opts.challenge).decode()
    return _json.dumps(_json.loads(options_to_json(opts))), 200, {'Content-Type': 'application/json'}


@app.route('/profile/webauthn-register/complete', methods=['POST'])
@login_required
def webauthn_register_complete():
    raw = session.pop('_wa_reg_challenge', None)
    if not raw:
        return jsonify(success=False, error='Session expired — please try again.'), 400
    challenge = base64.b64decode(raw)
    try:
        verification = verify_registration_response(
            credential=request.get_json(),
            expected_challenge=challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_RP_ORIGIN,
            require_user_verification=False,
        )
    except Exception as exc:
        app.logger.error('WebAuthn registration failed: %s', exc)
        return jsonify(success=False, error=f'Registration failed: {exc}'), 400

    current_user.webauthn_credential_id = verification.credential_id
    current_user.webauthn_public_key    = verification.credential_public_key
    current_user.webauthn_sign_count    = verification.sign_count
    current_user.webauthn_enabled       = True
    current_user.webauthn_type          = session.pop('_wa_reg_type', 'fingerprint')
    log_activity('profile', f'Registered WebAuthn biometric: {current_user.webauthn_type}')
    db.session.commit()
    return jsonify(success=True)


@app.route('/profile/webauthn-disable', methods=['POST'])
@login_required
def webauthn_disable():
    current_user.webauthn_credential_id = None
    current_user.webauthn_public_key    = None
    current_user.webauthn_sign_count    = 0
    current_user.webauthn_enabled       = False
    current_user.webauthn_type          = None
    log_activity('profile', 'Removed biometric credential')
    db.session.commit()
    flash('Fingerprint login removed.', 'info')
    return redirect(url_for('profile'))


@app.route('/auth/check-biometric', methods=['POST'])
@csrf.exempt
def check_biometric():
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        abort(403)
    email = (request.get_json() or {}).get('email', '').strip().lower()
    user  = User.query.filter_by(email=email).first()
    if user and user.webauthn_enabled:
        return jsonify(type=user.webauthn_type or 'fingerprint')
    return jsonify(type=None)


@app.route('/auth/webauthn-login/begin', methods=['POST'])
@csrf.exempt
def webauthn_login_begin():
    """Begin WebAuthn authentication directly from the login page (no prior password step)."""
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        abort(403)
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify(error='Please enter your email address first.'), 400
    user = User.query.filter_by(email=email).first()
    if not user or not user.webauthn_enabled:
        return jsonify(error='No biometric login is registered for this account.'), 400
    opts = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(id=user.webauthn_credential_id)],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    session['_wa_login_user_id']   = user.id
    session['_wa_login_challenge'] = base64.b64encode(opts.challenge).decode()
    return _json.dumps(_json.loads(options_to_json(opts))), 200, {'Content-Type': 'application/json'}


@app.route('/auth/webauthn-login/complete', methods=['POST'])
@csrf.exempt
def webauthn_login_complete():
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        abort(403)
    user_id = session.pop('_wa_login_user_id', None)
    raw     = session.pop('_wa_login_challenge', None)
    if not user_id or not raw:
        return jsonify(success=False, error='Session expired — please try again.'), 400
    user      = db.session.get(User, user_id)
    challenge = base64.b64decode(raw)
    if not user or not user.webauthn_enabled:
        return jsonify(success=False, error='WebAuthn not enabled.'), 400
    try:
        verification = verify_authentication_response(
            credential=request.get_json(),
            expected_challenge=challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_RP_ORIGIN,
            credential_public_key=user.webauthn_public_key,
            credential_current_sign_count=user.webauthn_sign_count,
            require_user_verification=False,
        )
    except Exception as exc:
        app.logger.error('WebAuthn login failed: %s', exc)
        return jsonify(success=False, error=f'Authentication failed: {exc}'), 400
    user.webauthn_sign_count = verification.new_sign_count
    login_user(user, remember=False)
    session['_logged_in_this_session'] = True
    log_activity('login', f'Logged in with biometric from {request.remote_addr}')
    db.session.commit()
    flash(f'Welcome back, {user.full_name.split()[0]}!', 'success')
    return jsonify(success=True, redirect=url_for('dashboard'))


@app.route('/auth/webauthn/begin', methods=['POST'])
def webauthn_auth_begin():
    user_id = session.get('_mfa_user_id')
    if not user_id:
        return jsonify(success=False, error='No pending login session.'), 400
    user = db.session.get(User, user_id)
    if not user or not user.webauthn_enabled:
        return jsonify(success=False, error='WebAuthn not enabled.'), 400

    opts = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(id=user.webauthn_credential_id)],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    session['_wa_auth_challenge'] = base64.b64encode(opts.challenge).decode()
    return _json.dumps(_json.loads(options_to_json(opts))), 200, {'Content-Type': 'application/json'}


@app.route('/auth/webauthn/complete', methods=['POST'])
def webauthn_auth_complete():
    user_id = session.get('_mfa_user_id')
    raw     = session.pop('_wa_auth_challenge', None)
    if not user_id or not raw:
        return jsonify(success=False, error='Session expired — please log in again.'), 400

    user      = db.session.get(User, user_id)
    challenge = base64.b64decode(raw)
    if not user or not user.webauthn_enabled:
        return jsonify(success=False, error='WebAuthn not enabled.'), 400

    try:
        verification = verify_authentication_response(
            credential=request.get_json(),
            expected_challenge=challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_RP_ORIGIN,
            credential_public_key=user.webauthn_public_key,
            credential_current_sign_count=user.webauthn_sign_count,
            require_user_verification=False,
        )
    except Exception as exc:
        app.logger.error('WebAuthn authentication failed: %s', exc)
        return jsonify(success=False, error=f'Authentication failed: {exc}'), 400

    user.webauthn_sign_count = verification.new_sign_count
    remember = session.pop('_mfa_remember', False)
    session.pop('_mfa_user_id', None)
    nxt = session.pop('_mfa_next', None)
    login_user(user, remember=False)
    session['_logged_in_this_session'] = True
    log_activity('login', f'Logged in with fingerprint/WebAuthn from {request.remote_addr}')
    db.session.commit()
    flash(f'Welcome back, {user.full_name.split()[0]}!', 'success')
    return jsonify(success=True, redirect=nxt or url_for('dashboard'))


# ---------------------------------------------------------------------------
# SocketIO
# ---------------------------------------------------------------------------
@socketio.on('connect')
def on_connect():
    print(f'[WS] connected: {request.sid}')


@socketio.on('disconnect')
def on_disconnect():
    print(f'[WS] disconnected: {request.sid}')


# ---------------------------------------------------------------------------
# Bootstrap & run
# ---------------------------------------------------------------------------
# All DDL and data migrations are handled by prestart.py before gunicorn starts.
# Only grant ADMIN_EMAIL here (needs to re-run on every restart).
_admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
if _admin_email:
    try:
        with app.app_context():
            _admin_user = User.query.filter_by(email=_admin_email).first()
            if _admin_user and not _admin_user.is_admin:
                _admin_user.is_admin = True
                _admin_user.role = 'super_admin'
                db.session.commit()
    except Exception:
        pass

# Start FIM scheduler on the first real HTTP request, not at import time.
# Using spawn_after at module level caused the eventlet hub to be registered
# in the gunicorn master process before fork; the copied hub state in the
# worker then deadlocked when the timer fired.
_fim_scheduler_started = False

@app.before_request
def _ensure_fim_started():
    global _fim_scheduler_started
    if _fim_scheduler_started:
        return
    _fim_scheduler_started = True
    print("=== FIM: starting scheduler on first request ===", flush=True)
    try:
        from integrity_scheduler import start_scheduler as _fim_start_sched
        _fim_start_sched(app)
        print("=== FIM: scheduler started ===", flush=True)
    except Exception as _fim_exc:
        print(f"=== FIM: scheduler error: {_fim_exc} ===", flush=True)
        app.logger.warning('FIM scheduler error (non-fatal): %s', _fim_exc)

print("=== app.py: module load complete ===", flush=True)

if __name__ == '__main__':
    debug = os.environ.get('FLASK_ENV', 'production') == 'development'
    port = int(os.environ.get('PORT', 5000))
    print(f"=== starting socketio.run on port {port} ===", flush=True)
    socketio.run(app, debug=debug, host='0.0.0.0', port=port,
                 use_reloader=False, allow_unsafe_werkzeug=True)
