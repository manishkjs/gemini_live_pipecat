(function () {
  const STORAGE_KEY = 'sl-left-sidebar-width';
  const MIN_W = 180;
  const MAX_W = 560;
  const DEFAULT_W = 300;
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    const px = parseInt(saved, 10);
    if (!isNaN(px) && px >= MIN_W && px <= MAX_W) {
      document.documentElement.style.setProperty('--sl-left-sidebar-width', px + 'px');
    }
  }
  function applyWidth(px, handle) {
    const clamped = Math.max(MIN_W, Math.min(MAX_W, Math.round(px)));
    document.documentElement.style.setProperty('--sl-left-sidebar-width', clamped + 'px');
    if (handle) handle.setAttribute('aria-valuenow', String(clamped));
    try { localStorage.setItem(STORAGE_KEY, String(clamped)); } catch (_) {}
  }
  function initSidebarResizer() {
    if (!document.documentElement.hasAttribute('data-has-sidebar')) return;
    if (document.querySelector('.sl-sidebar-resizer')) return;
    const handle = document.createElement('div');
    handle.className = 'sl-sidebar-resizer';
    handle.title = 'Drag or use Left/Right arrows to resize sidebar (double-click to reset)';
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', 'vertical');
    handle.setAttribute('aria-label', 'Resize navigation sidebar');
    handle.setAttribute('tabindex', '0');
    handle.setAttribute('aria-valuemin', String(MIN_W));
    handle.setAttribute('aria-valuemax', String(MAX_W));
    const current = parseInt(localStorage.getItem(STORAGE_KEY) || String(DEFAULT_W), 10);
    handle.setAttribute('aria-valuenow', String(isNaN(current) ? DEFAULT_W : current));
    document.body.appendChild(handle);

    let dragging = false;
    handle.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      dragging = true;
      handle.classList.add('is-dragging');
      document.body.classList.add('sl-resizing-sidebar');
      handle.setPointerCapture(e.pointerId);
      e.preventDefault();
    });

    handle.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      applyWidth(e.clientX, handle);
    });

    function stopDrag(e) {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('is-dragging');
      document.body.classList.remove('sl-resizing-sidebar');
      try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
    }
    handle.addEventListener('pointerup', stopDrag);
    handle.addEventListener('pointercancel', stopDrag);

    handle.addEventListener('keydown', function (e) {
      const cur = parseInt(handle.getAttribute('aria-valuenow') || String(DEFAULT_W), 10);
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        applyWidth(cur - 16, handle);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        applyWidth(cur + 16, handle);
      } else if (e.key === 'Home') {
        e.preventDefault();
        applyWidth(MIN_W, handle);
      } else if (e.key === 'End') {
        e.preventDefault();
        applyWidth(MAX_W, handle);
      }
    });

    handle.addEventListener('dblclick', function () {
      document.documentElement.style.removeProperty('--sl-left-sidebar-width');
      handle.setAttribute('aria-valuenow', String(DEFAULT_W));
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebarResizer);
  } else {
    initSidebarResizer();
  }
  document.addEventListener('astro:page-load', initSidebarResizer);
})();
