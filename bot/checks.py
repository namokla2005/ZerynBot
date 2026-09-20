import discord
from discord.ext import commands
from discord import app_commands
import database as db
import json


# ─── Helpers dual-mode (Context ↔ Interaction) ───────────────────────────────
# Lệnh con của hybrid_group được discord.py gọi check bằng `Interaction` trên
# đường slash, nhưng bằng `commands.Context` trên đường prefix. Mọi check dùng
# chung phải đọc dữ liệu qua các helper dưới đây để không vỡ ở một trong 2 đường.
def _get_guild(target):
    """Trả về guild của Context hoặc Interaction (None nếu là DM)."""
    return getattr(target, "guild", None)


def _get_member(target):
    """Trả về Member/User đã gọi lệnh, cho cả Context (`author`) và Interaction (`user`)."""
    member = getattr(target, "author", None)
    if member is None:
        member = getattr(target, "user", None)
    return member


def _fail(target, message: str):
    """Raise đúng loại CheckFailure theo loại target.

    - `commands.Context` (prefix + "baton" của hybrid trên đường slash) →
      `commands.CheckFailure`: hybrid.py bắt `CommandError` rồi dispatch vào
      `on_command_error`, nơi ta gửi thông báo cho người dùng.
    - `discord.Interaction` (check đăng ký bằng `@app_commands.check`) →
      `app_commands.CheckFailure`: chỉ loại này mới được tree.on_error xử lý;
      ném sai loại sẽ thành lỗi 500 "interaction failed".
    """
    # Duck-typing: `commands.Context` luôn có `.author`, `discord.Interaction`
    # không có (chỉ có `.user`) — nhờ vậy hàm vẫn đúng với Context giả trong test.
    if isinstance(target, commands.Context) or getattr(target, "author", None) is not None:
        raise commands.CheckFailure(message)
    raise app_commands.CheckFailure(message)


def _is_bot_admin_member(member: discord.Member) -> bool:
    """Owner server hoặc có quyền Administrator → luôn được phép."""
    guild = getattr(member, "guild", None)
    if guild is not None and member.id == guild.owner_id:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and perms.administrator)

async def check_bot_admin(ctx) -> bool:
    """Kiểm tra quyền điều khiển Bot theo cấu hình Whitelist Role (Dashboard).

    P0 FIX (dual-mode): discord.py gọi check này bằng 2 loại target khác nhau:
      - Prefix (@Bot <lệnh>) và bản "baton" của hybrid → `commands.Context`
      - Check đăng ký qua `@app_commands.check` (đường slash) → `discord.Interaction`

    Vì vậy mọi check ở đây phải đọc guild/member qua helper thay vì `ctx.author`
    (nếu không sẽ AttributeError khi được gọi bằng Interaction).
    """
    guild = _get_guild(ctx)
    member = _get_member(ctx)
    if guild is None or member is None:
        return False

    if _is_bot_admin_member(member):
        return True

    settings = await db.async_get_guild_settings(str(guild.id))
    admin_roles_str = settings.get("bot_admin_roles", "[]")

    try:
        admin_roles = json.loads(admin_roles_str)
    except Exception:
        admin_roles = []

    if admin_roles:
        # Chuẩn hoá về str cả 2 phía: dashboard có thể lưu id dạng số (JSON int)
        # trong khi role id từ discord.py luôn là int → nếu so trực tiếp sẽ không
        # bao giờ khớp và whitelist "im lặng" vô hiệu.
        allowed_roles = {str(r) for r in admin_roles}
        member_role_ids = {str(r.id) for r in getattr(member, "roles", [])}
        if allowed_roles & member_role_ids:
            return True
        _fail(ctx, "❌ Bạn không có Role được cấp phép (Bot Admin) để cấu hình Bot!")

    # Fallback to Manage Server if no whitelist is configured
    perms = getattr(member, "guild_permissions", None)
    if perms and perms.manage_guild:
        return True

    _fail(ctx, "❌ Bạn không có quyền Manage Server để cấu hình Bot!")


async def _check_permissions(target, **perms) -> bool:
    """Bản sao dual-mode của `commands.has_permissions` cho lệnh con hybrid.

    `commands.has_permissions` thực ra đã an toàn cho cả 2 đường (nó dùng
    `Context.permissions` / `Interaction.permissions`), nhưng ở đây thêm bản này
    để các cog có chỗ gom check chung và để test kiểm tra được tập quyền yêu cầu.
    """
    guild = _get_guild(target)
    member = _get_member(target)
    if guild is None or member is None:
        return False

    if isinstance(member, discord.Member):
        permissions = member.guild_permissions
    else:
        permissions = getattr(target, "permissions", discord.Permissions.none())

    missing = [name for name, value in perms.items() if value and not getattr(permissions, name, False)]
    if missing:
        pretty = ", ".join(name.replace("_", " ") for name in missing)
        _fail(target, f"❌ Bạn thiếu quyền: **{pretty}**")
    return True


async def check_administrator(target) -> bool:
    """Yêu cầu quyền Administrator."""
    return await _check_permissions(target, administrator=True)


async def check_manage_guild(target) -> bool:
    """Yêu cầu quyền Manage Server."""
    return await _check_permissions(target, manage_guild=True)


async def check_manage_roles(target) -> bool:
    """Yêu cầu quyền Manage Roles."""
    return await _check_permissions(target, manage_roles=True)


# ─── Decorator dual-mode (P0) ────────────────────────────────────────────────
# Lý do tồn tại: `discord/ext/commands/core.py::Command.can_run` CHỈ chạy
# `self.checks` của chính lệnh đó — nó KHÔNG duyệt check của group cha. Nên
# `@commands.has_permissions(...)` đặt trên `@commands.hybrid_group` KHÔNG hề
# bảo vệ các lệnh con (`xp add`, `giveaway start`, `verify enable`, ...).
#
# Hybrid còn tách check thành 2 danh sách chạy ở 2 đường khác nhau:
#   * `__commands_checks__`            → chạy với `Context`  (prefix + baton slash)
#   * `__discord_app_commands_checks__` → chạy với `Interaction` (slash)
# `dual_check()` gắn cả hai để lệnh con bị chặn trên mọi đường gọi.


def dual_check(predicate):
    """Gắn một predicate vào CẢ đường prefix lẫn đường slash."""

    def decorator(func):
        func = commands.check(predicate)(func)
        func = app_commands.check(predicate)(func)
        return func

    return decorator


def is_bot_admin():
    """Owner / Administrator / role trong `bot_admin_roles` / Manage Server (dual-mode)."""
    return dual_check(check_bot_admin)


def admin_only():
    """Gắn cho lệnh con cần quyền Administrator (dual-mode)."""
    return dual_check(check_administrator)


def manage_guild_only():
    """Gắn cho lệnh con cần quyền Manage Server (dual-mode)."""
    return dual_check(check_manage_guild)


def manage_roles_only():
    """Gắn cho lệnh con cần quyền Manage Roles (dual-mode)."""
    return dual_check(check_manage_roles)
