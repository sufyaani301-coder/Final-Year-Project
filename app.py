# ruff: noqa
# flake8: noqa
# pylint: disable=all
# mypy: ignore-errors
# type: ignore
import eventlet
eventlet.monkey_patch()
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
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
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
    'pool_size': 5,
    'max_overflow': 0,
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

# Mail (Gmail SMTP)
app.config['MAIL_SERVER']         = 'smtp.gmail.com'
app.config['MAIL_PORT']           = 587
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME', 'noreply@filevault.local')

# WebAuthn / FIDO2
WEBAUTHN_RP_ID     = os.environ.get('WEBAUTHN_RP_ID',     'localhost')
WEBAUTHN_RP_NAME   = 'FileVault'
WEBAUTHN_RP_ORIGIN = os.environ.get('WEBAUTHN_RP_ORIGIN', 'http://localhost:5000')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db       = SQLAlchemy(app)
migrate  = Migrate(app, db)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')
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
mail = Mail(app)

_enc_key = os.environ.get('ENCRYPTION_KEY', '')
fernet   = Fernet(_enc_key.encode()) if _enc_key else None

# Per-email failed login tracking
_login_attempts: dict = defaultdict(lambda: {'count': 0, 'locked_until': None})
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_MINUTES   = 15

ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'json', 'xml', 'zip', 'rar', 'mp4', 'mp3'
}

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

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class MonitoringPolicy(db.Model):
    __tablename__ = 'monitoring_policies'
    id                   = db.Column(db.Integer, primary_key=True)
    name                 = db.Column(db.String(100), unique=True, nullable=False)
    description          = db.Column(db.Text, nullable=True)
    check_interval_mins  = db.Column(db.Integer, nullable=False, default=60)
    alert_on_tamper      = db.Column(db.Boolean, nullable=False, default=True)
    alert_on_missing     = db.Column(db.Boolean, nullable=False, default=True)
    alert_on_size_change = db.Column(db.Boolean, nullable=False, default=False)
    email_alert          = db.Column(db.Boolean, nullable=False, default=True)
    socket_alert         = db.Column(db.Boolean, nullable=False, default=True)
    severity_default     = db.Column(db.String(10), nullable=False, default='high')
    max_file_size_mb     = db.Column(db.Integer, nullable=True)
    excluded_extensions  = db.Column(db.Text, nullable=False, default='')  # comma-separated
    retention_days       = db.Column(db.Integer, nullable=False, default=365)
    is_default           = db.Column(db.Boolean, nullable=False, default=False)
    is_active            = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id        = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at           = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                                     onupdate=lambda: datetime.now(timezone.utc))

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    files      = db.relationship('File', back_populates='policy', lazy='dynamic',
                                 foreign_keys='File.policy_id')

    @property
    def interval_label(self):
        m = self.check_interval_mins
        if m < 60:   return f'Every {m} min'
        if m == 60:  return 'Every hour'
        if m < 1440: return f'Every {m // 60}h'
        return 'Daily'

    @property
    def excluded_list(self):
        return [e.strip() for e in self.excluded_extensions.split(',') if e.strip()]


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id                  = db.Column(db.Integer, primary_key=True)
    full_name           = db.Column(db.String(120), nullable=False)
    email               = db.Column(db.String(120), unique=True, nullable=False)
    password_hash       = db.Column(db.String(256), nullable=False)
    is_admin            = db.Column(db.Boolean, default=False)
    role                = db.Column(db.String(20), default='user', nullable=False)
    created_at          = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    mfa_secret          = db.Column(db.String(32),  nullable=True)
    mfa_enabled         = db.Column(db.Boolean, default=False)
    email_verified      = db.Column(db.Boolean, default=False)
    verification_token  = db.Column(db.String(64), nullable=True)
    reset_token            = db.Column(db.String(64),  nullable=True)
    reset_token_expires    = db.Column(db.DateTime,    nullable=True)
    webauthn_credential_id = db.Column(db.LargeBinary, nullable=True)
    webauthn_public_key    = db.Column(db.LargeBinary, nullable=True)
    webauthn_sign_count    = db.Column(db.Integer,     default=0)
    webauthn_enabled       = db.Column(db.Boolean,     default=False)
    webauthn_type          = db.Column(db.String(20),  nullable=True)
    # FIM — default monitoring policy for files uploaded by this user
    default_policy_id      = db.Column(db.Integer,
                                       db.ForeignKey('monitoring_policies.id', ondelete='SET NULL'),
                                       nullable=True)

    files          = db.relationship('File', backref='owner', lazy=True,
                                     foreign_keys='File.user_id',
                                     cascade='all, delete-orphan')
    default_policy = db.relationship('MonitoringPolicy', foreign_keys=[default_policy_id])

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    @property
    def is_analyst(self):
        return self.role in ('super_admin', 'analyst')

    @property
    def is_auditor(self):
        return self.role in ('super_admin', 'analyst', 'auditor')

    @property
    def role_label(self):
        return {'super_admin': 'Super Admin', 'analyst': 'Analyst',
                'auditor': 'Auditor', 'user': 'User'}.get(self.role, 'User')

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p]
        if not parts:
            return '?'
        return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()


