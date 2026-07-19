import os
os.makedirs('diagrams', exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

# ─── helpers ──────────────────────────────────────────────────────────────────
def flowbox(ax, x, y, w, h, text, shape='rect',
            fc='#bfdbfe', ec='#2563eb', fs=9, tc='#111827'):
    if shape == 'diamond':
        cx, cy = x+w/2, y+h/2
        hw, hh = w/2, h/2
        ax.add_patch(plt.Polygon(
            [[cx,cy+hh],[cx+hw,cy],[cx,cy-hh],[cx-hw,cy]],
            facecolor=fc, edgecolor=ec, lw=2, zorder=3))
        ax.text(cx, cy, text, ha='center', va='center', fontsize=fs,
                fontweight='bold', color=tc, multialignment='center', zorder=4)
    elif shape == 'oval':
        ax.add_patch(mpatches.Ellipse((x+w/2, y+h/2), w, h,
                     facecolor=fc, edgecolor=ec, lw=2, zorder=3))
        ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs,
                fontweight='bold', color=tc, zorder=4)
    else:
        ax.add_patch(FancyBboxPatch((x,y), w, h,
                     boxstyle='round,pad=0.1,rounding_size=0.25',
                     facecolor=fc, edgecolor=ec, lw=2, zorder=3))
        ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs,
                fontweight='bold', color=tc, multialignment='center', zorder=4)

def arr(ax, x1, y1, x2, y2, color='#374151', dashed=False):
    ax.annotate('', xy=(x2,y2), xytext=(x1,y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8,
                                linestyle='dashed' if dashed else 'solid'))

def lbl(ax, x, y, text, color='#374151', fs=8.5):
    ax.text(x, y, text, ha='center', fontsize=fs,
            color=color, fontweight='bold')

def title_banner(ax, text):
    ax.text(0.5, 0.98, text, transform=ax.transAxes,
            ha='center', va='top', fontsize=12, fontweight='bold', color='#1a2e4a',
            bbox=dict(boxstyle='round,pad=0.4', fc='#bfdbfe', ec='#2563eb', lw=1.8))


# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 9 — ActionRequest Approval Workflow
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 15))
ax.set_xlim(0, 10); ax.set_ylim(0, 15)
ax.axis('off')
fig.patch.set_facecolor('white')
title_banner(ax, 'Figure 9: ActionRequest Approval Workflow')

# Start
flowbox(ax, 3.2, 13.8, 3.6, 0.75, 'User Selects\nRestricted Operation',
        shape='oval', fc='#1e40af', ec='#1e40af', tc='white')

flowbox(ax, 2.8, 12.5, 4.4, 0.9,
        'Submit ActionRequest\n(action + justification)', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 2.8, 11.2, 4.4, 0.9,
        'Record in DB\nstatus = pending', fc='#f1f5f9', ec='#475569')

flowbox(ax, 2.8, 9.9, 4.4, 0.9,
        'Notify Admin\n(SocketIO + Email)', fc='#fdf4ff', ec='#a21caf')

