"""Automod full matrix — ma trận test toàn diện cho bot/cogs/automod.py.

Mục tiêu: liệt kê & khóa hành vi cho MỌI lối vào/đường lách đã biết của automod:
- Cái gì PHẢI bị chặn (spam, link lạ, invite, telegram, từ cấm, caps, mention,
  link giả mạo/lừa đảo, chiêu lách Unicode/markdown/khoảng trắng...).
- Cái gì PHẢI cho qua (domain an toàn, email, tên file, số phiên bản, tin hợp lệ...).
- Các GAP đã biết (hiện chưa chặn được) được đánh dấu `xfail` — khi code vá xong,
  pytest sẽ tự báo XPASS.

Bối cảnh sự cố thật (khóa regression):
- Bạn của user gửi link `t.me/group` → bị timeout 5 phút (link filter hoạt động đúng).
- Bạn của user gửi file ảnh .png từ Discord CDN → TỪNG bị timeout oan 30 phút vì
  lỗi cũ coi `image.png` trong URL attachment là domain; đã sửa ở phase 7.

Liên quan các file khác (không trùng lặp nội dung, chỉ bổ sung):
- tests/test_phase5b_automod.py     — bypass qua edit/embed/Unicode cơ bản
- tests/test_phase7_automod_links.py — filename trong URL ≠ domain
- tests/test_phase7_automod_recovery.py — raid unlock / nuke exempt
"""
import asyncio
import time
import types
from collections import defaultdict

import discord
import pytest

import cogs.automod as am
from cogs.automod import Automod, count_emoji_units, extract_domains, message_scan_text, normalize_scan_text

# ─── Tiện ích chung ───────────────────────────────────────────────────────────

ZERO_WIDTH = "\u200b"          # zero-width space
ZWJ = "\u200d"                 # zero-width joiner
CYR_I = "\u0456"               # і Cyrillic (nhìn như i)
CYR_E = "\u0435"               # е Cyrillic (nhìn như e)
CYR_M = "\u043c"               # м Cyrillic (nhìn như m)
CYR_T = "\u0442"               # т Cyrillic (nhìn như t)
CYR_D = "\u0434"               # д Cyrillic (nhìn như d)
CYR_A = "\u0430"               # а Cyrillic (nhìn như a)
CYR_G_SCRIPT = "\u0261"        # ɡ Latin small script g (nhìn như g)
DOTLESS_I = "\u0131"           # ı dotsız i
IDEOGRAPHIC_DOT = "\u3002"     # 。 ideographic full stop
FULLWIDTH_T = "\uff54"         # ｔ
MULTI_ZW = ZERO_WIDTH + ZWJ


def _cog(recorded):
    """Cog tối giản: ghi lại lý do vi phạm thay vì đụng Discord API."""
    cog = Automod.__new__(Automod)
    cog.spam_cache = defaultdict(lambda: defaultdict(list))

    async def fake_handle(message, reason, settings):
        recorded.append(reason)

    cog._handle_violation = fake_handle
    return cog


def _msg(content="", embeds=None, stickers=None, attachments=None, poll=None):
    return types.SimpleNamespace(
        content=content,
        guild=object(),
        embeds=embeds or [],
        stickers=stickers or [],
        attachments=attachments or [],
        poll=poll,
    )


def _attachment(url):
    return types.SimpleNamespace(url=url)


def _run_rules(cog, message, settings):
    return asyncio.run(cog._check_text_rules(message, settings, message_scan_text(message)))


def _assert_blocked(message, settings, needle=None):
    recorded = []
    hit = _run_rules(_cog(recorded), message, settings)
    assert hit is True and recorded, f"KHÔNG bị chặn dù phải chặn: {message.content!r}"
    if needle:
        assert needle in recorded[0], f"lý do thiếu {needle!r}: {recorded[0]!r}"
    return recorded[0]


def _assert_passed(message, settings):
    recorded = []
    hit = _run_rules(_cog(recorded), message, settings)
    assert hit is False and not recorded, f"BỊ chặn dù phải cho qua: {message.content!r} → {recorded}"


# Các tổ hợp settings theo tính năng (khớp key thật trong database/community.py)
S_LINKS = {"links_enabled": 1, "bad_words_enabled": 0, "anti_invite_enabled": 0,
           "whitelist_links": [], "blacklist_links": [], "bad_words": []}
S_INVITE = {"links_enabled": 0, "bad_words_enabled": 0, "anti_invite_enabled": 1,
            "whitelist_links": [], "blacklist_links": [], "bad_words": []}
S_WORDS = {"links_enabled": 0, "bad_words_enabled": 1, "anti_invite_enabled": 0,
           "whitelist_links": [], "blacklist_links": [],
           "bad_words": ["freenitro", "discord-nitro"]}
S_OFF = {"links_enabled": 0, "bad_words_enabled": 0, "anti_invite_enabled": 0,
         "whitelist_links": [], "blacklist_links": [], "bad_words": []}


# ─── 1. Chuẩn hóa Unicode ─────────────────────────────────────────────────────

def test_normalize_strips_zero_width_and_lowercases():
    assert normalize_scan_text(f"FREE{ZERO_WIDTH}NITRO") == "freenitro"
    assert normalize_scan_text(f"Free{ZWJ}Nitro") == "freenitro"


def test_normalize_folds_fullwidth_and_lookalikes():
    assert normalize_scan_text("ｎｉｔｒｏ") == "nitro"          # fullwidth
    assert "discord-nitro" in normalize_scan_text(f"d{CYR_I}scord-nitro")   # і→i
    assert "t.me" in normalize_scan_text(f"t.{CYR_M}e")                    # м→m


def test_normalize_strips_combining_marks():
    # `nítro` tách thành n+i+combining → phải khớp `nitro`
    assert normalize_scan_text("ni\u0301tro") == "nitro"


def test_normalize_handles_empty_and_none():
    assert normalize_scan_text("") == ""
    assert normalize_scan_text(None) == ""


# ─── 2. Trích xuất domain ─────────────────────────────────────────────────────

def test_extract_url_host_not_path_filename():
    text = normalize_scan_text("xem https://cdn.discordapp.com/attachments/1/2/image.png")
    assert extract_domains(text) == [("cdn.discordapp.com", "url")]


def test_extract_bare_domain_with_path_returns_host_only():
    assert extract_domains(am.normalize_scan_text("vào example.com/image.png nhé")) == [("example.com", "bare")]


def test_extract_email_domain_is_ignored():
    assert extract_domains(am.normalize_scan_text("mail mình: abc@gmail.com")) == []


def test_extract_userinfo_uses_real_host():
    assert extract_domains(am.normalize_scan_text("https://user:pass@evil.example/x")) == [("evil.example", "url")]


def test_extract_strips_trailing_punctuation():
    assert extract_domains(am.normalize_scan_text("link: https://example.com/x.")) == [("example.com", "url")]
    assert extract_domains(am.normalize_scan_text("(https://example.com/x)")) == [("example.com", "url")]


# ─── 3. Link filter — PHẢI CHẶN ───────────────────────────────────────────────

