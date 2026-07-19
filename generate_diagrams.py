"""
FileVault — All 6 Academic Diagrams
Generates PNG files in the diagrams/ folder
"""

import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe
import numpy as np

os.makedirs('diagrams', exist_ok=True)

# ─── Colour palette ──────────────────────────────────────────────────────────
C = {
    'navy':   '#1a2e4a',
    'blue':   '#2563eb',
    'lblue':  '#3b82f6',
    'sky':    '#bfdbfe',
    'teal':   '#0f766e',
    'lteal':  '#99f6e4',
    'green':  '#15803d',
    'lgreen': '#bbf7d0',
    'red':    '#dc2626',
    'lred':   '#fecaca',
    'orange': '#ea580c',
    'lorange':'#fed7aa',
    'purple': '#7c3aed',
    'lpurple':'#e9d5ff',
    'gray':   '#374151',
    'lgray':  '#f3f4f6',
    'white':  '#ffffff',
    'dark':   '#111827',
}

def box(ax, x, y, w, h, text, fc='#bfdbfe', ec='#2563eb', fs=9,
        bold=False, radius=0.3, wrap=False, tc='#111827'):
    rect = FancyBboxPatch((x, y), w, h,
                          boxstyle=f'round,pad=0.1,rounding_size={radius}',
                          facecolor=fc, edgecolor=ec, linewidth=1.5, zorder=3)
    ax.add_patch(rect)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w/2, y + h/2, text, ha='center', va='center',
            fontsize=fs, fontweight=weight, color=tc,
            wrap=wrap, zorder=4,
            multialignment='center')

def arrow(ax, x1, y1, x2, y2, color='#374151', lw=1.5, style='->', label=''):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color,
                                lw=lw, connectionstyle='arc3,rad=0'))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my+0.15, label, ha='center', va='bottom',
                fontsize=7, color=color, style='italic')

def title_banner(ax, text):
    ax.text(0.5, 0.98, text, transform=ax.transAxes,
            ha='center', va='top', fontsize=13, fontweight='bold',
            color=C['navy'],
            bbox=dict(boxstyle='round,pad=0.4', fc=C['sky'], ec=C['blue'], lw=1.5))


# ══════════════════════════════════════════════════════════════════════════════
# 1. BLOCK DIAGRAM
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(14, 10))
ax.set_xlim(0, 14); ax.set_ylim(0, 10)
ax.axis('off')
title_banner(ax, 'Figure 1 — FileVault Block Diagram')

# ── Users block (left) ──────────────────────────────────────────────────────
box(ax, 0.3, 7.5, 2.2, 1.2, 'ADMIN\nUser', fc='#fde68a', ec='#d97706', bold=True, fs=10)
box(ax, 0.3, 5.8, 2.2, 1.2, 'NON-ADMIN\nUser', fc='#bfdbfe', ec='#2563eb', bold=True, fs=10)

# ── Core system (centre) ─────────────────────────────────────────────────────
# Outer system boundary
rect_sys = FancyBboxPatch((3.0, 1.0), 8.0, 8.2,
    boxstyle='round,pad=0.1,rounding_size=0.4',
    facecolor='#f8fafc', edgecolor='#1a2e4a', linewidth=2.5, zorder=1)
ax.add_patch(rect_sys)
ax.text(7.0, 9.35, 'FileVault System', ha='center', va='center',
        fontsize=12, fontweight='bold', color=C['navy'], zorder=5)

# Auth module
box(ax, 3.3, 7.4, 2.4, 1.4, 'Authentication\nModule\n(Login · MFA · WebAuthn)',
    fc='#fef3c7', ec='#d97706', fs=8)
# MAC module
box(ax, 6.1, 7.4, 2.4, 1.4, 'MAC Access\nControl\n(Clearance Levels 1–5)',
    fc='#ede9fe', ec='#7c3aed', fs=8)
# Encryption module
box(ax, 8.9, 7.4, 2.0, 1.4, 'Encryption\nModule\n(AES · HKDF)',
    fc='#fce7f3', ec='#db2777', fs=8)

# File Management
box(ax, 3.3, 5.2, 2.4, 1.6, 'File Management\nUpload · Download\nEdit · Delete · Replace',
    fc='#d1fae5', ec='#059669', fs=8)
# ActionRequest Workflow
box(ax, 6.1, 5.2, 2.4, 1.6, 'ActionRequest\nWorkflow\nRequest→Approve→Execute',
    fc='#fee2e2', ec='#dc2626', fs=8)
# FIM Engine
box(ax, 8.9, 5.2, 2.0, 1.6, 'FIM Engine\nSHA-256 Hash\nBaseline · Check',
    fc='#e0f2fe', ec='#0284c7', fs=8)

# Scheduler
box(ax, 3.3, 3.3, 2.4, 1.4, 'FIM Scheduler\n5 min scan\n15 min recovery · 1h escalate',
    fc='#f0fdf4', ec='#16a34a', fs=7.5)
