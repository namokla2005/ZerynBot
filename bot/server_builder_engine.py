"""
server_builder_engine.py — Pure Python planning, validation, preset, and diff engine
for Server Builder Studio.

Zero live Discord HTTP dependencies (`discord` is NOT imported here).
"""

from __future__ import annotations

import copy
import math
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

CHANNEL_TYPE_TEXT = 0
CHANNEL_TYPE_VOICE = 2
CHANNEL_TYPE_CATEGORY = 4
CHANNEL_TYPE_ANNOUNCEMENT = 5

MAX_GUILD_CHANNELS = 500
MAX_CATEGORY_CHILDREN = 50
MAX_GUILD_ROLES = 250
MAX_OVERWRITES_PER_CHANNEL = 100
MAX_CHANNEL_NAME_LEN = 100

OP_COST_CREATE_ROLE = 1.0
OP_COST_UPDATE_ROLE = 1.0
OP_COST_BULK_REORDER_ROLES = 1.5
OP_COST_CREATE_CATEGORY = 1.0
OP_COST_CREATE_CHANNEL = 1.0
OP_COST_OVERWRITES = 0.9
OP_COST_UPDATE_CHANNEL = 1.2
OP_COST_BULK_REORDER = 1.5
OP_COST_DELETE = 1.0
OP_COST_BIND_MODULES = 0.5

_VALID_CHILD_TYPES = frozenset({CHANNEL_TYPE_TEXT, CHANNEL_TYPE_VOICE, CHANNEL_TYPE_ANNOUNCEMENT})
_TEXT_LIKE_TYPES = frozenset({CHANNEL_TYPE_TEXT, CHANNEL_TYPE_ANNOUNCEMENT})

# Canonical 52-bit Discord permission registry shared by Dashboard, Engine, and Cog.
PERMISSION_BITS: Dict[int, str] = {
    0: "create_instant_invite",
    1: "kick_members",
    2: "ban_members",
    3: "administrator",
    4: "manage_channels",
    5: "manage_guild",
    6: "add_reactions",
    7: "view_audit_log",
    8: "priority_speaker",
    9: "stream",
    10: "view_channel",
    11: "send_messages",
    12: "send_tts_messages",
    13: "manage_messages",
    14: "embed_links",
    15: "attach_files",
    16: "read_message_history",
    17: "mention_everyone",
    18: "use_external_emojis",
    19: "view_guild_insights",
    20: "connect",
    21: "speak",
    22: "mute_members",
    23: "deafen_members",
    24: "move_members",
    25: "use_vad",
    26: "change_nickname",
    27: "manage_nicknames",
    28: "manage_roles",
    29: "manage_webhooks",
    30: "manage_guild_expressions",
    31: "use_application_commands",
    32: "request_to_speak",
    33: "manage_events",
    34: "manage_threads",
    35: "create_public_threads",
    36: "create_private_threads",
    37: "use_external_stickers",
    38: "send_messages_in_threads",
    39: "use_embedded_activities",
    40: "moderate_members",
    41: "view_creator_monetization_analytics",
    42: "use_soundboard",
    43: "create_guild_expressions",
    44: "create_events",
    45: "use_external_sounds",
    46: "send_voice_messages",
    48: "set_voice_channel_status",
    49: "send_polls",
    50: "use_external_apps",
    51: "pin_messages",
    52: "bypass_slowmode",
}

PERMISSION_BIT_BY_NAME: Dict[str, int] = {name: bit for bit, name in PERMISSION_BITS.items()}

PERMISSION_ALIASES: Dict[str, str] = {
    "read_messages": "view_channel",
    "use_voice_activation": "use_vad",
    "manage_expressions": "manage_guild_expressions",
    "manage_emojis": "manage_guild_expressions",
    "manage_emojis_and_stickers": "manage_guild_expressions",
    "create_expressions": "create_guild_expressions",
    "manage_permissions": "manage_roles",
    "external_emojis": "use_external_emojis",
    "external_stickers": "use_external_stickers",
    "create_polls": "send_polls",
}

ALL_KNOWN_PERMISSIONS_MASK: int = 0
for _perm_bit in PERMISSION_BITS:
    ALL_KNOWN_PERMISSIONS_MASK |= 1 << _perm_bit

PRIVILEGED_OVERWRITE_NAMES: frozenset[str] = frozenset({
    "manage_roles",
    "manage_webhooks",
    "manage_channels",
    "manage_messages",
    "manage_threads",
    "mention_everyone",
    "mute_members",
    "deafen_members",
    "move_members",
})

ROLE_BIND_MODULE_ALIASES: Dict[str, str] = {
    "autoroles_user": "autoroles_user",
    "autorole_user": "autoroles_user",
    "verify_verified": "verify_verified",
    "verify_verified_role": "verify_verified",
    "verify_pending": "verify_pending",
    "verify_pending_role": "verify_pending",
    "automod_immune": "automod_immune",
    "automod_immune_role": "automod_immune",
}

ROLE_BIND_MODULES: frozenset[str] = frozenset({
    "autoroles_user",
    "verify_verified",
    "verify_pending",
    "automod_immune",
})

_DEFAULT_ROLE_COLOR_HEX = "#99aab5"
_STAFF_LEAD_PERMS: List[str] = [
    "add_reactions",
    "attach_files",
    "bypass_slowmode",
    "change_nickname",
    "connect",
    "create_events",
    "create_instant_invite",
    "create_private_threads",
    "create_public_threads",
    "embed_links",
    "manage_events",
    "manage_messages",
    "manage_nicknames",
    "manage_threads",
    "moderate_members",
    "move_members",
    "mute_members",
    "pin_messages",
    "priority_speaker",
    "read_message_history",
    "send_messages",
    "send_messages_in_threads",
    "send_polls",
    "send_voice_messages",
    "speak",
    "stream",
    "use_application_commands",
    "use_embedded_activities",
    "use_external_emojis",
    "use_external_sounds",
    "use_external_stickers",
    "use_soundboard",
    "use_vad",
    "view_audit_log",
    "view_channel",
]
_MODERATOR_PERMS: List[str] = [
    "add_reactions",
    "attach_files",
    "change_nickname",
    "connect",
    "create_instant_invite",
    "create_public_threads",
    "embed_links",
    "manage_messages",
    "manage_nicknames",
    "manage_threads",
    "moderate_members",
    "mute_members",
    "pin_messages",
    "read_message_history",
    "send_messages",
    "send_messages_in_threads",
    "send_polls",
    "send_voice_messages",
    "speak",
    "stream",
    "use_application_commands",
    "use_external_emojis",
    "use_external_stickers",
    "use_vad",
    "view_channel",
]
_VIP_PERMS: List[str] = [
    "add_reactions",
    "attach_files",
    "change_nickname",
    "connect",
    "create_instant_invite",
    "create_public_threads",
    "embed_links",
    "priority_speaker",
    "read_message_history",
    "send_messages",
    "send_messages_in_threads",
    "send_polls",
    "send_voice_messages",
    "speak",
    "stream",
    "use_application_commands",
    "use_embedded_activities",
    "use_external_emojis",
    "use_external_sounds",
    "use_external_stickers",
    "use_soundboard",
    "use_vad",
    "view_channel",
]
_MEMBER_PERMS: List[str] = [
    "add_reactions",
    "attach_files",
    "change_nickname",
    "connect",
    "create_instant_invite",
    "embed_links",
    "read_message_history",
    "send_messages",
    "send_messages_in_threads",
    "send_polls",
    "send_voice_messages",
    "speak",
    "stream",
    "use_application_commands",
    "use_vad",
    "view_channel",
]

