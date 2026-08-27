"""
Cog: Fun — Anime GIF interactions, Ship, Marry/Divorce, Profile
Uses nekos.best API for anime GIFs.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import random
import hashlib
import aiohttp
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_get_marriage, async_create_marriage, async_delete_marriage,
    async_add_love_points,
)
from i18n import tr

NEKOS_API = "https://nekos.best/api/v2"


class MarryView(discord.ui.View):
    """Discord Buttons for /marry proposal."""

    def __init__(self, proposer: discord.Member, target: discord.Member, settings: dict):
        super().__init__(timeout=60)
        self.proposer = proposer
        self.target = target
        self.s = settings
        self.result = None

    @discord.ui.button(label="💖 Đồng ý", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message(
                tr(self.s, "fun.marry_not_for_you"), ephemeral=True
            )
        self.result = True
        self.stop()
        # Create marriage
        try:
            await async_create_marriage(
                str(interaction.guild.id), str(self.proposer.id), str(self.target.id)
            )
            embed = discord.Embed(
                description=tr(self.s, "fun.marry_accepted",
                               user1=self.proposer.mention, user2=self.target.mention),
                color=0xFF69B4,
            )
            embed.set_image(url="https://media1.tenor.com/m/MYCyIf0j9AQAAAAC/anime-couple.gif")
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            await interaction.response.send_message(
                tr(self.s, "fun.marry_already_married"), ephemeral=True
            )

    @discord.ui.button(label="💔 Từ chối", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message(
                tr(self.s, "fun.marry_not_for_you"), ephemeral=True
            )
        self.result = False
        self.stop()
        embed = discord.Embed(
            description=tr(self.s, "fun.marry_rejected",
                           user1=self.proposer.mention, user2=self.target.mention),
            color=0x808080,
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        self.stop()


class Fun(commands.Cog):
    """Anime GIF interactions & social/marriage commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _check_module(self, interaction: discord.Interaction) -> dict | None:
        if not interaction.guild:
            return None
        enabled = await async_is_module_enabled(str(interaction.guild.id), "fun")
        if not enabled:
            s = await async_get_guild_settings(str(interaction.guild.id))
            await interaction.response.send_message(
                tr(s, "common.module_disabled", module="Fun"), ephemeral=True
            )
            return None
        return await async_get_guild_settings(str(interaction.guild.id))

    async def _get_gif(self, category: str) -> str | None:
        """Fetch a random anime GIF from nekos.best API."""
        try:
            async with self.session.get(f"{NEKOS_API}/{category}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        return results[0].get("url")
        except Exception:
            pass
        return None

    async def _action_command(self, interaction: discord.Interaction, member: discord.Member,
                              category: str, key_self: str, key_other: str):
        """Generic handler for anime GIF action commands."""
        s = await self._check_module(interaction)
        if not s:
            return
        await interaction.response.defer()

        gif_url = await self._get_gif(category)

        if member.id == interaction.user.id:
            desc = tr(s, key_self, user=interaction.user.mention)
        else:
            desc = tr(s, key_other, user=interaction.user.mention, target=member.mention)
            # Add love points if married
            marriage = await async_get_marriage(str(interaction.guild.id), str(interaction.user.id))
            if marriage:
                partner_id = marriage["user2_id"] if marriage["user1_id"] == str(interaction.user.id) else marriage["user1_id"]
                if str(member.id) == partner_id:
                    await async_add_love_points(str(interaction.guild.id), str(interaction.user.id), 1)

        embed = discord.Embed(description=desc, color=0xFF69B4)
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.followup.send(embed=embed)

    async def _solo_command(self, interaction: discord.Interaction, category: str, key: str):
        """Handler for solo GIF commands (cry, dance)."""
        s = await self._check_module(interaction)
        if not s:
            return
        await interaction.response.defer()
        gif_url = await self._get_gif(category)
        embed = discord.Embed(
            description=tr(s, key, user=interaction.user.mention),
            color=0xFF69B4,
        )
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.followup.send(embed=embed)

    # ─── Action GIF Commands ────────────────────────────────────────────
    @app_commands.command(name="hug", description="Hug someone warmly")
    @app_commands.describe(member="Person to hug")
    @app_commands.guild_only()
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "hug", "fun.hug_self", "fun.hug_other")

    @app_commands.command(name="pat", description="Pat someone on the head")
    @app_commands.describe(member="Person to pat")
    @app_commands.guild_only()
    async def pat(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "pat", "fun.pat_self", "fun.pat_other")

    @app_commands.command(name="kiss", description="Kiss someone")
    @app_commands.describe(member="Person to kiss")
    @app_commands.guild_only()
    async def kiss(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "kiss", "fun.kiss_self", "fun.kiss_other")

    @app_commands.command(name="slap", description="Slap someone playfully")
    @app_commands.describe(member="Person to slap")
    @app_commands.guild_only()
    async def slap(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "slap", "fun.slap_self", "fun.slap_other")

    @app_commands.command(name="feed", description="Feed someone with anime food")
    @app_commands.describe(member="Person to feed")
    @app_commands.guild_only()
    async def feed(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "feed", "fun.feed_self", "fun.feed_other")

    @app_commands.command(name="cuddle", description="Cuddle someone")
    @app_commands.describe(member="Person to cuddle")
    @app_commands.guild_only()
    async def cuddle(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "cuddle", "fun.cuddle_self", "fun.cuddle_other")

    @app_commands.command(name="poke", description="Poke someone")
    @app_commands.describe(member="Person to poke")
    @app_commands.guild_only()
    async def poke(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "poke", "fun.poke_self", "fun.poke_other")

    @app_commands.command(name="highfive", description="High-five someone")
    @app_commands.describe(member="Person to high-five")
    @app_commands.guild_only()
    async def highfive(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "highfive", "fun.highfive_self", "fun.highfive_other")

    @app_commands.command(name="cry", description="Cry emotionally")
    @app_commands.guild_only()
    async def cry(self, interaction: discord.Interaction):
        await self._solo_command(interaction, "cry", "fun.cry")

    @app_commands.command(name="dance", description="Dance happily")
    @app_commands.guild_only()
    async def dance(self, interaction: discord.Interaction):
        await self._solo_command(interaction, "dance", "fun.dance")

    # ─── /ship ──────────────────────────────────────────────────────────
    @app_commands.command(name="ship", description="Check love compatibility between two users")
    @app_commands.describe(user1="First user", user2="Second user (default: you)")
    @app_commands.guild_only()
    async def ship(self, interaction: discord.Interaction, user1: discord.Member,
                   user2: discord.Member = None):
        s = await self._check_module(interaction)
        if not s:
            return

        u2 = user2 or interaction.user
        # Deterministic percentage based on sorted IDs
        pair = sorted([str(user1.id), str(u2.id)])
        seed = hashlib.md5(f"{pair[0]}-{pair[1]}".encode()).hexdigest()
        pct = int(seed[:4], 16) % 101

        # Progress bar
        filled = pct // 10
        bar = "❤️" * filled + "🖤" * (10 - filled)

        # Comment based on percentage
        if pct >= 90:
            comment = tr(s, "fun.ship_perfect")
        elif pct >= 70:
            comment = tr(s, "fun.ship_great")
        elif pct >= 50:
            comment = tr(s, "fun.ship_good")
        elif pct >= 30:
            comment = tr(s, "fun.ship_maybe")
        else:
            comment = tr(s, "fun.ship_low")

        embed = discord.Embed(
            title=f"💘 {user1.display_name} × {u2.display_name}",
            description=f"**{pct}%** {comment}\n{bar}",
            color=discord.Color.from_str("#FF69B4"),
        )
        await interaction.response.send_message(embed=embed)

    # ─── /marry ─────────────────────────────────────────────────────────
    @app_commands.command(name="marry", description="Propose marriage to someone")
    @app_commands.describe(member="Person to propose to")
    @app_commands.guild_only()
    async def marry(self, interaction: discord.Interaction, member: discord.Member):
        s = await self._check_module(interaction)
        if not s:
            return

        if member.id == interaction.user.id:
            return await interaction.response.send_message(tr(s, "fun.marry_self"), ephemeral=True)
        if member.bot:
            return await interaction.response.send_message(tr(s, "fun.marry_bot"), ephemeral=True)

        # Check if either is already married
        existing = await async_get_marriage(str(interaction.guild.id), str(interaction.user.id))
        if existing:
            return await interaction.response.send_message(tr(s, "fun.marry_already_married"), ephemeral=True)
        existing2 = await async_get_marriage(str(interaction.guild.id), str(member.id))
        if existing2:
            return await interaction.response.send_message(tr(s, "fun.marry_target_married"), ephemeral=True)

        view = MarryView(interaction.user, member, s)
        embed = discord.Embed(
            title="💍 " + tr(s, "fun.marry_proposal_title"),
            description=tr(s, "fun.marry_proposal", user1=interaction.user.mention, user2=member.mention),
            color=0xFF69B4,
        )
        await interaction.response.send_message(embed=embed, view=view)

    # ─── /divorce ───────────────────────────────────────────────────────
    @app_commands.command(name="divorce", description="End your marriage")
    @app_commands.guild_only()
    async def divorce(self, interaction: discord.Interaction):
        s = await self._check_module(interaction)
        if not s:
            return

        deleted = await async_delete_marriage(str(interaction.guild.id), str(interaction.user.id))
        if deleted:
            embed = discord.Embed(
                description=tr(s, "fun.divorce_success", user=interaction.user.mention),
                color=0x808080,
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(tr(s, "fun.divorce_not_married"), ephemeral=True)

    # ─── /profile ───────────────────────────────────────────────────────
    @app_commands.command(name="profile", description="View your social profile card")
    @app_commands.describe(member="User to view")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        s = await self._check_module(interaction)
        if not s:
            return

        target = member or interaction.user
        marriage = await async_get_marriage(str(interaction.guild.id), str(target.id))

        embed = discord.Embed(
            title=f"💝 {target.display_name}",
            color=0xFF69B4,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if marriage:
            partner_id = marriage["user2_id"] if marriage["user1_id"] == str(target.id) else marriage["user1_id"]
            partner = interaction.guild.get_member(int(partner_id))
            partner_name = partner.display_name if partner else f"<@{partner_id}>"
            married_at = marriage["married_at"]
            love_pts = marriage.get("love_points", 0)

            try:
                dt = datetime.fromisoformat(married_at)
                days = (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).days
            except Exception:
                days = 0

            embed.add_field(
                name=tr(s, "fun.profile_partner"),
                value=f"💍 {partner_name}",
                inline=True,
            )
            embed.add_field(
                name=tr(s, "fun.profile_days"),
                value=f"📅 {days} " + tr(s, "fun.profile_days_unit"),
                inline=True,
            )
            embed.add_field(
                name=tr(s, "fun.profile_love"),
                value=f"💖 {love_pts}",
                inline=True,
            )
        else:
            embed.description = tr(s, "fun.profile_single")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