# Notification
box(ax, 6.1, 3.3, 2.4, 1.4, 'Notification\nEngine\nWebSocket · Email',
    fc='#fdf4ff', ec='#a21caf', fs=8)
# Activity Log
box(ax, 8.9, 3.3, 2.0, 1.4, 'Activity &\nAccess Log\nAudit Trail',
    fc='#fff7ed', ec='#ea580c', fs=8)

# Database
box(ax, 4.5, 1.3, 5.0, 1.4, 'PostgreSQL Database\n(Users · Files · Baselines · Alerts · ActionRequests · Logs)',
    fc='#f1f5f9', ec='#475569', fs=8, bold=True)

# Internal arrows (top row → middle row)
for x in [4.5, 7.3]:
    ax.annotate('', xy=(x, 5.2+1.6), xytext=(x, 7.4),
                arrowprops=dict(arrowstyle='<->', color=C['gray'], lw=1.2))
ax.annotate('', xy=(9.9, 5.2+1.6), xytext=(9.9, 7.4),
            arrowprops=dict(arrowstyle='<->', color=C['gray'], lw=1.2))
# Middle row → bottom row
for x in [4.5, 7.3, 9.9]:
    ax.annotate('', xy=(x, 3.3+1.4), xytext=(x, 5.2),
                arrowprops=dict(arrowstyle='<->', color=C['gray'], lw=1.2))
# Bottom row → DB
for x in [4.5, 7.3, 9.9]:
    ax.annotate('', xy=(7.0, 1.3+1.4), xytext=(x, 3.3),
                arrowprops=dict(arrowstyle='->', color='#475569', lw=1.0))

# External arrows: users → system
arrow(ax, 2.5, 8.1, 3.3, 8.1, color='#d97706', lw=2)
arrow(ax, 2.5, 6.4, 3.3, 6.4, color='#2563eb', lw=2)
# Labels
ax.text(2.78, 8.2, 'Full\naccess', ha='center', va='bottom', fontsize=7, color='#d97706')
ax.text(2.78, 6.5, 'AR\nworkflow', ha='center', va='bottom', fontsize=7, color='#2563eb')

# External: notification → outside
box(ax, 11.2, 4.8, 2.5, 1.0, 'Email\n(Resend API)', fc='#fdf4ff', ec='#a21caf', fs=8)
box(ax, 11.2, 3.5, 2.5, 1.0, 'Browser\nWebSocket', fc='#fdf4ff', ec='#a21caf', fs=8)
arrow(ax, 11.0, 4.0, 11.2, 5.3, color='#a21caf', lw=1.5)
arrow(ax, 11.0, 4.0, 11.2, 4.0, color='#a21caf', lw=1.5)

plt.tight_layout()
plt.savefig('diagrams/1_block_diagram.png', dpi=180, bbox_inches='tight',
            facecolor='white')
plt.close()
print('✓ Block Diagram saved')


# ══════════════════════════════════════════════════════════════════════════════
# 2. USE CASE DIAGRAM
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(16, 11))
ax.set_xlim(0, 16); ax.set_ylim(0, 11)
ax.axis('off')
title_banner(ax, 'Figure 2 — FileVault Use Case Diagram')

def actor(ax, x, y, name, color='#1a2e4a'):
    # Head
    circle = plt.Circle((x, y+0.55), 0.28, color=color, zorder=4)
    ax.add_patch(circle)
    # Body
    ax.plot([x, x], [y+0.27, y-0.3], color=color, lw=2, zorder=4)
    # Arms
    ax.plot([x-0.35, x+0.35], [y+0.05, y+0.05], color=color, lw=2, zorder=4)
    # Legs
    ax.plot([x, x-0.3], [y-0.3, y-0.7], color=color, lw=2, zorder=4)
    ax.plot([x, x+0.3], [y-0.3, y-0.7], color=color, lw=2, zorder=4)
    ax.text(x, y-0.9, name, ha='center', va='top', fontsize=9,
            fontweight='bold', color=color)

def usecase(ax, x, y, w, h, text, fc='#bfdbfe', ec='#2563eb', fs=8):
    ell = mpatches.Ellipse((x, y), w, h, facecolor=fc, edgecolor=ec,
                           linewidth=1.5, zorder=3)
    ax.add_patch(ell)
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            color='#111827', multialignment='center', zorder=4)

# System boundary box
rect_b = FancyBboxPatch((3.2, 0.5), 9.5, 10.0,
    boxstyle='round,pad=0.1,rounding_size=0.3',
    facecolor='#f8fafc', edgecolor='#1a2e4a', linewidth=2, zorder=1)
ax.add_patch(rect_b)
ax.text(7.95, 10.6, 'FileVault System', ha='center', fontsize=11,
        fontweight='bold', color=C['navy'])

# Actors
actor(ax, 1.3, 7.5, 'Administrator', color='#d97706')
actor(ax, 1.3, 3.5, 'Non-Admin\nUser', color='#2563eb')
actor(ax, 14.7, 6.0, 'System\nScheduler', color='#059669')

