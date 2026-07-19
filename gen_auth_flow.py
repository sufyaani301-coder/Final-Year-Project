import os
os.makedirs('diagrams', exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(10, 16))
ax.set_xlim(0, 10); ax.set_ylim(0, 16)
ax.axis('off')
fig.patch.set_facecolor('white')

ax.text(5.0, 15.55, 'Figure 5: User Authentication Flow', ha='center', va='center',
        fontsize=13, fontweight='bold', color='#1a2e4a',
        bbox=dict(boxstyle='round,pad=0.4', fc='#bfdbfe', ec='#2563eb', lw=1.8))

def flowbox(ax, x, y, w, h, text, shape='rect',
            fc='#bfdbfe', ec='#2563eb', fs=9, tc='#111827'):
    if shape == 'diamond':
        cx, cy = x + w/2, y + h/2
        hw, hh = w/2, h/2
        diamond = plt.Polygon(
            [[cx, cy+hh],[cx+hw, cy],[cx, cy-hh],[cx-hw, cy]],
            facecolor=fc, edgecolor=ec, lw=2, zorder=3)
        ax.add_patch(diamond)
        ax.text(cx, cy, text, ha='center', va='center', fontsize=fs,
                fontweight='bold', color=tc, multialignment='center', zorder=4)
    elif shape == 'oval':
        ell = mpatches.Ellipse((x+w/2, y+h/2), w, h,
                               facecolor=fc, edgecolor=ec, lw=2, zorder=3)
        ax.add_patch(ell)
        ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs,
                fontweight='bold', color=tc, zorder=4)
    else:
        rect = FancyBboxPatch((x, y), w, h,
                              boxstyle='round,pad=0.1,rounding_size=0.25',
                              facecolor=fc, edgecolor=ec, lw=2, zorder=3)
        ax.add_patch(rect)
        ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs,
                fontweight='bold', color=tc, multialignment='center', zorder=4)

def arr(ax, x1, y1, x2, y2):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color='#374151', lw=1.8))

def side_deny(ax, x_from, y_from, label, note=''):
    ax.plot([x_from, 8.0], [y_from, y_from], color='#374151', lw=1.5)
    ax.annotate('', xy=(8.0, y_from - 0.01),
                xytext=(8.0, y_from),
                arrowprops=dict(arrowstyle='->', color='#dc2626', lw=1.8))
    fb = FancyBboxPatch((7.8, y_from - 0.85), 1.9, 0.72,
        boxstyle='round,pad=0.05,rounding_size=0.15',
        facecolor='#fee2e2', edgecolor='#dc2626', lw=1.8, zorder=3)
    ax.add_patch(fb)
    ax.text(8.75, y_from - 0.49, label, ha='center', va='center',
            fontsize=7.5, fontweight='bold', color='#7f1d1d',
            multialignment='center', zorder=4)
    if note:
        ax.text(8.75, y_from - 1.05, note, ha='center', fontsize=6.8,
                color='#dc2626', style='italic')

def yes_no(ax, x, y, is_yes=True):
    color = '#059669' if is_yes else '#dc2626'
    label = 'Yes' if is_yes else 'No'
    ax.text(x, y, label, ha='center', fontsize=8.5,
            color=color, fontweight='bold')

# ── NODES ─────────────────────────────────────────────────────────────────────

# Start
flowbox(ax, 3.5, 14.8, 3.0, 0.7, 'User Visits Login Page',
        shape='oval', fc='#1a2e4a', ec='#1a2e4a', tc='white')

# Step 1 — enter credentials
flowbox(ax, 3.0, 13.5, 4.0, 0.85,
        'Enter Username & Password', fc='#e0f2fe', ec='#0284c7')

