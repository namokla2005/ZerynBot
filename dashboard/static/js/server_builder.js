(() => {
  'use strict';

  const byId = id => document.getElementById(id);
  const studio = byId('sb-studio');
  if (!studio) return;

  const parseJson = id => {
    try { return JSON.parse(byId(id)?.textContent || '{}'); }
    catch (error) { return {}; }
  };
  const boot = parseJson('sb-bootstrap');
  const i18n = parseJson('sb-i18n');
  const tr = (key, fallback = '') => i18n[key] || fallback || key;
  const clone = value => JSON.parse(JSON.stringify(value));
  const gid = String(boot.guild_id || window.GUILD_ID || '');
  const apiBase = `/api/guild/${encodeURIComponent(gid)}/server-builder`;
  const terminalStatuses = new Set(['completed', 'cancelled', 'failed']);
  const permissionColumns = [
    { key: 'view_channel', flags: ['view_channel'] },
    { key: 'send_speak', flags: ['send_messages', 'speak'] },
    { key: 'connect_voice', flags: ['connect'] },
    { key: 'embed_file', flags: ['embed_links', 'attach_files'] },
  ];

  const state = {
    live: null,
    draft: { categories: [], uncategorized: [], roles: [], bindings: {} },
    initialDraft: null,
    roles: [],
    templates: { system: [], custom: [] },
    currentPresetValue: 'community_4cat',
    selected: null,
    history: [],
    diff: null,
    previewBusy: false,
    previewTimer: null,
    previewAbort: null,
    drag: null,
    tempIndex: 0,
    activeJob: boot.active_job || null,
    pollBusy: false,
    pollTimer: null,
    clockTimer: null,
    etaDeadline: 0,
    startedAt: 0,
  };

  const els = {
    source: byId('sb-source-badge'), banners: byId('sb-banners'), preset: byId('sb-preset'),
    customGroup: byId('sb-custom-presets'), systemGroup: byId('sb-system-presets'), deleteTemplate: byId('sb-delete-template'),
    importLive: byId('sb-import-live'), saveTemplate: byId('sb-save-template'), safeMode: byId('sb-safe-mode'),
    undo: byId('sb-undo'), reset: byId('sb-reset'), tree: byId('sb-tree'), count: byId('sb-channel-count'),
    addCategory: byId('sb-add-category'), inspectorEmpty: byId('sb-inspector-empty'), inspector: byId('sb-inspector'),
    kind: byId('sb-kind'), name: byId('sb-name'), sanitizeWrap: byId('sb-sanitize-wrap'), sanitize: byId('sb-sanitized-preview'),
    typeWrap: byId('sb-type-wrap'), type: byId('sb-channel-type'), newsHint: byId('sb-news-hint'),
    parentWrap: byId('sb-parent-wrap'), parent: byId('sb-parent'),
    topicWrap: byId('sb-topic-wrap'), topic: byId('sb-topic'), slowmodeWrap: byId('sb-slowmode-wrap'), slowmode: byId('sb-slowmode'),
    nsfwWrap: byId('sb-nsfw-wrap'), nsfw: byId('sb-nsfw'), voiceWrap: byId('sb-voice-wrap'), bitrate: byId('sb-bitrate'),
    userLimit: byId('sb-user-limit'), moduleWrap: byId('sb-module-wrap'), module: byId('sb-module'), syncSelected: byId('sb-sync-selected'),
    botViewWarning: byId('sb-bot-view-warning'), permissionsBody: byId('sb-permissions-body'), diffSummary: byId('sb-diff-summary'),
    refreshDiff: byId('sb-refresh-diff'), pendingCount: byId('sb-pending-count'), eta: byId('sb-eta'), discard: byId('sb-discard'),
    reviewApply: byId('sb-review-apply'), templateModal: byId('sb-template-modal'), templateName: byId('sb-template-name'),
    templateDescription: byId('sb-template-description'), templateConfirm: byId('sb-template-confirm'), diffModal: byId('sb-diff-modal'),
    diffModalSummary: byId('sb-diff-modal-summary'), modalRenameWarn: byId('sb-modal-rename-warn'),
    operationGroups: byId('sb-operation-groups'), deletionWarning: byId('sb-deletion-warning'), deletionTargets: byId('sb-deletion-targets'),
    confirmDeletions: byId('sb-confirm-deletions'), autoBind: byId('sb-auto-bind'), sendGuides: byId('sb-send-guides'),
    applyConfirm: byId('sb-apply-confirm'), progressModal: byId('sb-progress-modal'), jobCode: byId('sb-job-code'),
    jobStatus: byId('sb-job-status'), progressBar: byId('sb-progress-bar'), progressText: byId('sb-progress-text'),
    countdown: byId('sb-countdown'), elapsed: byId('sb-elapsed'), currentStep: byId('sb-current-step'),
    rateLimit: byId('sb-rate-limit'), rateLimitCountdown: byId('sb-rate-limit-countdown'), auditFeed: byId('sb-audit-feed'),
    cancelJob: byId('sb-cancel-job'), reload: byId('sb-reload'), closeProgress: byId('sb-close-progress'),
  };

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function button(className, text, title, action) {
    const element = node('button', className, text);
    element.type = 'button';
    if (title) element.title = title;
    if (action) element.dataset.action = action;
    return element;
  }

  function notify(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(String(message), type);
      return;
    }
    let host = byId('sb-toast-fallback');
    if (!host) {
      host = node('div', 'sb-toast-fallback');
      host.id = 'sb-toast-fallback';
      host.setAttribute('aria-live', 'polite');
      document.body.append(host);
    }
    const toast = node('div', `sb-toast sb-toast-${type}`, message);
    host.append(toast);
    window.setTimeout(() => toast.remove(), 4000);
  }

  async function request(path, options = {}) {
    const response = await fetch(`${apiBase}${path}`, options);
    let data;
    try { data = await response.json(); }
    catch (error) { data = { ok: false, message: tr('network_error') }; }
    if (!response.ok || data.ok === false) {
      const failure = new Error(data.message || data.error || tr('unknown_error'));
      failure.status = response.status;
      failure.data = data;
      throw failure;
    }
    return data;
  }

  function newTemp(prefix) {
    state.tempIndex += 1;
    return `tmp_${prefix}_${Date.now().toString(36)}_${state.tempIndex}`;
  }

  function entityKey(item) {
    return String(item.id || item.temp_id || '');
  }

  function normalizeBindModule(val) {
    if (val === null || val === undefined) return null;
    const text = String(val).trim();
    if (!text || text === 'none' || text === 'null' || text === 'undefined') return null;
    return text;
  }

  function parseRoleColor(value) {
    if (typeof value === 'number') {
      const num = Number.isFinite(value) && value > 0 ? (Math.trunc(value) & 0xffffff) : 0;
      return { intVal: num, css: num ? `#${num.toString(16).padStart(6, '0')}` : '#8b8d96' };
    }
    const text = String(value || '').trim();
    const hexMatch = /^#?([0-9a-fA-F]{6})$/.exec(text);
    if (hexMatch) {
      const num = parseInt(hexMatch[1], 16);
      return { intVal: num, css: num ? `#${hexMatch[1].toLowerCase()}` : '#8b8d96' };
    }
    if (/^\d+$/.test(text)) {
      const num = Number(text) & 0xffffff;
      return { intVal: num, css: num ? `#${num.toString(16).padStart(6, '0')}` : '#8b8d96' };
    }
    return { intVal: 0, css: '#8b8d96' };
  }

  function normalizeRoleEntry(role) {
    const cleanId = (role.id !== null && role.id !== undefined && String(role.id) !== '' && String(role.id) !== 'null')
      ? String(role.id)
      : null;
    const tempId = role.temp_id ? String(role.temp_id) : null;
    const isEveryone = Boolean(role.is_everyone || role.name === '@everyone');
    const parsed = parseRoleColor(role.color);
    const entry = {
      id: cleanId,
      temp_id: tempId,
      name: String(role.name || ''),
      color: parsed.intVal,
      position: Number(role.position || 0),
      hoist: Boolean(role.hoist),
      mentionable: Boolean(role.mentionable),
      managed: Boolean(role.managed),
      is_everyone: isEveryone,
    };
    if (role.permissions !== undefined && role.permissions !== null) {
      entry.permissions = role.permissions;
    }
    return entry;
  }

  function mergedRoles() {
    const result = [];
    const byId = new Set();
    const byTemp = new Set();
    let hasEveryone = false;

    const addRole = raw => {
      if (!raw || typeof raw !== 'object') return;
      const entry = normalizeRoleEntry(raw);
      if (entry.is_everyone) {
        if (hasEveryone) return;
        hasEveryone = true;
      }
      if (entry.id && byId.has(entry.id)) return;
      if (entry.temp_id && byTemp.has(entry.temp_id)) return;
      if (entry.id) byId.add(entry.id);
      if (entry.temp_id) byTemp.add(entry.temp_id);
      result.push(entry);
    };

    (state.roles || []).forEach(addRole);
    (state.draft.roles || []).forEach(addRole);
    return result;
  }

  function normalizeChannel(raw, parentId) {
    const channel = {
      id: raw.id ? String(raw.id) : null,
      temp_id: raw.temp_id || (!raw.id ? newTemp('ch') : null),
      name: String(raw.name || tr('new_channel')),
      type: [0, 2, 5].includes(Number(raw.type)) ? Number(raw.type) : 0,
      parent_id: parentId === undefined ? (raw.parent_id == null ? null : String(raw.parent_id)) : parentId,
      position: Number(raw.position || 0),
      topic: String(raw.topic || ''),
      slowmode: Number(raw.slowmode || 0),
      nsfw: Boolean(raw.nsfw),
      bitrate: Number(raw.bitrate || 64000),
      user_limit: Number(raw.user_limit || 0),
      overwrites: Array.isArray(raw.overwrites) ? clone(raw.overwrites) : [],
      permissions_synced: raw.permissions_synced !== false,
      sync_permissions: raw.sync_permissions !== false,
      bind_module: normalizeBindModule(raw.bind_module),
      _deleted: Boolean(raw._deleted),
    };
    channel._original = raw._original || (channel.id ? JSON.stringify(compactChannel(channel)) : null);
    return channel;
  }

  function normalizeTree(raw) {
    const categories = (Array.isArray(raw?.categories) ? raw.categories : []).map((entry, index) => {
      const category = {
        id: entry.id ? String(entry.id) : null,
        temp_id: entry.temp_id || (!entry.id ? newTemp('cat') : null),
        name: String(entry.name || tr('new_category')),
        type: 4,
        position: Number(entry.position ?? index),
        overwrites: Array.isArray(entry.overwrites) ? clone(entry.overwrites) : [],
        channels: [],
        _deleted: Boolean(entry._deleted),
        _collapsed: Boolean(entry._collapsed),
      };
      const key = entityKey(category);
      category.channels = (Array.isArray(entry.channels) ? entry.channels : []).map(ch => normalizeChannel(ch, key));
      category._original = entry._original || (category.id ? JSON.stringify(compactCategory(category, false)) : null);
      return category;
    });
    return {
      categories,
      uncategorized: (Array.isArray(raw?.uncategorized) ? raw.uncategorized : []).map(ch => normalizeChannel(ch, null)),
      roles: Array.isArray(raw?.roles) ? clone(raw.roles) : clone(state.roles),
      bindings: raw?.bindings && typeof raw.bindings === 'object' ? clone(raw.bindings) : {},
    };
  }

  function compactOverwrites(items) {
    return (Array.isArray(items) ? items : []).map(item => ({
      id: String(item.id || ''),
      type: item.type === 'member' ? 'member' : 'role',
      allow: Array.isArray(item.allow) ? [...new Set(item.allow.map(String))] : [],
      deny: Array.isArray(item.deny) ? [...new Set(item.deny.map(String))] : [],
    })).filter(item => item.id);
  }

  function compactChannel(ch) {
    return {
      id: ch.id || null,
      temp_id: ch.temp_id || null,
      name: String(ch.name || ''),
      type: Number(ch.type),
      parent_id: ch.parent_id || null,
      position: Number(ch.position || 0),
      topic: String(ch.topic || ''),
      slowmode: Number(ch.slowmode || 0),
      nsfw: Boolean(ch.nsfw),
      bitrate: Number(ch.bitrate || 64000),
      user_limit: Number(ch.user_limit || 0),
      overwrites: compactOverwrites(ch.overwrites),
      permissions_synced: Boolean(ch.permissions_synced),
      sync_permissions: Boolean(ch.sync_permissions),
      bind_module: normalizeBindModule(ch.bind_module),
    };
  }

  function compactCategory(cat, withChildren = true) {
    const result = {
      id: cat.id || null,
      temp_id: cat.temp_id || null,
      name: String(cat.name || ''),
      type: 4,
      position: Number(cat.position || 0),
      overwrites: compactOverwrites(cat.overwrites),
    };
    if (withChildren) result.channels = cat.channels.filter(ch => !ch._deleted).map(compactChannel);
    return result;
  }

  function cleanBindings(activeChannels) {
    const activeRefs = new Set();
    activeChannels.forEach(ch => {
      if (ch.id) activeRefs.add(String(ch.id));
      if (ch.temp_id) activeRefs.add(String(ch.temp_id));
    });
    const out = {};
    const raw = state.draft.bindings && typeof state.draft.bindings === 'object' ? state.draft.bindings : {};
    Object.entries(raw).forEach(([modKey, targetRef]) => {
      const cleanKey = normalizeBindModule(modKey);
      const refStr = targetRef === null || targetRef === undefined ? '' : String(targetRef).trim();
      if (!cleanKey || !refStr || refStr === 'none' || refStr === 'null') return;
      if (!activeRefs.has(refStr)) return;
      out[cleanKey] = refStr;
    });
    activeChannels.forEach(ch => {
      const bm = normalizeBindModule(ch.bind_module);
      if (bm && !out[bm]) {
        out[bm] = entityKey(ch);
      }
    });
    return out;
  }

  function compactTree() {
    const activeCats = state.draft.categories.filter(cat => !cat._deleted);
    const activeUncat = state.draft.uncategorized.filter(ch => !ch._deleted);
    const activeChannels = [...activeCats.flatMap(cat => cat.channels.filter(ch => !ch._deleted)), ...activeUncat];
    return {
      categories: activeCats.map(cat => compactCategory(cat, true)),
      uncategorized: activeUncat.map(compactChannel),
      roles: mergedRoles(),
      bindings: cleanBindings(activeChannels),
    };
  }

  function payloadBody(extra = {}) {
    const body = { tree: compactTree(), safe_mode: els.safeMode.checked, confirm_deletions: false, ...extra };
    const json = JSON.stringify(body);
    if (new TextEncoder().encode(json).length >= 100000) throw new Error(tr('payload_too_large'));
    return { body, json };
  }

  function allChannels() {
    return [...state.draft.categories.flatMap(cat => cat.channels), ...state.draft.uncategorized];
  }

  function findEntity(key) {
    for (const category of state.draft.categories) {
      if (entityKey(category) === key) return { kind: 'category', item: category, parent: null, list: state.draft.categories };
      const child = category.channels.find(ch => entityKey(ch) === key);
      if (child) return { kind: 'channel', item: child, parent: category, list: category.channels };
    }
    const child = state.draft.uncategorized.find(ch => entityKey(ch) === key);
    return child ? { kind: 'channel', item: child, parent: null, list: state.draft.uncategorized } : null;
  }

  function ensureSelection() {
    if (state.selected && findEntity(state.selected)) return;
    if (state.draft.categories.length) state.selected = entityKey(state.draft.categories[0]);
    else if (state.draft.uncategorized.length) state.selected = entityKey(state.draft.uncategorized[0]);
    else state.selected = null;
  }

  function snapshot() {
    state.history.push({ draft: clone(state.draft), selected: state.selected });
    if (state.history.length > 40) state.history.shift();
    els.undo.disabled = false;
  }

  function mutate(callback) {
    snapshot();
    callback();
    updatePositions();
    state.diff = null;
    ensureSelection();
    renderAll();
    schedulePreviewDiff();
  }

  function updatePositions() {
    state.draft.categories.forEach((cat, catIndex) => {
      cat.position = catIndex;
      const parentId = entityKey(cat);
      cat.channels.forEach((ch, index) => { ch.position = index; ch.parent_id = parentId; });
    });
    state.draft.uncategorized.forEach((ch, index) => { ch.position = index; ch.parent_id = null; });
  }

  function isModified(item, kind) {
    if (!item.id) return true;
    if (item._deleted) return false;
    const now = kind === 'category' ? compactCategory(item, false) : compactChannel(item);
    return item._original !== JSON.stringify(now);
  }

  function pendingCount() {
    let total = 0;
    state.draft.categories.forEach(cat => {
      if (!cat.id || cat._deleted || isModified(cat, 'category')) total += 1;
      cat.channels.forEach(ch => { if (!ch.id || ch._deleted || isModified(ch, 'channel')) total += 1; });
    });
    state.draft.uncategorized.forEach(ch => { if (!ch.id || ch._deleted || isModified(ch, 'channel')) total += 1; });
    return total;
  }

  function everyoneRoleId() {
    const found = mergedRoles().find(r => r.is_everyone || r.name === '@everyone');
    return found && found.id ? String(found.id) : null;
  }

  function overwriteFor(item, roleId) {
    const targetId = String(roleId);
    const evId = targetId === '@everyone' ? everyoneRoleId() : null;
    return (item.overwrites || []).find(ow => {
      if ((ow.type || 'role') !== 'role') return false;
      const idStr = String(ow.id);
      return idStr === targetId || (evId && idStr === evId);
    });
  }

  function permissionState(item, roleId, flags) {
    const overwrite = overwriteFor(item, roleId);
    if (!overwrite) return 'inherit';
    if (flags.some(flag => (overwrite.deny || []).includes(flag))) return 'deny';
    if (flags.some(flag => (overwrite.allow || []).includes(flag))) return 'allow';
    return 'inherit';
  }

  function columnFlags(item, kind, column) {
    if (column.key !== 'send_speak') return column.flags;
    if (kind === 'channel') return Number(item.type) === 2 ? ['speak'] : ['send_messages'];
    return ['send_messages', 'speak'];
  }

  function isViewDenied(item) {
    return permissionState(item, '@everyone', ['view_channel']) === 'deny';
  }

  function isReadOnly(item) {
    return permissionState(item, '@everyone', ['send_messages', 'speak']) === 'deny';
  }

  function isPrivate(item) {
    return isViewDenied(item);
  }

  function channelIcon(ch) {
    if (isViewDenied(ch)) return '🔒';
    if (Number(ch.type) === 2) return '🔊';
    if (Number(ch.type) === 5) return '📢';
    return '#';
  }

  function statusPill(item, kind) {
    if (item._deleted) return node('span', 'sb-status sb-status-deleted', tr('status_deleted'));
    if (!item.id) return node('span', 'sb-status sb-status-new', tr('status_new'));
    if (isModified(item, kind)) return node('span', 'sb-status sb-status-modified', tr('status_modified'));
    return null;
  }

  function actionIcon(symbol, title, action, key) {
    const control = button('sb-icon-btn', symbol, title, action);
    control.dataset.key = key;
    return control;
  }

  function renderCategory(category) {
    const key = entityKey(category);
    const activeCount = category.channels.filter(ch => !ch._deleted).length;
    const isSelected = state.selected === key;
    const card = node('article', `sb-category${category._deleted ? ' is-deleted' : ''}${isSelected ? ' is-selected' : ''}`);
    card.dataset.key = key;
    card.dataset.kind = 'category';
    card.draggable = !category._deleted;

    const head = node('div', 'sb-category-head');
    const collapse = actionIcon(category._collapsed ? '▶' : '▼', '', 'collapse', key);
    const drag = node('span', 'sb-drag', '⠿'); drag.title = tr('move_up');
    const name = node('button', 'sb-entity-name', category.name);
    name.type = 'button'; name.dataset.action = 'select'; name.dataset.key = key;
    head.append(collapse, drag, name);

    const catCount = node('span', `sb-cat-count${activeCount > 50 ? ' is-danger' : ''}`, `${activeCount}/50`);
    head.append(catCount);
    if (isReadOnly(category)) head.append(node('span', 'sb-mini-badge', tr('read_only')));
    if (isPrivate(category)) head.append(node('span', 'sb-mini-badge sb-private', tr('private')));
    const pill = statusPill(category, 'category'); if (pill) head.append(pill);

    const actions = node('div', 'sb-row-actions');
    const sync = button('sb-text-btn', tr('sync'), tr('sync_children'), 'sync-category'); sync.dataset.key = key;
    const add = actionIcon('+', tr('add_channel'), 'add-channel', key);
    actions.append(
      sync, add,
      actionIcon('↑', tr('move_up'), 'up', key),
      actionIcon('↓', tr('move_down'), 'down', key),
      actionIcon(category._deleted ? '↩' : '×', category._deleted ? tr('restore') : tr('delete'), 'delete', key)
    );
    head.append(actions);
    card.append(head);

    if (!category._collapsed) {
      const children = node('div', 'sb-channel-list');
      children.dataset.parent = key;
      category.channels.forEach(ch => children.append(renderChannel(ch)));
      card.append(children);
    }
    return card;
  }

  function renderChannel(channel) {
    const key = entityKey(channel);
    const isSelected = state.selected === key;
    const row = node('div', `sb-channel-row${channel._deleted ? ' is-deleted' : ''}${isSelected ? ' is-selected' : ''}`);
    row.dataset.key = key; row.dataset.kind = 'channel'; row.draggable = !channel._deleted;
    const drag = node('span', 'sb-drag', '⠿');
    const icon = node('span', 'sb-channel-icon', channelIcon(channel));
    const name = node('button', 'sb-entity-name', channel.name);
    name.type = 'button'; name.dataset.action = 'select'; name.dataset.key = key;
    name.title = tr('selected_channel');
    row.append(drag, icon, name);
    const pill = statusPill(channel, 'channel'); if (pill) row.append(pill);
    const isSynced = channel.sync_permissions !== false && channel.permissions_synced !== false;
    row.append(node('span', isSynced ? 'sb-sync-badge is-synced' : 'sb-sync-badge', isSynced ? tr('synced') : tr('custom_permissions')));
    const actions = node('div', 'sb-row-actions');
    actions.append(
      actionIcon('↑', tr('move_up'), 'up', key),
      actionIcon('↓', tr('move_down'), 'down', key),
      actionIcon(channel._deleted ? '↩' : '×', channel._deleted ? tr('restore') : tr('delete'), 'delete', key)
    );
    row.append(actions);
    return row;
  }

  function renderTree() {
    const fragment = document.createDocumentFragment();
    state.draft.categories.forEach(category => fragment.append(renderCategory(category)));
    if (state.draft.uncategorized.length) {
      const section = node('section', 'sb-category sb-uncategorized');
      const head = node('div', 'sb-category-head');
      head.append(node('strong', '', tr('uncategorized')));
      const add = button('sb-text-btn', '+', tr('add_channel'), 'add-uncategorized');
      head.append(add); section.append(head);
      const list = node('div', 'sb-channel-list'); list.dataset.parent = '';
      state.draft.uncategorized.forEach(ch => list.append(renderChannel(ch)));
      section.append(list); fragment.append(section);
    }
    if (!state.draft.categories.length && !state.draft.uncategorized.length) {
      fragment.append(node('div', 'sb-empty', tr('diff_empty')));
    }
    els.tree.replaceChildren(fragment);
    const total = state.draft.categories.filter(cat => !cat._deleted).length + allChannels().filter(ch => !ch._deleted).length;
    const categoryOverflow = state.draft.categories.some(cat => cat.channels.filter(ch => !ch._deleted).length > 50);
    els.count.textContent = `${total} / 500`;
    els.count.classList.toggle('is-danger', total > 500 || categoryOverflow);
  }

  function sanitizeName(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^\p{L}\p{N}_-]/gu, '')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 100) || 'channel';
  }

  function option(value, label) {
    const item = node('option', '', label); item.value = value; return item;
  }

  function botViewBlocked(item) {
    if (state.live?.bot_permissions?.administrator) return false;
    const botId = String(boot.bot_client_id || '');
    const botRoles = mergedRoles().filter(r => r.managed || (r.id && String(r.id) === botId) || String(r.name || '').toLowerCase().includes('zeryn'));
    if (botRoles.some(r => r.id && permissionState(item, String(r.id), ['view_channel']) === 'deny')) return true;
    const everyoneDenied = permissionState(item, '@everyone', ['view_channel']) === 'deny';
    if (!everyoneDenied) return false;
    return !botRoles.some(r => {
      const rKey = r.id ? String(r.id) : (r.temp_id ? String(r.temp_id) : '');
      return rKey && permissionState(item, rKey, ['view_channel']) === 'allow';
    });
  }

  function renderInspector() {
    const found = state.selected ? findEntity(state.selected) : null;
    els.inspector.hidden = !found;
    els.inspectorEmpty.hidden = Boolean(found);
    if (!found) return;
    const { item, kind, parent } = found;
    els.kind.textContent = kind === 'category' ? tr('selected_category') : tr('selected_channel');
    els.name.value = item.name;
    const channel = kind === 'channel';
    const chType = Number(item.type);
    els.typeWrap.hidden = !channel;
    els.parentWrap.hidden = !channel;
    els.topicWrap.hidden = !channel || chType === 2;
    els.slowmodeWrap.hidden = !channel || chType === 2;
    els.nsfwWrap.hidden = !channel || chType === 2;
    els.voiceWrap.hidden = !channel || chType !== 2;
    els.moduleWrap.hidden = !channel;
    els.sanitizeWrap.hidden = !channel || chType === 2;
    const hasCommunity = !state.live || (state.live.guild_features || []).includes('COMMUNITY');
    els.newsHint.hidden = !(channel && chType === 5 && !hasCommunity);

    if (channel) {
      els.type.value = String(chType);
      els.topic.value = item.topic;
      els.slowmode.value = String(item.slowmode);
      els.nsfw.checked = item.nsfw;
      els.bitrate.max = String(state.live?.bitrate_limit || 96000);
      els.bitrate.value = String(item.bitrate);
      els.userLimit.value = String(item.user_limit);
      els.module.value = normalizeBindModule(item.bind_module) || 'none';
      els.sanitize.textContent = sanitizeName(item.name);
      const parentOptions = [option('', tr('no_category'))];
      state.draft.categories.filter(cat => !cat._deleted).forEach(cat => parentOptions.push(option(entityKey(cat), cat.name)));
      els.parent.replaceChildren(...parentOptions);
      els.parent.value = item.parent_id || '';
      els.syncSelected.textContent = tr('sync_channel');
      els.syncSelected.disabled = !parent;
    } else {
      els.syncSelected.textContent = tr('sync_children');
      els.syncSelected.disabled = false;
    }
    renderPermissions(item, kind);
    els.botViewWarning.hidden = !botViewBlocked(item);
  }

  function renderPermissions(item, kind) {
    const rows = document.createDocumentFragment();
    mergedRoles().slice().sort((a, b) => Number(b.position) - Number(a.position)).forEach(role => {
      const row = node('tr');
      const isEveryone = Boolean(role.is_everyone || role.name === '@everyone');
      const locked = !isEveryone && Boolean(role.id) && state.live?.bot_top_role_pos != null && Number(role.position) >= Number(state.live.bot_top_role_pos);
      const roleCell = node('th');
      const dot = node('span', 'sb-role-dot');
      dot.style.backgroundColor = parseRoleColor(role.color).css;
      roleCell.append(dot, document.createTextNode(role.name || String(role.id || role.temp_id || '')));
      if (locked) {
        const lock = node('span', 'sb-role-lock', '🔒');
        lock.title = tr('role_locked');
        roleCell.append(lock);
      }
      row.append(roleCell);

      permissionColumns.forEach(column => {
        const cell = node('td');
        const group = node('div', 'sb-tristate');
        const flags = columnFlags(item, kind, column);
        const roleKey = isEveryone ? '@everyone' : String(role.id || role.temp_id || '');
        const current = permissionState(item, roleKey, flags);
        [['allow', '✅'], ['inherit', '/'], ['deny', '❌']].forEach(([value, symbol]) => {
          const control = button(`sb-state-btn${current === value ? ' active' : ''}`, symbol, tr(value), 'permission');
          control.dataset.key = entityKey(item);
          control.dataset.role = roleKey;
          control.dataset.column = column.key;
          control.dataset.value = value;
          control.disabled = locked;
          group.append(control);
        });
        cell.append(group);
        row.append(cell);
      });
      rows.append(row);
    });
    els.permissionsBody.replaceChildren(rows);
  }

  function renderBanners() {
    const banners = [];
    const permissions = state.live?.bot_permissions || {};
    const missing = [];
    if (!permissions.administrator && !permissions.manage_channels) missing.push(tr('manage_channels'));
    if (!permissions.administrator && !permissions.manage_roles) missing.push(tr('manage_roles'));
    if (state.live && (!state.live.bot_in_guild || missing.length)) {
      banners.push({ cls: 'danger', text: `${tr('permission_missing')} ${missing.join(', ')}`.trim() });
    }
    if (state.live && !(state.live.guild_features || []).includes('COMMUNITY') && allChannels().some(ch => !ch._deleted && Number(ch.type) === 5)) {
      banners.push({ cls: 'warning', text: tr('community_fallback') });
    }
    if (allChannels().some(ch => !ch._deleted && botViewBlocked(ch)) || state.draft.categories.some(cat => !cat._deleted && botViewBlocked(cat))) {
      banners.push({ cls: 'danger', text: tr('bot_view_warning') });
    }
    const total = state.draft.categories.filter(cat => !cat._deleted).length + allChannels().filter(ch => !ch._deleted).length;
    if (total > 500) banners.push({ cls: 'danger', text: tr('channel_limit_warning') });
    if (state.draft.categories.some(cat => !cat._deleted && cat.channels.filter(ch => !ch._deleted).length > 50)) {
      banners.push({ cls: 'danger', text: tr('category_limit_warning') });
    }
    els.banners.replaceChildren(...banners.map(entry => {
      const banner = node('div', `sb-banner sb-banner-${entry.cls}`);
      banner.append(node('i', 'bi bi-exclamation-triangle-fill'), document.createTextNode(entry.text));
      return banner;
    }));
  }

  function renderDiffSummary() {
    const summary = state.diff?.summary;
    if (!summary) {
      els.diffSummary.textContent = tr('diff_empty');
      els.eta.textContent = '~0s';
      return;
    }
    const grid = node('div', 'sb-summary-grid');
    const values = [
      [tr('diff_create'), Number(summary.create_roles || 0) + Number(summary.create_categories || 0) + Number(summary.create_channels || 0)],
      [tr('diff_rename'), Number(summary.renames || 0)],
      [tr('diff_sync'), Number(summary.sync_permissions || 0)],
      [tr('diff_update'), Number(summary.update_channels || 0) + Number(summary.update_overwrites || 0) + Number(summary.bulk_reorder || 0) + Number(summary.bind_modules || 0)],
      [tr('diff_delete'), Number(summary.delete_channels || 0) + Number(summary.delete_categories || 0)],
    ];
    values.forEach(([label, value]) => {
      const box = node('div', 'sb-summary-item');
      box.append(node('strong', '', value), node('span', '', label));
      grid.append(box);
    });
    if ((state.diff.warnings || []).length) {
      grid.append(node('div', 'sb-summary-note', `${tr('warnings')}: ${state.diff.warnings.join(' · ')}`));
    }
    if ((state.diff.errors || []).length) {
      grid.append(node('div', 'sb-summary-note is-danger', `${tr('errors')}: ${state.diff.errors.join(' · ')}`));
    }
    els.diffSummary.replaceChildren(grid);
    els.eta.textContent = `~${Math.ceil(Number(state.diff.eta_seconds || 0))}s`;
  }

  function renderAll() {
    ensureSelection();
    renderTree();
    renderInspector();
    renderBanners();
    renderDiffSummary();
    const diffOps = state.diff ? Number(state.diff.summary?.total_operations || 0) : pendingCount();
    els.pendingCount.textContent = String(diffOps);
    els.undo.disabled = state.history.length === 0;
    const hasErrors = Boolean(state.diff && (state.diff.errors || []).length > 0);
    const perms = state.live?.bot_permissions || {};
    const canManage = !state.live || Boolean(perms.administrator || perms.manage_channels);
    els.reviewApply.disabled = state.previewBusy || Boolean(state.activeJob) || diffOps === 0 || hasErrors || !canManage;
  }

  function selectEntity(key) {
    state.selected = key;
    renderTree();
    renderInspector();
  }

  function addCategory() {
    mutate(() => {
      const category = normalizeTree({ categories: [{ temp_id: newTemp('cat'), name: tr('new_category'), channels: [] }] }).categories[0];
      state.draft.categories.push(category);
      state.selected = entityKey(category);
    });
  }

  function addChannel(parentKey) {
    mutate(() => {
      const parent = parentKey ? findEntity(parentKey)?.item : null;
      const overwrites = parent ? clone(parent.overwrites || []) : [];
      const channel = normalizeChannel({
        temp_id: newTemp('ch'),
        name: tr('new_channel'),
        type: 0,
        overwrites,
        permissions_synced: Boolean(parent),
        sync_permissions: Boolean(parent),
      }, parentKey || null);
      if (parent) parent.channels.push(channel);
      else state.draft.uncategorized.push(channel);
      state.selected = entityKey(channel);
    });
  }

  function moveEntity(key, direction) {
    const found = findEntity(key); if (!found) return;
    const index = found.list.indexOf(found.item);
    const target = index + direction;
    if (target < 0 || target >= found.list.length) return;
    mutate(() => {
      found.list.splice(index, 1);
      found.list.splice(target, 0, found.item);
    });
  }

  function deleteOrRestore(key) {
    const found = findEntity(key); if (!found) return;
    if (found.item.id && !found.item._deleted && els.safeMode.checked) {
      notify(tr('safe_mode_protected'), 'warning');
      return;
    }
    mutate(() => {
      if (!found.item.id) {
        found.list.splice(found.list.indexOf(found.item), 1);
        if (found.kind === 'category') found.item.channels.forEach(ch => state.draft.uncategorized.push(ch));
        if (state.selected === key) state.selected = null;
      } else {
        found.item._deleted = !found.item._deleted;
        if (found.kind === 'category') found.item.channels.forEach(ch => { ch._deleted = found.item._deleted; });
      }
    });
  }

  function syncItem(key) {
    const found = findEntity(key); if (!found) return;
    mutate(() => {
      if (found.kind === 'category') {
        const catOws = clone(found.item.overwrites || []);
        found.item.channels.forEach(ch => {
          ch.overwrites = clone(catOws);
          ch.permissions_synced = true;
          ch.sync_permissions = true;
        });
      } else if (found.parent) {
        found.item.overwrites = clone(found.parent.overwrites || []);
        found.item.permissions_synced = true;
        found.item.sync_permissions = true;
      }
    });
    notify(tr('synced_toast'), 'success');
  }

  function setPermission(key, roleId, columnKey, value) {
    const found = findEntity(key);
    const column = permissionColumns.find(entry => entry.key === columnKey);
    if (!found || !column) return;
    const flags = columnFlags(found.item, found.kind, column);
    mutate(() => {
      let overwrite = overwriteFor(found.item, roleId);
      if (!overwrite) {
        overwrite = { id: roleId, type: 'role', allow: [], deny: [] };
        found.item.overwrites.push(overwrite);
      }
      flags.forEach(flag => {
        overwrite.allow = overwrite.allow.filter(item => item !== flag);
        overwrite.deny = overwrite.deny.filter(item => item !== flag);
        if (value === 'allow') overwrite.allow.push(flag);
        if (value === 'deny') overwrite.deny.push(flag);
      });
      if (!overwrite.allow.length && !overwrite.deny.length) {
        found.item.overwrites = found.item.overwrites.filter(item => item !== overwrite);
      }
      if (found.kind === 'channel') {
        found.item.permissions_synced = false;
        found.item.sync_permissions = false;
      } else if (found.kind === 'category') {
        const catOws = clone(found.item.overwrites || []);
        found.item.channels.forEach(ch => {
          if (ch.sync_permissions !== false && ch.permissions_synced !== false) {
            ch.overwrites = clone(catOws);
          }
        });
      }
    });
  }

  function updateSelected(property, value) {
    const found = state.selected ? findEntity(state.selected) : null;
    if (!found) return;
    snapshot();
    if (property === 'bind_module') {
      const nextBind = normalizeBindModule(value);
      const prevBind = normalizeBindModule(found.item.bind_module);
      if (!state.draft.bindings || typeof state.draft.bindings !== 'object') {
        state.draft.bindings = {};
      }
      const chId = found.item.id ? String(found.item.id) : null;
      const chTemp = found.item.temp_id ? String(found.item.temp_id) : null;
      const pointsToItem = ref => ref && ((chId && String(ref) === chId) || (chTemp && String(ref) === chTemp));

      if (nextBind) {
        allChannels().forEach(ch => {
          if (ch !== found.item && normalizeBindModule(ch.bind_module) === nextBind) {
            ch.bind_module = null;
          }
        });
        if (prevBind && prevBind !== nextBind && pointsToItem(state.draft.bindings[prevBind])) {
          delete state.draft.bindings[prevBind];
        }
        state.draft.bindings[nextBind] = entityKey(found.item);
      } else {
        Object.keys(state.draft.bindings).forEach(k => {
          if (pointsToItem(state.draft.bindings[k])) {
            delete state.draft.bindings[k];
          }
        });
      }
      found.item.bind_module = nextBind;
    } else {
      found.item[property] = value;
    }
    state.diff = null;
    updatePositions();
    renderAll();
    schedulePreviewDiff();
  }

  function ensureLiveOption(show) {
    let opt = els.systemGroup.querySelector('option[value="__live__"]');
    if (show && !opt) {
      opt = option('__live__', tr('preset_imported'));
      els.systemGroup.prepend(opt);
    } else if (!show && opt) {
      opt.remove();
    }
  }

  async function loadTree(usePreset = true) {
    try {
      const data = await request('/tree');
      state.live = data;
      state.roles = Array.isArray(data.roles) ? clone(data.roles) : [];
      const liveTree = normalizeTree(data);
      let selectedTree = liveTree;
      const selectedPreset = state.templates.system.find(item => String(item.id) === 'community_4cat');
      if (usePreset && selectedPreset?.tree) {
        selectedTree = normalizeTree(selectedPreset.tree);
        ensureLiveOption(false);
        state.currentPresetValue = 'community_4cat';
        els.preset.value = 'community_4cat';
      } else {
        ensureLiveOption(true);
        state.currentPresetValue = '__live__';
        els.preset.value = '__live__';
      }
      updateDeleteTemplate();
      state.draft = selectedTree;
      state.initialDraft = clone(selectedTree);
      state.history = [];
      state.selected = null;
      state.diff = null;
      els.source.textContent = data.live_source === 'discord' ? tr('source_discord') : tr('source_cache');
      if (data.active_job && !terminalStatuses.has(data.active_job.status)) attachJob(data.active_job);
      renderAll();
      schedulePreviewDiff(50);
    } catch (error) {
      els.tree.replaceChildren(node('div', 'sb-empty is-danger', `${tr('load_error')}: ${error.message}`));
      notify(error.message, 'error');
    }
  }

  async function loadTemplates() {
    try {
      const data = await request('/templates');
      state.templates = { system: data.system || [], custom: data.custom || [] };
      const systems = [];
      state.templates.system.forEach(item => {
        const label = tr(`preset_${item.id}_name`, item.name || item.name_key || item.id);
        const opt = option(String(item.id), label);
        opt.title = tr(`preset_${item.id}_desc`, item.description || '');
        systems.push(opt);
      });
      if (!systems.some(item => item.value === 'community_4cat')) {
        systems.unshift(option('community_4cat', tr('preset_community_4cat_name')));
      }
      els.systemGroup.replaceChildren(...systems);
      els.customGroup.replaceChildren(...state.templates.custom.map(item => option(`custom:${item.id}`, item.name)));
      if (state.currentPresetValue === '__live__') ensureLiveOption(true);
      els.preset.value = state.currentPresetValue || 'community_4cat';
      updateDeleteTemplate();
    } catch (error) { notify(error.message, 'error'); }
  }

  function updateDeleteTemplate() {
    els.deleteTemplate.disabled = !els.preset.value.startsWith('custom:');
  }

  function loadSelectedTemplate() {
    const value = els.preset.value;
    if (value === '__live__') return;
    let template;
    if (value.startsWith('custom:')) template = state.templates.custom.find(item => String(item.id) === value.slice(7));
    else template = state.templates.system.find(item => String(item.id) === value);
    if (!template?.tree) {
      updateDeleteTemplate();
      return;
    }
    if (pendingCount() && !window.confirm(tr('discard_confirm'))) {
      els.preset.value = state.currentPresetValue;
      updateDeleteTemplate();
      return;
    }
    ensureLiveOption(false);
    state.currentPresetValue = value;
    updateDeleteTemplate();
    state.draft = normalizeTree(template.tree);
    state.initialDraft = clone(state.draft);
    state.history = [];
    state.selected = null;
    state.diff = null;
    renderAll();
    schedulePreviewDiff(50);
  }

  async function saveTemplate() {
    const name = els.templateName.value.trim();
    if (!name) { notify(tr('template_name_required'), 'error'); return; }
    try {
      const data = await request('/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: els.templateDescription.value.trim(), tree: compactTree() }),
      });
      state.templates.custom.push(data.template);
      closeModal(els.templateModal);
      els.templateName.value = '';
      els.templateDescription.value = '';
      state.currentPresetValue = `custom:${data.template.id}`;
      await loadTemplates();
      notify(tr('template_saved'), 'success');
    } catch (error) { notify(error.message, 'error'); }
  }

  async function deleteTemplate() {
    if (!els.preset.value.startsWith('custom:') || !window.confirm(tr('delete_template_confirm'))) return;
    const id = els.preset.value.slice(7);
    try {
      await request(`/templates/${encodeURIComponent(id)}`, { method: 'DELETE' });
      state.currentPresetValue = 'community_4cat';
      await loadTemplates();
      notify(tr('template_deleted'), 'success');
    } catch (error) { notify(error.message, 'error'); }
  }

  function schedulePreviewDiff(delay = 320) {
    if (state.previewTimer) window.clearTimeout(state.previewTimer);
    state.previewTimer = window.setTimeout(() => {
      state.previewTimer = null;
      previewDiff(false, true);
    }, delay);
  }

  async function previewDiff(openAfter = false, silent = false) {
    if (state.previewAbort) {
      state.previewAbort.abort();
      state.previewAbort = null;
    }
    const controller = new AbortController();
    state.previewAbort = controller;
    state.previewBusy = true;
    renderAll();
    try {
      const packed = payloadBody();
      const data = await request('/preview-diff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: packed.json,
        signal: controller.signal,
      });
      if (state.previewAbort !== controller) return;
      state.diff = data.diff;
      state.diff.warnings = [...(data.diff.warnings || []), ...(data.warnings || [])];
      state.previewBusy = false;
      renderAll();
      if (openAfter) openDiffModal();
    } catch (error) {
      if (error.name === 'AbortError') return;
      state.previewBusy = false;
      renderAll();
      if (!silent || openAfter) notify(error.message, 'error');
    } finally {
      if (state.previewAbort === controller) state.previewAbort = null;
    }
  }

  function operationLabel(operation) {
    if (operation.label) return String(operation.label);
    const op = String(operation.op || operation.type || operation.action || '').toLowerCase();
    if (op === 'update_channel' && operation.old_name && operation.new_name && operation.old_name !== operation.new_name) {
      return `${operation.old_name} → ${operation.new_name}`;
    }
    return String(operation.name || operation.target_name || operation.channel_name || op || '—');
  }

  function operationGroup(operation) {
    const op = String(operation.op || operation.type || operation.action || '').toLowerCase();
    if (op.includes('delete')) return 'delete';
    if (op.includes('rename') || (op === 'update_channel' && operation.old_name && operation.new_name && operation.old_name !== operation.new_name)) {
      return 'rename';
    }
    if (op.includes('sync')) return 'sync';
    if (op.includes('create')) return 'create';
    return 'update';
  }

  function openDiffModal() {
    if (!state.diff) return;
    const summary = state.diff.summary || {};
    const chips = [
      [tr('diff_create'), Number(summary.create_roles || 0) + Number(summary.create_categories || 0) + Number(summary.create_channels || 0)],
      [tr('diff_rename'), Number(summary.renames || 0)],
      [tr('diff_sync'), Number(summary.sync_permissions || 0)],
      [tr('diff_update'), Number(summary.update_channels || 0) + Number(summary.update_overwrites || 0)],
      [tr('diff_reorder'), Number(summary.bulk_reorder || 0)],
      [tr('diff_bind'), Number(summary.bind_modules || 0)],
      [tr('diff_delete'), Number(summary.delete_channels || 0) + Number(summary.delete_categories || 0)],
    ].filter(([, count]) => count > 0);
    chips.push([tr('eta'), `~${Math.ceil(Number(state.diff.eta_seconds || 0))}s`]);
    els.diffModalSummary.replaceChildren(...chips.map(([lbl, val]) => node('span', 'sb-diff-chip', `${lbl}: ${val}`)));
    els.modalRenameWarn.hidden = !(summary.rename_warning || Number(summary.renames || 0) > 0);

    const groups = [
      ['create', tr('diff_create')],
      ['rename', tr('diff_rename')],
      ['sync', tr('diff_sync')],
      ['update', tr('diff_update')],
      ['delete', tr('diff_delete')],
    ];
    const operations = Array.isArray(state.diff.operations) ? state.diff.operations : [];
    const sections = [];
    groups.forEach(([kind, label]) => {
      const items = operations.filter(item => operationGroup(item) === kind);
      if (!items.length) return;
      const section = node('section', `sb-operation-group sb-operation-${kind}`);
      section.append(node('h3', '', `${label} (${items.length})`));
      const list = node('ul');
      items.forEach(item => list.append(node('li', '', operationLabel(item))));
      section.append(list);
      sections.push(section);
    });
    els.operationGroups.replaceChildren(...sections);

    const hasDeletions = Boolean(summary.has_deletions);
    els.deletionWarning.hidden = !hasDeletions;
    els.confirmDeletions.checked = false;
    const rawTargets = Array.isArray(summary.delete_targets) && summary.delete_targets.length
      ? summary.delete_targets
      : operations.filter(item => operationGroup(item) === 'delete');
    els.deletionTargets.replaceChildren(...rawTargets.map(item => node('li', '', typeof item === 'string' ? item : operationLabel(item))));
    els.applyConfirm.disabled = hasDeletions || (state.diff.errors || []).length > 0;
    openModal(els.diffModal);
  }

  async function applyDraft() {
    const summary = state.diff?.summary || {};
    const confirmDeletions = Boolean(summary.has_deletions && els.confirmDeletions.checked);
    if (summary.has_deletions && !confirmDeletions) return;
    els.applyConfirm.disabled = true;
    try {
      const packed = payloadBody({
        confirm_deletions: confirmDeletions,
        auto_bind_modules: els.autoBind.checked,
        send_guides: els.sendGuides.checked,
      });
      const data = await request('/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: packed.json,
      });
      closeModal(els.diffModal);
      attachJob(data.job);
    } catch (error) {
      if (error.status === 409 && error.data?.active_job) {
        closeModal(els.diffModal);
        attachJob(error.data.active_job);
        notify(tr('job_running'), 'info');
      } else if (error.status === 403) {
        notify(`${tr('missing_permissions')}: ${(error.data?.missing || []).join(', ')}`, 'error');
      } else {
        notify(`${tr('apply_error')}: ${error.message}`, 'error');
      }
      els.applyConfirm.disabled = false;
    }
  }

  function openModal(modal) { modal.hidden = false; document.body.classList.add('sb-modal-open'); }
  function closeModal(modal) { modal.hidden = true; if (!document.querySelector('.sb-modal:not([hidden])')) document.body.classList.remove('sb-modal-open'); }

  function formatTime(seconds) {
    const value = Math.max(0, Math.ceil(Number(seconds) || 0));
    return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  }

  function parseTimestamp(value) {
    if (value === null || value === undefined || value === '') return 0;
    if (typeof value === 'number') {
      if (!Number.isFinite(value) || value <= 0) return 0;
      return value < 1e12 ? value * 1000 : value;
    }
    const text = String(value).trim();
    if (/^\d+(\.\d+)?$/.test(text)) {
      const num = Number(text);
      return num > 0 ? (num < 1e12 ? num * 1000 : num) : 0;
    }
    const parsed = Date.parse(text);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  function attachJob(job) {
    if (!job?.id) return;
    state.activeJob = job;
    state.startedAt = parseTimestamp(job.started_at || job.created_at) || Date.now();
    state.etaDeadline = Date.now() + Number(job.eta_seconds || 0) * 1000;
    openModal(els.progressModal);
    renderJob(job);
    startJobTimers();
    renderAll();
  }

  function jobLogs(job) {
    if (Array.isArray(job.step_logs)) return job.step_logs;
    if (typeof job.step_logs_json === 'string') {
      try { const logs = JSON.parse(job.step_logs_json); return Array.isArray(logs) ? logs : []; }
      catch (error) { return []; }
    }
    return [];
  }

  function renderJob(job) {
    const total = Number(job.total_steps || 0);
    const completed = Number(job.completed_steps || 0);
    const percent = total ? Math.min(100, Math.round(completed * 100 / total)) : 0;
    els.jobCode.textContent = `#${job.job_code || job.id}`;
    els.jobStatus.textContent = tr(`status_${job.status}`, job.status);
    els.jobStatus.className = `sb-job-status sb-job-${job.status}`;
    els.progressBar.style.width = `${percent}%`;
    els.progressText.textContent = `${completed} / ${total} (${percent}%)`;
    els.currentStep.textContent = job.current_step_label || '—';
    const rateUntil = parseTimestamp(job.rate_limit_until);
    els.rateLimit.hidden = !(job.status === 'paused_rl' || rateUntil > Date.now());

    const logs = jobLogs(job);
    const scrollBottom = Math.abs(els.auditFeed.scrollHeight - els.auditFeed.scrollTop - els.auditFeed.clientHeight) < 32;
    els.auditFeed.replaceChildren(...(logs.length ? logs.map(entry => {
      const line = node('div', 'sb-audit-line');
      if (typeof entry === 'string') line.textContent = entry;
      else line.textContent = [entry.timestamp || entry.time, entry.label || entry.message || entry.status].filter(Boolean).join(' · ');
      return line;
    }) : [node('div', 'sb-empty', tr('audit_empty'))]));
    if (scrollBottom) els.auditFeed.scrollTop = els.auditFeed.scrollHeight;

    const terminal = terminalStatuses.has(job.status);
    els.cancelJob.disabled = terminal;
    els.closeProgress.disabled = !terminal;
    if (terminal && job.error_message) notify(job.error_message, 'error');
  }

  function updateClock() {
    const now = Date.now();
    els.countdown.textContent = formatTime((state.etaDeadline - now) / 1000);
    els.elapsed.textContent = formatTime((now - state.startedAt) / 1000);
    const until = parseTimestamp(state.activeJob?.rate_limit_until);
    els.rateLimitCountdown.textContent = formatTime((until - now) / 1000);
  }

  function startJobTimers() {
    if (state.clockTimer) window.clearInterval(state.clockTimer);
    if (state.pollTimer) window.clearInterval(state.pollTimer);
    updateClock();
    state.clockTimer = window.setInterval(updateClock, 1000);
    state.pollTimer = window.setInterval(pollJob, 1200);
    pollJob();
  }

  async function pollJob() {
    if (state.pollBusy || !state.activeJob?.id) return;
    state.pollBusy = true;
    try {
      const data = await request(`/jobs/${encodeURIComponent(state.activeJob.id)}`);
      state.activeJob = data.job;
      if (data.job.started_at || data.job.created_at) {
        const ts = parseTimestamp(data.job.started_at || data.job.created_at);
        if (ts) state.startedAt = ts;
      }
      state.etaDeadline = Date.now() + Number(data.job.eta_seconds || 0) * 1000;
      renderJob(data.job);
      if (terminalStatuses.has(data.job.status)) {
        window.clearInterval(state.pollTimer); state.pollTimer = null;
        window.clearInterval(state.clockTimer); state.clockTimer = null;
        if (data.job.status === 'completed') await loadTree(false);
        state.activeJob = null;
        renderAll();
      }
    } catch (error) {
      if (error.status === 404) {
        window.clearInterval(state.pollTimer); state.pollTimer = null;
        window.clearInterval(state.clockTimer); state.clockTimer = null;
        state.activeJob = null;
      }
      notify(error.message, 'error');
    } finally {
      state.pollBusy = false;
    }
  }

  async function cancelJob() {
    if (!state.activeJob?.id || !window.confirm(tr('cancel_job_confirm'))) return;
    try {
      await request(`/jobs/${encodeURIComponent(state.activeJob.id)}/cancel`, { method: 'POST' });
      notify(tr('cancel_requested'), 'info');
      await pollJob();
    } catch (error) { notify(error.message, 'error'); }
  }

  function bindInspector() {
    els.name.addEventListener('change', () => updateSelected('name', els.name.value.trim()));
    els.name.addEventListener('input', () => {
      const found = state.selected && findEntity(state.selected);
      if (found?.kind === 'channel' && Number(found.item.type) !== 2) {
        els.sanitize.textContent = sanitizeName(els.name.value);
      }
    });
    els.type.addEventListener('change', () => updateSelected('type', Number(els.type.value)));
    els.parent.addEventListener('change', () => {
      const found = state.selected && findEntity(state.selected);
      if (!found || found.kind !== 'channel') return;
      const targetKey = els.parent.value;
      snapshot();
      found.list.splice(found.list.indexOf(found.item), 1);
      if (targetKey) findEntity(targetKey)?.item.channels.push(found.item);
      else state.draft.uncategorized.push(found.item);
      found.item.parent_id = targetKey || null;
      if (!targetKey) {
        found.item.sync_permissions = false;
        found.item.permissions_synced = false;
      }
      state.diff = null;
      updatePositions();
      renderAll();
      schedulePreviewDiff();
    });
    els.topic.addEventListener('change', () => updateSelected('topic', els.topic.value));
    els.slowmode.addEventListener('change', () => updateSelected('slowmode', Number(els.slowmode.value)));
    els.nsfw.addEventListener('change', () => updateSelected('nsfw', els.nsfw.checked));
    els.bitrate.addEventListener('change', () => updateSelected('bitrate', Number(els.bitrate.value)));
    els.userLimit.addEventListener('change', () => updateSelected('user_limit', Number(els.userLimit.value)));
    els.module.addEventListener('change', () => updateSelected('bind_module', normalizeBindModule(els.module.value)));
  }

  els.tree.addEventListener('click', event => {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    const key = target.dataset.key;
    const action = target.dataset.action;
    if (action === 'select') selectEntity(key);
    else if (action === 'collapse') {
      const found = findEntity(key);
      if (found) { found.item._collapsed = !found.item._collapsed; renderTree(); }
    }
    else if (action === 'add-channel') addChannel(key);
    else if (action === 'add-uncategorized') addChannel(null);
    else if (action === 'up') moveEntity(key, -1);
    else if (action === 'down') moveEntity(key, 1);
    else if (action === 'delete') deleteOrRestore(key);
    else if (action === 'sync-category') syncItem(key);
  });

  els.tree.addEventListener('dblclick', event => {
    const target = event.target.closest('.sb-entity-name');
    if (!target) return;
    const found = findEntity(target.dataset.key);
    if (!found || found.item._deleted) return;
    const input = node('input', 'sb-inline-rename');
    input.type = 'text';
    input.value = found.item.name;
    target.replaceWith(input);
    input.focus();
    input.select();
    let settled = false;
    const finish = save => {
      if (settled) return;
      settled = true;
      if (save && input.value.trim()) {
        state.selected = entityKey(found.item);
        updateSelected('name', input.value.trim());
      } else {
        renderTree();
      }
    };
    input.addEventListener('blur', () => finish(true), { once: true });
    input.addEventListener('keydown', keyEvent => {
      if (keyEvent.key === 'Enter') { keyEvent.preventDefault(); finish(true); }
      else if (keyEvent.key === 'Escape') { keyEvent.preventDefault(); finish(false); }
    });
  });

  els.tree.addEventListener('dragstart', event => {
    const row = event.target.closest('[data-kind][data-key]');
    if (!row || row.classList.contains('is-deleted')) return;
    state.drag = { key: row.dataset.key, kind: row.dataset.kind };
    row.classList.add('is-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', row.dataset.key);
    }
  });
  els.tree.addEventListener('dragover', event => {
    if (state.drag && event.target.closest('[data-kind][data-key], .sb-channel-list')) event.preventDefault();
  });
  els.tree.addEventListener('drop', event => {
    event.preventDefault();
    if (!state.drag) return;
    const source = findEntity(state.drag.key);
    const row = event.target.closest('[data-kind][data-key]');
    if (!source || (row && row.dataset.key === state.drag.key)) { state.drag = null; return; }
    snapshot();
    source.list.splice(source.list.indexOf(source.item), 1);
    if (source.kind === 'category') {
      const target = row ? findEntity(row.dataset.key) : null;
      const index = target?.kind === 'category' ? state.draft.categories.indexOf(target.item) : state.draft.categories.length;
      state.draft.categories.splice(Math.max(0, index), 0, source.item);
    } else {
      let list = state.draft.uncategorized;
      const target = row ? findEntity(row.dataset.key) : null;
      if (target?.kind === 'channel') list = target.list;
      else if (target?.kind === 'category') list = target.item.channels;
      else {
        const container = event.target.closest('.sb-channel-list');
        if (container?.dataset.parent) list = findEntity(container.dataset.parent)?.item.channels || list;
      }
      const targetIndex = target?.kind === 'channel' && target.list === list ? list.indexOf(target.item) : list.length;
      list.splice(Math.max(0, targetIndex), 0, source.item);
    }
    state.drag = null;
    state.diff = null;
    updatePositions();
    renderAll();
    schedulePreviewDiff();
  });
  els.tree.addEventListener('dragend', () => { state.drag = null; renderTree(); });

  els.permissionsBody.addEventListener('click', event => {
    const target = event.target.closest('[data-action="permission"]');
    if (!target || target.disabled) return;
    setPermission(target.dataset.key, target.dataset.role, target.dataset.column, target.dataset.value);
  });

  els.addCategory.addEventListener('click', addCategory);
  els.syncSelected.addEventListener('click', () => { if (state.selected) syncItem(state.selected); });
  els.undo.addEventListener('click', () => {
    const previous = state.history.pop();
    if (!previous) return;
    state.draft = previous.draft;
    state.selected = previous.selected;
    state.diff = null;
    renderAll();
    schedulePreviewDiff();
  });
  els.reset.addEventListener('click', () => {
    if (!window.confirm(tr('reset_confirm'))) return;
    state.draft = clone(state.initialDraft);
    state.history = [];
    state.selected = null;
    state.diff = null;
    renderAll();
    schedulePreviewDiff(50);
  });
  els.discard.addEventListener('click', () => {
    if (!window.confirm(tr('discard_confirm'))) return;
    state.draft = clone(state.initialDraft);
    state.history = [];
    state.selected = null;
    state.diff = null;
    renderAll();
    schedulePreviewDiff(50);
  });
  els.importLive.addEventListener('click', async () => {
    if (pendingCount() && !window.confirm(tr('import_confirm'))) return;
    await loadTree(false);
  });
  els.preset.addEventListener('change', loadSelectedTemplate);
  els.deleteTemplate.addEventListener('click', deleteTemplate);
  els.saveTemplate.addEventListener('click', () => openModal(els.templateModal));
  els.templateConfirm.addEventListener('click', saveTemplate);
  els.refreshDiff.addEventListener('click', () => previewDiff(false, false));
  els.reviewApply.addEventListener('click', () => previewDiff(true, false));
  els.safeMode.addEventListener('change', () => {
    if (els.safeMode.checked) {
      state.draft.categories.forEach(cat => {
        cat._deleted = false;
        cat.channels.forEach(ch => { ch._deleted = false; });
      });
      state.draft.uncategorized.forEach(ch => { ch._deleted = false; });
    }
    state.diff = null;
    renderAll();
    schedulePreviewDiff(0);
  });
  els.confirmDeletions.addEventListener('change', () => {
    els.applyConfirm.disabled = Boolean(state.diff?.summary?.has_deletions && !els.confirmDeletions.checked);
  });
  els.applyConfirm.addEventListener('click', applyDraft);
  els.cancelJob.addEventListener('click', cancelJob);
  els.reload.addEventListener('click', () => window.location.reload());
  els.closeProgress.addEventListener('click', () => { if (!state.activeJob) closeModal(els.progressModal); });
  document.addEventListener('click', event => {
    const close = event.target.closest('[data-close]');
    if (close) closeModal(byId(close.dataset.close));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const modal = document.querySelector('.sb-modal:not([hidden])');
      if (modal && modal !== els.progressModal) closeModal(modal);
    }
  });
  bindInspector();

  async function initialize() {
    await loadTemplates();
    await loadTree(true);
    if (state.activeJob && !state.pollTimer && !terminalStatuses.has(state.activeJob.status)) {
      attachJob(state.activeJob);
    }
  }
  initialize();
})();
