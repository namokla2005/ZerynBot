"""
emojis.py — Quản lý tập trung toàn bộ 56 Custom Application Emojis cho ZerynBot V2.
Cung cấp các hàm e() và partial() để tích hợp vào Embed, Message, Button, SelectMenu.
"""
from typing import Optional

try:
    import discord
except ImportError:
    discord = None

EMOJIS: dict[str, int] = {
    # ─── 1. Automated Modules & Events (6 Emojis) ─────────────────────────────
    "zb_welcome": 1545431231938699314,
    "zb_goodbye": 1545431223688499350,
    "zb_autorole": 1545431221587157032,
    "zb_logger": 1545431227790659734,
    "zb_tempvoice": 1545431229585956915,
    "zb_levelup": 1545431225781592084,

    # ─── 2. Economy & Jobs (10 Emojis) ────────────────────────────────────────
    "zb_coin": 1545430919425556531,
    "zb_bank": 1545430877289582592,
    "zb_work": 1545430983086440538,
    "zb_fish": 1545430924500533280,
    "zb_hunt": 1545430927079903304,
    "zb_inventory": 1545430929030520864,
    "zb_sell": 1545430961108422806,
    "zb_shop": 1545430964446961718,
    "zb_coinflip": 1545430922701054002,
    "zb_slots": 1545430968817557626,

    # ─── 3. AI & Web (4 Emojis) ───────────────────────────────────────────────
    "zb_ask": 1545430872835231874,
    "zb_web_search": 1545430980754415697,
    "zb_summarize": 1545430970918764604,
    "zb_vision": 1545430976921083974,

    # ─── 4. Moderation & Security (6 Emojis) ──────────────────────────────────
    "zb_ban": 1545430875184038068,
    "zb_kick": 1545430930875748423,
    "zb_timeout": 1545430973032833134,
    "zb_warn": 1545430979085340692,
    "zb_clear": 1545430917319884860,
    "zb_lock": 1545430935145816094,

    # ─── 5. Music & Player (6 Emojis) ─────────────────────────────────────────
    "zb_play": 1545430949649448980,
    "zb_lofi": 1545430937150562354,
    "zb_pause": 1545430944972804156,
    "zb_skip": 1545430966858817587,
    "zb_loop": 1545430939612745778,
    "zb_queue": 1545430954502529095,

    # ─── 6. Social, Leveling & Utility (8 Emojis) ─────────────────────────────
    "zb_rank": 1545430957136420994,
    "zb_leaderboard": 1545430933157453926,
    "zb_marry": 1545430942196174888,
    "zb_ship": 1545430962928746536,
    "zb_ping": 1545430947166421082,
    "zb_poll": 1545430951759446027,
    "zb_reminder": 1545430958982037534,
    "zb_verified": 1545430974832050276,

    # ─── 7. Categories for /help (16 Emojis) ──────────────────────────────────
    "zb_cat_home": 1545430897023520859,
    "zb_cat_ai": 1545430879525146655,
    "zb_cat_economy": 1545430887770882089,
    "zb_cat_fun": 1545430889973157960,
    "zb_cat_music": 1545430906041540660,
    "zb_cat_moderation": 1545430903998779484,
    "zb_cat_automod": 1545430881672499330,
    "zb_cat_leveling": 1545430901700173945,
    "zb_cat_voice": 1545430915285647410,
    "zb_cat_info": 1545430899439702188,
    "zb_cat_utility": 1545430913121394688,
    "zb_cat_giveaway": 1545430891470389249,
    "zb_cat_tickets": 1545430910793416704,
    "zb_cat_birthday": 1545430883765452894,
    "zb_cat_customcmd": 1545430885799694436,
    "zb_cat_roles": 1545430908482494474,
}


def e(name: str, default: str = "") -> str:
    """
    Trả về định dạng emoji cho Discord Markdown (ví dụ: `<:zb_coin:1545430919425556531>`).
    Nếu emoji không tồn tại trong danh sách, trả về chuỗi `default`.
    """
    emoji_id = EMOJIS.get(name)
    if emoji_id:
        return f"<:{name}:{emoji_id}>"
    return default


def partial(name: str, fallback_emoji: Optional[str] = None):
    """
    Trả về `discord.PartialEmoji` cho các thành phần UI như `Button(emoji=...)` hoặc `SelectOption(emoji=...)`.
    Nếu không tìm thấy emoji_id, trả về `fallback_emoji`.
    """
    emoji_id = EMOJIS.get(name)
    if emoji_id:
        if discord is not None:
            return discord.PartialEmoji(name=name, id=emoji_id)
        return f"<:{name}:{emoji_id}>"
    return fallback_emoji