# Decision 1 — user exists?
flowbox(ax, 2.8, 11.9, 4.4, 1.2,
        'Username exists\nin database?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Decision 2 — password correct?
flowbox(ax, 2.8, 10.0, 4.4, 1.2,
        'Password hash\nmatches? (PBKDF2)',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Step — log failed attempt
flowbox(ax, 3.0, 8.7, 4.0, 0.85,
        'Log Failed Attempt\n& Check Threshold',
        fc='#fff7ed', ec='#ea580c')

# Decision 3 — threshold exceeded?
flowbox(ax, 2.8, 7.1, 4.4, 1.2,
        'Failed attempts\n>= threshold?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Alert admin
flowbox(ax, 3.0, 5.9, 4.0, 0.85,
        'Emit Security Alert\nto Admin (SocketIO + Email)',
        fc='#fee2e2', ec='#dc2626')

# Decision 4 — MFA enabled?
flowbox(ax, 2.8, 4.5, 4.4, 1.2,
        'MFA (TOTP)\nenabled for user?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Step — prompt TOTP
flowbox(ax, 3.0, 3.2, 4.0, 0.85,
        'Prompt for\nTOTP Code', fc='#e0f2fe', ec='#0284c7')

# Decision 5 — TOTP valid?
flowbox(ax, 2.8, 1.8, 4.4, 1.2,
        'TOTP code\nvalid?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# End — session created
flowbox(ax, 3.5, 0.3, 3.0, 0.8,
        'Create Session\nRedirect to Dashboard',
        shape='oval', fc='#15803d', ec='#15803d', tc='white')

# ── ARROWS ────────────────────────────────────────────────────────────────────
arr(ax, 5.0, 14.8, 5.0, 14.35)
arr(ax, 5.0, 13.5, 5.0, 13.1)
arr(ax, 5.0, 11.9, 5.0, 11.2)   # down from decision 1
arr(ax, 5.0, 10.0, 5.0, 9.55)   # down from decision 2 (No path → log)
arr(ax, 5.0, 8.7,  5.0, 8.35)
arr(ax, 5.0, 7.1,  5.0, 6.75)   # yes → alert
arr(ax, 5.0, 5.9,  5.0, 5.55)   # after alert
arr(ax, 5.0, 4.5,  5.0, 4.05)   # yes → prompt TOTP
arr(ax, 5.0, 3.2,  5.0, 2.85)
arr(ax, 5.0, 1.8,  5.0, 1.0)
arr(ax, 5.0, 1.0,  5.0, 0.3)    # yes → session

# ── SIDE DENIES & BYPASSES ───────────────────────────────────────────────────
# User not found → deny
ax.plot([7.2, 8.0], [12.5, 12.5], color='#374151', lw=1.5)
ax.annotate('', xy=(8.0, 11.9),
            xytext=(8.0, 12.5),
            arrowprops=dict(arrowstyle='->', color='#dc2626', lw=1.8))
box1 = FancyBboxPatch((7.8, 11.3), 1.9, 0.65,
    boxstyle='round,pad=0.05,rounding_size=0.15',
    facecolor='#fee2e2', edgecolor='#dc2626', lw=1.8, zorder=3)
ax.add_patch(box1)
ax.text(8.75, 11.625, 'DENY\nInvalid credentials', ha='center', va='center',
        fontsize=7.5, fontweight='bold', color='#7f1d1d',
        multialignment='center', zorder=4)
ax.text(6.8, 12.62, 'No', fontsize=8.5, color='#dc2626', fontweight='bold')

# Password wrong → log (Yes = correct, continue down; No = log)
# Actually on decision 2: Yes = password matches → continue; No = log failed
yes_no(ax, 5.18, 9.7, is_yes=True)   # yes down to log? No — yes = correct password

# Rewrite: Decision 2 Yes = password correct → skip log, go to MFA check
# Let me draw a bypass arrow: if password correct, skip log+threshold, go to MFA
ax.plot([7.2, 8.5, 8.5], [10.6, 10.6, 5.1], color='#059669', lw=1.8, linestyle='--')
ax.annotate('', xy=(7.2, 5.1),
            xytext=(8.5, 5.1),
            arrowprops=dict(arrowstyle='->', color='#059669', lw=1.8))
ax.text(8.65, 8.0, 'Password\ncorrect\n(skip log)', ha='left', fontsize=7.5,
        color='#059669', style='italic')
ax.text(6.8, 10.7, 'Yes', fontsize=8.5, color='#059669', fontweight='bold')
ax.text(5.18, 10.6, 'No', fontsize=8.5, color='#dc2626', fontweight='bold')

# Threshold not reached → back to login
ax.plot([7.2, 8.8], [7.7, 7.7], color='#374151', lw=1.5)
ax.annotate('', xy=(8.8, 7.1),
            xytext=(8.8, 7.7),
            arrowprops=dict(arrowstyle='->', color='#374151', lw=1.8))
box2 = FancyBboxPatch((7.7, 6.5), 2.1, 0.65,
    boxstyle='round,pad=0.05,rounding_size=0.15',
    facecolor='#fff7ed', edgecolor='#ea580c', lw=1.8, zorder=3)
ax.add_patch(box2)
ax.text(8.75, 6.825, 'Return to\nLogin Page', ha='center', va='center',
        fontsize=7.5, fontweight='bold', color='#7c2d12',
        multialignment='center', zorder=4)
ax.text(6.8, 7.82, 'No', fontsize=8.5, color='#374151', fontweight='bold')
yes_no(ax, 5.18, 7.7, is_yes=True)

# MFA not enabled → skip to session
ax.plot([7.2, 9.0, 9.0], [5.1, 5.1, 0.7], color='#059669', lw=1.8, linestyle='--')
ax.annotate('', xy=(6.5, 0.7),
            xytext=(9.0, 0.7),
            arrowprops=dict(arrowstyle='->', color='#059669', lw=1.8))
ax.text(9.15, 2.9, 'No MFA\n(skip TOTP)', ha='left', fontsize=7.5,
        color='#059669', style='italic')
ax.text(6.8, 5.22, 'No', fontsize=8.5, color='#374151', fontweight='bold')
yes_no(ax, 5.18, 5.1, is_yes=True)

# TOTP invalid → deny
ax.plot([7.2, 8.2], [2.4, 2.4], color='#374151', lw=1.5)
ax.annotate('', xy=(8.2, 1.8),
            xytext=(8.2, 2.4),
            arrowprops=dict(arrowstyle='->', color='#dc2626', lw=1.8))
box3 = FancyBboxPatch((7.5, 1.2), 2.2, 0.65,
    boxstyle='round,pad=0.05,rounding_size=0.15',
    facecolor='#fee2e2', edgecolor='#dc2626', lw=1.8, zorder=3)
ax.add_patch(box3)
ax.text(8.6, 1.525, 'DENY\nInvalid TOTP code', ha='center', va='center',
        fontsize=7.5, fontweight='bold', color='#7f1d1d',
        multialignment='center', zorder=4)
ax.text(6.8, 2.52, 'No', fontsize=8.5, color='#dc2626', fontweight='bold')
yes_no(ax, 5.18, 2.4, is_yes=True)

plt.tight_layout()
plt.savefig(r'diagrams/fig5_auth_flow.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('Done')