# Admin use cases
admin_ucs = [
    (5.8, 9.5, 'Upload File\n& Classify', C['sky'], C['blue']),
    (8.5, 9.5, 'Manage Users\n& Clearance', C['sky'], C['blue']),
    (11.2, 9.5, 'View Activity\n& Access Logs', C['sky'], C['blue']),
    (5.8, 8.0, 'Approve / Reject\nAction Requests', '#fef3c7', '#d97706'),
    (8.5, 8.0, 'Acknowledge\nAlerts', '#fef3c7', '#d97706'),
    (11.2, 8.0, 'Reset / Capture\nBaseline', '#fef3c7', '#d97706'),
    (5.8, 6.5, 'Download /\nDecrypt File', '#d1fae5', '#059669'),
    (8.5, 6.5, 'Edit File in\nBrowser', '#d1fae5', '#059669'),
    (11.2, 6.5, 'Delete / Rename\n/ Replace File', '#d1fae5', '#059669'),
]
for x, y, t, fc, ec in admin_ucs:
    usecase(ax, x, y, 2.5, 0.9, t, fc=fc, ec=ec)
    ax.plot([1.65, x-1.25], [7.5, y], color='#d97706', lw=1, zorder=2)

# User use cases
user_ucs = [
    (5.8, 4.8, 'Login / Register\n(MFA · WebAuthn)', C['sky'], C['blue']),
    (8.5, 4.8, 'Submit Action\nRequest', '#fee2e2', '#dc2626'),
    (11.2, 4.8, 'View My\nRequests', C['sky'], C['blue']),
    (5.8, 3.3, 'Execute Approved\nOperation', '#fce7f3', '#db2777'),
    (8.5, 3.3, 'View & Download\nShared Files', C['sky'], C['blue']),
    (11.2, 3.3, 'Update Profile\n& Notifications', C['sky'], C['blue']),
    (7.95, 1.8, 'View Monitored\nFiles (own clearance)', '#ede9fe', '#7c3aed'),
]
for x, y, t, fc, ec in user_ucs:
    usecase(ax, x, y, 2.5, 0.9, t, fc=fc, ec=ec)
    ax.plot([1.65, x-1.25], [3.5, y], color='#2563eb', lw=1, zorder=2)

# Scheduler use cases
sched_ucs = [
    (11.2, 6.5, 'Periodic FIM\nScan (5 min)', None, None),
    (11.2, 5.2, 'Recovery\nScan (15 min)', None, None),
    (11.2, 3.9, 'Escalate\nAlerts (1 hr)', None, None),
]
sched_uc_data = [
    (12.0, 6.3, 'Periodic FIM\nScan (5 min)', '#f0fdf4', '#16a34a'),
    (12.0, 5.0, 'Recovery Scan\n(15 min)', '#f0fdf4', '#16a34a'),
    (12.0, 3.7, 'Auto-Escalate\nAlerts (1 hr)', '#f0fdf4', '#16a34a'),
]
for x, y, t, fc, ec in sched_uc_data:
    usecase(ax, x, y, 2.3, 0.8, t, fc=fc, ec=ec, fs=7.5)
    ax.plot([14.35, x+1.15], [6.0, y], color='#059669', lw=1, zorder=2)

# Include relationship example
ax.annotate('', xy=(8.5-1.25, 4.8), xytext=(5.8+1.25, 4.8),
            arrowprops=dict(arrowstyle='->', color='#dc2626', lw=1,
                            linestyle='dashed'))
ax.text(7.15, 4.95, '«include»', ha='center', fontsize=7, color='#dc2626', style='italic')

plt.tight_layout()
plt.savefig('diagrams/2_use_case_diagram.png', dpi=180, bbox_inches='tight',
            facecolor='white')
plt.close()
print('✓ Use Case Diagram saved')


# ══════════════════════════════════════════════════════════════════════════════
# 3. SEQUENCE DIAGRAM — ActionRequest Workflow
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(16, 12))
ax.set_xlim(0, 16); ax.set_ylim(0, 12)
ax.axis('off')
title_banner(ax, 'Figure 3 — Sequence Diagram: ActionRequest Workflow (Submit → Approve → Execute)')

# Lifeline headers
lifelines = [
    (1.5,  'Non-Admin\nUser',   '#bfdbfe', '#2563eb'),
    (4.5,  'FileVault\nApp (Flask)', '#fef3c7', '#d97706'),
    (7.5,  'Database\n(PostgreSQL)', '#d1fae5', '#059669'),
    (10.5, 'Administrator\nBrowser', '#fee2e2', '#dc2626'),
    (13.5, 'Email /\nWebSocket', '#ede9fe', '#7c3aed'),
]
for x, name, fc, ec in lifelines:
    box(ax, x-0.8, 10.2, 1.6, 0.9, name, fc=fc, ec=ec, fs=8.5, bold=True)
    ax.plot([x, x], [10.2, 0.3], color='#94a3b8', lw=1.5, linestyle='--', zorder=1)

