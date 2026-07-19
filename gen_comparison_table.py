import os
os.makedirs('diagrams', exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# ── Data ─────────────────────────────────────────────────────────────────────
SYSTEMS = [
    'Google\nDrive',
    'Dropbox\nBusiness',
    'Box\nEnterprise',
    'Nextcloud\n(Self-hosted)',
    'Tresorit\n(E2EE)',
    'FileVault\n(Proposed)',
]

FEATURES = [
    ('Encryption at Rest',            ['✓', '✓', '✓', '✓', '✓', '✓']),
    ('Encryption in Transit (TLS)',   ['✓', '✓', '✓', '✓', '✓', '✓']),
    ('Per-File Key Derivation',       ['✗', '✗', '✗', '◑', '✓', '✓']),
    ('File Integrity Monitoring',     ['✗', '✗', '◑', '◑', '✗', '✓']),
    ('Mandatory Access Control',      ['✗', '✗', '◑', '✗', '✗', '✓']),
    ('Multi-Factor Authentication',   ['✓', '✓', '✓', '✓', '✓', '✓']),
    ('Full Audit Trail / Access Log', ['◑', '◑', '✓', '✓', '✓', '✓']),
    ('Real-Time Security Alerts',     ['✗', '✗', '✓', '◑', '◑', '✓']),
    ('Action Approval Workflow',      ['✗', '✗', '◑', '◑', '✗', '✓']),
    ('Role-Based Access Control',     ['◑', '◑', '✓', '✓', '◑', '✓']),
    ('Self-Hosted / Open Source',     ['✗', '✗', '✗', '✓', '✗', '✓']),
    ('PDF Security Reports',          ['✗', '◑', '✓', '◑', '◑', '✓']),
    ('Tamper Detection & Recovery',   ['✗', '✗', '✗', '✗', '✗', '✓']),
]

# ── Layout constants ─────────────────────────────────────────────────────────
N_FEAT  = len(FEATURES)
N_SYS   = len(SYSTEMS)
ROW_H   = 0.52
FEAT_W  = 3.6     # width of feature label column
COL_W   = 1.9     # width of each system column
PAD_L   = 0.25
PAD_R   = 0.25
FIG_W   = PAD_L + FEAT_W + N_SYS * COL_W + PAD_R
HDR_H   = 0.90    # system header row height
TITLE_H = 0.70
FIG_H   = TITLE_H + HDR_H + N_FEAT * ROW_H + 0.55

fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
ax.set_xlim(0, FIG_W)
ax.set_ylim(0, FIG_H)
ax.axis('off')
fig.patch.set_facecolor('white')

# ── Title ────────────────────────────────────────────────────────────────────
title_y = FIG_H - TITLE_H / 2
ax.text(FIG_W / 2, title_y,
        'Table 1: Comparison of Existing Secure File Storage and Monitoring Systems',
        ha='center', va='center', fontsize=12.5, fontweight='bold', color='#1a2e4a',
        bbox=dict(boxstyle='round,pad=0.45', fc='#bfdbfe', ec='#2563eb', lw=2.0))

# ── Helper: rounded cell ──────────────────────────────────────────────────────
def cell(x, y, w, h, fc, ec='#cbd5e1', lw=0.8, radius=0.06, zorder=2):
    p = FancyBboxPatch((x, y), w, h,
        boxstyle=f'round,pad=0.02,rounding_size={radius}',
        facecolor=fc, edgecolor=ec, lw=lw, zorder=zorder)
    ax.add_patch(p)

# ── Coordinates ──────────────────────────────────────────────────────────────
table_top = FIG_H - TITLE_H - 0.1          # top of header row
hdr_y     = table_top - HDR_H              # bottom of header row
grid_top  = hdr_y                          # top of data grid

# ── System header row ─────────────────────────────────────────────────────────
# Feature column header
cell(PAD_L, hdr_y, FEAT_W, HDR_H, '#1e293b', '#0f172a', lw=1.5, radius=0.1, zorder=3)
ax.text(PAD_L + FEAT_W / 2, hdr_y + HDR_H / 2, 'Security Feature',
        ha='center', va='center', fontsize=10, fontweight='bold', color='white', zorder=4)

SYS_COLORS = [
    '#0369a1',  # Google Drive — blue
    '#0369a1',  # Dropbox
    '#0369a1',  # Box
    '#065f46',  # Nextcloud — green
    '#0369a1',  # Tresorit
    '#7c2d12',  # FileVault — highlighted
]
SYS_FC = [
    '#e0f2fe',
    '#e0f2fe',
    '#e0f2fe',
    '#d1fae5',
    '#e0f2fe',
    '#fff7ed',
]

for s, sys_name in enumerate(SYSTEMS):
    sx = PAD_L + FEAT_W + s * COL_W
    is_fv = (s == N_SYS - 1)
    ec = '#7c2d12' if is_fv else '#0369a1'
    hc = '#7c2d12' if is_fv else '#0369a1'
    cell(sx, hdr_y, COL_W, HDR_H, hc, hc, lw=1.8, radius=0.1, zorder=3)
    ax.text(sx + COL_W / 2, hdr_y + HDR_H / 2, sys_name,
            ha='center', va='center', fontsize=8.5, fontweight='bold',
            color='white', multialignment='center', zorder=4)

# ── Data rows ─────────────────────────────────────────────────────────────────
MARK_STYLE = {
    '✓': ('#14532d', '#dcfce7', '✓'),  # green
    '◑': ('#78350f', '#fef3c7', '◑'),  # amber
    '✗': ('#7f1d1d', '#fee2e2', '✗'),  # red
}

for r, (feat_name, values) in enumerate(FEATURES):
    row_y = grid_top - (r + 1) * ROW_H
    row_bg = '#f8fafc' if r % 2 == 0 else '#f1f5f9'

    # Feature label cell
    cell(PAD_L, row_y, FEAT_W, ROW_H, row_bg, '#cbd5e1', lw=0.7, zorder=2)
    ax.text(PAD_L + 0.18, row_y + ROW_H / 2, feat_name,
            ha='left', va='center', fontsize=8.8, color='#1e293b',
            fontweight='bold' if r % 2 == 0 else 'normal', zorder=3)

    for s, mark in enumerate(values):
        sx = PAD_L + FEAT_W + s * COL_W
        is_fv = (s == N_SYS - 1)
        cell_bg = '#fff7ed' if is_fv else row_bg
        ec = '#ea580c' if is_fv else '#cbd5e1'
        lw = 1.0 if is_fv else 0.7
        cell(sx, row_y, COL_W, ROW_H, cell_bg, ec, lw=lw, zorder=2)

        tc, mc, glyph = MARK_STYLE[mark]
        ax.text(sx + COL_W / 2, row_y + ROW_H / 2, glyph,
                ha='center', va='center', fontsize=13,
                color=tc, fontweight='bold', zorder=3)

# ── Outer border ──────────────────────────────────────────────────────────────
total_w  = FEAT_W + N_SYS * COL_W
total_h  = HDR_H + N_FEAT * ROW_H
border_y = grid_top - N_FEAT * ROW_H
cell(PAD_L, border_y, total_w, total_h + HDR_H,
     'none', '#475569', lw=2.0, radius=0.15, zorder=5)
# 'none' won't work for facecolor — use transparent
from matplotlib.patches import FancyBboxPatch as FBP
border = FBP((PAD_L, border_y), total_w, total_h + HDR_H,
    boxstyle='round,pad=0.02,rounding_size=0.15',
    facecolor='none', edgecolor='#475569', lw=2.0, zorder=5)
ax.add_patch(border)

# ── Legend ───────────────────────────────────────────────────────────────────
legend_y = border_y - 0.42
items = [
    ('✓', '#14532d', '#dcfce7', 'Fully Supported'),
    ('◑', '#78350f', '#fef3c7', 'Partially Supported / Plugin Required'),
    ('✗', '#7f1d1d', '#fee2e2', 'Not Supported'),
]
lx = PAD_L
for glyph, tc, fc, label in items:
    lg = FBP((lx, legend_y), 0.32, 0.30,
        boxstyle='round,pad=0.03,rounding_size=0.07',
        facecolor=fc, edgecolor=tc, lw=1.2, zorder=3)
    ax.add_patch(lg)
    ax.text(lx + 0.16, legend_y + 0.15, glyph,
            ha='center', va='center', fontsize=11, color=tc, fontweight='bold', zorder=4)
    ax.text(lx + 0.42, legend_y + 0.15, label,
            ha='left', va='center', fontsize=8.5, color='#374151', zorder=4)
    lx += 3.2

# FileVault highlight note
ax.text(PAD_L + FEAT_W + (N_SYS - 0.5) * COL_W, legend_y + 0.15,
        '← Proposed System',
        ha='center', va='center', fontsize=8, color='#7c2d12',
        fontweight='bold', style='italic', zorder=4)

plt.tight_layout(pad=0.1)
plt.savefig(r'diagrams/table1_comparison.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('Done — diagrams/table1_comparison.png')