class File(db.Model):
    __tablename__ = 'files'
    id            = db.Column(db.Integer, primary_key=True)
    uuid          = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    original_name = db.Column(db.String(260), nullable=False)
    stored_name   = db.Column(db.String(260), nullable=False)
    size          = db.Column(db.Integer, default=0)
    mimetype      = db.Column(db.String(120), default='application/octet-stream')
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_encrypted  = db.Column(db.Boolean, default=False)
    file_hash     = db.Column(db.String(64), nullable=True)
    # FIM monitoring columns
    monitoring_enabled = db.Column(db.Boolean, nullable=False, default=True)
    policy_id          = db.Column(db.Integer,
                                   db.ForeignKey('monitoring_policies.id', ondelete='SET NULL'),
                                   nullable=True)
    current_status     = db.Column(db.String(20), nullable=False, default='pending')
    last_checked_at    = db.Column(db.DateTime, nullable=True)
    next_check_at      = db.Column(db.DateTime, nullable=True)
    check_count        = db.Column(db.Integer, nullable=False, default=0)
    alert_count        = db.Column(db.Integer, nullable=False, default=0)

    shares    = db.relationship('FileShare', backref='file', lazy=True,
                               foreign_keys='FileShare.file_id',
                               cascade='all, delete-orphan')
    policy    = db.relationship('MonitoringPolicy', foreign_keys=[policy_id],
                                back_populates='files')
    baselines = db.relationship('IntegrityBaseline', back_populates='file',
                                cascade='all, delete-orphan',
                                order_by='IntegrityBaseline.captured_at.desc()',
                                lazy='dynamic')
    checks    = db.relationship('IntegrityCheck', back_populates='file',
                                cascade='all, delete-orphan',
                                order_by='IntegrityCheck.checked_at.desc()',
                                lazy='dynamic')
    fim_alerts = db.relationship('IntegrityAlert', back_populates='file',
                                 cascade='all, delete-orphan',
                                 order_by='IntegrityAlert.raised_at.desc()',
                                 lazy='dynamic')

    @property
    def current_baseline(self):
        return self.baselines.filter_by(is_current=True).first()

    @property
    def open_alert_count(self):
        return self.fim_alerts.filter_by(status='open').count()

    @property
    def status_badge(self):
        return {
            'ok':          ('<span class="badge badge-ok">OK</span>',          'bi-shield-check text-success'),
            'tampered':    ('<span class="badge badge-tampered">TAMPERED</span>', 'bi-shield-exclamation text-danger'),
            'missing':     ('<span class="badge badge-missing">MISSING</span>',   'bi-file-earmark-x text-warning'),
            'error':       ('<span class="badge badge-error">ERROR</span>',        'bi-exclamation-triangle text-warning'),
            'pending':     ('<span class="badge badge-pending">PENDING</span>',    'bi-hourglass-split text-muted'),
            'unmonitored': ('<span class="badge badge-secondary">UNMONITORED</span>', 'bi-shield-slash text-muted'),
        }.get(self.current_status, ('<span class="badge bg-secondary">UNKNOWN</span>', 'bi-question-circle'))

    @property
    def is_shared(self):
        return len(self.shares) > 0

    @property
    def size_human(self):
        size = float(self.size or 0)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'

    @property
    def icon(self):
        ext = self.original_name.rsplit('.', 1)[-1].lower() if '.' in self.original_name else ''
        return {
            'pdf':  'bi-file-earmark-pdf text-danger',
            'doc':  'bi-file-earmark-word text-primary',
            'docx': 'bi-file-earmark-word text-primary',
            'xls':  'bi-file-earmark-excel text-success',
            'xlsx': 'bi-file-earmark-excel text-success',
            'ppt':  'bi-file-earmark-ppt text-warning',
            'pptx': 'bi-file-earmark-ppt text-warning',
            'zip':  'bi-file-earmark-zip text-secondary',
            'rar':  'bi-file-earmark-zip text-secondary',
            'txt':  'bi-file-earmark-text text-muted',
            'csv':  'bi-file-earmark-spreadsheet text-success',
            'json': 'bi-file-earmark-code text-info',
            'xml':  'bi-file-earmark-code text-info',
            'mp4':  'bi-file-earmark-play text-danger',
            'mp3':  'bi-file-earmark-music text-warning',
            'png':  'bi-file-earmark-image text-info',
            'jpg':  'bi-file-earmark-image text-info',
            'jpeg': 'bi-file-earmark-image text-info',
            'gif':  'bi-file-earmark-image text-info',
        }.get(ext, 'bi-file-earmark text-secondary')

    @property
    def is_image(self):
        return self.mimetype.startswith('image/')

    def to_dict(self):
        return {
            'uuid':          self.uuid,
            'id':            self.id,
            'original_name': self.original_name,
            'size_human':    self.size_human,
            'is_image':      self.is_image,
            'icon':          self.icon,
            'stored_name':   self.stored_name,
            'uploaded_at':   self.uploaded_at.strftime('%b %d, %Y'),
            'user_id':       self.user_id,
            'is_shared':     self.is_shared,
            'download_url':  url_for('download_file', file_uuid=self.uuid),
            'delete_url':    url_for('delete_file',   file_uuid=self.uuid),
            'share_url':     url_for('share_file',    file_uuid=self.uuid),
            'rename_url':    url_for('rename_file',   file_uuid=self.uuid),
            'preview_url':   url_for('preview_file', file_uuid=self.uuid) if self.is_image else None,
        }


