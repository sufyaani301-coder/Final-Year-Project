# ruff: noqa
"""
models.py — All SQLAlchemy models for FileVault.

Extracted from app.py so that routes, helpers, and models live in
separate modules. app.py imports db and all model classes from here.
"""
import uuid
import secrets
import json as _json
from datetime import datetime, timezone, timedelta

from flask import url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ---------------------------------------------------------------------------
# Monitoring policy
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
    excluded_extensions  = db.Column(db.Text, nullable=False, default='')
    retention_days       = db.Column(db.Integer, nullable=False, default=365)
    is_default           = db.Column(db.Boolean, nullable=False, default=False)
    is_active            = db.Column(db.Boolean, nullable=False, default=True)
    created_by_id        = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    updated_at           = db.Column(db.DateTime, nullable=True)

    files        = db.relationship('File', back_populates='policy', lazy='dynamic',
                                   foreign_keys='File.policy_id')
    created_by   = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def excluded_list(self):
        return [e.strip() for e in self.excluded_extensions.split(',') if e.strip()]


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

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
    default_policy_id      = db.Column(db.Integer,
                                       db.ForeignKey('monitoring_policies.id', ondelete='SET NULL'),
                                       nullable=True)
    email_alerts_enabled   = db.Column(db.Boolean, nullable=False, default=True)
    alert_email            = db.Column(db.String(120), nullable=True)
    # Clearance level: 1=TOP SECRET (access all), 5=UNCLASSIFIED (access level-5 only)
    clearance_level        = db.Column(db.Integer, nullable=False, default=5)

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
    def role_label(self):
        return {'super_admin': 'Super Admin', 'user': 'User'}.get(self.role, 'User')

    @property
    def clearance_label(self):
        return {1: 'TOP SECRET', 2: 'SECRET', 3: 'CONFIDENTIAL',
                4: 'RESTRICTED', 5: 'UNCLASSIFIED'}.get(self.clearance_level, 'UNCLASSIFIED')

    def can_view_file(self, file):
        """True if this user's clearance level permits viewing the file."""
        if self.is_admin:
            return True
        return (self.clearance_level or 5) <= (file.classification or 5)

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p]
        if not parts:
            return '?'
        return (parts[0][0] + parts[-1][0]).upper() if len(parts) > 1 else parts[0][:2].upper()


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------

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
    monitoring_enabled = db.Column(db.Boolean, nullable=False, default=True)
    policy_id          = db.Column(db.Integer,
                                   db.ForeignKey('monitoring_policies.id', ondelete='SET NULL'),
                                   nullable=True)
    current_status     = db.Column(db.String(20), nullable=False, default='pending')
    last_checked_at    = db.Column(db.DateTime, nullable=True)
    next_check_at      = db.Column(db.DateTime, nullable=True)
    check_count        = db.Column(db.Integer, nullable=False, default=0)
    alert_count        = db.Column(db.Integer, nullable=False, default=0)
    # Classification: 1=TOP SECRET, 2=SECRET, 3=CONFIDENTIAL, 4=RESTRICTED, 5=UNCLASSIFIED
    classification     = db.Column(db.Integer, nullable=False, default=5)

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

    @property
    def classification_label(self):
        return {1: 'TOP SECRET', 2: 'SECRET', 3: 'CONFIDENTIAL',
                4: 'RESTRICTED', 5: 'UNCLASSIFIED'}.get(self.classification, 'UNCLASSIFIED')

    @property
    def classification_css(self):
        return {1: 'class-ts', 2: 'class-secret', 3: 'class-conf',
                4: 'class-restricted', 5: 'class-unclass'}.get(self.classification, 'class-unclass')

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


# ---------------------------------------------------------------------------
# FileShare / ShareToken
# ---------------------------------------------------------------------------

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
    expires_at     = db.Column(db.DateTime, nullable=True)
    download_count = db.Column(db.Integer, default=0)

    file       = db.relationship('File', backref=db.backref('share_tokens', cascade='all, delete-orphan'))
    created_by = db.relationship('User')

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

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
# FIM models
# ---------------------------------------------------------------------------

