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
  const MAX_GUILD_ROLES = 250;
  const DEFAULT_ROLE_COLOR = '#99aab5';
  const PERMISSION_BITS = {
    0: 'create_instant_invite',
    1: 'kick_members',
    2: 'ban_members',
    3: 'administrator',
    4: 'manage_channels',
    5: 'manage_guild',
    6: 'add_reactions',
    7: 'view_audit_log',
    8: 'priority_speaker',
    9: 'stream',
    10: 'view_channel',
    11: 'send_messages',
    12: 'send_tts_messages',
    13: 'manage_messages',
    14: 'embed_links',
    15: 'attach_files',
    16: 'read_message_history',
    17: 'mention_everyone',
    18: 'use_external_emojis',
    19: 'view_guild_insights',
    20: 'connect',
    21: 'speak',
    22: 'mute_members',
    23: 'deafen_members',
    24: 'move_members',
    25: 'use_vad',
    26: 'change_nickname',
    27: 'manage_nicknames',
    28: 'manage_roles',
    29: 'manage_webhooks',
    30: 'manage_guild_expressions',
    31: 'use_application_commands',
    32: 'request_to_speak',
    33: 'manage_events',
    34: 'manage_threads',
    35: 'create_public_threads',
    36: 'create_private_threads',
    37: 'use_external_stickers',
    38: 'send_messages_in_threads',
    39: 'use_embedded_activities',
    40: 'moderate_members',
    41: 'view_creator_monetization_analytics',
    42: 'use_soundboard',
    43: 'create_guild_expressions',
    44: 'create_events',
    45: 'use_external_sounds',
    46: 'send_voice_messages',
    48: 'set_voice_channel_status',
    49: 'send_polls',
    50: 'use_external_apps',
    51: 'pin_messages',
    52: 'bypass_slowmode',
  };
  const PERMISSION_BIT_BY_NAME = Object.fromEntries(
    Object.entries(PERMISSION_BITS).map(([bit, name]) => [name, Number(bit)])
  );
  const PERMISSION_ALIASES = {
    read_messages: 'view_channel',
    use_voice_activation: 'use_vad',
    manage_expressions: 'manage_guild_expressions',
    manage_emojis: 'manage_guild_expressions',
    manage_emojis_and_stickers: 'manage_guild_expressions',
    create_expressions: 'create_guild_expressions',
    manage_permissions: 'manage_roles',
    external_emojis: 'use_external_emojis',
    external_stickers: 'use_external_stickers',
    create_polls: 'send_polls',
  };
  const DANGEROUS_PERMISSIONS = new Set([
    'administrator',
    'manage_guild',
    'manage_roles',
    'manage_channels',
    'ban_members',
    'kick_members',
    'manage_webhooks',
    'mention_everyone',
  ]);
  const ROLE_PERMISSION_GROUPS = [
    {
      key: 'perm_group_general',
      flags: [
        'administrator',
        'manage_guild',
        'manage_roles',
        'manage_channels',
        'manage_webhooks',
        'manage_guild_expressions',
        'create_guild_expressions',
        'view_audit_log',
        'view_guild_insights',
        'manage_events',
        'create_events',
        'view_creator_monetization_analytics',
        'use_external_apps',
      ],
    },
    {
      key: 'perm_group_membership',
      flags: [
        'create_instant_invite',
        'change_nickname',
        'manage_nicknames',
        'kick_members',
        'ban_members',
        'moderate_members',
      ],
    },
    {
      key: 'perm_group_text',
      flags: [
        'view_channel',
        'send_messages',
        'send_messages_in_threads',
        'create_public_threads',
        'create_private_threads',
        'embed_links',
        'attach_files',
        'add_reactions',
        'use_external_emojis',
        'use_external_stickers',
        'mention_everyone',
        'manage_messages',
        'pin_messages',
        'bypass_slowmode',
        'manage_threads',
        'read_message_history',
        'send_tts_messages',
        'use_application_commands',
        'send_voice_messages',
        'send_polls',
      ],
    },
    {
      key: 'perm_group_voice',
      flags: [
        'connect',
        'speak',
        'stream',
        'use_soundboard',
        'use_external_sounds',
        'use_vad',
        'priority_speaker',
        'mute_members',
        'deafen_members',
        'move_members',
        'use_embedded_activities',
        'request_to_speak',
        'set_voice_channel_status',
      ],
    },
  ];
  const ROLE_QUICK_PRESETS = [
    {
      id: 'mod',
      labelKey: 'role_preset_mod',
      flags: [
        'view_channel', 'kick_members', 'ban_members', 'moderate_members',
        'manage_messages', 'pin_messages', 'manage_threads', 'manage_nicknames',
        'mute_members', 'deafen_members', 'move_members', 'view_audit_log',
        'change_nickname', 'create_instant_invite', 'send_messages',
        'send_messages_in_threads', 'create_public_threads', 'embed_links',
        'attach_files', 'add_reactions', 'use_external_emojis',
        'use_external_stickers', 'read_message_history', 'connect', 'speak',
        'stream', 'use_vad', 'use_application_commands', 'send_polls',
        'send_voice_messages',
      ],
    },
    {
      id: 'staff',
      labelKey: 'role_preset_staff',
      flags: [
        'view_channel', 'moderate_members', 'manage_messages', 'pin_messages',
        'manage_threads', 'manage_nicknames', 'mute_members', 'move_members',
        'view_audit_log', 'change_nickname', 'create_instant_invite',
        'send_messages', 'send_messages_in_threads', 'create_public_threads',
        'embed_links', 'attach_files', 'add_reactions', 'use_external_emojis',
        'use_external_stickers', 'read_message_history', 'connect', 'speak',
        'stream', 'use_vad', 'use_application_commands', 'send_polls',
        'send_voice_messages',
      ],
    },
    {
      id: 'vip',
      labelKey: 'role_preset_vip',
      flags: [
        'view_channel', 'create_instant_invite', 'change_nickname',
        'send_messages', 'send_messages_in_threads', 'create_public_threads',
        'embed_links', 'attach_files', 'add_reactions', 'use_external_emojis',
        'use_external_stickers', 'read_message_history', 'connect', 'speak',
        'stream', 'use_vad', 'use_application_commands', 'send_polls',
        'send_voice_messages', 'priority_speaker', 'use_soundboard',
        'use_external_sounds', 'use_embedded_activities',
      ],
    },
    {
      id: 'member',
      labelKey: 'role_preset_member',
      flags: [
        'view_channel', 'create_instant_invite', 'change_nickname',
        'send_messages', 'send_messages_in_threads', 'create_public_threads',
        'embed_links', 'attach_files', 'add_reactions', 'use_external_emojis',
        'use_external_stickers', 'read_message_history', 'connect', 'speak',
        'stream', 'use_vad', 'use_application_commands', 'send_polls',
        'send_voice_messages',
      ],
    },
    {
      id: 'muted',
      labelKey: 'role_preset_muted',
      flags: ['view_channel', 'read_message_history'],
    },
    {
      id: 'clear',
      labelKey: 'role_preset_clear',
      flags: [],
    },
  ];
  const DISCORD_ROLE_SWATCHES = [
    '#99aab5', '#1abc9c', '#2ecc71', '#3498db', '#9b59b6',
    '#e91e63', '#f1c40f', '#e67e22', '#e74c3c', '#95a5a6',
    '#607d8b', '#11806a', '#1f8b4c', '#206694', '#71368a',
    '#ad1457', '#c27c0e', '#a84300', '#7c6cf0', '#ff8a9b',
  ];
  const ROLE_BIND_MODULES = new Set([
    'autoroles_user',
    'verify_verified',
    'verify_pending',
    'automod_immune',
  ]);
  const ROLE_BIND_MODULE_ALIASES = {
    autoroles_user: 'autoroles_user',
    autorole_user: 'autoroles_user',
    verify_verified: 'verify_verified',
    verify_verified_role: 'verify_verified',
    verify_pending: 'verify_pending',
    verify_pending_role: 'verify_pending',
    automod_immune: 'automod_immune',
    automod_immune_role: 'automod_immune',
  };

  const state = {
    live: null,
    draft: { categories: [], uncategorized: [], roles: [], bindings: {} },
    initialDraft: null,
    roles: [],
    templates: { system: [], custom: [] },
    currentPresetValue: 'community_4cat',
    activeTab: 'channels',
    roleSearch: '',
    permSearch: '',
    openPermGroups: new Set(['perm_group_general', 'perm_group_membership']),
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
    undo: byId('sb-undo'), reset: byId('sb-reset'),
    tabChannels: byId('sb-tab-channels'), tabRoles: byId('sb-tab-roles'),
    tree: byId('sb-tree'), count: byId('sb-channel-count'),
    rolePanel: byId('sb-role-panel'), roleCount: byId('sb-role-count'), roleSearch: byId('sb-role-search'),
    roleList: byId('sb-role-list'), addCategory: byId('sb-add-category'), addRole: byId('sb-add-role'),
    mobileBack: byId('sb-mobile-back'),
    inspectorEmpty: byId('sb-inspector-empty'), inspector: byId('sb-inspector'),
    kind: byId('sb-kind'), roleLockBanner: byId('sb-role-lock-banner'), roleLockText: byId('sb-role-lock-text'),
    name: byId('sb-name'), sanitizeWrap: byId('sb-sanitize-wrap'), sanitize: byId('sb-sanitized-preview'),
    typeWrap: byId('sb-type-wrap'), type: byId('sb-channel-type'), newsHint: byId('sb-news-hint'),
    parentWrap: byId('sb-parent-wrap'), parent: byId('sb-parent'),
    topicWrap: byId('sb-topic-wrap'), topic: byId('sb-topic'), slowmodeWrap: byId('sb-slowmode-wrap'), slowmode: byId('sb-slowmode'),
    nsfwWrap: byId('sb-nsfw-wrap'), nsfw: byId('sb-nsfw'), voiceWrap: byId('sb-voice-wrap'), bitrate: byId('sb-bitrate'),
    userLimit: byId('sb-user-limit'), moduleWrap: byId('sb-module-wrap'), module: byId('sb-module'), syncSelected: byId('sb-sync-selected'),
    botViewWarning: byId('sb-bot-view-warning'), channelPermissionsSec: byId('sb-channel-permissions-sec'),
    permissionsBody: byId('sb-permissions-body'),
    roleInspector: byId('sb-role-inspector'), roleColorSection: byId('sb-role-color-section'),
    roleColorPicker: byId('sb-role-color-picker'), roleColorHex: byId('sb-role-color-hex'),
    roleColorReset: byId('sb-role-color-reset'), roleSwatches: byId('sb-role-swatches'),
    roleFlagsSection: byId('sb-role-flags-section'), roleHoist: byId('sb-role-hoist'), roleMentionable: byId('sb-role-mentionable'),
    roleModuleWrap: byId('sb-role-module-wrap'), roleModule: byId('sb-role-module'),
    roleQuickPresetsWrap: byId('sb-role-quick-presets-wrap'), roleQuickPresets: byId('sb-role-quick-presets'),
    rolePermMatrix: byId('sb-role-perm-matrix'), permSearch: byId('sb-perm-search'),
    roleAdminWarning: byId('sb-role-admin-warning'), rolePermGroups: byId('sb-role-perm-groups'),
    roleUsageSection: byId('sb-role-usage-section'), roleUsageChips: byId('sb-role-usage-chips'),
    diffSummary: byId('sb-diff-summary'), refreshDiff: byId('sb-refresh-diff'),
    pendingCount: byId('sb-pending-count'), eta: byId('sb-eta'), discard: byId('sb-discard'),
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

  function normalizeRoleBindModule(val) {
    const clean = normalizeBindModule(val);
    if (!clean) return null;
    const canonical = ROLE_BIND_MODULE_ALIASES[clean] || clean;
    return ROLE_BIND_MODULES.has(canonical) ? canonical : null;
  }

  function normalizeRoleColorHex(value) {
    if (typeof value === 'number') {
      const num = Number.isFinite(value) && value > 0 ? (Math.trunc(value) & 0xffffff) : 0;
      const hex = num ? `#${num.toString(16).padStart(6, '0')}` : DEFAULT_ROLE_COLOR;
      return hex === '#000000' ? DEFAULT_ROLE_COLOR : hex;
    }
    const text = String(value || '').trim();
    if (!text) return DEFAULT_ROLE_COLOR;
    const hex6 = /^#?([0-9a-fA-F]{6})$/.exec(text);
    if (hex6) {
      const low = `#${hex6[1].toLowerCase()}`;
      return (low === '#000000' || low === DEFAULT_ROLE_COLOR) ? DEFAULT_ROLE_COLOR : low;
    }
    const hex3 = /^#([0-9a-fA-F]{3})$/.exec(text);
    if (hex3) {
      const expanded = `#${hex3[1].split('').map(c => c + c).join('').toLowerCase()}`;
      return (expanded === '#000000' || expanded === DEFAULT_ROLE_COLOR) ? DEFAULT_ROLE_COLOR : expanded;
    }
    if (/^\d+$/.test(text)) {
      const num = Number(text) & 0xffffff;
      const hex = num ? `#${num.toString(16).padStart(6, '0')}` : DEFAULT_ROLE_COLOR;
      return hex === '#000000' ? DEFAULT_ROLE_COLOR : hex;
    }
    return DEFAULT_ROLE_COLOR;
  }

  function parseRoleColor(value) {
    if (typeof value === 'number') {
      const num = Number.isFinite(value) && value > 0 ? (Math.trunc(value) & 0xffffff) : 0;
      return { intVal: num, css: num ? `#${num.toString(16).padStart(6, '0')}` : DEFAULT_ROLE_COLOR };
    }
    const text = String(value || '').trim();
    const hexMatch = /^#?([0-9a-fA-F]{6})$/.exec(text);
    if (hexMatch) {
      const low = hexMatch[1].toLowerCase();
      if (low === '000000' || low === '99aab5') {
        return { intVal: 0, css: DEFAULT_ROLE_COLOR };
      }
      const num = parseInt(low, 16);
      return { intVal: num, css: `#${low}` };
    }
    const hex3Match = /^#([0-9a-fA-F]{3})$/.exec(text);
    if (hex3Match) {
      const expanded = hex3Match[1].split('').map(c => c + c).join('').toLowerCase();
      if (expanded === '000000') return { intVal: 0, css: DEFAULT_ROLE_COLOR };
      return { intVal: parseInt(expanded, 16), css: `#${expanded}` };
    }
    if (/^\d+$/.test(text)) {
      const num = Number(text) & 0xffffff;
      return { intVal: num, css: num ? `#${num.toString(16).padStart(6, '0')}` : DEFAULT_ROLE_COLOR };
    }
    return { intVal: 0, css: DEFAULT_ROLE_COLOR };
  }

  function normalizePermissionList(value) {
    const names = new Set();
    const addName = raw => {
      const cleaned = String(raw || '').trim();
      if (!cleaned) return;
      const canonical = PERMISSION_ALIASES[cleaned] || cleaned;
      if (Object.prototype.hasOwnProperty.call(PERMISSION_BIT_BY_NAME, canonical) || /^bit_\d+$/.test(canonical)) {
        names.add(canonical);
      }
    };
    if (Array.isArray(value)) {
      value.forEach(addName);
    } else if (typeof value === 'string' && value.includes(',')) {
      value.split(',').forEach(addName);
    } else if (value && typeof value === 'object') {
      Object.entries(value).forEach(([k, enabled]) => {
        if (enabled) addName(k);
      });
    } else if (
      typeof value === 'bigint'
      || typeof value === 'number'
      || (typeof value === 'string' && /^\d+$/.test(value.trim()))
    ) {
      try {
        const rawInt = typeof value === 'bigint'
          ? value
          : BigInt(typeof value === 'number' ? Math.max(0, Math.trunc(value)) : value.trim());
        const bits = rawInt > 0n ? rawInt : 0n;
        if (bits > 0n) {
          for (let b = 0; b < 64; b += 1) {
            if ((bits & (1n << BigInt(b))) !== 0n) {
              names.add(PERMISSION_BITS[b] || `bit_${b}`);
            }
          }
        }
      } catch (error) { /* ignore invalid bitfield */ }
    }
    return [...names].sort();
  }

  function compactRole(role) {
    const isEveryone = Boolean(role.is_everyone || role.name === '@everyone' || role.id === '@everyone');
    return {
      id: isEveryone ? '@everyone' : (role.id || null),
      temp_id: isEveryone ? null : (role.temp_id || null),
      name: isEveryone ? '@everyone' : String(role.name || ''),
      color: isEveryone ? DEFAULT_ROLE_COLOR : normalizeRoleColorHex(role.color !== undefined ? role.color : role.color_hex),
      position: isEveryone ? 0 : Number(role.position || 0),
      permissions: normalizePermissionList(role.permissions),
      hoist: isEveryone ? false : Boolean(role.hoist),
      mentionable: isEveryone ? false : Boolean(role.mentionable),
      managed: Boolean(role.managed),
      is_everyone: isEveryone,
      bind_role_module: isEveryone || role.managed ? null : normalizeRoleBindModule(role.bind_role_module),
    };
  }

  function normalizeRoleEntry(role) {
    const isEveryone = Boolean(role.is_everyone || role.name === '@everyone' || role.id === '@everyone');
    const rawId = role.id !== null && role.id !== undefined ? String(role.id).trim() : '';
    const cleanId = isEveryone ? '@everyone' : ((rawId && rawId !== 'null' && rawId !== 'undefined') ? rawId : null);
    let tempId = isEveryone ? null : (role.temp_id ? String(role.temp_id) : null);
    if (!cleanId && !tempId) {
      tempId = typeof newTemp === 'function'
        ? newTemp('role')
        : `tmp_role_${Date.now().toString(36)}_${(state.tempIndex = (state.tempIndex || 0) + 1)}`;
    }
    const rawColor = role.color !== undefined ? role.color : role.color_hex;
    const rawPerms = role.permissions !== undefined && role.permissions !== null ? role.permissions : role.permission_bits;
    const entry = {
      id: cleanId,
      temp_id: tempId,
      name: isEveryone ? '@everyone' : String(role.name || tr('new_role')),
      color: isEveryone ? DEFAULT_ROLE_COLOR : normalizeRoleColorHex(rawColor),
      position: isEveryone ? 0 : Number(role.position || 0),
      permissions: normalizePermissionList(rawPerms),
      hoist: isEveryone ? false : Boolean(role.hoist),
      mentionable: isEveryone ? false : Boolean(role.mentionable),
      managed: Boolean(role.managed),
      is_everyone: isEveryone,
      bind_role_module: isEveryone || role.managed ? null : normalizeRoleBindModule(role.bind_role_module),
      _cache_readonly: Boolean(role._cache_readonly),
      _deleted: isEveryone || role.managed ? false : Boolean(role._deleted),
    };
    entry._original = role._original !== undefined
      ? role._original
      : (cleanId ? JSON.stringify(compactRole(entry)) : null);
    return entry;
  }

  function mergedRoles(opts = {}) {
    const includeDeleted = Boolean(opts && opts.includeDeleted);
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
      if (!includeDeleted && entry._deleted) return;
      result.push(entry);
    };

    (state.draft.roles || []).forEach(addRole);
    (state.roles || []).forEach(addRole);
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

  function buildRoleBindingReverseMap(raw) {
    const byTarget = {};
    const collect = obj => {
      if (!obj || typeof obj !== 'object') return;
      Object.entries(obj).forEach(([k, v]) => {
        const canonical = normalizeRoleBindModule(k);
        const ref = v === null || v === undefined ? '' : String(v).trim();
        if (canonical && ref && ref !== 'none' && ref !== 'null' && !byTarget[ref]) {
          byTarget[ref] = canonical;
        }
      });
    };
    collect(raw?.bindings);
    collect(raw?.role_bindings);
    if (!Object.keys(byTarget).length && state.live?.bindings) {
      collect(state.live.bindings);
    }
    return byTarget;
  }

  function mergeRolesForTree(raw) {
    const reverseBind = buildRoleBindingReverseMap(raw);
    const liveRoles = (Array.isArray(state.roles) ? state.roles : []).map(r => {
      const entry = normalizeRoleEntry(r);
      const refKey = entry.id || entry.temp_id;
      if (!entry.bind_role_module && refKey && reverseBind[refKey]) {
        entry.bind_role_module = reverseBind[refKey];
        if (entry.id) entry._original = JSON.stringify(compactRole(entry));
      }
      return entry;
    });
    const rawRoles = Array.isArray(raw?.roles) ? raw.roles.map(r => {
      const entry = normalizeRoleEntry(r);
      const refKey = entry.id || entry.temp_id;
      if (!entry.bind_role_module && refKey && reverseBind[refKey]) {
        entry.bind_role_module = reverseBind[refKey];
        if (entry.id && r._original === undefined) entry._original = JSON.stringify(compactRole(entry));
      }
      return entry;
    }) : [];

    if (!liveRoles.length) return rawRoles;
    if (!rawRoles.length) return liveRoles;

    const merged = liveRoles.map(r => clone(r));
    const matchedLiveIndexes = new Set();
    const ceiling = typeof effectiveRoleCeiling === 'function' ? effectiveRoleCeiling() : Infinity;
    const isLiveLocked = entry => Boolean(entry.managed) || (Boolean(entry.id) && Number.isFinite(ceiling) && Number(entry.position) >= ceiling);

    rawRoles.forEach(target => {
      if (target.is_everyone) {
        const evIdx = merged.findIndex(r => r.is_everyone);
        if (evIdx !== -1) {
          matchedLiveIndexes.add(evIdx);
          if (target.permissions.length || target.id === '@everyone') {
            merged[evIdx].permissions = clone(target.permissions);
          }
          if (target._original !== undefined) merged[evIdx]._original = target._original;
        } else {
          merged.push(target);
        }
        return;
      }

      let idx = target.id ? merged.findIndex((r, i) => !matchedLiveIndexes.has(i) && r.id === target.id) : -1;
      if (idx === -1 && !target.id) {
        const lowerName = target.name.trim().toLowerCase();
        idx = merged.findIndex((r, i) => (
          !matchedLiveIndexes.has(i)
          && !r.is_everyone
          && !isLiveLocked(r)
          && r.name.trim().toLowerCase() === lowerName
        ));
      }

      if (idx !== -1) {
        matchedLiveIndexes.add(idx);
        const curr = merged[idx];
        if (isLiveLocked(curr)) return;
        if (target.bind_role_module) {
          merged.forEach((other, j) => {
            if (j !== idx && other.bind_role_module === target.bind_role_module && !isLiveLocked(other)) {
              other.bind_role_module = null;
            }
          });
        }
        merged[idx] = {
          ...curr,
          temp_id: target.temp_id || curr.temp_id || null,
          name: target.name,
          color: target.color,
          hoist: target.hoist,
          mentionable: target.mentionable,
          permissions: clone(target.permissions),
          position: target.id ? target.position : curr.position,
          bind_role_module: target.bind_role_module,
          _deleted: Boolean(target._deleted),
          _original: curr._original || target._original,
        };
      } else {
        if (!target.id && Number.isFinite(ceiling) && ceiling > 1 && target.position >= ceiling) {
          target.position = ceiling - 1;
        }
        if (target.bind_role_module) {
          merged.forEach(other => {
            if (other.bind_role_module === target.bind_role_module && !isLiveLocked(other)) {
              other.bind_role_module = null;
            }
          });
        }
        merged.push(target);
      }
    });

    return merged;
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
      roles: mergeRolesForTree(raw),
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

  function cleanBindings(activeChannels, activeRoles = []) {
    const activeChannelRefs = new Set();
    activeChannels.forEach(ch => {
      if (ch.id) activeChannelRefs.add(String(ch.id));
      if (ch.temp_id) activeChannelRefs.add(String(ch.temp_id));
    });
    const activeRoleRefs = new Set();
    activeRoles.forEach(role => {
      if (role.is_everyone) return;
      if (role.id) activeRoleRefs.add(String(role.id));
      if (role.temp_id) activeRoleRefs.add(String(role.temp_id));
    });
    const out = {};
    const raw = state.draft.bindings && typeof state.draft.bindings === 'object' ? state.draft.bindings : {};
    Object.entries(raw).forEach(([modKey, targetRef]) => {
      const cleanKey = normalizeBindModule(modKey);
      const refStr = targetRef === null || targetRef === undefined ? '' : String(targetRef).trim();
      if (!cleanKey || !refStr || refStr === 'none' || refStr === 'null') return;
      const roleKey = normalizeRoleBindModule(cleanKey);
      if (roleKey) {
        if (!activeRoleRefs.has(refStr)) return;
        out[roleKey] = refStr;
      } else {
        if (!activeChannelRefs.has(refStr)) return;
        out[cleanKey] = refStr;
      }
    });
    activeChannels.forEach(ch => {
      const bm = normalizeBindModule(ch.bind_module);
      if (bm && !out[bm]) {
        out[bm] = entityKey(ch);
      }
    });
    activeRoles.forEach(role => {
      if (role.is_everyone || role.managed) return;
      const bm = normalizeRoleBindModule(role.bind_role_module);
      if (bm) {
        out[bm] = entityKey(role);
      }
    });
    return out;
  }

  function compactTree() {
    const activeCats = state.draft.categories.filter(cat => !cat._deleted);
    const activeUncat = state.draft.uncategorized.filter(ch => !ch._deleted);
    const activeChannels = [...activeCats.flatMap(cat => cat.channels.filter(ch => !ch._deleted)), ...activeUncat];
    const activeRoles = mergedRoles({ includeDeleted: false });
    return {
      categories: activeCats.map(cat => compactCategory(cat, true)),
      uncategorized: activeUncat.map(compactChannel),
      roles: activeRoles.map(compactRole),
      bindings: cleanBindings(activeChannels, activeRoles),
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

  function allRoles() {
    return mergedRoles({ includeDeleted: true });
  }

  function findEntity(key) {
    if (!key) return null;
    for (const category of state.draft.categories) {
      if (entityKey(category) === key) return { kind: 'category', item: category, parent: null, list: state.draft.categories };
      const child = category.channels.find(ch => entityKey(ch) === key);
      if (child) return { kind: 'channel', item: child, parent: category, list: category.channels };
    }
    const child = state.draft.uncategorized.find(ch => entityKey(ch) === key);
    if (child) return { kind: 'channel', item: child, parent: null, list: state.draft.uncategorized };
    const draftRole = (state.draft.roles || []).find(r => (
      entityKey(r) === key || (Boolean(r.is_everyone || r.name === '@everyone') && key === '@everyone')
    ));
    if (draftRole) return { kind: 'role', item: draftRole, parent: null, list: state.draft.roles };
    const liveRole = (state.roles || []).find(r => (
      entityKey(r) === key || (Boolean(r.is_everyone || r.name === '@everyone') && key === '@everyone')
    ));
    if (liveRole) return { kind: 'role', item: normalizeRoleEntry(liveRole), parent: null, list: state.draft.roles };
    return null;
  }

  function ensureSelection() {
    const found = state.selected ? findEntity(state.selected) : null;
    if (state.activeTab === 'roles') {
      if (found && found.kind === 'role') return;
      const sorted = sortedRolesList(allRoles());
      const preferred = sorted.find(r => !r.is_everyone && !r._deleted) || sorted[0] || null;
      state.selected = preferred ? entityKey(preferred) : null;
      return;
    }
    if (found && (found.kind === 'category' || found.kind === 'channel')) return;
    if (state.draft.categories.length) state.selected = entityKey(state.draft.categories[0]);
    else if (state.draft.uncategorized.length) state.selected = entityKey(state.draft.uncategorized[0]);
    else state.selected = null;
  }

  function snapshot() {
    state.history.push({ draft: clone(state.draft), selected: state.selected, activeTab: state.activeTab });
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

  function updateRolePositions(force = false) {
    if (!force || !Array.isArray(state.draft.roles)) return;
    const ceiling = typeof effectiveRoleCeiling === 'function' ? effectiveRoleCeiling() : Infinity;
    const isMovable = role => (
      role
      && !role.is_everyone
      && role.name !== '@everyone'
      && role.id !== '@everyone'
      && !role._deleted
      && !role.managed
      && !(Boolean(role.id) && Number.isFinite(ceiling) && Number(role.position) >= ceiling)
    );

    const occupiedFixed = new Set();
    state.draft.roles.forEach(role => {
      if (role.is_everyone || role.name === '@everyone' || role.id === '@everyone') {
        role.position = 0;
        return;
      }
      if (!isMovable(role) && !role._deleted) {
        occupiedFixed.add(Number(role.position || 0));
      }
    });

    const movable = state.draft.roles.filter(isMovable);
    if (!movable.length) return;

    const maxBound = Number.isFinite(ceiling) ? Math.max(1, ceiling - 1) : Infinity;
    const existingPool = movable
      .map(r => Number(r.position || 0))
      .filter(p => p >= 1 && p < ceiling && !occupiedFixed.has(p));

    const uniqueValid = [...new Set(existingPool)].sort((a, b) => b - a);
    if (uniqueValid.length === movable.length) {
      movable.forEach((role, idx) => { role.position = uniqueValid[idx]; });
      return;
    }

    const available = [];
    const upper = Number.isFinite(maxBound) ? maxBound : Math.max(movable.length + occupiedFixed.size + 5, 50);
    for (let p = upper; p >= 1 && available.length < movable.length; p -= 1) {
      if (!occupiedFixed.has(p)) available.push(p);
    }
    if (available.length < movable.length) {
      let nextPos = upper + 1;
      while (available.length < movable.length) {
        if (!occupiedFixed.has(nextPos)) available.unshift(nextPos);
        nextPos += 1;
      }
    }
    movable.forEach((role, idx) => { role.position = available[idx]; });
  }

  function updatePositions(reorderRoles = false) {
    state.draft.categories.forEach((cat, catIndex) => {
      cat.position = catIndex;
      const parentId = entityKey(cat);
      cat.channels.forEach((ch, index) => { ch.position = index; ch.parent_id = parentId; });
    });
    state.draft.uncategorized.forEach((ch, index) => { ch.position = index; ch.parent_id = null; });
    if (reorderRoles) updateRolePositions(true);
  }

  function isModified(item, kind) {
    if (!item.id) return true;
    if (item._deleted) return false;
    let now;
    if (kind === 'category') now = compactCategory(item, false);
    else if (kind === 'role') now = compactRole(item);
    else now = compactChannel(item);
    return item._original !== JSON.stringify(now);
  }

  function pendingCount() {
    let total = 0;
    state.draft.categories.forEach(cat => {
      if (!cat.id || cat._deleted || isModified(cat, 'category')) total += 1;
      cat.channels.forEach(ch => { if (!ch.id || ch._deleted || isModified(ch, 'channel')) total += 1; });
    });
    state.draft.uncategorized.forEach(ch => { if (!ch.id || ch._deleted || isModified(ch, 'channel')) total += 1; });
    (state.draft.roles || []).forEach(role => { if (!role.id || role._deleted || isModified(role, 'role')) total += 1; });
    return total;
  }

  function everyoneRoleId() {
    const found = mergedRoles().find(r => r.is_everyone || r.name === '@everyone');
    return found && found.id ? String(found.id) : null;
  }

  function effectiveRoleCeiling() {
    const botTop = state.live?.bot_top_role_pos != null ? Number(state.live.bot_top_role_pos) : Infinity;
    const isOwner = Boolean(state.live?.is_guild_owner || state.live?.user_permissions?.is_owner);
    const userTop = (!isOwner && state.live?.user_top_role_pos != null) ? Number(state.live.user_top_role_pos) : Infinity;
    return Math.min(botTop, userTop);
  }

  function permissionSetFromRaw(perms) {
    if (!perms || typeof perms !== 'object' && !Array.isArray(perms) && typeof perms !== 'string' && typeof perms !== 'number') {
      return null;
    }
    const set = new Set();
    if (Array.isArray(perms) || typeof perms === 'string' || typeof perms === 'number') {
      normalizePermissionList(perms).forEach(flag => set.add(flag));
      return set;
    }
    if (Array.isArray(perms.granted)) {
      normalizePermissionList(perms.granted).forEach(flag => set.add(flag));
    }
    if (perms.bitfield !== undefined && perms.bitfield !== null) {
      normalizePermissionList(perms.bitfield).forEach(flag => set.add(flag));
    }
    Object.entries(perms).forEach(([k, v]) => {
      if (v === true && Object.prototype.hasOwnProperty.call(PERMISSION_BIT_BY_NAME, k)) {
        set.add(k);
      }
    });
    return set;
  }

  function isRoleHierarchyLocked(role) {
    if (!role) return false;
    const isEveryone = Boolean(role.is_everyone || role.name === '@everyone' || role.id === '@everyone');
    if (isEveryone || !role.id) return false;
    const ceiling = effectiveRoleCeiling();
    return Number.isFinite(ceiling) && Number(role.position) >= ceiling;
  }

  function isRoleInspectorLocked(role) {
    if (!role) return true;
    if (state.live?.live_source === 'cache' || role._cache_readonly) return true;
    if (role.managed) return true;
    return isRoleHierarchyLocked(role);
  }

  function canEditPermissionFlag(role, flag) {
    if (!role || role._deleted) return false;
    if (isRoleInspectorLocked(role)) return false;
    if (state.live?.bot_permissions) {
      const botSet = permissionSetFromRaw(state.live.bot_permissions);
      const botAdmin = Boolean(state.live.bot_permissions.administrator || botSet?.has('administrator'));
      const botManageRoles = botAdmin || Boolean(state.live.bot_permissions.manage_roles || botSet?.has('manage_roles'));
      if (!botManageRoles) return false;
      if (!botAdmin && botSet && !botSet.has(flag)) return false;
    }
    if (state.live?.user_permissions) {
      const isOwner = Boolean(state.live.is_guild_owner || state.live.user_permissions.is_owner);
      if (!isOwner) {
        const userSet = permissionSetFromRaw(state.live.user_permissions);
        const userAdmin = Boolean(state.live.user_permissions.administrator || userSet?.has('administrator'));
        const userManageRoles = userAdmin || Boolean(state.live.user_permissions.manage_roles || userSet?.has('manage_roles'));
        if (!userManageRoles) return false;
        if (!userAdmin && userSet && !userSet.has(flag)) return false;
      }
    }
    return true;
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

  function sortedRolesList(roles) {
    return (roles || []).slice().sort((a, b) => {
      const aEv = Boolean(a.is_everyone || a.name === '@everyone');
      const bEv = Boolean(b.is_everyone || b.name === '@everyone');
      if (aEv !== bEv) return aEv ? 1 : -1;
      const posDiff = Number(b.position || 0) - Number(a.position || 0);
      if (posDiff !== 0) return posDiff;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
  }

  function roleLockReason(role) {
    if (state.live?.live_source === 'cache' || role._cache_readonly) return tr('role_locked_cache');
    if (role.managed) return tr('role_locked_managed');
    const isOwner = Boolean(state.live?.is_guild_owner || state.live?.user_permissions?.is_owner);
    const botTop = state.live?.bot_top_role_pos != null ? Number(state.live.bot_top_role_pos) : Infinity;
    const userTop = (!isOwner && state.live?.user_top_role_pos != null) ? Number(state.live.user_top_role_pos) : Infinity;
    if (Boolean(role.id) && Number.isFinite(userTop) && Number(role.position) >= userTop && Number(role.position) < botTop) {
      return tr('role_locked_user');
    }
    return tr('role_locked');
  }

  function permLockReason(role, flag) {
    if (isRoleInspectorLocked(role)) return roleLockReason(role);
    if (state.live?.bot_permissions) {
      const botSet = permissionSetFromRaw(state.live.bot_permissions);
      const botAdmin = Boolean(state.live.bot_permissions.administrator || botSet?.has('administrator'));
      const botManageRoles = botAdmin || Boolean(state.live.bot_permissions.manage_roles || botSet?.has('manage_roles'));
      if (!botManageRoles || (!botAdmin && botSet && !botSet.has(flag))) return tr('perm_locked_bot');
    }
    return tr('perm_locked_user');
  }

  function roleOverwriteTargets(role) {
    const key = entityKey(role);
    const evId = role.is_everyone ? everyoneRoleId() : null;
    const matches = [];
    const check = (item, kind) => {
      if (item._deleted) return;
      const hit = (item.overwrites || []).some(ow => {
        if ((ow.type || 'role') !== 'role') return false;
        const idStr = String(ow.id);
        return idStr === key || (role.is_everyone && idStr === '@everyone') || (evId && idStr === evId);
      });
      if (hit) matches.push({ kind, item, key: entityKey(item) });
    };
    state.draft.categories.forEach(cat => {
      check(cat, 'category');
      cat.channels.forEach(ch => check(ch, 'channel'));
    });
    state.draft.uncategorized.forEach(ch => check(ch, 'channel'));
    return matches;
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

  function renderRoleRow(role, movableMeta) {
    const key = entityKey(role);
    const isEveryone = Boolean(role.is_everyone || role.name === '@everyone');
    const isLocked = isRoleInspectorLocked(role);
    const isSelected = state.selected === key;
    const filtering = Boolean(state.roleSearch.trim());
    const canMove = !filtering && !isEveryone && !isLocked && !role._deleted;
    const row = node(
      'div',
      `sb-role-row${role._deleted ? ' is-deleted' : ''}${isSelected ? ' is-selected' : ''}${isLocked ? ' is-locked' : ''}${isEveryone ? ' is-everyone' : ''}`
    );
    row.dataset.key = key;
    row.dataset.kind = 'role';
    row.draggable = canMove;

    const drag = node('span', `sb-drag${canMove ? '' : ' is-disabled'}`, '⠿');
    const pos = node('span', 'sb-role-pos', `#${Number(role.position || 0)}`);
    const dot = node('span', 'sb-role-dot');
    const safeColor = normalizeRoleColorHex(role.color);
    if (/^#[0-9a-f]{6}$/i.test(safeColor)) dot.style.backgroundColor = safeColor;

    const name = node('button', 'sb-entity-name', role.name);
    name.type = 'button';
    name.dataset.action = 'select';
    name.dataset.key = key;

    row.append(drag, pos, dot, name);

    const badges = node('div', 'sb-role-badges');
    if (role.managed) badges.append(node('span', 'sb-mini-badge sb-badge-managed', tr('role_badge_bot')));
    if (isLocked) {
      const lock = node('span', 'sb-role-lock', '🔒');
      lock.title = roleLockReason(role);
      badges.append(lock);
    }
    if ((role.permissions || []).includes('administrator')) {
      badges.append(node('span', 'sb-mini-badge sb-badge-danger', 'ADMIN'));
    }
    if (role.hoist) badges.append(node('span', 'sb-mini-badge sb-badge-hoist', tr('role_badge_hoist')));
    if (role.mentionable) badges.append(node('span', 'sb-mini-badge sb-badge-mention', '@'));
    if (role.bind_role_module) {
      badges.append(node('span', 'sb-mini-badge sb-badge-module', tr(`role_module_short_${role.bind_role_module}`, role.bind_role_module)));
    }
    const owCount = roleOverwriteTargets(role).length;
    if (owCount > 0) {
      const owBadge = node('span', 'sb-cat-count', `${owCount} #`);
      owBadge.title = tr('role_overwrites_used');
      badges.append(owBadge);
    }
    const pill = statusPill(role, 'role');
    if (pill) badges.append(pill);
    row.append(badges);

    const actions = node('div', 'sb-row-actions');
    const movableIdx = movableMeta.indexByKey.get(key);
    const upBtn = actionIcon('↑', tr('move_up'), 'role-up', key);
    upBtn.disabled = !canMove || movableIdx === undefined || movableIdx <= 0;
    const downBtn = actionIcon('↓', tr('move_down'), 'role-down', key);
    downBtn.disabled = !canMove || movableIdx === undefined || movableIdx >= movableMeta.count - 1;
    actions.append(upBtn, downBtn);

    const canDelete = !isEveryone && !role.managed && !isRoleHierarchyLocked(role) && !(state.live?.live_source === 'cache' || role._cache_readonly);
    if (canDelete) {
      actions.append(actionIcon(role._deleted ? '↩' : '×', role._deleted ? tr('restore') : tr('delete'), 'delete', key));
    }
    row.append(actions);
    return row;
  }

  function renderRoles() {
    const allSorted = sortedRolesList(allRoles());
    const activeCount = allSorted.filter(r => !r._deleted).length;
    els.roleCount.textContent = `${activeCount} / ${MAX_GUILD_ROLES}`;
    els.roleCount.classList.toggle('is-danger', activeCount > MAX_GUILD_ROLES);

    const ceiling = effectiveRoleCeiling();
    const movableOrder = allSorted.filter(r => !r.is_everyone && !r._deleted && !isRoleInspectorLocked(r));
    const movableMeta = {
      count: movableOrder.length,
      indexByKey: new Map(movableOrder.map((r, idx) => [entityKey(r), idx])),
    };

    const query = state.roleSearch.trim().toLowerCase();
    const visible = query
      ? allSorted.filter(r => String(r.name || '').toLowerCase().includes(query))
      : allSorted;

    const aboveCeiling = [];
    const belowCeiling = [];
    const everyoneRows = [];
    visible.forEach(role => {
      if (role.is_everyone || role.name === '@everyone') {
        everyoneRows.push(role);
      } else if (Boolean(role.id) && Number.isFinite(ceiling) && Number(role.position) >= ceiling) {
        aboveCeiling.push(role);
      } else {
        belowCeiling.push(role);
      }
    });

    const fragment = document.createDocumentFragment();
    aboveCeiling.forEach(role => fragment.append(renderRoleRow(role, movableMeta)));
    if (aboveCeiling.length && (belowCeiling.length || everyoneRows.length)) {
      const divider = node('div', 'sb-role-ceiling-divider');
      const pill = node('span', 'sb-role-ceiling-pill');
      pill.append(document.createTextNode(`🔒 ${tr('role_ceiling_divider')}`));
      divider.append(pill);
      fragment.append(divider);
    }
    belowCeiling.forEach(role => fragment.append(renderRoleRow(role, movableMeta)));
    everyoneRows.forEach(role => fragment.append(renderRoleRow(role, movableMeta)));
    if (!visible.length) {
      fragment.append(node('div', 'sb-empty', tr('diff_empty')));
    }
    els.roleList.replaceChildren(fragment);
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

  function renderRolePermissionGroups(role) {
    const permSet = new Set(normalizePermissionList(role.permissions));
    const search = state.permSearch.trim().toLowerCase();
    const frag = document.createDocumentFragment();
    els.roleAdminWarning.hidden = !permSet.has('administrator');

    ROLE_PERMISSION_GROUPS.forEach(group => {
      const matchingFlags = group.flags.filter(flag => {
        if (!search) return true;
        const label = tr(`perm_${flag}`, flag).toLowerCase();
        return label.includes(search) || flag.toLowerCase().includes(search);
      });
      if (!matchingFlags.length) return;

      const details = node('details', 'sb-perm-group');
      details.dataset.group = group.key;
      details.open = Boolean(search) || state.openPermGroups.has(group.key);
      details.addEventListener('toggle', () => {
        if (search) return;
        if (details.open) state.openPermGroups.add(group.key);
        else state.openPermGroups.delete(group.key);
      });

      const summary = node('summary');
      const enabledCount = group.flags.filter(f => permSet.has(f)).length;
      summary.append(
        node('span', '', tr(group.key)),
        node('span', 'sb-perm-group-count', `${enabledCount} / ${group.flags.length}`)
      );
      details.append(summary);

      const list = node('div', 'sb-perm-list');
      matchingFlags.forEach(flag => {
        const editable = canEditPermissionFlag(role, flag);
        const item = node('label', `sb-perm-item${editable ? '' : ' is-locked'}`);
        const cb = node('input');
        cb.type = 'checkbox';
        cb.checked = permSet.has(flag);
        cb.disabled = !editable;
        cb.dataset.action = 'role-perm';
        cb.dataset.flag = flag;
        if (!editable) item.title = permLockReason(role, flag);
        item.append(cb, node('span', 'sb-perm-label', tr(`perm_${flag}`, flag)));
        if (DANGEROUS_PERMISSIONS.has(flag)) {
          item.append(node('span', 'sb-perm-danger-badge', '⚠️'));
        }
        if (!editable) {
          const lock = node('span', 'sb-role-lock', '🔒');
          lock.title = permLockReason(role, flag);
          item.append(lock);
        }
        list.append(item);
      });
      details.append(list);
      frag.append(details);
    });
    els.rolePermGroups.replaceChildren(frag);
  }

  function renderRoleInspector(role) {
    const isEveryone = Boolean(role.is_everyone || role.name === '@everyone');
    const locked = isRoleInspectorLocked(role);
    els.kind.textContent = isEveryone ? tr('selected_everyone_role') : tr('selected_role');
    els.name.value = role.name;
    els.name.disabled = isEveryone || locked;

    if (locked) {
      els.roleLockBanner.hidden = false;
      els.roleLockText.textContent = roleLockReason(role);
    } else if (isEveryone) {
      els.roleLockBanner.hidden = false;
      els.roleLockText.textContent = tr('role_everyone_hint');
    } else {
      els.roleLockBanner.hidden = true;
    }

    els.roleColorSection.hidden = isEveryone;
    els.roleFlagsSection.hidden = isEveryone;
    els.roleModuleWrap.hidden = isEveryone || Boolean(role.managed);

    const activeColor = normalizeRoleColorHex(role.color);
    els.roleColorPicker.value = activeColor;
    els.roleColorPicker.disabled = isEveryone || locked;
    els.roleColorHex.value = activeColor;
    els.roleColorHex.disabled = isEveryone || locked;
    els.roleColorReset.disabled = isEveryone || locked;

    const swatchNodes = DISCORD_ROLE_SWATCHES.map(hex => {
      const sw = button(`sb-color-swatch${activeColor === hex ? ' active' : ''}`, '', hex, 'role-swatch');
      sw.dataset.color = hex;
      sw.disabled = isEveryone || locked;
      if (/^#[0-9a-f]{6}$/i.test(hex)) sw.style.backgroundColor = hex;
      return sw;
    });
    els.roleSwatches.replaceChildren(...swatchNodes);

    els.roleHoist.checked = Boolean(role.hoist);
    els.roleHoist.disabled = isEveryone || locked;
    els.roleMentionable.checked = Boolean(role.mentionable);
    els.roleMentionable.disabled = isEveryone || locked;
    els.roleModule.value = normalizeRoleBindModule(role.bind_role_module) || 'none';
    els.roleModule.disabled = isEveryone || Boolean(role.managed) || locked;

    const canAnyPerm = PERMISSION_GROUP_ANY_EDITABLE(role);
    const presetButtons = ROLE_QUICK_PRESETS.map(preset => {
      const btn = button('sb-preset-pill', tr(preset.labelKey), '', 'role-preset');
      btn.dataset.preset = preset.id;
      btn.disabled = locked || !canAnyPerm;
      return btn;
    });
    els.roleQuickPresets.replaceChildren(...presetButtons);

    renderRolePermissionGroups(role);

    const targets = roleOverwriteTargets(role);
    if (targets.length) {
      const chips = targets.map(t => {
        const prefix = t.kind === 'category' ? '📁 ' : '# ';
        const chip = button('sb-usage-chip', `${prefix}${t.item.name}`, '', 'jump-channel');
        chip.dataset.targetKey = t.key;
        return chip;
      });
      els.roleUsageChips.replaceChildren(...chips);
    } else {
      els.roleUsageChips.replaceChildren(node('span', 'sb-usage-empty', tr('role_usage_empty')));
    }
  }

  function PERMISSION_GROUP_ANY_EDITABLE(role) {
    return Object.keys(PERMISSION_BIT_BY_NAME).some(flag => canEditPermissionFlag(role, flag));
  }

  function renderInspector() {
    const found = state.selected ? findEntity(state.selected) : null;
    els.inspector.hidden = !found;
    els.inspectorEmpty.hidden = Boolean(found);
    if (!found) return;

    const { item, kind, parent } = found;
    const isRole = kind === 'role';
    const channel = kind === 'channel';
    const chType = Number(item.type);

    els.typeWrap.hidden = isRole || !channel;
    els.parentWrap.hidden = isRole || !channel;
    els.topicWrap.hidden = isRole || !channel || chType === 2;
    els.slowmodeWrap.hidden = isRole || !channel || chType === 2;
    els.nsfwWrap.hidden = isRole || !channel || chType === 2;
    els.voiceWrap.hidden = isRole || !channel || chType !== 2;
    els.moduleWrap.hidden = isRole || !channel;
    els.sanitizeWrap.hidden = isRole || !channel || chType === 2;
    els.syncSelected.hidden = isRole;
    els.channelPermissionsSec.hidden = isRole;
    els.roleInspector.hidden = !isRole;

    if (isRole) {
      els.newsHint.hidden = true;
      els.botViewWarning.hidden = true;
      renderRoleInspector(item);
      return;
    }

    els.roleLockBanner.hidden = true;
    els.name.disabled = false;
    els.kind.textContent = kind === 'category' ? tr('selected_category') : tr('selected_channel');
    els.name.value = item.name;
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
      const locked = isRoleHierarchyLocked(role);
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
    if (state.live?.live_source === 'cache') {
      banners.push({ cls: 'warning', text: tr('role_locked_cache') });
    }
    if (state.live && !(state.live.guild_features || []).includes('COMMUNITY') && allChannels().some(ch => !ch._deleted && Number(ch.type) === 5)) {
      banners.push({ cls: 'warning', text: tr('community_fallback') });
    }
    if (allChannels().some(ch => !ch._deleted && botViewBlocked(ch)) || state.draft.categories.some(cat => !cat._deleted && botViewBlocked(cat))) {
      banners.push({ cls: 'danger', text: tr('bot_view_warning') });
    }
    const totalChannels = state.draft.categories.filter(cat => !cat._deleted).length + allChannels().filter(ch => !ch._deleted).length;
    if (totalChannels > 500) banners.push({ cls: 'danger', text: tr('channel_limit_warning') });
    if (state.draft.categories.some(cat => !cat._deleted && cat.channels.filter(ch => !ch._deleted).length > 50)) {
      banners.push({ cls: 'danger', text: tr('category_limit_warning') });
    }
    if (allRoles().filter(r => !r._deleted).length > MAX_GUILD_ROLES) {
      banners.push({ cls: 'danger', text: tr('role_limit_warning') });
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
    const roleReorderCount = Number(Boolean(summary.bulk_reorder_roles || summary.reorder_roles));
    const grid = node('div', 'sb-summary-grid');
    const values = [
      [tr('diff_create'), Number(summary.create_roles || 0) + Number(summary.create_categories || 0) + Number(summary.create_channels || 0)],
      [tr('diff_rename'), Number(summary.renames || 0)],
      [tr('diff_sync'), Number(summary.sync_permissions || 0)],
      [
        tr('diff_update'),
        Number(summary.update_roles || 0)
        + Number(summary.update_channels || 0)
        + Number(summary.update_overwrites || 0)
        + Number(Boolean(summary.bulk_reorder))
        + roleReorderCount
        + Number(Boolean(summary.bind_modules)),
      ],
      [tr('diff_delete'), Number(summary.delete_roles || 0) + Number(summary.delete_channels || 0) + Number(summary.delete_categories || 0)],
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

  function setActiveTab(tab) {
    state.activeTab = tab === 'roles' ? 'roles' : 'channels';
    const isRoles = state.activeTab === 'roles';
    els.tabChannels.classList.toggle('active', !isRoles);
    els.tabChannels.setAttribute('aria-selected', String(!isRoles));
    els.tabRoles.classList.toggle('active', isRoles);
    els.tabRoles.setAttribute('aria-selected', String(isRoles));
    els.tree.hidden = isRoles;
    els.rolePanel.hidden = !isRoles;
    els.addCategory.hidden = isRoles;
    els.addRole.hidden = !isRoles;
    ensureSelection();
    renderAll();
  }

  function renderAll() {
    ensureSelection();
    renderTree();
    renderRoles();
    renderInspector();
    renderBanners();
    renderDiffSummary();
    const diffOps = state.diff ? Number(state.diff.summary?.total_operations || 0) : pendingCount();
    els.pendingCount.textContent = String(diffOps);
    els.undo.disabled = state.history.length === 0;
    const hasErrors = Boolean(state.diff && (state.diff.errors || []).length > 0);
    const perms = state.live?.bot_permissions || {};
    const summary = state.diff?.summary || {};
    const needsChannels = Boolean(
      Number(summary.create_categories || 0) + Number(summary.create_channels || 0)
      + Number(summary.update_channels || 0) + Number(summary.delete_categories || 0)
      + Number(summary.delete_channels || 0) + Number(Boolean(summary.bulk_reorder))
    );
    const needsRoles = Boolean(
      Number(summary.create_roles || 0) + Number(summary.update_roles || 0)
      + Number(summary.delete_roles || 0) + Number(summary.sync_permissions || 0)
      + Number(summary.update_overwrites || 0)
      + Number(Boolean(summary.bulk_reorder_roles || summary.reorder_roles))
    );
    const canChannels = !state.live || Boolean(perms.administrator || perms.manage_channels);
    const canRoles = !state.live || Boolean(perms.administrator || perms.manage_roles);
    const canManage = (!needsChannels || canChannels) && (!needsRoles || canRoles) && (canChannels || canRoles);
    els.reviewApply.disabled = state.previewBusy || Boolean(state.activeJob) || diffOps === 0 || hasErrors || !canManage;
  }

  function selectEntity(key, fromUser = false) {
    state.selected = key;
    renderTree();
    renderRoles();
    renderInspector();
    if (fromUser && window.innerWidth <= 1024 && els.inspector && !els.inspector.hidden) {
      const rect = els.inspector.getBoundingClientRect();
      if (rect.top < 0 || rect.top > window.innerHeight * 0.72) {
        els.inspector.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  }

  function addCategory() {
    mutate(() => {
      const category = normalizeTree({ categories: [{ temp_id: newTemp('cat'), name: tr('new_category'), channels: [] }], roles: [] }).categories[0];
      state.draft.categories.push(category);
      state.activeTab = 'channels';
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
      state.activeTab = 'channels';
      state.selected = entityKey(channel);
    });
  }

  function addRole() {
    if (state.live?.live_source === 'cache') {
      notify(tr('role_locked_cache'), 'warning');
      return;
    }
    const activeTotal = allRoles().filter(r => !r._deleted).length;
    if (activeTotal >= MAX_GUILD_ROLES) {
      notify(tr('role_limit_warning'), 'warning');
    }
    mutate(() => {
      const role = normalizeRoleEntry({
        id: null,
        temp_id: newTemp('role'),
        name: tr('new_role'),
        color: DEFAULT_ROLE_COLOR,
        position: 1,
        permissions: [],
        hoist: false,
        mentionable: false,
        managed: false,
        is_everyone: false,
        bind_role_module: null,
      });
      const firstUnlockedIdx = state.draft.roles.findIndex(r => !r.is_everyone && !r._deleted && !isRoleInspectorLocked(r));
      if (firstUnlockedIdx === -1) state.draft.roles.unshift(role);
      else state.draft.roles.splice(firstUnlockedIdx, 0, role);
      updateRolePositions(true);
      state.activeTab = 'roles';
      state.selected = entityKey(role);
    });
    setActiveTab('roles');
  }

  function moveEntity(key, direction) {
    const found = findEntity(key); if (!found || found.kind === 'role') return;
    const index = found.list.indexOf(found.item);
    const target = index + direction;
    if (target < 0 || target >= found.list.length) return;
    mutate(() => {
      found.list.splice(index, 1);
      found.list.splice(target, 0, found.item);
    });
  }

  function moveRole(key, direction) {
    if (state.roleSearch.trim()) return;
    const sorted = sortedRolesList(state.draft.roles);
    const movable = sorted.filter(r => !r.is_everyone && !r._deleted && !isRoleInspectorLocked(r));
    const index = movable.findIndex(r => entityKey(r) === key);
    const target = index + direction;
    if (index === -1 || target < 0 || target >= movable.length) return;
    mutate(() => {
      const movedItem = movable.splice(index, 1)[0];
      movable.splice(target, 0, movedItem);
      const lockedAbove = sorted.filter(r => !r.is_everyone && !movable.includes(r) && !r._deleted);
      const deletedRoles = sorted.filter(r => !r.is_everyone && r._deleted);
      const everyone = sorted.filter(r => r.is_everyone);
      state.draft.roles = [...lockedAbove, ...movable, ...deletedRoles, ...everyone];
      updateRolePositions(true);
    });
  }

  function stripRoleOverwrites(roleRef) {
    if (!roleRef) return;
    const target = String(roleRef);
    state.draft.categories.forEach(cat => {
      cat.overwrites = (cat.overwrites || []).filter(ow => String(ow.id) !== target);
      cat.channels.forEach(ch => {
        ch.overwrites = (ch.overwrites || []).filter(ow => String(ow.id) !== target);
      });
    });
    state.draft.uncategorized.forEach(ch => {
      ch.overwrites = (ch.overwrites || []).filter(ow => String(ow.id) !== target);
    });
    if (state.draft.bindings && typeof state.draft.bindings === 'object') {
      Object.keys(state.draft.bindings).forEach(modKey => {
        if (String(state.draft.bindings[modKey]) === target) {
          delete state.draft.bindings[modKey];
        }
      });
    }
  }

  function deleteOrRestore(key) {
    const found = findEntity(key); if (!found) return;
    if (found.kind === 'role') {
      const role = found.item;
      if (role.is_everyone || role.managed || isRoleHierarchyLocked(role)) return;
      if (state.live?.live_source === 'cache' || role._cache_readonly) {
        notify(tr('role_locked_cache'), 'warning');
        return;
      }
      if (role.id && !role._deleted && els.safeMode.checked) {
        notify(tr('safe_mode_protected_role'), 'warning');
        return;
      }
      mutate(() => {
        let targetRole = (state.draft.roles || []).find(r => entityKey(r) === key);
        if (!targetRole) {
          targetRole = clone(role);
          state.draft.roles.push(targetRole);
        }
        if (!targetRole.id) {
          const refKey = targetRole.temp_id || entityKey(targetRole);
          state.draft.roles.splice(state.draft.roles.indexOf(targetRole), 1);
          stripRoleOverwrites(refKey);
          updateRolePositions(true);
          if (state.selected === key) state.selected = null;
        } else {
          targetRole._deleted = !targetRole._deleted;
        }
      });
      return;
    }

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
    const found = findEntity(key); if (!found || found.kind === 'role') return;
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
    if (!found || found.kind === 'role' || !column) return;
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
    if (found.kind === 'role') {
      const roleKey = entityKey(found.item);
      if (isRoleInspectorLocked(found.item)) return;
      if (found.item.is_everyone && property !== 'permissions') return;
      snapshot();
      let targetRole = (state.draft.roles || []).find(r => (
        entityKey(r) === roleKey || (Boolean(r.is_everyone) && found.item.is_everyone)
      ));
      if (!targetRole) {
        targetRole = clone(found.item);
        state.draft.roles.push(targetRole);
      }
      if (property === 'bind_role_module') {
        if (targetRole.managed || targetRole.is_everyone) {
          state.history.pop();
          return;
        }
        const nextBind = normalizeRoleBindModule(value);
        const prevBind = normalizeRoleBindModule(targetRole.bind_role_module);
        if (!state.draft.bindings || typeof state.draft.bindings !== 'object') {
          state.draft.bindings = {};
        }
        const rId = targetRole.id ? String(targetRole.id) : null;
        const rTemp = targetRole.temp_id ? String(targetRole.temp_id) : null;
        const pointsToRole = ref => ref && ((rId && String(ref) === rId) || (rTemp && String(ref) === rTemp));
        if (nextBind) {
          (state.draft.roles || []).forEach(r => {
            if (r !== targetRole && normalizeRoleBindModule(r.bind_role_module) === nextBind) {
              r.bind_role_module = null;
            }
          });
          if (prevBind && prevBind !== nextBind && pointsToRole(state.draft.bindings[prevBind])) {
            delete state.draft.bindings[prevBind];
          }
          state.draft.bindings[nextBind] = entityKey(targetRole);
        } else {
          Object.keys(state.draft.bindings).forEach(k => {
            if (pointsToRole(state.draft.bindings[k])) {
              delete state.draft.bindings[k];
            }
          });
        }
        targetRole.bind_role_module = nextBind;
      } else if (property === 'color') {
        targetRole.color = normalizeRoleColorHex(value);
      } else if (property === 'permissions') {
        targetRole.permissions = normalizePermissionList(value);
      } else if (property === 'name') {
        targetRole.name = String(value || '').trim().slice(0, 100) || tr('new_role');
      } else if (property === 'hoist' || property === 'mentionable') {
        targetRole[property] = Boolean(value);
      }
      state.diff = null;
      renderAll();
      schedulePreviewDiff();
      return;
    }

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

  async function loadTree(usePreset = true, refresh = false) {
    try {
      const data = await request(refresh ? '/tree?refresh=1' : '/tree');
      state.live = data;
      state.roles = Array.isArray(data.roles) ? data.roles.map(r => normalizeRoleEntry(r)) : [];
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
    const isRole = operation.kind === 'role' || op.includes('role');
    if (op === 'update_channel' && operation.old_name && operation.new_name && operation.old_name !== operation.new_name) {
      return `${operation.old_name} → ${operation.new_name}`;
    }
    if (op === 'update_role' && operation.old_name && operation.new_name && operation.old_name !== operation.new_name) {
      return `🎭 @${operation.old_name} → @${operation.new_name}`;
    }
    const baseName = String(operation.name || operation.role_name || operation.target_name || operation.channel_name || op || '—');
    return isRole && !baseName.startsWith('@') && !baseName.startsWith('🎭') ? `🎭 @${baseName}` : baseName;
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
    const roleOpsTotal = Number(summary.create_roles || 0) + Number(summary.update_roles || 0) + Number(summary.delete_roles || 0);
    const reorderTotal = Number(Boolean(summary.bulk_reorder)) + Number(Boolean(summary.bulk_reorder_roles || summary.reorder_roles));
    const chips = [
      [tr('diff_roles'), roleOpsTotal],
      [tr('diff_create'), Number(summary.create_roles || 0) + Number(summary.create_categories || 0) + Number(summary.create_channels || 0)],
      [tr('diff_rename'), Number(summary.renames || 0)],
      [tr('diff_sync'), Number(summary.sync_permissions || 0)],
      [tr('diff_update'), Number(summary.update_roles || 0) + Number(summary.update_channels || 0) + Number(summary.update_overwrites || 0)],
      [tr('diff_reorder'), reorderTotal],
      [tr('diff_bind'), Number(Boolean(summary.bind_modules))],
      [tr('diff_delete'), Number(summary.delete_roles || 0) + Number(summary.delete_channels || 0) + Number(summary.delete_categories || 0)],
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
        const errCode = error.data?.error;
        const detail = (error.data?.missing || error.data?.denied_flags || []).join(', ');
        if (errCode === 'user_missing_permissions') {
          notify(`${tr('user_missing_permissions')}${detail ? `: ${detail}` : ''}`, 'error');
        } else if (errCode === 'privilege_escalation_denied') {
          notify(`${tr('privilege_escalation_error')}${detail ? `: ${detail}` : ''}`, 'error');
        } else if (errCode === 'user_role_hierarchy_denied' || errCode === 'channel_access_denied') {
          notify(error.data?.message || tr('role_hierarchy_error'), 'error');
        } else {
          notify(`${tr('missing_permissions')}${detail ? `: ${detail}` : ''}`, 'error');
        }
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
        if (data.job.status === 'completed') await loadTree(false, true);
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

  function applyRolePreset(presetId) {
    const found = state.selected ? findEntity(state.selected) : null;
    const preset = ROLE_QUICK_PRESETS.find(item => item.id === presetId);
    if (!found || found.kind !== 'role' || !preset || isRoleInspectorLocked(found.item)) return;
    const currentSet = new Set(normalizePermissionList(found.item.permissions));
    const wantedSet = new Set(preset.flags);
    const nextPerms = [];
    let skipped = false;

    currentSet.forEach(flag => {
      if (/^bit_\d+$/.test(flag)) nextPerms.push(flag);
    });
    Object.keys(PERMISSION_BIT_BY_NAME).forEach(flag => {
      const editable = canEditPermissionFlag(found.item, flag);
      const want = wantedSet.has(flag);
      const had = currentSet.has(flag);
      if (editable) {
        if (want) nextPerms.push(flag);
      } else {
        if (had) nextPerms.push(flag);
        if (want !== had) skipped = true;
      }
    });
    updateSelected('permissions', nextPerms);
    if (skipped) notify(tr('role_preset_filtered_toast'), 'info');
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

    els.roleColorPicker.addEventListener('input', () => {
      els.roleColorHex.value = normalizeRoleColorHex(els.roleColorPicker.value);
    });
    els.roleColorPicker.addEventListener('change', () => {
      updateSelected('color', els.roleColorPicker.value);
    });
    els.roleColorHex.addEventListener('change', () => {
      const raw = els.roleColorHex.value.trim();
      if (/^#?[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(raw)) {
        updateSelected('color', raw);
      } else {
        const found = state.selected && findEntity(state.selected);
        els.roleColorHex.value = found?.kind === 'role' ? normalizeRoleColorHex(found.item.color) : DEFAULT_ROLE_COLOR;
      }
    });
    els.roleColorReset.addEventListener('click', () => updateSelected('color', DEFAULT_ROLE_COLOR));
    els.roleSwatches.addEventListener('click', event => {
      const target = event.target.closest('[data-action="role-swatch"]');
      if (!target || target.disabled) return;
      updateSelected('color', target.dataset.color);
    });
    els.roleHoist.addEventListener('change', () => updateSelected('hoist', els.roleHoist.checked));
    els.roleMentionable.addEventListener('change', () => updateSelected('mentionable', els.roleMentionable.checked));
    els.roleModule.addEventListener('change', () => updateSelected('bind_role_module', normalizeRoleBindModule(els.roleModule.value)));
    els.roleQuickPresets.addEventListener('click', event => {
      const target = event.target.closest('[data-action="role-preset"]');
      if (!target || target.disabled) return;
      applyRolePreset(target.dataset.preset);
    });
    els.permSearch.addEventListener('input', () => {
      state.permSearch = els.permSearch.value || '';
      const found = state.selected && findEntity(state.selected);
      if (found?.kind === 'role') renderRolePermissionGroups(found.item);
    });
    els.rolePermGroups.addEventListener('change', event => {
      const cb = event.target.closest('input[data-action="role-perm"]');
      if (!cb || cb.disabled) return;
      const found = state.selected && findEntity(state.selected);
      if (!found || found.kind !== 'role' || !canEditPermissionFlag(found.item, cb.dataset.flag)) return;
      const permSet = new Set(normalizePermissionList(found.item.permissions));
      if (cb.checked) permSet.add(cb.dataset.flag);
      else permSet.delete(cb.dataset.flag);
      updateSelected('permissions', [...permSet]);
    });
    els.roleUsageChips.addEventListener('click', event => {
      const target = event.target.closest('[data-action="jump-channel"]');
      if (!target) return;
      const targetKey = target.dataset.targetKey;
      if (!targetKey) return;
      state.selected = targetKey;
      setActiveTab('channels');
    });
  }

  els.tabChannels.addEventListener('click', () => setActiveTab('channels'));
  els.tabRoles.addEventListener('click', () => setActiveTab('roles'));
  els.roleSearch.addEventListener('input', () => {
    state.roleSearch = els.roleSearch.value || '';
    renderRoles();
  });
  els.mobileBack.addEventListener('click', () => {
    const target = state.activeTab === 'roles' ? els.rolePanel : els.tree;
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  els.tree.addEventListener('click', event => {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    const key = target.dataset.key;
    const action = target.dataset.action;
    if (action === 'select') selectEntity(key, true);
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

  els.roleList.addEventListener('click', event => {
    const target = event.target.closest('[data-action]');
    if (!target || target.disabled) return;
    const key = target.dataset.key;
    const action = target.dataset.action;
    if (action === 'select') selectEntity(key, true);
    else if (action === 'role-up') moveRole(key, -1);
    else if (action === 'role-down') moveRole(key, 1);
    else if (action === 'delete') deleteOrRestore(key);
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

  els.roleList.addEventListener('dblclick', event => {
    const target = event.target.closest('.sb-entity-name');
    if (!target) return;
    const found = findEntity(target.dataset.key);
    if (!found || found.kind !== 'role' || found.item.is_everyone || isRoleInspectorLocked(found.item) || found.item._deleted) return;
    const input = node('input', 'sb-inline-rename');
    input.type = 'text';
    input.maxLength = 100;
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
        updateSelected('name', input.value.trim().slice(0, 100));
      } else {
        renderRoles();
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
    if (state.drag && state.drag.kind !== 'role' && event.target.closest('[data-kind][data-key], .sb-channel-list')) event.preventDefault();
  });
  els.tree.addEventListener('drop', event => {
    event.preventDefault();
    if (!state.drag || state.drag.kind === 'role') return;
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

  els.roleList.addEventListener('dragstart', event => {
    if (state.roleSearch.trim()) return;
    const row = event.target.closest('.sb-role-row[data-key]');
    if (!row || !row.draggable) return;
    state.drag = { key: row.dataset.key, kind: 'role' };
    row.classList.add('is-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', row.dataset.key);
    }
  });
  els.roleList.addEventListener('dragover', event => {
    if (state.drag?.kind !== 'role') return;
    const row = event.target.closest('.sb-role-row[data-key]');
    if (row && row.draggable) event.preventDefault();
  });
  els.roleList.addEventListener('drop', event => {
    event.preventDefault();
    if (state.drag?.kind !== 'role') return;
    const sourceKey = state.drag.key;
    const targetRow = event.target.closest('.sb-role-row[data-key]');
    state.drag = null;
    if (!targetRow || !targetRow.draggable || targetRow.dataset.key === sourceKey) {
      renderRoles();
      return;
    }
    const targetKey = targetRow.dataset.key;
    const sorted = sortedRolesList(state.draft.roles);
    const movable = sorted.filter(r => !r.is_everyone && !r._deleted && !isRoleInspectorLocked(r));
    const srcIdx = movable.findIndex(r => entityKey(r) === sourceKey);
    const dstIdx = movable.findIndex(r => entityKey(r) === targetKey);
    if (srcIdx === -1 || dstIdx === -1 || srcIdx === dstIdx) {
      renderRoles();
      return;
    }
    mutate(() => {
      const moved = movable.splice(srcIdx, 1)[0];
      movable.splice(dstIdx, 0, moved);
      const lockedAbove = sorted.filter(r => !r.is_everyone && !movable.includes(r) && !r._deleted);
      const deletedRoles = sorted.filter(r => !r.is_everyone && r._deleted);
      const everyone = sorted.filter(r => r.is_everyone);
      state.draft.roles = [...lockedAbove, ...movable, ...deletedRoles, ...everyone];
      updateRolePositions(true);
    });
  });
  els.roleList.addEventListener('dragend', () => { state.drag = null; renderRoles(); });

  els.permissionsBody.addEventListener('click', event => {
    const target = event.target.closest('[data-action="permission"]');
    if (!target || target.disabled) return;
    setPermission(target.dataset.key, target.dataset.role, target.dataset.column, target.dataset.value);
  });

  els.addCategory.addEventListener('click', addCategory);
  els.addRole.addEventListener('click', addRole);
  els.syncSelected.addEventListener('click', () => { if (state.selected) syncItem(state.selected); });
  els.undo.addEventListener('click', () => {
    const previous = state.history.pop();
    if (!previous) return;
    state.draft = previous.draft;
    state.selected = previous.selected;
    state.diff = null;
    if (previous.activeTab && previous.activeTab !== state.activeTab) {
      setActiveTab(previous.activeTab);
    } else {
      renderAll();
    }
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
    await loadTree(false, true);
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
      (state.draft.roles || []).forEach(role => { role._deleted = false; });
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
    // Deep-link ?tab=roles (mục 👑 Roles trên rail) — mở thẳng tab Vai trò
    try {
      if (new URLSearchParams(window.location.search).get('tab') === 'roles') {
        setActiveTab('roles');
      }
    } catch (e) { /* bỏ qua */ }
    await loadTemplates();
    await loadTree(true);
    if (state.activeJob && !state.pollTimer && !terminalStatuses.has(state.activeJob.status)) {
      attachJob(state.activeJob);
    }
  }
  initialize();
})();