class FileShare(db.Model):
    __tablename__ = 'file_shares'
    id             = db.Column(db.Integer, primary_key=True)
    file_id        = db.Column(db.Integer, db.ForeignKey('files.id'),  nullable=False)
    shared_with_id = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    shared_by_id   = db.Column(db.Integer, db.ForeignKey('users.id'),  nullable=False)
    shared_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    shared_with = db.relationship('User', foreign_keys='FileShare.shared_with_id')
    shared_by   = db.relationship('User', foreign_keys='FileShare.shared_by_id')


class ShareToken(db.Model):
    """Public share link — no login required to download."""
    __tablename__ = 'share_tokens'
    id             = db.Column(db.Integer, primary_key=True)
    token          = db.Column(db.String(64), unique=True, nullable=False,
                               default=lambda: secrets.token_urlsafe(32))
    file_id        = db.Column(db.Integer, db.ForeignKey('files.id'), nullable=False)
    created_by_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    expires_at     = db.Column(db.DateTime, nullable=True)   # None = never expires
    download_count = db.Column(db.Integer, default=0)

    file       = db.relationship('File', backref=db.backref('share_tokens', cascade='all, delete-orphan'))
    created_by = db.relationship('User')

    @property
    def is_expired(self):
        return self.expires_at is not None and datetime.now(timezone.utc) > self.expires_at


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action     = db.Column(db.String(50),  nullable=False)
    detail     = db.Column(db.String(500), default='')
    ip_address = db.Column(db.String(45),  default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys='ActivityLog.user_id')


# ---------------------------------------------------------------------------
# FIM Models
# ---------------------------------------------------------------------------

class IntegrityBaseline(db.Model):
    """Immutable hash anchor. Written once at upload; superseded (not updated) on reset."""
    __tablename__ = 'integrity_baselines'
    id               = db.Column(db.Integer, primary_key=True)
    file_id          = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='CASCADE'), nullable=False)
    sha256_hash      = db.Column(db.String(64), nullable=False)
    file_size_bytes  = db.Column(db.BigInteger, nullable=False)
    is_current       = db.Column(db.Boolean, nullable=False, default=True)
    captured_at      = db.Column(db.DateTime, nullable=False,
                                 default=lambda: datetime.now(timezone.utc))
    captured_by_id   = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    capture_reason   = db.Column(db.String(20), nullable=False, default='upload')
    superseded_at    = db.Column(db.DateTime, nullable=True)
    superseded_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    supersede_note   = db.Column(db.String(500), nullable=True)

    file          = db.relationship('File', back_populates='baselines')
    captured_by   = db.relationship('User', foreign_keys=[captured_by_id])
    superseded_by = db.relationship('User', foreign_keys=[superseded_by_id])
    checks        = db.relationship('IntegrityCheck', back_populates='baseline', lazy='dynamic')

    @property
    def short_hash(self):
        return (self.sha256_hash[:16] + '...') if self.sha256_hash else '—'

    def supersede(self, by_user, note=''):
        self.is_current       = False
        self.superseded_at    = datetime.now(timezone.utc)
        self.superseded_by_id = by_user.id if by_user else None
        self.supersede_note   = note


class IntegrityCheck(db.Model):
    """One row per scheduler tick or manual check."""
    __tablename__ = 'integrity_checks'
    id                   = db.Column(db.Integer, primary_key=True)
    file_id              = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='CASCADE'), nullable=False)
    baseline_id          = db.Column(db.Integer, db.ForeignKey('integrity_baselines.id', ondelete='SET NULL'), nullable=True)
    checked_at           = db.Column(db.DateTime, nullable=False,
                                     default=lambda: datetime.now(timezone.utc))
    computed_sha256      = db.Column(db.String(64), nullable=True)
    file_size_at_check   = db.Column(db.BigInteger, nullable=True)
    status               = db.Column(db.String(20), nullable=False)  # ok|tampered|missing|error|permission_denied
    triggered_by         = db.Column(db.String(20), nullable=False, default='scheduler')  # scheduler|manual|upload|watchdog
    triggered_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    check_duration_ms    = db.Column(db.Integer, nullable=True)
    error_message        = db.Column(db.String(500), nullable=True)

    file              = db.relationship('File', back_populates='checks')
    baseline          = db.relationship('IntegrityBaseline', back_populates='checks')
    triggered_by_user = db.relationship('User', foreign_keys=[triggered_by_user_id])
    alert             = db.relationship('IntegrityAlert', back_populates='check', uselist=False)

    @property
    def passed(self):
        return self.status == 'ok'