# Presets live in an ALL-CAPS module constant so scripts/i18n_audit.py classifies
# preset labels as CATALOG rather than hardcoded DISCORD strings.
SYSTEM_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "community_4cat",
        "name_key": "server_builder.preset_community_4cat_name",
        "desc_key": "server_builder.preset_community_4cat_desc",
        "name": "Community Standard (4 Categories)",
        "description": "Balanced 4-category community structure with read-only announcements, public chat, voice rooms, and private staff/support.",
        "tree": {
            "roles": [
                {
                    "temp_id": "role_staff_lead",
                    "id": None,
                    "name": "Staff Lead",
                    "color": "#e74c3c",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_STAFF_LEAD_PERMS),
                    "position": 4,
                    "bind_role_module": "automod_immune",
                },
                {
                    "temp_id": "role_mod",
                    "id": None,
                    "name": "Moderator",
                    "color": "#3498db",
                    "hoist": True,
                    "mentionable": True,
                    "permissions": list(_MODERATOR_PERMS),
                    "position": 3,
                    "bind_role_module": None,
                },
                {
                    "temp_id": "role_vip",
                    "id": None,
                    "name": "VIP",
                    "color": "#f1c40f",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_VIP_PERMS),
                    "position": 2,
                    "bind_role_module": None,
                },
                {
                    "temp_id": "role_member",
                    "id": None,
                    "name": "Member",
                    "color": "#2ecc71",
                    "hoist": False,
                    "mentionable": False,
                    "permissions": list(_MEMBER_PERMS),
                    "position": 1,
                    "bind_role_module": "autoroles_user",
                },
            ],
            "categories": [
                {
                    "temp_id": "cat_announce",
                    "id": None,
                    "name": "📢 ANNOUNCEMENT",
                    "position": 0,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "read_message_history"],
                            "deny": ["send_messages", "add_reactions"],
                        },
                        {
                            "id": "role_staff_lead",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "manage_messages"],
                            "deny": [],
                        },
                        {
                            "id": "role_mod",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history"],
                            "deny": [],
                        },
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_rules",
                            "id": None,
                            "name": "rules",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Server rules and community guidelines.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_announce",
                            "id": None,
                            "name": "announce",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Official server announcements.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_gate",
                            "id": None,
                            "name": "gate",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Welcome gate & member verification.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "welcome",
                        },
                        {
                            "temp_id": "ch_news",
                            "id": None,
                            "name": "news",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Updates and community news.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 3,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_chat",
                    "id": None,
                    "name": "💬 CHAT",
                    "position": 1,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": [
                                "view_channel",
                                "send_messages",
                                "read_message_history",
                                "embed_links",
                                "attach_files",
                            ],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_chat_chung",
                            "id": None,
                            "name": "chat-chung",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "General community chat.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_bot_chat",
                            "id": None,
                            "name": "bot-chat",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Bot commands and fun interactions.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_game_chat",
                            "id": None,
                            "name": "game-chat",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Gaming discussions and LFG.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_media_share",
                            "id": None,
                            "name": "media-share",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Share images, clips, and memes.",
                            "slowmode": 5,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 3,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_voice",
                    "id": None,
                    "name": "🔊 VOICE CHAT",
                    "position": 2,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": [
                                "view_channel",
                                "connect",
                                "speak",
                                "send_messages",
                                "read_message_history",
                            ],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_set_music",
                            "id": None,
                            "name": "set-music",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Music player requests and controls.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "music",
                        },
                        {
                            "temp_id": "ch_vc_chung",
                            "id": None,
                            "name": "🔊 Chung",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_vc_game",
                            "id": None,
                            "name": "🎮 Game",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_vc_study",
                            "id": None,
                            "name": "📚 Học tập",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 3,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_vc_chill",
                            "id": None,
                            "name": "☕ Chill",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 4,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_staff",
                    "id": None,
                    "name": "🛡️ STAFF & SUPPORT",
                    "position": 3,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": [],
                            "deny": ["view_channel"],
                        },
                        {
                            "id": "role_staff_lead",
                            "type": "role",
                            "allow": [
                                "view_channel",
                                "send_messages",
                                "read_message_history",
                                "manage_messages",
                                "connect",
                                "speak",
                            ],
                            "deny": [],
                        },
                        {
                            "id": "role_mod",
                            "type": "role",
                            "allow": [
                                "view_channel",
                                "send_messages",
                                "read_message_history",
                                "connect",
                                "speak",
                            ],
                            "deny": [],
                        },
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_ticket_support",
                            "id": None,
                            "name": "ticket-support",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Open a support ticket with staff.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": False,
                            "overwrites": [
                                {
                                    "id": "@everyone",
                                    "type": "role",
                                    "allow": ["view_channel", "read_message_history"],
                                    "deny": ["send_messages"],
                                },
                                {
                                    "id": "role_staff_lead",
                                    "type": "role",
                                    "allow": ["view_channel", "send_messages", "read_message_history"],
                                    "deny": [],
                                },
                                {
                                    "id": "role_mod",
                                    "type": "role",
                                    "allow": ["view_channel", "send_messages", "read_message_history"],
                                    "deny": [],
                                },
                            ],
                            "bind_module": "tickets",
                        },
                        {
                            "temp_id": "ch_mod_chat",
                            "id": None,
                            "name": "mod-chat",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Private moderator coordination.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_bot_logs",
                            "id": None,
                            "name": "bot-logs",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Automod & server audit logs.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "bot_logs",
                        },
                        {
                            "temp_id": "ch_vc_staff",
                            "id": None,
                            "name": "🔊 Họp Staff",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 3,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
            ],
            "bindings": {
                "welcome": "ch_gate",
                "verify": "ch_gate",
                "music": "ch_set_music",
                "tickets": "ch_ticket_support",
                "bot_logs": "ch_bot_logs",
                "automod_immune": "role_staff_lead",
                "autoroles_user": "role_member",
            },
        },
    },
    {
        "id": "gaming_squad",
        "name_key": "server_builder.preset_gaming_squad_name",
        "desc_key": "server_builder.preset_gaming_squad_desc",
        "name": "Gaming Squad & Clan",
        "description": "Clan/gaming layout with LFG text channels, Duo/Trio/Squad voice limits, music controls, and staff logs.",
        "tree": {
            "roles": [
                {
                    "temp_id": "role_leader",
                    "id": None,
                    "name": "Clan Leader",
                    "color": "#e74c3c",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_STAFF_LEAD_PERMS),
                    "position": 4,
                    "bind_role_module": "automod_immune",
                },
                {
                    "temp_id": "role_officer",
                    "id": None,
                    "name": "Clan Officer",
                    "color": "#e67e22",
                    "hoist": True,
                    "mentionable": True,
                    "permissions": list(_MODERATOR_PERMS),
                    "position": 3,
                    "bind_role_module": None,
                },
                {
                    "temp_id": "role_veteran",
                    "id": None,
                    "name": "Squad Veteran",
                    "color": "#9b59b6",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_VIP_PERMS),
                    "position": 2,
                    "bind_role_module": None,
                },
                {
                    "temp_id": "role_recruit",
                    "id": None,
                    "name": "Clan Member",
                    "color": "#3498db",
                    "hoist": False,
                    "mentionable": False,
                    "permissions": list(_MEMBER_PERMS),
                    "position": 1,
                    "bind_role_module": "autoroles_user",
                },
            ],
            "categories": [
                {
                    "temp_id": "cat_clan_info",
                    "id": None,
                    "name": "📢 CLAN INFO",
                    "position": 0,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "read_message_history"],
                            "deny": ["send_messages", "add_reactions"],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_g_rules",
                            "id": None,
                            "name": "rules",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Clan rules & match conduct.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_announce",
                            "id": None,
                            "name": "announcements",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Tournament and scrim schedule.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_welcome",
                            "id": None,
                            "name": "welcome",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "New recruit welcome & verify.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "welcome",
                        },
                    ],
                },
                {
                    "temp_id": "cat_clan_lobby",
                    "id": None,
                    "name": "🎮 LOBBY & TEXT",
                    "position": 1,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "embed_links", "attach_files"],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_g_lfg",
                            "id": None,
                            "name": "tim-dong-doi",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Looking for teammates.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_highlights",
                            "id": None,
                            "name": "highlights",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Match clips & screenshots.",
                            "slowmode": 5,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_bot",
                            "id": None,
                            "name": "bot-chat",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Stats and bot commands.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_clan_voice",
                    "id": None,
                    "name": "🎧 SQUAD VOICE",
                    "position": 2,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "connect", "speak", "send_messages", "read_message_history"],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_g_music",
                            "id": None,
                            "name": "set-music",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Music commands for voice squads.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "music",
                        },
                        {
                            "temp_id": "ch_g_vc_duo",
                            "id": None,
                            "name": "🎮 Duo (2)",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 2,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_vc_trio",
                            "id": None,
                            "name": "🎯 Trio (3)",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 3,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_vc_squad",
                            "id": None,
                            "name": "🔥 Squad (5)",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 5,
                            "position": 3,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_clan_staff",
                    "id": None,
                    "name": "🛡️ CLAN STAFF",
                    "position": 3,
                    "overwrites": [
                        {"id": "@everyone", "type": "role", "allow": [], "deny": ["view_channel"]},
                        {
                            "id": "role_leader",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "manage_messages", "connect", "speak"],
                            "deny": [],
                        },
                        {
                            "id": "role_officer",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "connect", "speak"],
                            "deny": [],
                        },
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_g_staff_chat",
                            "id": None,
                            "name": "staff-chat",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Officer planning.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_g_logs",
                            "id": None,
                            "name": "bot-logs",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Moderation and automod logs.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "bot_logs",
                        },
                    ],
                },
            ],
            "bindings": {
                "welcome": "ch_g_welcome",
                "music": "ch_g_music",
                "bot_logs": "ch_g_logs",
                "automod_immune": "role_leader",
                "autoroles_user": "role_recruit",
            },
        },
    },
    {
        "id": "study_class",
        "name_key": "server_builder.preset_study_class_name",
        "desc_key": "server_builder.preset_study_class_desc",
        "name": "Study Group & Class",
        "description": "Structured classroom/study layout with announcements, materials, Q&A, submissions, study voice rooms, and staff.",
        "tree": {
            "roles": [
                {
                    "temp_id": "role_instructor",
                    "id": None,
                    "name": "Instructor",
                    "color": "#e74c3c",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_STAFF_LEAD_PERMS),
                    "position": 3,
                    "bind_role_module": "automod_immune",
                },
                {
                    "temp_id": "role_tutor",
                    "id": None,
                    "name": "Tutor",
                    "color": "#2ecc71",
                    "hoist": True,
                    "mentionable": True,
                    "permissions": list(_MODERATOR_PERMS),
                    "position": 2,
                    "bind_role_module": None,
                },
                {
                    "temp_id": "role_student",
                    "id": None,
                    "name": "Student",
                    "color": "#3498db",
                    "hoist": False,
                    "mentionable": False,
                    "permissions": list(_MEMBER_PERMS),
                    "position": 1,
                    "bind_role_module": "autoroles_user",
                },
            ],
            "categories": [
                {
                    "temp_id": "cat_study_notice",
                    "id": None,
                    "name": "📌 THÔNG BÁO & TÀI LIỆU",
                    "position": 0,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "read_message_history"],
                            "deny": ["send_messages", "add_reactions"],
                        },
                        {
                            "id": "role_instructor",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "manage_messages"],
                            "deny": [],
                        },
                        {
                            "id": "role_tutor",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history"],
                            "deny": [],
                        },
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_s_notice",
                            "id": None,
                            "name": "thong-bao",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Class schedules and announcements.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "welcome",
                        },
                        {
                            "temp_id": "ch_s_docs",
                            "id": None,
                            "name": "tai-lieu",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Lecture notes and reading materials.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_study_discuss",
                    "id": None,
                    "name": "💬 THẢO LUẬN & NỘP BÀI",
                    "position": 1,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "embed_links", "attach_files"],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_s_qa",
                            "id": None,
                            "name": "hoi-dap",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Ask questions and help peers.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_s_submit",
                            "id": None,
                            "name": "nop-bai",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Assignment submissions.",
                            "slowmode": 10,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_study_voice",
                    "id": None,
                    "name": "🎧 PHÒNG HỌC VOICE",
                    "position": 2,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "connect", "speak", "send_messages", "read_message_history"],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_s_music",
                            "id": None,
                            "name": "set-music",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Lo-fi / study music queue.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "music",
                        },
                        {
                            "temp_id": "ch_s_vc_1",
                            "id": None,
                            "name": "📚 Phòng học 1",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_s_vc_group",
                            "id": None,
                            "name": "👥 Phòng nhóm",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 6,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_study_staff",
                    "id": None,
                    "name": "🛡️ STAFF & LOGS",
                    "position": 3,
                    "overwrites": [
                        {"id": "@everyone", "type": "role", "allow": [], "deny": ["view_channel"]},
                        {
                            "id": "role_instructor",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "manage_messages"],
                            "deny": [],
                        },
                        {
                            "id": "role_tutor",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history"],
                            "deny": [],
                        },
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_s_logs",
                            "id": None,
                            "name": "bot-logs",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Classroom moderation logs.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "bot_logs",
                        }
                    ],
                },
            ],
            "bindings": {
                "welcome": "ch_s_notice",
                "music": "ch_s_music",
                "bot_logs": "ch_s_logs",
                "automod_immune": "role_instructor",
                "autoroles_user": "role_student",
            },
        },
    },
    {
        "id": "creator_community",
        "name_key": "server_builder.preset_creator_community_name",
        "desc_key": "server_builder.preset_creator_community_desc",
        "name": "Creator Starter (Minimal)",
        "description": "Clean minimal starter server with Welcome & Info, Community Chat, and Lounge Voice + music controls.",
        "tree": {
            "roles": [
                {
                    "temp_id": "role_c_mod",
                    "id": None,
                    "name": "Channel Mod",
                    "color": "#3498db",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_MODERATOR_PERMS),
                    "position": 3,
                    "bind_role_module": "automod_immune",
                },
                {
                    "temp_id": "role_supporter",
                    "id": None,
                    "name": "Supporter",
                    "color": "#ff8a9b",
                    "hoist": True,
                    "mentionable": False,
                    "permissions": list(_VIP_PERMS),
                    "position": 2,
                    "bind_role_module": None,
                },
                {
                    "temp_id": "role_follower",
                    "id": None,
                    "name": "Follower",
                    "color": "#7c6cf0",
                    "hoist": False,
                    "mentionable": False,
                    "permissions": list(_MEMBER_PERMS),
                    "position": 1,
                    "bind_role_module": "autoroles_user",
                },
            ],
            "categories": [
                {
                    "temp_id": "cat_c_info",
                    "id": None,
                    "name": "👋 WELCOME & INFO",
                    "position": 0,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "read_message_history"],
                            "deny": ["send_messages"],
                        },
                        {
                            "id": "role_c_mod",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history"],
                            "deny": [],
                        },
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_c_welcome",
                            "id": None,
                            "name": "welcome",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Welcome new members!",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "welcome",
                        },
                        {
                            "temp_id": "ch_c_announce",
                            "id": None,
                            "name": "announcements",
                            "type": CHANNEL_TYPE_ANNOUNCEMENT,
                            "topic": "Creator updates & streams.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_c_chat",
                    "id": None,
                    "name": "💬 COMMUNITY CHAT",
                    "position": 1,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "send_messages", "read_message_history", "embed_links", "attach_files"],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_c_general",
                            "id": None,
                            "name": "general",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Hang out and chat.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_c_showcase",
                            "id": None,
                            "name": "showcase",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Fan art & community creations.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                        {
                            "temp_id": "ch_c_bot",
                            "id": None,
                            "name": "bot-commands",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Bot utilities & fun commands.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 2,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
                {
                    "temp_id": "cat_c_voice",
                    "id": None,
                    "name": "🎙️ LOUNGE VOICE",
                    "position": 2,
                    "overwrites": [
                        {
                            "id": "@everyone",
                            "type": "role",
                            "allow": ["view_channel", "connect", "speak", "send_messages", "read_message_history"],
                            "deny": [],
                        }
                    ],
                    "channels": [
                        {
                            "temp_id": "ch_c_music",
                            "id": None,
                            "name": "set-music",
                            "type": CHANNEL_TYPE_TEXT,
                            "topic": "Music bot controls.",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 0,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": "music",
                        },
                        {
                            "temp_id": "ch_c_lounge",
                            "id": None,
                            "name": "☕ Lounge",
                            "type": CHANNEL_TYPE_VOICE,
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "bitrate": 64000,
                            "user_limit": 0,
                            "position": 1,
                            "sync_permissions": True,
                            "overwrites": [],
                            "bind_module": None,
                        },
                    ],
                },
            ],
            "bindings": {
                "welcome": "ch_c_welcome",
                "music": "ch_c_music",
                "automod_immune": "role_c_mod",
                "autoroles_user": "role_follower",
            },
        },
    },
]


