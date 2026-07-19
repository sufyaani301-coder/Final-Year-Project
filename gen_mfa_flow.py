import os
os.makedirs('diagrams', exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(12, 16))
ax.set_xlim(0, 12); ax.set_ylim(0, 16)
ax.axis('off')
fig.patch.set_facecolor('white')

ax.text(6.0, 15.55, 'Figure 6: MFA Setup and Verification Flow', ha='center', va='center',
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

def arr(ax, x1, y1, x2, y2, color='#374151'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8))

def label(ax, x, y, text, color='#374151'):
    ax.text(x, y, text, ha='center', fontsize=8.5,
            color=color, fontweight='bold')

# ─── DIVIDER LINE between Setup (left) and Verification (right) ──────────────
ax.plot([6.0, 6.0], [0.3, 15.2], color='#cbd5e1', lw=1.5, linestyle='--')
ax.text(3.0, 15.2, 'PART A — MFA SETUP', ha='center', fontsize=10,
        fontweight='bold', color='#0369a1',
        bbox=dict(boxstyle='round,pad=0.3', fc='#e0f2fe', ec='#0284c7', lw=1.5))
ax.text(9.0, 15.2, 'PART B — MFA VERIFICATION', ha='center', fontsize=10,
        fontweight='bold', color='#7c3aed',
        bbox=dict(boxstyle='round,pad=0.3', fc='#ede9fe', ec='#7c3aed', lw=1.5))

# ════════════════════════════════════════════════════════════
# PART A — MFA SETUP (left side)
# ════════════════════════════════════════════════════════════

flowbox(ax, 1.0, 13.8, 4.0, 0.8, 'User Navigates to\nProfile > MFA Setup',
        shape='oval', fc='#1e40af', ec='#1e40af', tc='white')

flowbox(ax, 1.0, 12.5, 4.0, 0.9,
        'System Generates\nTOTP Secret (pyotp)', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 1.0, 11.2, 4.0, 0.9,
        'Display QR Code\n(Google Authenticator URI)', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 1.0, 9.9, 4.0, 0.9,
        'User Scans QR Code\nwith Authenticator App', fc='#f0fdf4', ec='#059669')