# ── Helper to draw sequence messages ────────────────────────────────────────
def seq(ax, x1, x2, y, label, color='#374151', dashed=False, ret=False):
    ls = '--' if dashed else '-'
    style = '<-' if ret else '->'
    ax.annotate('', xy=(x2, y), xytext=(x1, y),
                arrowprops=dict(arrowstyle=style, color=color, lw=1.5,
                                linestyle=ls))
    mx = (x1+x2)/2
    dy = 0.12
    ax.text(mx, y+dy, label, ha='center', va='bottom', fontsize=7.5,
            color=color, style='italic' if dashed else 'normal',
            bbox=dict(fc='white', ec='none', pad=1))

def act_box(ax, x, y, h, label, fc='#f1f5f9', ec='#475569'):
    box(ax, x-0.3, y-h, 0.6, h, '', fc=fc, ec=ec, fs=7, radius=0.05)

# Activation boxes
for y_start, y_end, x in [
    (9.8, 5.0, 1.5), (9.8, 0.8, 4.5),
    (9.5, 0.8, 7.5), (7.5, 3.5, 10.5),
]:
    rect = plt.Rectangle((x-0.2, y_end), 0.4, y_start-y_end,
                          fc='#e2e8f0', ec='#64748b', lw=1, zorder=3)
    ax.add_patch(rect)

# Step labels (left margin)
steps = [
    (9.5, '① Submit Request'),
    (8.5, '② Store in DB'),
    (7.8, '③ Notify Admin'),
    (6.9, '④ Admin Reviews'),
    (6.1, '⑤ Approve + Token'),
    (5.2, '⑥ Notify User'),
    (4.3, '⑦ User Executes'),
    (3.5, '⑧ Validate Token + Password'),
    (2.6, '⑨ Perform Operation'),
    (1.7, '⑩ Log + Notify'),
    (0.9, '⑪ Confirm to User'),
]
for y, label in steps:
    ax.text(0.05, y, label, va='center', fontsize=8,
            color='#475569', fontweight='bold')

# Sequence messages
seq(ax, 1.5, 4.5, 9.5, 'POST /fim/request (action, justification)', '#2563eb')
seq(ax, 4.5, 7.5, 8.9, 'INSERT ActionRequest (status=pending)', '#059669')
seq(ax, 4.5, 10.5, 8.1, 'SocketIO emit(action_request_update)', '#dc2626')
seq(ax, 4.5, 13.5, 7.6, 'Email: "New request pending approval"', '#7c3aed')

ax.text(10.5, 7.2, 'Admin sees\nnotification', ha='center', va='top',
        fontsize=7.5, color='#dc2626',
        bbox=dict(boxstyle='round', fc='#fee2e2', ec='#dc2626', pad=3))

seq(ax, 10.5, 4.5, 6.5, 'POST /admin/requests/approve (reason)', '#dc2626')
seq(ax, 4.5, 7.5, 6.0, 'UPDATE AR: status=approved, exec_token, expires_at', '#059669')
seq(ax, 4.5, 1.5, 5.4, 'SocketIO emit(action_request_update, token)', '#2563eb', dashed=True)
seq(ax, 4.5, 13.5, 4.9, 'Email: "Your request approved — 30 min token"', '#7c3aed')

seq(ax, 1.5, 4.5, 4.2, 'POST /download/<uuid>?token=<exec_token> + password', '#2563eb')
seq(ax, 4.5, 7.5, 3.7, 'Validate token · check clearance · verify password', '#059669')
seq(ax, 4.5, 7.5, 3.1, 'UPDATE AR: status=executed · Log FileAccess', '#059669')
seq(ax, 7.5, 4.5, 2.5, 'File content / operation result', '#059669', dashed=True, ret=True)
seq(ax, 4.5, 13.5, 2.0, 'Email Admin: "Operation executed by user"', '#7c3aed')
seq(ax, 4.5, 1.5, 1.4, '200 OK — File served / operation complete', '#2563eb', dashed=True, ret=True)

plt.tight_layout()
plt.savefig('diagrams/3_sequence_diagram.png', dpi=180, bbox_inches='tight',
            facecolor='white')
plt.close()
print('✓ Sequence Diagram saved')


# ══════════════════════════════════════════════════════════════════════════════
# 4. ARCHITECTURE DIAGRAM
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(15, 11))
ax.set_xlim(0, 15); ax.set_ylim(0, 11)
ax.axis('off')
title_banner(ax, 'Figure 4 — FileVault System Architecture Diagram (3-Tier)')

# Layer backgrounds
layers = [
    (0.3, 8.2, 14.4, 2.4, '#fef9c3', '#ca8a04', 'PRESENTATION LAYER  (Client Browser)'),
    (0.3, 4.6, 14.4, 3.4, '#f0f9ff', '#0369a1', 'APPLICATION LAYER  (Railway Cloud — Flask + Gunicorn + SocketIO)'),
    (0.3, 1.0, 14.4, 3.4, '#f0fdf4', '#15803d', 'DATA LAYER  (PostgreSQL Database + File Storage)'),
]
for x, y, w, h, fc, ec, label in layers:
    rect = FancyBboxPatch((x, y), w, h,
        boxstyle='round,pad=0.15,rounding_size=0.4',
        facecolor=fc, edgecolor=ec, linewidth=2.5, zorder=1, alpha=0.6)
    ax.add_patch(rect)
    ax.text(x+0.2, y+h-0.02, label, va='top', fontsize=9,
            fontweight='bold', color=ec)

