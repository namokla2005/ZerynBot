"""Phase 7 — Automod link false-positive: attachment filename không được coi là domain.

Ca thật 2026-10-30: user gửi ảnh `image.png` (không có text) bị timeout với lý do
"Gửi link không rõ nguồn gốc: image.png". Nguyên nhân: message_scan_text thêm URL
CDN của attachment, rồi BARE_DOMAIN_PATTERN quét cả path `.../image.png` và coi
`image.png` là domain (`.png` là TLD).

Test này khóa các bất biến:
- Host Discord CDN (`cdn.discordapp.com`, `media.discordapp.net`) + filename bất kỳ
  không bị chặn.
- URL có scheme/path chỉ xét hostname, không xét filename trong path.
- Bare URL `example.com/image.png` chỉ xét example.com.
- Filename trần (`image.png`, `file.zip`) không bị coi là link; blacklist/global
  keyword vẫn thắng nếu admin hoặc scam keyword khớp.
- URL có userinfo `https://discord.com@evil.example` phải xét host thật evil.example.
"""
import asyncio
import types

from cogs.automod import Automod, message_scan_text

SETTINGS_LINKS = {
    "links_enabled": 1, "bad_words_enabled": 0, "anti_invite_enabled": 0,
    "whitelist_links": [], "blacklist_links": [], "bad_words": [],
}


def _cog(recorded):
    cog = Automod.__new__(Automod)

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


def _run(cog, message, settings=None):
    return asyncio.run(cog._check_text_rules(
        message, settings or SETTINGS_LINKS, message_scan_text(message)
    ))


# ─── Attachments / Discord CDN ────────────────────────────────────────────────

def test_discord_attachment_image_png_is_not_blocked():
    recorded = []
    message = _msg(attachments=[_attachment(
        "https://cdn.discordapp.com/attachments/889155256926228551/"
        "156594261926188113/image.png?ex=6a000000&is=69feb000&hm=deadbeef&"
    )])
    assert _run(_cog(recorded), message) is False
    assert recorded == [], recorded


def test_media_discordapp_net_attachment_is_safe():
    recorded = []
    message = _msg(attachments=[_attachment(
        "https://media.discordapp.net/attachments/1/2/image.png?width=800&height=600"
    )])
    assert _run(_cog(recorded), message) is False
    assert recorded == [], recorded


def test_unknown_attachment_host_is_blocked_by_host_not_filename():
    recorded = []
    message = _msg(attachments=[_attachment(
        "https://evil.example/attachments/1/2/image.png"
    )])
    assert _run(_cog(recorded), message) is True
    assert len(recorded) == 1
    assert "evil.example" in recorded[0]
    assert "image.png" not in recorded[0], recorded


# ─── URL path / bare URL ──────────────────────────────────────────────────────

def test_explicit_url_path_filename_is_not_a_domain():
    recorded = []
    message = _msg("xem https://example.com/image.png")
    assert _run(_cog(recorded), message) is True
    assert "example.com" in recorded[0]
    assert "image.png" not in recorded[0], recorded


def test_bare_url_path_filename_is_not_a_domain():
    recorded = []
    message = _msg("xem example.com/image.png")
    assert _run(_cog(recorded), message) is True
    assert "example.com" in recorded[0]
    assert "image.png" not in recorded[0], recorded


def test_userinfo_url_uses_real_hostname():
    recorded = []
    message = _msg("https://discord.com@evil.example/gift")
    assert _run(_cog(recorded), message) is True
    assert "evil.example" in recorded[0]
    assert "discord.com" not in recorded[0], recorded


# ─── Filename trần + ưu tiên blacklist/global keyword ─────────────────────────

def test_plain_filename_token_is_not_a_link():
    recorded = []
    message = _msg("file của mình là image.png nhé")
    assert _run(_cog(recorded), message) is False
    assert recorded == [], recorded


def test_blacklisted_filename_is_still_blocked():
    recorded = []
    settings = dict(SETTINGS_LINKS, blacklist_links=["image.png"])
    message = _msg("image.png")
    assert _run(_cog(recorded), message, settings) is True
    assert "Blacklist" in recorded[0], recorded


def test_global_scam_keyword_with_file_extension_is_still_blocked():
    recorded = []
    message = _msg("discord-nitro.zip")
    assert _run(_cog(recorded), message) is True
    assert "giả mạo" in recorded[0] or "lừa đảo" in recorded[0], recorded