LINK_BLOCK_CASES = [
    # Sự cố thật
    "t.me/group",
    "https://t.me/group",
    "mọi người vào t.me/group nhé",
    # Telegram biến thể
    "http://t.me/joinchat/AAAAAE123",
    "https://t.me/group?start=123",
    "T.ME/GROUP",
    "telegram.me/abc",
    "telegram.org/abc",
    "telegram.dog/abc",
    # Chiêu lách Unicode với t.me
    f"t{ZERO_WIDTH}.me/group",
    f"t.{CYR_M}e/group",
    f"{FULLWIDTH_T}\uff0e\uff4d\uff45/group",
    f"t{IDEOGRAPHIC_DOT}me/group",
    # URL shortener / domain lạ
    "bit.ly/xyz",
    "tinyurl.com/abc",
    "cutt.ly/abc",
    "goo.gl/abc",
    "is.gd/abc",
    "https://example.com/page",
    "sub.example.com/path",
    "shop.biz/khuyen-mai",
    # Giả mạo domain an toàn bằng subdomain (spoof)
    "https://youtube.com.evil.io/watch",
    "https://discord.com.evil.example/",
    # URL trong markdown/angle/spoiler/code — vẫn là link
    "[vào đây](https://t.me/group)",
    "<https://t.me/group>",
    "||https://t.me/group||",
    "`https://t.me/group`",
    "（https://t.me/group）",
    # Homoglyph Cyrillic / punycode — kiểm chứng thực nghiệm: CHẶN được
    f"{CYR_T}.me/group",                    # т→t
    f"{CYR_T}.{CYR_E}.me/group",            # т.е → t.e
    "https://xn--80ak6aa92e.com/x",         # host punycode (IDN giả dạng)
    # Defang / phá scheme — vẫn bị bắt qua domain trần
    "hxxps://t.me/group",                   # hxxp defanged
    "https:// t.me/group",                  # khoảng trắng sau //
    "https:/\\t.me/group",                  # slash hỗn hợp
    # Từ nghiên cứu web (đã probe thực nghiệm: CHẶN được)
    "https://t-elegram.me/group",           # lookalike gạch ngang
    "tel\u0435gram.me/group",               # Cyrillic е → telegram.me
    "telegr\u0430m.me/group",               # Cyrillic а → telegram.me
    "https://\u0440\u0430ypal.com/login",   # Cyrillic р+а → paypal.com (phishing)
    "https://t.\tme/group",                 # TAB trong hostname
    "https://discord.\ngg/abc123",          # newline trong hostname
]


@pytest.mark.parametrize("content", LINK_BLOCK_CASES)
def test_link_must_block_unknown_and_evasions(content):
    _assert_blocked(_msg(content), S_LINKS, needle="không rõ nguồn gốc")


def test_tme_incident_is_blocked_with_reason():
    """Sự cố 'bạn gửi t.me/group bị timeout': lý do phải đúng loại link."""
    reason = _assert_blocked(_msg("https://t.me/group"), S_LINKS)
    assert "t.me" in reason


def test_link_filter_off_then_tme_passes():
    """Tắt link filter → t.me không còn bị chặn (đúng theo toggle)."""
    _assert_passed(_msg("https://t.me/group"), S_OFF)


# ─── 4. Link filter — PHẢI CHO QUA ────────────────────────────────────────────

LINK_PASS_CASES = [
    "https://www.youtube.com/watch?v=abc",
    "https://youtu.be/abc",
    "https://m.youtube.com/watch?v=abc",
    "https://music.youtube.com/watch?v=abc",
    "https://facebook.com/page",
    "https://fb.com/x",
    "https://google.com/search?q=x",
    "https://google.com.vn/x",
    "https://github.com/a/b",
    "https://tenor.com/view/x",
    "https://giphy.com/gifs/x",
    "https://twitter.com/x",
    "https://x.com/x",
    "https://instagram.com/x",
    "https://tiktok.com/@x",
    "https://imgur.com/x",
    "https://reddit.com/r/x",
    "https://open.spotify.com/track/x",
    "https://twitch.tv/x",
    "https://steamcommunity.com/x",
    "https://roblox.com/games/x",
    "https://discord.com/channels/1/2/3",
    "https://cdn.discordapp.net/attachments/1/2/a.png",
    "discord.gg",
    # Không phải link
    "mail mình: abc@gmail.com",
    "phiên bản 3.14.159 mới ra",
    "file gửi kèm là image.png nhé",
    "ảnh photo.jpeg với video.mp4 đều ổn",
    "bundle app.min.js chạy tốt",
    "hôm nay trời đẹp, đi chơi không?",
]


@pytest.mark.parametrize("content", LINK_PASS_CASES)
def test_link_must_pass_safe_and_nonlinks(content):
    _assert_passed(_msg(content), S_LINKS)


def test_long_clean_message_passes():
    """Tin sạch 4000 ký tự (sát giới hạn Discord) không bị chặn và không treo."""
    _assert_passed(_msg("a" * 4000), S_LINKS)


# ─── 5. Link filter — Whitelist / Blacklist / global scam keyword ─────────────

def test_whitelist_exact_and_subdomain_pass():
    s = dict(S_LINKS, whitelist_links=["example.com"])
    _assert_passed(_msg("xem example.com nhé"), s)
    _assert_passed(_msg("xem sub.example.com/path nhé"), s)


def test_whitelist_does_not_cover_lookalike_domain():
    s = dict(S_LINKS, whitelist_links=["example.com"])
    _assert_blocked(_msg("xem notexample.com nhé"), s)


def test_whitelist_entry_with_scheme_and_path_is_normalized():
    s = dict(S_LINKS, whitelist_links=["https://example.com/some/path"])
    _assert_passed(_msg("https://example.com/khac"), s)


def test_blacklist_beats_global_safe_domain():
    s = dict(S_LINKS, blacklist_links=["youtube.com"])
    _assert_blocked(_msg("https://youtube.com/watch?v=x"), s, needle="Blacklist")


def test_blacklist_beats_whitelist():
    s = dict(S_LINKS, blacklist_links=["example.com"], whitelist_links=["example.com"])
    _assert_blocked(_msg("https://example.com/x"), s, needle="Blacklist")


def test_blacklist_covers_subdomains():
    s = dict(S_LINKS, blacklist_links=["example.com"])
    _assert_blocked(_msg("https://cdn.example.com/x"), s, needle="Blacklist")


def test_blacklist_entry_with_url_prefix_is_parsed():
    s = dict(S_LINKS, blacklist_links=["https://bad.site/some/path"])
    _assert_blocked(_msg("xem bad.site nha"), s, needle="Blacklist")


def test_blacklist_does_not_cover_dash_spoof():
    """`evil-example.com` KHÔNG được coi là subdomain của `example.com`."""
    s = dict(S_LINKS, blacklist_links=["example.com"])
    _assert_blocked(_msg("xem evil-example.com nhe"), s, needle="không rõ nguồn gốc")


def test_invite_shortener_domains_blocked_as_unknown_links():
    """dsc.gg/dis.gd/invite.gg/discord.link: ở chế độ mặc định (links ON)
    bị chặn như host lạ; chỉ hở nếu admin TẮT link filter (xem xfail)."""
    for url in ("https://dsc.gg/alpha123", "https://dis.gd/alpha123",
                "https://invite.gg/alpha123", "https://discord.link/alpha123"):
        _assert_blocked(_msg(url), S_LINKS, needle="không rõ nguồn gốc")


GLOBAL_SCAM_CASES = [
    "https://discord-nitro.com/claim",
    "https://free-nitro.io/gift",
    "https://steam-nitro.cc/x",
    "https://free-robux.net/x",
    "https://dlscord.org/x",
    "https://d1scord.com/x",
    f"https://discord-ni{ZERO_WIDTH}tro.com/x",
    "discord-nitro.com",
]


@pytest.mark.parametrize("content", GLOBAL_SCAM_CASES)
def test_global_scam_keywords_blocked_as_fake(content):
    _assert_blocked(_msg(content), S_LINKS, needle="giả mạo")


