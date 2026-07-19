import os
os.makedirs('diagrams', exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(18, 11))
ax.set_xlim(0, 18)
ax.set_ylim(0, 11)
ax.axis('off')
fig.patch.set_facecolor('white')

# ── Title ────────────────────────────────────────────────────────────────────
ax.text(9.0, 10.6, 'Figure 2: Agile Development Sprint Plan — FileVault (8 Weeks)',
        ha='center', va='center', fontsize=14, fontweight='bold', color='#1a2e4a',
        bbox=dict(boxstyle='round,pad=0.45', fc='#bfdbfe', ec='#2563eb', lw=2.0))

# ── Configuration ────────────────────────────────────────────────────────────
LEFT        = 1.4    # left edge of week grid
RIGHT       = 17.2   # right edge of week grid
GRID_W      = RIGHT - LEFT
WEEK_W      = GRID_W / 8
TOP_ROW     = 9.65   # y of week header row top
HEADER_H    = 0.55
ROW_GAP     = 0.18   # gap between sprint rows
BAR_H       = 1.55   # height of each sprint bar

SPRINT_COLORS = [
    ('#1e40af', '#dbeafe', '#93c5fd'),  # Sprint 1 — blue
    ('#065f46', '#d1fae5', '#6ee7b7'),  # Sprint 2 — green
    ('#7c2d12', '#ffedd5', '#fdba74'),  # Sprint 3 — orange
    ('#6b21a8', '#ede9fe', '#c4b5fd'),  # Sprint 4 — purple
]

SPRINTS = [
    {
        'label': 'Sprint 1',
        'weeks': '  Weeks 1 – 2',
        'title': 'Foundation & Authentication',
        'deliverables': [
            'Project structure & database models',
            'User registration + email verification',
            'Secure login / logout (Flask-Login)',
            'Password hashing (PBKDF2-SHA256)',
            'Password reset via Resend API',
            'Activity logging for all auth events',
        ],
    },
    {
        'label': 'Sprint 2',
        'weeks': '  Weeks 3 – 4',
        'title': 'File Management & Audit Trail',
        'deliverables': [
            'File upload with MIME-type detection',
            'Classification assignment on upload',
            'Secure on-disk storage (random names)',
            'Download, preview, rename, replace, delete',
            'FileAccessLog — complete audit trail',
            'Admin file-management dashboard',
        ],
    },
    {
        'label': 'Sprint 3',
        'weeks': '  Weeks 5 – 6',
        'title': 'Encryption, MAC & MFA',
        'deliverables': [
            'AES encryption at rest (Fernet)',
            'Per-file key derivation (HKDF-SHA256)',
            '5-level Mandatory Access Control model',
            'TOTP multi-factor authentication (pyotp)',
            'Session timeout & security hardening',
            'In-browser code editor (CodeMirror 5)',
        ],
    },
    {
        'label': 'Sprint 4',
        'weeks': '  Weeks 7 – 8',
        'title': 'Monitoring, Alerting & Deployment',
        'deliverables': [
            'File Integrity Monitoring (SHA-256 baseline)',
            'Multi-threaded FIM scheduler (APScheduler)',
            'Alert lifecycle + ActionRequest workflow',
            'Real-time WebSocket notifications & email alerts',
            'Security dashboard, FIM analytics, PDF reports',
            'Railway deployment + GitHub Actions CI/CD',
        ],
    },
]

# ── Week header row ──────────────────────────────────────────────────────────
header_bg = FancyBboxPatch((LEFT - 0.02, TOP_ROW - HEADER_H), GRID_W + 0.04, HEADER_H,
    boxstyle='round,pad=0.04,rounding_size=0.15',
    facecolor='#1e293b', edgecolor='#0f172a', lw=1.5, zorder=3)
ax.add_patch(header_bg)

for w in range(8):
    cx = LEFT + w * WEEK_W + WEEK_W / 2
    ax.text(cx, TOP_ROW - HEADER_H / 2, f'Week {w+1}',
            ha='center', va='center', fontsize=9.5, fontweight='bold',
            color='white', zorder=4)
    if w > 0:
        ax.plot([LEFT + w * WEEK_W, LEFT + w * WEEK_W],
                [TOP_ROW - HEADER_H, 0.3],
                color='#cbd5e1', lw=0.7, linestyle=':', zorder=1)

# Sprint boundary lines (every 2 weeks)
for s in range(1, 4):
    bx = LEFT + s * 2 * WEEK_W
    ax.plot([bx, bx], [TOP_ROW - HEADER_H, 0.3],
            color='#94a3b8', lw=1.2, linestyle='--', zorder=2)

