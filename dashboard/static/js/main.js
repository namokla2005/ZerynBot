/* main.js — General dashboard utilities */

// ─── Auto-dismiss flash messages ──────────────────────────────────────────────
document.querySelectorAll('.alert').forEach(alert => {
  setTimeout(() => {
    alert.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    alert.style.opacity = '0';
    alert.style.transform = 'translateY(-8px)';
    setTimeout(() => alert.remove(), 400);
  }, 4000);
});

// ─── Module toggle (instant AJAX) ─────────────────────────────────────────────
document.querySelectorAll('.module-toggle').forEach(toggle => {
  toggle.addEventListener('change', async function () {
    const guildId = this.dataset.guild;
    const module  = this.dataset.module;
    const enabled = this.checked;
    const card    = this.closest('.module-card');

    try {
      const res = await fetch(`/api/guild/${guildId}/modules/${module}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error('Failed');

      // Update card border style
      card.classList.toggle('mod-on',  enabled);
      card.classList.toggle('mod-off', !enabled);

      // Update sidebar status dot if exists
      const dot = document.querySelector(`.nav-dot-${module}`);
      if (dot) {
        dot.classList.toggle('on',  enabled);
        dot.classList.toggle('off', !enabled);
      }

      showToast(enabled ? `✅ ${module} đã bật` : `⚫ ${module} đã tắt`, enabled ? 'success' : 'info');
    } catch (e) {
      this.checked = !enabled; // Revert on error
      showToast('❌ Lỗi khi cập nhật module', 'error');
    }
  });
});

// ─── Color swatch sync ────────────────────────────────────────────────────────
document.querySelectorAll('input[type="color"]').forEach(picker => {
  const swatchId = picker.dataset.swatch;
  const display  = picker.dataset.display;
  const swatch   = swatchId ? document.getElementById(swatchId) : picker.parentElement;
  const textEl   = display  ? document.getElementById(display)  : null;

  const update = () => {
    if (swatch) swatch.style.backgroundColor = picker.value;
    if (textEl) textEl.value = picker.value;
  };
  picker.addEventListener('input', update);
  update();
});
document.querySelectorAll('.color-text-input').forEach(input => {
  const pickerId = input.dataset.picker;
  const picker   = document.getElementById(pickerId);
  input.addEventListener('input', () => {
    if (/^#[0-9a-fA-F]{6}$/.test(input.value) && picker) {
      picker.value = input.value;
      const swatch = picker.parentElement;
      if (swatch) swatch.style.backgroundColor = input.value;
    }
  });
});

// ─── Tab system ───────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(target)?.classList.add('active');
  });
});

// ─── Toast notification ───────────────────────────────────────────────────────
function showToast(message, type = 'success') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    Object.assign(container.style, {
      position: 'fixed', bottom: '24px', right: '24px',
      display: 'flex', flexDirection: 'column', gap: '8px', zIndex: '9999',
    });
    document.body.appendChild(container);
  }

  const colors = {
    success: { bg: 'rgba(35,165,90,0.95)',  border: 'rgba(35,165,90,0.4)' },
    error:   { bg: 'rgba(242,63,67,0.95)',  border: 'rgba(242,63,67,0.4)' },
    info:    { bg: 'rgba(88,101,242,0.95)', border: 'rgba(88,101,242,0.4)' },
  };
  const c = colors[type] || colors.info;

  const toast = document.createElement('div');
  toast.textContent = message;
  Object.assign(toast.style, {
    background: c.bg, border: `1px solid ${c.border}`,
    color: 'white', padding: '10px 16px', borderRadius: '8px',
    fontSize: '0.85rem', fontWeight: '600',
    backdropFilter: 'blur(8px)', boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
    opacity: '0', transform: 'translateX(20px)', transition: 'all 0.25s ease',
    maxWidth: '300px',
  });
  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(0)';
  });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(() => toast.remove(), 250);
  }, 3000);
}

// ─── Confirm delete ───────────────────────────────────────────────────────────
document.querySelectorAll('[data-confirm]').forEach(el => {
  el.addEventListener('click', e => {
    const msg = el.dataset.confirm || 'Bạn có chắc không?';
    if (!confirm(msg)) e.preventDefault();
  });
});