class IntegrityAlert(db.Model):
    """Raised when an integrity check finds status != 'ok'."""
    __tablename__ = 'integrity_alerts'
    id                  = db.Column(db.Integer, primary_key=True)
    file_id             = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='CASCADE'), nullable=False)
    check_id            = db.Column(db.Integer, db.ForeignKey('integrity_checks.id', ondelete='CASCADE'), nullable=False)
    raised_at           = db.Column(db.DateTime, nullable=False,
                                    default=lambda: datetime.now(timezone.utc))
    severity            = db.Column(db.String(10), nullable=False, default='high')
    alert_type          = db.Column(db.String(30), nullable=False, default='hash_mismatch')
    title               = db.Column(db.String(200), nullable=False)
    description         = db.Column(db.Text, nullable=True)
    # Forensic evidence — copied at creation, never updated
    expected_hash       = db.Column(db.String(64), nullable=False, default='')
    found_hash          = db.Column(db.String(64), nullable=True)
    expected_size       = db.Column(db.BigInteger, nullable=True)
    found_size          = db.Column(db.BigInteger, nullable=True)
    # Lifecycle
    status              = db.Column(db.String(20), nullable=False, default='open')
    # Assignment
    assigned_to_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_at         = db.Column(db.DateTime, nullable=True)
    assigned_by_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    # Acknowledgement
    acknowledged_at     = db.Column(db.DateTime, nullable=True)
    acknowledged_by_id  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    # Resolution
    resolved_at         = db.Column(db.DateTime, nullable=True)
    resolved_by_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    resolution_type     = db.Column(db.String(30), nullable=True)
    resolution_note     = db.Column(db.String(1000), nullable=True)
    # Escalation
    escalated_to_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    escalated_at        = db.Column(db.DateTime, nullable=True)
    # Notification tracking
    email_sent          = db.Column(db.Boolean, nullable=False, default=False)
    socket_emitted      = db.Column(db.Boolean, nullable=False, default=False)

    file            = db.relationship('File', back_populates='fim_alerts')
    check           = db.relationship('IntegrityCheck', back_populates='alert')
    assigned_to     = db.relationship('User', foreign_keys=[assigned_to_id])
    assigned_by     = db.relationship('User', foreign_keys=[assigned_by_id])
    acknowledged_by = db.relationship('User', foreign_keys=[acknowledged_by_id])
    resolved_by     = db.relationship('User', foreign_keys=[resolved_by_id])
    escalated_to    = db.relationship('User', foreign_keys=[escalated_to_id])
    comments        = db.relationship('AlertComment', back_populates='alert',
                                      cascade='all, delete-orphan',
                                      order_by='AlertComment.created_at')

    @property
    def size_delta(self):
        if self.found_size is None or self.expected_size is None:
            return None
        return self.found_size - self.expected_size

    @property
    def is_open(self):
        return self.status == 'open'

    @property
    def severity_class(self):
        return {
            'info':     'badge-info',
            'low':      'badge-low',
            'medium':   'badge-medium',
            'high':     'badge-high',
            'critical': 'badge-critical',
        }.get(self.severity, 'bg-secondary')

    @property
    def severity_icon(self):
        return {
            'info':     'bi-info-circle text-secondary',
            'low':      'bi-exclamation-circle text-info',
            'medium':   'bi-exclamation-triangle text-warning',
            'high':     'bi-shield-exclamation',
            'critical': 'bi-shield-fill-exclamation text-danger',
        }.get(self.severity, 'bi-question-circle')

    def acknowledge(self, by_user):
        self.status              = 'acknowledged'
        self.acknowledged_at     = datetime.now(timezone.utc)
        self.acknowledged_by_id  = by_user.id

    def resolve(self, by_user, resolution_type, note=''):
        self.status          = 'resolved'
        self.resolved_at     = datetime.now(timezone.utc)
        self.resolved_by_id  = by_user.id
        self.resolution_type = resolution_type
        self.resolution_note = note

    def mark_false_positive(self, by_user, note=''):
        self.resolve(by_user, 'false_positive', note)
        self.status = 'false_positive'

    def escalate(self, to_user, by_user):
        self.status          = 'escalated'
        self.escalated_to_id = to_user.id
        self.escalated_at    = datetime.now(timezone.utc)
        if not self.acknowledged_at:
            self.acknowledge(by_user)

    def assign(self, to_user, by_user):
        self.assigned_to_id = to_user.id
        self.assigned_at    = datetime.now(timezone.utc)
        self.assigned_by_id = by_user.id


