"""
Cog: Economy & Mini-Games (v2)
Features: Daily streak, Wallet/Bank balance, Transfers, Coinflip, Slots, Interactive Blackjack, Server Role Shop.
Optimized for ARM / Termux with pure async database transactions.
"""
import sys, os, time, random, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import config
from database import (
    async_get_guild_settings, async_is_module_enabled,
    async_get_economy_settings, async_get_economy_user,
    async_claim_daily, async_modify_wallet, async_transfer_money,
    async_deposit_money, async_withdraw_money,
    async_get_economy_shop, async_buy_shop_item, async_get_top_economy
)
from i18n import tr


# ─── Blackjack Game Engine & UI View ──────────────────────────────────────────

CARD_SUITS = ['♠', '♥', '♦', '♣']
CARD_RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
CARD_VALUES = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
    'J': 10, 'Q': 10, 'K': 10, 'A': 11
}

def create_deck():
    deck = [f"{r}{s}" for s in CARD_SUITS for r in CARD_RANKS]
    random.shuffle(deck)
    return deck

def calc_hand(hand: list[str]) -> int:
    val = 0
    aces = 0
    for card in hand:
        rank = card[:-1]
        val += CARD_VALUES[rank]
        if rank == 'A':
            aces += 1
    while val > 21 and aces > 0:
        val -= 10
        aces -= 1
    return val

def fmt_hand(hand: list[str]) -> str:
    return " ".join([f"`{c}`" for c in hand]) + f" (*{calc_hand(hand)} điểm*)"


