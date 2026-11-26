/* theme.js — 3-state Iridescent theme controller (light / dark / auto) */
(function () {
  'use strict';

  const KEY = 'zeryn-theme';
  const MODES = ['light', 'dark', 'auto'];
  const FALLBACK = { light: 'Light', dark: 'Dark', auto: 'Auto', tooltip: 'Switch theme (Light / Dark / Auto)' };
  const ICON = { light: '☾', dark: '◐', auto: '☀︎' };
  const NEXT_LABEL = { light: 'dark', dark: 'auto', auto: 'light' };
  const mql = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  let memMode = null;
  const isValid = (m) => m === 'light' || m === 'dark' || m === 'auto';

  function get() {
    if (memMode) return memMode;
    try { const v = window.localStorage.getItem(KEY); return isValid(v) ? v : 'auto'; } catch (e) { return 'auto'; }
  }

  function resolved(mode) {
    const m = isValid(mode) ? mode : get();
    return m === 'auto' ? ((mql && mql.matches) ? 'dark' : 'light') : m;
  }

  function readI18n() {
    const el = document.getElementById('theme-i18n');
    if (!el) return FALLBACK;
    try {
      const d = JSON.parse(el.textContent || '{}');
      if (!d || typeof d !== 'object') return FALLBACK;
      return {
        light: d.light || FALLBACK.light, dark: d.dark || FALLBACK.dark,
        auto: d.auto || FALLBACK.auto, tooltip: d.tooltip || FALLBACK.tooltip,
      };
    } catch (e) { return FALLBACK; }
  }

  function updateButtons(mode, real) {
    const i18n = readI18n();
    const label = i18n[NEXT_LABEL[mode]];
    const tip = i18n.tooltip ? label + ' — ' + i18n.tooltip : label;
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.dataset.mode = mode;
      btn.dataset.resolved = real;
      btn.setAttribute('title', tip);
      btn.setAttribute('aria-label', tip);
      const iconEl = btn.querySelector('.theme-toggle-icon');
      const textEl = btn.querySelector('.theme-toggle-text');
      if (iconEl) iconEl.textContent = ICON[mode];
      if (textEl) textEl.textContent = label;
    });
  }

  function apply(nextMode) {
    const mode = isValid(nextMode) ? nextMode : get();
    const real = resolved(mode);
    document.documentElement.setAttribute('data-theme', real);
    updateButtons(mode, real);
    window.dispatchEvent(new CustomEvent('zeryn:themechange', {
      detail: { mode: mode, resolved: real }, bubbles: false, composed: false,
    }));
    return real;
  }

  function set(nextMode) {
    const mode = isValid(nextMode) ? nextMode : 'auto';
    try { window.localStorage.setItem(KEY, mode); memMode = null; } catch (e) { memMode = mode; }
    apply(mode);
    return mode;
  }

  const cycle = () => set(MODES[(MODES.indexOf(get()) + 1) % MODES.length]);

  document.addEventListener('click', function (e) {
    const btn = e.target && typeof e.target.closest === 'function' ? e.target.closest('[data-theme-toggle]') : null;
    if (btn) { e.preventDefault(); cycle(); }
  });
  if (mql) {
    const onOsChange = function () { if (get() === 'auto') apply('auto'); };
    if (typeof mql.addEventListener === 'function') mql.addEventListener('change', onOsChange);
    else if (typeof mql.addListener === 'function') mql.addListener(onOsChange);
  }
  window.zerynTheme = { get: get, set: set, cycle: cycle, apply: apply, resolved: resolved };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { updateButtons(get(), resolved()); });
  }
  apply();
})();