class AlertComment(db.Model):
    __tablename__ = 'alert_comments'
    id          = db.Column(db.Integer, primary_key=True)
    alert_id    = db.Column(db.Integer, db.ForeignKey('integrity_alerts.id', ondelete='CASCADE'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    comment     = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    created_at  = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc))
    is_deleted  = db.Column(db.Boolean, nullable=False, default=False)

    alert = db.relationship('IntegrityAlert', back_populates='comments')
    user  = db.relationship('User')


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


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
    link = url_for('verify_email', token=token, _external=True)
    msg = Message('Verify your FileVault email', recipients=[user.email])
    msg.body = (
        f'Hi {user.full_name},\n\n'
        f'Click here to verify your email address:\n{link}\n\n'
        f'If you did not register for FileVault, ignore this email.'
    )
    import threading
    def _send():
        with app.app_context():
            try:
                mail.send(msg)
            except Exception as exc:
                app.logger.error('Verification email failed for %s: %s', user.email, exc)
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
# Template context processors
# ---------------------------------------------------------------------------
@app.context_processor
def _fim_nav_context():
    """Inject FIM nav badge counts into every template."""
    if not current_user.is_authenticated:
        return {'fim_open_alerts': 0, 'nav_total_files': 0}
    try:
        if current_user.is_admin:
            open_count = IntegrityAlert.query.filter_by(status='open').count()
            file_count = File.query.count()
        else:
            uid_sub    = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
            open_count = IntegrityAlert.query.filter(
                IntegrityAlert.status == 'open',
                IntegrityAlert.file_id.in_(uid_sub),
            ).count()
            file_count = File.query.filter_by(user_id=current_user.id).count()
        return {'fim_open_alerts': open_count, 'nav_total_files': file_count}
    except Exception:
        return {'fim_open_alerts': 0, 'nav_total_files': 0}


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
            flash(f'Welcome back, {user.full_name.split()[0]}!', 'success')
            nxt = request.args.get('next', '')
            return redirect(nxt if nxt and _is_safe_redirect(nxt) else url_for('dashboard'))

        record['count'] += 1
        remaining = _LOCKOUT_THRESHOLD - record['count']
        if remaining <= 0:
            record['locked_until'] = datetime.now(timezone.utc) + timedelta(minutes=_LOCKOUT_MINUTES)
            flash(f'Too many failed attempts. Account locked for {_LOCKOUT_MINUTES} minutes.', 'danger')
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

        return redirect(url_for('profile'))

    my_files     = File.query.filter_by(user_id=current_user.id).all()
    total_size   = sum(f.size for f in my_files)
    quota        = app.config['STORAGE_QUOTA_BYTES']
    quota_pct    = min(100, round(total_size / quota * 100, 1))
    shared_count = sum(1 for f in my_files if f.is_shared)
    created = current_user.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    days_joined = (datetime.now(timezone.utc) - created).days

    return render_template('profile.html',
        total_files=len(my_files),
        total_size=format_bytes(total_size),
        quota_pct=quota_pct,
        quota_max=format_bytes(quota),
        shared_count=shared_count,
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
        file_q  = File.query.filter_by(user_id=current_user.id)
        uid_sub = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
        alert_q = IntegrityAlert.query.filter(IntegrityAlert.file_id.in_(uid_sub))

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

    if is_admin:
        chk_q = IntegrityCheck.query
    else:
        uid_sub2  = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
        chk_q     = IntegrityCheck.query.filter(IntegrityCheck.file_id.in_(uid_sub2))
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
def upload_file():
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
    with open(save_path, 'wb') as fh:
        fh.write(raw_data)
    size = len(raw_data)
    mime = mimetypes.guess_type(original_name)[0] or 'application/octet-stream'

    try:
        rec = File(original_name=original_name, stored_name=stored_name,
                   size=size, mimetype=mime, user_id=current_user.id,
                   is_encrypted=False, file_hash=sha256_hash)
        db.session.add(rec)
        log_activity('upload', f'Uploaded "{original_name}" ({format_bytes(size)})')
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.exists(save_path):
            os.remove(save_path)
        return err('Database error, upload cancelled.', 500)

    # Capture FIM baseline immediately after upload
    try:
        from integrity_engine import capture_baseline as _cap_baseline
        _cap_baseline(rec, current_user, reason='upload')
        db.session.commit()
    except Exception as _fim_exc:
        app.logger.warning('FIM baseline capture failed for "%s": %s', original_name, _fim_exc)

    broadcast_event('upload', f'{current_user.full_name} uploaded "{original_name}"',
                    original_name, current_user.full_name)

    if is_ajax:
        return jsonify(success=True, file=rec.to_dict())
    flash(f'"{original_name}" uploaded successfully.', 'success')
    return redirect(url_for('fim_monitoring'))


@app.route('/download/<file_uuid>')
@login_required
def download_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id and current_user.id not in [s.shared_with_id for s in rec.shares]:
        abort(403)
    log_activity('download', f'Downloaded "{rec.original_name}"')
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_FOLDER'], rec.stored_name,
                               as_attachment=True, download_name=rec.original_name)


@app.route('/decrypt/<file_uuid>', methods=['POST'])
@login_required
def decrypt_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id and current_user.id not in [s.shared_with_id for s in rec.shares]:
        abort(403)
    password = request.form.get('password', '')
    if not current_user.check_password(password):
        return jsonify(success=False, error='Incorrect password. Use your FileVault login password.'), 403
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], rec.stored_name)
    if not os.path.exists(file_path):
        return jsonify(success=False, error='File not found on server. Please re-upload the file.'), 404
    log_activity('download', f'Downloaded "{rec.original_name}"')
    db.session.commit()
    return send_from_directory(app.config['UPLOAD_FOLDER'], rec.stored_name,
                               as_attachment=True, download_name=rec.original_name)


