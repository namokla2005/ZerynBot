"""
Cog: Fun — Anime GIF interactions, Ship, Marry/Divorce, Profile
Uses nekos.best API for anime GIFs with interactive action buttons and metadata.
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
    async_increment_fun_interaction, async_get_fun_interaction_count,
)
from i18n import tr
from bot.emojis import e

NEKOS_API = "https://nekos.best/api/v2"
USER_AGENT = "ZerynBot (https://zerynbot.id.vn, 2.0)"

# Curated fallback GIFs if API is unreachable
FALLBACK_GIFS = {
    "hug": [
        ("https://media1.tenor.com/m/kCZVO9q7ixkAAAAC/hug-anime.gif", "Tonari no Kaibutsu-kun"),
        ("https://media1.tenor.com/m/7zb4dKqX3yIAAAAC/anime-hug.gif", "Toradora!"),
    ],
    "pat": [
        ("https://media1.tenor.com/m/wLqFGYigJuIAAAAC/mai-sakurajima.gif", "Seishun Buta Yarou"),
        ("https://media1.tenor.com/m/DCMl9bvOzVUAAAAC/pat-head.gif", "Gochuumon wa Usagi Desuka"),
    ],
    "kiss": [
        ("https://media1.tenor.com/m/IAPyY4b9e28AAAAC/anime-kiss.gif", "Sakura Trick"),
        ("https://media1.tenor.com/m/F02Ep3b2qJgAAAAC/anime-kiss.gif", "Toradora!"),
    ],
    "slap": [
        ("https://media1.tenor.com/m/Ws6Dm1ZW_vMAAAAC/girl-slap.gif", "Toradora!"),
        ("https://media1.tenor.com/m/o_wLqKkI2g4AAAAC/anime-slap.gif", "Chuunibyou demo Koi ga Shitai!"),
    ],
    "feed": [
        ("https://media1.tenor.com/m/vE7w42Y8oQAAAAAC/feed-anime.gif", "Blend S"),
        ("https://media1.tenor.com/m/1Y7iK3j_L2gAAAAC/anime-feed.gif", "Kobayashi-san Chi no Maid Dragon"),
    ],
    "cuddle": [
        ("https://media1.tenor.com/m/e3GfM-7sNfAAAAAC/anime-cuddle.gif", "Tamako Market"),
    ],
    "poke": [
        ("https://media1.tenor.com/m/3Xg0P6lX2g8AAAAC/anime-poke.gif", "K-On!"),
    ],
    "highfive": [
        ("https://media1.tenor.com/m/M1k9b7K8y2gAAAAC/anime-high-five.gif", "Haikyuu!!"),
    ],
    "cry": [
        ("https://media1.tenor.com/m/qV6oK3_8y2gAAAAC/anime-cry.gif", "KonoSuba"),
    ],
    "dance": [
        ("https://media1.tenor.com/m/2cc51c2d-745c-4e6e-866d-80d01f31712e.gif", "Lucky Star"),
    ],
    "marry": [
        ("https://media1.tenor.com/m/MYCyIf0j9AQAAAAC/anime-couple.gif", "Tonikaku Kawaii"),
    ]
}


class ActionResponseView(discord.ui.View):
    """Interactive button allowing the target to respond back (e.g. Slap back, Hug back)."""

    def __init__(self, proposer: discord.Member, target: discord.Member, action_type: str, settings: dict, cog: "Fun"):
        super().__init__(timeout=90)
        self.proposer = proposer
        self.target = target
        self.action_type = action_type
        self.s = settings
        self.cog = cog

        # Dynamically set button label
        btn_key = f"fun.btn_{action_type}_back"
        btn_label = tr(self.s, btn_key)
        if btn_label == btn_key:
            btn_label = f"↩️ {action_type.capitalize()} back"

        btn = discord.ui.Button(label=btn_label, style=discord.ButtonStyle.secondary, emoji=None)
        btn.callback = self.on_respond
        self.add_item(btn)

    async def on_respond(self, interaction: discord.Interaction):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message(
                tr(self.s, "fun.action_not_for_you"), ephemeral=True
            )

        # Disable button on original message
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        # Increment interaction counter: target -> proposer
        count = await async_increment_fun_interaction(
            str(interaction.guild.id), str(self.target.id), str(self.proposer.id), self.action_type
        )

        # Add love points if married
        marriage = await async_get_marriage(str(interaction.guild.id), str(self.target.id))
        if marriage:
            p_id = marriage["user2_id"] if marriage["user1_id"] == str(self.target.id) else marriage["user1_id"]
            if str(self.proposer.id) == p_id:
                await async_add_love_points(str(interaction.guild.id), str(self.target.id), 1)

        # Fetch new random GIF
        gif_url, anime_name = await self.cog._get_gif(self.action_type)

        key_other = f"fun.{self.action_type}_other"
        desc = tr(self.s, key_other, user=self.target.mention, target=self.proposer.mention)
        count_key = f"fun.count_{self.action_type}"
        count_text = tr(self.s, count_key, target=self.proposer.display_name, count=count)
        if count_text != count_key:
            desc = f"{desc}\n{count_text}"

        embed = discord.Embed(description=desc, color=0xFF69B4)
        if gif_url:
            embed.set_image(url=gif_url)
        if anime_name:
            embed.set_footer(text=f"Anime: {anime_name}")

        # Attach next counter view so the cycle can continue playfully
        next_view = ActionResponseView(
            proposer=self.target,
            target=self.proposer,
            action_type=self.action_type,
            settings=self.s,
            cog=self.cog,
        )
        await interaction.response.send_message(embed=embed, view=next_view)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class MarryView(discord.ui.View):
    """Discord Buttons for /marry proposal."""

    def __init__(self, proposer: discord.Member, target: discord.Member, settings: dict, cog: "Fun"):
        super().__init__(timeout=60)
        self.proposer = proposer
        self.target = target
        self.s = settings
        self.cog = cog
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
            gif_url, anime_name = await self.cog._get_gif("hug")
            if not gif_url:
                gif_url = "https://media1.tenor.com/m/MYCyIf0j9AQAAAAC/anime-couple.gif"
                anime_name = "Tonikaku Kawaii"
            embed.set_image(url=gif_url)
            if anime_name:
                embed.set_footer(text=f"Anime: {anime_name}")
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
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=5)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)

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

    async def _get_gif(self, category: str) -> tuple[str | None, str | None]:
        """Fetch a random anime GIF and anime title from nekos.best API with curated fallback."""
        if not self.session or self.session.closed:
            headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
            self.session = aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=5))

        try:
            async with self.session.get(f"{NEKOS_API}/{category}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        r = results[0]
                        return r.get("url"), r.get("anime_name")
        except Exception:
            pass

        # Fallback to curated anime GIFs if API request times out or is unavailable
        if category in FALLBACK_GIFS:
            choice = random.choice(FALLBACK_GIFS[category])
            return choice[0], choice[1]

        return None, None

    async def _action_command(self, interaction: discord.Interaction, member: discord.Member,
                              category: str, key_self: str, key_other: str):
        """Generic handler for anime GIF action commands."""
        s = await self._check_module(interaction)
        if not s:
            return
        await interaction.response.defer()

        gif_url, anime_name = await self._get_gif(category)

        if member.id == interaction.user.id:
            desc = tr(s, key_self, user=interaction.user.mention)
            embed = discord.Embed(description=desc, color=0xFF69B4)
            if gif_url:
                embed.set_image(url=gif_url)
            if anime_name:
                embed.set_footer(text=f"Anime: {anime_name}")
            await interaction.followup.send(embed=embed)
        else:
            # Increment interaction counter
            count = await async_increment_fun_interaction(
                str(interaction.guild.id), str(interaction.user.id), str(member.id), category
            )

            # Add love points if married
            marriage = await async_get_marriage(str(interaction.guild.id), str(interaction.user.id))
            if marriage:
                partner_id = marriage["user2_id"] if marriage["user1_id"] == str(interaction.user.id) else marriage["user1_id"]
                if str(member.id) == partner_id:
                    await async_add_love_points(str(interaction.guild.id), str(interaction.user.id), 1)

            desc = tr(s, key_other, user=interaction.user.mention, target=member.mention)
            count_key = f"fun.count_{category}"
            count_text = tr(s, count_key, target=member.display_name, count=count)
            if count_text != count_key:
                desc = f"{desc}\n{count_text}"

            embed = discord.Embed(description=desc, color=0xFF69B4)
            if gif_url:
                embed.set_image(url=gif_url)
            if anime_name:
                embed.set_footer(text=f"Anime: {anime_name}")

            # Attach interactive response button (e.g. Slap back, Hug back)
            view = ActionResponseView(
                proposer=interaction.user,
                target=member,
                action_type=category,
                settings=s,
                cog=self,
            )
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg

    async def _solo_command(self, interaction: discord.Interaction, category: str, key: str):
        """Handler for solo GIF commands (cry, dance)."""
        s = await self._check_module(interaction)
        if not s:
            return
        await interaction.response.defer()
        gif_url, anime_name = await self._get_gif(category)
        embed = discord.Embed(
            description=tr(s, key, user=interaction.user.mention),
            color=0xFF69B4,
        )
        if gif_url:
            embed.set_image(url=gif_url)
        if anime_name:
            embed.set_footer(text=f"Anime: {anime_name}")
        await interaction.followup.send(embed=embed)

    # ─── Action GIF Commands ────────────────────────────────────────────
    @app_commands.command(name="hug", description="Hug someone warmly with anime GIF")
    @app_commands.describe(member="Person to hug")
    @app_commands.guild_only()
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "hug", "fun.hug_self", "fun.hug_other")

    @app_commands.command(name="pat", description="Pat someone on the head with anime GIF")
    @app_commands.describe(member="Person to pat")
    @app_commands.guild_only()
    async def pat(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "pat", "fun.pat_self", "fun.pat_other")

    @app_commands.command(name="kiss", description="Kiss someone with anime GIF")
    @app_commands.describe(member="Person to kiss")
    @app_commands.guild_only()
    async def kiss(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "kiss", "fun.kiss_self", "fun.kiss_other")

    @app_commands.command(name="slap", description="Slap someone playfully with anime GIF")
    @app_commands.describe(member="Person to slap")
    @app_commands.guild_only()
    async def slap(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "slap", "fun.slap_self", "fun.slap_other")

    @app_commands.command(name="feed", description="Feed someone with anime food")
    @app_commands.describe(member="Person to feed")
    @app_commands.guild_only()
    async def feed(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "feed", "fun.feed_self", "fun.feed_other")

    @app_commands.command(name="cuddle", description="Cuddle someone with anime GIF")
    @app_commands.describe(member="Person to cuddle")
    @app_commands.guild_only()
    async def cuddle(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "cuddle", "fun.cuddle_self", "fun.cuddle_other")

    @app_commands.command(name="poke", description="Poke someone with anime GIF")
    @app_commands.describe(member="Person to poke")
    @app_commands.guild_only()
    async def poke(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "poke", "fun.poke_self", "fun.poke_other")

    @app_commands.command(name="highfive", description="High-five someone with anime GIF")
    @app_commands.describe(member="Person to high-five")
    @app_commands.guild_only()
    async def highfive(self, interaction: discord.Interaction, member: discord.Member):
        await self._action_command(interaction, member, "highfive", "fun.highfive_self", "fun.highfive_other")

    @app_commands.command(name="cry", description="Cry emotionally with anime GIF")
    @app_commands.guild_only()
    async def cry(self, interaction: discord.Interaction):
        await self._solo_command(interaction, "cry", "fun.cry")

    @app_commands.command(name="dance", description="Dance happily with anime GIF")
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
        await interaction.response.defer()

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
            category = "kiss"
        elif pct >= 70:
            comment = tr(s, "fun.ship_great")
            category = "hug"
        elif pct >= 50:
            comment = tr(s, "fun.ship_good")
            category = "cuddle"
        elif pct >= 30:
            comment = tr(s, "fun.ship_maybe")
            category = "pat"
        else:
            comment = tr(s, "fun.ship_low")
            category = "slap"

        gif_url, anime_name = await self._get_gif(category)

        embed = discord.Embed(
            title=f"{e('zb_ship')} {user1.display_name} × {u2.display_name}",
            description=f"**{pct}%** {comment}\n{bar}",
            color=discord.Color.from_str("#FF69B4"),
        )
        if gif_url:
            embed.set_image(url=gif_url)
        if anime_name:
            embed.set_footer(text=f"Anime: {anime_name}")

        await interaction.followup.send(embed=embed)

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

        view = MarryView(interaction.user, member, s, self)
        embed = discord.Embed(
            title=f"{e('zb_marry')} " + tr(s, "fun.marry_proposal_title"),
            description=tr(s, "fun.marry_proposal", user1=interaction.user.mention, user2=member.mention),
            color=0xFF69B4,
        )
        gif_url, anime_name = await self._get_gif("handhold")
        if not gif_url:
            gif_url, anime_name = await self._get_gif("hug")
        if gif_url:
            embed.set_image(url=gif_url)
        if anime_name:
            embed.set_footer(text=f"Anime: {anime_name}")

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
            gif_url, anime_name = await self._get_gif("cry")
            if gif_url:
                embed.set_image(url=gif_url)
            if anime_name:
                embed.set_footer(text=f"Anime: {anime_name}")
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
