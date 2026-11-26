"""
test_dashboard_theme.py — Regression & WCAG checks for Iridescent Dual-Theme (V12).

Covers:
1. Legal Freeze invariant: /tos and /privacy stay isolated on theme_legal.css?v=1.0
   with zero theme switcher/FOUC/dark overrides.
2. Frame & Landing invariants: all 7 non-legal CSS-linked frame templates and
   landing.html load FOUC guard, theme.js?v=18.0, valid #theme-i18n JSON, and
   data-theme-toggle; GET / preserves >= 12 /invite CTAs.
3. i18n & JS behavior: 6 locales hold all theme.* keys (2072 keys/file), and
   Node VM execution of dashboard/static/js/theme.js verifies 3-state cycling
   (light -> dark -> auto), localStorage persistence, matchMedia auto-switching,
   zeryn:themechange event dispatch, and DOM updates without innerHTML.
4. WCAG contrast math (>= 4.5:1): parses :root (Light #f5f4fb) and
   [data-theme="dark"] (Dark #0d0b16) tokens from style.css.
"""
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "dashboard" / "templates"
STYLE_CSS = ROOT / "dashboard" / "static" / "css" / "style.css"
THEME_LEGAL_CSS = ROOT / "dashboard" / "static" / "css" / "theme_legal.css"
THEME_JS = ROOT / "dashboard" / "static" / "js" / "theme.js"
LOCALES_DIR = ROOT / "locales"

# LF-normalized SHA-256 of the frozen V17 stylesheet (bd3ca66:dashboard/static/css/style.css)
FROZEN_LEGAL_LF_SHA256 = "5051ccb850e3fecb40c0a31d42546032f82aa2a27f3aec618c47e61c8e313479"

LEGAL_TEMPLATES = ("tos.html", "privacy.html")
FRAME_TEMPLATES = (
    "base_server.html",
    "home.html",
    "login.html",
    "admin.html",
    "admin_support.html",
    "docs.html",
    "support.html",
)
THEME_KEYS = ("theme.to_light", "theme.to_dark", "theme.auto", "theme.tooltip")


# ─── 1. Legal Freeze Invariant ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", LEGAL_TEMPLATES)
def test_legal_templates_stay_frozen_and_isolated(name):
    html = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    assert "theme_legal.css" in html and "?v=1.0" in html
    assert "style.css" not in html
    assert "theme.js" not in html
    assert "zeryn-theme" not in html
    assert "data-theme-toggle" not in html
    assert 'id="theme-i18n"' not in html


def test_theme_legal_css_matches_frozen_baseline():
    assert THEME_LEGAL_CSS.exists(), "dashboard/static/css/theme_legal.css missing"
    raw = THEME_LEGAL_CSS.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == FROZEN_LEGAL_LF_SHA256
    text = raw.decode("utf-8")
    assert '[data-theme="dark"]' not in text
    assert "theme-toggle-btn" not in text


def test_legal_routes_render_isolated(client, temp_db):
    for path in ("/tos", "/privacy"):
        resp = client.get(path)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "theme_legal.css?v=1.0" in body
        assert "style.css" not in body
        assert "theme.js" not in body
        assert "data-theme-toggle" not in body


# ─── 2. Frame & Landing Invariants ─────────────────────────────────────────────

@pytest.mark.parametrize("name", FRAME_TEMPLATES)
def test_frame_templates_have_iridescent_contract(name):
    html = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    assert re.search(r"style\.css'\)\s*\}\}\?v=(1[89]|[2-9]\d)\.", html), f"{name} missing versioned style.css (>=v18)"
    assert "style.css') }}?v=17.0" not in html, f"{name} still links v=17.0"
    assert "zeryn-theme" in html, f"{name} missing inline FOUC script"
    assert html.index("zeryn-theme") < html.index("style.css"), (
        f"{name} must place inline zeryn-theme FOUC script BEFORE style.css"
    )
    assert re.search(r"js/theme\.js'\)\s*\}\}\?v=(1[89]|[2-9]\d)\.", html), f"{name} missing versioned theme.js (>=v18)"
    assert 'id="theme-i18n"' in html, f"{name} missing #theme-i18n JSON script"
    assert "| tojson" in html or "|tojson" in html, f"{name} must serialize #theme-i18n via tojson"
    assert "data-theme-toggle" in html, f"{name} missing data-theme-toggle button"