@app.route('/preview-auth/<file_uuid>', methods=['POST'])
@login_required
def preview_auth(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    shared_ids = [s.shared_with_id for s in rec.shares]
    if rec.user_id != current_user.id and current_user.id not in shared_ids:
        return jsonify(success=False, error='Access denied.'), 403
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
    shared_ids = [s.shared_with_id for s in rec.shares]
    if rec.user_id != current_user.id and current_user.id not in shared_ids:
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], rec.stored_name,
                               mimetype=rec.mimetype or 'application/octet-stream')


@app.route('/delete/<file_uuid>', methods=['POST'])
@login_required
def delete_file(file_uuid):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id and not current_user.is_admin:
        return (jsonify(success=False, error='Forbidden'), 403) if is_ajax else abort(403)

    name, stored = rec.original_name, rec.stored_name
    log_activity('delete', f'Deleted "{name}"')
    db.session.delete(rec)
    db.session.commit()

    disk = os.path.join(app.config['UPLOAD_FOLDER'], stored)
    if os.path.exists(disk):
        os.remove(disk)

    broadcast_event('delete', f'{current_user.full_name} deleted "{name}"',
                    name, current_user.full_name)
    if is_ajax:
        return jsonify(success=True)
    flash(f'"{name}" deleted.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/rename/<file_uuid>', methods=['POST'])
@login_required
def rename_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id:
        return jsonify(success=False, error='Forbidden'), 403
    new_name = request.form.get('name', '').strip()
    if not new_name:
        return jsonify(success=False, error='Name cannot be empty'), 400
    ext = rec.original_name.rsplit('.', 1)[-1] if '.' in rec.original_name else ''
    if ext and not new_name.lower().endswith('.' + ext.lower()):
        new_name += '.' + ext
    old_name = rec.original_name
    rec.original_name = secure_filename(new_name)
    log_activity('rename', f'Renamed "{old_name}" → "{rec.original_name}"')
    db.session.commit()
    return jsonify(success=True, name=rec.original_name)


@app.route('/share/<file_uuid>', methods=['POST'])
@login_required
def share_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id:
        abort(403)
    target = db.session.get(User, request.form.get('share_with_user_id', type=int))
    if not target:
        flash('User not found.', 'danger')
        return redirect(url_for('dashboard'))
    if FileShare.query.filter_by(file_id=rec.id, shared_with_id=target.id).first():
        flash(f'Already shared with {target.full_name}.', 'info')
        return redirect(url_for('dashboard'))
    db.session.add(FileShare(file_id=rec.id, shared_with_id=target.id,
                             shared_by_id=current_user.id))
    log_activity('share', f'Shared "{rec.original_name}" with {target.full_name}')
    db.session.commit()
    broadcast_event('share',
                    f'{current_user.full_name} shared "{rec.original_name}" with {target.full_name}',
                    rec.original_name, current_user.full_name)
    flash(f'Shared with {target.full_name}.', 'success')
    return redirect(url_for('dashboard'))


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
    if not current_user.is_super_admin:
        abort(403)
    if user_id == current_user.id:
        flash("You can't change your own role.", 'warning')
        return redirect(url_for('admin_panel'))
    user = db.session.get(User, user_id) or abort(404)
    new_role = request.form.get('role', 'user')
    if new_role not in ('super_admin', 'analyst', 'auditor', 'user'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('admin_panel'))
    user.role = new_role
    user.is_admin = new_role == 'super_admin'
    db.session.commit()
    log_activity('profile', f'Changed role of {user.full_name} to {new_role}')
    db.session.commit()
    flash(f'Role of {user.full_name} changed to {new_role.replace("_", " ").title()}.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/verify/<file_uuid>')
@login_required
def verify_file(file_uuid):
    rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if rec.user_id != current_user.id and current_user.id not in [s.shared_with_id for s in rec.shares]:
        abort(403)
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

    q = File.query if current_user.is_admin else File.query.filter_by(user_id=current_user.id)
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

    all_users = User.query.filter(User.id != current_user.id).all()
    policies  = MonitoringPolicy.query.filter_by(is_active=True).all()

    return render_template('fim/monitoring.html',
        files=pagination.items,
        pagination=pagination,
        query=query,
        status_filter=status,
        sort=sort,
        order=order,
        all_users=all_users,
        policies=policies,
    )


# ---------------------------------------------------------------------------
# FIM — File detail / check history
# ---------------------------------------------------------------------------
@app.route('/fim/file/<int:file_id>')
@login_required
def fim_file_status(file_id):
    file_rec = File.query.get_or_404(file_id)
    if file_rec.user_id != current_user.id and not current_user.is_admin:
        abort(403)

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
def fim_manual_check(file_uuid):
    from integrity_engine import check_single_file, run_alert_pipeline

    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    if file_rec.user_id != current_user.id and not current_user.is_admin:
        return jsonify(success=False, error='Forbidden'), 403

    result = check_single_file(
        file_id=file_rec.id,
        triggered_by='manual',
        triggered_by_user_id=current_user.id,
    )
    if result['status'] not in ('ok', 'skip'):
        run_alert_pipeline(file_rec, result)
    db.session.commit()

    return jsonify(
        success=True,
        status=result['status'],
        check_id=result.get('check_id'),
        message={
            'ok':      'File integrity verified — no changes detected.',
            'tampered':'⚠ Hash mismatch detected! Alert raised.',
            'missing': '⚠ File is missing from disk! Alert raised.',
            'error':   'Check error — see alert details.',
            'skip':    'Skipped (no baseline).',
        }.get(result['status'], result['status']),
    )


