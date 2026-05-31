/* ── FileVault — Global JS (2026 redesign) ── */

// ── Theme: apply before paint (also in base.html <head> for zero-flash) ──
(function () {
  try {
    var t = localStorage.getItem('fv-theme') || 'light';
    document.documentElement.setAttribute('data-theme', t);
  } catch (e) {}
})();

document.addEventListener('DOMContentLoaded', () => {

  // ── Auto-dismiss flash toasts ──────────────────────────────────────────
  document.querySelectorAll('.toast').forEach(el => {
    const t = bootstrap.Toast.getOrCreateInstance(el, { delay: 4500 });
    t.show();
    setTimeout(() => t.hide(), 5000);
  });

  // ── Dark-mode toggle ───────────────────────────────────────────────────
  function syncThemeIcons() {
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    document.querySelectorAll('.theme-toggle').forEach(btn => {
      const icon = btn.querySelector('i');
      if (icon) icon.className = dark ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    });
  }

  syncThemeIcons(); // set icon immediately on load

  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('fv-theme', next); } catch (e) {}
      syncThemeIcons();
    });
  });

  // ── Sidebar toggle + overlay ───────────────────────────────────────────
  const sidebar        = document.getElementById('sidebar');
  const sidebarToggle  = document.getElementById('sidebarToggle');
  const sidebarOverlay = document.querySelector('.sidebar-overlay');

  function openSidebar() {
    sidebar?.classList.add('open');
    sidebarOverlay?.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
  function closeSidebar() {
    sidebar?.classList.remove('open');
    sidebarOverlay?.classList.remove('active');
    document.body.style.overflow = '';
  }

  sidebarToggle?.addEventListener('click', e => {
    e.stopPropagation();
    sidebar?.classList.contains('open') ? closeSidebar() : openSidebar();
  });

  sidebarOverlay?.addEventListener('click', closeSidebar);

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSidebar();
  });

  // ── Active nav link highlight (in case template misses it) ────────────
  const currentPath = window.location.pathname;
  document.querySelectorAll('.sidebar-link').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });

});

// ── Global programmatic toast ──────────────────────────────────────────────
function showToast(message, type = 'success') {
  const icons = {
    success: 'bi-check-circle-fill',
    danger:  'bi-exclamation-triangle-fill',
    warning: 'bi-exclamation-circle-fill',
    info:    'bi-info-circle-fill',
  };
  const container = document.querySelector('.toast-container') || (() => {
    const c = document.createElement('div');
    c.className = 'toast-container position-fixed top-0 end-0 p-3';
    c.style.zIndex = 9999;
    document.body.appendChild(c);
    return c;
  })();

  const el = document.createElement('div');
  el.className = `toast align-items-center text-bg-${type} border-0 show mb-2`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `
    <div class="d-flex">
      <div class="toast-body fw-semibold d-flex align-items-center gap-2">
        <i class="bi ${icons[type] || icons.info}"></i>${message}
      </div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
    </div>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transition = 'opacity .3s';
    setTimeout(() => el.remove(), 320);
  }, 3500);
}

// ── AJAX delete (file cards) ───────────────────────────────────────────────
async function ajaxDelete(url, cardEl) {
  if (!confirm('Delete this file? This cannot be undone.')) return;
  cardEl.classList.add('deleting');
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrfToken,
      },
    });
    const data = await r.json();
    if (data.success) {
      setTimeout(() => cardEl.remove(), 350);
      showToast('File deleted.', 'success');
    } else {
      cardEl.classList.remove('deleting');
      showToast(data.error || 'Delete failed.', 'danger');
    }
  } catch {
    cardEl.classList.remove('deleting');
    showToast('Network error. Please try again.', 'danger');
  }
}
