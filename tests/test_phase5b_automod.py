"""Tests Phase 5b — automod không còn bị qua mặt bằng edit / embed / Unicode.

Mỗi test kiểm một lối bypass cụ thể mà bản cũ cho qua.
"""
import asyncio
import types

import pytest


def _cog(recorded):
    from cogs.automod import Automod

    cog = Automod.__new__(Automod)

    async def fake_handle(message, reason, settings):
        recorded.append(reason)

    cog._handle_violation = fake_handle
    return cog


SETTINGS_LINKS = {"links_enabled": 1, "bad_words_enabled": 0, "anti_invite_enabled": 0,
                  "whitelist_links": [], "blacklist_links": [], "bad_words": []}
SETTINGS_WORDS = {"links_enabled": 0, "bad_words_enabled": 1, "anti_invite_enabled": 0,
                  "whitelist_links": [], "blacklist_links": [],
                  "bad_words": ["discord-nitro", "freenitro"]}
SETTINGS_INVITE = {"links_enabled": 0, "bad_words_enabled": 0, "anti_invite_enabled": 1,
                   "whitelist_links": [], "blacklist_links": [], "bad_words": []}


def _msg(content="", embeds=None, stickers=None, attachments=None):
    def emb(title="", description="", url="", fields=(), footer="", author=""):
        return types.SimpleNamespace(
            title=title, description=description, url=url,
            fields=[types.SimpleNamespace(name=n, value=v) for n, v in fields],
            footer=types.SimpleNamespace(text=footer) if footer else None,
            author=types.SimpleNamespace(name=author) if author else None,
        )

    return types.SimpleNamespace(
        content=content,
        guild=object(),
        embeds=embeds or [],
        stickers=stickers or [],
        attachments=attachments or [],
    )


# ─── Chuẩn hóa Unicode ────────────────────────────────────────────────────────

def test_normalize_kills_homoglyph_and_zero_width():
    from cogs.automod import normalize_scan_text

    assert "discord-nitro" in normalize_scan_text("dіscord-nіtro")   # i Cyrillic
    assert "freenitro" in normalize_scan_text("free​nitro")  # zero-width space
    assert "nitro" in normalize_scan_text("ｎｉｔｒｏ")        # fullwidth
    assert normalize_scan_text("") == ""


def test_scan_text_covers_embeds_stickers_attachments():
    import types

    from cogs.automod import message_scan_text

    embed = types.SimpleNamespace(
        title="Free Nitro", description="xem tại http://scam-mirror.example/gift", url="",
        fields=[types.SimpleNamespace(name="Bước 1", value="dán link discord-nitro")],
        footer=types.SimpleNamespace(text="hết hạn soon"),
        author=types.SimpleNamespace(name="Discord Support"),
    )
    sticker = types.SimpleNamespace(name="freenitro", description="")
    att = types.SimpleNamespace(url="http://evil.example/payload.exe")
    text = message_scan_text(_msg("hello", embeds=[embed], stickers=[sticker], attachments=[att]))
    for needle in ("scam-mirror.example", "discord-nitro", "freenitro", "evil.example/payload.exe"):
        assert needle in text, f"thiếu {needle} trong văn bản quét được"


# ─── Luật chạy trên nội dung đã quét ──────────────────────────────────────────

def test_link_hidden_in_embed_description_is_caught():
    from cogs.automod import Automod, message_scan_text

    recorded = []
    cog = _cog(recorded)
    embed = types.SimpleNamespace(
        title="Quà tặng", description="Nhận quà: http://scam-mirror.example/gift", url="",
        fields=[], footer=None, author=None,
    )
    message = _msg("", embeds=[embed])
    hit = asyncio.run(cog._check_text_rules(message, SETTINGS_LINKS, message_scan_text(message)))
    assert hit is True and recorded, "link nằm trong embed description bị bỏ qua"


def test_bad_word_with_homoglyph_is_caught():
    from cogs.automod import Automod, message_scan_text

    recorded = []
    cog = _cog(recorded)
    message = _msg("dіscord-nіtro ở đây")
    hit = asyncio.run(cog._check_text_rules(message, SETTINGS_WORDS, message_scan_text(message)))
    assert hit is True and recorded, "từ cấm viết bằng ký tự Cyrillic vẫn lọt"


def test_invite_inside_embed_is_caught():
    from cogs.automod import message_scan_text

    recorded = []
    cog = _cog(recorded)
    embed = types.SimpleNamespace(
        title="Tham gia", description="", url="https://discord.gg/inviteme",
        fields=[], footer=None, author=None,
    )
    message = _msg("", embeds=[embed])
    hit = asyncio.run(cog._check_text_rules(message, SETTINGS_INVITE, message_scan_text(message)))
    assert hit is True and recorded, "link mời ở embed url không bị chặn"