def test_safe_domains_include_discordapp_net():
    import cogs.automod as am

    assert "discordapp.net" in am.GLOBAL_SAFE_DOMAINS


# ─── Poll content ────────────────────────────────────────────────────────────

def test_poll_question_link_is_scanned():
    recorded = []
    poll = types.SimpleNamespace(
        question="Nhận quà tại https://evil.example/gift",
        answers=[types.SimpleNamespace(text="OK")],
    )
    message = _msg(poll=poll)
    assert _run(_cog(recorded), message) is True
    assert "evil.example" in recorded[0], recorded


def test_poll_answer_filename_is_not_a_link():
    recorded = []
    poll = types.SimpleNamespace(
        question="Chọn file",
        answers=[types.SimpleNamespace(text="image.png")],
    )
    message = _msg(poll=poll)
    assert _run(_cog(recorded), message) is False
    assert recorded == [], recorded


def test_automod_gate_handles_non_member_author_without_crash(monkeypatch):
    """Webhook/User author không có guild_permissions/roles: vẫn phải được quét."""
    # Full suite có thể load automod qua nhiều tên module; patch đúng globals
    # của chính method thay vì một module copy khác.
    method_globals = Automod._automod_gate.__globals__
    marker = {"immune_roles": [], "_test_marker": True}

    async def fake_enabled(guild_id, module):
        return True

    async def fake_settings(guild_id):
        return marker

    monkeypatch.setitem(method_globals, "async_is_module_enabled", fake_enabled)
    monkeypatch.setitem(method_globals, "async_get_automod_settings", fake_settings)
    guild = types.SimpleNamespace(id=123, owner_id=1)
    author = types.SimpleNamespace(bot=False)  # no guild_permissions / roles
    message = types.SimpleNamespace(author=author, guild=guild)
    cog = Automod.__new__(Automod)
    assert asyncio.run(cog._automod_gate(message)) is marker


def test_plain_jxl_filename_is_not_a_link():
    recorded = []
    message = _msg("ảnh photo.jxl nhé")
    assert _run(_cog(recorded), message) is False
    assert recorded == [], recorded


def test_explicit_url_with_file_extension_is_still_checked():
    """Dedup ưu tiên source url: `https://image.png` là URL thật, không được skip."""
    recorded = []
    message = _msg("image.png https://image.png/gift")
    assert _run(_cog(recorded), message) is True
    assert "image.png" in recorded[0], recorded


# ─── Mọi đuôi ảnh ─────────────────────────────────────────────────────────────

IMAGE_EXTENSIONS = [
    "png", "jpg", "jpeg", "jfif", "gif", "webp", "apng", "avif", "jxl", "bmp",
    "svg", "ico", "tif", "tiff", "heic", "heif", "jp2", "j2k", "psd", "raw",
    "cr2", "cr3", "nef", "arw", "dng", "orf", "rw2", "tga", "exr", "hdr",
    "wbmp",
]


def test_all_image_attachment_urls_are_safe():
    """Attachment URL không bao giờ xét filename → mọi đuôi ảnh đều an toàn."""
    for ext in IMAGE_EXTENSIONS:
        recorded = []
        message = _msg(attachments=[_attachment(
            f"https://cdn.discordapp.com/attachments/1/2/image.{ext}?ex=abc&hm=def"
        )])
        assert _run(_cog(recorded), message) is False, ext
        assert recorded == [], (ext, recorded)


def test_all_image_bare_filenames_are_safe():
    """Khi user gõ tên file trần, các đuôi ảnh phổ biến/ít gặp đều không phải link."""
    for ext in IMAGE_EXTENSIONS:
        recorded = []
        message = _msg(f"file image.{ext} nhé")
        assert _run(_cog(recorded), message) is False, ext
        assert recorded == [], (ext, recorded)


def test_bare_token_prefix_matches_are_not_domains():
    """`image.jp2` không được khớp tiền tố `image.jp`; `example.com2` cũng vậy."""
    for token in ("image.jp2", "example.com2"):
        recorded = []
        message = _msg(f"file {token} nhé")
        assert _run(_cog(recorded), message) is False, token
        assert recorded == [], (token, recorded)