def sanitize_channel_name(name: str, channel_type: int) -> str:
    """Sanitize a Discord channel or category name according to channel_type rules."""
    raw = str(name or "")
    try:
        ctype = int(channel_type)
    except (TypeError, ValueError):
        ctype = CHANNEL_TYPE_TEXT

    if ctype in _TEXT_LIKE_TYPES:
        slug = raw.strip().lower()
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"[^\w\-]", "", slug, flags=re.UNICODE)
        slug = re.sub(r"-{2,}", "-", slug)
        slug = slug.strip("-")[:MAX_CHANNEL_NAME_LEN].strip("-")
        return slug or "channel"

    cleaned = re.sub(r"[\r\n\t]+", " ", raw).strip()
    cleaned = cleaned[:MAX_CHANNEL_NAME_LEN].strip()
    return cleaned or "channel"


def get_system_presets() -> List[Dict[str, Any]]:
    """Return deep copies of the 4 built-in Server Builder preset structures."""
    return copy.deepcopy(SYSTEM_PRESETS)


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _is_everyone_role(role: Dict[str, Any]) -> bool:
    rid = str(role.get("id") or "").strip()
    rname = str(role.get("name") or "").strip()
    return bool(role.get("is_everyone")) or rid == "@everyone" or rname == "@everyone"


def normalize_role_bind_module(value: Any) -> Optional[str]:
    """Canonicalize a role module binding token, or return None if unset/unknown."""
    if value is None or isinstance(value, bool):
        return None
    token = str(value).strip().lower()
    if not token or token in {"none", "null", "undefined"}:
        return None
    return ROLE_BIND_MODULE_ALIASES.get(token)


def _canonical_perm_flag(raw_name: str) -> Optional[str]:
    token = raw_name.strip().lower()
    if not token:
        return None
    canon = PERMISSION_ALIASES.get(token, token)
    if canon.startswith("bit_") and canon[4:].isdigit():
        bit = int(canon[4:])
        if bit in PERMISSION_BITS:
            return PERMISSION_BITS[bit]
        if 0 <= bit < 64:
            return f"bit_{bit}"
        return None
    return canon


def _bits_to_perm_list(bitfield: int) -> List[str]:
    bits = max(0, int(bitfield)) & ((1 << 64) - 1)
    out: List[str] = []
    while bits:
        lsb = bits & -bits
        bit_pos = lsb.bit_length() - 1
        out.append(PERMISSION_BITS.get(bit_pos, f"bit_{bit_pos}"))
        bits ^= lsb
    return sorted(set(out))


def normalize_role_permissions(value: Any) -> List[str]:
    """Normalize role permissions (int, digit str, csv str, list/set, dict) into a sorted list[str]."""
    if value is None or isinstance(value, bool) or value == 0 or value == "":
        return []
    if isinstance(value, int):
        return _bits_to_perm_list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.isdigit():
            return _bits_to_perm_list(int(text))
        parts = [p.strip() for p in text.split(",") if p.strip()]
        flags = {_canonical_perm_flag(p) for p in parts}
        return sorted(f for f in flags if f)
    if isinstance(value, dict):
        flags = {_canonical_perm_flag(str(k)) for k, enabled in value.items() if enabled and k is not None}
        return sorted(f for f in flags if f)
    if isinstance(value, (list, tuple, set, frozenset)):
        flags = set()
        for item in value:
            if item is None or isinstance(item, bool):
                continue
            if isinstance(item, int):
                flags.update(_bits_to_perm_list(item))
                continue
            canon = _canonical_perm_flag(str(item))
            if canon:
                flags.add(canon)
        return sorted(flags)
    return []


def permissions_to_bitfield(value: Any) -> int:
    """Convert permission flags or bitfield inputs into a 64-bit integer mask."""
    if value is None or isinstance(value, bool) or value == 0 or value == "":
        return 0
    if isinstance(value, int):
        return max(0, value) & ((1 << 64) - 1)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        if text.isdigit():
            return max(0, int(text)) & ((1 << 64) - 1)
    mask = 0
    for name in normalize_role_permissions(value):
        bit = PERMISSION_BIT_BY_NAME.get(name)
        if bit is not None:
            mask |= 1 << bit
        elif name.startswith("bit_") and name[4:].isdigit():
            bit_pos = int(name[4:])
            if 0 <= bit_pos < 64:
                mask |= 1 << bit_pos
    return mask


def normalize_role_color(value: Any) -> str:
    """Canonicalize Discord role color (0 / #000000 / empty -> '#99aab5', else '#rrggbb')."""
    if value is None or isinstance(value, bool):
        return _DEFAULT_ROLE_COLOR_HEX
    if isinstance(value, int):
        if value <= 0:
            return _DEFAULT_ROLE_COLOR_HEX
        hex_val = f"#{value & 0xFFFFFF:06x}"
        return _DEFAULT_ROLE_COLOR_HEX if hex_val == "#000000" else hex_val
    text = str(value).strip()
    if not text:
        return _DEFAULT_ROLE_COLOR_HEX
    if text.isdigit():
        num = int(text)
        if num <= 0:
            return _DEFAULT_ROLE_COLOR_HEX
        hex_val = f"#{num & 0xFFFFFF:06x}"
        return _DEFAULT_ROLE_COLOR_HEX if hex_val == "#000000" else hex_val
    raw_hex = text[1:] if text.startswith("#") else text
    if len(raw_hex) == 3 and all(c in "0123456789abcdefABCDEF" for c in raw_hex):
        expanded = "".join(c * 2 for c in raw_hex).lower()
        return _DEFAULT_ROLE_COLOR_HEX if expanded == "000000" else f"#{expanded}"
    if len(raw_hex) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw_hex):
        lowered = raw_hex.lower()
        return _DEFAULT_ROLE_COLOR_HEX if lowered == "000000" else f"#{lowered}"
    return _DEFAULT_ROLE_COLOR_HEX


def compute_channel_permissions(
    guild_roles: Optional[List[Dict[str, Any]]],
    member_role_ids: Optional[Any],
    channel_overwrites: Optional[List[Dict[str, Any]]],
    *,
    is_owner: bool = False,
    parent_overwrites: Optional[List[Dict[str, Any]]] = None,
    member_id: Optional[str] = None,
) -> int:
    """Evaluate effective channel permission bitfield via Discord's 4-step algorithm."""
    if is_owner:
        return ALL_KNOWN_PERMISSIONS_MASK

    role_set = {str(rid).strip() for rid in (member_role_ids or []) if rid is not None and str(rid).strip()}
    everyone_raw_id: Optional[str] = None
    base = 0

    for role in guild_roles or []:
        if not isinstance(role, dict):
            continue
        rid = str(role.get("id") or "").strip()
        perms = permissions_to_bitfield(role.get("permissions", role.get("permission_bits", 0)))
        if _is_everyone_role(role):
            base |= perms
            if rid and rid != "@everyone":
                everyone_raw_id = rid
        elif rid and rid in role_set:
            base |= perms

    admin_bit = 1 << PERMISSION_BIT_BY_NAME["administrator"]
    if base & admin_bit:
        return ALL_KNOWN_PERMISSIONS_MASK

    effective_overwrites = (
        parent_overwrites
        if (channel_overwrites is None and parent_overwrites is not None)
        else (channel_overwrites or [])
    )

    everyone_ids = {"@everyone"}
    if everyone_raw_id:
        everyone_ids.add(everyone_raw_id)

    role_allow = 0
    role_deny = 0
    member_ows: List[Tuple[int, int]] = []

    # Step 1: @everyone overwrite first, collecting role/member overwrites in one pass
    for ow in effective_overwrites:
        if not isinstance(ow, dict):
            continue
        target_id = str(ow.get("id") if ow.get("id") is not None else ow.get("target_id") or "").strip()
        if not target_id:
            continue
        raw_type = str(ow.get("type") or "role").strip().lower()
        ow_type = "member" if raw_type in ("1", "member") else "role"
        allow_bits = permissions_to_bitfield(ow.get("allow", ow.get("allow_bits", 0)))
        deny_bits = permissions_to_bitfield(ow.get("deny", ow.get("deny_bits", 0)))

        if ow_type == "role" and target_id in everyone_ids:
            base = (base & ~deny_bits) | allow_bits
        elif ow_type == "role" and target_id in role_set:
            role_allow |= allow_bits
            role_deny |= deny_bits
        elif ow_type == "member" and member_id is not None and target_id == str(member_id).strip():
            member_ows.append((allow_bits, deny_bits))

    # Step 2: combined role overwrites
    base = (base & ~role_deny) | role_allow

    # Step 3: member-specific overwrite
    for allow_bits, deny_bits in member_ows:
        base = (base & ~deny_bits) | allow_bits

    return base & ((1 << 64) - 1)


def _normalize_perm_list(raw: Any) -> Tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, int) and not isinstance(raw, bool):
        return (str(raw),)
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return tuple(sorted(set(parts)))
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return ()
    return tuple(sorted({str(x).strip() for x in raw if x is not None and str(x).strip()}))


def canonicalize_overwrites(overwrites: Optional[List[Dict[str, Any]]]) -> List[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]]]:
    """Convert permission overwrites into a sorted canonical list of tuples for diffing."""
    if not overwrites:
        return []
    canonical: List[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]]] = []
    for ow in overwrites:
        if not isinstance(ow, dict):
            continue
        target_id = str(ow.get("id") if ow.get("id") is not None else "").strip()
        if not target_id:
            continue
        target_type = str(ow.get("type") or "role").strip().lower()
        allow = _normalize_perm_list(ow.get("allow"))
        deny = _normalize_perm_list(ow.get("deny"))
        if not allow and not deny:
            continue
        canonical.append((target_type, target_id, allow, deny))
    canonical.sort()
    return canonical


def is_overwrites_synced(
    cat_overwrites: Optional[List[Dict[str, Any]]],
    ch_overwrites: Optional[List[Dict[str, Any]]],
) -> bool:
    """Return True if a channel's permission overwrites match its parent category."""
    return canonicalize_overwrites(cat_overwrites) == canonicalize_overwrites(ch_overwrites)