# PRESENTATION LAYER components
pres = [
    (1.0, 8.5, 2.5, 1.5, 'Bootstrap 5\nResponsive UI', '#fef9c3', '#ca8a04'),
    (4.0, 8.5, 2.5, 1.5, 'Jinja2\nTemplates', '#fef9c3', '#ca8a04'),
    (7.0, 8.5, 2.5, 1.5, 'CodeMirror 5\nCode Editor', '#fef9c3', '#ca8a04'),
    (10.0, 8.5, 2.0, 1.5, 'Socket.IO\nClient (WS)', '#fef9c3', '#ca8a04'),
    (12.5, 8.5, 2.0, 1.5, 'CSRF Token\n(meta tag)', '#fef9c3', '#ca8a04'),
]
for x, y, w, h, t, fc, ec in pres:
    box(ax, x, y, w, h, t, fc=fc, ec=ec, fs=8.5)

# APPLICATION LAYER components
app_comps = [
    (0.6, 6.8, 2.2, 1.2, 'Authentication\n(Flask-Login\nPBKDF2 · MFA)', '#bfdbfe', '#2563eb'),
    (3.0, 6.8, 2.2, 1.2, 'MAC Access\nControl\n(Clearance 1–5)', '#ede9fe', '#7c3aed'),
    (5.4, 6.8, 2.2, 1.2, 'File Manager\n(Upload·Download\nEdit·Delete)', '#d1fae5', '#059669'),
    (7.8, 6.8, 2.2, 1.2, 'ActionRequest\nWorkflow\n(Token 30 min)', '#fee2e2', '#dc2626'),
    (10.2, 6.8, 2.0, 1.2, 'Encryption\n(AES·HKDF\nFernet)', '#fce7f3', '#db2777'),
    (12.4, 6.8, 2.1, 1.2, 'Rate Limiter\n(Flask-Limiter\nCSRF Guard)', '#fff7ed', '#ea580c'),

    (0.6, 5.2, 2.2, 1.2, 'FIM Engine\n(SHA-256\nBaseline·Check)', '#e0f2fe', '#0284c7'),
    (3.0, 5.2, 2.2, 1.2, 'FIM Scheduler\n(3 Threads\n5/15 min·1hr)', '#e0f2fe', '#0284c7'),
    (5.4, 5.2, 2.2, 1.2, 'SocketIO\nServer\n(Real-time WS)', '#fdf4ff', '#a21caf'),
    (7.8, 5.2, 2.2, 1.2, 'Email Engine\n(Resend API\nAsync)', '#fdf4ff', '#a21caf'),
    (10.2, 5.2, 2.0, 1.2, 'Activity Log\n(All events\nAudit trail)', '#fff7ed', '#ea580c'),
    (12.4, 5.2, 2.1, 1.2, 'SQLAlchemy\nORM\n(Flask-Migrate)', '#f1f5f9', '#475569'),
]
for x, y, w, h, t, fc, ec in app_comps:
    box(ax, x, y, w, h, t, fc=fc, ec=ec, fs=7.5)

# DATA LAYER components
data_comps = [
    (0.6, 1.3, 3.0, 2.5, 'PostgreSQL\nUsers · Files · Baselines\nAlerts · ActionRequests\nLogs · ShareTokens', '#d1fae5', '#059669'),
    (4.0, 1.3, 2.5, 2.5, 'File Storage\n(vault_uploads/)\nEncrypted\nCiphertext', '#d1fae5', '#059669'),
    (6.8, 1.3, 2.5, 2.5, 'SQLite\n(Local Dev)\nvault.db', '#f1f5f9', '#475569'),
    (9.6, 1.3, 2.3, 1.0, 'Resend\nEmail API', '#fdf4ff', '#a21caf'),
    (12.2, 1.3, 2.3, 1.0, 'GitHub\nCI/CD → Railway', '#f8fafc', '#1a2e4a'),
    (9.6, 2.5, 2.3, 1.0, 'Railway\nPaaS Host', '#fef9c3', '#ca8a04'),
    (12.2, 2.5, 2.3, 1.0, 'ENV Variables\n(Secrets)', '#fee2e2', '#dc2626'),
]
for x, y, w, h, t, fc, ec in data_comps:
    box(ax, x, y, w, h, t, fc=fc, ec=ec, fs=8)

# Arrows between layers
# Presentation ↔ Application
for x in [2.1, 5.1, 8.1, 11.2, 13.5]:
    ax.annotate('', xy=(x, 8.0), xytext=(x, 7.4+0.6),
                arrowprops=dict(arrowstyle='<->', color='#64748b', lw=1.2))