def test_child_templates_do_not_link_stale_css():
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        if path.name in LEGAL_TEMPLATES:
            continue
        html = path.read_text(encoding="utf-8")
        assert "style.css') }}?v=17.0" not in html
        assert "style.css?v=17.0" not in html


def test_landing_template_and_route_contract(client, temp_db):
    src = (TEMPLATES_DIR / "landing.html").read_text(encoding="utf-8")
    assert "zeryn-theme" in src
    assert src.index("zeryn-theme") < src.index("<style>"), (
        "landing.html FOUC script must run before <style>"
    )
    assert re.search(r"js/theme\.js'\)\s*\}\}\?v=(1[89]|[2-9]\d)\.", src)
    assert 'id="theme-i18n"' in src
    assert "data-theme-toggle" in src

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert body.count('href="/invite"') >= 12
    assert "data-theme-toggle" in body
    assert re.search(r"theme\.js\?v=(1[89]|[2-9]\d)\.", body)
    m = re.search(r'<script id="theme-i18n" type="application/json">(.*?)</script>', body, re.S)
    assert m is not None, "Rendered / missing #theme-i18n script"
    parsed = json.loads(m.group(1))
    assert set(parsed.keys()) == {"light", "dark", "auto", "tooltip"}
    assert all(isinstance(v, str) and v.strip() for v in parsed.values())


def test_rendered_frame_pages_emit_valid_theme_contract(client, temp_db, monkeypatch):
    flask = pytest.importorskip("flask")
    assert flask is not None
    from conftest import MOCK_GUILD_ID, login
    import config

    def _assert_theme_html(path: str):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        body = resp.get_data(as_text=True)
        assert re.search(r"style\.css\?v=(1[89]|[2-9]\d)\.", body), f"{path} missing versioned style.css"
        assert re.search(r"theme\.js\?v=(1[89]|[2-9]\d)\.", body), f"{path} missing versioned theme.js"
        assert "data-theme-toggle" in body, f"{path} missing data-theme-toggle"
        m = re.search(r'<script id="theme-i18n" type="application/json">(.*?)</script>', body, re.S)
        assert m is not None, f"{path} missing #theme-i18n"
        parsed = json.loads(m.group(1))
        assert set(parsed.keys()) == {"light", "dark", "auto", "tooltip"}

    # /login renders 200 for anonymous sessions (redirects 302 once logged in)
    _assert_theme_html("/login")

    login(client)
    monkeypatch.setattr(config, "BOT_OWNER_ID", "111111111111111111")

    for path in ("/docs", "/dashboard", f"/dashboard/{MOCK_GUILD_ID}", "/support", "/admin", "/admin/support"):
        _assert_theme_html(path)


# ─── 3. i18n Parity & theme.js Behavior ────────────────────────────────────────

def test_theme_i18n_keys_present_and_synced_across_all_locales():
    counts = {}
    for lang in ("vi", "en", "zh", "es", "pt", "fr"):
        data = json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        counts[lang] = len(data)
        for key in THEME_KEYS:
            assert key in data and isinstance(data[key], str) and data[key].strip(), (
                f"{lang}.json missing or empty {key}"
            )
    assert len(set(counts.values())) == 1, f"Locale key count mismatch: {counts}"
    assert counts["vi"] >= 2072


def test_theme_js_source_contract():
    """Pure-Python structural verification of theme.js (runs even if Node.js is absent on Termux)."""
    src = THEME_JS.read_text(encoding="utf-8")
    assert "innerHTML" not in src
    assert "zeryn-theme" in src
    assert "zeryn:themechange" in src
    assert "theme-switching" in src
    assert "requestAnimationFrame" in src
    for mode in ("'light'", "'dark'", "'auto'"):
        assert mode in src, f"Missing mode {mode} in theme.js"