def _check_overwrites_safety(
    overwrites: Optional[List[Dict[str, Any]]],
    location_label: str,
    role_pos_by_id: Dict[str, int],
    bot_top_role_pos: Optional[int],
    bot_role_set: Set[str],
    bot_user_str: Optional[str],
    warnings: List[str],
) -> None:
    if not overwrites:
        return
    for ow in overwrites:
        if not isinstance(ow, dict):
            continue
        target_id = str(ow.get("id") if ow.get("id") is not None else "").strip()
        if not target_id:
            continue
        deny_set = set(_normalize_perm_list(ow.get("deny")))

        target_position = ow.get("position", role_pos_by_id.get(target_id))
        if bot_top_role_pos is not None and isinstance(target_position, int):
            if target_position >= bot_top_role_pos:
                warnings.append(
                    f"Overwrite on role {target_id} in {location_label} cannot be edited because its position ({target_position}) >= bot top role ({bot_top_role_pos})."
                )

        targets_bot = (
            (bot_user_str and target_id == bot_user_str)
            or (target_id in bot_role_set)
            or bool(ow.get("is_bot") or ow.get("targets_bot"))
        )
        if targets_bot and "view_channel" in deny_set:
            warnings.append(
                f"Overwrite in {location_label} denies view_channel to ZerynBot ({target_id})."
            )


def _validate_role_binding_target(
    mod_key: str,
    role_name: str,
    is_ev: bool,
    is_managed: bool,
    has_real_id: bool,
    pos: Any,
    bot_top_role_pos: Optional[int],
    is_guild_owner: bool,
    user_top_role_pos: Optional[int],
    errors: List[str],
    *,
    is_unchanged: bool = False,
    warnings: Optional[List[str]] = None,
) -> None:
    if is_ev or is_managed:
        errors.append(
            f"Role '{role_name}' cannot be bound to module '{mod_key}' because it is @everyone or managed."
        )
        return
    if has_real_id and isinstance(pos, int) and not isinstance(pos, bool):
        if bot_top_role_pos is not None and pos >= bot_top_role_pos:
            msg = (
                f"Existing role '{role_name}' cannot be bound to module '{mod_key}' "
                f"because its position ({pos}) >= bot top role ({bot_top_role_pos})."
            )
            if is_unchanged and warnings is not None:
                warnings.append(msg)
            else:
                errors.append(msg)
        if (not is_guild_owner) and user_top_role_pos is not None and pos >= user_top_role_pos:
            msg = (
                f"Existing role '{role_name}' cannot be bound to module '{mod_key}' "
                f"because its position ({pos}) >= user top role ({user_top_role_pos})."
            )
            if is_unchanged and warnings is not None:
                warnings.append(msg)
            else:
                errors.append(msg)