# Application ↔ Data
for x in [2.1, 5.1, 8.1]:
    ax.annotate('', xy=(x, 3.8), xytext=(x, 4.6+0.6),
                arrowprops=dict(arrowstyle='<->', color='#64748b', lw=1.2))

plt.tight_layout()
plt.savefig('diagrams/4_architecture_diagram.png', dpi=180, bbox_inches='tight',
            facecolor='white')
plt.close()
print('✓ Architecture Diagram saved')


# ══════════════════════════════════════════════════════════════════════════════
# 5. NETWORK DIAGRAM
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(15, 10))
ax.set_xlim(0, 15); ax.set_ylim(0, 10)
ax.axis('off')
title_banner(ax, 'Figure 5 — FileVault Network Diagram')

def net_node(ax, x, y, w, h, icon, name, sublabel='', fc='#bfdbfe', ec='#2563eb'):
    box(ax, x-w/2, y-h/2, w, h, f'{icon}\n{name}\n{sublabel}',
        fc=fc, ec=ec, fs=8, bold=True if not sublabel else False)

def net_arrow(ax, x1, y1, x2, y2, label='', color='#374151', dashed=False):
    ls = 'dashed' if dashed else 'solid'
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8,
                                linestyle=ls,
                                connectionstyle='arc3,rad=0'))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my+0.15, label, ha='center', fontsize=7.5,
                color=color, style='italic',
                bbox=dict(fc='white', ec='none', pad=1))

# Internet cloud shape
cloud = mpatches.FancyBboxPatch((5.5, 4.2), 4.0, 2.2,
    boxstyle='round,pad=0.5', facecolor='#e0f2fe', edgecolor='#0284c7',
    linewidth=2.5, zorder=2)
ax.add_patch(cloud)
ax.text(7.5, 5.3, '☁  INTERNET\nHTTPS / WSS / TLS', ha='center', va='center',
        fontsize=10, fontweight='bold', color='#0284c7', zorder=3)

# Nodes
net_node(ax, 1.8, 8.0, 2.5, 1.4, '💻', 'Admin Browser',
         'Chrome/Firefox', fc='#fde68a', ec='#d97706')
net_node(ax, 1.8, 5.3, 2.5, 1.4, '💻', 'User Browser',
         'Chrome/Firefox', fc='#bfdbfe', ec='#2563eb')
net_node(ax, 1.8, 2.5, 2.5, 1.4, '📱', 'Mobile Browser',
         '(Responsive)', fc='#bfdbfe', ec='#2563eb')

net_node(ax, 7.5, 8.5, 3.0, 1.4, '🔄', 'GitHub',
         'Source Repository\nCI/CD Trigger', fc='#f1f5f9', ec='#1a2e4a')

net_node(ax, 11.8, 7.5, 3.0, 2.0, '🚂', 'Railway PaaS',
         'Flask App\nGunicorn WSGI\nPort 8080', fc='#fef9c3', ec='#ca8a04')

net_node(ax, 11.8, 4.8, 3.0, 1.6, '🗄', 'PostgreSQL',
         'Railway DB\nPort 5432', fc='#d1fae5', ec='#059669')

net_node(ax, 11.8, 2.5, 3.0, 1.6, '📧', 'Resend API',
         'Email Delivery\napi.resend.com', fc='#fdf4ff', ec='#a21caf')

net_node(ax, 7.5, 1.5, 3.0, 1.4, '📁', 'File Storage',
         'vault_uploads/\n(Railway Volume)', fc='#d1fae5', ec='#059669')

# Network connections
# Browsers → Internet
net_arrow(ax, 3.05, 8.0, 5.5, 5.5, 'HTTPS :443\nWebSocket WSS', '#d97706')
net_arrow(ax, 3.05, 5.3, 5.5, 5.3, 'HTTPS :443', '#2563eb')
net_arrow(ax, 3.05, 2.5, 5.5, 4.8, 'HTTPS :443', '#2563eb')

# Internet → Railway
net_arrow(ax, 9.5, 5.5, 10.3, 7.5, 'HTTPS/WSS\nForwarded', '#ca8a04')

# GitHub → Railway (CI/CD)
net_arrow(ax, 9.0, 8.5, 10.3, 8.0, 'git push\n→ Auto Deploy', '#1a2e4a', dashed=True)

# Railway → PostgreSQL (internal)
net_arrow(ax, 11.8, 6.5, 11.8, 6.4, 'Internal\nTCP :5432', '#059669')
ax.annotate('', xy=(11.8, 6.4), xytext=(11.8, 6.5),
            arrowprops=dict(arrowstyle='->', color='#059669', lw=1.8))
ax.plot([11.8, 11.8], [6.5, 6.4], color='white')
net_arrow(ax, 11.8, 6.5, 11.8, 6.3, 'Internal TCP\n:5432', '#059669')

# Railway → Resend API
net_arrow(ax, 11.8, 6.5, 11.8, 3.3, 'HTTPS\nResend API', '#a21caf')