def test_whitelisted_domain_still_passes():
    from cogs.automod import message_scan_text

    recorded = []
    cog = _cog(recorded)
    settings = dict(SETTINGS_LINKS, whitelist_links=["youtube.com"])
    message = _msg("xem https://www.youtube.com/watch?v=abc")
    hit = asyncio.run(cog._check_text_rules(message, settings, message_scan_text(message)))
    assert hit is False and not recorded, "domain whitelist lại bị chặn (regression)"


def test_clean_message_trips_nothing():
    from cogs.automod import message_scan_text

    recorded = []
    cog = _cog(recorded)
    message = _msg("hôm nay ổn không bạn")
    for settings in (SETTINGS_LINKS, SETTINGS_WORDS, SETTINGS_INVITE):
        assert asyncio.run(cog._check_text_rules(message, settings, message_scan_text(message))) is False
    assert not recorded


# ─── on_message_edit ──────────────────────────────────────────────────────────

def test_edit_listener_exists_and_shares_rules():
    import inspect

    from cogs.automod import Automod

    src = inspect.getsource(Automod.on_message_edit)
    assert "_check_text_rules" in src, "on_message_edit không dùng chung luật với on_message"
    assert "_automod_gate" in src, "on_message_edit bỏ qua các miễn nhiễm (admin/bot/kênh)"


def test_on_message_uses_same_gate_as_edit():
    import inspect

    from cogs.automod import Automod

    assert "_automod_gate" in inspect.getsource(Automod.on_message)
    assert "message_scan_text" in inspect.getsource(Automod.on_message)


def test_edit_of_clean_message_short_circuits():
    """Không được đốt DB/luật cho mỗi lần sửa tin nhắn vô hại."""
    recorded = []
    cog = _cog(recorded)
    gates = []

    async def fake_gate(message):
        gates.append(message)
        return SETTINGS_LINKS

    cog._automod_gate = fake_gate

    before = _msg("bình thường")
    after = _msg("bình thường")
    asyncio.run(cog.on_message_edit(before, after))
    assert gates == [], "tin sửa không đổi nội dung vẫn bị xét -> tốn DB mỗi lần edit"

    after2 = _msg("http://scam-mirror.example/x")
    asyncio.run(cog.on_message_edit(before, after2))
    assert recorded, "edit thành link lừa đảo phải bị xử lý"


# ─── Regression cho chinh lloi do tao rapid trong phase 5b ────────────────────

def _member_message(guild_id="777", content="hello"):
    """Message cua thanh vien thuong, du cho on_message chay het nhanh spam."""
    perms = types.SimpleNamespace(manage_messages=False, administrator=False)
    author = types.SimpleNamespace(
        id=4242, bot=False, guild_permissions=perms, roles=[], mention="<@4242>",
    )
    channel = types.SimpleNamespace(id=5150, name="general")
    guild = types.SimpleNamespace(id=int(guild_id), owner=object(), name="G")
    author.guild = guild
    return types.SimpleNamespace(
        author=author, guild=guild, channel=channel, content=content,
        embeds=[], stickers=[], attachments=[], mentions=[], role_mentions=[],
    )


def test_on_message_spam_path_has_guild_id():
    """`guild_id` bi mat khai bao khi tach _automod_gate -> NameError moi tin nhan.

    Fast check: spam rule dung self.spam_cache[guild_id], nam ben duoi doan gate.
    """
    from collections import defaultdict

    from cogs.automod import Automod

    cog = Automod.__new__(Automod)
    cog.spam_cache = defaultdict(lambda: defaultdict(list))
    handled = []

    async def fake_gate(message):
        return {"spam_enabled": 1, "spam_allowed_channels": [], "links_enabled": 0,
                "bad_words_enabled": 0, "anti_invite_enabled": 0, "anti_caps_enabled": 0,
                "anti_mentions_enabled": 0, "whitelist_links": [], "blacklist_links": [],
                "bad_words": []}

    async def fake_handle(message, reason, settings):
        handled.append(reason)

    async def fake_check(message, settings, content):
        return False

    cog._automod_gate = fake_gate
    cog._handle_violation = fake_handle
    cog._check_text_rules = fake_check

    for _ in range(7):
        asyncio.run(cog.on_message(_member_message()))
    assert handled, "spam du 7 tin lien tiep ma khong xu ly -> nhanh spam khong chay"
