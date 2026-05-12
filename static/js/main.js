/* ── FileVault global JS ── */

// Dark mode
(function () {
  const saved = localStorage.getItem('fv-theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
})();

document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss toasts
  document.querySelectorAll('.toast').forEach(el => {
    const t = bootstrap.Toast.getOrCreateInstance(el, { delay: 4500 });
    t.show();
    setTimeout(() => t.hide(), 5000);
  });

  // Dark mode toggle
  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('fv-theme', next);
      btn.querySelector('i').className = next === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    });
    // Set correct initial icon
    const cur = document.documentElement.getAttribute('data-theme');
    const icon = btn.querySelector('i');
    if (icon) icon.className = cur === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
  });

  // Sidebar toggle + overlay
  const sidebar = document.getElementById('sidebar');
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebarOverlay = document.querySelector('.sidebar-overlay');

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', function (e) {
      e.stopPropagation();
      sidebar.classList.toggle('open');
      if (sidebarOverlay) sidebarOverlay.classList.toggle('active');
    });
  }
  if (sidebarOverlay) {
    sidebarOverlay.addEventListener('click', function () {
      sidebar.classList.remove('open');
      sidebarOverlay.classList.remove('active');
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sidebar) {
      sidebar.classList.remove('open');
      if (sidebarOverlay) sidebarOverlay.classList.remove('active');
    }
  });
});

// AJAX delete helper (used by dashboard)
async function ajaxDelete(url, cardEl) {
  if (!confirm('Delete this file?')) return;
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
    } else {
      cardEl.classList.remove('deleting');
      alert(data.error || 'Delete failed.');
    }
  } catch {
    cardEl.classList.remove('deleting');
    alert('Network error. Please try again.');
  }
}