def test_theme_js_behavior_in_node_vm():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not found in PATH")

    js_script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const code = fs.readFileSync(process.argv[1], 'utf8');

function runScenario(opts = {}) {
  const store = Object.create(null);
  if (opts.initialStored !== undefined) store['zeryn-theme'] = opts.initialStored;
  let prefersDark = Boolean(opts.prefersDark);
  const mqlListeners = [];
  const docListeners = {};
  const winListeners = {};
  const dispatched = [];

  const attrs = {};
  const classes = new Set();
  const rafQueue = [];
  let nextRafId = 1;
  const iconEl = { _text: '' };
  Object.defineProperty(iconEl, 'textContent', {
    get() { return this._text; },
    set(v) { this._text = String(v); },
  });
  Object.defineProperty(iconEl, 'innerHTML', {
    set() { throw new Error('innerHTML must not be used'); },
  });

  const textEl = { _text: '' };
  Object.defineProperty(textEl, 'textContent', {
    get() { return this._text; },
    set(v) { this._text = String(v); },
  });
  Object.defineProperty(textEl, 'innerHTML', {
    set() { throw new Error('innerHTML must not be used'); },
  });

  const btnAttrs = {};
  const toggleBtn = {
    dataset: {},
    setAttribute(k, v) { btnAttrs[k] = String(v); },
    getAttribute(k) { return btnAttrs[k]; },
    querySelector(sel) {
      if (sel === '.theme-toggle-icon') return iconEl;
      if (sel === '.theme-toggle-text') return textEl;
      return null;
    },
    closest(sel) { return sel === '[data-theme-toggle]' ? toggleBtn : null; },
  };
  Object.defineProperty(toggleBtn, 'innerHTML', {
    set() { throw new Error('innerHTML must not be used on button'); },
  });

  const i18nEl = {
    textContent: JSON.stringify({
      light: 'Sáng',
      dark: 'Tối',
      auto: 'Tự động',
      tooltip: 'Đổi giao diện',
    }),
  };

  const sandbox = {
    window: null,
    document: {
      readyState: 'complete',
      documentElement: {
        offsetHeight: 900,
        classList: {
          add(c) { classes.add(c); },
          remove(c) { classes.delete(c); },
          contains(c) { return classes.has(c); },
        },
        setAttribute(k, v) { attrs[k] = String(v); },
        getAttribute(k) { return attrs[k]; },
      },
      getElementById(id) { return id === 'theme-i18n' ? i18nEl : null; },
      querySelectorAll(sel) { return sel === '[data-theme-toggle]' ? [toggleBtn] : []; },
      addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
    },
    CustomEvent: function CustomEvent(type, init) {
      this.type = type;
      this.detail = init && init.detail;
      this.bubbles = Boolean(init && init.bubbles);
      this.composed = Boolean(init && init.composed);
    },
  };
  sandbox.window = {
    localStorage: opts.throwStorage ? {
      getItem() { throw new Error('blocked'); },
      setItem() { throw new Error('blocked'); },
    } : {
      getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
      setItem(k, v) { store[k] = String(v); },
    },
    matchMedia(query) {
      assert.strictEqual(query, '(prefers-color-scheme: dark)');
      return {
        get matches() { return prefersDark; },
        addEventListener(ev, fn) { if (ev === 'change') mqlListeners.push(fn); },
      };
    },
    dispatchEvent(ev) { dispatched.push(ev); return true; },
    addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); },
    requestAnimationFrame(fn) { const id = nextRafId++; rafQueue.push({ id, fn }); return id; },
    cancelAnimationFrame(id) {
      const idx = rafQueue.findIndex((item) => item.id === id);
      if (idx !== -1) rafQueue.splice(idx, 1);
    },
  };

  vm.runInNewContext(code, sandbox);
  return {
    api: sandbox.window.zerynTheme,
    store,
    attrs,
    classes,
    flushRaf() {
      const batch = rafQueue.splice(0, rafQueue.length);
      batch.forEach((item) => item.fn(0));
    },
    toggleBtn,
    btnAttrs,
    iconEl,
    textEl,
    dispatched,
    triggerOsDark(next) {
      prefersDark = next;
      mqlListeners.forEach((fn) => fn({ matches: next }));
    },
    clickToggle() {
      let prevented = false;
      (docListeners.click || []).forEach((fn) => fn({
        target: toggleBtn,
        preventDefault() { prevented = true; },
      }));
      return prevented;
    },
  };
}

