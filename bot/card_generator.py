"""
card_generator.py — Generate Welcome/Goodbye banner card images using Pillow.

Card design (inspired by reference images):
  - Dark rounded background card
  - Coloured accent bars on the left and right sides
  - Circular avatar in the center
  - Member # badge at top
  - Large bold username below avatar
  - Smaller server name at bottom

Fonts: Uses Windows system fonts (Segoe UI, Arial, Calibri) which support
Vietnamese and other Unicode characters. Falls back to Pillow's default
if no system font is found.
"""

import io
import os
import asyncio
import logging
from pathlib import Path

import aiohttp

log = logging.getLogger("BotV2")

# ─── System font discovery ─────────────────────────────────────────────────────
# Prefer Segoe UI (Windows) → Arial → Calibri → all of which support Vietnamese
_WIN_FONTS = r"C:\Windows\Fonts"
_BOLD_CANDIDATES = ["tahomabd.ttf", "segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "verdanab.ttf"]
_REG_CANDIDATES  = ["tahoma.ttf", "segoeui.ttf",  "arial.ttf",   "calibri.ttf",  "verdana.ttf"]


def _find_system_font(candidates: list[str]) -> str | None:
    for name in candidates:
        path = os.path.join(_WIN_FONTS, name)
        if os.path.exists(path):
            return path
    return None


_SYS_BOLD = _find_system_font(_BOLD_CANDIDATES)
_SYS_REG  = _find_system_font(_REG_CANDIDATES)

if _SYS_BOLD:
    log.info(f"[Card] Using bold font: {os.path.basename(_SYS_BOLD)}")
else:
    log.warning("[Card] No bold system font found — text may not render Vietnamese correctly")


def _get_pil_font(size: int, bold: bool = False):
    """Return a PIL ImageFont using system fonts that support Vietnamese."""
    from PIL import ImageFont
    path = _SYS_BOLD if bold else _SYS_REG
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception as e:
            log.warning(f"[Card] Could not load system font {path}: {e}")
    # Final fallback
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


# ─── Avatar download ───────────────────────────────────────────────────────────
async def _download_avatar(url: str) -> bytes | None:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        log.warning(f"[Card] Avatar download error: {e}")
    return None


# Helper: download avatar synchronously (for use from Flask/api.py)
def _download_avatar_sync(url: str) -> bytes | None:
    try:
        import requests as _req
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = _req.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        log.warning(f"[Card] Avatar download (sync) error: {e}")
    return None


# ─── Card renderer ─────────────────────────────────────────────────────────────
def _make_circle_avatar(img_bytes: bytes, size: int) -> "Image":
    """Crop image into a circle with the given diameter."""
    from PIL import Image, ImageDraw
    avatar = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    avatar = avatar.resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)

    output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    output.paste(avatar, (0, 0), mask)
    return output


def _draw_rounded_rect(draw, xy, radius: int, fill):
    """Draw a rounded rectangle on the given ImageDraw."""
    from PIL import ImageDraw as PilDraw
    x1, y1, x2, y2 = xy
    r = radius
    draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
    draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
    draw.ellipse([x1, y1, x1 + 2*r, y1 + 2*r], fill=fill)
    draw.ellipse([x2 - 2*r, y1, x2, y1 + 2*r], fill=fill)
    draw.ellipse([x1, y2 - 2*r, x1 + 2*r, y2], fill=fill)
    draw.ellipse([x2 - 2*r, y2 - 2*r, x2, y2], fill=fill)