flowbox(ax, 2.6, 8.3, 4.8, 1.2,
        'Admin Reviews\nRequest?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Reject path (left)
flowbox(ax, 0.2, 7.5, 2.5, 0.85,
        'Status = rejected\nReason recorded', fc='#fee2e2', ec='#dc2626', tc='#7f1d1d')
flowbox(ax, 0.2, 6.3, 2.5, 0.85,
        'Notify User\n(SocketIO + Email)', fc='#fdf4ff', ec='#a21caf')
flowbox(ax, 0.4, 5.1, 2.1, 0.75, 'Request Closed',
        shape='oval', fc='#dc2626', ec='#dc2626', tc='white', fs=8.5)

# Approve path (right)
flowbox(ax, 7.3, 7.5, 2.5, 0.85,
        'Status = approved\nGenerate exec_token', fc='#d1fae5', ec='#059669')
flowbox(ax, 7.3, 6.3, 2.5, 0.85,
        'Token valid\n30 minutes', fc='#d1fae5', ec='#059669')
flowbox(ax, 7.3, 5.1, 2.5, 0.85,
        'Notify User\n(SocketIO + Email)', fc='#fdf4ff', ec='#a21caf')

# User executes
flowbox(ax, 2.8, 3.8, 4.4, 0.9,
        'User Submits Operation\nwith exec_token + password', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 2.6, 2.4, 4.8, 1.2,
        'Token valid &\nnot expired?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

flowbox(ax, 2.8, 1.1, 4.4, 0.9,
        'Execute Operation\nLog + status = executed', fc='#d1fae5', ec='#059669')

flowbox(ax, 3.5, 0.15, 3.0, 0.75, 'Operation Complete',
        shape='oval', fc='#15803d', ec='#15803d', tc='white')

# Expired token deny
flowbox(ax, 7.3, 2.9, 2.5, 0.85,
        'DENY\nToken expired/invalid', fc='#fee2e2', ec='#dc2626', tc='#7f1d1d')

# Main flow arrows
arr(ax, 5.0, 13.8, 5.0, 13.4)
arr(ax, 5.0, 12.5, 5.0, 12.1)
arr(ax, 5.0, 11.2, 5.0, 10.8)
arr(ax, 5.0, 9.9,  5.0, 9.5)
arr(ax, 5.0, 8.3,  5.0, 4.7)
arr(ax, 5.0, 3.8,  5.0, 3.6)
arr(ax, 5.0, 2.4,  5.0, 2.0)
arr(ax, 5.0, 1.1,  5.0, 0.9)

# Reject branch
ax.plot([2.6, 1.5], [8.9, 8.9], color='#374151', lw=1.5)
arr(ax, 1.5, 8.9, 1.5, 8.35, color='#dc2626')
arr(ax, 1.5, 7.5, 1.5, 7.15)
arr(ax, 1.5, 6.3, 1.5, 5.85)
lbl(ax, 2.2, 9.05, 'Reject', '#dc2626')

# Approve branch
ax.plot([7.4, 8.5], [8.9, 8.9], color='#374151', lw=1.5)
arr(ax, 8.5, 8.9, 8.5, 8.35, color='#059669')
arr(ax, 8.5, 7.5, 8.5, 7.15)
arr(ax, 8.5, 6.3, 8.5, 5.95)
lbl(ax, 7.0, 9.05, 'Approve', '#059669')

# Approved → user executes
ax.plot([8.5, 8.5], [5.1, 4.25], color='#374151', lw=1.5)
arr(ax, 8.5, 4.25, 7.2, 4.25, color='#059669')

# Token invalid → deny
ax.plot([7.4, 8.5], [3.0, 3.0], color='#374151', lw=1.5)
arr(ax, 8.5, 3.0, 9.8, 3.35, color='#dc2626')
lbl(ax, 7.0, 3.15, 'No', '#dc2626')
lbl(ax, 5.18, 3.0, 'Yes', '#059669')

plt.tight_layout()
plt.savefig('diagrams/fig9_actionrequest_workflow.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('[OK] Figure 9 saved')


# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 10 — File Integrity Monitoring Cycle
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 14))
ax.set_xlim(0, 10); ax.set_ylim(0, 14)
ax.axis('off')
fig.patch.set_facecolor('white')
title_banner(ax, 'Figure 10: File Integrity Monitoring Cycle')

flowbox(ax, 3.2, 12.8, 3.6, 0.75, 'File Uploaded\nby Administrator',
        shape='oval', fc='#1e40af', ec='#1e40af', tc='white')

flowbox(ax, 2.8, 11.5, 4.4, 0.9,
        'Compute SHA-256 Hash\nof Encrypted File', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 2.8, 10.2, 4.4, 0.9,
        'Store Baseline Hash\nin FileBaseline Table', fc='#f0fdf4', ec='#059669')

flowbox(ax, 2.6,  8.7, 4.8, 1.2,
        'monitoring_enabled\nfor this file?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Skip path
flowbox(ax, 6.8, 8.85, 2.8, 0.75,
        'Skip — No Scan\nScheduled', fc='#f1f5f9', ec='#94a3b8', fs=8.5)

flowbox(ax, 2.8, 7.4, 4.4, 0.9,
        'FIM Scheduler Triggers\nScan (every 5 min)', fc='#fff7ed', ec='#ea580c')

flowbox(ax, 2.8, 6.1, 4.4, 0.9,
        'Recompute SHA-256\nHash of File', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 2.6, 4.6, 4.8, 1.2,
        'Hash matches\nbaseline?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# OK path
flowbox(ax, 6.8, 4.75, 2.8, 0.75,
        'Status = OK\nUpdate last_checked_at', fc='#d1fae5', ec='#059669', fs=8.5)

flowbox(ax, 2.8, 3.3, 4.4, 0.9,
        'Raise FIMAlert\n(tampered / missing)', fc='#fee2e2', ec='#dc2626')

flowbox(ax, 2.8, 2.1, 4.4, 0.9,
        'Notify Admin\n(SocketIO + Email)', fc='#fdf4ff', ec='#a21caf')

flowbox(ax, 2.6, 0.7, 4.8, 1.1,
        'Wait for Next\nScheduled Scan\n(5 min cycle)',
        shape='oval', fc='#374151', ec='#374151', tc='white', fs=8.5)

# Arrows
arr(ax, 5.0, 12.8, 5.0, 12.4)
arr(ax, 5.0, 11.5, 5.0, 11.1)
arr(ax, 5.0, 10.2, 5.0, 9.9)
arr(ax, 5.0,  8.7, 5.0, 8.3)
arr(ax, 5.0,  7.4, 5.0, 7.0)
arr(ax, 5.0,  6.1, 5.0, 5.8)
arr(ax, 5.0,  4.6, 5.0, 4.2)
arr(ax, 5.0,  3.3, 5.0, 3.0)
arr(ax, 5.0,  2.1, 5.0, 1.8)

# Monitoring disabled
ax.plot([7.4, 8.2], [9.3, 9.3], color='#374151', lw=1.5)
arr(ax, 8.2, 9.3, 8.2, 9.23, color='#94a3b8')
lbl(ax, 7.0, 9.42, 'No', '#94a3b8')
lbl(ax, 5.18, 9.3, 'Yes', '#059669')

# Hash matches
ax.plot([7.4, 8.2], [5.2, 5.2], color='#374151', lw=1.5)
arr(ax, 8.2, 5.2, 9.6, 5.12, color='#059669')
lbl(ax, 6.8, 5.35, 'Yes', '#059669')
lbl(ax, 5.18, 5.2, 'No', '#dc2626')

# Cycle back arrow (after OK and after notify)
ax.plot([9.5, 9.5], [4.75, 1.25], color='#374151', lw=1.5, linestyle='--')
arr(ax, 9.5, 1.25, 7.6, 1.25, color='#374151', dashed=True)
ax.text(9.65, 3.0, 'Back to\nnext cycle', ha='left', fontsize=7.5,
        color='#374151', style='italic')

plt.tight_layout()
plt.savefig('diagrams/fig10_fim_cycle.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('[OK] Figure 10 saved')


# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 11 — Integrity Alert Lifecycle
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(13, 9))
ax.set_xlim(0, 13); ax.set_ylim(0, 9)
ax.axis('off')
fig.patch.set_facecolor('white')
title_banner(ax, 'Figure 11: Integrity Alert Lifecycle')

states = [
    (1.2,  4.0, 2.2, 1.4, 'OPEN',          '#dc2626', '#fee2e2', '#7f1d1d'),
    (4.2,  5.5, 2.2, 1.4, 'ACKNOWLEDGED',  '#d97706', '#fef3c7', '#78350f'),
    (7.2,  5.5, 2.2, 1.4, 'RESOLVED',      '#059669', '#d1fae5', '#064e3b'),
    (4.2,  2.2, 2.2, 1.4, 'ESCALATED',     '#7c3aed', '#ede9fe', '#3b0764'),
    (7.2,  2.2, 2.2, 1.4, 'FALSE POSITIVE','#0284c7', '#e0f2fe', '#0c4a6e'),
    (10.2, 4.0, 2.2, 1.4, 'CLOSED',        '#374151', '#f1f5f9', '#111827'),
]

for x, y, w, h, name, ec, fc, tc in states:
    rect = FancyBboxPatch((x, y), w, h,
        boxstyle='round,pad=0.15,rounding_size=0.3',
        facecolor=fc, edgecolor=ec, linewidth=2.5, zorder=3)
    ax.add_patch(rect)
    ax.text(x+w/2, y+h/2, name, ha='center', va='center',
            fontsize=10, fontweight='bold', color=tc, zorder=4)

# Start
ax.add_patch(mpatches.Ellipse((0.5, 4.7), 0.7, 0.7,
             facecolor='#1a2e4a', edgecolor='#1a2e4a', zorder=3))
ax.text(0.5, 3.85, 'FIM\nDetects\nTamper', ha='center', fontsize=7.5,
        color='#1a2e4a', fontweight='bold')

# End
ax.add_patch(mpatches.Ellipse((12.4, 4.7), 0.6, 0.6,
             facecolor='white', edgecolor='#1a2e4a', lw=2.5, zorder=3))
ax.add_patch(mpatches.Ellipse((12.4, 4.7), 0.4, 0.4,
             facecolor='#1a2e4a', edgecolor='#1a2e4a', zorder=4))

def state_arr(ax, x1, y1, x2, y2, label, color='#374151', rad=0.0):
    ax.annotate('', xy=(x2,y2), xytext=(x1,y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.6,
                                connectionstyle=f'arc3,rad={rad}'))
    mx, my = (x1+x2)/2, (y1+y2)/2
    ax.text(mx, my+0.18, label, ha='center', fontsize=7.5,
            color=color, style='italic',
            bbox=dict(fc='white', ec='none', pad=1))

# Transitions
state_arr(ax, 0.85, 4.7, 1.2, 4.7, 'Raised', '#dc2626')
state_arr(ax, 3.4, 5.2, 4.2, 5.9, 'Admin\nAcknowledges', '#d97706')
state_arr(ax, 6.4, 6.2, 7.2, 6.2, 'Admin\nResolves', '#059669')
state_arr(ax, 3.4, 4.3, 4.2, 2.9, '1hr: Auto\nEscalate', '#7c3aed')
state_arr(ax, 3.4, 5.0, 4.2, 3.1, 'Mark False\nPositive', '#0284c7', rad=0.3)
state_arr(ax, 6.4, 2.9, 7.2, 2.9, 'Admin\nConfirms FP', '#0284c7')
state_arr(ax, 9.4, 6.2, 10.2, 4.9, 'Closed', '#374151')
state_arr(ax, 9.4, 2.9, 10.2, 4.3, 'Closed', '#374151')
state_arr(ax, 6.4, 4.7, 10.2, 4.7, 'Direct\nResolve', '#059669', rad=-0.2)
state_arr(ax, 12.1, 4.7, 11.8, 4.7, '', '#1a2e4a')

# Re-open arrow (resolved back to open if tamper re-detected)
ax.annotate('', xy=(2.3, 5.4), xytext=(7.2, 6.5),
            arrowprops=dict(arrowstyle='->', color='#dc2626', lw=1.3,
                            linestyle='dashed', connectionstyle='arc3,rad=0.4'))
ax.text(4.8, 7.3, 'Re-detected\n(new tamper)', ha='center', fontsize=7.5,
        color='#dc2626', style='italic')

# Legend
legend = [('#dc2626','OPEN'), ('#d97706','ACKNOWLEDGED'), ('#7c3aed','ESCALATED'),
          ('#059669','RESOLVED'), ('#0284c7','FALSE POSITIVE'), ('#374151','CLOSED')]
for i,(c,n) in enumerate(legend):
    ax.add_patch(FancyBboxPatch((0.2+i*2.1, 0.2), 1.8, 0.45,
        boxstyle='round,pad=0.05', facecolor=c+'22', edgecolor=c, lw=1.5))
    ax.text(0.2+i*2.1+0.9, 0.43, n, ha='center', va='center',
            fontsize=7, color=c, fontweight='bold')

plt.tight_layout()
plt.savefig('diagrams/fig11_alert_lifecycle.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('[OK] Figure 11 saved')


# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 15 — Deployment Architecture on Railway
# ══════════════════════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(14, 10))
ax.set_xlim(0, 14); ax.set_ylim(0, 10)
ax.axis('off')
fig.patch.set_facecolor('white')
title_banner(ax, 'Figure 15: Deployment Architecture on Railway')

def box(ax, x, y, w, h, text, fc, ec, fs=9, bold=False, tc='#111827'):
    ax.add_patch(FancyBboxPatch((x,y), w, h,
        boxstyle='round,pad=0.1,rounding_size=0.3',
        facecolor=fc, edgecolor=ec, lw=2, zorder=3))
    ax.text(x+w/2, y+h/2, text, ha='center', va='center',
            fontsize=fs, fontweight='bold' if bold else 'normal',
            color=tc, multialignment='center', zorder=4)

def pipe_arr(ax, x1, y1, x2, y2, label='', color='#475569', dashed=False):
    ax.annotate('', xy=(x2,y2), xytext=(x1,y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8,
                                linestyle='dashed' if dashed else 'solid'))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my+0.18, label, ha='center', fontsize=7.5, color=color,
                style='italic', bbox=dict(fc='white', ec='none', pad=1))

# Developer workstation
box(ax, 0.2, 7.5, 2.8, 2.0,
    'Developer\nWorkstation\n\npython / git\nlocal dev', '#f1f5f9', '#475569', fs=8.5)

# GitHub
box(ax, 4.0, 7.5, 2.8, 2.0,
    'GitHub\nRepository\n\nmain branch\nsource code', '#f8fafc', '#1a2e4a', fs=8.5, bold=False)

# Railway platform boundary
rail_bg = FancyBboxPatch((7.5, 1.0), 6.2, 8.5,
    boxstyle='round,pad=0.2,rounding_size=0.4',
    facecolor='#fefce8', edgecolor='#ca8a04', lw=2.5, zorder=1, alpha=0.5)
ax.add_patch(rail_bg)
ax.text(10.6, 9.6, 'RAILWAY CLOUD PLATFORM', ha='center', fontsize=10,
        fontweight='bold', color='#92400e')

# Railway web service
box(ax, 7.8, 6.8, 5.6, 1.8,
    'Railway Web Service\n\nFlask 3.0 + Gunicorn (4 workers)\nSocket.IO  |  Port 8080  |  HTTPS auto', '#fef9c3', '#ca8a04', fs=8.5, bold=True)

# Railway PostgreSQL
box(ax, 7.8, 4.5, 2.6, 1.8,
    'Railway\nPostgreSQL\n\nManaged DB\nPort 5432', '#d1fae5', '#059669', fs=8.5)

# Railway Volume
box(ax, 11.0, 4.5, 2.6, 1.8,
    'Railway\nVolume\n\nvault_uploads/\nEncrypted files', '#e0f2fe', '#0284c7', fs=8.5)

# ENV Variables
box(ax, 7.8, 2.0, 2.6, 2.0,
    'Environment\nVariables\n\nSECRET_KEY\nDATABASE_URL\nRESEND_API_KEY', '#fff7ed', '#ea580c', fs=7.5)

# Resend API (external)
box(ax, 11.0, 2.0, 2.6, 2.0,
    'Resend API\n(External)\n\nEmail delivery\napi.resend.com', '#fdf4ff', '#a21caf', fs=8.5)

# Users
box(ax, 0.2, 3.5, 2.8, 2.0,
    'End Users\n(Browsers)\n\nAdmin + Users\nHTTPS / WSS', '#bfdbfe', '#2563eb', fs=8.5)

box(ax, 0.2, 1.0, 2.8, 2.0,
    'Mobile Users\n(Browsers)\n\nResponsive UI\nHTTPS', '#bfdbfe', '#2563eb', fs=8.5)

# Arrows
pipe_arr(ax, 3.0, 8.5, 4.0, 8.5, 'git push', '#1a2e4a')
pipe_arr(ax, 6.8, 8.5, 7.8, 8.1, 'Auto Deploy\n(webhook)', '#ca8a04')
pipe_arr(ax, 3.0, 4.5, 7.5, 7.5, 'HTTPS :443\nWebSocket', '#2563eb')
pipe_arr(ax, 3.0, 2.0, 7.5, 7.2, 'HTTPS :443', '#2563eb')
pipe_arr(ax, 10.6, 6.8, 10.6, 6.3, 'SQLAlchemy\nORM', '#059669')
pipe_arr(ax, 11.8, 6.8, 11.8, 6.3, 'Disk I/O', '#0284c7')
pipe_arr(ax, 9.1, 4.5, 9.1, 4.0, 'Read ENV\nat startup', '#ea580c')
pipe_arr(ax, 12.3, 4.5, 12.3, 4.0, 'HTTPS POST', '#a21caf')

# GitHub Actions note
ax.text(5.4, 7.3, 'GitHub Actions\nCI/CD Pipeline', ha='center', fontsize=7.5,
        color='#1a2e4a', style='italic',
        bbox=dict(boxstyle='round,pad=0.3', fc='#f8fafc', ec='#1a2e4a', lw=1))

plt.tight_layout()
plt.savefig('diagrams/fig15_deployment_railway.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('[OK] Figure 15 saved')

print('\nAll diagrams done.')
