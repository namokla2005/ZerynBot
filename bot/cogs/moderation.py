"""
Cog: Moderation (v2) — kick, ban, unban, timeout, untimeout, warn, warnings, delwarn, clear, slowmode, lock, unlock
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import re
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_add_mod_warning, async_get_mod_warnings,
    async_count_mod_warnings, async_delete_mod_warning,
)
from i18n import tr
try:
    from emojis import e
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e


def _parse_duration(text: str) -> timedelta | None:
    """Parse duration strings like '10m', '2h', '1d' into timedelta."""
    m = re.fullmatch(r"(\d+)\s*([smhd])", text.strip().lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    if unit == "s":
        return timedelta(seconds=val)
    elif unit == "m":
        return timedelta(minutes=val)
    elif unit == "h":
        return timedelta(hours=val)
    elif unit == "d":
        return timedelta(days=min(val, 28))
    return None


class Moderation(commands.Cog):
    """Server moderation commands: kick, ban, warn, clear, lock, etc."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _check_module(self, interaction: discord.Interaction) -> dict | None:
        """Check if moderation module is enabled. Returns guild settings or None."""
        if not interaction.guild:
            return None
        enabled = await async_is_module_enabled(str(interaction.guild.id), "moderation")
        if not enabled:
            s = await async_get_guild_settings(str(interaction.guild.id))
            await interaction.response.send_message(
                tr(s, "common.module_disabled", module="Moderation"), ephemeral=True
            )
            return None
        return await async_get_guild_settings(str(interaction.guild.id))

    # ─── /kick ──────────────────────────────────────────────────────────
    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for kick")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        s = await self._check_module(interaction)
        if not s:
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message(tr(s, "mod.cannot_target_higher"), ephemeral=True)
        if not interaction.guild.me.top_role > member.top_role:
            return await interaction.response.send_message(tr(s, "mod.bot_role_too_low"), ephemeral=True)

        reason_text = reason or tr(s, "mod.no_reason")
        try:
            await member.send(tr(s, "mod.kick_dm", server=interaction.guild.name, reason=reason_text))
        except Exception:
            pass
        await member.kick(reason=f"{interaction.user}: {reason_text}")
        embed = discord.Embed(
            description=f"{e('zb_kick')} " + tr(s, "mod.kick_success", user=member.mention, reason=reason_text),
            color=config.COLOR_WARNING,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /ban ───────────────────────────────────────────────────────────
    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for ban", delete_days="Days of messages to delete (0-7)")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member,
                  reason: str = None, delete_days: app_commands.Range[int, 0, 7] = 0):
        s = await self._check_module(interaction)
        if not s:
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message(tr(s, "mod.cannot_target_higher"), ephemeral=True)
        if not interaction.guild.me.top_role > member.top_role:
            return await interaction.response.send_message(tr(s, "mod.bot_role_too_low"), ephemeral=True)

        reason_text = reason or tr(s, "mod.no_reason")
        try:
            await member.send(tr(s, "mod.ban_dm", server=interaction.guild.name, reason=reason_text))
        except Exception:
            pass
        await member.ban(reason=f"{interaction.user}: {reason_text}", delete_message_days=delete_days)
        embed = discord.Embed(
            description=f"{e('zb_ban')} " + tr(s, "mod.ban_success", user=member.mention, reason=reason_text),
            color=config.COLOR_ERROR,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /unban ─────────────────────────────────────────────────────────
    @app_commands.command(name="unban", description="Unban a user by ID")
    @app_commands.describe(user_id="The user ID to unban", reason="Reason for unban")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = None):
        s = await self._check_module(interaction)
        if not s:
            return
        try:
            user = await self.bot.fetch_user(int(user_id))
        except Exception:
            return await interaction.response.send_message(tr(s, "mod.user_not_found"), ephemeral=True)
        reason_text = reason or tr(s, "mod.no_reason")
        try:
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason_text}")
        except discord.NotFound:
            return await interaction.response.send_message(tr(s, "mod.user_not_banned"), ephemeral=True)
        embed = discord.Embed(
            description=tr(s, "mod.unban_success", user=str(user), reason=reason_text),
            color=config.COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /timeout ───────────────────────────────────────────────────────
    @app_commands.command(name="timeout", description="Timeout (mute) a member")
    @app_commands.describe(member="Member to timeout", duration="Duration (e.g. 10m, 2h, 1d)", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout_cmd(self, interaction: discord.Interaction, member: discord.Member,
                          duration: str, reason: str = None):
        s = await self._check_module(interaction)
        if not s:
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            return await interaction.response.send_message(tr(s, "mod.cannot_target_higher"), ephemeral=True)

        delta = _parse_duration(duration)
        if not delta:
            return await interaction.response.send_message(tr(s, "mod.invalid_duration"), ephemeral=True)

        reason_text = reason or tr(s, "mod.no_reason")
        await member.timeout(delta, reason=f"{interaction.user}: {reason_text}")
        embed = discord.Embed(
            description=f"{e('zb_timeout')} " + tr(s, "mod.timeout_success", user=member.mention, duration=duration, reason=reason_text),
            color=config.COLOR_WARNING,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /untimeout ─────────────────────────────────────────────────────
    @app_commands.command(name="untimeout", description="Remove timeout from a member")
    @app_commands.describe(member="Member to untimeout", reason="Reason")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        s = await self._check_module(interaction)
        if not s:
            return
        reason_text = reason or tr(s, "mod.no_reason")
        await member.timeout(None, reason=f"{interaction.user}: {reason_text}")
        embed = discord.Embed(
            description=tr(s, "mod.untimeout_success", user=member.mention),
            color=config.COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    # ─── /warn ──────────────────────────────────────────────────────────
    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.describe(member="Member to warn", reason="Reason for warning")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        s = await self._check_module(interaction)
        if not s:
            return
        if member.bot:
            return await interaction.response.send_message(tr(s, "mod.cannot_warn_bot"), ephemeral=True)

        warn_id = await async_add_mod_warning(
            str(interaction.guild.id), str(member.id), str(interaction.user.id), reason
        )
        total = await async_count_mod_warnings(str(interaction.guild.id), str(member.id))

        embed = discord.Embed(
            description=f"{e('zb_warn')} " + tr(s, "mod.warn_success", user=member.mention, reason=reason, warn_id=warn_id, total=total),
            color=config.COLOR_WARNING,
        )

        # Auto-escalation
        escalation_msg = ""
        if total >= 5:
            try:
                await member.kick(reason=f"Auto-kick: {total} warnings")
                escalation_msg = tr(s, "mod.auto_kick", total=total)
            except Exception:
                pass
        elif total >= 3:
            try:
                await member.timeout(timedelta(hours=1), reason=f"Auto-timeout: {total} warnings")
                escalation_msg = tr(s, "mod.auto_timeout", total=total)
            except Exception:
                pass

        if escalation_msg:
            embed.add_field(name="⚠️ Auto-Escalation", value=escalation_msg, inline=False)

        try:
            await member.send(tr(s, "mod.warn_dm", server=interaction.guild.name, reason=reason, total=total))
        except Exception:
            pass

        await interaction.response.send_message(embed=embed)

    # ─── /warnings ──────────────────────────────────────────────────────
    @app_commands.command(name="warnings", description="View warnings for a member")
    @app_commands.describe(member="Member to check (default: yourself)")
    @app_commands.guild_only()
    async def warnings(self, interaction: discord.Interaction, member: discord.Member = None):
        s = await self._check_module(interaction)
        if not s:
            return
        target = member or interaction.user
        warns = await async_get_mod_warnings(str(interaction.guild.id), str(target.id))
        if not warns:
            return await interaction.response.send_message(
                tr(s, "mod.no_warnings", user=target.display_name), ephemeral=True
            )
        lines = []
        for w in warns[:15]:
            lines.append(f"`#{w['id']}` — {w['reason'][:60]} (<t:{int(datetime.fromisoformat(w['created_at']).timestamp())}:R>)")
        embed = discord.Embed(
            title=f"{e('zb_warn')} " + tr(s, "mod.warnings_title", user=target.display_name, total=len(warns)),
            description="\n".join(lines),
            color=config.COLOR_WARNING,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ─── /delwarn ───────────────────────────────────────────────────────
    @app_commands.command(name="delwarn", description="Delete a warning by ID")
    @app_commands.describe(warn_id="Warning ID to delete")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def delwarn(self, interaction: discord.Interaction, warn_id: int):
        s = await self._check_module(interaction)
        if not s:
            return
        deleted = await async_delete_mod_warning(warn_id, str(interaction.guild.id))
        if deleted:
            await interaction.response.send_message(tr(s, "mod.delwarn_success", warn_id=warn_id), ephemeral=True)
        else:
            await interaction.response.send_message(tr(s, "mod.delwarn_not_found", warn_id=warn_id), ephemeral=True)

    # ─── /clear ─────────────────────────────────────────────────────────
    @app_commands.command(name="clear", description="Bulk delete messages")
    @app_commands.describe(amount="Number of messages to delete (1-100)", member="Only delete from this member")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction,
                    amount: app_commands.Range[int, 1, 100], member: discord.Member = None):
        s = await self._check_module(interaction)
        if not s:
            return
        await interaction.response.defer(ephemeral=True)

        def check(msg):
            if member and msg.author != member:
                return False
            return True

        deleted = await interaction.channel.purge(limit=amount, check=check, oldest_first=False)
        await interaction.followup.send(
            f"{e('zb_clear')} " + tr(s, "mod.clear_success", count=len(deleted)), ephemeral=True
        )

    # ─── /slowmode ──────────────────────────────────────────────────────
    @app_commands.command(name="slowmode", description="Set slowmode for a channel")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable)", channel="Target channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(self, interaction: discord.Interaction,
                       seconds: app_commands.Range[int, 0, 21600],
                       channel: discord.TextChannel = None):
        s = await self._check_module(interaction)
        if not s:
            return
        target = channel or interaction.channel
        await target.edit(slowmode_delay=seconds)
        if seconds == 0:
            msg = tr(s, "mod.slowmode_off", channel=target.mention)
        else:
            msg = tr(s, "mod.slowmode_on", channel=target.mention, seconds=seconds)
        await interaction.response.send_message(msg, ephemeral=True)

    # ─── /lock ──────────────────────────────────────────────────────────
    @app_commands.command(name="lock", description="Lock a channel (prevent @everyone from sending messages)")
    @app_commands.describe(channel="Channel to lock")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def lock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        s = await self._check_module(interaction)
        if not s:
            return
        target = channel or interaction.channel
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"{e('zb_lock')} " + tr(s, "mod.lock_success", channel=target.mention))

    # ─── /unlock ────────────────────────────────────────────────────────
    @app_commands.command(name="unlock", description="Unlock a channel")
    @app_commands.describe(channel="Channel to unlock")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unlock(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        s = await self._check_module(interaction)
        if not s:
            return
        target = channel or interaction.channel
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(tr(s, "mod.unlock_success", channel=target.mention))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