def _render_card(
    avatar_bytes: bytes | None,
    top_label: str,
    username: str,
    preposition: str,
    server_name: str,
    accent_color: tuple,       # RGB tuple e.g. (88, 237, 135)
    accent_color2: tuple = None,
    card_bg: tuple = (15, 10, 25), # Slightly darker for the main card like Discord's new UI
    bg_bytes: bytes | None = None,
) -> io.BytesIO:
    from PIL import Image, ImageDraw, ImageFilter
    import unicodedata

    top_label   = unicodedata.normalize('NFC', top_label)
    username    = unicodedata.normalize('NFC', username)
    preposition = unicodedata.normalize('NFC', preposition)
    server_name = unicodedata.normalize('NFC', server_name)

    if not accent_color2:
        accent_color2 = accent_color

    # ─── Canvas ─────────────────────────────────────────────────────────────
    W, H    = 540, 320
    CARD_W  = 540
    CARD_H  = 320
    CARD_X  = 0
    CARD_Y  = 0

    # Transparent background!
    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Load bg image
    bg_img = None
    try:
        raw_bg = None
        if bg_bytes:
            raw_bg = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
        elif Path("dashboard/static/bg.png").exists():
            raw_bg = Image.open("dashboard/static/bg.png").convert("RGBA")
            
        if raw_bg:
            # Crop/resize bg to WxH
            bg_ratio = raw_bg.width / raw_bg.height
            target_ratio = W / H
            if bg_ratio > target_ratio:
                # crop width
                new_w = int(target_ratio * raw_bg.height)
                x = (raw_bg.width - new_w) // 2
                raw_bg = raw_bg.crop((x, 0, x + new_w, raw_bg.height))
            else:
                new_h = int(raw_bg.width / target_ratio)
                y = (raw_bg.height - new_h) // 2
                raw_bg = raw_bg.crop((0, y, raw_bg.width, y + new_h))
            bg_img = raw_bg.resize((W, H), Image.LANCZOS)
            
            # Apply blur 3%
            bg_img = bg_img.filter(ImageFilter.GaussianBlur(3))
            
            # Darken the background
            dark_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 110))
            bg_img = Image.alpha_composite(bg_img, dark_overlay)
            
    except Exception as e:
        log.warning(f"[Card] Failed to load bg.png: {e}")

    # Draw rounded background image
    if bg_img:
        mask = Image.new("L", (W, H), 0)
        mask_draw = ImageDraw.Draw(mask)
        _draw_rounded_rect(mask_draw, (0, 0, W, H), radius=20, fill=255)
        img.paste(bg_img, (0, 0), mask)
    else:
        _draw_rounded_rect(draw, (0, 0, W, H), radius=20, fill=(30, 31, 34, 255))

    # ─── Avatar ──────────────────────────────────────────────────────────────
    AV_SIZE = 110
    AV_X    = (W - AV_SIZE) // 2
    AV_Y    = CARD_Y + 65

    if avatar_bytes:
        try:
            av = _make_circle_avatar(avatar_bytes, AV_SIZE)
            # Add a subtle border around avatar
            border_size = AV_SIZE + 8
            border_x = (W - border_size) // 2
            border_y = AV_Y - 4
            draw.ellipse([border_x, border_y, border_x + border_size, border_y + border_size], fill=(255, 255, 255, 255))
            
            img.paste(av, (AV_X, AV_Y), av)
        except Exception:
            pass

    # ─── Top label (Member #N / "Sad to see you go!") ────────────────────────
    font_top  = _get_pil_font(18, bold=True)
    # draw a pill background
    label_w, label_h = 160, 28
    label_x = (W - label_w) // 2
    label_y = CARD_Y + 18
    _draw_rounded_rect(draw, (label_x, label_y, label_x + label_w, label_y + label_h), radius=8, fill=(60, 63, 75, 255))
    draw.text((W // 2, label_y + label_h // 2), top_label, font=font_top, fill=(255, 255, 255), anchor="mm")

    # ─── Username ────────────────────────────────────────────────────────────
    font_user = _get_pil_font(36, bold=True)
    user_y    = AV_Y + AV_SIZE + 14
    draw.text((W // 2, user_y), username, font=font_user, fill=(255, 255, 255), anchor="mt")

    # ─── "to" / "from" preposition ───────────────────────────────────────────
    font_prep = _get_pil_font(16, bold=False)
    prep_bbox = draw.textbbox((0, 0), username, font=font_user)
    prep_y    = user_y + (prep_bbox[3] - prep_bbox[1]) + 6
    draw.text((W // 2, prep_y), preposition, font=font_prep, fill=(200, 200, 200), anchor="mt")

    # ─── Server name ─────────────────────────────────────────────────────────
    font_srv = _get_pil_font(22, bold=True)
    srv_bbox = draw.textbbox((0, 0), preposition, font=font_prep)
    srv_y    = prep_y + (srv_bbox[3] - srv_bbox[1]) + 4
    draw.text((W // 2, srv_y), server_name, font=font_srv, fill=(255, 255, 255), anchor="mt")

    # ─── Export ──────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    # DO NOT convert to RGB so we keep transparency!
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ─── Public async API ──────────────────────────────────────────────────────────
async def generate_welcome_card(member, bg_url: str = None) -> io.BytesIO | None:
    """Generate a welcome banner card for the given member. Returns PNG BytesIO."""
    try:
        avatar_bytes = await _download_avatar(str(member.display_avatar.url))
        bg_bytes     = await _download_avatar(bg_url) if bg_url else None
        top_label    = f"Member #{member.guild.member_count}"
        username     = f"Welcome {member.display_name}"
        server       = member.guild.name

        loop = asyncio.get_event_loop()
        buf = await loop.run_in_executor(
            None,
            lambda: _render_card(
                avatar_bytes  = avatar_bytes,
                top_label     = top_label,
                username      = username,
                preposition   = "to",
                server_name   = server,
                accent_color  = (255, 183, 197),    # Pastel Pink left
                accent_color2 = (255, 158, 194),    # Pastel Pink right
                card_bg       = (15, 10, 25),
                bg_bytes      = bg_bytes,
            )
        )
        return buf
    except Exception as e:
        log.error(f"[Card] generate_welcome_card error: {e}")
        return None


async def generate_goodbye_card(member, bg_url: str = None) -> io.BytesIO | None:
    """Generate a goodbye banner card for the given member. Returns PNG BytesIO."""
    try:
        avatar_bytes = await _download_avatar(str(member.display_avatar.url))
        bg_bytes     = await _download_avatar(bg_url) if bg_url else None
        top_label    = "Sad to see you go!"
        username     = f"Goodbye {member.display_name}"
        server       = member.guild.name

        loop = asyncio.get_event_loop()
        buf = await loop.run_in_executor(
            None,
            lambda: _render_card(
                avatar_bytes  = avatar_bytes,
                top_label     = top_label,
                username      = username,
                preposition   = "from",
                server_name   = server,
                accent_color  = (255, 179, 71),    # Pastel orange left
                accent_color2 = (255, 204, 51),    # Pastel yellow right
                card_bg       = (15, 10, 25),
                bg_bytes      = bg_bytes,
            )
        )
        return buf
    except Exception as e:
        log.error(f"[Card] generate_goodbye_card error: {e}")
        return None
