import discord
from discord.ext import commands
import database as db
import json

async def check_bot_admin(ctx: commands.Context) -> bool:
    """Kiểm tra quyền điều khiển Bot theo cấu hình Whitelist Role (Dashboard)"""
    if ctx.guild is None:
        return False
        
    if ctx.author.id == ctx.guild.owner_id:
        return True
        
    if ctx.author.guild_permissions.administrator:
        return True
        
    settings = db.get_guild_settings(str(ctx.guild.id))
    admin_roles_str = settings.get("bot_admin_roles", "[]")
    
    try:
        admin_roles = json.loads(admin_roles_str)
    except:
        admin_roles = []
        
    if admin_roles:
        member_role_ids = [str(r.id) for r in ctx.author.roles]
        has_role = any(r_id in admin_roles for r_id in member_role_ids)
        if has_role:
            return True
        raise commands.CheckFailure("❌ Bạn không có Role được cấp phép (Bot Admin) để cấu hình Bot!")
        
    # Fallback to Manage Server if no whitelist is configured
    if ctx.author.guild_permissions.manage_guild:
        return True
        
    raise commands.CheckFailure("❌ Bạn không có quyền Manage Server để cấu hình Bot!")

def is_bot_admin():
    return commands.check(check_bot_admin)
