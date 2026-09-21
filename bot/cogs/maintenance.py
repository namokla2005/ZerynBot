"""
Cog: Maintenance (V2)
=====================
Task ngầm dọn dẹp dữ liệu cũ (auto-prune) chạy mỗi 24 giờ.

Chỉ dọn các bảng tích luỹ theo thời gian (chính xác theo hiện trạng):
- `guild_stats`       → > 60 ngày
- `automod_warnings`  → > 2 ngày (cảnh cáo chỉ có nghĩa trong 24h)
- `fun_interactions`  → > 60 ngày
- `reminders`         → > 30 ngày
- `music_song_cache`  → > 7 ngày (tự động dọn dẹp cache bài hát)

KHÔNG đụng `user_levels` / `economy_users` (dữ liệu member phải giữ nguyên).
Dùng bảng `maintenance_jobs.job_key=='auto_prune'` để chống chạy lặp khi bot
restart nhiều lần trong cùng ngày.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from discord.ext import commands, tasks

from database import (
    async_get_maintenance_job,
    async_prune_old_data,
    async_set_maintenance_job,
    async_vacuum_db,
    async_wal_checkpoint,
)

logger = logging.getLogger("BotV2.Maintenance")


class Maintenance(commands.Cog):
    """Dọn dẹp dữ liệu cũ định kỳ để giữ database gọn."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_prune_task.start()

    def cog_unload(self):
        self.auto_prune_task.cancel()

    def _prune_temp_files(self) -> int:
        """Dọn dẹp các file rác tạm (.tmp, temp_*) cũ hơn 24h trong thư mục data/ (an toàn trước file lock)."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_dir = os.path.join(base_dir, "data")
        if not os.path.isdir(data_dir):
            return 0
        cleaned = 0
        cutoff = time.time() - 86400  # Cũ hơn 24 giờ
        try:
            for fname in os.listdir(data_dir):
                if fname.endswith(".tmp") or fname.startswith("temp_"):
                    fpath = os.path.join(data_dir, fname)
                    if os.path.isfile(fpath):
                        try:
                            if os.path.getmtime(fpath) < cutoff:
                                os.remove(fpath)
                                cleaned += 1
                        except OSError:
                            pass
        except OSError:
            pass
        return cleaned

    @tasks.loop(seconds=3600)  # kiểm tra mỗi giờ, chỉ prune khi đủ 24h
    async def auto_prune_task(self):
        try:
            last_run = await async_get_maintenance_job("auto_prune")
            now = time.time()
            # Nếu mới prune trong 24h qua → bỏ qua (chống restart lặp trong ngày)
            if last_run and (now - last_run) < 86400:
                return

            deleted = await async_prune_old_data(song_cache_days=7)
            temp_cleaned = self._prune_temp_files()
            if temp_cleaned:
                deleted["temp_files"] = temp_cleaned
            await async_set_maintenance_job("auto_prune", now)

            total = sum(deleted.values())
            if total:
                logger.info(
                    "[Auto-Prune] Đã dọn %d dòng: %s", total,
                    ", ".join(f"{k}={v}" for k, v in deleted.items()),
                )
                await async_wal_checkpoint()
                await async_vacuum_db()
        except Exception:
            logger.exception("[Auto-Prune] Lỗi khi dọn dữ liệu cũ")

    @auto_prune_task.before_loop
    async def before_auto_prune_task(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Maintenance(bot))