# ── Sprint rows ──────────────────────────────────────────────────────────────
for i, sprint in enumerate(SPRINTS):
    hc, bc, ac = SPRINT_COLORS[i]
    week_start = i * 2
    x0 = LEFT + week_start * WEEK_W
    y0 = TOP_ROW - HEADER_H - (i + 1) * (BAR_H + ROW_GAP) - ROW_GAP * i

    # Main sprint bar
    bar = FancyBboxPatch((x0 + 0.05, y0), WEEK_W * 2 - 0.10, BAR_H,
        boxstyle='round,pad=0.06,rounding_size=0.18',
        facecolor=bc, edgecolor=hc, lw=2.2, zorder=3)
    ax.add_patch(bar)

    # Sprint label pill (left)
    pill = FancyBboxPatch((x0 + 0.1, y0 + BAR_H - 0.38), 0.92, 0.30,
        boxstyle='round,pad=0.04,rounding_size=0.1',
        facecolor=hc, edgecolor=hc, lw=1, zorder=4)
    ax.add_patch(pill)
    ax.text(x0 + 0.56, y0 + BAR_H - 0.23, sprint['label'],
            ha='center', va='center', fontsize=8, fontweight='bold',
            color='white', zorder=5)

    # Sprint title
    ax.text(x0 + 1.15, y0 + BAR_H - 0.23, sprint['title'],
            ha='left', va='center', fontsize=9.5, fontweight='bold',
            color=hc, zorder=5)

    # Week range tag
    ax.text(x0 + WEEK_W * 2 - 0.15, y0 + BAR_H - 0.23, sprint['weeks'],
            ha='right', va='center', fontsize=8, color=hc,
            style='italic', zorder=5)

    # Deliverable bullets
    max_items = len(sprint['deliverables'])
    for j, item in enumerate(sprint['deliverables']):
        dy = y0 + BAR_H - 0.58 - j * ((BAR_H - 0.65) / max_items)
        ax.plot(x0 + 0.22, dy + 0.04, 'o', ms=3.8, color=hc, zorder=5)
        ax.text(x0 + 0.36, dy + 0.04, item,
                ha='left', va='center', fontsize=8, color='#1e293b', zorder=5)

    # Sprint review badge (right edge)
    review_x = x0 + WEEK_W * 2 - 0.08
    badge = mpatches.Ellipse((review_x, y0 + BAR_H / 2), 0.02, BAR_H * 0.55,
        facecolor=hc, edgecolor=hc, lw=1, zorder=4, alpha=0.35)
    ax.add_patch(badge)

    # Sprint review marker
    ax.text(review_x + 0.06, y0 + BAR_H / 2, '▶',
            ha='left', va='center', fontsize=10, color=hc, zorder=5)

# ── Week-band shading (alternating) ─────────────────────────────────────────
for w in range(8):
    if w % 2 == 1:
        shade = FancyBboxPatch((LEFT + w * WEEK_W, 0.25), WEEK_W,
            TOP_ROW - HEADER_H - 0.25,
            boxstyle='square,pad=0',
            facecolor='#f1f5f9', edgecolor='none', lw=0, zorder=0, alpha=0.45)
        ax.add_patch(shade)

# ── Timeline arrow ───────────────────────────────────────────────────────────
ax.annotate('', xy=(RIGHT + 0.25, 0.55), xytext=(LEFT - 0.1, 0.55),
            arrowprops=dict(arrowstyle='->', color='#475569', lw=1.8))
ax.text(9.0, 0.28, 'Development Timeline (8 Weeks)',
        ha='center', fontsize=9, color='#475569', fontweight='bold')

# Sprint review markers legend
ax.text(RIGHT + 0.32, 0.58, '▶ = Sprint Review',
        ha='left', fontsize=8, color='#475569', style='italic', va='center')

# ── Legend pills ─────────────────────────────────────────────────────────────
legend_items = [
    ('#1e40af', '#dbeafe', 'Sprint 1: Authentication'),
    ('#065f46', '#d1fae5', 'Sprint 2: File Management'),
    ('#7c2d12', '#ffedd5', 'Sprint 3: Encryption & MAC'),
    ('#6b21a8', '#ede9fe', 'Sprint 4: Monitoring & Deployment'),
]
lx = LEFT
for hc, bc, lbl in legend_items:
    lpill = FancyBboxPatch((lx, 0.62), 3.6, 0.28,
        boxstyle='round,pad=0.04,rounding_size=0.08',
        facecolor=bc, edgecolor=hc, lw=1.6, zorder=3)
    ax.add_patch(lpill)
    ax.text(lx + 1.8, 0.76, lbl,
            ha='center', va='center', fontsize=8, color=hc, fontweight='bold', zorder=4)
    lx += 3.8

plt.tight_layout()
plt.savefig(r'diagrams/fig2_sprint_plan.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('Done — diagrams/fig2_sprint_plan.png')