// 1. Default auto resolves OS preference (dark -> 'dark')
const s1 = runScenario({ prefersDark: true });
assert.strictEqual(s1.api.get(), 'auto');
assert.strictEqual(s1.api.resolved(), 'dark');
assert.strictEqual(s1.attrs['data-theme'], 'dark');
assert.strictEqual(s1.iconEl.textContent, '☀︎');
assert.strictEqual(s1.textEl.textContent, 'Sáng');
assert.strictEqual(s1.toggleBtn.dataset.mode, 'auto');
assert.strictEqual(s1.toggleBtn.dataset.resolved, 'dark');

// 2. OS preference change triggers auto-switch & zeryn:themechange
s1.triggerOsDark(false);
assert.strictEqual(s1.attrs['data-theme'], 'light');
assert.strictEqual(s1.toggleBtn.dataset.resolved, 'light');
const evAuto = s1.dispatched[s1.dispatched.length - 1];
assert.strictEqual(evAuto.type, 'zeryn:themechange');
assert.strictEqual(evAuto.detail.mode, 'auto');
assert.strictEqual(evAuto.detail.resolved, 'light');
assert.strictEqual(evAuto.bubbles, false);
assert.strictEqual(evAuto.composed, false);

// 3. 3-state cycle: auto -> light -> dark -> auto (via click & cycle)
assert.strictEqual(s1.clickToggle(), true);
assert.strictEqual(s1.api.get(), 'light');
assert.strictEqual(s1.store['zeryn-theme'], 'light');
assert.strictEqual(s1.attrs['data-theme'], 'light');
assert.strictEqual(s1.iconEl.textContent, '☾');
assert.strictEqual(s1.textEl.textContent, 'Tối');

s1.api.cycle();
assert.strictEqual(s1.api.get(), 'dark');
assert.strictEqual(s1.store['zeryn-theme'], 'dark');
assert.strictEqual(s1.attrs['data-theme'], 'dark');
assert.strictEqual(s1.iconEl.textContent, '◐');
assert.strictEqual(s1.textEl.textContent, 'Tự động');

// Explicit dark ignores OS change
s1.triggerOsDark(false);
assert.strictEqual(s1.attrs['data-theme'], 'dark');

s1.api.cycle();
assert.strictEqual(s1.api.get(), 'auto');
assert.strictEqual(s1.store['zeryn-theme'], 'auto');
assert.strictEqual(s1.attrs['data-theme'], 'light');

// 4. Restricted localStorage falls back to in-memory mode cleanly
const s2 = runScenario({ throwStorage: true, prefersDark: false });
assert.strictEqual(s2.api.get(), 'auto');
s2.api.set('dark');
assert.strictEqual(s2.api.get(), 'dark');
assert.strictEqual(s2.attrs['data-theme'], 'dark');