class IntegrityBaseline(db.Model):
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
    __tablename__ = 'integrity_checks'
    id                   = db.Column(db.Integer, primary_key=True)
    file_id              = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='CASCADE'), nullable=False)
    baseline_id          = db.Column(db.Integer, db.ForeignKey('integrity_baselines.id', ondelete='SET NULL'), nullable=True)
    checked_at           = db.Column(db.DateTime, nullable=False,
                                     default=lambda: datetime.now(timezone.utc))
    computed_sha256      = db.Column(db.String(64), nullable=True)
    file_size_at_check   = db.Column(db.BigInteger, nullable=True)
    status               = db.Column(db.String(20), nullable=False)
    triggered_by         = db.Column(db.String(20), nullable=False, default='scheduler')
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
    expected_hash       = db.Column(db.String(64), nullable=False, default='')
    found_hash          = db.Column(db.String(64), nullable=True)
    expected_size       = db.Column(db.BigInteger, nullable=True)
    found_size          = db.Column(db.BigInteger, nullable=True)
    status              = db.Column(db.String(20), nullable=False, default='open')
    assigned_to_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_at         = db.Column(db.DateTime, nullable=True)
    assigned_by_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    acknowledged_at     = db.Column(db.DateTime, nullable=True)
    acknowledged_by_id  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    resolved_at         = db.Column(db.DateTime, nullable=True)
    resolved_by_id      = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    resolution_type     = db.Column(db.String(30), nullable=True)
    resolution_note     = db.Column(db.String(1000), nullable=True)
    escalated_to_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    escalated_at        = db.Column(db.DateTime, nullable=True)
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