def test_global_scam_keyword_with_file_extension_still_blocked():
    """`discord-nitro.zip` không được lách qua nhánh bỏ-qua-filename."""
    _assert_blocked(_msg("discord-nitro.zip"), S_LINKS, needle="giả mạo")


# ─── 6. Anti-Invite — PHẢI CHẶN ───────────────────────────────────────────────

INVITE_BLOCK_CASES = [
    "discord.gg/abc123",
    "https://discord.gg/abc123",
    "http://discord.gg/abc",
    "www.discord.gg/abc",
    "https://www.discord.gg/abc",
    "discord.com/invite/abc",
    "https://discord.com/invite/abcdef",
    "discordapp.com/invite/abc",
    "https://discordapp.com/invite/xyz",
    "discord.io/abc",
    "discord.me/abc",
    "discord.li/abc",
    "DISCORD.GG/ABC",
    "https://DISCORD.GG/AbC",
    f"discord{ZERO_WIDTH}.gg/abc",
    f"d{CYR_I}scord.gg/abc",
    f"discord.{CYR_G_SCRIPT}{CYR_G_SCRIPT}/abc",
    "discord.gg/abc?utm_source=x",
    "discord.gg/abc/extra",
    "https://discord.com/invite/abc?event=1",
    "<https://discord.gg/abc>",
    "[vào đây](https://discord.gg/abc)",
    "||https://discord.gg/abc||",
    "mời mọi người discord.gg/abc nha",
    # Homoglyph ngay trong tên miền (HOSTILE_LOOKALIKES xử lý)
    f"discor{CYR_D}.gg/abc",                # д→d
    f"discord{CYR_A}pp.com/invite/x",       # а→a
    "discord\uff0egg/abc",                  # ．(fullwidth) → NFKC quy về dấu chấm
    f"discord{ZWJ}.gg/abc",                 # ZWJ bị loại trước khi khớp
    "```\nhttps://discord.gg/alpha123\n```",  # trong fenced code block vẫn quét
]


@pytest.mark.parametrize("content", INVITE_BLOCK_CASES)
def test_invite_must_block(content):
    _assert_blocked(_msg(content), S_INVITE)


INVITE_PASS_CASES = [
    "discord.gg",                       # không có code mời
    "discord.gg/",
    "https://discord.gg",
    "discord.com/channels/111/222/333",  # link kênh, không phải invite
    "discord.com/settings",
    "https://discord.com/invite",        # thiếu code
    "mình dùng discord hằng ngày",
    "server discord của mình tên là ABC",
    "discord.gg.",                        # dấu chấm câu cuối — không có code mời
]


@pytest.mark.parametrize("content", INVITE_PASS_CASES)
def test_invite_must_pass_legit_mentions(content):
    _assert_passed(_msg(content), S_INVITE)


def test_invite_checked_even_when_link_filter_off():
    """anti_invite phải độc lập với links_enabled (2 toggle riêng)."""
    s = dict(S_INVITE, links_enabled=0)
    _assert_blocked(_msg("discord.gg/abc"), s)


# ─── 7. Bad words ─────────────────────────────────────────────────────────────

def test_badword_plain_and_case_insensitive():
    _assert_blocked(_msg("ai mua freenitro khum"), S_WORDS, needle="freenitro")
    _assert_blocked(_msg("mua FrEeNiTrO đi"), S_WORDS, needle="freenitro")


def test_badword_zero_width_evasion_blocked():
    _assert_blocked(_msg(f"mua free{ZERO_WIDTH}nitro đi"), S_WORDS, needle="freenitro")


def test_badword_cyrillic_evasion_blocked():
    _assert_blocked(_msg(f"mua fr{CYR_E}enitro đi"), S_WORDS, needle="freenitro")


def test_badword_combining_mark_evasion_blocked():
    _assert_blocked(_msg("mua free\u0301nitro đi"), S_WORDS, needle="freenitro")


def test_badword_zalgo_evasion_blocked():
    # Zalgo nhiều dấu chồng: combining marks bị loại trước khi so khớp
    _assert_blocked(_msg("free\u0335\u0336nitro now"), S_WORDS, needle="freenitro")


def test_badword_substring_semantics():
    """Bad word khớp theo substring (không phải word-boundary) — ghi nhận hành vi."""
    s = dict(S_WORDS, bad_words=["nitro"])
    _assert_blocked(_msg("khí nitrogen là gì"), s, needle="nitro")


def test_badword_clean_message_passes():
    _assert_passed(_msg("hôm nay ăn gì thế mọi người"), S_WORDS)


def test_badword_empty_list_passes():
    s = dict(S_WORDS, bad_words=[])
    _assert_passed(_msg("freenitro discord-nitro"), s)


# ─── 8. Anti-Caps (chạy qua on_message — code thật nằm inline trong on_message) ─

def _live_msg(content="hello", channel_id=5150, uid=4242, mentions=None, role_mentions=None):
    """Message của thành viên thường — đủ field để on_message chạy hết nhánh."""
    author = types.SimpleNamespace(id=uid, bot=False, mention=f"<@{uid}>")
    channel = types.SimpleNamespace(id=channel_id, mention=f"<#{channel_id}>")
    guild = types.SimpleNamespace(id=777, name="G")
    return types.SimpleNamespace(
        author=author, guild=guild, channel=channel, content=content,
        embeds=[], stickers=[], attachments=[],
        mentions=mentions or [], role_mentions=role_mentions or [],
        mention_everyone=False, jump_url="https://discord.com/jump",
    )


def _flow_cog(monkeypatch, recorded, settings):
    """Cog cho test chạy qua on_message: gate/text-rules thay bằng fake,
    nhưng spam/caps/mentions là CODE THẬT trong on_message cần kiểm."""
    cog = _cog(recorded)

    async def fake_gate(message):
        return settings

    async def fake_text_rules(message, settings_, content):
        return False

    async def fake_guild_settings(guild_id):
        return {"language": "vi"}

    cog._automod_gate = fake_gate
    cog._check_text_rules = fake_text_rules
    monkeypatch.setattr(am, "async_get_guild_settings", fake_guild_settings)
    return cog


CAPS_BLOCK = [
    "ĐÂY LÀ TIN NHẮN IN HOA TOÀN BỘ CẦU XIN MỌI NGƯỜI",
    "HELLO EVERYBODY HOW ARE YOU ALL TODAY",
    "ABCDEFGHabc11",   # 11 ký tự letters, 8/11 ≈ 72.7% > 70%
]
CAPS_PASS = [
    "Xin chào các bạn mình là thành viên mới",
    "AAAAAAAAAA",      # đúng 10 ký tự → chưa kiểm (điều kiện len > 10)
    "ABCDEFGabc11",    # tỷ lệ đúng 7/10 = 70% → KHÔNG vượt ngưỡng
    "hello world",     # quá ngắn, không đủ 10 ký tự
]


CAPS_SETTINGS = {"spam_enabled": 0, "anti_caps_enabled": 1, "anti_mentions_enabled": 0}


@pytest.mark.parametrize("content", CAPS_BLOCK)
def test_caps_block(monkeypatch, content):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, CAPS_SETTINGS)
    asyncio.run(cog.on_message(_live_msg(content=content)))
    assert recorded, f"tin in hoa phải bị chặn: {content!r}"


@pytest.mark.parametrize("content", CAPS_PASS)
def test_caps_pass(monkeypatch, content):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, CAPS_SETTINGS)
    asyncio.run(cog.on_message(_live_msg(content=content)))
    assert not recorded, f"tin hợp lệ bị chặn oan: {content!r} → {recorded}"