# Railway → File Storage
net_arrow(ax, 10.3, 6.8, 9.0, 2.2, 'Disk I/O\nRead/Write', '#059669', dashed=True)

# Protocol legend
legend_items = [
    ('#2563eb', 'HTTPS (TLS 1.3) — all browser traffic'),
    ('#a21caf', 'WSS (WebSocket Secure) — real-time alerts'),
    ('#059669', 'TCP (internal) — DB + file access'),
    ('#1a2e4a', 'GitHub Actions — CI/CD pipeline'),
]
for i, (color, label) in enumerate(legend_items):
    ax.plot([0.3, 0.9], [1.0-i*0.35, 1.0-i*0.35], color=color, lw=2.5)
    ax.text(1.0, 1.0-i*0.35, label, va='center', fontsize=7.5, color=color)

ax.text(0.3, 1.25, 'Network Legend:', fontsize=8, fontweight='bold', color=C['navy'])

plt.tight_layout()
plt.savefig('diagrams/5_network_diagram.png', dpi=180, bbox_inches='tight',
            facecolor='white')
plt.close()
print('✓ Network Diagram saved')


# ══════════════════════════════════════════════════════════════════════════════
# 6. DATA FLOW DIAGRAM  (Level 0 + Level 1)
# ══════════════════════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(18, 10))
fig.patch.set_facecolor('white')

# ── DFD Level 0 (Context Diagram) ───────────────────────────────────────────
ax0 = axes[0]
ax0.set_xlim(0, 9); ax0.set_ylim(0, 9)
ax0.axis('off')
ax0.text(4.5, 8.7, 'DFD Level 0 — Context Diagram', ha='center', fontsize=11,
         fontweight='bold', color=C['navy'],
         bbox=dict(boxstyle='round,pad=0.4', fc=C['sky'], ec=C['blue'], lw=1.5))

# Central process
proc = plt.Circle((4.5, 4.5), 1.8, facecolor='#fef3c7', edgecolor='#d97706',
                  linewidth=2.5, zorder=3)
ax0.add_patch(proc)
ax0.text(4.5, 4.5, 'FileVault\nSystem', ha='center', va='center',
         fontsize=11, fontweight='bold', color='#92400e', zorder=4)

def ext_entity(ax, x, y, text, fc, ec):
    rect = FancyBboxPatch((x-1.0, y-0.5), 2.0, 1.0,
        boxstyle='round,pad=0.1,rounding_size=0.2',
        facecolor=fc, edgecolor=ec, linewidth=2, zorder=3)
    ax.add_patch(rect)
    ax.text(x, y, text, ha='center', va='center', fontsize=8.5,
            fontweight='bold', color='#111827', zorder=4)

# External entities
ext_entity(ax0, 1.2, 8.0, 'Administrator', '#fde68a', '#d97706')
ext_entity(ax0, 1.2, 1.5, 'Non-Admin\nUser', '#bfdbfe', '#2563eb')
ext_entity(ax0, 7.8, 8.0, 'Email\nService', '#fdf4ff', '#a21caf')
ext_entity(ax0, 7.8, 1.5, 'File\nStorage', '#d1fae5', '#059669')

def dfd_arrow(ax, x1, y1, x2, y2, label, color='#374151'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.5))
    mx, my = (x1+x2)/2, (y1+y2)/2
    ax.text(mx, my, label, ha='center', va='center', fontsize=7,
            color=color, style='italic',
            bbox=dict(fc='white', ec='none', pad=1))

# Flows
dfd_arrow(ax0, 1.8, 7.7, 3.1, 5.8, 'Login · Upload · Approve\nManage users · View logs', '#d97706')
dfd_arrow(ax0, 3.1, 5.1, 1.8, 2.0, 'Alerts · Audit logs\nDashboard · Reports', '#d97706')
dfd_arrow(ax0, 1.8, 1.8, 3.1, 3.5, 'Login · Submit Request\nExecute operation', '#2563eb')
dfd_arrow(ax0, 3.1, 3.8, 1.8, 1.5, 'Approval status\nFiles · Notifications', '#2563eb')
dfd_arrow(ax0, 5.9, 5.8, 7.2, 7.7, 'Alert emails\nNotifications', '#a21caf')
dfd_arrow(ax0, 5.9, 3.5, 7.2, 1.8, 'Read/Write\nEncrypted files', '#059669')
dfd_arrow(ax0, 7.2, 1.5, 5.9, 3.2, 'File content', '#059669')

# ── DFD Level 1 ─────────────────────────────────────────────────────────────
ax1 = axes[1]
ax1.set_xlim(0, 9); ax1.set_ylim(0, 9)
ax1.axis('off')
ax1.text(4.5, 8.7, 'DFD Level 1 — Internal Processes', ha='center', fontsize=11,
         fontweight='bold', color=C['navy'],
         bbox=dict(boxstyle='round,pad=0.4', fc=C['sky'], ec=C['blue'], lw=1.5))