// 5. Double-rAF keeps html.theme-switching active across Frame 1 paint, then clears cleanly
assert.strictEqual(s2.classes.has('theme-switching'), true);
s2.flushRaf();
assert.strictEqual(s2.classes.has('theme-switching'), true);
s2.flushRaf();
assert.strictEqual(s2.classes.has('theme-switching'), false);
"""

    proc = subprocess.run(
        [node, "-e", js_script, str(THEME_JS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    assert proc.returncode == 0, f"Node VM test failed:\n{proc.stdout}\n{proc.stderr}"


# ─── 4. WCAG Contrast Math (>= 4.5:1) ─────────────────────────────────────────

def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def _chan(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)


def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l1 = _relative_luminance(_hex_to_rgb(fg_hex))
    l2 = _relative_luminance(_hex_to_rgb(bg_hex))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _extract_css_block(css: str, selector: str) -> str:
    """Brace-balanced CSS block extractor tolerant of whitespace/comments/minification."""
    cleaned = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    m = re.search(rf"{re.escape(selector)}\s*\{{", cleaned)
    if not m:
        return ""
    depth = 1
    pos = m.end()
    start = pos
    while pos < len(cleaned) and depth > 0:
        ch = cleaned[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:pos]
        pos += 1
    return ""


def _parse_css_vars(block: str, base: dict[str, str] | None = None) -> dict[str, str]:
    tokens = dict(base or {})
    for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;}]+)", block):
        tokens[m.group(1)] = m.group(2).strip()
    for _ in range(4):
        for k, v in list(tokens.items()):
            vm = re.match(r"^var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)$", v)
            if vm:
                ref_val = tokens.get(vm.group(1))
                if ref_val is not None:
                    tokens[k] = ref_val
                elif vm.group(2):
                    tokens[k] = vm.group(2).strip()
    return tokens


def test_style_css_wcag_contrast_ratios():
    css = STYLE_CSS.read_text(encoding="utf-8")
    root_block = _extract_css_block(css, ":root")
    dark_block = _extract_css_block(css, '[data-theme="dark"]')
    assert root_block and dark_block, "Missing :root or [data-theme='dark'] block in style.css"

    light = _parse_css_vars(root_block)
    dark = _parse_css_vars(dark_block, base=light)

    assert light["--bg-body"].lower() == "#f5f4fb"
    assert dark["--bg-body"].lower() == "#0d0b16"

    for mode_name, tokens in (("light", light), ("dark", dark)):
        bg = tokens["--bg-body"]
        for tok in ("--ink", "--mut", "--text-muted", "--accent-ink", "--pink-ink", "--success", "--danger-ink", "--warning"):
            ratio = _contrast_ratio(tokens[tok], bg)
            assert ratio >= 4.5, f"{mode_name} {tok} ({tokens[tok]}) on {bg} contrast={ratio:.2f} < 4.5"

    # Primary ink accent (#5e4ce6) passes normal-text >=4.5:1 with white foreground
    assert _contrast_ratio("#ffffff", light["--accent-ink"]) >= 4.5
    # Brand gradient base (#7c6cf0) meets UI/large-text >=3.0:1 threshold with white foreground
    assert _contrast_ratio("#ffffff", light["--accent"]) >= 3.0


def test_landing_html_wcag_contrast_ratios():
    html = (TEMPLATES_DIR / "landing.html").read_text(encoding="utf-8")
    root_block = _extract_css_block(html, ":root")
    dark_block = _extract_css_block(html, '[data-theme="dark"]')
    assert root_block and dark_block, "Missing :root or [data-theme='dark'] in landing.html"

    light = _parse_css_vars(root_block)
    dark = _parse_css_vars(dark_block, base=light)
    tokens_to_check = (
        "--ink",
        "--mut",
        "--dim",
        "--text-primary",
        "--text-secondary",
        "--text-muted",
        "--accent-vio-text",
        "--accent-coral-text",
        "--accent-amber-text",
        "--accent-mint-text",
        "--accent-blue-text",
        "--accent-red-text",
        "--accent-pink-text",
    )
    for mode_name, tokens in (("light", light), ("dark", dark)):
        bg = tokens["--bg"]
        for tok in tokens_to_check:
            ratio = _contrast_ratio(tokens[tok], bg)
            assert ratio >= 4.5, f"landing.html {mode_name} {tok} ({tokens[tok]}) on {bg}: {ratio:.2f} < 4.5"


def test_server_overview_charts_sync_with_theme_change():
    html = (TEMPLATES_DIR / "server.html").read_text(encoding="utf-8")
    assert "readChartThemeTokens" in html
    assert "getComputedStyle(document.documentElement)" in html
    assert "zeryn:themechange" in html
    assert "chart.update('none')" in html
    assert "Chart.defaults.color = '#b9bbbe'" not in html