# ─── 9. Anti-Mentions (chạy qua on_message) ───────────────────────────────────

MENTION_SETTINGS = {"spam_enabled": 0, "anti_mentions_enabled": 1, "max_mentions": 5}


@pytest.mark.parametrize("n_users,n_roles,blocked", [
    (5, 0, False),
    (0, 5, False),
    (5, 1, True),
    (0, 6, True),
    (6, 0, True),
    (3, 3, True),
    (2, 2, False),
])
def test_mentions_boundary_matrix(monkeypatch, n_users, n_roles, blocked):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, MENTION_SETTINGS)
    msg = _live_msg(
        mentions=[types.SimpleNamespace(id=1000 + i) for i in range(n_users)],
        role_mentions=[types.SimpleNamespace(id=2000 + i) for i in range(n_roles)],
    )
    asyncio.run(cog.on_message(msg))
    if blocked:
        assert recorded, f"{n_users} user + {n_roles} role phải bị chặn"
    else:
        assert not recorded, f"{n_users} user + {n_roles} role không được chặn oan"


def test_mentions_default_max_is_5(monkeypatch):
    recorded = []
    settings = {"spam_enabled": 0, "anti_mentions_enabled": 1}  # không set max_mentions
    cog = _flow_cog(monkeypatch, recorded, settings)
    msg = _live_msg(mentions=[types.SimpleNamespace(id=i) for i in range(6)])
    asyncio.run(cog.on_message(msg))
    assert recorded, "mặc định phải là 5 mention"


def test_mentions_disabled_passes_even_many(monkeypatch):
    recorded = []
    settings = {"spam_enabled": 0, "anti_mentions_enabled": 0}
    cog = _flow_cog(monkeypatch, recorded, settings)
    msg = _live_msg(
        mentions=[types.SimpleNamespace(id=i) for i in range(20)],
        role_mentions=[types.SimpleNamespace(id=i) for i in range(5)],
    )
    asyncio.run(cog.on_message(msg))
    assert not recorded


def test_mentions_count_unique_not_raw_tokens(monkeypatch):
    """6 token `<@1>` thô nhưng chỉ 1 unique mention → không vi phạm.

    Discord trả field mentions đã dedupe; automod đếm field này chứ không
    regex token trong content — nên token lặp không khuếch đại được."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, MENTION_SETTINGS)
    msg = _live_msg(content="<@1> " * 6, mentions=[types.SimpleNamespace(id=1)])
    asyncio.run(cog.on_message(msg))
    assert not recorded


def test_mentions_in_code_block_not_counted(monkeypatch):
    """`<@1>` trong code block: Discord không resolve → mentions rỗng → cho qua."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, MENTION_SETTINGS)
    msg = _live_msg(content="`<@1>` " * 5, mentions=[])
    asyncio.run(cog.on_message(msg))
    assert not recorded


def test_custom_emoji_not_mentions(monkeypatch):
    """<:party:100> là custom emoji, không phải mention — không được đếm."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, MENTION_SETTINGS)
    msg = _live_msg(content="<:party:100> " * 4, mentions=[])
    asyncio.run(cog.on_message(msg))
    assert not recorded


def test_reply_reference_does_not_inflate_mentions(monkeypatch):
    """Reply có reference nhưng không tạo mention ẩn — không tính vào ngưỡng."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, MENTION_SETTINGS)
    msg = _live_msg(content="đồng ý")
    msg.reference = types.SimpleNamespace(message_id=99)
    asyncio.run(cog.on_message(msg))
    assert not recorded


# ─── 10. Spam 5 tin/5 giây ────────────────────────────────────────────────────

SPAM_SETTINGS = {"spam_enabled": 1, "spam_allowed_channels": [],
                 "anti_caps_enabled": 0, "anti_mentions_enabled": 0}


