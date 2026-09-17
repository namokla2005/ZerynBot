"""
Cog: Utility (v2) — Prefix commands: ping, membercount, help
"""
import sys, os, time, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from datetime import datetime, timezone
import config
from database import async_get_guild_settings
from i18n import tr
try:
    from emojis import e, partial, embed_title, clean_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, partial, embed_title, clean_title


class DeleteHelpButton(discord.ui.Button):
    def __init__(self, settings: dict, author_id: int):
        super().__init__(
            label=tr(settings, "help.btn_delete") if tr(settings, "help.btn_delete") != "help.btn_delete" else "Đóng",
            style=discord.ButtonStyle.secondary,
            emoji=partial("zb_clear", "🗑️"),
            row=1
        )
        self.author_id = author_id
        self.settings = settings

    async def callback(self, interaction: discord.Interaction):
        has_manage = False
        if interaction.guild and hasattr(interaction.user, "guild_permissions"):
            has_manage = interaction.user.guild_permissions.manage_messages
        if interaction.user.id != self.author_id and not has_manage:
            return await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)
        try:
            await interaction.message.delete()
        except Exception:
            pass


class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, ctx: commands.Context, settings: dict):
        self.bot = bot
        self.ctx = ctx
        self.settings = settings

        options = [
            discord.SelectOption(
                label=tr(settings, "help.home_label"),
                description=tr(settings, "help.home_desc")[:100],
                emoji=partial("zb_cat_home", "🏠"),
                value="home",
                default=True
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_ai_label"),
                description=tr(settings, "help.cat_ai_desc")[:100],
                emoji=partial("zb_cat_ai", "🤖"),
                value="ai"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_eco_label"),
                description=tr(settings, "help.cat_eco_desc")[:100],
                emoji=partial("zb_cat_economy", "💰"),
                value="economy"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_fun_label"),
                description=tr(settings, "help.cat_fun_desc")[:100],
                emoji=partial("zb_cat_fun", "🎭"),
                value="fun"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_music_label"),
                description=tr(settings, "help.cat_music_desc")[:100],
                emoji=partial("zb_cat_music", "🎵"),
                value="music"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_mod_label"),
                description=tr(settings, "help.cat_mod_desc")[:100],
                emoji=partial("zb_cat_moderation", "🛡️"),
                value="moderation"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_automod_label"),
                description=tr(settings, "help.cat_automod_desc")[:100],
                emoji=partial("zb_cat_automod", "🔒"),
                value="automod"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_level_label"),
                description=tr(settings, "help.cat_level_desc")[:100],
                emoji=partial("zb_cat_leveling", "🌟"),
                value="leveling"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_voice_label"),
                description=tr(settings, "help.cat_voice_desc")[:100],
                emoji=partial("zb_cat_voice", "🎙️"),
                value="voice"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_info_label"),
                description=tr(settings, "help.cat_info_desc")[:100],
                emoji=partial("zb_cat_info", "ℹ️"),
                value="info"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_util_label"),
                description=tr(settings, "help.cat_util_desc")[:100],
                emoji=partial("zb_cat_utility", "⚙️"),
                value="utility"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_giveaway_label"),
                description=tr(settings, "help.cat_giveaway_desc")[:100],
                emoji=partial("zb_cat_giveaway", "🎁"),
                value="giveaway"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_ticket_label"),
                description=tr(settings, "help.cat_ticket_desc")[:100],
                emoji=partial("zb_cat_tickets", "🎫"),
                value="tickets"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_birthday_label"),
                description=tr(settings, "help.cat_birthday_desc")[:100],
                emoji=partial("zb_cat_birthday", "🎂"),
                value="birthday"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_customcmd_label"),
                description=tr(settings, "help.cat_customcmd_desc")[:100],
                emoji=partial("zb_cat_customcmd", "⚡"),
                value="customcmd"
            ),
            discord.SelectOption(
                label=tr(settings, "help.cat_verify_label"),
                description=tr(settings, "help.cat_verify_desc")[:100],
                emoji=partial("zb_verified", "🛡️"),
                value="verify"
            ),
        ]
        super().__init__(
            placeholder=tr(settings, "help.placeholder"),
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)

        for opt in self.options:
            opt.default = (opt.value == self.values[0])

        val = self.values[0]
        color_map = {
            "home": 0xF4A7BB,
            "ai": 0x9D8DF1,
            "economy": 0xFEE75C,
            "fun": 0xEB6F92,
            "music": 0x5865F2,
            "moderation": 0xED4245,
            "automod": 0x34495E,
            "leveling": 0xF1C40F,
            "voice": 0x57F287,
            "info": 0x3498DB,
            "utility": 0x95A5A6,
            "giveaway": 0xE91E63,
            "tickets": 0x2ECC71,
            "birthday": 0xFF7675,
            "customcmd": 0x9B59B6,
            "verify": 0x57F287,
        }

        embed = discord.Embed(
            color=color_map.get(val, 0xF4A7BB),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(
            text=tr(self.settings, "common.requested_by", user=self.ctx.author.display_name),
            icon_url=self.ctx.author.display_avatar.url
        )

        if self.bot.user.display_avatar:
            embed.set_author(
                name="Zeryn Bot • Command Center",
                icon_url=self.bot.user.display_avatar.url,
                url="https://zerynbot.id.vn"
            )

        def get_modules_display():
            return (
                f"{e('zb_cat_ai')} `AI` • {e('zb_cat_economy')} `Economy` • {e('zb_cat_music')} `Music` • {e('zb_cat_moderation')} `Moderation`\n"
                f"{e('zb_cat_automod')} `AutoMod` • {e('zb_cat_leveling')} `Leveling` • {e('zb_cat_voice')} `TempVoice` • {e('zb_cat_utility')} `Utility`\n"
                f"{e('zb_cat_giveaway')} `Giveaway` • {e('zb_cat_tickets')} `Tickets` • {e('zb_cat_birthday')} `Birthday` • {e('zb_verified')} `Verify Gate`\n"
                f"{e('zb_cat_info')} `Info` • {e('zb_cat_fun')} `Fun` • {e('zb_cat_customcmd')} `CustomCmd` • {e('zb_logger')} `Logger`\n"
                f"{e('zb_welcome')} `Welcome` • {e('zb_autorole')} `AutoRoles` • {e('zb_reactionroles')} `ReactionRoles` • {e('zb_remind')} `Remind`"
            )

        if val == "home":
            embed.title = embed_title("zb_cat_home", tr(self.settings, "help.home_title"))
            raw_desc = tr(self.settings, "help.description")
            embed.description = raw_desc.replace("🪙", e("zb_coin")).replace("💰", e("zb_bank"))
            if self.bot.user.display_avatar:
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            ws_ping = round(self.bot.latency * 1000)
            embed.add_field(
                name=embed_title("zb_ping", tr(self.settings, "help.stats_title")),
                value=tr(self.settings, "help.stats_val", ping=ws_ping, uptime="99.9%"),
                inline=True
            )
            embed.add_field(
                name=tr(self.settings, "help.modules_title"),
                value=get_modules_display(),
                inline=True
            )
            embed.add_field(
                name=tr(self.settings, "help.guide_name"),
                value=tr(self.settings, "help.guide_value"),
                inline=False
            )
        else:
            cat_key_map = {
                "ai": "ai",
                "economy": "eco",
                "fun": "fun",
                "music": "music",
                "moderation": "mod",
                "automod": "automod",
                "leveling": "level",
                "voice": "voice",
                "info": "info",
                "utility": "util",
                "giveaway": "giveaway",
                "tickets": "ticket",
                "birthday": "birthday",
                "customcmd": "customcmd",
                "verify": "verify",
            }
            prefix = cat_key_map.get(val, val)
            raw_title = tr(self.settings, f"help.cat_{prefix}_title")
            emoji_key = "zb_verified" if val == "verify" else f"zb_cat_{val}"
            embed.title = embed_title(emoji_key, raw_title)
            raw_cmds = tr(self.settings, f"help.cat_{prefix}_cmds")
            embed.description = raw_cmds.replace("🪙", e("zb_coin")).replace("💰", e("zb_bank"))

        await interaction.response.edit_message(embed=embed, view=self.view)



class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, ctx: commands.Context, settings: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.ctx = ctx
        self.settings = settings
        self.message = None

        # Row 0: Select dropdown
        self.add_item(HelpSelect(bot, ctx, settings))

        # Row 1: Action links & Delete button
        client_id = config.CLIENT_ID or (str(bot.user.id) if bot.user else "1396825488198078514")
        invite_url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot%20applications.commands"

        btn_dashboard = tr(settings, "help.btn_dashboard") if tr(settings, "help.btn_dashboard") != "help.btn_dashboard" else "Dashboard"
        btn_support = tr(settings, "help.btn_support") if tr(settings, "help.btn_support") != "help.btn_support" else "Support Server"
        btn_invite = tr(settings, "help.btn_invite") if tr(settings, "help.btn_invite") != "help.btn_invite" else "Add Bot"

        self.add_item(discord.ui.Button(label=btn_dashboard, style=discord.ButtonStyle.link, url="https://zerynbot.id.vn", emoji="🌐", row=1))
        self.add_item(discord.ui.Button(label=btn_support, style=discord.ButtonStyle.link, url="https://discord.gg/VPybhdNbXC", emoji="💬", row=1))
        self.add_item(discord.ui.Button(label=btn_invite, style=discord.ButtonStyle.link, url=invite_url, emoji="➕", row=1))
        self.add_item(DeleteHelpButton(settings, ctx.author.id))

    async def on_timeout(self):
        for item in self.children:
            if not isinstance(item, discord.ui.Button) or item.style != discord.ButtonStyle.link:
                item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class Utility(commands.Cog):
    """Lệnh tiện ích."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx: commands.Context):
        if not ctx.guild:
            return
        from database import async_is_module_enabled
        enabled = await async_is_module_enabled(str(ctx.guild.id), "utility")
        if not enabled:
            s = await async_get_guild_settings(str(ctx.guild.id))
            await ctx.send(tr(s, "common.module_disabled", module="Utility"))
            raise commands.CommandError("Module disabled")

    # ─── ping ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="ping", description="Kiểm tra độ trễ kết nối của bot")
    async def ping(self, ctx: commands.Context):
        ws = round(self.bot.latency * 1000)

        t0 = time.perf_counter()
        await ctx.defer()
        t1 = time.perf_counter()
        api = round((t1 - t0) * 1000)

        guild_id = str(ctx.guild.id) if ctx.guild else ""
        settings = await async_get_guild_settings(guild_id) if guild_id else {}

        if ws < 80:
            quality = tr(settings, "utility.quality_excellent")
        elif ws < 150:
            quality = tr(settings, "utility.quality_good")
        elif ws < 300:
            quality = tr(settings, "utility.quality_medium")
        else:
            quality = tr(settings, "utility.quality_poor")

        embed = discord.Embed(
            title=embed_title("zb_ping", tr(settings, "utility.ping_title")),
            color=config.COLOR_PING,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name=f"🌐 {tr(settings, 'utility.ping_ws')}", value=f"**{ws}** ms", inline=True)
        embed.add_field(name=f"📡 {tr(settings, 'utility.ping_api')}", value=f"**{api}** ms", inline=True)
        embed.add_field(name=f"📊 {tr(settings, 'utility.ping_quality')}", value=quality, inline=True)
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.reply(embed=embed)

    # ─── membercount ───────────────────────────────────────────────────────────
    @commands.hybrid_command(name="membercount", description="Thống kê số lượng thành viên và bot trong server")
    @commands.guild_only()
    async def membercount(self, ctx: commands.Context):
        guild  = ctx.guild
        total  = guild.member_count or len(guild.members)

        bots = online = idle = dnd = offline = 0
        for m in guild.members:
            if m.bot:
                bots += 1
            if m.status == discord.Status.online:
                online += 1
            elif m.status == discord.Status.idle:
                idle += 1
            elif m.status == discord.Status.dnd:
                dnd += 1
            else:
                offline += 1

        humans = total - bots
        human_pct = round(humans / total * 100, 1) if total else 0
        bot_pct   = round(bots   / total * 100, 1) if total else 0

        bar_len   = 20
        filled    = round(human_pct / 100 * bar_len)
        progress  = f"`{'█' * filled}{'░' * (bar_len - filled)}` {human_pct}%"

        settings = await async_get_guild_settings(str(guild.id))

        embed = discord.Embed(
            title=embed_title("zb_cat_info", tr(settings, "utility.membercount_title", server=guild.name)),
            color=config.COLOR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name=f"📊 {tr(settings, 'utility.membercount_total')}",  value=f"**{total}**", inline=True)
        embed.add_field(name=f"👤 {tr(settings, 'utility.membercount_humans')}", value=f"**{humans}** ({human_pct}%)", inline=True)
        embed.add_field(name=f"{e('zb_cat_ai')} {tr(settings, 'utility.membercount_bots')}",   value=f"**{bots}** ({bot_pct}%)", inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_ratio')}", value=progress, inline=False)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_online')}", value=f"**{online}**",  inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_idle')}",   value=f"**{idle}**",    inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_dnd')}",    value=f"**{dnd}**",     inline=True)
        embed.add_field(name=f"{tr(settings, 'utility.membercount_offline')}", value=f"**{offline}**", inline=True)
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    # ─── help ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="help", description="Trung tâm hỗ trợ và hướng dẫn toàn bộ lệnh của Zeryn Bot")
    @discord.app_commands.describe(command="Tên lệnh cần tra cứu chi tiết (VD: play, coinflip, ban, verify...)")
    async def help_cmd(self, ctx: commands.Context, *, command: str = None):
        settings = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        ws_ping = round(self.bot.latency * 1000)

        if command:
            from bot.commands_data import get_command_data
            cmd_data = get_command_data(command)
            if not cmd_data:
                err_msg = tr(settings, "help.cmd_not_found", cmd=command)
                return await ctx.send(err_msg, ephemeral=True)

            cmd_name = cmd_data["name"]
            embed = discord.Embed(
                title=tr(settings, "help.cmd_detail_title", cmd=cmd_name),
                description=cmd_data.get("desc", ""),
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc),
            )
            if self.bot.user and self.bot.user.display_avatar:
                embed.set_author(
                    name="Zeryn Bot • Command Guide",
                    icon_url=self.bot.user.display_avatar.url,
                    url="https://zerynbot.id.vn/commands"
                )

            usage = cmd_data.get("usage", f"/{cmd_name}")
            embed.add_field(
                name=tr(settings, "help.cmd_usage_field"),
                value=f"`{usage}`",
                inline=False
            )

            example = cmd_data.get("example", f"/{cmd_name}")
            embed.add_field(
                name=tr(settings, "help.cmd_example_field"),
                value=f"`{example}`",
                inline=False
            )

            if cmd_data.get("args"):
                args_lines = []
                for a in cmd_data["args"]:
                    req_str = "bắt buộc" if a.get("required") else "tùy chọn"
                    type_str = a.get("type", "Text")
                    args_lines.append(f"• `{a['name']}` ({type_str}, {req_str}): {a.get('desc', '')}")
                embed.add_field(
                    name=tr(settings, "help.cmd_params_field"),
                    value="\n".join(args_lines),
                    inline=False
                )

            if cmd_data.get("perm"):
                embed.add_field(
                    name=tr(settings, "help.cmd_perm_field"),
                    value=f"`{cmd_data['perm']}`",
                    inline=False
                )

            embed.set_footer(
                text=tr(settings, "common.requested_by", user=ctx.author.display_name),
                icon_url=ctx.author.display_avatar.url,
            )

            view = discord.ui.View()
            view.add_item(discord.ui.Button(
                label=tr(settings, "help.btn_dashboard") if tr(settings, "help.btn_dashboard") != "help.btn_dashboard" else "Dashboard",
                style=discord.ButtonStyle.link,
                url="https://zerynbot.id.vn/commands",
                emoji="🌐"
            ))
            return await ctx.send(embed=embed, view=view)

        def get_modules_display():
            return (
                f"{e('zb_cat_ai')} `AI` • {e('zb_cat_economy')} `Economy` • {e('zb_cat_music')} `Music` • {e('zb_cat_moderation')} `Moderation`\n"
                f"{e('zb_cat_automod')} `AutoMod` • {e('zb_cat_leveling')} `Leveling` • {e('zb_cat_voice')} `TempVoice` • {e('zb_cat_utility')} `Utility`\n"
                f"{e('zb_cat_giveaway')} `Giveaway` • {e('zb_cat_tickets')} `Tickets` • {e('zb_cat_birthday')} `Birthday` • {e('zb_verified')} `Verify Gate`\n"
                f"{e('zb_cat_info')} `Info` • {e('zb_cat_fun')} `Fun` • {e('zb_cat_customcmd')} `CustomCmd` • {e('zb_logger')} `Logger`\n"
                f"{e('zb_welcome')} `Welcome` • {e('zb_autorole')} `AutoRoles` • {e('zb_reactionroles')} `ReactionRoles` • {e('zb_remind')} `Remind`"
            )

        raw_desc = tr(settings, "help.description")
        embed = discord.Embed(
            title=embed_title("zb_cat_home", tr(settings, "help.home_title")),
            description=raw_desc.replace("🪙", e("zb_coin")).replace("💰", e("zb_bank")),
            color=0xF4A7BB,
            timestamp=datetime.now(timezone.utc),
        )
        if self.bot.user.display_avatar:
            embed.set_author(
                name="Zeryn Bot • Command Center",
                icon_url=self.bot.user.display_avatar.url,
                url="https://zerynbot.id.vn"
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        embed.add_field(
            name=embed_title("zb_ping", tr(settings, "help.stats_title")),
            value=tr(settings, "help.stats_val", ping=ws_ping, uptime="99.9%"),
            inline=True
        )
        embed.add_field(
            name=tr(settings, "help.modules_title"),
            value=get_modules_display(),
            inline=True
        )
        embed.add_field(
            name=tr(settings, "help.guide_name"),
            value=tr(settings, "help.guide_value"),
            inline=False,
        )
        embed.set_footer(
            text=tr(settings, "common.requested_by", user=ctx.author.display_name),
            icon_url=ctx.author.display_avatar.url,
        )

        view = HelpView(self.bot, ctx, settings)
        view.message = await ctx.send(embed=embed, view=view)

    @help_cmd.autocomplete("command")
    async def help_autocomplete(self, interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
        from bot.commands_data import ALL_COMMAND_NAMES
        curr = (current or "").strip().lower().lstrip("/")
        matches = []
        for name in ALL_COMMAND_NAMES:
            if not curr or curr in name.lower():
                matches.append(discord.app_commands.Choice(name=f"/{name}", value=name))
            if len(matches) >= 25:
                break
        return matches

    # ─── poll ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="poll", description="Tạo một cuộc bình chọn nhanh")
    @discord.app_commands.describe(question="Câu hỏi bình chọn")
    async def poll(self, ctx: commands.Context, *, question: str):
        s = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        embed = discord.Embed(
            title=embed_title("zb_poll", tr(s, "utility.poll_title")),
            description=tr(s, "utility.poll_desc", question=question),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "utility.poll_created_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await msg.add_reaction("🤷")

    # ─── roll ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="roll", description="Tung xúc xắc (ngẫu nhiên từ 1 đến số chỉ định)")
    @discord.app_commands.describe(max_number="Số lớn nhất (mặc định là 100)")
    async def roll(self, ctx: commands.Context, max_number: int = 100):
        s = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        if max_number <= 1:
            await ctx.send(tr(s, "utility.roll_min_err"))
            return
        result = random.randint(1, max_number)
        embed = discord.Embed(
            title=tr(s, "utility.roll_title"),
            description=tr(s, "utility.roll_result", res=result, max=max_number),
            color=0xFEE75C
        )
        await ctx.send(embed=embed)

    # ─── choose ────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="choose", description="Bot sẽ chọn ngẫu nhiên giúp bạn một phương án")
    @discord.app_commands.describe(options="Các phương án cách nhau bởi dấu phẩy (VD: Ăn cơm, Ăn phở, Nhịn)")
    async def choose(self, ctx: commands.Context, *, options: str):
        s = await async_get_guild_settings(str(ctx.guild.id)) if ctx.guild else {}
        opts = [o.strip() for o in options.split(",") if o.strip()]
        if len(opts) < 2:
            await ctx.send(tr(s, "utility.choose_min_err"))
            return
        result = random.choice(opts)
        embed = discord.Embed(
            title=tr(s, "utility.choose_title"),
            description=tr(s, "utility.choose_result", opts=", ".join(opts), res=result),
            color=config.COLOR_INFO
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))

