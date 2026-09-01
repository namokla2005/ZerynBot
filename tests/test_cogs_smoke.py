"""
Smoke test: mọi cog trong bot/cogs phải load được lên một discord.py Bot giả
(không login Discord, không network). Phát hiện ngay: import lỗi, cú pháp sai,
setup() bị thiếu, lệnh slash khai báo sai.
"""
import os
import sys
import asyncio

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COGS_DIR = os.path.join(BASE_DIR, "bot", "cogs")


def test_all_cogs_load():
    import discord
    from discord.ext import commands, tasks

    # Chặn mọi @tasks.loop tự chạy (bot không login trong test)
    tasks.Loop.start = lambda self, *a, **k: None

    bot = commands.Bot(
        command_prefix="/", intents=discord.Intents.none(), help_command=None
    )

    async def load_all():
        failures = {}
        for f in sorted(os.listdir(COGS_DIR)):
            if f.endswith(".py") and not f.startswith("_"):
                ext = f"cogs.{f[:-3]}"
                try:
                    await bot.load_extension(ext)
                except Exception as e:  # noqa: BLE001 — muốn gom hết lỗi rồi báo 1 lần
                    failures[ext] = repr(e)
        return failures

    failures = asyncio.run(load_all())
    try:
        bot.tree.get_commands()  # đảm bảo tree parse được sau khi load
    finally:
        asyncio.run(bot.close()) if not bot.is_closed() else None
    assert not failures, f"Cogs load thất bại: {failures}"


def test_command_tree_count_reasonable():
    """Bảo vệ khỏi việc vô tình mất hẳn lệnh (vd: refactor làm 1 cog im lặng fail)."""
    import discord
    from discord.ext import commands, tasks

    tasks.Loop.start = lambda self, *a, **k: None
    bot = commands.Bot(
        command_prefix="/", intents=discord.Intents.none(), help_command=None
    )

    async def load_all():
        for f in sorted(os.listdir(COGS_DIR)):
            if f.endswith(".py") and not f.startswith("_"):
                await bot.load_extension(f"cogs.{f[:-3]}")

    asyncio.run(load_all())
    top_level = len(bot.tree.get_commands())
    if not bot.is_closed():
        asyncio.run(bot.close())
    # Kỳ vọng hiện tại: 85; chỉ yêu cầu không sụt đột ngột
    assert top_level >= 80, f"Chỉ còn {top_level} lệnh top-level — có cog im lặng fail?"