def test_spam_five_messages_pass_sixth_blocks(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    for _ in range(5):
        asyncio.run(cog.on_message(_live_msg()))
    assert recorded == [], "5 tin liên tiếp chưa được coi là spam"
    asyncio.run(cog.on_message(_live_msg()))
    assert recorded, "tin thứ 6 trong 5 giây phải bị chặn"


def test_spam_allowed_channel_exempt(monkeypatch):
    recorded = []
    settings = dict(SPAM_SETTINGS, spam_allowed_channels=["5150"])
    cog = _flow_cog(monkeypatch, recorded, settings)
    for _ in range(15):
        asyncio.run(cog.on_message(_live_msg(channel_id=5150)))
    assert recorded == [], "kênh nằm trong spam_allowed_channels phải được miễn"


def test_spam_different_users_are_independent(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    for _ in range(5):
        asyncio.run(cog.on_message(_live_msg(uid=1)))
    for _ in range(5):
        asyncio.run(cog.on_message(_live_msg(uid=2)))
    assert recorded == [], "cache spam phải tách theo user"


def test_spam_counter_resets_after_trigger(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    for _ in range(6):
        asyncio.run(cog.on_message(_live_msg()))
    assert len(recorded) == 1
    for _ in range(5):
        asyncio.run(cog.on_message(_live_msg()))
    assert len(recorded) == 1, "sau khi trigger phải reset, 5 tin kế chưa đủ"
    asyncio.run(cog.on_message(_live_msg()))
    assert len(recorded) == 2


def test_spam_old_timestamps_are_pruned(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    cog.spam_cache["777"]["4242"] = [time.time() - 60] * 10  # 10 tin cũ 60s
    asyncio.run(cog.on_message(_live_msg()))
    assert recorded == [], "timestamp quá 5 giây phải bị loại khỏi cửa sổ"


def test_spam_disabled_passes_many(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, dict(SPAM_SETTINGS, spam_enabled=0))
    for _ in range(20):
        asyncio.run(cog.on_message(_live_msg()))
    assert recorded == []


def test_spam_near_duplicate_messages_still_rate_limited(monkeypatch):
    """Near-duplicate (BUY NOW!, BUY NOW!!...) vẫn bị đếm tốc độ như thường."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    for i in range(6):
        asyncio.run(cog.on_message(_live_msg(content="BUY NOW" + "!" * i)))
    assert len(recorded) == 1, "tin thứ 6 phải kích hoạt rate limit"


def test_spam_burst_20_messages_triggers_three_times(monkeypatch):
    """20 tin liên tiếp → vi phạm ở các tin 6/12/18 (cache reset sau mỗi lần)."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    for _ in range(20):
        asyncio.run(cog.on_message(_live_msg()))
    assert len(recorded) == 3


# ─── 11. Attachment / media (khóa regression sự cố .png) ──────────────────────

def test_incident_png_attachment_from_cdn_is_not_blocked():
    """Sự cố thật: ảnh .png từ Discord CDN từng bị timeout oan."""
    msg = _msg(attachments=[_attachment(
        "https://cdn.discordapp.com/attachments/1/2/anh-dep.png?ex=abc&hm=def")])
    _assert_passed(msg, S_LINKS)


def test_content_none_with_attachment_does_not_crash():
    msg = _msg(content=None, attachments=[_attachment(
        "https://cdn.discordapp.com/attachments/1/2/x.png")])
    _assert_passed(msg, S_LINKS)


def test_attachment_mixed_unknown_host_still_blocked():
    msg = _msg(attachments=[
        _attachment("https://cdn.discordapp.com/attachments/1/2/x.png"),
        _attachment("https://payload.evil.example/x.png"),
    ])
    _assert_blocked(msg, S_LINKS, needle="payload.evil.example")


def test_attachment_plus_telegram_text_blocks_on_text():
    msg = _msg(content="kèm link nè https://t.me/group",
               attachments=[_attachment("https://cdn.discordapp.com/attachments/1/2/x.png")])
    _assert_blocked(msg, S_LINKS, needle="t.me")


def test_attachment_filename_with_link_like_text_passes():
    """Tên file chứa 't.me'/'discord.gg' nhưng URL là CDN Discord → cho qua.

    Filename là metadata client, không phải link user đăng; URL CDN thuộc
    nhóm an toàn. Cùng họ với sự cố .png bị timeout oan (30 phút)."""
    att = _attachment("https://cdn.discordapp.com/attachments/1/2/t.me_group_discord.gg_demo.png")
    _assert_passed(_msg("ảnh minh họa", attachments=[att]), S_LINKS)


# ─── 12. Embed / sticker / poll ───────────────────────────────────────────────

def _embed(**kw):
    base = dict(title="", description="", url="", fields=(), footer=None, author=None)
    base.update(kw)
    fields = [types.SimpleNamespace(name=n, value=v) for n, v in (base.pop("fields") or ())]
    return types.SimpleNamespace(**base, fields=fields)


def test_embed_field_with_invite_is_blocked():
    emb = _embed(fields=[("Tham gia ngay", "discord.gg/abc")])
    _assert_blocked(_msg("", embeds=[emb]), S_INVITE)


def test_embed_description_telegram_blocked():
    emb = _embed(description="vào https://t.me/group ngay")
    _assert_blocked(_msg("", embeds=[emb]), S_LINKS, needle="t.me")


def test_sticker_name_with_telegram_link_is_blocked():
    sticker = types.SimpleNamespace(name="t.me/group", description="")
    _assert_blocked(_msg("", stickers=[sticker]), S_LINKS, needle="t.me")


def test_poll_answer_with_telegram_link_is_blocked():
    poll = types.SimpleNamespace(question="Chọn đi",
                                 answers=[types.SimpleNamespace(text="t.me/group")])
    _assert_blocked(_msg(poll=poll), S_LINKS, needle="t.me")


# ─── 13. on_message_edit — sửa tin để lách ────────────────────────────────────

def _edit_cog(monkeypatch, recorded, settings):
    cog = _cog(recorded)

    async def fake_gate(message):
        return settings

    async def fake_guild_settings(guild_id):
        return {"language": "vi"}

    cog._automod_gate = fake_gate
    monkeypatch.setattr(am, "async_get_guild_settings", fake_guild_settings)
    return cog


def test_edit_to_telegram_link_is_blocked(monkeypatch):
    recorded = []
    cog = _edit_cog(monkeypatch, recorded, S_LINKS)
    before = _msg("câu chuyện bình thường")
    after = _msg("câu chuyện bình thường https://t.me/group")
    asyncio.run(cog.on_message_edit(before, after))
    assert recorded, "edit thêm link telegram phải bị chặn"


def test_edit_to_caps_is_blocked(monkeypatch):
    recorded = []
    cog = _edit_cog(monkeypatch, recorded, dict(S_LINKS, anti_caps_enabled=1))
    before = _msg("xin chào mọi người")
    after = _msg("XIN CHÀO MỌI NGƯỜI ƠI MÌNH MỚI VÀO")
    asyncio.run(cog.on_message_edit(before, after))
    assert recorded, "edit thành toàn chữ hoa phải bị chặn"


def test_edit_too_many_mentions_is_blocked(monkeypatch):
    recorded = []
    cog = _edit_cog(monkeypatch, recorded, dict(S_LINKS, anti_mentions_enabled=1, max_mentions=5))
    before = _msg("chào")
    after = _live_msg(
        content="chào các bạn",
        mentions=[types.SimpleNamespace(id=1000 + i) for i in range(6)],
    )
    asyncio.run(cog.on_message_edit(before, after))
    assert recorded, "edit thành tag 6 người phải bị chặn"


def test_edit_same_text_with_new_embed_still_scanned(monkeypatch):
    recorded = []
    cog = _edit_cog(monkeypatch, recorded, S_INVITE)
    before = _msg("xem nè")
    after = _msg("xem nè", embeds=[_embed(description="discord.gg/abc")])
    asyncio.run(cog.on_message_edit(before, after))
    assert recorded, "text không đổi nhưng thêm embed invite vẫn phải bị quét"


# ─── 14. Gate — miễn nhiễm & bỏ qua ──────────────────────────────────────────


class _FakeMemberGate:
    """Member giả cho gate: được patch vào discord.Member trong lúc test."""

    def __init__(self, uid=4242, manage_messages=False, administrator=False,
                 roles=(), bot=False, owner_of=None):
        self.id = uid
        self.bot = bot
        self.guild_permissions = types.SimpleNamespace(
            manage_messages=manage_messages, administrator=administrator)
        self.roles = list(roles)
        self.mention = f"<@{uid}>"


@pytest.fixture()
def member_cls(monkeypatch):
    monkeypatch.setattr(discord, "Member", _FakeMemberGate)
    return _FakeMemberGate


def _patch_gate_db(monkeypatch, settings):
    async def enabled(guild_id, module):
        return True

    async def get_settings(guild_id):
        return settings

    monkeypatch.setattr(am, "async_is_module_enabled", enabled)
    monkeypatch.setattr(am, "async_get_automod_settings", get_settings)


def _gate_msg(author, guild=None):
    return types.SimpleNamespace(author=author, guild=guild or types.SimpleNamespace(id=777, owner=object()))


def test_gate_bot_author_skipped(monkeypatch):
    _patch_gate_db(monkeypatch, {"immune_roles": []})
    cog = Automod.__new__(Automod)
    author = types.SimpleNamespace(bot=True)
    assert asyncio.run(cog._automod_gate(_gate_msg(author))) is None


def test_gate_dm_without_guild_skipped(monkeypatch):
    _patch_gate_db(monkeypatch, {"immune_roles": []})
    cog = Automod.__new__(Automod)
    author = types.SimpleNamespace(bot=False)
    assert asyncio.run(cog._automod_gate(types.SimpleNamespace(author=author, guild=None))) is None


def test_gate_module_disabled_skipped(monkeypatch):
    async def enabled(guild_id, module):
        return False

    monkeypatch.setattr(am, "async_is_module_enabled", enabled)
    cog = Automod.__new__(Automod)
    author = types.SimpleNamespace(bot=False)
    assert asyncio.run(cog._automod_gate(_gate_msg(author))) is None


def test_gate_admin_and_owner_skipped(monkeypatch, member_cls):
    marker = {"immune_roles": []}
    _patch_gate_db(monkeypatch, marker)
    cog = Automod.__new__(Automod)

    owner = member_cls(uid=1)
    guild = types.SimpleNamespace(id=777, owner=owner)
    assert asyncio.run(cog._automod_gate(_gate_msg(owner, guild))) is None

    admin = member_cls(uid=2, administrator=True)
    assert asyncio.run(cog._automod_gate(_gate_msg(admin))) is None

    mod = member_cls(uid=3, manage_messages=True)
    assert asyncio.run(cog._automod_gate(_gate_msg(mod))) is None


def test_gate_normal_member_is_scanned(monkeypatch, member_cls):
    marker = {"immune_roles": []}
    _patch_gate_db(monkeypatch, marker)
    cog = Automod.__new__(Automod)
    member = member_cls(uid=4, roles=[types.SimpleNamespace(id=55)])
    assert asyncio.run(cog._automod_gate(_gate_msg(member))) is marker


def test_gate_immune_role_skipped(monkeypatch, member_cls):
    marker = {"immune_roles": ["55"]}
    _patch_gate_db(monkeypatch, marker)
    cog = Automod.__new__(Automod)
    member = member_cls(uid=4, roles=[types.SimpleNamespace(id=55)])
    assert asyncio.run(cog._automod_gate(_gate_msg(member))) is None


def test_gate_webhook_style_author_without_perms_is_scanned(monkeypatch):
    """Author kiểu webhook (không phải Member): không crash, vẫn bị quét."""
    marker = {"immune_roles": []}
    _patch_gate_db(monkeypatch, marker)
    cog = Automod.__new__(Automod)
    author = types.SimpleNamespace(bot=False)  # không có guild_permissions/roles
    assert asyncio.run(cog._automod_gate(_gate_msg(author))) is marker


# ─── 15. Leo thang vi phạm: cảnh báo → timeout ────────────────────────────────


class _SentMsg:
    def __init__(self, rec):
        self.rec = rec

    async def delete(self, delay=None, **kw):
        self.rec.append(("msg_delete", delay))


class _SendableChannel:
    def __init__(self, rec):
        self.rec = rec
        self.mention = "#general"

    async def send(self, content=None, embed=None, **kw):
        self.rec.append(("channel_send", content, embed is not None))
        return _SentMsg(self.rec)


class _TargetMember:
    def __init__(self, rec, uid=4242):
        self.rec = rec
        self.id = uid
        self.mention = f"<@{uid}>"

    async def send(self, embed=None, **kw):
        self.rec.append(("dm_send", getattr(embed, "title", None)))

    async def timeout(self, until, reason=None):
        self.rec.append(("timeout", until, reason))


def _violation_env(monkeypatch, warnings_value):
    rec = []
    cog = Automod.__new__(Automod)
    cog.bot = types.SimpleNamespace(
        dispatch=lambda *a, **k: rec.append(("dispatch", a[3] if len(a) > 3 else None)))
    counter = {"n": 0}

    async def fake_add_warning(guild_id, user_id):
        if isinstance(warnings_value, (list, tuple)):
            value = warnings_value[counter["n"] % len(warnings_value)]
            counter["n"] += 1
            return value
        return warnings_value

    async def fake_guild_settings(guild_id):
        return {"language": "vi"}

    monkeypatch.setattr(am, "async_add_automod_warning", fake_add_warning)
    monkeypatch.setattr(am, "async_get_guild_settings", fake_guild_settings)
    return cog, rec


def _violation_msg(rec, settings_extra=None):
    settings = {"timeout_duration_minutes": 5, "log_channel_id": None, "notify_role_id": None}
    settings.update(settings_extra or {})
    channel = _SendableChannel(rec)
    member = _TargetMember(rec)
    guild = types.SimpleNamespace(id=777, name="G", get_channel=lambda cid: _SendableChannel(rec))
    message = types.SimpleNamespace(
        content="nội dung vi phạm", jump_url="https://discord.com/jump",
        channel=channel, author=member, guild=guild, delete=_async_noop,
    )
    return message, settings


async def _async_noop(*a, **k):
    return None


def test_first_violation_warns_no_timeout(monkeypatch):
    cog, rec = _violation_env(monkeypatch, 1)
    message, settings = _violation_msg(rec)
    asyncio.run(cog._handle_violation(message, "spam", settings))
    kinds = [r[0] for r in rec]
    assert ("dispatch", "warn") in [(r[0], r[1]) for r in rec if r[0] == "dispatch"]
    assert "timeout" not in kinds, "vi phạm đầu tiên chỉ được cảnh báo"
    assert "dm_send" in kinds


def test_second_violation_timeout_default_5_minutes(monkeypatch):
    cog, rec = _violation_env(monkeypatch, 2)
    message, settings = _violation_msg(rec)
    asyncio.run(cog._handle_violation(message, "spam", settings))
    timeout = [r for r in rec if r[0] == "timeout"]
    assert timeout, "vi phạm thứ 2 phải bị timeout"
    until = timeout[0][1]
    delta = (until - discord.utils.utcnow()).total_seconds()
    assert 4.5 * 60 < delta < 5.5 * 60, f"timeout phải ~5 phút, được {delta}s"


def test_timeout_custom_30_minutes_honored(monkeypatch):
    """Sự cố '30 phút': nếu admin đặt timeout_duration_minutes=30 thì phải đúng 30."""
    cog, rec = _violation_env(monkeypatch, 2)
    message, settings = _violation_msg(rec, {"timeout_duration_minutes": 30})
    asyncio.run(cog._handle_violation(message, "spam", settings))
    timeout = [r for r in rec if r[0] == "timeout"]
    assert timeout
    delta = (timeout[0][1] - discord.utils.utcnow()).total_seconds()
    assert 29.5 * 60 < delta < 30.5 * 60


def test_timeout_garbage_value_falls_back_to_5(monkeypatch):
    """Giá trị rác không được làm nổ NameError/ValueError (regression)."""
    cog, rec = _violation_env(monkeypatch, 2)
    message, settings = _violation_msg(rec, {"timeout_duration_minutes": "abc"})
    asyncio.run(cog._handle_violation(message, "spam", settings))
    timeout = [r for r in rec if r[0] == "timeout"]
    assert timeout
    delta = (timeout[0][1] - discord.utils.utcnow()).total_seconds()
    assert 4.5 * 60 < delta < 5.5 * 60


def test_timeout_sends_log_channel_with_role_ping(monkeypatch):
    cog, rec = _violation_env(monkeypatch, 2)
    message, settings = _violation_msg(rec, {"log_channel_id": "888", "notify_role_id": "999"})
    asyncio.run(cog._handle_violation(message, "spam", settings))
    log_sends = [r for r in rec if r[0] == "channel_send" and r[1] and "999" in str(r[1])]
    assert log_sends, "log channel phải nhận tin có ping role"


# ─── 16. Anti-Raid ────────────────────────────────────────────────────────────


class _PermChannel:
    def __init__(self, cid):
        self.id = cid
        self.name = f"ch-{cid}"

    def overwrites_for(self, role):
        return None

    async def set_permissions(self, target, *a, **kw):
        LOG_PERMS.append((self.id, dict(kw)))


LOG_PERMS = []


def _raid_env(monkeypatch, *, threshold=5, raid_locked=0, action="lockdown"):
    rec = {"updates": [], "enabled_calls": []}
    LOG_PERMS.clear()

    async def enabled(guild_id, module):
        rec["enabled_calls"].append(module)
        return True

    async def getsets(guild_id):
        return {"anti_raid_enabled": 1, "raid_join_per_window": threshold,
                "raid_action": action, "raid_locked": raid_locked,
                "log_channel_id": None}

    async def update(guild_id, **kw):
        rec["updates"].append(kw)

    async def guild_settings(guild_id):
        return {}

    monkeypatch.setattr(am, "async_is_module_enabled", enabled)
    monkeypatch.setattr(am, "async_get_automod_settings", getsets)
    monkeypatch.setattr(am, "async_update_automod_settings", update)
    monkeypatch.setattr(am, "async_get_guild_settings", guild_settings)

    guild = types.SimpleNamespace(
        id=123, name="G", default_role=object(),
        text_channels=[_PermChannel(1), _PermChannel(2)],
    )
    cog = Automod.__new__(Automod)
    cog.join_cache = defaultdict(list)
    cog.raid_locked_guilds = set()
    cog.bot = types.SimpleNamespace(get_guild=lambda gid: None, dispatch=lambda *a: None)
    return cog, guild, rec


def _join(guild):
    return types.SimpleNamespace(bot=False, guild=guild)


def test_raid_below_threshold_no_lockdown(monkeypatch):
    cog, guild, rec = _raid_env(monkeypatch, threshold=5)
    for _ in range(4):
        asyncio.run(cog.on_member_join(_join(guild)))
    assert rec["updates"] == [] and LOG_PERMS == []


def test_raid_threshold_triggers_lockdown(monkeypatch):
    cog, guild, rec = _raid_env(monkeypatch, threshold=5)
    for _ in range(5):
        asyncio.run(cog.on_member_join(_join(guild)))
    assert any(u.get("raid_locked") == 1 for u in rec["updates"]), rec
    assert len(LOG_PERMS) == 2, "mọi kênh text phải bị khoá @everyone"
    assert all(p[1].get("send_messages") is False for p in LOG_PERMS), LOG_PERMS


def test_raid_already_locked_does_not_relockdown(monkeypatch):
    cog, guild, rec = _raid_env(monkeypatch, threshold=5, raid_locked=1)
    for _ in range(8):
        asyncio.run(cog.on_member_join(_join(guild)))
    assert rec["updates"] == [] and LOG_PERMS == []


def test_raid_old_joins_outside_window_are_pruned(monkeypatch):
    cog, guild, rec = _raid_env(monkeypatch, threshold=5)
    cog.join_cache["123"] = [time.time() - 120] * 10
    asyncio.run(cog.on_member_join(_join(guild)))
    assert rec["updates"] == []


def test_raid_verify_action_enables_verify_gate(monkeypatch):
    import database
    calls = []

    async def fake_upsert_verify(guild_id, **kw):
        calls.append((guild_id, kw))

    monkeypatch.setattr(database, "async_upsert_verify_settings", fake_upsert_verify, raising=False)
    cog, guild, rec = _raid_env(monkeypatch, threshold=5, action="verify")
    for _ in range(5):
        asyncio.run(cog.on_member_join(_join(guild)))
    assert calls and calls[0][1].get("enabled") == 1, "raid_action=verify phải bật verify gate"


# ─── 17. Anti-Nuke ────────────────────────────────────────────────────────────


class _AsyncIter:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._it = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _NukeGuild:
    def __init__(self, rec, actor, member=None):
        self.id = 123
        self.owner_id = 1
        self.name = "G"
        self.rec = rec
        self._actor = actor
        self._member = member
        self.default_role = object()
        self.text_channels = [_PermChannel(1)]

    def get_member(self, uid):
        if self._member and self._member.id == uid:
            return self._member
        return None

    def audit_logs(self, limit=10, action=None):
        entries = []
        if self._actor is not None:
            entries.append(types.SimpleNamespace(user=self._actor, created_at=discord.utils.utcnow()))
        return _AsyncIter(entries)

    async def ban(self, user, reason=None, delete_message_seconds=0):
        self.rec["bans"].append(("ban", user.id))


def _nuke_env(monkeypatch, *, threshold=5, actor=None, admin_member=False, owner_id=1):
    rec = {"updates": [], "bans": []}
    LOG_PERMS.clear()

    async def enabled(guild_id, module):
        return True

    async def getsets(guild_id):
        return {"anti_nuke_enabled": 1, "nuke_threshold": threshold,
                "log_channel_id": None, "raid_locked": 0, "nuke_actions": ["channel_delete"]}

    async def update(guild_id, **kw):
        rec["updates"].append(kw)

    async def guild_settings(guild_id):
        return {"bot_admin_roles": "[]"}

    monkeypatch.setattr(am, "async_is_module_enabled", enabled)
    monkeypatch.setattr(am, "async_get_automod_settings", getsets)
    monkeypatch.setattr(am, "async_update_automod_settings", update)
    monkeypatch.setattr(am, "async_get_guild_settings", guild_settings)

    member = None
    if actor is not None:
        member = types.SimpleNamespace(
            id=actor.id,
            guild_permissions=types.SimpleNamespace(administrator=admin_member),
            roles=[types.SimpleNamespace(id=88)],
        )
    guild = _NukeGuild(rec, actor, member)
    guild.owner_id = owner_id
    cog = Automod.__new__(Automod)
    cog.nuke_cache = defaultdict(list)
    cog.nuke_last_handled = {}
    cog.raid_locked_guilds = set()
    cog.bot = types.SimpleNamespace(get_guild=lambda gid: None, dispatch=lambda *a: None)
    return cog, guild, rec


def test_nuke_below_threshold_no_action(monkeypatch):
    actor = types.SimpleNamespace(id=2, bot=False, mention="<@2>")
    cog, guild, rec = _nuke_env(monkeypatch, threshold=5, actor=actor)
    for _ in range(4):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    assert rec["bans"] == [] and rec["updates"] == []


def test_nuke_threshold_bans_and_locks_down(monkeypatch):
    actor = types.SimpleNamespace(id=2, bot=False, mention="<@2>")
    cog, guild, rec = _nuke_env(monkeypatch, threshold=5, actor=actor)
    for _ in range(5):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    assert ("ban", 2) in rec["bans"], "đủ ngưỡng phải ban thủ phạm"
    assert any(u.get("raid_locked") == 1 for u in rec["updates"]), "phải lockdown bảo vệ"
    assert LOG_PERMS, "kênh phải bị khoá @everyone"


def test_nuke_cooldown_blocks_second_action(monkeypatch):
    actor = types.SimpleNamespace(id=2, bot=False, mention="<@2>")
    cog, guild, rec = _nuke_env(monkeypatch, threshold=5, actor=actor)
    for _ in range(5):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    first_bans = len(rec["bans"])
    for _ in range(5):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    assert len(rec["bans"]) == first_bans, "cooldown 20s phải chặn xử lý lặp"


def test_nuke_owner_is_exempt(monkeypatch):
    actor = types.SimpleNamespace(id=1, bot=False, mention="<@1>")
    cog, guild, rec = _nuke_env(monkeypatch, threshold=5, actor=actor, owner_id=1)
    for _ in range(5):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    assert rec["bans"] == [], "chủ server không bao giờ bị ban vì anti-nuke"


def test_nuke_admin_member_is_exempt(monkeypatch):
    actor = types.SimpleNamespace(id=2, bot=False, mention="<@2>")
    cog, guild, rec = _nuke_env(monkeypatch, threshold=5, actor=actor, admin_member=True)
    for _ in range(5):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    assert rec["bans"] == [], "admin được miễn trừ anti-nuke"


def test_nuke_bot_actor_is_skipped(monkeypatch):
    actor = types.SimpleNamespace(id=3, bot=True, mention="<@3>")
    cog, guild, rec = _nuke_env(monkeypatch, threshold=5, actor=actor)
    for _ in range(5):
        asyncio.run(cog._on_delete_event(guild, "channel_delete"))
    assert rec["bans"] == [], "bot dọn kênh không được bị ban"


# ─── 18. Ca từng là GAP — ĐÃ VÁ (test thường); gap còn lại đánh xfail ────────

def test_spaced_dot_domain_invite_blocked():
    """`discord. gg/abc`: deobfuscated_variants gộp khoảng trắng quanh dấu chấm."""
    _assert_blocked(_msg("discord. gg/abc"), S_INVITE)


def test_bracket_notation_link_blocked():
    """`t[.]me` giải `[.]` -> `.` rồi khớp _TELEGRAM_LINK_RE."""
    _assert_blocked(_msg("ghé t[.]me/group nhé"), S_LINKS)


def test_tg_scheme_link_blocked():
    """`tg://` là URI deep-link Telegram — quét theo scheme, không chỉ http/https."""
    _assert_blocked(_msg("tg://resolve?domain=group"), S_LINKS)


def test_dscgg_invite_shortener_blocked():
    _assert_blocked(_msg("dsc.gg/abc"), S_INVITE)


def test_disgd_invite_shortener_blocked():
    _assert_blocked(_msg("dis.gd/abc"), S_INVITE)


@pytest.mark.xfail(reason="markdown ** chen giữa từ cấm ('free**nitro**') chưa được lọc", strict=False)
def test_gap_markdown_broken_badword():
    _assert_blocked(_msg("nhận free**nitro** ngay"), S_WORDS)


def test_everyone_without_permission_blocked(monkeypatch):
    """@everyone/@here bị chặn nếu người gửi không có quyền mention_everyone."""
    recorded = []
    settings = {"spam_enabled": 0, "anti_mentions_enabled": 1, "max_mentions": 5}
    cog = _flow_cog(monkeypatch, recorded, settings)
    msg = _live_msg(content="@everyone vào đây")
    msg.mention_everyone = True
    asyncio.run(cog.on_message(msg))
    assert recorded, "@everyone phải bị chặn khi thiếu quyền"


def test_everyone_with_permission_passes(monkeypatch):
    recorded = []
    settings = {"spam_enabled": 0, "anti_mentions_enabled": 1, "max_mentions": 5}
    cog = _flow_cog(monkeypatch, recorded, settings)
    msg = _live_msg(content="@everyone vào đây")
    msg.mention_everyone = True
    msg.author.guild_permissions = types.SimpleNamespace(mention_everyone=True)
    asyncio.run(cog.on_message(msg))
    assert not recorded


def test_dotless_i_invite_is_blocked_by_re_ignorecase():
    """`dıscord.gg` (ı U+0131) VẪN khớp pattern mời nhờ re.IGNORECASE của Python:
    'ı'.upper() == 'I' nên engine coi ı≡i. Đã kiểm chứng thực nghiệm."""
    _assert_blocked(_msg(f"d{DOTLESS_I}scord.gg/abc"), S_INVITE)


def test_comma_variant_invite_blocked():
    """`discord,gg/abc`: dấu phẩy hoán về dấu chấm trong biến thể."""
    _assert_blocked(_msg("discord,gg/abc"), S_INVITE)


def test_emoji_between_invite_blocked():
    """`discord.🔥gg/abc`: bỏ ký tự ngoài ASCII trong biến thể."""
    _assert_blocked(_msg("discord.\U0001F525gg/abc"), S_INVITE)


def test_semicolon_variant_invite_blocked():
    _assert_blocked(_msg("discord;gg/abc"), S_INVITE)


def test_spelled_out_dot_invite_blocked():
    """`discord dot gg/abc` — chữ 'dot' được thay về '.' trước khi khớp."""
    _assert_blocked(_msg("discord dot gg/abc"), S_INVITE)


def test_trailing_dot_invite_blocked():
    """`discord.gg./abc`: pattern invite chấp nhận dấu chấm cuối hostname."""
    _assert_blocked(_msg("discord.gg./abc"), S_INVITE)


# ── Bổ sung từ nghiên cứu web ─────────────────────────────────────────────────

def test_invite_gg_invite_only_blocked():
    """invite.gg là vanity shortener invite — đã nằm trong DISCORD_INVITE_PATTERN."""
    _assert_blocked(_msg("https://invite.gg/alpha123"), S_INVITE)


def test_spaced_characters_invite_blocked():
    """`d i s c o r d . g g / alpha123` — gộp ký tự đơn bị tách."""
    _assert_blocked(_msg("d i s c o r d . g g / alpha123"), S_INVITE)


def test_parens_dot_invite_blocked():
    """`discord(.)gg` — `(.)` được thay về `.`."""
    _assert_blocked(_msg("discord(.)gg/alpha123"), S_INVITE)


def test_middle_dot_invite_blocked():
    """`discord·gg` (U+00B7) — hoán về dấu chấm."""
    _assert_blocked(_msg("discord\u00b7gg/alpha123"), S_INVITE)


def test_zwnj_between_domain_blocked():
    """U+200C bị _ZERO_WIDTH_RE loại trước khi so — dưới chế độ links."""
    _assert_blocked(_msg("t\u200c.me/group"), S_LINKS)


def test_bom_between_domain_blocked():
    """U+FEFF bị _ZERO_WIDTH_RE loại trước khi so — dưới chế độ links."""
    _assert_blocked(_msg("t\ufeff.me/group"), S_LINKS)


def test_hxxps_bracket_dot_blocked():
    """`hxxps://t[.]me/group` — [.] giải mã rồi khớp _TELEGRAM_LINK_RE."""
    _assert_blocked(_msg("hxxps://t[.]me/group"), S_LINKS)


def test_emoji_flood_blocked(monkeypatch):
    """8 emoji liên tiếp → vi phạm spam emoji (ngưỡng mặc định 8)."""
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    asyncio.run(cog.on_message(_live_msg(content="\U0001F600" * 8)))
    assert recorded, "8 emoji liên tiếp phải bị chặn"


def test_emoji_under_threshold_passes(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    asyncio.run(cog.on_message(_live_msg(content="\U0001F600" * 7)))
    assert not recorded, "7 emoji chưa vượt ngưỡng 8"


def test_emoji_flood_disabled_with_spam_off(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, dict(SPAM_SETTINGS, spam_enabled=0))
    asyncio.run(cog.on_message(_live_msg(content="\U0001F600" * 8)))
    assert not recorded, "tắt chống spam thì không chặn emoji flood"


def test_emoji_zwj_family_counts_as_one_unit():
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"
    assert count_emoji_units(family) == 1
    assert count_emoji_units(family * 8) == 8


@pytest.mark.xfail(reason="zalgo spam (combining marks) chưa có heuristic riêng", strict=False)
def test_gap_zalgo_spam(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    asyncio.run(cog.on_message(_live_msg(
        content="S\u0338\u0351\u035dP\u0337\u0351A\u0336\u0355M\u0334\u035a")))
    assert recorded, "zalgo spam đang lọt qua"


def test_forward_snapshot_scanned():
    """Tin forward: nội dung trong message_snapshots cũng phải bị quét."""
    msg = _msg("")
    msg.message_snapshots = [types.SimpleNamespace(content="https://t.me/group")]
    _assert_blocked(msg, S_LINKS, needle="t.me")


def test_forward_clean_snapshot_passes():
    msg = _msg("")
    msg.message_snapshots = [types.SimpleNamespace(content="Lịch họp 9 giờ")]
    _assert_passed(msg, S_LINKS)


def test_embed_url_telegram_is_blocked():
    """embed.url cũng nằm trong tầm quét — message_scan_text gom cả URL embed."""
    emb = types.SimpleNamespace(url="https://t.me/group", title="", description="", fields=[])
    _assert_blocked(_msg("xem nè", embeds=[emb]), S_LINKS, needle="t.me")


@pytest.mark.xfail(reason="nhiều dòng lặp trong MỘT tin chưa được đếm (chỉ đếm theo số tin)", strict=False)
def test_gap_repeated_lines_single_message(monkeypatch):
    recorded = []
    cog = _flow_cog(monkeypatch, recorded, SPAM_SETTINGS)
    asyncio.run(cog.on_message(_live_msg(content="mua ngay\n" * 10)))
    assert recorded, "lặp 10 dòng trong 1 tin đang lọt qua"