class BlackjackView(discord.ui.View):
    def __init__(self, cog, ctx: commands.Context, bet: int, settings: dict):
        super().__init__(timeout=60.0)
        self.cog = cog
        self.ctx = ctx
        self.bet = bet
        self.settings = settings
        self.deck = create_deck()
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.message: discord.Message | None = None
        self.is_finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(tr(self.settings, "common.no_permission"), ephemeral=True)
            return False
        return True

    def build_embed(self, hide_dealer: bool = True, title_status: str = None, color: int = 0x5865F2) -> discord.Embed:
        sym = self.settings.get("currency_symbol", "🪙")
        embed = discord.Embed(
            title=title_status or tr(self.settings, "economy.bj_title"),
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        
        if hide_dealer:
            dealer_str = f"`{self.dealer_hand[0]}` `🎴` (*? điểm*)"
        else:
            dealer_str = fmt_hand(self.dealer_hand)

        embed.add_field(name=f"🤖 {tr(self.settings, 'economy.bj_dealer')}", value=dealer_str, inline=False)
        embed.add_field(name=f"👤 {self.ctx.author.display_name}", value=fmt_hand(self.player_hand), inline=False)
        embed.set_footer(text=f"{tr(self.settings, 'economy.bet_amount')}: {self.bet:,} {sym}")
        return embed

    async def finish_game(self, result: str, interaction: discord.Interaction = None):
        """result: 'win', 'lose', 'bust', 'tie', 'blackjack'"""
        self.is_finished = True
        self.stop()
        sym = self.settings.get("currency_symbol", "🪙")
        
        for child in self.children:
            child.disabled = True

        if result == "win":
            payout = self.bet * 2
            await async_modify_wallet(str(self.ctx.guild.id), str(self.ctx.author.id), payout)
            status = tr(self.settings, "economy.bj_win", amount=self.bet, sym=sym)
            color = 0x57F287
        elif result == "blackjack":
            payout = int(self.bet * 2.5)
            await async_modify_wallet(str(self.ctx.guild.id), str(self.ctx.author.id), payout)
            status = tr(self.settings, "economy.bj_blackjack", amount=int(self.bet * 1.5), sym=sym)
            color = 0xFEE75C
        elif result == "tie":
            await async_modify_wallet(str(self.ctx.guild.id), str(self.ctx.author.id), self.bet)
            status = tr(self.settings, "economy.bj_tie", sym=sym)
            color = 0x95A5A6
        elif result == "bust":
            status = tr(self.settings, "economy.bj_bust", amount=self.bet, sym=sym)
            color = 0xED4245
        else: # lose
            status = tr(self.settings, "economy.bj_lose", amount=self.bet, sym=sym)
            color = 0xED4245

        embed = self.build_embed(hide_dealer=False, title_status=status, color=color)
        if interaction:
            await interaction.response.edit_message(embed=embed, view=self)
        elif self.message:
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Rút (Hit)", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_finished:
            return
        self.player_hand.append(self.deck.pop())
        pval = calc_hand(self.player_hand)
        if pval > 21:
            await self.finish_game("bust", interaction)
        elif pval == 21:
            await self.dealer_turn(interaction)
        else:
            embed = self.build_embed(hide_dealer=True)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Dừng (Stand)", style=discord.ButtonStyle.secondary, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_finished:
            return
        await self.dealer_turn(interaction)

    async def dealer_turn(self, interaction: discord.Interaction):
        # Dealer draws until 17 or higher
        while calc_hand(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
            
        pval = calc_hand(self.player_hand)
        dval = calc_hand(self.dealer_hand)
        
        if dval > 21 or pval > dval:
            await self.finish_game("win", interaction)
        elif dval > pval:
            await self.finish_game("lose", interaction)
        else:
            await self.finish_game("tie", interaction)

    async def on_timeout(self):
        if not self.is_finished:
            await self.finish_game("lose")


# ─── Economy Cog ───────────────────────────────────────────────────────────────

class Economy(commands.Cog):
    """Module quản lý Tiền tệ, Mini-games & Cửa hàng Role."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        return await async_is_module_enabled(str(ctx.guild.id), "economy")

    # ─── daily ─────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="daily", description="Điểm danh nhận tiền hàng ngày (tích lũy chuỗi ngày)")
    async def daily(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        user_data = await async_get_economy_user(str(ctx.guild.id), str(ctx.author.id))
        
        last_daily = user_data.get("last_daily_at", 0)
        now = time.time()
        cooldown = 86400  # 24 giờ
        
        if now - last_daily < cooldown:
            remaining = int(cooldown - (now - last_daily))
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            await ctx.send(tr(s, "economy.daily_cooldown", hours=hours, mins=mins), ephemeral=True)
            return

        # Tính streak (nếu trong vòng 48h thì giữ streak, quá 48h thì reset về 1)
        current_streak = user_data.get("daily_streak", 0)
        if now - last_daily < 172800: # 48 giờ
            new_streak = current_streak + 1
        else:
            new_streak = 1

        base_reward = eco_s.get("daily_amount", 100)
        streak_bonus = (new_streak - 1) * eco_s.get("streak_bonus", 20)
        # Bonus ngày 7 x2
        multiplier = 2 if (new_streak % 7 == 0) else 1
        total_reward = (base_reward + streak_bonus) * multiplier
        
        sym = eco_s.get("currency_symbol", "🪙")
        await async_claim_daily(str(ctx.guild.id), str(ctx.author.id), total_reward, new_streak)
        
        embed = discord.Embed(
            title=tr(s, "economy.daily_title"),
            description=tr(s, "economy.daily_desc", amount=total_reward, sym=sym, streak=new_streak),
            color=0x57F287,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── balance ───────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="balance", aliases=["cash", "money", "bal"], description="Xem số dư ví và ngân hàng")
    @app_commands.describe(member="Thành viên cần xem số dư (để trống để xem của bạn)")
    async def balance(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        user_data = await async_get_economy_user(str(ctx.guild.id), str(target.id))
        
        sym = eco_s.get("currency_symbol", "🪙")
        wallet = user_data.get("wallet", 0)
        bank = user_data.get("bank", 0)
        streak = user_data.get("daily_streak", 0)
        
        embed = discord.Embed(
            title=tr(s, "economy.bal_title", user=target.display_name),
            color=config.COLOR_INFO,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name=f"💵 {tr(s, 'economy.wallet')}", value=f"**{wallet:,}** {sym}", inline=True)
        embed.add_field(name=f"🏦 {tr(s, 'economy.bank')}", value=f"**{bank:,}** {sym}", inline=True)
        embed.add_field(name=f"🔥 {tr(s, 'economy.streak')}", value=f"**{streak}** {tr(s, 'economy.days')}", inline=True)
        embed.add_field(name=f"💎 {tr(s, 'economy.total_net')}", value=f"**{(wallet + bank):,}** {sym}", inline=False)
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── deposit ───────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="deposit", aliases=["dep"], description="Nạp tiền từ Ví vào tài khoản Ngân hàng (Bank)")
    @app_commands.describe(amount="Số tiền cần nạp (hoặc gõ 'all' / 'max' để nạp toàn bộ ví)")
    async def deposit(self, ctx: commands.Context, amount: str):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        success, dep_amount, user_data, err = await async_deposit_money(str(ctx.guild.id), str(ctx.author.id), amount)
        if not success:
            if err == "invalid_amount":
                await ctx.send(tr(s, "economy.deposit_invalid_amount"), ephemeral=True)
            elif err == "wallet_empty":
                await ctx.send(tr(s, "economy.deposit_wallet_empty", sym=sym), ephemeral=True)
            elif err == "not_enough_wallet":
                try:
                    req_amt = int(amount)
                except Exception:
                    req_amt = 0
                await ctx.send(tr(s, "economy.deposit_not_enough_wallet", amount=req_amt, wallet=user_data.get("wallet", 0), sym=sym), ephemeral=True)
            return

        embed = discord.Embed(
            title=tr(s, "economy.deposit_success_title"),
            description=tr(s, "economy.deposit_success_desc", amount=dep_amount, sym=sym, wallet=user_data.get("wallet", 0), bank=user_data.get("bank", 0)),
            color=0x57F287,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── withdraw ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="withdraw", aliases=["with", "wd"], description="Rút tiền từ Ngân hàng (Bank) về Ví tiền mặt")
    @app_commands.describe(amount="Số tiền cần rút (hoặc gõ 'all' / 'max' để rút toàn bộ ngân hàng)")
    async def withdraw(self, ctx: commands.Context, amount: str):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        success, with_amount, user_data, err = await async_withdraw_money(str(ctx.guild.id), str(ctx.author.id), amount)
        if not success:
            if err == "invalid_amount":
                await ctx.send(tr(s, "economy.withdraw_invalid_amount"), ephemeral=True)
            elif err == "bank_empty":
                await ctx.send(tr(s, "economy.withdraw_bank_empty", sym=sym), ephemeral=True)
            elif err == "not_enough_bank":
                try:
                    req_amt = int(amount)
                except Exception:
                    req_amt = 0
                await ctx.send(tr(s, "economy.withdraw_not_enough_bank", amount=req_amt, bank=user_data.get("bank", 0), sym=sym), ephemeral=True)
            return

        embed = discord.Embed(
            title=tr(s, "economy.withdraw_success_title"),
            description=tr(s, "economy.withdraw_success_desc", amount=with_amount, sym=sym, wallet=user_data.get("wallet", 0), bank=user_data.get("bank", 0)),
            color=0x57F287,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── pay ───────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="pay", description="Chuyển tiền từ ví của bạn cho thành viên khác")
    @app_commands.describe(member="Thành viên nhận tiền", amount="Số tiền cần chuyển")
    async def pay(self, ctx: commands.Context, member: discord.Member, amount: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        if member.id == ctx.author.id or member.bot:
            await ctx.send(tr(s, "economy.pay_invalid_target"), ephemeral=True)
            return
        if amount <= 0:
            await ctx.send(tr(s, "economy.pay_invalid_amount"), ephemeral=True)
            return

        success = await async_transfer_money(str(ctx.guild.id), str(ctx.author.id), str(member.id), amount)
        if not success:
            await ctx.send(tr(s, "economy.pay_not_enough_money", sym=sym), ephemeral=True)
            return

        embed = discord.Embed(
            title=tr(s, "economy.pay_success_title"),
            description=tr(s, "economy.pay_success_desc", sender=ctx.author.mention, receiver=member.mention, amount=amount, sym=sym),
            color=0x57F287,
            timestamp=datetime.now(timezone.utc)
        )
        await ctx.send(embed=embed)

    # ─── rich / baltop ─────────────────────────────────────────────────────────
    @commands.hybrid_command(name="rich", aliases=["baltop", "topmoney", "ecotop"], description="Bảng xếp hạng đại gia tiền tệ trong server")
    async def rich(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        top_users = await async_get_top_economy(str(ctx.guild.id), limit=10)
        if not top_users:
            await ctx.send(tr(s, "economy.leaderboard_empty"))
            return

        desc = ""
        medals = ["🥇", "🥈", "🥉"]
        for idx, u in enumerate(top_users):
            rank = medals[idx] if idx < 3 else f"`#{idx+1:2}`"
            member = ctx.guild.get_member(int(u["user_id"]))
            name = member.display_name if member else f"User {u['user_id']}"
            total = u.get("total", u.get("wallet", 0) + u.get("bank", 0))
            desc += f"{rank} **{name}** — **{total:,}** {sym}\n"

        embed = discord.Embed(
            title=tr(s, "economy.leaderboard_title", server=ctx.guild.name),
            description=desc,
            color=0xFEE75C,
            timestamp=datetime.now(timezone.utc)
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    # ─── coinflip ──────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="coinflip", aliases=["cf"], description="Tung đồng xu cá cược (Ngửa/Sấp)")
    @app_commands.describe(choice="Lựa chọn của bạn (heads = Ngửa, tails = Sấp)", bet="Số tiền cược")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Ngửa (Heads) 🪙", value="heads"),
        app_commands.Choice(name="Sấp (Tails) 🪙", value="tails")
    ])
    async def coinflip(self, ctx: commands.Context, choice: str, bet: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        if bet <= 0:
            await ctx.send(tr(s, "economy.invalid_bet"), ephemeral=True)
            return

        user_data = await async_get_economy_user(str(ctx.guild.id), str(ctx.author.id))
        if user_data.get("wallet", 0) < bet:
            await ctx.send(tr(s, "economy.not_enough_money", sym=sym), ephemeral=True)
            return

        # Trừ tiền cược
        await async_modify_wallet(str(ctx.guild.id), str(ctx.author.id), -bet)

        result = random.choice(["heads", "tails"])
        res_name = tr(s, "economy.cf_heads") if result == "heads" else tr(s, "economy.cf_tails")
        is_win = (choice.lower() == result)

        if is_win:
            win_amount = bet * 2
            await async_modify_wallet(str(ctx.guild.id), str(ctx.author.id), win_amount)
            embed = discord.Embed(
                title=tr(s, "economy.cf_win_title"),
                description=tr(s, "economy.cf_win_desc", res=res_name, amount=bet, sym=sym),
                color=0x57F287,
                timestamp=datetime.now(timezone.utc)
            )
        else:
            embed = discord.Embed(
                title=tr(s, "economy.cf_lose_title"),
                description=tr(s, "economy.cf_lose_desc", res=res_name, amount=bet, sym=sym),
                color=0xED4245,
                timestamp=datetime.now(timezone.utc)
            )

        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── slots ─────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="slots", description="Quay hũ Slot Machine may mắn")
    @app_commands.describe(bet="Số tiền cược")
    async def slots(self, ctx: commands.Context, bet: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        if bet <= 0:
            await ctx.send(tr(s, "economy.invalid_bet"), ephemeral=True)
            return

        user_data = await async_get_economy_user(str(ctx.guild.id), str(ctx.author.id))
        if user_data.get("wallet", 0) < bet:
            await ctx.send(tr(s, "economy.not_enough_money", sym=sym), ephemeral=True)
            return

        # Trừ tiền cược
        await async_modify_wallet(str(ctx.guild.id), str(ctx.author.id), -bet)

        icons = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
        r1, r2, r3 = random.choice(icons), random.choice(icons), random.choice(icons)

        # Tính toán thưởng
        if r1 == r2 == r3:
            if r1 == "7️⃣":
                multiplier = 25
            elif r1 == "💎":
                multiplier = 10
            else:
                multiplier = 5
        elif r1 == r2 or r2 == r3 or r1 == r3:
            multiplier = 2
        else:
            multiplier = 0

        slot_display = f"🎰 **[ {r1} | {r2} | {r3} ]** 🎰"

        if multiplier > 0:
            payout = bet * multiplier
            profit = payout - bet
            await async_modify_wallet(str(ctx.guild.id), str(ctx.author.id), payout)
            embed = discord.Embed(
                title=tr(s, "economy.slots_win_title"),
                description=f"{slot_display}\n\n{tr(s, 'economy.slots_win_desc', mult=multiplier, amount=profit, sym=sym)}",
                color=0x57F287,
                timestamp=datetime.now(timezone.utc)
            )
        else:
            embed = discord.Embed(
                title=tr(s, "economy.slots_lose_title"),
                description=f"{slot_display}\n\n{tr(s, 'economy.slots_lose_desc', amount=bet, sym=sym)}",
                color=0xED4245,
                timestamp=datetime.now(timezone.utc)
            )

        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── blackjack ─────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="blackjack", aliases=["bj"], description="Đánh bài Xì dách với Bot bằng nút bấm tương tác")
    @app_commands.describe(bet="Số tiền cược")
    async def blackjack(self, ctx: commands.Context, bet: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        if bet <= 0:
            await ctx.send(tr(s, "economy.invalid_bet"), ephemeral=True)
            return

        user_data = await async_get_economy_user(str(ctx.guild.id), str(ctx.author.id))
        if user_data.get("wallet", 0) < bet:
            await ctx.send(tr(s, "economy.not_enough_money", sym=sym), ephemeral=True)
            return

        # Trừ tiền cược
        await async_modify_wallet(str(ctx.guild.id), str(ctx.author.id), -bet)

        view = BlackjackView(self, ctx, bet, s)
        
        # Check instant Blackjack 21 on deal
        pval = calc_hand(view.player_hand)
        dval = calc_hand(view.dealer_hand)
        
        if pval == 21 and dval == 21:
            await view.finish_game("tie")
            embed = view.build_embed(hide_dealer=False)
            view.message = await ctx.send(embed=embed, view=view)
            return
        elif pval == 21:
            await view.finish_game("blackjack")
            embed = view.build_embed(hide_dealer=False)
            view.message = await ctx.send(embed=embed, view=view)
            return

        embed = view.build_embed(hide_dealer=True)
        view.message = await ctx.send(embed=embed, view=view)

    # ─── shop ──────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="shop", description="Xem cửa hàng mua Role bằng tiền ảo của server")
    async def shop(self, ctx: commands.Context):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        items = await async_get_economy_shop(str(ctx.guild.id))
        if not items:
            await ctx.send(tr(s, "economy.shop_empty"))
            return

        desc = tr(s, "economy.shop_guide") + "\n\n"
        for it in items:
            role = ctx.guild.get_role(int(it["role_id"])) if it.get("role_id") else None
            role_mention = role.mention if role else f"`{tr(s, 'economy.role_not_found')}`"
            stock_str = f"({tr(s, 'economy.stock')}: {it['stock']})" if it["stock"] >= 0 else ""
            desc += f"`ID: {it['id']}` • **{it['name']}** ({role_mention}) — **{it['price']:,}** {sym} {stock_str}\n"

        desc += f"\n{tr(s, 'economy.shop_bank_hint')}"

        embed = discord.Embed(
            title=tr(s, "economy.shop_title", server=ctx.guild.name),
            description=desc,
            color=0x5865F2,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=tr(s, "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── buy ───────────────────────────────────────────────────────────────────
    @commands.hybrid_command(name="buy", description="Mua Role từ cửa hàng server bằng ID (Thanh toán qua Ngân hàng)")
    @app_commands.describe(item_id="ID của vật phẩm trong cửa hàng")
    async def buy(self, ctx: commands.Context, item_id: int):
        s = await async_get_guild_settings(str(ctx.guild.id))
        eco_s = await async_get_economy_settings(str(ctx.guild.id))
        sym = eco_s.get("currency_symbol", "🪙")

        success, role_id, info, price = await async_buy_shop_item(str(ctx.guild.id), str(ctx.author.id), item_id)
        if not success:
            if info == "item_not_found":
                await ctx.send(tr(s, "economy.item_not_found"), ephemeral=True)
            elif info == "out_of_stock":
                await ctx.send(tr(s, "economy.out_of_stock"), ephemeral=True)
            elif info in ("not_enough_bank", "not_enough_money"):
                user_data = await async_get_economy_user(str(ctx.guild.id), str(ctx.author.id))
                await ctx.send(tr(s, "economy.buy_need_bank", price=price, bank=user_data.get("bank", 0), sym=sym), ephemeral=True)
            return

        # Cấp role cho user
        if role_id:
            role = ctx.guild.get_role(int(role_id))
            if role:
                try:
                    await ctx.author.add_roles(role, reason="Mua role từ Economy Shop")
                except Exception as e:
                    await ctx.send(tr(s, "economy.role_assign_error", role=role.name), ephemeral=True)
                    return

        await ctx.send(tr(s, "economy.buy_success", item=info, sym=sym))


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
