"""
auth.py — Discord OAuth2 helpers for the Flask dashboard.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from urllib.parse import urlencode
import config

# Permissions bit: Manage Guild (0x20 = 32)
MANAGE_GUILD = 0x20


def get_oauth2_url() -> str:
    """Build the Discord OAuth2 authorization URL."""
    params = {
        "client_id":     config.CLIENT_ID,
        "redirect_uri":  config.REDIRECT_URI,
        "response_type": "code",
        "scope":         config.OAUTH2_SCOPES,
    }
    return f"{config.OAUTH2_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for an access token."""
    data = {
        "client_id":     config.CLIENT_ID,
        "client_secret": config.CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  config.REDIRECT_URI,
    }
    resp = requests.post(
        config.OAUTH2_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_user(access_token: str) -> dict:
    """Fetch current user from Discord API."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_user_guilds(access_token: str) -> list:
    """Fetch guilds the user is in."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_bot_guilds() -> list:
    """Fetch guilds the bot is in (using bot token)."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bot {config.TOKEN}"},
        timeout=10,
    )
    if not resp.ok:
        return []
    return resp.json()

def get_member_roles(guild_id: str, user_id: str) -> list:
    """Fetch member's role IDs from a guild using the bot token."""
    resp = requests.get(
        f"{config.DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
        headers={"Authorization": f"Bot {config.TOKEN}"},
        timeout=10,
    )
    if not resp.ok:
        return []
    data = resp.json()
    return data.get("roles", [])


def get_manageable_guilds(access_token: str) -> list:
    """
    Return guilds where:
    - The user has MANAGE_GUILD permission, AND
    - The bot is present in that guild.
    Each guild dict gets an extra 'bot_in_guild' key.
    """
    user_guilds = get_user_guilds(access_token)
    bot_guild_ids = {g["id"] for g in get_bot_guilds()}

    result = []
    for g in user_guilds:
        perms = int(g.get("permissions", 0))
        if perms & MANAGE_GUILD:
            g["bot_in_guild"] = g["id"] in bot_guild_ids
            g["icon_url"] = (
                f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
                if g.get("icon") else None
            )
            result.append(g)
    return result


def get_avatar_url(user: dict) -> str:
    """Build Discord CDN avatar URL for a user dict."""
    uid   = user.get("id", "")
    avatar = user.get("avatar")
    if avatar:
        ext = "gif" if avatar.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{ext}?size=256"
    disc = int(user.get("discriminator", 0) or 0)
    return f"https://cdn.discordapp.com/embed/avatars/{disc % 5}.png"