def validate_tree_limits(
    tree: Dict[str, Any],
    bot_top_role_pos: Optional[int] = None,
    bot_role_ids: Optional[Any] = None,
    bot_user_id: Optional[str] = None,
    *,
    is_guild_owner: bool = True,
    user_top_role_pos: Optional[int] = None,
    current_bindings: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Validate Discord structural limits and role/permission safety warnings."""
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(tree, dict):
        return {
            "ok": False,
            "errors": ["Tree payload must be a JSON object."],
            "warnings": [],
        }

    roles = tree.get("roles") or []
    categories = tree.get("categories") or []
    uncategorized = tree.get("uncategorized") or []

    if not isinstance(roles, list) or not isinstance(categories, list) or not isinstance(uncategorized, list):
        return {
            "ok": False,
            "errors": ["roles, categories, and uncategorized must be lists."],
            "warnings": [],
        }

    bot_role_set = {str(r) for r in (bot_role_ids or []) if r is not None}
    bot_user_str = str(bot_user_id) if bot_user_id is not None else None
    curr_binds_norm: Dict[str, str] = {}
    if isinstance(current_bindings, dict):
        for k, v in current_bindings.items():
            if _is_valid_binding_token(k) and _is_valid_binding_token(v):
                nk = normalize_role_bind_module(str(k)) or str(k).strip()
                curr_binds_norm[nk] = str(v).strip()

    role_pos_by_id: Dict[str, int] = {}
    roles_by_ref: Dict[str, Dict[str, Any]] = {}
    checked_role_bindings: Set[Tuple[str, str]] = set()
    if len(roles) > MAX_GUILD_ROLES:
        errors.append(
            f"Role count ({len(roles)}) exceeds Discord limit of {MAX_GUILD_ROLES}."
        )
    for idx, role in enumerate(roles):
        if not isinstance(role, dict):
            errors.append(f"Role entry at index {idx} must be an object.")
            continue
        is_ev = _is_everyone_role(role)
        r_name = "@everyone" if is_ev else str(role.get("name") or f"role-{idx}").strip()
        pos = role.get("position")
        raw_id = str(role.get("id") or "").strip()
        has_real_id = bool(raw_id) and not is_ev
        for key in (role.get("id"), role.get("temp_id")):
            if key:
                roles_by_ref[str(key)] = role
        if isinstance(pos, int) and not isinstance(pos, bool):
            for key in (role.get("id"), role.get("temp_id")):
                if key:
                    role_pos_by_id[str(key)] = pos
            if (not is_ev) and bot_top_role_pos is not None and pos >= bot_top_role_pos:
                warnings.append(
                    f"Role '{r_name}' has position {pos} >= bot top role ({bot_top_role_pos}) and will be skipped."
                )

        raw_bmod = role.get("bind_role_module")
        if _is_valid_binding_token(raw_bmod):
            norm_bmod = normalize_role_bind_module(raw_bmod)
            if norm_bmod is None:
                errors.append(f"Role '{r_name}' has unknown bind_role_module {raw_bmod!r}.")
            else:
                ref_key = raw_id or str(role.get("temp_id") or "")
                pair = (norm_bmod, ref_key)
                if pair not in checked_role_bindings:
                    checked_role_bindings.add(pair)
                    is_unchanged = bool(raw_id) and curr_binds_norm.get(norm_bmod) == raw_id
                    _validate_role_binding_target(
                        norm_bmod,
                        r_name,
                        is_ev,
                        bool(role.get("managed")),
                        has_real_id,
                        pos,
                        bot_top_role_pos,
                        is_guild_owner,
                        user_top_role_pos,
                        errors,
                        is_unchanged=is_unchanged,
                        warnings=warnings,
                    )

    for binding_dict in (tree.get("bindings"), tree.get("role_bindings")):
        if not isinstance(binding_dict, dict):
            continue
        for raw_key, raw_ref in binding_dict.items():
            if not _is_valid_binding_token(raw_key) or not _is_valid_binding_token(raw_ref):
                continue
            norm_bmod = normalize_role_bind_module(raw_key)
            if norm_bmod is None:
                continue
            ref_str = str(raw_ref).strip()
            if (norm_bmod, ref_str) in checked_role_bindings:
                continue
            checked_role_bindings.add((norm_bmod, ref_str))
            if ref_str == "@everyone":
                errors.append(f"Role '@everyone' cannot be bound to module '{norm_bmod}'.")
                continue
            matched = roles_by_ref.get(ref_str)
            if matched is not None:
                m_ev = _is_everyone_role(matched)
                m_name = "@everyone" if m_ev else str(matched.get("name") or ref_str).strip()
                m_raw_id = str(matched.get("id") or "").strip()
                m_has_id = bool(m_raw_id) and not m_ev
                is_unchanged = bool(m_raw_id) and curr_binds_norm.get(norm_bmod) == m_raw_id
                _validate_role_binding_target(
                    norm_bmod,
                    m_name,
                    m_ev,
                    bool(matched.get("managed")),
                    m_has_id,
                    matched.get("position"),
                    bot_top_role_pos,
                    is_guild_owner,
                    user_top_role_pos,
                    errors,
                    is_unchanged=is_unchanged,
                    warnings=warnings,
                )

    total_channels = len(categories) + len(uncategorized)
    for c_idx, cat in enumerate(categories):
        if not isinstance(cat, dict):
            errors.append(f"Category at index {c_idx} must be an object.")
            continue
        cat_name = str(cat.get("name") or f"Category {c_idx + 1}").strip()
        cat_ow_list = cat.get("overwrites") or []
        if isinstance(cat_ow_list, list) and len(cat_ow_list) > MAX_OVERWRITES_PER_CHANNEL:
            errors.append(
                f"Category '{cat_name}' has {len(cat_ow_list)} overwrites, exceeding limit of {MAX_OVERWRITES_PER_CHANNEL}."
            )
        children = cat.get("channels") or []
        if not isinstance(children, list):
            errors.append(f"Category '{cat_name}' channels must be a list.")
            continue
        total_channels += len(children)
        if len(children) > MAX_CATEGORY_CHILDREN:
            errors.append(
                f"Category '{cat_name}' has {len(children)} channels, exceeding Discord limit of {MAX_CATEGORY_CHILDREN}."
            )

        _check_overwrites_safety(
            cat_ow_list,
            f"category '{cat_name}'",
            role_pos_by_id,
            bot_top_role_pos,
            bot_role_set,
            bot_user_str,
            warnings,
        )

        for ch_idx, ch in enumerate(children):
            if not isinstance(ch, dict):
                errors.append(f"Channel at index {ch_idx} in '{cat_name}' must be an object.")
                continue
            ch_name = str(ch.get("name") or f"channel-{ch_idx}").strip()
            ch_type = ch.get("type", CHANNEL_TYPE_TEXT)
            ch_type_int = _safe_int(ch_type, -1)
            if ch_type_int not in _VALID_CHILD_TYPES:
                errors.append(f"Channel '{ch_name}' has invalid type {ch_type!r} (expected 0, 2, or 5).")
            ch_ow_list = ch.get("overwrites") or []
            if isinstance(ch_ow_list, list) and len(ch_ow_list) > MAX_OVERWRITES_PER_CHANNEL:
                errors.append(
                    f"Channel '{ch_name}' has {len(ch_ow_list)} overwrites, exceeding limit of {MAX_OVERWRITES_PER_CHANNEL}."
                )
            if not ch.get("sync_permissions", False):
                _check_overwrites_safety(
                    ch_ow_list,
                    f"channel '{ch_name}'",
                    role_pos_by_id,
                    bot_top_role_pos,
                    bot_role_set,
                    bot_user_str,
                    warnings,
                )

    for u_idx, ch in enumerate(uncategorized):
        if not isinstance(ch, dict):
            errors.append(f"Uncategorized channel at index {u_idx} must be an object.")
            continue
        ch_name = str(ch.get("name") or f"channel-{u_idx}").strip()
        ch_type = ch.get("type", CHANNEL_TYPE_TEXT)
        ch_type_int = _safe_int(ch_type, -1)
        if ch_type_int not in _VALID_CHILD_TYPES:
            errors.append(f"Channel '{ch_name}' has invalid type {ch_type!r} (expected 0, 2, or 5).")
        ch_ow_list = ch.get("overwrites") or []
        if isinstance(ch_ow_list, list) and len(ch_ow_list) > MAX_OVERWRITES_PER_CHANNEL:
            errors.append(
                f"Channel '{ch_name}' has {len(ch_ow_list)} overwrites, exceeding limit of {MAX_OVERWRITES_PER_CHANNEL}."
            )
        _check_overwrites_safety(
            ch_ow_list,
            f"channel '{ch_name}'",
            role_pos_by_id,
            bot_top_role_pos,
            bot_role_set,
            bot_user_str,
            warnings,
        )

    if total_channels > MAX_GUILD_CHANNELS:
        errors.append(
            f"Total channel count ({total_channels}) exceeds Discord limit of {MAX_GUILD_CHANNELS}."
        )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def _clean_overwrites_for_op(
    overwrites: Optional[List[Dict[str, Any]]],
    role_ref_remap: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    if not overwrites:
        return cleaned
    remap = role_ref_remap or {}
    for ow in overwrites:
        if not isinstance(ow, dict):
            continue
        raw_id = ow.get("id")
        if raw_id is None:
            continue
        target_id = str(raw_id).strip()
        if not target_id:
            continue
        target_id = remap.get(target_id, target_id)
        allow = list(_normalize_perm_list(ow.get("allow")))
        deny = list(_normalize_perm_list(ow.get("deny")))
        if not allow and not deny:
            continue
        cleaned.append({
            "id": target_id,
            "type": str(ow.get("type") or "role").strip().lower(),
            "allow": allow,
            "deny": deny,
        })
    return cleaned


def _index_current_tree(current_tree: Dict[str, Any]) -> Tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
    Dict[str, Dict[str, Any]],
]:
    roles_by_id: Dict[str, Dict[str, Any]] = {}
    roles_by_name: Dict[str, Dict[str, Any]] = {}
    for r in current_tree.get("roles") or []:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "").strip()
        if rid:
            roles_by_id[rid] = r
        elif _is_everyone_role(r):
            roles_by_id["@everyone"] = r
        rname = str(r.get("name") or "").strip().lower()
        if rname and rname not in roles_by_name:
            roles_by_name[rname] = r

    cats_by_id: Dict[str, Dict[str, Any]] = {}
    cats_by_name: Dict[str, Dict[str, Any]] = {}
    channels_by_id: Dict[str, Dict[str, Any]] = {}

    for idx, cat in enumerate(current_tree.get("categories") or []):
        if not isinstance(cat, dict):
            continue
        cid = str(cat.get("id") or "").strip()
        cat_entry = {**cat, "position": _safe_int(cat.get("position"), idx)}
        if cid:
            cats_by_id[cid] = cat_entry
        cname = sanitize_channel_name(str(cat.get("name") or ""), CHANNEL_TYPE_CATEGORY).lower()
        if cname and cname not in cats_by_name:
            cats_by_name[cname] = cat_entry

        for ch_idx, ch in enumerate(cat.get("channels") or []):
            if not isinstance(ch, dict):
                continue
            chid = str(ch.get("id") or "").strip()
            if chid:
                channels_by_id[chid] = {
                    **ch,
                    "parent_id": cid or ch.get("parent_id"),
                    "position": _safe_int(ch.get("position"), ch_idx),
                }

    for u_idx, ch in enumerate(current_tree.get("uncategorized") or []):
        if not isinstance(ch, dict):
            continue
        chid = str(ch.get("id") or "").strip()
        if chid:
            channels_by_id[chid] = {
                **ch,
                "parent_id": None,
                "position": _safe_int(ch.get("position"), u_idx),
            }

    return roles_by_id, roles_by_name, cats_by_id, cats_by_name, channels_by_id


def _is_valid_binding_token(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    token = str(value).strip()
    return bool(token) and token.lower() not in {"none", "null", "undefined"}


def _resolve_bindings_and_unbinds(
    target_tree: Dict[str, Any],
    channel_ref_by_temp: Dict[str, str],
    role_ref_remap: Optional[Dict[str, str]] = None,
    current_bindings: Optional[Dict[str, str]] = None,
    deleted_role_ids: Optional[Set[str]] = None,
) -> Tuple[Dict[str, str], Set[str]]:
    resolved: Dict[str, str] = {}
    explicit_role_unbinds: Set[str] = set()
    role_remap = role_ref_remap or {}
    curr_binds = current_bindings or {}
    del_roles = deleted_role_ids or set()

    for raw_dict in (target_tree.get("bindings"), target_tree.get("role_bindings")):
        if not isinstance(raw_dict, dict):
            continue
        for mod_key, ref in raw_dict.items():
            if not _is_valid_binding_token(mod_key):
                continue
            norm_role_mod = normalize_role_bind_module(mod_key)
            if norm_role_mod is not None:
                if _is_valid_binding_token(ref):
                    ref_str = str(ref).strip()
                    resolved[norm_role_mod] = role_remap.get(ref_str, ref_str)
                    explicit_role_unbinds.discard(norm_role_mod)
                else:
                    resolved.pop(norm_role_mod, None)
                    explicit_role_unbinds.add(norm_role_mod)
                continue
            if not _is_valid_binding_token(ref):
                continue
            ref_str = str(ref).strip()
            resolved[str(mod_key).strip()] = channel_ref_by_temp.get(ref_str, ref_str)

    all_channels: List[Dict[str, Any]] = []
    for cat in target_tree.get("categories") or []:
        if isinstance(cat, dict):
            all_channels.extend(ch for ch in (cat.get("channels") or []) if isinstance(ch, dict))
    for ch in target_tree.get("uncategorized") or []:
        if isinstance(ch, dict):
            all_channels.append(ch)

    for ch in all_channels:
        bmod = ch.get("bind_module")
        raw_refs = {str(r).strip() for r in (ch.get("id"), ch.get("temp_id")) if _is_valid_binding_token(r)}
        resolved_refs = {channel_ref_by_temp.get(r, r) for r in raw_refs} | raw_refs
        primary_ref = str(ch.get("id") or ch.get("temp_id") or "").strip()
        if not primary_ref:
            continue
        target_ref = channel_ref_by_temp.get(primary_ref, primary_ref)

        if _is_valid_binding_token(bmod):
            # Explicit channel-level bind_module always takes precedence over stale tree["bindings"].
            resolved[str(bmod).strip()] = target_ref
        elif isinstance(bmod, str):
            # Explicit empty/sentinel ("", "none", "null", "undefined") clears stale bindings for this channel.
            for k in [k for k, v in resolved.items() if v in resolved_refs]:
                del resolved[k]

    for r in target_tree.get("roles") or []:
        if not isinstance(r, dict):
            continue
        if _is_everyone_role(r) or bool(r.get("managed")):
            continue
        raw_refs = {str(x).strip() for x in (r.get("id"), r.get("temp_id")) if _is_valid_binding_token(x)}
        resolved_refs = {role_remap.get(x, x) for x in raw_refs} | raw_refs
        primary_ref = str(r.get("id") or r.get("temp_id") or "").strip()
        if not primary_ref:
            continue
        target_ref = role_remap.get(primary_ref, primary_ref)

        if "bind_role_module" in r:
            raw_rbmod = r.get("bind_role_module")
            norm_rbmod = normalize_role_bind_module(raw_rbmod)
            if norm_rbmod is not None:
                for k in [
                    k for k, v in resolved.items()
                    if k in ROLE_BIND_MODULES and v in resolved_refs and k != norm_rbmod
                ]:
                    del resolved[k]
                resolved[norm_rbmod] = target_ref
                explicit_role_unbinds.discard(norm_rbmod)
            elif raw_rbmod is None or isinstance(raw_rbmod, str):
                for k in [k for k, v in resolved.items() if k in ROLE_BIND_MODULES and v in resolved_refs]:
                    del resolved[k]
                for k in ROLE_BIND_MODULES:
                    if curr_binds.get(k) in resolved_refs:
                        explicit_role_unbinds.add(k)

    for k in ROLE_BIND_MODULES:
        if resolved.get(k) in del_roles:
            del resolved[k]
            explicit_role_unbinds.add(k)
        elif curr_binds.get(k) in del_roles and k not in resolved:
            explicit_role_unbinds.add(k)

    return resolved, explicit_role_unbinds


def _normalize_bindings(
    target_tree: Dict[str, Any],
    channel_ref_by_temp: Dict[str, str],
    role_ref_remap: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    resolved, _ = _resolve_bindings_and_unbinds(
        target_tree, channel_ref_by_temp, role_ref_remap=role_ref_remap
    )
    return resolved


def _empty_diff_summary(safe_mode: bool, confirm_deletions: bool) -> Dict[str, Any]:
    return {
        "total_operations": 0,
        "create_roles": 0,
        "update_roles": 0,
        "reorder_roles": False,
        "bulk_reorder_roles": False,
        "delete_roles": 0,
        "create_categories": 0,
        "create_channels": 0,
        "sync_permissions": 0,
        "update_overwrites": 0,
        "update_channels": 0,
        "renames": 0,
        "rename_warning": False,
        "bulk_reorder": False,
        "delete_channels": 0,
        "delete_categories": 0,
        "has_deletions": False,
        "delete_targets": [],
        "protected_deletions": 0,
        "bind_modules": False,
        "safe_mode": bool(safe_mode),
        "confirm_deletions": bool(confirm_deletions),
    }


def compute_diff(
    current_tree: Optional[Dict[str, Any]],
    target_tree: Optional[Dict[str, Any]],
    safe_mode: bool = True,
    confirm_deletions: bool = False,
    bot_top_role_pos: Optional[int] = None,
    *,
    is_guild_owner: bool = True,
    user_top_role_pos: Optional[int] = None,
    protected_role_ids: Optional[Any] = None,
    live_source: str = "discord",
) -> Dict[str, Any]:
    """Compute ordered Discord Server Builder operations and ETA between current and target trees."""
    curr = current_tree if isinstance(current_tree, dict) else {}
    tgt = target_tree if isinstance(target_tree, dict) else {}

    validation = validate_tree_limits(
        tgt,
        bot_top_role_pos=bot_top_role_pos,
        is_guild_owner=is_guild_owner,
        user_top_role_pos=user_top_role_pos,
        current_bindings=curr.get("bindings") if isinstance(curr.get("bindings"), dict) else None,
    )
    warnings: List[str] = list(validation["warnings"])
    errors: List[str] = list(validation["errors"])
    if errors:
        return {
            "summary": _empty_diff_summary(safe_mode, confirm_deletions),
            "operations": [],
            "eta_seconds": 0.0,
            "warnings": warnings,
            "errors": errors,
        }

    roles_by_id, _, cats_by_id, _, channels_by_id = _index_current_tree(curr)

    role_create_ops: List[Dict[str, Any]] = []
    role_update_ops: List[Dict[str, Any]] = []
    role_reorder_ops: List[Dict[str, Any]] = []
    cat_create_ops: List[Dict[str, Any]] = []
    ch_create_ops: List[Dict[str, Any]] = []
    perm_ops: List[Dict[str, Any]] = []
    update_ops: List[Dict[str, Any]] = []
    reorder_items: List[Dict[str, Any]] = []
    delete_ch_ops: List[Dict[str, Any]] = []
    delete_cat_ops: List[Dict[str, Any]] = []
    delete_role_ops: List[Dict[str, Any]] = []
    bind_ops: List[Dict[str, Any]] = []

    is_cache_mode = str(live_source or "discord").strip().lower() == "cache"
    cache_edit_warned = False

    def _warn_cache_readonly() -> None:
        nonlocal cache_edit_warned
        if not cache_edit_warned:
            cache_edit_warned = True
            warnings.append(
                "Offline SQLite cache mode: role edits/deletions were skipped to protect existing permissions."
            )

    curr_everyone_id: Optional[str] = None
    curr_everyone_role: Optional[Dict[str, Any]] = None
    for cid, c_role in roles_by_id.items():
        if _is_everyone_role(c_role):
            curr_everyone_id = cid
            curr_everyone_role = c_role
            break

    target_roles = [r for r in (tgt.get("roles") or []) if isinstance(r, dict)]
    matched_role_ids: Set[str] = set()
    role_matches: Dict[int, Optional[Dict[str, Any]]] = {}
    role_ref_remap: Dict[str, str] = {}

    # Pass 1: @everyone and explicit IDs
    for idx, r in enumerate(target_roles):
        if _is_everyone_role(r):
            if curr_everyone_role is not None and curr_everyone_id and curr_everyone_id not in matched_role_ids:
                role_matches[idx] = curr_everyone_role
                matched_role_ids.add(curr_everyone_id)
            continue
        rid = str(r.get("id") or "").strip()
        if rid and rid in roles_by_id and rid not in matched_role_ids:
            role_matches[idx] = roles_by_id[rid]
            matched_role_ids.add(rid)

    # Pass 2: case-insensitive name match for roles without explicit ID (e.g. presets/templates)
    for idx, r in enumerate(target_roles):
        if idx in role_matches or _is_everyone_role(r):
            continue
        rid = str(r.get("id") or "").strip()
        if rid:
            continue
        rname_lower = str(r.get("name") or "").strip().lower()
        if not rname_lower:
            continue
        for cid, c_role in roles_by_id.items():
            if cid in matched_role_ids or _is_everyone_role(c_role) or bool(c_role.get("managed")):
                continue
            if str(c_role.get("name") or "").strip().lower() == rname_lower:
                role_matches[idx] = c_role
                matched_role_ids.add(cid)
                break

    movable_target_roles: List[Dict[str, Any]] = []
    for idx, r in enumerate(target_roles):
        is_ev = _is_everyone_role(r)
        temp_id = "" if is_ev else str(r.get("temp_id") or f"role_tmp_{idx}").strip()
        curr_r = role_matches.get(idx)

        if curr_r is not None:
            curr_is_ev = _is_everyone_role(curr_r)
            curr_raw_id = str(curr_r.get("id") or ("@everyone" if curr_is_ev else "")).strip()
            canon_id = "@everyone" if curr_is_ev else curr_raw_id
            if temp_id and canon_id:
                role_ref_remap[temp_id] = canon_id
            if curr_is_ev and curr_raw_id and curr_raw_id != "@everyone":
                role_ref_remap[curr_raw_id] = "@everyone"

            curr_managed = bool(curr_r.get("managed", False))
            curr_pos = 0 if curr_is_ev else _safe_int(curr_r.get("position"), 0)
            curr_name = "@everyone" if curr_is_ev else str(curr_r.get("name") or "").strip()[:100]
            curr_color = _DEFAULT_ROLE_COLOR_HEX if curr_is_ev else normalize_role_color(
                curr_r.get("color", curr_r.get("color_hex", 0))
            )
            curr_hoist = False if curr_is_ev else bool(curr_r.get("hoist", False))
            curr_mentionable = False if curr_is_ev else bool(curr_r.get("mentionable", False))
            curr_perms = normalize_role_permissions(curr_r.get("permissions", curr_r.get("permission_bits", 0)))

            has_name = ("name" in r and r.get("name") is not None)
            has_color = ("color" in r or "color_hex" in r)
            has_hoist = ("hoist" in r)
            has_mentionable = ("mentionable" in r)
            has_perms = ("permissions" in r or "permission_bits" in r)
            has_pos = ("position" in r and r.get("position") is not None)

            tgt_name = "@everyone" if curr_is_ev else (
                (str(r.get("name") or "").strip()[:100] or curr_name) if has_name else curr_name
            )
            tgt_color = _DEFAULT_ROLE_COLOR_HEX if curr_is_ev else (
                normalize_role_color(r.get("color", r.get("color_hex", 0))) if has_color else curr_color
            )
            tgt_hoist = False if curr_is_ev else (bool(r.get("hoist", False)) if has_hoist else curr_hoist)
            tgt_mentionable = False if curr_is_ev else (
                bool(r.get("mentionable", False)) if has_mentionable else curr_mentionable
            )
            tgt_perms = normalize_role_permissions(
                r.get("permissions", r.get("permission_bits", 0))
            ) if has_perms else curr_perms
            tgt_pos = 0 if curr_is_ev else (_safe_int(r.get("position"), curr_pos) if has_pos else curr_pos)

            changes: Dict[str, Any] = {}
            if curr_is_ev:
                if tgt_perms != curr_perms:
                    changes["permissions"] = tgt_perms
                    changes["permissions_bitfield"] = str(permissions_to_bitfield(tgt_perms))
            else:
                if tgt_name != curr_name:
                    changes["name"] = tgt_name
                if tgt_color != curr_color:
                    changes["color"] = tgt_color
                if tgt_hoist != curr_hoist:
                    changes["hoist"] = tgt_hoist
                if tgt_mentionable != curr_mentionable:
                    changes["mentionable"] = tgt_mentionable
                if tgt_perms != curr_perms:
                    changes["permissions"] = tgt_perms
                    changes["permissions_bitfield"] = str(permissions_to_bitfield(tgt_perms))

            role_cache_readonly = is_cache_mode or bool(curr_r.get("_cache_readonly")) or bool(r.get("_cache_readonly"))
            if role_cache_readonly:
                if changes or (not curr_is_ev and tgt_pos != curr_pos):
                    _warn_cache_readonly()
                continue

            if curr_managed:
                if changes:
                    warnings.append(f"Managed role '@{curr_name}' is read-only and was skipped.")
                continue

            if (not curr_is_ev) and (not is_guild_owner) and user_top_role_pos is not None and curr_pos >= user_top_role_pos:
                if changes or tgt_pos != curr_pos:
                    errors.append(
                        f"user_role_hierarchy_denied: Role '@{curr_name}' (position {curr_pos}) >= user top role ({user_top_role_pos})."
                    )
                continue

            if (not curr_is_ev) and bot_top_role_pos is not None and curr_pos >= bot_top_role_pos:
                continue

            if changes:
                role_update_ops.append({
                    "op": "update_role",
                    "phase": "roles",
                    "role_id": canon_id,
                    "is_everyone": curr_is_ev,
                    "name": tgt_name,
                    "old_name": curr_name,
                    "changes": changes,
                    "cost_seconds": OP_COST_UPDATE_ROLE,
                    "label": "Update role: @everyone" if curr_is_ev else f"Update role: @{tgt_name}",
                })

            if not curr_is_ev:
                movable_target_roles.append({
                    "id": canon_id,
                    "temp_id": None,
                    "name": tgt_name,
                    "curr_pos": curr_pos,
                    "target_pos": max(1, tgt_pos),
                    "idx": idx,
                    "is_new": False,
                })
            continue

        # Unmatched target role -> skip @everyone/managed, else create_role
        if is_ev:
            continue
        rname = str(r.get("name") or f"Role {idx + 1}").strip()[:100] or f"Role {idx + 1}"
        if bool(r.get("managed", False)):
            warnings.append(f"Managed role '@{rname}' cannot be created and was skipped.")
            continue

        rcolor = normalize_role_color(r.get("color", r.get("color_hex", 0)))
        rhoist = bool(r.get("hoist", False))
        rmentionable = bool(r.get("mentionable", False))
        rperms = normalize_role_permissions(r.get("permissions", r.get("permission_bits", 0)))
        rbits = permissions_to_bitfield(rperms)
        default_new_pos = max(1, len(target_roles) - idx)
        rpos = max(1, _safe_int(r.get("position"), default_new_pos)) if r.get("position") is not None else default_new_pos
        rbmod = normalize_role_bind_module(r.get("bind_role_module"))

        role_create_ops.append({
            "op": "create_role",
            "phase": "roles",
            "temp_id": temp_id,
            "name": rname,
            "color": rcolor,
            "hoist": rhoist,
            "mentionable": rmentionable,
            "permissions": rperms,
            "permissions_bitfield": str(rbits),
            "position": rpos,
            "defer_position": False,
            "bind_role_module": rbmod,
            "cost_seconds": OP_COST_CREATE_ROLE,
            "label": f"Create role: @{rname}",
        })
        movable_target_roles.append({
            "id": None,
            "temp_id": temp_id,
            "name": rname,
            "curr_pos": None,
            "target_pos": rpos,
            "idx": idx,
            "is_new": True,
        })

    # Determine whether a single batch role reorder REST call is needed
    movable_current_roles: List[Dict[str, Any]] = []
    for cid, c_role in roles_by_id.items():
        if _is_everyone_role(c_role) or bool(c_role.get("managed", False)):
            continue
        c_pos = _safe_int(c_role.get("position"), 0)
        if bot_top_role_pos is not None and c_pos >= bot_top_role_pos:
            continue
        if is_cache_mode or bool(c_role.get("_cache_readonly")):
            continue
        movable_current_roles.append({"id": cid, "pos": c_pos})
    movable_current_roles.sort(key=lambda item: (item["pos"], item["id"]))

    matched_target_existing = [m for m in movable_target_roles if not m["is_new"]]
    surviving_ids = {m["id"] for m in matched_target_existing if m["id"]}
    curr_surviving_order = [m["id"] for m in movable_current_roles if m["id"] in surviving_ids]
    tgt_surviving_sorted = sorted(matched_target_existing, key=lambda m: (m["target_pos"], -m["idx"]))
    tgt_surviving_order = [m["id"] for m in tgt_surviving_sorted]

    existing_order_changed = (
        curr_surviving_order != tgt_surviving_order
        or any(m["target_pos"] != m["curr_pos"] for m in matched_target_existing)
    )
    new_roles_need_reorder = bool(role_create_ops) and (
        len(movable_target_roles) >= 2
        or (
            len(movable_target_roles) == 1
            and movable_target_roles[0]["target_pos"] > 1
            and len(movable_current_roles) >= 1
        )
    )
    if (existing_order_changed or new_roles_need_reorder) and movable_target_roles:
        ordered_items = sorted(movable_target_roles, key=lambda m: (m["target_pos"], -m["idx"]))
        role_reorder_ops.append({
            "op": "bulk_reorder_roles",
            "phase": "roles",
            "items": [
                {
                    "id": item["id"],
                    "temp_id": item["temp_id"],
                    "name": item["name"],
                    "position": item["target_pos"],
                }
                for item in ordered_items
            ],
            "cost_seconds": OP_COST_BULK_REORDER_ROLES,
            "label": "Reorder server roles hierarchy",
        })
        for rop in role_create_ops:
            rop["defer_position"] = True

    matched_cat_ids: Set[str] = set()
    matched_ch_ids: Set[str] = set()
    channel_ref_by_temp: Dict[str, str] = {}
    renames_count = 0
    positions_changed = False

    target_cats = [c for c in (tgt.get("categories") or []) if isinstance(c, dict)]
    cat_matches: Dict[int, Optional[Dict[str, Any]]] = {}
    for cat_idx, cat in enumerate(target_cats):
        raw_cat_id = str(cat.get("id") or "").strip()
        if raw_cat_id and raw_cat_id in cats_by_id and raw_cat_id not in matched_cat_ids:
            cat_matches[cat_idx] = cats_by_id[raw_cat_id]
            matched_cat_ids.add(raw_cat_id)
    for cat_idx, cat in enumerate(target_cats):
        if cat_idx in cat_matches:
            continue
        raw_cat_id = str(cat.get("id") or "").strip()
        if not raw_cat_id:
            cname = sanitize_channel_name(str(cat.get("name") or ""), CHANNEL_TYPE_CATEGORY).lower()
            for cid, cobj in cats_by_id.items():
                if cid in matched_cat_ids:
                    continue
                if sanitize_channel_name(str(cobj.get("name") or ""), CHANNEL_TYPE_CATEGORY).lower() == cname:
                    cat_matches[cat_idx] = cobj
                    matched_cat_ids.add(cid)
                    break

    def _plan_channel_list(
        ch_list: List[Dict[str, Any]],
        parent_curr_cat: Optional[Dict[str, Any]],
        parent_real_id: Optional[str],
        parent_temp_id: Optional[str],
        parent_target_overwrites: List[Dict[str, Any]],
    ) -> None:
        nonlocal renames_count, positions_changed

        clean_ch_list = [ch for ch in ch_list if isinstance(ch, dict)]
        ch_matches: Dict[int, Optional[Dict[str, Any]]] = {}
        # Pass 1: explicit IDs
        for ch_idx, ch in enumerate(clean_ch_list):
            raw_id = str(ch.get("id") or "").strip()
            if raw_id and raw_id in channels_by_id and raw_id not in matched_ch_ids:
                ch_matches[ch_idx] = channels_by_id[raw_id]
                matched_ch_ids.add(raw_id)

        # Pass 2: fallback by (sanitized_name, channel_type) within matched parent without reusing matched IDs
        allow_name_match = (parent_real_id is not None) or (parent_curr_cat is None and parent_temp_id is None)
        if allow_name_match:
            for ch_idx, ch in enumerate(clean_ch_list):
                if ch_idx in ch_matches:
                    continue
                raw_id = str(ch.get("id") or "").strip()
                if raw_id:
                    continue
                ch_type = _safe_int(ch.get("type"), CHANNEL_TYPE_TEXT)
                sanitized = sanitize_channel_name(str(ch.get("name") or ""), ch_type).lower()
                for ch_id, ch_obj in channels_by_id.items():
                    if ch_id in matched_ch_ids:
                        continue
                    ch_parent = str(ch_obj.get("parent_id")) if ch_obj.get("parent_id") else None
                    if ch_parent != parent_real_id:
                        continue
                    ctype_curr = _safe_int(ch_obj.get("type"), CHANNEL_TYPE_TEXT)
                    cname_curr = sanitize_channel_name(str(ch_obj.get("name") or ""), ctype_curr).lower()
                    if (cname_curr, ctype_curr) == (sanitized, ch_type):
                        ch_matches[ch_idx] = ch_obj
                        matched_ch_ids.add(ch_id)
                        break

        for ch_idx, ch in enumerate(clean_ch_list):
            ch_type = _safe_int(ch.get("type"), CHANNEL_TYPE_TEXT)
            sanitized_name = sanitize_channel_name(str(ch.get("name") or ""), ch_type)
            target_pos = _safe_int(ch.get("position"), ch_idx)
            temp_id = str(ch.get("temp_id") or f"ch_tmp_{parent_temp_id or 'root'}_{ch_idx}").strip()
            curr_ch = ch_matches.get(ch_idx)

            sync_perms = bool(ch.get("sync_permissions", False))
            raw_overwrites = _clean_overwrites_for_op(ch.get("overwrites"), role_ref_remap)
            effective_overwrites = (
                copy.deepcopy(parent_target_overwrites)
                if (sync_perms and parent_target_overwrites)
                else raw_overwrites
            )

            topic = str(ch.get("topic") or "")[:1024] if ch_type in _TEXT_LIKE_TYPES else ""
            slowmode = max(0, min(21600, _safe_int(ch.get("slowmode"), 0))) if ch_type in _TEXT_LIKE_TYPES else 0
            nsfw = bool(ch.get("nsfw", False))
            bitrate = max(8000, min(384000, _safe_int(ch.get("bitrate"), 64000))) if ch_type == CHANNEL_TYPE_VOICE else 64000
            user_limit = max(0, min(99, _safe_int(ch.get("user_limit"), 0))) if ch_type == CHANNEL_TYPE_VOICE else 0
            bind_module = ch.get("bind_module")

            if curr_ch is None:
                if ch_idx != target_pos:
                    positions_changed = True
                ch_create_ops.append({
                    "op": "create_channel",
                    "phase": "channels",
                    "temp_id": temp_id,
                    "name": sanitized_name,
                    "type": ch_type,
                    "channel_type": ch_type,
                    "category_id": parent_real_id,
                    "category_temp_id": parent_temp_id,
                    "topic": topic,
                    "slowmode": slowmode,
                    "nsfw": nsfw,
                    "bitrate": bitrate,
                    "user_limit": user_limit,
                    "position": target_pos,
                    "sync_permissions": sync_perms,
                    "overwrites": effective_overwrites,
                    "bind_module": bind_module,
                    "cost_seconds": OP_COST_CREATE_CHANNEL,
                    "label": f"Create channel: {sanitized_name}",
                })
                reorder_items.append({
                    "id": None,
                    "temp_id": temp_id,
                    "type": ch_type,
                    "position": target_pos,
                    "parent_id": parent_real_id,
                    "parent_temp_id": parent_temp_id,
                })
                if channels_by_id or cats_by_id:
                    positions_changed = True
                continue

            curr_id = str(curr_ch["id"])
            if temp_id:
                channel_ref_by_temp[temp_id] = curr_id

            # Permission sync / overwrite diff
            curr_ow = _clean_overwrites_for_op(curr_ch.get("overwrites"), role_ref_remap)
            curr_cat_ow_ref = (
                _clean_overwrites_for_op(parent_curr_cat.get("overwrites"), role_ref_remap)
                if parent_curr_cat is not None
                else []
            )
            if "sync_permissions" in curr_ch:
                curr_synced = bool(curr_ch["sync_permissions"])
            elif "permissions_synced" in curr_ch:
                curr_synced = bool(curr_ch["permissions_synced"])
            else:
                curr_synced = is_overwrites_synced(curr_cat_ow_ref, curr_ow)

            if sync_perms and (parent_real_id is not None or parent_temp_id is not None):
                if not is_overwrites_synced(parent_target_overwrites, curr_ow) or not curr_synced:
                    perm_ops.append({
                        "op": "sync_permissions",
                        "phase": "permissions",
                        "channel_id": curr_id,
                        "category_id": parent_real_id,
                        "category_temp_id": parent_temp_id,
                        "name": sanitized_name,
                        "cost_seconds": OP_COST_OVERWRITES,
                        "label": f"Sync permissions: {sanitized_name}",
                    })
            else:
                if canonicalize_overwrites(curr_ow) != canonicalize_overwrites(raw_overwrites):
                    perm_ops.append({
                        "op": "update_overwrites",
                        "phase": "permissions",
                        "target_kind": "channel",
                        "channel_id": curr_id,
                        "name": sanitized_name,
                        "overwrites": raw_overwrites,
                        "cost_seconds": OP_COST_OVERWRITES,
                        "label": f"Update overwrites: {sanitized_name}",
                    })

            # Channel attribute diffs
            changes: Dict[str, Any] = {}
            curr_name = str(curr_ch.get("name") or "")
            target_raw_name = str(ch.get("name") or "").strip()
            rename_warning = False
            # Only a user edit counts as a rename: identical names that merely sanitize
            # differently (emoji / ・ separators) must not produce phantom renames.
            if sanitized_name != curr_name and target_raw_name != curr_name:
                changes["name"] = sanitized_name
                rename_warning = True
                renames_count += 1

            if ch_type in _TEXT_LIKE_TYPES:
                if topic != str(curr_ch.get("topic") or ""):
                    changes["topic"] = topic
                if slowmode != _safe_int(curr_ch.get("slowmode"), 0):
                    changes["slowmode"] = slowmode

            if nsfw != bool(curr_ch.get("nsfw", False)):
                changes["nsfw"] = nsfw

            if ch_type == CHANNEL_TYPE_VOICE:
                if bitrate != _safe_int(curr_ch.get("bitrate"), 64000):
                    changes["bitrate"] = bitrate
                if user_limit != _safe_int(curr_ch.get("user_limit"), 0):
                    changes["user_limit"] = user_limit

            curr_parent_id = str(curr_ch.get("parent_id")) if curr_ch.get("parent_id") else None
            if parent_temp_id is not None and parent_real_id is None:
                changes["category_temp_id"] = parent_temp_id
                positions_changed = True
            elif curr_parent_id != parent_real_id:
                changes["category_id"] = parent_real_id
                positions_changed = True

            if changes:
                update_ops.append({
                    "op": "update_channel",
                    "phase": "updates",
                    "target_kind": "channel",
                    "channel_id": curr_id,
                    "name": sanitized_name,
                    "old_name": curr_name,
                    "new_name": sanitized_name,
                    "changes": changes,
                    "rename_warning": rename_warning,
                    "cost_seconds": OP_COST_UPDATE_CHANNEL,
                    "label": f"Update channel: {sanitized_name}",
                })

            curr_pos = _safe_int(curr_ch.get("position"), ch_idx)
            if curr_pos != target_pos:
                positions_changed = True
            reorder_items.append({
                "id": curr_id,
                "temp_id": None,
                "type": ch_type,
                "position": target_pos,
                "parent_id": parent_real_id,
                "parent_temp_id": parent_temp_id,
            })

    for cat_idx, cat in enumerate(target_cats):
        sanitized_cat_name = sanitize_channel_name(str(cat.get("name") or ""), CHANNEL_TYPE_CATEGORY)
        target_pos = _safe_int(cat.get("position"), cat_idx)
        cat_temp_id = str(cat.get("temp_id") or f"cat_tmp_{cat_idx}").strip()
        curr_cat = cat_matches.get(cat_idx)

        cat_overwrites = _clean_overwrites_for_op(cat.get("overwrites"), role_ref_remap)
        children = cat.get("channels") or []

        if curr_cat is None:
            cat_create_ops.append({
                "op": "create_category",
                "phase": "categories",
                "temp_id": cat_temp_id,
                "name": sanitized_cat_name,
                "position": target_pos,
                "overwrites": cat_overwrites,
                "cost_seconds": OP_COST_CREATE_CATEGORY,
                "label": f"Create category: {sanitized_cat_name}",
            })
            reorder_items.append({
                "id": None,
                "temp_id": cat_temp_id,
                "type": CHANNEL_TYPE_CATEGORY,
                "position": target_pos,
                "parent_id": None,
                "parent_temp_id": None,
            })
            if cat_idx != target_pos or cats_by_id or channels_by_id:
                positions_changed = True
            _plan_channel_list(children, None, None, cat_temp_id, cat_overwrites)
        else:
            curr_cat_id = str(curr_cat["id"])
            curr_cat_ow = _clean_overwrites_for_op(curr_cat.get("overwrites"), role_ref_remap)
            if canonicalize_overwrites(curr_cat_ow) != canonicalize_overwrites(cat_overwrites):
                perm_ops.append({
                    "op": "update_overwrites",
                    "phase": "permissions",
                    "target_kind": "category",
                    "channel_id": curr_cat_id,
                    "name": sanitized_cat_name,
                    "overwrites": cat_overwrites,
                    "cost_seconds": OP_COST_OVERWRITES,
                    "label": f"Update category overwrites: {sanitized_cat_name}",
                })

            curr_cat_name = str(curr_cat.get("name") or "")
            target_cat_raw = str(cat.get("name") or "").strip()
            if sanitized_cat_name != curr_cat_name and target_cat_raw != curr_cat_name:
                renames_count += 1
                update_ops.append({
                    "op": "update_channel",
                    "phase": "updates",
                    "target_kind": "category",
                    "channel_id": curr_cat_id,
                    "name": sanitized_cat_name,
                    "old_name": curr_cat_name,
                    "new_name": sanitized_cat_name,
                    "changes": {"name": sanitized_cat_name},
                    "rename_warning": True,
                    "cost_seconds": OP_COST_UPDATE_CHANNEL,
                    "label": f"Rename category: {sanitized_cat_name}",
                })

            curr_cat_pos = _safe_int(curr_cat.get("position"), cat_idx)
            if curr_cat_pos != target_pos:
                positions_changed = True
            reorder_items.append({
                "id": curr_cat_id,
                "temp_id": None,
                "type": CHANNEL_TYPE_CATEGORY,
                "position": target_pos,
                "parent_id": None,
                "parent_temp_id": None,
            })
            _plan_channel_list(children, curr_cat, curr_cat_id, None, cat_overwrites)

    _plan_channel_list(tgt.get("uncategorized") or [], None, None, None, [])

    if safe_mode or not confirm_deletions:
        projected_total = len(cats_by_id) + len(channels_by_id) + len(cat_create_ops) + len(ch_create_ops)
        if projected_total > MAX_GUILD_CHANNELS:
            errors.append(
                f"Post-apply channel total ({projected_total}) with preserved existing channels exceeds Discord limit of {MAX_GUILD_CHANNELS}."
            )
        for cat_idx, cat in enumerate(target_cats):
            curr_cat = cat_matches.get(cat_idx)
            if curr_cat is None:
                continue
            curr_cat_id = str(curr_cat["id"])
            retained_unmatched = sum(
                1 for cid, ch_obj in channels_by_id.items()
                if cid not in matched_ch_ids and str(ch_obj.get("parent_id") or "") == curr_cat_id
            )
            target_ch_count = len([c for c in (cat.get("channels") or []) if isinstance(c, dict)])
            if target_ch_count + retained_unmatched > MAX_CATEGORY_CHILDREN:
                cat_label = str(cat.get("name") or curr_cat_id)
                errors.append(
                    f"Category '{cat_label}' would reach {target_ch_count + retained_unmatched} channels in Safe Mode, exceeding Discord limit of {MAX_CATEGORY_CHILDREN}."
                )

    if renames_count > 0:
        warnings.append(
            f"Channel/category renames ({renames_count}) are subject to Discord's 2 renames per 10 minutes per-channel rate limit."
        )

    reorder_ops: List[Dict[str, Any]] = []
    if positions_changed and reorder_items:
        reorder_ops.append({
            "op": "bulk_reorder",
            "phase": "reorder",
            "items": reorder_items,
            "cost_seconds": OP_COST_BULK_REORDER,
            "label": "Bulk reorder categories and channels",
        })

    # Deletions: unmatched existing channels, categories, and eligible roles
    delete_targets: List[Dict[str, Any]] = []
    unmatched_channels = [ch for cid, ch in channels_by_id.items() if cid not in matched_ch_ids]
    unmatched_categories = [cat for cid, cat in cats_by_id.items() if cid not in matched_cat_ids]

    for ch in unmatched_channels:
        delete_targets.append({
            "id": str(ch["id"]),
            "name": str(ch.get("name") or ""),
            "type": int(ch.get("type", CHANNEL_TYPE_TEXT) or CHANNEL_TYPE_TEXT),
            "kind": "channel",
            "label": f"Channel: #{ch.get('name') or ch['id']}",
        })
    for cat in unmatched_categories:
        delete_targets.append({
            "id": str(cat["id"]),
            "name": str(cat.get("name") or ""),
            "type": CHANNEL_TYPE_CATEGORY,
            "kind": "category",
            "label": f"Category: {cat.get('name') or cat['id']}",
        })

    protected_set = {str(x).strip() for x in (protected_role_ids or []) if x is not None and str(x).strip()}
    protected_role_skips = 0
    deletable_unmatched_roles: List[Dict[str, Any]] = []
    for rid, c_role in roles_by_id.items():
        if rid in matched_role_ids:
            continue
        if _is_everyone_role(c_role) or bool(c_role.get("managed", False)):
            continue
        c_pos = _safe_int(c_role.get("position"), 0)
        c_name = str(c_role.get("name") or rid)
        if is_cache_mode or bool(c_role.get("_cache_readonly")):
            if not safe_mode:
                _warn_cache_readonly()
                protected_role_skips += 1
            continue
        if bot_top_role_pos is not None and c_pos >= bot_top_role_pos:
            if not safe_mode:
                protected_role_skips += 1
                warnings.append(
                    f"Role '@{c_name}' (position {c_pos}) >= bot top role ({bot_top_role_pos}) cannot be deleted and was skipped."
                )
            continue
        if (not is_guild_owner) and user_top_role_pos is not None and c_pos >= user_top_role_pos:
            if not safe_mode:
                protected_role_skips += 1
                errors.append(
                    f"user_role_hierarchy_denied: Cannot delete role '@{c_name}' (position {c_pos}) >= user top role ({user_top_role_pos})."
                )
            continue
        if rid in protected_set:
            if not safe_mode:
                protected_role_skips += 1
                warnings.append(
                    f"Protected role '@{c_name}' is actively bound to ZerynBot modules and cannot be deleted."
                )
            continue
        deletable_unmatched_roles.append(c_role)
        delete_targets.append({
            "id": rid,
            "name": c_name,
            "type": None,
            "kind": "role",
            "label": f"Role: @{c_name}",
        })

    protected_deletions = (len(delete_targets) if safe_mode else 0) + protected_role_skips
    has_deletions = (not safe_mode) and len(delete_targets) > 0

    if has_deletions and not confirm_deletions:
        warnings.append(
            f"{len(delete_targets)} existing channel(s)/category(s)/role(s) would be deleted; set confirm_deletions=True to execute deletions."
        )

    if not safe_mode and confirm_deletions:
        # Children MUST be deleted before categories; roles deleted after channels/categories
        for ch in unmatched_channels:
            ch_name = str(ch.get("name") or ch["id"])
            delete_ch_ops.append({
                "op": "delete_channel",
                "phase": "deletions",
                "channel_id": str(ch["id"]),
                "name": ch_name,
                "type": int(ch.get("type", CHANNEL_TYPE_TEXT) or CHANNEL_TYPE_TEXT),
                "cost_seconds": OP_COST_DELETE,
                "label": f"Delete channel: {ch_name}",
            })
        for cat in unmatched_categories:
            cat_name = str(cat.get("name") or cat["id"])
            delete_cat_ops.append({
                "op": "delete_category",
                "phase": "deletions",
                "channel_id": str(cat["id"]),
                "name": cat_name,
                "type": CHANNEL_TYPE_CATEGORY,
                "cost_seconds": OP_COST_DELETE,
                "label": f"Delete category: {cat_name}",
            })
        for c_role in deletable_unmatched_roles:
            r_id = str(c_role["id"])
            r_name = str(c_role.get("name") or r_id)
            delete_role_ops.append({
                "op": "delete_role",
                "phase": "deletions",
                "role_id": r_id,
                "name": r_name,
                "cost_seconds": OP_COST_DELETE,
                "label": f"Delete role: @{r_name}",
            })

    projected_roles = len(roles_by_id) + len(role_create_ops) - len(delete_role_ops)
    if projected_roles > MAX_GUILD_ROLES:
        errors.append(
            f"Post-apply role total ({projected_roles}) exceeds Discord limit of {MAX_GUILD_ROLES}."
        )
    elif (not safe_mode and confirm_deletions) and (len(roles_by_id) + len(role_create_ops) > MAX_GUILD_ROLES):
        warnings.append(
            f"Peak role count during creation ({len(roles_by_id) + len(role_create_ops)}) exceeds Discord's {MAX_GUILD_ROLES} limit before deletions run."
        )

    if errors:
        return {
            "summary": _empty_diff_summary(safe_mode, confirm_deletions),
            "operations": [],
            "eta_seconds": 0.0,
            "warnings": warnings,
            "errors": errors,
        }

    raw_current_bindings = curr.get("bindings")
    current_bindings: Dict[str, str] = {}
    if isinstance(raw_current_bindings, dict):
        for key, value in raw_current_bindings.items():
            if not _is_valid_binding_token(key) or not _is_valid_binding_token(value):
                continue
            raw_k = str(key).strip()
            canon_k = normalize_role_bind_module(raw_k) or raw_k
            current_bindings[canon_k] = str(value).strip()

    deleted_role_ids = {op["role_id"] for op in delete_role_ops}
    resolved_bindings, explicit_role_unbinds = _resolve_bindings_and_unbinds(
        tgt,
        channel_ref_by_temp,
        role_ref_remap=role_ref_remap,
        current_bindings=current_bindings,
        deleted_role_ids=deleted_role_ids,
    )
    bindings_payload: Dict[str, Any] = dict(resolved_bindings)
    for k in sorted(explicit_role_unbinds):
        if k in current_bindings and k not in bindings_payload:
            bindings_payload[k] = None

    changed_bindings = {
        key: value for key, value in bindings_payload.items()
        if current_bindings.get(key) != value
    }
    if bindings_payload and changed_bindings:
        bind_ops.append({
            "op": "bind_modules",
            "phase": "bindings",
            "bindings": bindings_payload,
            "cost_seconds": OP_COST_BIND_MODULES,
            "label": "Bind ZerynBot modules",
        })

    operations: List[Dict[str, Any]] = [
        *role_create_ops,
        *role_update_ops,
        *role_reorder_ops,
        *cat_create_ops,
        *ch_create_ops,
        *perm_ops,
        *update_ops,
        *reorder_ops,
        *delete_ch_ops,
        *delete_cat_ops,
        *delete_role_ops,
        *bind_ops,
    ]

    eta_seconds = round(sum(float(op.get("cost_seconds", 1.0)) for op in operations), 2)

    summary = {
        "total_operations": len(operations),
        "create_roles": len(role_create_ops),
        "update_roles": len(role_update_ops),
        "reorder_roles": bool(role_reorder_ops),
        "bulk_reorder_roles": bool(role_reorder_ops),
        "delete_roles": len(delete_role_ops),
        "create_categories": len(cat_create_ops),
        "create_channels": len(ch_create_ops),
        "sync_permissions": sum(1 for op in perm_ops if op["op"] == "sync_permissions"),
        "update_overwrites": sum(1 for op in perm_ops if op["op"] == "update_overwrites"),
        "update_channels": len(update_ops),
        "renames": renames_count,
        "rename_warning": renames_count > 0,
        "bulk_reorder": bool(reorder_ops),
        "delete_channels": len(delete_ch_ops),
        "delete_categories": len(delete_cat_ops),
        "has_deletions": has_deletions,
        "delete_targets": delete_targets,
        "protected_deletions": protected_deletions,
        "bind_modules": bool(bind_ops),
        "safe_mode": bool(safe_mode),
        "confirm_deletions": bool(confirm_deletions),
    }

    return {
        "summary": summary,
        "operations": operations,
        "eta_seconds": eta_seconds,
        "warnings": warnings,
        "errors": errors,
    }


def recalibrate_eta(
    completed_steps: int,
    elapsed_seconds: float,
    remaining_baseline_cost: float,
    prev_avg: Optional[float] = None,
    rate_limit_until: float = 0.0,
    now: Optional[float] = None,
) -> Tuple[float, float]:
    """Recalculate remaining ETA and EMA step duration (0.7 * actual + 0.3 * baseline)."""
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    now_ts = time.time() if now is None else _finite(now, time.time())
    rl_wait = max(0.0, _finite(rate_limit_until) - now_ts)
    remaining_cost = max(0.0, _finite(remaining_baseline_cost))
    try:
        completed = max(0, int(completed_steps or 0))
    except (TypeError, ValueError):
        completed = 0
    elapsed = max(0.0, _finite(elapsed_seconds))
    candidate_baseline = _finite(prev_avg, 1.0) if prev_avg is not None else 1.0
    baseline = candidate_baseline if candidate_baseline > 0 else 1.0

    if completed > 0:
        actual_avg = elapsed / completed
        ema_avg = 0.7 * actual_avg + 0.3 * baseline
    else:
        ema_avg = baseline

    eta = remaining_cost * ema_avg + rl_wait
    return (round(max(0.0, eta), 2), round(max(0.0, ema_avg), 4))
