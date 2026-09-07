"""
Cog: Verify Gate (V2)
=====================
Xác thực thành viên trước khi vào server (chế độ hard gate).

- Verify Mode: **button** — thành viên bấm nút "Tôi đã đọc nội quy & Xác thực"
  (dùng emoji `zb_verified`) để nhận vai trò xác thực.
- Gate Level: **hard** — thành viên mới chỉ thấy kênh `#xac-thuc` (kênh verify).
  Bot lưu snapshot overrides (cho vai trò pending) để khôi phục nguyên trạng khi tắt.
- Anti-Raid / Anti-Nuke được tích hợp trong cog `automod.py`, không nằm ở đây.

Yêu cầu quyền: `manage_roles` (gán vai trò), `manage_channels` (gate hard).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import logging
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from database import (
    async_is_module_enabled,
    async_get_verify_settings,
    async_upsert_verify_settings,
)
from i18n import tr

try:
    from emojis import e, partial, embed_title
except (ImportError, ModuleNotFoundError):
    from bot.emojis import e, partial, embed_title

log = logging.getLogger("BotV2.Verify")

# ─── Custom ID cho button verify (bền vững qua restart) ─────────────────────────
VERIFY_BUTTON_ID = "zb_verify_button"


# ═════════════════════════════════════════════════════════════════════════════
# ─── Helpers serialization PermissionOverwrite (cho snapshot overrides) ──────
# ═════════════════════════════════════════════════════════════════════════════
def _serialize_overwrite(overwrite: Optional[discord.PermissionOverwrite]) -> Optional[dict]:
    """
    Chuyển PermissionOverwrite thành dict {perm_name: bool} chỉ chứa quyền được set.
    Các quyền có value None (không set) được bỏ qua.
    """
    if overwrite is None:
        return None
    data = {}
    for key, value in overwrite.items():
        if value is not None:
            # bool(False) = False (deny); bool(True) = True (allow)
            data[str(key)] = bool(value)
    return data or None


def _deserialize_overwrite(data: Optional[dict]) -> Optional[discord.PermissionOverwrite]:
    if not data:
        return None
    return discord.PermissionOverwrite(**data)


def _load_saved_overrides(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ═════════════════════════════════════════════════════════════════════════════
# ─── Verify Button (View) ─────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════
class VerifyView(discord.ui.View):
    """View chứa một nút xác thực duy nhất."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Tôi đã đọc nội quy & Xác thực",
        style=discord.ButtonStyle.success,
        emoji=partial("zb_verified", "✅"),
        custom_id=VERIFY_BUTTON_ID,
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("❌ Lệnh này chỉ dùng trong server.", ephemeral=True)
            return

        try:
            s = await async_get_verify_settings(str(guild.id))
        except Exception as exc:  # bảo hiểm nếu DB lỗi
            log.error(f"[Verify] DB error in button: {exc}")
            await interaction.response.send_message("❌ Đã xảy ra lỗi khi đọc cấu hình.", ephemeral=True)
            return

        if not int(s.get("enabled", 0)):
            await interaction.response.send_message(
                "❌ Tính năng xác thực đã bị tắt.", ephemeral=True
            )
            return

        member = interaction.user
        if member.bot:
            await interaction.response.send_message("🤖 Bạn là bot, không cần xác thực.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        added = []
        removed = []

        # 1. Gán vai trò verified
        verified_role_id = s.get("verified_role_id")
        if verified_role_id:
            role = guild.get_role(int(verified_role_id))
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Verified via button ({interaction.user})")
                    added.append(role.name)
                except discord.Forbidden:
                    log.warning(f"[Verify] Missing perms to add role {role.name} in {guild.name}")
                except Exception as exc:
                    log.warning(f"[Verify] Failed to add role {role.name}: {exc}")

        # 2. Gỡ vai trò pending
        pending_role_id = s.get("pending_role_id")
        if pending_role_id:
            role = guild.get_role(int(pending_role_id))
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Verified via button")
                    removed.append(role.name)
                except discord.Forbidden:
                    log.warning(f"[Verify] Missing perms to remove role {role.name}")
                except Exception as exc:
                    log.warning(f"[Verify] Failed to remove role {role.name}: {exc}")

        # 3. Nếu hard gate: dọn overwrite của member trên các kênh (nếu có dùng member-level).
        #    Với cơ chế pending-role, ai rời pending là được mở lại toàn quyền truyền thống.

        # 4. Log
        await _log_verify(interaction, s, added, removed)

        ok_emoji = e("zb_verified", "✅")
        await interaction.followup.send(
            f"{ok_emoji} Xác thực thành công, chúc mừng **{member.display_name}**!",
            ephemeral=True,
        )


async def _log_verify(interaction: discord.Interaction, s: dict, added: list, removed: list):
    """Gửi log xác thực tới kênh log nếu được cấu hình."""
    log_channel_id = s.get("log_channel_id")
    if not log_channel_id:
        return
    channel = interaction.guild.get_channel(int(log_channel_id))
    if not isinstance(channel, discord.TextChannel):
        return

    desc = f"**Người dùng:** {interaction.user.mention} (`{interaction.user.id}`)"
    if added:
        desc += f"\n**Đã thêm:** {', '.join(added)}"
    if removed:
        desc += f"\n**Đã gỡ:** {', '.join(removed)}"

    embed = discord.Embed(
        title=embed_title("zb_verified", "✅ Xác thực thành viên"),
        description=desc,
        color=discord.Color.success(),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"Guild: {interaction.guild.name}")
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        log.warning(f"[Verify] Missing perms to send log to {channel.name}")


# ═════════════════════════════════════════════════════════════════════════════
# ─── Cog Verify ───────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════
class Verify(commands.Cog, name="Verify"):
    """Xác thực thành viên trước khi vào server."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        if not await async_is_module_enabled(str(ctx.guild.id), "verify"):
            await ctx.send("🔒 Module Verify đang tắt.", ephemeral=True)
            return False
        return True

    # ─── Group /verify ───────────────────────────────────────────────────────
    @commands.hybrid_group(name="verify", description="Cấu hình Verify Gate (Xác thực thành viên)")
    @app_commands.default_permissions(manage_roles=True)
    async def verify_group(self, ctx: commands.Context):
        """Group lệnh cấu hình Verify."""
        if ctx.invoked_subcommand is None:
            await self._show_status(ctx)

    # ─── /verify status ──────────────────────────────────────────────────────
    @verify_group.command(name="status", description="Xem trạng thái Verify Gate")
    async def verify_status(self, ctx: commands.Context):
        await self._show_status(ctx)

    async def _show_status(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_verify_settings(guild_id)
        enabled = bool(int(s.get("enabled", 0)))
        hide = bool(int(s.get("hide_channels", 1)))

        ch = ctx.guild.get_channel(int(s["channel_id"])) if s.get("channel_id") else None
        vr = ctx.guild.get_role(int(s["verified_role_id"])) if s.get("verified_role_id") else None
        pr = ctx.guild.get_role(int(s["pending_role_id"])) if s.get("pending_role_id") else None

        total_overrides = len(_load_saved_overrides(s.get("saved_overrides", "[]")))

        status_emoji = e("zb_seen", "🟢") if enabled else e("zb_off", "🔴")
        embed = discord.Embed(
            title=embed_title("zb_verified", "🔐 Verify Gate"),
            color=discord.Color.success() if enabled else discord.Color.dark_grey(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Trạng thái",
            value=f"{status_emoji} {'**BẬT**' if enabled else '**TẮT**'} ({'hard gate' if hide else 'soft'})",
            inline=False,
        )
        embed.add_field(
            name="Kênh xác thực",
            value=ch.mention if ch else "`chưa đặt`",
            inline=True,
        )
        embed.add_field(
            name="Vai trò đã xác thực",
            value=vr.mention if vr else "`chưa đặt`",
            inline=True,
        )
        embed.add_field(
            name="Vai trò chờ",
            value=pr.mention if pr else "`chưa đặt`",
            inline=True,
        )
        embed.add_field(
            name="Kênh log",
            value=(
                ctx.guild.get_channel(int(s["log_channel_id"])).mention
                if s.get("log_channel_id")
                and isinstance(ctx.guild.get_channel(int(s["log_channel_id"])), discord.TextChannel)
                else "`chưa đặt`"
            ),
            inline=True,
        )
        embed.add_field(
            name="Chế độ ẩn kênh",
            value="🟢 Bật" if hide else "🔴 Tắt",
            inline=True,
        )
        embed.add_field(
            name="Snapshot overrides",
            value=f"{total_overrides} kênh",
            inline=True,
        )
        embed.set_footer(text=tr("vi", "common.requested_by", user=ctx.author.display_name), icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ─── /verify enable ──────────────────────────────────────────────────────
    @verify_group.command(name="enable", description="BẬT Verify Gate (hard gate — chỉ thấy kênh xác thực)")
    async def verify_enable(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_verify_settings(guild_id)

        if not s.get("channel_id"):
            await ctx.send("❌ Hãy đặt kênh xác thực trước: `/verify channel #kênh`", ephemeral=True)
            return

        # Tạo vai trò pending nếu chưa có
        pending_role = None
        if s.get("pending_role_id"):
            pending_role = ctx.guild.get_role(int(s["pending_role_id"]))
        if pending_role is None:
            pending_role = await self._ensure_pending_role(ctx)
            if pending_role is None:
                await ctx.send("❌ Không tạo được vai trò chờ — kiểm tra quyền `Quản lý vai trò`.", ephemeral=True)
                return
            await async_upsert_verify_settings(guild_id, pending_role_id=str(pending_role.id))

        # Áp hard gate: snapshot + set overwrite cho pending role trên mọi kênh
        ch = ctx.guild.get_channel(int(s["channel_id"]))
        if not isinstance(ch, discord.TextChannel):
            await ctx.send("❌ Kênh xác thực không hợp lệ.", ephemeral=True)
            return

        count, errors = await self._apply_hard_gate(ctx, pending_role, ch)

        await async_upsert_verify_settings(
            guild_id,
            enabled=1,
            hide_channels=1,
            saved_overrides=json.dumps(count, ensure_ascii=False),
        )

        if errors:
            await ctx.send(
                f"✅ Đã bật Verify Gate (hard). Đã thiết lập {len(count)} kênh; "
                f"⚠️ {errors} kênh bỏ qua (thiếu quyền `Quản lý kênh`).",
                ephemeral=True,
            )
        else:
            await ctx.send(
                f"✅ Đã bật Verify Gate (hard). Thành viên mới sẽ chỉ thấy {ch.mention}.",
                ephemeral=True,
            )

    # ─── /verify disable ─────────────────────────────────────────────────────
    @verify_group.command(name="disable", description="TẮT Verify Gate và khôi phục overrides")
    async def verify_disable(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_verify_settings(guild_id)

        restore_count = await self._restore_gate(ctx)

        # Gỡ vai trò pending khỏi mọi thành viên
        removed_members = 0
        pending_role_id = s.get("pending_role_id")
        if pending_role_id:
            role = ctx.guild.get_role(int(pending_role_id))
            if role:
                members = [m for m in ctx.guild.members if role in m.roles]
                for m in members:
                    try:
                        await m.remove_roles(role, reason="Verify disabled")
                        removed_members += 1
                    except discord.Forbidden:
                        break
                    except Exception:
                        break

        await async_upsert_verify_settings(
            guild_id, enabled=0, hide_channels=0, saved_overrides="[]"
        )

        await ctx.send(
            f"🔴 Đã tắt Verify Gate. Đã khôi phục {restore_count} kênh, gỡ vai trò chờ khỏi {removed_members} thành viên.",
            ephemeral=True,
        )

    # ─── /verify channel ─────────────────────────────────────────────────────
    @verify_group.command(name="channel", description="Đặt kênh xác thực (nơi gửi nút bấm)")
    @app_commands.describe(channel="Kênh dùng làm kênh xác thực")
    async def verify_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        guild_id = str(ctx.guild.id)
        cid = str(channel.id) if channel else None
        await async_upsert_verify_settings(guild_id, channel_id=cid)
        if channel:
            await ctx.send(f"✅ Đã đặt kênh xác thực: {channel.mention}", ephemeral=True)
        else:
            await ctx.send("❌ Hãy chỉ định kênh.", ephemeral=True)

    # ─── /verify role ────────────────────────────────────────────────────────
    @verify_group.command(name="role", description="Đặt vai trò thành viên đã xác thực")
    @app_commands.describe(role="Vai trò được gán sau khi bấm nút xác thực")
    async def verify_role(self, ctx: commands.Context, role: discord.Role = None):
        guild_id = str(ctx.guild.id)
        rid = str(role.id) if role else None
        await async_upsert_verify_settings(guild_id, verified_role_id=rid)
        if role:
            await ctx.send(f"✅ Đã đặt vai trò xác thực: {role.mention}", ephemeral=True)
        else:
            await ctx.send("❌ Hãy chỉ định vai trò.", ephemeral=True)

    # ─── /verify pending ─────────────────────────────────────────────────────
    @verify_group.command(name="pending", description="Đặt vai trò chờ (pending) cho thành viên mới")
    @app_commands.describe(role="Vai trò đại diện cho thành viên chưa xác thực")
    async def verify_pending(self, ctx: commands.Context, role: discord.Role = None):
        guild_id = str(ctx.guild.id)
        rid = str(role.id) if role else None
        await async_upsert_verify_settings(guild_id, pending_role_id=rid)
        if role:
            await ctx.send(f"✅ Đã đặt vai trò chờ: {role.mention}", ephemeral=True)
        else:
            await ctx.send("❌ Hãy chỉ định vai trò.", ephemeral=True)

    # ─── /verify hide ────────────────────────────────────────────────────────
    @verify_group.command(name="hide", description="Bật/tắt chế độ ẩn kênh (hard gate)")
    @app_commands.rename(state="che_do")
    @app_commands.describe(state="Bật (hard — chỉ thấy kênh xác thực) hoặc Tắt (soft)")
    async def verify_hide(self, ctx: commands.Context, state: str):
        val = state.strip().lower()
        hide = val in ("on", "bật", "true", "1", "yes")
        await async_upsert_verify_settings(str(ctx.guild.id), hide_channels=1 if hide else 0)
        if hide:
            await ctx.send(
                "✅ Đã bật chế độ **hard gate** — thành viên mới chỉ thấy kênh xác thực.",
                ephemeral=True,
            )
        else:
            await ctx.send(
                "🔴 Đã tắt chế độ ẩn kênh (soft mode).",
                ephemeral=True,
            )

    # ─── /verify text ────────────────────────────────────────────────────────
    @verify_group.command(name="text", description="Đặt nội dung thông điệp xác thực")
    @app_commands.describe(content="Nội dung (hỗ trợ {server})")
    async def verify_text(self, ctx: commands.Context, content: str):
        await async_upsert_verify_settings(str(ctx.guild.id), verify_text=content)
        await ctx.send("✅ Đã đặt nội dung xác thực.", ephemeral=True)

    # ─── /verify button ──────────────────────────────────────────────────────
    @verify_group.command(name="button", description="Đặt nhãn nút xác thực")
    @app_commands.describe(label="Chữ hiển thị trên nút")
    async def verify_button(self, ctx: commands.Context, label: str):
        await async_upsert_verify_settings(str(ctx.guild.id), button_label=label)
        await ctx.send(f"✅ Đã đặt nhãn nút: **{label}**", ephemeral=True)

    # ─── /verify panel ───────────────────────────────────────────────────────
    @verify_group.command(name="panel", description="Gửi bảng xác thực (nút bấm) vào kênh xác thực")
    async def verify_panel(self, ctx: commands.Context):
        guild_id = str(ctx.guild.id)
        s = await async_get_verify_settings(guild_id)

        if not s.get("channel_id"):
            await ctx.send("❌ Hãy đặt kênh xác thực trước.", ephemeral=True)
            return

        ch = ctx.guild.get_channel(int(s["channel_id"]))
        if not isinstance(ch, discord.TextChannel):
            await ctx.send("❌ Kênh xác thực không hợp lệ.", ephemeral=True)
            return

        text = (s.get("verify_text") or "Chào mừng đến với **{server}**! Bấm nút bên dưới để xác thực.").replace(
            "{server}", ctx.guild.name
        )
        label = s.get("button_label") or "Tôi đã đọc nội quy & Xác thực"

        embed = discord.Embed(
            title=embed_title("zb_verified", "🔐 Xác thực thành viên"),
            description=text,
            color=discord.Color.brand_green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"{ctx.guild.name} • {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

        # Nút xác thực dùng nhãn động từ cấu hình
        view = VerifyView(self.bot)
        view.children[0].label = label

        try:
            await ch.send(embed=embed, view=view)
            await ctx.send(f"✅ Đã gửi bảng xác thực vào {ch.mention}.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ Bot thiếu quyền gửi tin trong kênh xác thực.", ephemeral=True)
        except Exception as exc:
            log.error(f"[Verify] panel send error: {exc}")
            await ctx.send("❌ Không gửi được bảng xác thực.", ephemeral=True)

    # ─── Listener: on_member_join (hard gate) ───────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild_id = str(member.guild.id)
        try:
            s = await async_get_verify_settings(guild_id)
        except Exception as exc:
            log.error(f"[Verify] on_member_join DB error: {exc}")
            return

        if not int(s.get("enabled", 0)):
            return
        if not int(s.get("hide_channels", 1)):
            return

        # Thành viên đã có vai trò xác thực → bỏ qua
        verified_role_id = s.get("verified_role_id")
        if verified_role_id:
            vr = member.guild.get_role(int(verified_role_id))
            if vr and vr in member.roles:
                return

        pending_role_id = s.get("pending_role_id")
        if pending_role_id:
            pr = member.guild.get_role(int(pending_role_id))
            if pr:
                try:
                    await member.add_roles(pr, reason="Verify gate: member joined")
                except discord.Forbidden:
                    log.warning(f"[Verify] Missing perms to add pending role to {member} in {member.guild.name}")
                except Exception as exc:
                    log.warning(f"[Verify] add pending role failed: {exc}")

    # ─── Hard gate helpers ───────────────────────────────────────────────────
    async def _ensure_pending_role(self, ctx: commands.Context) -> Optional[discord.Role]:
        """Tạo vai trò chờ (pending) nếu chưa tồn tại."""
        name = "Chưa xác thực"
        try:
            role = await ctx.guild.create_role(
                name=name,
                reason="Verify gate setup",
                colour=discord.Color.dark_grey(),
            )
            # Đặt vai trò ngay trên @everyone để tránh giẫm lên vai trò thường
            try:
                await role.edit(position=1, reason="Verify gate setup")
            except discord.Forbidden:
                pass
            return role
        except discord.Forbidden:
            log.warning(f"[Verify] Missing perms to create pending role in {ctx.guild.name}")
            return None
        except Exception as exc:
            log.warning(f"[Verify] create pending role failed: {exc}")
            return None

    async def _apply_hard_gate(self, ctx: commands.Context, pending_role: discord.Role, verify_channel: discord.TextChannel):
        """
        Snapshot overwrites hiện tại của pending role trên mọi kênh, sau đó:
        - Kênh verify: cho phép `view_channel`.
        - Các kênh khác: chặn `view_channel`.
        Trả về (list_snapshot, số kênh lỗi).
        """
        snapshots = []
        errors = 0
        guild = ctx.guild

        for channel in guild.channels:
            try:
                current = channel.overwrites_for(pending_role)
                snapshots.append({
                    "channel_id": str(channel.id),
                    "overwrite": _serialize_overwrite(current),
                })

                if channel.id == verify_channel.id:
                    await channel.set_permissions(
                        pending_role,
                        overwrite=discord.PermissionOverwrite(view_channel=True),
                        reason="Verify gate: allow verify channel",
                    )
                else:
                    await channel.set_permissions(
                        pending_role,
                        overwrite=discord.PermissionOverwrite(view_channel=False),
                        reason="Verify gate: hide non-verify channels",
                    )
            except discord.Forbidden:
                errors += 1
                log.warning(f"[Verify] Missing perms on channel {channel.name}")
            except Exception as exc:
                errors += 1
                log.warning(f"[Verify] gate error on {channel.name}: {exc}")

        return snapshots, errors

    async def _restore_gate(self, ctx: commands.Context) -> int:
        """
        Khôi phục overwrites từ snapshot đã lưu trong DB.
        Với các kênh trong snapshot: khôi phục lại overwrite gốc của pending role.
        Trả về số kênh đã khôi phục.
        """
        guild_id = str(ctx.guild.id)
        s = await async_get_verify_settings(guild_id)
        snapshots = _load_saved_overrides(s.get("saved_overrides", "[]"))

        # Xác định target: pending role nếu còn, ngược lại @everyone
        target = None
        if s.get("pending_role_id"):
            target = ctx.guild.get_role(int(s["pending_role_id"]))
        if target is None:
            target = ctx.guild.default_role

        restored = 0
        for entry in snapshots:
            try:
                channel = ctx.guild.get_channel(int(entry["channel_id"]))
                if channel is None:
                    continue
                original = _deserialize_overwrite(entry.get("overwrite"))
                await channel.set_permissions(
                    target,
                    overwrite=original,
                    reason="Verify gate: restore overrides",
                )
                restored += 1
            except discord.Forbidden:
                log.warning(f"[Verify] Missing perms to restore channel {entry.get('channel_id')}")
            except Exception as exc:
                log.warning(f"[Verify] restore error on {entry.get('channel_id')}: {exc}")

        return restored


async def setup(bot):
    await bot.add_cog(Verify(bot))
    # Đăng ký persistent view để nút xác thực vẫn hoạt động sau khi bot restart.
    bot.add_view(VerifyView(bot))