class ChangeRequest(db.Model):
    __tablename__ = 'change_requests'
    id              = db.Column(db.Integer, primary_key=True)
    file_id         = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='CASCADE'), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    action_type     = db.Column(db.String(30), nullable=False)
    action_data     = db.Column(db.Text,    nullable=True)
    justification   = db.Column(db.String(500), nullable=True)
    status          = db.Column(db.String(20),  nullable=False, default='pending')
    requested_at    = db.Column(db.DateTime, nullable=False,
                                default=lambda: datetime.now(timezone.utc))
    reviewed_by_id  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reviewed_at     = db.Column(db.DateTime, nullable=True)
    review_note     = db.Column(db.String(500), nullable=True)
    pending_file    = db.Column(db.String(260), nullable=True)
    executed_at     = db.Column(db.DateTime, nullable=True)

    file         = db.relationship('File', foreign_keys=[file_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by  = db.relationship('User', foreign_keys=[reviewed_by_id])

    @property
    def action_label(self):
        return {'replace': 'Replace file content',
                'delete':  'Delete file',
                'rename':  'Rename file'}.get(self.action_type, self.action_type.title())

    @property
    def data(self):
        try:
            return _json.loads(self.action_data) if self.action_data else {}
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# File Access Log — every interaction with a file
# ---------------------------------------------------------------------------

class FileAccessLog(db.Model):
    """Immutable audit record for every file event: view, upload, download,
    edit, rename, delete, share, copy. Feeds the real-time event monitor."""
    __tablename__ = 'file_access_logs'
    id          = db.Column(db.Integer, primary_key=True)
    file_id     = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='SET NULL'), nullable=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action      = db.Column(db.String(30),  nullable=False)   # upload/view/download/edit/rename/delete/share/copy
    outcome     = db.Column(db.String(20),  nullable=False, default='success')  # success/denied/requested/approved/rejected/executed
    ip_address  = db.Column(db.String(45),  nullable=True)
    file_name   = db.Column(db.String(260), nullable=True)    # snapshot — file may be deleted later
    user_name   = db.Column(db.String(120), nullable=True)    # snapshot
    details     = db.Column(db.Text, nullable=True)
    timestamp   = db.Column(db.DateTime, nullable=False,
                            default=lambda: datetime.now(timezone.utc))

    file = db.relationship('File', foreign_keys=[file_id])
    user = db.relationship('User', foreign_keys=[user_id])

    @property
    def action_icon(self):
        return {
            'upload':   'bi-cloud-upload text-success',
            'view':     'bi-eye text-info',
            'download': 'bi-download text-primary',
            'edit':     'bi-pencil text-warning',
            'rename':   'bi-cursor-text text-warning',
            'delete':   'bi-trash text-danger',
            'share':    'bi-share text-success',
            'copy':     'bi-files text-secondary',
            'access_denied': 'bi-shield-x text-danger',
        }.get(self.action, 'bi-activity text-muted')

    @property
    def outcome_badge(self):
        return {
            'success':  '<span class="badge bg-success">SUCCESS</span>',
            'denied':   '<span class="badge bg-danger">DENIED</span>',
            'requested':'<span class="badge bg-warning text-dark">REQUESTED</span>',
            'approved': '<span class="badge bg-primary">APPROVED</span>',
            'rejected': '<span class="badge bg-danger">REJECTED</span>',
            'executed': '<span class="badge bg-success">EXECUTED</span>',
        }.get(self.outcome, '<span class="badge bg-secondary">UNKNOWN</span>')


# ---------------------------------------------------------------------------
# Action Request — user requests download/edit/rename/delete; admin approves
# ---------------------------------------------------------------------------

class ActionRequest(db.Model):
    """FBI-style authorisation: user submits request → admin approves/rejects
    with reason → user confirms with account password → action executes."""
    __tablename__ = 'action_requests'
    id              = db.Column(db.Integer, primary_key=True)
    file_id         = db.Column(db.Integer, db.ForeignKey('files.id', ondelete='CASCADE'), nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reviewed_by_id  = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action_type     = db.Column(db.String(20), nullable=False)   # download / edit / rename / delete
    justification   = db.Column(db.Text, nullable=True)
    status          = db.Column(db.String(20), nullable=False, default='pending')
    # pending → approved/rejected; approved → executed/expired
    admin_reason    = db.Column(db.Text, nullable=True)          # admin's approval/rejection note
    exec_token      = db.Column(db.String(64), nullable=True, unique=True)  # one-time token for execution
    requested_at    = db.Column(db.DateTime, nullable=False,
                                default=lambda: datetime.now(timezone.utc))
    reviewed_at     = db.Column(db.DateTime, nullable=True)
    expires_at      = db.Column(db.DateTime, nullable=True)      # 30 min after approval
    executed_at     = db.Column(db.DateTime, nullable=True)

    file         = db.relationship('File', foreign_keys=[file_id])
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by  = db.relationship('User', foreign_keys=[reviewed_by_id])

    @property
    def is_expired(self):
        if self.status != 'approved':
            return False
        if not self.expires_at:
            return False
        # expires_at is stored as naive UTC; compare with naive utcnow()
        exp = self.expires_at.replace(tzinfo=None)
        return datetime.utcnow() > exp

    @property
    def action_label(self):
        return {'download': 'Download', 'edit': 'Edit',
                'rename': 'Rename', 'delete': 'Delete',
                'replace': 'Replace'}.get(self.action_type, self.action_type.title())

    @property
    def status_badge(self):
        return {
            'pending':  '<span class="badge bg-warning text-dark">PENDING</span>',
            'approved': '<span class="badge bg-success">APPROVED</span>',
            'rejected': '<span class="badge bg-danger">REJECTED</span>',
            'executed': '<span class="badge bg-primary">EXECUTED</span>',
            'expired':  '<span class="badge bg-secondary">EXPIRED</span>',
        }.get(self.status, '<span class="badge bg-secondary">UNKNOWN</span>')
