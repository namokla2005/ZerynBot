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
    "zb_welcome": 1545451792785997874,
    "zb_goodbye": 1545451723458347158,
    "zb_autorole": 1545451661307420902,
    "zb_logger": 1545451740248145930,
    "zb_tempvoice": 1545451779506839552,
    "zb_levelup": 1545451733881192541,

    # ─── 2. Economy & Jobs (10 Emojis) ────────────────────────────────────────
    "zb_coin": 1545451715623395368,
    "zb_bank": 1545451665123975320,
    "zb_work": 1545451794749202532,
    "zb_fish": 1545451721679962195,
    "zb_hunt": 1545451725241065645,
    "zb_inventory": 1545451726960594944,
    "zb_sell": 1545451760443719761,
    "zb_shop": 1545451771416158318,
    "zb_coinflip": 1545451719222362212,
    "zb_slots": 1545451776218767471,

    # ─── 3. AI & Web (4 Emojis) ───────────────────────────────────────────────
    "zb_ask": 1545451658966999124,
    "zb_web_search": 1545451789883539518,
    "zb_summarize": 1545451777883639850,
    "zb_vision": 1545451786201210970,

    # ─── 4. Moderation & Security (6 Emojis) ──────────────────────────────────
    "zb_ban": 1545451663257772142,
    "zb_kick": 1545451729707999332,
    "zb_timeout": 1545451781889462332,
    "zb_warn": 1545451788143169546,
    "zb_clear": 1545451703690592286,
    "zb_lock": 1545451735613702224,

    # ─── 5. Music & Player (6 Emojis) ─────────────────────────────────────────
    "zb_play": 1545451751019249684,
    "zb_lofi": 1545451737354346566,
    "zb_pause": 1545451747240181870,
    "zb_skip": 1545451774058569789,
    "zb_loop": 1545451743221907569,
    "zb_queue": 1545451754445869227,

    # ─── 6. Social, Leveling & Utility (8 Emojis) ─────────────────────────────
    "zb_rank": 1545451756463456328,
    "zb_leaderboard": 1545451732006346873,
    "zb_marry": 1545451745386172526,
    "zb_ship": 1545451769046241332,
    "zb_ping": 1545451749186347039,
    "zb_poll": 1545451752717942926,
    "zb_reminder": 1545451758782775409,
    "zb_verified": 1545451784309575850,

    # ─── 7. Categories for /help (16 Emojis) ──────────────────────────────────
    "zb_cat_home": 1545451683490824283,
    "zb_cat_ai": 1545451666541645845,
    "zb_cat_economy": 1545451675035369502,
    "zb_cat_fun": 1545451677707018362,
    "zb_cat_music": 1545451693242843247,
    "zb_cat_moderation": 1545451691099291868,
    "zb_cat_automod": 1545451668659904562,
    "zb_cat_leveling": 1545451688779972678,
    "zb_cat_voice": 1545451702067531936,
    "zb_cat_info": 1545451686838145034,
    "zb_cat_utility": 1545451700226097203,
    "zb_cat_giveaway": 1545451679758160013,
    "zb_cat_tickets": 1545451697961308263,
    "zb_cat_birthday": 1545451670475903029,
    "zb_cat_customcmd": 1545451672870985748,
    "zb_cat_roles": 1545451695805304872,
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


def clean_title(title: str) -> str:
    """Loại bỏ các emoji/biểu tượng Unicode mặc định ở đầu tiêu đề."""
    if not title:
        return ""
    import re
    return re.sub(r'^[^\w\s\(\)\[\]#\-•|]+\s*', '', title).strip()


def embed_title(emoji_name: str, raw_title: str) -> str:
    """Tạo tiêu đề embed chuẩn: <custom_emoji> <Nội dung đã lọc bỏ emoji cũ>."""
    custom = e(emoji_name)
    cleaned = clean_title(raw_title)
    if custom:
        return f"{custom} {cleaned}" if cleaned else custom
    return raw_title