flowbox(ax, 1.0, 8.6, 4.0, 0.9,
        'User Enters\nVerification TOTP Code', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 0.8, 7.0, 4.4, 1.2,
        'TOTP Code\nValid?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

flowbox(ax, 1.0, 5.7, 4.0, 0.9,
        'Save TOTP Secret\nto User Record', fc='#d1fae5', ec='#059669')

flowbox(ax, 1.0, 4.4, 4.0, 0.9,
        'Set mfa_enabled = True\nLog Activity Event', fc='#d1fae5', ec='#059669')

flowbox(ax, 1.0, 3.1, 4.0, 0.9,
        'Show Success Message\n"MFA is now active"', fc='#d1fae5', ec='#059669')

flowbox(ax, 1.5, 1.8, 3.0, 0.8, 'MFA Setup Complete',
        shape='oval', fc='#15803d', ec='#15803d', tc='white')

# Setup arrows
arr(ax, 3.0, 13.8, 3.0, 13.4)
arr(ax, 3.0, 12.5, 3.0, 12.1)
arr(ax, 3.0, 11.2, 3.0, 10.8)
arr(ax, 3.0, 9.9,  3.0, 9.5)
arr(ax, 3.0, 8.6,  3.0, 8.2)
arr(ax, 3.0, 7.0,  3.0, 6.6)
arr(ax, 3.0, 5.7,  3.0, 5.3)
arr(ax, 3.0, 4.4,  3.0, 4.0)
arr(ax, 3.0, 3.1,  3.0, 2.6)

# Invalid TOTP → retry
ax.plot([5.2, 5.6], [7.6, 7.6], color='#374151', lw=1.5)
ax.plot([5.6, 5.6], [7.6, 9.05], color='#374151', lw=1.5)
arr(ax, 5.6, 9.05, 5.0, 9.05, color='#dc2626')
ax.text(5.7, 8.3, 'No\n(retry)', ha='left', fontsize=8, color='#dc2626', fontweight='bold')
label(ax, 3.18, 7.05, 'Yes', '#059669')

# ════════════════════════════════════════════════════════════
# PART B — MFA VERIFICATION (right side, during login)
# ════════════════════════════════════════════════════════════

flowbox(ax, 6.8, 13.8, 4.2, 0.8, 'User Submits\nCorrect Password at Login',
        shape='oval', fc='#5b21b6', ec='#5b21b6', tc='white')

flowbox(ax, 6.5, 12.2, 4.4, 1.2,
        'mfa_enabled\nfor this user?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# MFA not enabled → skip
ax.plot([6.5, 5.8], [12.8, 12.8], color='#374151', lw=1.5)
ax.annotate('', xy=(5.8, 10.0),
            xytext=(5.8, 12.8),
            arrowprops=dict(arrowstyle='->', color='#059669', lw=1.8))
flowbox(ax, 5.3, 9.3, 2.0, 0.7, 'Skip MFA\nStep',
        fc='#d1fae5', ec='#059669', fs=8)
ax.text(5.5, 12.95, 'No', fontsize=8.5, color='#374151', fontweight='bold')

flowbox(ax, 6.8, 10.9, 4.2, 0.9,
        'Redirect to\nMFA Verify Page (/auth/mfa-verify)', fc='#ede9fe', ec='#7c3aed')

flowbox(ax, 6.8, 9.6, 4.2, 0.9,
        'User Enters\n6-Digit TOTP Code', fc='#e0f2fe', ec='#0284c7')

flowbox(ax, 6.6, 8.0, 4.4, 1.2,
        'TOTP Valid?\n(30-sec window)',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

flowbox(ax, 6.8, 6.7, 4.2, 0.9,
        'Increment Failed\nMFA Attempt Counter', fc='#fff7ed', ec='#ea580c')

flowbox(ax, 6.6, 5.2, 4.4, 1.2,
        'Attempts\n>= 5?',
        shape='diamond', fc='#fef9c3', ec='#ca8a04')

# Lock account
flowbox(ax, 6.8, 3.9, 4.2, 0.9,
        'Lock Account\n& Notify Admin', fc='#fee2e2', ec='#dc2626', tc='#7f1d1d')

flowbox(ax, 6.8, 2.7, 4.2, 0.9,
        'Flask-Login: login_user()\nCreate Secure Session', fc='#d1fae5', ec='#059669')

flowbox(ax, 7.2, 1.4, 3.4, 0.8, 'Redirect to Dashboard',
        shape='oval', fc='#15803d', ec='#15803d', tc='white')

# Verification arrows
arr(ax, 8.9, 13.8, 8.9, 13.4)
arr(ax, 8.9, 12.2, 8.9, 11.8)
arr(ax, 8.9, 10.9, 8.9, 10.5)
arr(ax, 8.9, 9.6,  8.9, 9.2)
arr(ax, 8.9, 8.0,  8.9, 7.6)
arr(ax, 8.9, 6.7,  8.9, 6.4)
arr(ax, 8.9, 5.2,  8.9, 4.8)
arr(ax, 8.9, 3.9,  8.9, 3.6)   # lock → (dead end shown)
arr(ax, 8.9, 2.7,  8.9, 2.2)

# MFA enabled → prompt
label(ax, 9.1, 12.3, 'Yes', '#059669')

# TOTP invalid → increment
ax.plot([11.0, 11.4], [8.6, 8.6], color='#374151', lw=1.5)
ax.plot([11.4, 11.4], [8.6, 7.15], color='#374151', lw=1.5)
arr(ax, 11.4, 7.15, 11.0, 7.15, color='#dc2626')
ax.text(11.5, 7.9, 'No', ha='left', fontsize=8.5, color='#dc2626', fontweight='bold')
label(ax, 9.1, 8.65, 'Yes', '#059669')

# Attempts < 5 → retry TOTP
ax.plot([6.6, 6.1], [5.8, 5.8], color='#374151', lw=1.5)
ax.plot([6.1, 6.1], [5.8, 10.05], color='#374151', lw=1.5)
arr(ax, 6.1, 10.05, 6.8, 10.05, color='#374151')
ax.text(6.15, 7.9, 'No\n(retry)', ha='left', fontsize=8, color='#374151', fontweight='bold')
label(ax, 9.1, 5.85, 'Yes', '#dc2626')

# Skip MFA → session
arr(ax, 6.3, 9.65, 6.8, 3.15, color='#059669')

# Session → dashboard
arr(ax, 8.9, 2.7, 8.9, 2.2)

plt.tight_layout()
plt.savefig(r'diagrams/fig6_mfa_flow.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('Done')