def process(ax, x, y, r, text, fc, ec):
    circ = plt.Circle((x, y), r, facecolor=fc, edgecolor=ec, lw=1.8, zorder=3)
    ax.add_patch(circ)
    ax.text(x, y, text, ha='center', va='center', fontsize=7.5,
            fontweight='bold', color='#111827',
            multialignment='center', zorder=4)

def datastore(ax, x, y, w, text, fc='#f1f5f9', ec='#475569'):
    ax.plot([x, x+w], [y, y], color=ec, lw=2, zorder=3)
    ax.plot([x, x+w], [y-0.35, y-0.35], color=ec, lw=2, zorder=3)
    ax.plot([x, x], [y, y-0.35], color=ec, lw=1.5, zorder=3)
    ax.plot([x+w, x+w], [y, y-0.35], color=ec, lw=1.5, zorder=3)
    rect = plt.Rectangle((x, y-0.35), w, 0.35, fc=fc, ec='none', zorder=2)
    ax.add_patch(rect)
    ax.text(x+w/2, y-0.17, text, ha='center', va='center',
            fontsize=7, color='#111827', zorder=4)

# Processes
process(ax1, 1.5, 7.2, 0.75, 'P1\nAuth &\nSession', '#fef3c7', '#d97706')
process(ax1, 4.5, 7.2, 0.75, 'P2\nMAC\nControl', '#ede9fe', '#7c3aed')
process(ax1, 7.5, 7.2, 0.75, 'P3\nFile\nEncrypt', '#fce7f3', '#db2777')
process(ax1, 1.5, 4.5, 0.75, 'P4\nAction\nRequest', '#fee2e2', '#dc2626')
process(ax1, 4.5, 4.5, 0.75, 'P5\nFIM\nEngine', '#e0f2fe', '#0284c7')
process(ax1, 7.5, 4.5, 0.75, 'P6\nNotify\nEngine', '#fdf4ff', '#a21caf')
process(ax1, 4.5, 1.8, 0.75, 'P7\nAudit\nLogger', '#fff7ed', '#ea580c')

# Data stores
datastore(ax1, 0.2, 2.5, 1.8, 'DS1: Users', '#f1f5f9', '#475569')
datastore(ax1, 2.5, 2.5, 1.8, 'DS2: Files + Baselines', '#d1fae5', '#059669')
datastore(ax1, 5.0, 2.5, 1.8, 'DS3: ActionRequests', '#fee2e2', '#dc2626')
datastore(ax1, 7.0, 2.5, 1.8, 'DS4: Alerts + Logs', '#fff7ed', '#ea580c')

datastore(ax1, 0.2, 1.2, 2.5, 'DS5: ActivityLog', '#fdf4ff', '#a21caf')
datastore(ax1, 3.5, 1.2, 2.5, 'DS6: FileAccessLog', '#fdf4ff', '#a21caf')
datastore(ax1, 6.5, 1.2, 2.0, 'DS7: ShareTokens', '#f1f5f9', '#475569')

# Data flows between processes
def fl(ax, x1, y1, x2, y2, label='', c='#374151'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=c, lw=1.2))
    mx, my = (x1+x2)/2+0.05, (y1+y2)/2+0.1
    if label:
        ax.text(mx, my, label, ha='center', fontsize=6.5, color=c, style='italic')

fl(ax1, 2.25, 7.2, 3.75, 7.2, 'Credentials\nverified', '#d97706')
fl(ax1, 5.25, 7.2, 6.75, 7.2, 'Clearance\ncheck pass', '#7c3aed')
fl(ax1, 4.5, 6.45, 4.5, 5.25, 'Allowed\nfile ID', '#7c3aed')
fl(ax1, 5.25, 4.5, 6.75, 4.5, 'Trigger\nalert', '#0284c7')
fl(ax1, 1.5, 5.25, 1.5, 3.2, 'Request\ndata', '#dc2626')
fl(ax1, 2.25, 4.5, 3.75, 4.5, 'AR\napproved', '#dc2626')
fl(ax1, 4.5, 3.75, 4.5, 3.2, 'Log\nevent', '#059669')
fl(ax1, 4.5, 2.55, 4.5, 2.55, '', '#ea580c')
fl(ax1, 1.5, 3.75, 3.0, 1.35, 'Write\nlog', '#ea580c')
fl(ax1, 7.5, 3.75, 7.0, 2.85, 'Log\nalert', '#ea580c')
fl(ax1, 1.1, 2.5, 1.1, 2.15, 'User\nrecord', '#475569')
fl(ax1, 3.5, 2.5, 3.4, 2.15, 'File\nmetadata', '#059669')

plt.tight_layout()
plt.savefig('diagrams/6_data_flow_diagram.png', dpi=180, bbox_inches='tight',
            facecolor='white')
plt.close()
print('✓ Data Flow Diagram saved')

print('\n✅ All 6 diagrams saved in diagrams/ folder:')
for f in sorted(os.listdir('diagrams')):
    path = os.path.join('diagrams', f)
    size = os.path.getsize(path) // 1024
    print(f'   {f}  ({size} KB)')