# ---------------------------------------------------------------------------
# FIM — Reset / accept baseline
# ---------------------------------------------------------------------------
@app.route('/fim/baseline/<file_uuid>/reset', methods=['POST'])
@login_required
def fim_reset_baseline(file_uuid):
    from integrity_engine import accept_new_baseline

    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403

    file_rec = File.query.filter_by(uuid=file_uuid).first_or_404()
    note     = request.form.get('note', '').strip()

    ok = accept_new_baseline(file_rec, current_user, note=note or 'Baseline reset by admin')
    if not ok:
        return jsonify(success=False, error='Failed to capture new baseline — file may be missing'), 500

    db.session.commit()
    log_activity('baseline_reset', f'Reset baseline for "{file_rec.original_name}"')
    db.session.commit()
    return jsonify(success=True, message='Baseline updated and open alerts resolved.')


# ---------------------------------------------------------------------------
# FIM — Alerts centre
# ---------------------------------------------------------------------------
@app.route('/fim/alerts')
@login_required
def fim_alerts():
    sev    = request.args.get('severity', '')
    status = request.args.get('status', 'open')
    fid    = request.args.get('file_id', '', type=str)
    page   = request.args.get('page', 1, type=int)

    if current_user.is_admin:
        q = IntegrityAlert.query
    else:
        uid_sub = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
        q = IntegrityAlert.query.filter(IntegrityAlert.file_id.in_(uid_sub))

    if status:
        q = q.filter_by(status=status)
    if sev:
        q = q.filter_by(severity=sev)
    if fid:
        try:
            q = q.filter_by(file_id=int(fid))
        except ValueError:
            pass

    q = q.order_by(IntegrityAlert.raised_at.desc())
    pagination = q.paginate(page=page, per_page=25, error_out=False)

    analysts = User.query.filter(User.role.in_(['super_admin', 'analyst'])).all()

    return render_template('fim/alerts.html',
        alerts=pagination.items,
        pagination=pagination,
        sev_filter=sev,
        status_filter=status,
        file_id_filter=fid,
        analysts=analysts,
    )


# ---------------------------------------------------------------------------
# FIM — Alert actions (acknowledge / resolve / false-positive / escalate /
#        assign / comment)
# ---------------------------------------------------------------------------
def _get_alert_for_action(alert_id):
    alert = IntegrityAlert.query.get_or_404(alert_id)
    if not current_user.is_admin:
        file_owner = File.query.get(alert.file_id)
        if not file_owner or file_owner.user_id != current_user.id:
            abort(403)
    return alert


