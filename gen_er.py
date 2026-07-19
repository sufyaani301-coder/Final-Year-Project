import os
os.makedirs('diagrams', exist_ok=True)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(18, 13))
ax.set_xlim(0, 18); ax.set_ylim(0, 13)
ax.axis('off')
fig.patch.set_facecolor('white')

ax.text(9.0, 12.65, 'Figure 4: Entity-Relationship Diagram -- FileVault Database',
        ha='center', fontsize=13, fontweight='bold', color='#1a2e4a',
        bbox=dict(boxstyle='round,pad=0.4', fc='#bfdbfe', ec='#2563eb', lw=1.8))

def entity(ax, x, y, w, title, attrs, hc, bc, ec):
    hdr = FancyBboxPatch((x, y + len(attrs)*0.38), w, 0.52,
        boxstyle='round,pad=0.05,rounding_size=0.1',
        facecolor=hc, edgecolor=ec, lw=2, zorder=3)
    ax.add_patch(hdr)
    ax.text(x + w/2, y + len(attrs)*0.38 + 0.26, title, ha='center', va='center',
            fontsize=9, fontweight='bold', color='white', zorder=4)
    for i, (pk, attr) in enumerate(reversed(attrs)):
        row = FancyBboxPatch((x, y + i*0.38), w, 0.38,
            boxstyle='square,pad=0',
            facecolor='#fffbeb' if pk == 'PK' else bc, edgecolor=ec, lw=1, zorder=3)
        ax.add_patch(row)
        prefix = 'PK  ' if pk == 'PK' else ('FK  ' if pk == 'FK' else '      ')
        color  = '#92400e' if pk == 'PK' else ('#1d4ed8' if pk == 'FK' else '#111827')
        ax.text(x + 0.12, y + i*0.38 + 0.19, prefix + attr, va='center',
                fontsize=7.5, color=color,
                fontweight='bold' if pk else 'normal', zorder=4)

# USER
entity(ax, 0.2, 7.2, 3.2, 'USER',
    [('PK','id'), ('','username'), ('','email'), ('','password_hash'),
     ('','is_admin'), ('','clearance_level'), ('','mfa_secret'),
     ('','email_alerts_enabled'), ('','created_at')],
    '#1e40af', '#eff6ff', '#2563eb')

# MONITORED FILE
entity(ax, 4.2, 7.0, 3.4, 'MONITORED_FILE',
    [('PK','id'), ('','uuid'), ('','original_name'), ('','stored_name'),
     ('','size'), ('','classification'), ('','mime_type'),
     ('FK','uploader_id'), ('','uploaded_at'), ('','monitoring_enabled')],
    '#065f46', '#f0fdf4', '#059669')

# FILE BASELINE
entity(ax, 8.6, 8.2, 3.2, 'FILE_BASELINE',
    [('PK','id'), ('FK','file_id'), ('','hash_sha256'),
     ('','captured_at'), ('FK','captured_by'), ('','capture_reason')],
    '#0369a1', '#f0f9ff', '#0284c7')

# FIM ALERT
entity(ax, 12.4, 7.2, 3.2, 'FIM_ALERT',
    [('PK','id'), ('FK','file_id'), ('','alert_type'), ('','severity'),
     ('','status'), ('','detected_at'), ('','expected_hash'),
     ('','actual_hash'), ('FK','acknowledged_by'), ('','resolved_at')],
    '#9f1239', '#fff1f2', '#e11d48')

# ACTION REQUEST
entity(ax, 4.2, 1.8, 3.4, 'ACTION_REQUEST',
    [('PK','id'), ('FK','requester_id'), ('FK','file_id'),
     ('','action'), ('','justification'), ('','status'),
     ('','exec_token'), ('','expires_at'), ('FK','approved_by'),
     ('','created_at')],
    '#7c2d12', '#fff7ed', '#ea580c')

# FILE ACCESS LOG
entity(ax, 8.6, 2.5, 3.2, 'FILE_ACCESS_LOG',
    [('PK','id'), ('FK','file_id'), ('FK','user_id'),
     ('','action'), ('','outcome'), ('','timestamp'), ('','details')],
    '#4a044e', '#fdf4ff', '#a21caf')

# ACTIVITY LOG
entity(ax, 0.2, 2.5, 3.2, 'ACTIVITY_LOG',
    [('PK','id'), ('FK','user_id'), ('','action'),
     ('','timestamp'), ('','ip_address'), ('','details')],
    '#374151', '#f9fafb', '#6b7280')

# SHARE TOKEN
entity(ax, 12.4, 3.0, 3.2, 'SHARE_TOKEN',
    [('PK','id'), ('FK','file_id'), ('FK','created_by'),
     ('','token'), ('','expires_at'), ('','max_uses'), ('','use_count')],
    '#164e63', '#ecfeff', '#0891b2')

def rel_line(ax, x1, y1, x2, y2, label=''):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color='#475569', lw=1.6))
    mx, my = (x1+x2)/2, (y1+y2)/2
    if label:
        ax.text(mx, my+0.13, label, ha='center', fontsize=7,
                color='#475569', style='italic',
                bbox=dict(fc='white', ec='none', pad=1))

# User uploads File
rel_line(ax, 3.4, 10.2, 4.2, 10.2, 'uploads (1..N)')
# File has Baseline
rel_line(ax, 7.6, 10.5, 8.6, 10.5, 'has (1..N)')
# File raises Alert
rel_line(ax, 11.6, 10.2, 12.4, 10.2, 'raises (1..N)')
# User submits ActionRequest
rel_line(ax, 1.8, 7.2, 5.9, 5.7, 'submits (1..N)')
# File targeted by ActionRequest
rel_line(ax, 5.9, 6.85, 5.9, 5.6, 'targets (1..N)')
# File logged in FileAccessLog
rel_line(ax, 10.2, 6.85, 10.2, 5.5, 'logged (1..N)')
# User generates ActivityLog
rel_line(ax, 1.8, 7.2, 1.8, 5.4, 'generates (1..N)')
# File shared via ShareToken
rel_line(ax, 14.0, 6.85, 14.0, 4.75, 'shared via (1..N)')

# Legend
legend = [('#fffbeb', '#92400e', 'PK = Primary Key'),
          ('#eff6ff', '#1d4ed8', 'FK = Foreign Key')]
for i, (fc, tc, lbl) in enumerate(legend):
    rect = FancyBboxPatch((0.2+i*3.5, 0.1), 3.0, 0.45,
        boxstyle='round,pad=0.05', facecolor=fc, edgecolor='#94a3b8', lw=1)
    ax.add_patch(rect)
    ax.text(0.2+i*3.5+1.5, 0.33, lbl, ha='center', va='center',
            fontsize=8, color=tc, fontweight='bold')

plt.tight_layout()
plt.savefig(r'diagrams/fig4_er_diagram.png', dpi=180,
            bbox_inches='tight', facecolor='white')
plt.close()
print('Done')