@app.route('/fim/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
def fim_alert_acknowledge(alert_id):
    alert = _get_alert_for_action(alert_id)
    if alert.status not in ('open', 'escalated'):
        return jsonify(success=False, error='Alert is already closed'), 400
    alert.acknowledge(current_user)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/resolve', methods=['POST'])
@login_required
def fim_alert_resolve(alert_id):
    alert       = _get_alert_for_action(alert_id)
    res_type    = request.form.get('resolution_type', 'investigated')
    note        = request.form.get('note', '').strip()
    alert.resolve(current_user, res_type, note)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/false-positive', methods=['POST'])
@login_required
def fim_alert_false_positive(alert_id):
    alert = _get_alert_for_action(alert_id)
    note  = request.form.get('note', '').strip()
    alert.mark_false_positive(current_user, note)
    db.session.commit()
    return jsonify(success=True, new_status=alert.status)


@app.route('/fim/alerts/<int:alert_id>/escalate', methods=['POST'])
@login_required
def fim_alert_escalate(alert_id):
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
        uid_sub = db.session.query(File.id).filter_by(user_id=current_user.id).subquery()
        alert_q = IntegrityAlert.query.filter(IntegrityAlert.file_id.in_(uid_sub))
        check_q = IntegrityCheck.query.filter(IntegrityCheck.file_id.in_(uid_sub))
        file_q  = File.query.filter_by(user_id=current_user.id)

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
# FIM — Policies
# ---------------------------------------------------------------------------
@app.route('/fim/policies')
@login_required
def fim_policies():
    if not current_user.is_admin:
        abort(403)
    policies = MonitoringPolicy.query.order_by(MonitoringPolicy.is_default.desc(),
                                               MonitoringPolicy.name).all()
    return render_template('fim/policies.html', policies=policies)


@app.route('/fim/policies/create', methods=['POST'])
@login_required
def fim_policy_create():
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403

    name = request.form.get('name', '').strip()
    if not name:
        return jsonify(success=False, error='Name is required'), 400
    if MonitoringPolicy.query.filter_by(name=name).first():
        return jsonify(success=False, error='A policy with that name already exists'), 400

    p = MonitoringPolicy(
        name                = name,
        description         = request.form.get('description', '').strip(),
        check_interval_mins = request.form.get('check_interval_mins', 60, type=int),
        alert_on_tamper     = request.form.get('alert_on_tamper',      '1') == '1',
        alert_on_missing    = request.form.get('alert_on_missing',     '1') == '1',
        alert_on_size_change= request.form.get('alert_on_size_change', '0') == '1',
        email_alert         = request.form.get('email_alert',          '1') == '1',
        socket_alert        = request.form.get('socket_alert',         '1') == '1',
        severity_default    = request.form.get('severity_default',     'high'),
        retention_days      = request.form.get('retention_days',       365, type=int),
        excluded_extensions = request.form.get('excluded_extensions',  '').strip(),
        is_default          = request.form.get('is_default',           '0') == '1',
        created_by_id       = current_user.id,
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(success=True, policy_id=p.id, name=p.name)


@app.route('/fim/policies/<int:policy_id>/update', methods=['POST'])
@login_required
def fim_policy_update(policy_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    p = MonitoringPolicy.query.get_or_404(policy_id)

    p.name                 = request.form.get('name', p.name).strip()
    p.description          = request.form.get('description', '').strip()
    p.check_interval_mins  = request.form.get('check_interval_mins', p.check_interval_mins, type=int)
    p.alert_on_tamper      = request.form.get('alert_on_tamper',      '1') == '1'
    p.alert_on_missing     = request.form.get('alert_on_missing',     '1') == '1'
    p.alert_on_size_change = request.form.get('alert_on_size_change', '0') == '1'
    p.email_alert          = request.form.get('email_alert',          '1') == '1'
    p.socket_alert         = request.form.get('socket_alert',         '1') == '1'
    p.severity_default     = request.form.get('severity_default',     p.severity_default)
    p.retention_days       = request.form.get('retention_days',       p.retention_days, type=int)
    p.excluded_extensions  = request.form.get('excluded_extensions',  '').strip()
    p.is_default           = request.form.get('is_default',           '0') == '1'
    p.updated_at           = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify(success=True)


@app.route('/fim/policies/<int:policy_id>/delete', methods=['POST'])
@login_required
def fim_policy_delete(policy_id):
    if not current_user.is_admin:
        return jsonify(success=False, error='Admin required'), 403
    p = MonitoringPolicy.query.get_or_404(policy_id)
    if p.is_default:
        return jsonify(success=False, error='Cannot delete the default policy'), 400
    File.query.filter_by(policy_id=p.id).update({'policy_id': None})
    db.session.delete(p)
    db.session.commit()
    return jsonify(success=True)


# ---------------------------------------------------------------------------
# FIM — Assign policy to file
# ---------------------------------------------------------------------------
@app.route('/fim/file/<int:file_id>/set-policy', methods=['POST'])
@login_required
def fim_set_file_policy(file_id):
    file_rec = File.query.get_or_404(file_id)
    if file_rec.user_id != current_user.id and not current_user.is_admin:
        return jsonify(success=False, error='Forbidden'), 403
    pid = request.form.get('policy_id', type=int)
    file_rec.policy_id = pid
    db.session.commit()
    return jsonify(success=True)


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
# Skip all DB DDL when imported by prestart.py (SKIP_DB_INIT=1).
# prestart.py handles migrations via Flask-Migrate Python API before gunicorn starts.
if not os.environ.get('SKIP_DB_INIT'):
    try:
        with app.app_context():
            try:
                db.create_all()
            except Exception:
                pass
            # Add columns that predate the current schema (safe to run repeatedly)
            for _stmt in [
                "ALTER TABLE users ADD COLUMN webauthn_type VARCHAR(20)",
                "ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'",
                "ALTER TABLE files ADD COLUMN file_hash VARCHAR(64)",
            ]:
                try:
                    db.session.execute(db.text(_stmt))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            # Migrate existing admins to super_admin role
            try:
                db.session.execute(db.text(
                    "UPDATE users SET role='super_admin' WHERE is_admin IS TRUE AND (role IS NULL OR role='user')"
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
            # Grant admin to ADMIN_EMAIL if set
            _admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
            if _admin_email:
                try:
                    _admin_user = User.query.filter_by(email=_admin_email).first()
                    if _admin_user and not _admin_user.is_admin:
                        _admin_user.is_admin = True
                        _admin_user.role = 'super_admin'
                        db.session.commit()
                except Exception:
                    db.session.rollback()
    except Exception:
        pass

# Defer FIM startup until after the eventlet hub is running (avoids blocking
# CLI commands like flask db upgrade that never start the event loop).
def _start_fim_deferred():
    with app.app_context():
        try:
            from integrity_scheduler import start_scheduler as _fim_start_sched
            from integrity_watchdog  import start_event_worker as _fim_start_watch
            _fim_start_sched(app)
            _fim_start_watch(app)
        except Exception as _fim_exc:
            app.logger.warning('FIM startup error (non-fatal): %s', _fim_exc)

eventlet.spawn_after(1, _start_fim_deferred)

if __name__ == '__main__':
    debug = os.environ.get('FLASK_ENV', 'production') == 'development'
    socketio.run(app, debug=debug, host='0.0.0.0', port=5000)
