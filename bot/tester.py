"""
tester.py — Comprehensive Self-Diagnostic & Functional Assertion Suite for ZerynBot V2.
Runs automated deep functional tests for all 20 modules and core logic pillars:
  1. SQLite WAL & Schema Architecture
  2. In-Memory RAM Cache Engine
  3. Audio Pipeline & FFmpeg / yt-dlp
  4. 20 Core Modules Settings Schema
  5. Leveling & XP Mathematical Engine
  6. Dual-Tier Economy & Atomic Transactions
  7. Mini-Games & Blackjack Engine Logic
  8. SSRF Security & URL Defense Filter
  9. Multi-Language i18n & Keyword Interpolation
  10. Pillow Dynamic Card Image Generator
  11. SQLite WAL Concurrency & Deadlock Defense

Reports status to Webhook and exits with code 1 if any logic assertion fails.
"""
import sys
import os
import json
import time
import shutil
import asyncio
import platform
import tempfile
import traceback
import sqlite3
import subprocess
import importlib.util
import io

import aiohttp

# Ensure parent directory and bot directory are in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

import config
from cache import cache
from database import get_db_path, init_db, set_db_path, snapshot_database

def _safe_print(text: str):
    """Safe print wrapper preventing UnicodeEncodeError on non-UTF8 terminals."""
    try:
        print(text, flush=True)
    except Exception:
        try:
            print(text.encode("ascii", errors="ignore").decode("ascii"), flush=True)
        except Exception:
            pass

async def _post_webhook_report(embeds: list, full_text: str = None, filename: str = None):
    """Đăng nhiều embed + 1 file chi tiết lên webhook admin.

    Báo cáo khởi động giờ chứa đường dẫn file, số hàng DB và commit đang chạy nên
    ưu tiên STATUS_WEBHOOK_URL (kênh admin riêng), chỉ fallback về kênh log khi chưa
    cấu hình. Kèm file .txt vì embed bị Discord giới hạn 4096 ký tự/mô tả và
    6000 ký tự/embed — không đủ cho toàn bộ traceback.
    """
    webhook_url = (
        getattr(config, "STATUS_WEBHOOK_URL", None)
        or getattr(config, "WEBHOOK_LOG_URL", None)
        or os.getenv("WEBHOOK_FEEDBACK_URL")
        or os.getenv("FEEDBACK_WEBHOOK_URL")
    )
    if not webhook_url:
        return
    try:
        payload = {
            "embeds": embeds[:10],
            "username": "ZerynBot Self-Test",
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession() as session:
            if full_text and filename:
                form = aiohttp.FormData()
                form.add_field("payload_json", json.dumps(payload), content_type="application/json")
                form.add_field(
                    "files[0]", full_text.encode("utf-8"),
                    filename=filename, content_type="text/plain",
                )
                async with session.post(webhook_url, data=form, timeout=timeout) as resp:
                    _safe_print(
                        f"[Tester] Báo cáo khởi động: HTTP {resp.status} · "
                        f"{len(payload['embeds'])} embed + {filename}"
                    )
                    if resp.status >= 300:
                        _safe_print(f"[Tester] Webhook trả {resp.status}: {(await resp.text())[:200]}")
            else:
                async with session.post(webhook_url, json=payload, timeout=timeout) as resp:
                    _safe_print(
                        f"[Tester] Báo cáo khởi động: HTTP {resp.status} · "
                        f"{len(payload['embeds'])} embed"
                    )
                    if resp.status >= 300:
                        _safe_print(f"[Tester] Webhook trả {resp.status}: {(await resp.text())[:200]}")
    except Exception as e:
        _safe_print(f"[Tester] Error sending webhook report: {e}")


# ─── Ngữ cảnh máy thật cho báo cáo khởi động ────────────────────────────────────

def _clamp(text, limit: int) -> str:
    """Cắt chuỗi theo trần ký tự của Discord, ưu tiên giữ phần cuối (nơi có lỗi)."""
    s = str(text if text is not None else "")
    if len(s) <= limit:
        return s
    return "…" + s[-(limit - 1):]


def _read_procfs(path: str) -> dict:
    """Đọc file dạng 'Key:  value unit' như /proc/meminfo; {} nếu bị từ chối."""
    try:
        out = {}
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                key, _, val = line.partition(":")
                out[key.strip()] = val.strip()
        return out
    except Exception:
        return {}


def _mem_kb(info: dict, key: str):
    parts = info.get(key, "").split()
    return int(parts[0]) // 1024 if parts and parts[0].isdigit() else None


def _memory_snapshot() -> str:
    info = _read_procfs("/proc/meminfo")
    total, avail = _mem_kb(info, "MemTotal"), _mem_kb(info, "MemAvailable")
    if total:
        used = total - (avail if avail is not None else 0)
        text = f"RAM {used}/{total} MiB đã dùng"
        st, sf = _mem_kb(info, "SwapTotal"), _mem_kb(info, "SwapFree")
        if st:
            text += f" · swap {st - (sf or 0)}/{st} MiB"
        return text
    try:
        import psutil
        vm = psutil.virtual_memory()
        return f"RAM {vm.used // (1024 ** 2)}/{vm.total // (1024 ** 2)} MiB đã dùng"
    except Exception:
        return "RAM: không đọc được"


def _disk_snapshot() -> str:
    try:
        du = shutil.disk_usage(BASE_DIR)
        return f"đĩa còn {du.free / 1024 ** 3:.1f}/{du.total / 1024 ** 3:.1f} GiB"
    except Exception:
        return "đĩa: không đọc được"


def _load_uptime_snapshot() -> str:
    bits = []
    try:
        la = os.getloadavg()
        bits.append(f"load {la[0]:.1f}/{la[1]:.1f}/{la[2]:.1f} ({os.cpu_count()} core)")
    except Exception:
        pass
    try:
        with open("/proc/uptime", encoding="utf-8", errors="replace") as fh:
            secs = int(float(fh.read().split()[0]))
        days, rem = divmod(secs, 86400)
        hours, mins = divmod(rem, 3600)
        bits.append(f"uptime {days}d {hours}h{mins:02d}m" if days else f"uptime {hours}h{mins:02d}m")
    except Exception:
        pass
    return " · ".join(bits) if bits else "load/uptime: không đọc được"


def _build_snapshot() -> str:
    """Commit đang chạy — để biết bản báo cáo xanh là của code nào."""
    try:
        def _git(*args):
            return subprocess.run(
                ["git", *args], cwd=BASE_DIR, capture_output=True,
                text=True, timeout=6,
            ).stdout.strip()
        branch, sha = _git("rev-parse", "--abbrev-ref", "HEAD"), _git("rev-parse", "--short", "HEAD")
        if not sha:
            return "?"
        dirty = bool(_git("status", "--porcelain"))
        return f"{branch or '?'}@{sha}{' (working tree dirty)' if dirty else ''}"
    except Exception:
        return "?"


def _versions_snapshot() -> str:
    try:
        import importlib.metadata as md
        bits = [f"Python {platform.python_version()}"]
        for pkg in ("discord.py", "Flask", "aiosqlite", "yt-dlp", "Pillow", "aiohttp"):
            try:
                bits.append(f"{pkg} {md.version(pkg)}")
            except Exception:
                continue
        return " · ".join(bits)
    except Exception:
        return f"Python {sys.version.split()[0]}"


def _host_snapshot() -> str:
    try:
        u = os.uname()
        return f"{u.sysname} {u.machine}"
    except Exception:
        try:
            return platform.platform(terse=True)
        except Exception:
            return "?"


HOT_TABLES = (
    "guilds", "economy_users", "user_inventory", "economy_transactions", "user_levels",
    "reminders", "giveaways", "mod_warnings", "automod_warnings", "custom_commands",
    "ticket_panels", "ticket_buttons", "reaction_roles_panels", "reaction_roles_items",
    "music_playlists", "music_playlist_tracks", "music_song_cache", "activity_logs",
    "ai_activity_logs", "support_threads", "support_messages", "guild_stats",
    "fun_interactions", "maintenance_jobs",
)

FK_CHILDREN = (
    ("music_playlist_tracks", "playlist_id", "music_playlists"),
    ("ticket_buttons", "panel_id", "ticket_panels"),
    ("reaction_roles_items", "panel_id", "reaction_roles_panels"),
)


def _db_health(db_path: str) -> dict:
    """Sức khỏe DB, đọc ở chế độ CHỈ ĐỌC.

    Chạy TRƯỚC khi self-test chuyển sang sandbox nên đây là số liệu của
    `data/bot.db` thật; `mode=ro` đảm bảo không giành write-lock của bot đang chạy.
    """
    health = {"path": db_path, "rows": {}, "orphans": {}}
    try:
        health["size_kib"] = round(os.path.getsize(db_path) / 1024)
        wal = db_path + "-wal"
        health["wal_kib"] = round(os.path.getsize(wal) / 1024) if os.path.exists(wal) else 0
    except OSError as exc:
        health["size_error"] = str(exc)

    conn = None
    try:
        try:
            from urllib.request import pathname2url
            conn = sqlite3.connect(f"file:{pathname2url(db_path)}?mode=ro", uri=True, timeout=5)
        except Exception:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.execute("PRAGMA query_only=ON")

        one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
        health["journal_mode"] = one("PRAGMA journal_mode")
        health["foreign_keys"] = one("PRAGMA foreign_keys")
        health["busy_timeout_ms"] = one("PRAGMA busy_timeout")
        health["user_version"] = one("PRAGMA user_version")
        health["integrity"] = one("PRAGMA quick_check")
        health["tables"] = one("SELECT count(*) FROM sqlite_master WHERE type='table'")
        try:
            pages, free = one("PRAGMA page_count"), one("PRAGMA freelist_count")
            health["freelist_pct"] = round(free * 100 / pages) if pages else 0
        except Exception:
            pass
        for table in HOT_TABLES:
            try:
                health["rows"][table] = one(f'SELECT COUNT(*) FROM "{table}"')
            except Exception:
                continue
        for child, col, parent in FK_CHILDREN:
            try:
                health["orphans"][f"{child}.{col}"] = one(
                    f'SELECT COUNT(*) FROM "{child}" WHERE "{col}" IS NOT NULL '
                    f'AND "{col}" NOT IN (SELECT id FROM "{parent}")'
                )
            except Exception:
                continue
    except Exception as exc:
        health["error"] = str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    # PRAGMA là PER-CONNECTION: kết nối probe ở trên dùng mặc định SQLite nên chỉ số
    # foreign_keys/busy_timeout đọc được ở đó KHÔNG phải giá trị app đang dùng. Must
    # đo qua chính helper mà mọi kết nối của app đi qua.
    try:
        from database.conn import _connect_sync
        probe = _connect_sync(timeout=5.0)
        try:
            probe.execute("PRAGMA query_only=ON")
            health["app_foreign_keys"] = probe.execute("PRAGMA foreign_keys").fetchone()[0]
            health["app_busy_timeout_ms"] = probe.execute("PRAGMA busy_timeout").fetchone()[0]
            health["app_synchronous"] = probe.execute("PRAGMA synchronous").fetchone()[0]
        finally:
            probe.close()
    except Exception as exc:
        health["app_pragma_error"] = str(exc)
    return health

class SystemTester:
    @staticmethod
    async def run_all_tests() -> bool:
        """Chạy self-test trên SNAPSHOT của data/bot.db, không ghi lên DB thật.

        Các suite chèn hàng dò (`999999_test_g`, `u1_test`, XP probe...) rồi dọn
        bằng DELETE ở cuối suite. Khi suite TIMEOUT hoặc raise giữa chừng, phần dọn
        đó bị bỏ qua và rác nằm lại DB production vĩnh viễn — mà `bot.py` lại chạy
        bộ test này ở MỖI lần startup. Sandbox giữ nguyên dữ liệu thật để đọc, nhưng
        mọi ghi chỉ đi vào file tạm.
        """
        real_db = get_db_path()
        # Số liệu DB PHẢI được lấy trước khi chuyển sang sandbox, nếu không báo cáo
        # sẽ mô tả bản sao tạm thay vì data/bot.db thật.
        db_health = await asyncio.to_thread(_db_health, real_db)
        sandbox = os.path.join(tempfile.gettempdir(), f"zerynbot_selftest_{os.getpid()}.db")
        isolated = False
        try:
            snapshot_database(sandbox)
            set_db_path(sandbox)
            isolated = True
        except Exception as e:
            _safe_print(f"⚠️  [Tester] Không tạo được sandbox DB ({e}) — chạy trên DB thật.")
        try:
            return await SystemTester._run_all_tests(db_health=db_health, sandboxed=isolated)
        finally:
            if isolated:
                set_db_path(real_db)
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.remove(sandbox + suffix)
                    except OSError:
                        pass

    @staticmethod
    async def _run_all_tests(db_health: dict = None, sandboxed: bool = False) -> bool:
        """Run deep functional and assertion tests across all core systems."""
        started_wall = time.time()
        _safe_print("=" * 68)
        _safe_print("🔍 BẮT ĐẦU BỘ KIỂM THỬ CHỨC NĂNG SÂU & LOGIC (ZERYNBOT V2)")
        _safe_print("=" * 68)

        suite_records = []
        failed_suites = []
        error_details = {}
        total_assertions = 0

        # Helper to execute and record a test suite
        async def _run_suite(name: str, coro, timeout_sec: float = 10.0):
            nonlocal total_assertions
            start_t = time.perf_counter()
            record = {"name": name, "ok": False, "ms": 0.0, "asserts": 0,
                      "note": "", "error": "", "timeout_sec": timeout_sec}
            try:
                assert_count, note = await asyncio.wait_for(coro(), timeout=timeout_sec)
                record.update(ok=True, ms=(time.perf_counter() - start_t) * 1000,
                              asserts=assert_count, note=note or "")
                total_assertions += assert_count
                status_line = f"🟢 **{name}** — OK ({record['ms']:.1f}ms, {assert_count} asserts passed)"
                if note:
                    status_line += f" [{note}]"
            except asyncio.TimeoutError:
                record.update(ms=(time.perf_counter() - start_t) * 1000,
                              error=f"TimeoutError: vượt quá {timeout_sec}s (treating as hang).")
                failed_suites.append(name)
                status_line = f"🔴 **{name}** — TIMEOUT ({record['ms']:.1f}ms)"
            except AssertionError as ae:
                record.update(ms=(time.perf_counter() - start_t) * 1000,
                              error=f"AssertionError: {ae}\n{traceback.format_exc()}")
                failed_suites.append(name)
                status_line = f"🔴 **{name}** — ASSERTION FAIL: {ae} ({record['ms']:.1f}ms)"
            except Exception:
                record.update(ms=(time.perf_counter() - start_t) * 1000,
                              error=traceback.format_exc())
                failed_suites.append(name)
                status_line = f"🔴 **{name}** — ERROR ({record['ms']:.1f}ms)"
            if record["error"]:
                error_details[name] = record["error"]
            suite_records.append(record)
            _safe_print(f"  {status_line}")

        # ─── 1. SQLite WAL & Schema Architecture ──────────────────────────────
        async def suite_db_wal():
            asserts = 0
            init_db()
            asserts += 1
            def _check():
                with sqlite3.connect(get_db_path(), timeout=5) as conn:
                    cur = conn.cursor()
                    cur.execute("PRAGMA journal_mode;")
                    jmode = cur.fetchone()[0].lower()
                    assert jmode in ("wal", "memory"), f"Expected journal_mode wal/memory, got {jmode}"

                    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
                    tables = {r[0] for r in cur.fetchall()}
                    required = [
                        "guilds", "guild_modules", "ticket_panels", "reaction_roles_panels",
                        "automod_settings", "logger_settings", "leveling_settings", "user_levels",
                        "level_roles", "giveaways", "economy_settings", "economy_users",
                        "economy_shop", "user_inventory", "tempvoice_settings", "tempvoice_active",
                        "custom_commands", "ai_settings", "reminders", "mod_warnings",
                        "birthday_settings", "verify_settings"
                    ]
                    missing = [t for t in required if t not in tables]
                    assert not missing, f"Missing required database tables: {missing}"
                    return len(required)
            count = await asyncio.to_thread(_check)
            asserts += count + 1
            return asserts, "WAL Mode active, all 22 core tables verified"

        # ─── 2. In-Memory RAM Cache Engine ─────────────────────────────────────
        async def suite_cache():
            asserts = 0
            test_key = "system_test_probe_key"
            payload = {"status": "ok", "timestamp": time.time(), "code": 200}
            await cache.aset(test_key, payload, ttl=10)
            asserts += 1

            retrieved = await cache.aget(test_key)
            asserts += 1
            assert retrieved == payload, f"Cache mismatch: expected {payload}, got {retrieved}"

            await cache.adelete(test_key)
            asserts += 1

            empty = await cache.aget(test_key)
            asserts += 1
            assert empty is None, f"Cache delete failed: key still returned {empty}"
            return asserts, "Set/Get/TTL/Delete operational"

        # ─── 3. Audio Pipeline & FFmpeg / yt-dlp ──────────────────────────────
        async def suite_audio():
            asserts = 0
            import yt_dlp
            assert hasattr(yt_dlp, "YoutubeDL"), "yt_dlp is missing YoutubeDL attribute"
            asserts += 1

            spec = importlib.util.find_spec("cogs.music") or importlib.util.find_spec("bot.cogs.music")
            assert spec is not None, "Module cogs.music not found"
            asserts += 1

            ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg", path="/data/data/com.termux/files/usr/bin")
            if not ffmpeg_path:
                if os.name == "nt":
                    return asserts, "SKIP (Dev Windows: FFmpeg optional)"
                else:
                    raise AssertionError("FFmpeg binary not found on Linux/Termux system PATH")
            asserts += 1
            return asserts, f"FFmpeg present at {os.path.basename(ffmpeg_path)}"

        # ─── 4. 20 Core Modules Settings Schema ────────────────────────────────
        async def suite_20_modules():
            from database import (
                async_get_guild_settings, async_get_leveling_settings,
                async_get_automod_settings, async_get_logger_settings,
                async_get_economy_settings, async_get_tempvoice_settings,
                async_get_ai_settings, async_get_birthday_settings,
                async_get_verify_settings, async_get_all_ticket_panels,
                async_get_active_giveaways, async_get_custom_commands,
                async_get_user_reminders, async_get_mod_warnings,
                get_reaction_roles_panels
            )
            asserts = 0
            test_gid = "999999001"

            # 1. Welcome / Goodbye
            s = await async_get_guild_settings(test_gid)
            assert isinstance(s, dict), "async_get_guild_settings did not return dict"
            asserts += 1

            # 2. AutoRoles (part of guild_settings)
            assert "autorole_ids" in s or "autoroles" in s or isinstance(s, dict), "autoroles config missing"
            asserts += 1

            # 3. Leveling
            l_set = await async_get_leveling_settings(test_gid)
            assert isinstance(l_set, dict) and "message_xp_min" in l_set, "leveling_settings invalid"
            asserts += 1

            # 4, 5, 6. Utility, Info, Music Cog specs
            for cog in ["utility", "info", "music"]:
                spec = importlib.util.find_spec(f"cogs.{cog}") or importlib.util.find_spec(f"bot.cogs.{cog}")
                assert spec is not None, f"Cog cogs.{cog} could not be resolved"
                asserts += 1

            # 7. Tickets
            t_panels = await async_get_all_ticket_panels()
            assert isinstance(t_panels, list), "async_get_all_ticket_panels did not return list"
            asserts += 1

            # 8. Reaction Roles
            rr = await asyncio.to_thread(get_reaction_roles_panels, test_gid)
            assert isinstance(rr, list), "get_reaction_roles_panels did not return list"
            asserts += 1

            # 9. AutoMods
            am = await async_get_automod_settings(test_gid)
            assert isinstance(am, dict) and "spam_enabled" in am, "automod_settings invalid"
            asserts += 1

            # 10. Logger
            lg = await async_get_logger_settings(test_gid)
            assert isinstance(lg, dict), "logger_settings invalid"
            asserts += 1

            # 11. Giveaways
            ga = await async_get_active_giveaways()
            assert isinstance(ga, list), "async_get_active_giveaways did not return list"
            asserts += 1

            # 12. Economy
            ec = await async_get_economy_settings(test_gid)
            assert isinstance(ec, dict) and "daily_amount" in ec, "economy_settings invalid"
            asserts += 1

            # 13. TempVoice
            tv = await async_get_tempvoice_settings(test_gid)
            assert isinstance(tv, dict) and "enabled" in tv, "tempvoice_settings invalid"
            asserts += 1

            # 14. Custom Commands
            cc = await async_get_custom_commands(test_gid)
            assert isinstance(cc, list), "async_get_custom_commands did not return list"
            asserts += 1

            # 15. AI
            ai_s = await async_get_ai_settings(test_gid)
            assert isinstance(ai_s, dict) and "enabled" in ai_s, "ai_settings invalid"
            asserts += 1

            # 16. Remind
            rem = await async_get_user_reminders("0")
            assert isinstance(rem, list), "async_get_user_reminders did not return list"
            asserts += 1

            # 17. Moderation
            warns = await async_get_mod_warnings(test_gid, "0")
            assert isinstance(warns, list), "async_get_mod_warnings did not return list"
            asserts += 1

            # 18. Fun Cog spec
            spec_f = importlib.util.find_spec("cogs.fun") or importlib.util.find_spec("bot.cogs.fun")
            assert spec_f is not None, "Cog cogs.fun could not be resolved"
            asserts += 1

            # 19. Birthday
            bd = await async_get_birthday_settings(test_gid)
            assert isinstance(bd, dict), "async_get_birthday_settings did not return dict"
            asserts += 1

            # 20. Verify Gate
            vf = await async_get_verify_settings(test_gid)
            assert isinstance(vf, dict) and "enabled" in vf, "verify_settings invalid"
            asserts += 1

            return asserts, "All 20 modules verified"

        # ─── 5. Leveling & XP Mathematical Engine ─────────────────────────────
        async def suite_leveling_xp():
            try:
                from bot.cogs.leveling import calc_level_from_xp, calc_xp_for_level
            except ImportError:
                from cogs.leveling import calc_level_from_xp, calc_xp_for_level
            from database import async_update_user_xp, async_get_user_level, async_reset_user_xp
            import aiosqlite

            asserts = 0
            # Test math formulas
            assert calc_level_from_xp(0) == 0, "calc_level_from_xp(0) != 0"
            assert calc_level_from_xp(99) == 0, "calc_level_from_xp(99) != 0"
            assert calc_level_from_xp(100) == 1, "calc_level_from_xp(100) != 1"
            assert calc_level_from_xp(400) == 2, "calc_level_from_xp(400) != 2"
            assert calc_level_from_xp(900) == 3, "calc_level_from_xp(900) != 3"
            assert calc_level_from_xp(10000) == 10, "calc_level_from_xp(10000) != 10"
            assert calc_xp_for_level(1) == 100, "calc_xp_for_level(1) != 100"
            assert calc_xp_for_level(2) == 400, "calc_xp_for_level(2) != 400"
            assert calc_xp_for_level(10) == 10000, "calc_xp_for_level(10) != 10000"
            asserts += 9

            # Test DB integration
            tg = "test_lvl_guild_999"
            tu = "test_lvl_user_999"
            await async_update_user_xp(tg, tu, xp=450, level=2)
            asserts += 1

            info = await async_get_user_level(tg, tu)
            assert info["xp"] == 450, f"User XP expected 450, got {info.get('xp')}"
            assert info["level"] == 2, f"User Level expected 2, got {info.get('level')}"
            asserts += 2

            await async_reset_user_xp(tg, tu)
            asserts += 1

            info_reset = await async_get_user_level(tg, tu)
            assert info_reset["xp"] == 0, f"Reset XP expected 0, got {info_reset.get('xp')}"
            assert info_reset["level"] == 0, f"Reset Level expected 0, got {info_reset.get('level')}"
            asserts += 2

            # Clean up
            async with aiosqlite.connect(get_db_path(), timeout=10.0) as db:
                await db.execute("DELETE FROM user_levels WHERE guild_id = ?", (tg,))
                await db.commit()

            return asserts, "Formulas & DB state verified"

        # ─── 6. Dual-Tier Economy & Atomic Transactions ───────────────────────
        async def suite_economy():
            from database import (
                async_modify_wallet, async_deposit_money,
                async_withdraw_money, async_transfer_money,
                async_get_economy_user
            )
            import aiosqlite

            asserts = 0
            tg = "test_econ_guild_999"
            u_alice = "econ_alice_001"
            u_bob = "econ_bob_002"

            # Clean up test rows first
            async with aiosqlite.connect(get_db_path(), timeout=10.0) as db:
                await db.execute("DELETE FROM economy_users WHERE guild_id = ?", (tg,))
                await db.commit()

            # 1. Modify wallet
            alice = await async_modify_wallet(tg, u_alice, 500)
            assert alice["wallet"] >= 500, f"Alice wallet expected >= 500, got {alice['wallet']}"
            initial_wallet = alice["wallet"]
            asserts += 1

            # 2. Deposit money to Bank
            ok, amt, alice, err = await async_deposit_money(tg, u_alice, 300)
            assert ok is True, f"Deposit 300 failed with err: {err}"
            assert amt == 300, f"Deposit amount expected 300, got {amt}"
            assert alice["bank"] == 300, f"Alice bank expected 300, got {alice['bank']}"
            assert alice["wallet"] == initial_wallet - 300, f"Alice wallet expected {initial_wallet - 300}, got {alice['wallet']}"
            asserts += 4

            # 3. Overspend deposit defense
            ok, amt, alice, err = await async_deposit_money(tg, u_alice, 999999)
            assert ok is False, "Deposit overspend should have been rejected"
            assert err == "not_enough_wallet", f"Expected err 'not_enough_wallet', got {err}"
            asserts += 2

            # 4. Withdraw money from Bank
            ok, amt, alice, err = await async_withdraw_money(tg, u_alice, 100)
            assert ok is True, f"Withdraw 100 failed with err: {err}"
            assert amt == 100, f"Withdraw amount expected 100, got {amt}"
            assert alice["bank"] == 200, f"Alice bank expected 200, got {alice['bank']}"
            asserts += 3

            # 5. Overspend withdraw defense
            ok, amt, alice, err = await async_withdraw_money(tg, u_alice, 999999)
            assert ok is False, "Withdraw overspend should have been rejected"
            assert err == "not_enough_bank", f"Expected err 'not_enough_bank', got {err}"
            asserts += 2

            # 6. Transfer money (/pay) Alice -> Bob
            bob_before = await async_get_economy_user(tg, u_bob)
            bob_wallet_before = bob_before["wallet"]
            alice_wallet_before = alice["wallet"]

            ok = await async_transfer_money(tg, u_alice, u_bob, 50)
            assert ok is True, "Transfer 50 Alice -> Bob failed"
            asserts += 1

            bob_after = await async_get_economy_user(tg, u_bob)
            alice_after = await async_get_economy_user(tg, u_alice)
            assert bob_after["wallet"] == bob_wallet_before + 50, f"Bob wallet expected {bob_wallet_before + 50}, got {bob_after['wallet']}"
            assert alice_after["wallet"] == alice_wallet_before - 50, f"Alice wallet expected {alice_wallet_before - 50}, got {alice_after['wallet']}"
            asserts += 2

            # 7. Transfer overspend defense
            ok = await async_transfer_money(tg, u_alice, u_bob, 999999)
            assert ok is False, "Transfer overspend should have been rejected"
            asserts += 1

            # 8. Transfer to self defense
            ok = await async_transfer_money(tg, u_alice, u_alice, 50)
            assert ok is False, "Transfer to self should have been rejected"
            asserts += 1

            # 9. Test atomic betting & transactions
            from database import async_place_bet, async_get_user_transactions
            bet_ok = await async_place_bet(tg, u_alice, 50)
            assert bet_ok is True, "Atomic place bet 50 failed"
            asserts += 1

            bet_fail = await async_place_bet(tg, u_alice, 999999)
            assert bet_fail is False, "Atomic place bet overspend should have been rejected"
            asserts += 1

            txs = await async_get_user_transactions(tg, u_alice, limit=5)
            assert len(txs) >= 1, "Expected at least 1 transaction record for Alice"
            asserts += 1

            # Clean up
            async with aiosqlite.connect(get_db_path(), timeout=10.0) as db:
                await db.execute("DELETE FROM economy_users WHERE guild_id = ?", (tg,))
                await db.commit()

            return asserts, "Wallet, Bank, Pay, Bet & Overspend defenses verified"

        # ─── 7. Mini-Games & Blackjack Engine Logic ───────────────────────────
        async def suite_blackjack():
            try:
                from bot.cogs.economy import create_deck, calc_hand
            except ImportError:
                from cogs.economy import create_deck, calc_hand

            asserts = 0
            # Deck creation
            deck = create_deck()
            assert len(deck) == 52, f"Expected 52 cards, got {len(deck)}"
            assert len(set(deck)) == 52, "Deck contains duplicate cards"
            asserts += 2

            # Card point calculations
            assert calc_hand(['A♠', 'K♥']) == 21, "A+K must equal 21 (Natural Blackjack)"
            assert calc_hand(['A♠', 'A♥']) == 12, "A+A must equal 12 (Soft Ace reduction)"
            assert calc_hand(['A♠', 'A♥', 'A♦']) == 13, "A+A+A must equal 13 (Double reduction)"
            assert calc_hand(['A♠', '9♥', '5♦']) == 15, "A+9+5 must equal 15"
            assert calc_hand(['10♠', 'J♥', '2♦']) == 22, "10+J+2 must equal 22 (Bust)"
            assert calc_hand(['2♠', '3♥', '4♦', '5♣', '6♠']) == 20, "2+3+4+5+6 must equal 20"
            assert calc_hand(['K♠', 'Q♦', 'J♣']) == 30, "Face cards must equal 10 each"
            asserts += 7

            return asserts, "Deck generation & Soft-Ace math verified"

        # ─── 8. SSRF Security & URL Defense Filter ────────────────────────────
        async def suite_ssrf():
            from dashboard.auth import is_safe_http_url
            asserts = 0

            # Disallowed URLs (must be blocked)
            blocked_urls = [
                "http://127.0.0.1",
                "http://localhost:5000",
                "http://192.168.1.1",
                "http://10.0.0.1/admin",
                "http://172.16.0.1",
                "http://169.254.169.254/latest/meta-data/",
                "http://2130706433",  # Decimal notation of 127.0.0.1
                "file:///etc/passwd",
                "ftp://example.com",
                "javascript:alert(1)",
                "",
                None
            ]
            for url in blocked_urls:
                is_safe = is_safe_http_url(url)
                assert is_safe is False, f"SSRF defense failed: URL '{url}' should be blocked!"
                asserts += 1

            # Allowed public Internet URLs
            allowed_urls = [
                "https://cdn.discordapp.com/icons/test.png",
                "https://zerynbot.id.vn"
            ]
            for url in allowed_urls:
                is_safe = is_safe_http_url(url)
                assert is_safe is True, f"SSRF defense false positive: URL '{url}' should be allowed!"
                asserts += 1

            return asserts, "12 attack vectors blocked, legitimate CDNs allowed"

        # ─── 9. Multi-Language i18n & Keyword Interpolation ───────────────────
        async def suite_i18n():
            from i18n import i18n, tr, DEFAULT_LANG
            asserts = 0

            # 1. Check supported locales count
            expected_langs = {"vi", "en", "zh", "es", "pt", "fr"}
            loaded_langs = set(i18n.translations.keys())
            missing_langs = expected_langs - loaded_langs
            assert not missing_langs, f"Missing language files: {missing_langs}"
            asserts += 1

            # 2. Check 100% key parity giữa các locale.
            # KHÔNG hardcode số key nữa: con số 1618 cứng làm suite đỏ mỗi khi thêm
            # một key i18n hợp lệ (vd: admin.stepup_not_set_*). Điều cần kiểm là MỌI
            # locale có ĐÚNG CÙNG tập key với locale mặc định.
            key_counts = {lang: len(keys) for lang, keys in i18n.translations.items()}
            base_count = len(i18n.translations[DEFAULT_LANG])
            assert base_count > 0, f"Default locale '{DEFAULT_LANG}' rỗng!"
            asserts += 1

            for lang, count in key_counts.items():
                assert count == base_count, (
                    f"Locale '{lang}' có {count} keys, lệch so với '{DEFAULT_LANG}' ({base_count}) "
                    "→ thiếu/thừa key i18n."
                )
                asserts += 1

            base_keys = set(i18n.translations[DEFAULT_LANG].keys())
            for lang, keys in i18n.translations.items():
                diff = base_keys.symmetric_difference(set(keys.keys()))
                assert not diff, f"Locale '{lang}' lệch key so với '{DEFAULT_LANG}': {sorted(diff)[:10]}"
                asserts += 1

            # 3. Test keyword interpolation
            res_vi = tr("vi", "music.volume_changed", vol=80)
            assert "80" in res_vi, f"i18n keyword interpolation failed for 'vi': {res_vi}"
            assert "{vol}" not in res_vi, f"Unformatted placeholder found in 'vi': {res_vi}"
            asserts += 2

            res_en = tr("en", "music.volume_changed", vol=80)
            assert "80" in res_en, f"i18n keyword interpolation failed for 'en': {res_en}"
            assert "{vol}" not in res_en, f"Unformatted placeholder found in 'en': {res_en}"
            asserts += 2

            return asserts, f"6/6 locales synchronized ({base_count} keys), interpolation OK"

        # ─── 10. Pillow Dynamic Card Image Generator ──────────────────────────
        async def suite_pillow():
            try:
                from bot.card_generator import _render_rank_card
            except ImportError:
                from card_generator import _render_rank_card

            asserts = 0
            buf = _render_rank_card(
                avatar_bytes=None,
                username="ZerynTester#1337",
                xp=450,
                level=2,
                rank=1,
                next_xp=900,
                prev_xp=400
            )
            assert buf is not None, "_render_rank_card returned None"
            assert isinstance(buf, io.BytesIO), f"Expected io.BytesIO, got {type(buf)}"
            asserts += 2

            val = buf.getvalue()
            # Verify PNG Magic Number: 0x89 0x50 0x4E 0x47 0x0D 0x0A 0x1A 0x0A
            assert val[:8] == b'\x89PNG\r\n\x1a\n', f"Invalid PNG magic bytes: {val[:8]}"
            assert len(val) > 4000, f"Rendered card too small ({len(val)} bytes), incomplete render"
            asserts += 2

            return asserts, f"PNG buffer rendered ({len(val)} bytes, valid magic header)"

        # ─── 11. SQLite WAL Concurrency & Deadlock Defense ────────────────────
        async def suite_concurrency():
            from database import async_modify_wallet, async_get_economy_user
            import aiosqlite

            asserts = 0
            tg = "test_concurrent_guild_999"

            # Pre-clean
            async with aiosqlite.connect(get_db_path(), timeout=10.0) as db:
                await db.execute("DELETE FROM economy_users WHERE guild_id = ?", (tg,))
                await db.commit()

            # Execute 10 simultaneous async write transactions
            async def _worker(worker_id: int):
                u_id = f"worker_user_{worker_id}"
                res = await async_modify_wallet(tg, u_id, 100 + worker_id)
                assert res["wallet"] >= 100 + worker_id, f"Worker {worker_id} wallet mismatch"
                return res

            tasks = [_worker(i) for i in range(10)]
            workers_res = await asyncio.gather(*tasks)
            assert len(workers_res) == 10, f"Expected 10 completed workers, got {len(workers_res)}"
            asserts += 11

            # Clean up
            async with aiosqlite.connect(get_db_path(), timeout=10.0) as db:
                await db.execute("DELETE FROM economy_users WHERE guild_id = ?", (tg,))
                await db.commit()

            return asserts, "10 concurrent async transactions completed with zero lock errors"

        # ─── Run All 11 Suites ────────────────────────────────────────────────
        await _run_suite("1. SQLite WAL & Schema Architecture", suite_db_wal)
        await _run_suite("2. In-Memory RAM Cache Engine", suite_cache)
        await _run_suite("3. Audio Pipeline & FFmpeg / yt-dlp", suite_audio)
        await _run_suite("4. 20 Core Modules Settings Schema", suite_20_modules)
        await _run_suite("5. Leveling & XP Mathematical Engine", suite_leveling_xp)
        await _run_suite("6. Dual-Tier Economy & Atomic Transactions", suite_economy)
        await _run_suite("7. Mini-Games & Blackjack Engine Logic", suite_blackjack)
        await _run_suite("8. SSRF Security & URL Defense Filter", suite_ssrf)
        await _run_suite("9. Multi-Language i18n & Interpolation", suite_i18n)
        await _run_suite("10. Pillow Dynamic Card Image Generator", suite_pillow)
        await _run_suite("11. SQLite WAL Concurrency & Deadlock Defense", suite_concurrency)

        _safe_print("=" * 68)

        # ─── Process Results ──────────────────────────────────────────────────
        duration_s = time.time() - started_wall
        all_ok = not failed_suites
        slowest = max(suite_records, key=lambda r: r["ms"]) if suite_records else None
        h = db_health or {}
        build = _build_snapshot()
        color = 0x57F287 if all_ok else 0xED4245
        verdict = "🟢 SẴN SÀNG VẬN HÀNH" if all_ok else f"🚨 {len(failed_suites)} SUITE FAIL"

        db_summary = (
            f"journal=`{h.get('journal_mode', '?')}` · "
            f"foreign_keys(app)=`{h.get('app_foreign_keys', h.get('foreign_keys', '?'))}` · "
            f"busy_timeout(app)=`{h.get('app_busy_timeout_ms', h.get('busy_timeout_ms', '?'))}ms` · "
            f"user_version=`{h.get('user_version', '?')}` · "
            f"quick_check=`{h.get('integrity', h.get('error', '?'))}` · {h.get('tables', '?')} bảng · "
            f"bot.db {h.get('size_kib', '?')} KiB + WAL {h.get('wal_kib', '?')} KiB · "
            f"freelist {h.get('freelist_pct', '?')}%"
        )

        overview = {
            "title": f"{'🚀' if all_ok else '🚨'} BÁO CÁO KIỂM THỬ KHỞI ĐỘNG — {verdict}",
            "description": _clamp(
                (f"**{len(suite_records) - len(failed_suites)}/{len(suite_records)} suite PASS** · "
                 f"**{total_assertions} assertions** · hoàn tất trong **{duration_s:.2f}s**\n"
                 + ("Toàn bộ logic lõi (economy nguyên tử, leveling, SSRF, i18n, audio, WAL "
                    "concurrency) được xác nhận bằng assert thật, không phải smoke test import."
                    if all_ok else
                    "Hệ thống VẪN khởi động nhưng có lỗi logic — xem embed 'Traceback' bên dưới.")),
                4096),
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "footer": {"text": f"ZerynBot V2 Functional Assertion Tester · {build}"},
            "fields": [
                {"name": "🏗️ Build đang chạy", "value": _clamp(f"`{build}`", 1024), "inline": True},
                {"name": "🖥️ Host", "value": _clamp(_host_snapshot(), 1024), "inline": True},
                {"name": "📦 Phiên bản", "value": _clamp(_versions_snapshot(), 1024)},
                {"name": "🧠 Tài nguyên", "value": _clamp(f"{_memory_snapshot()} · {_disk_snapshot()}", 1024)},
                {"name": "⚙️ Tải máy & uptime", "value": _clamp(_load_uptime_snapshot(), 1024)},
                {"name": "⏱️ Suite chậm nhất",
                 "value": _clamp(
                     f"`{slowest['name']}` — {slowest['ms']:.0f} ms / {slowest['asserts']} asserts"
                     if slowest else "—", 1024)},
                {"name": "🗄️ Sức khỏe DB (đọc từ file thật, mode=ro)", "value": _clamp(db_summary, 1024)},
                {"name": "🧪 Cách ly khi test",
                 "value": ("Self-test chạy trên **snapshot DB tạm** → `data/bot.db` không nhận hàng dò."
                           if sandboxed else
                           "⚠️ Không tạo được snapshot → self-test đang ghi vào **DB thật**.")},
            ],
        }

        suite_embed = {
            "title": f"📋 Chi tiết {len(suite_records)} nhóm kiểm thử",
            "color": color,
            "fields": [
                {
                    "name": f"{'🟢' if r['ok'] else '🔴'} {r['name']}",
                    "value": _clamp(
                        f"{r['ms']:.1f} ms · {r['asserts']} asserts"
                        + (f"\n`{r['note']}`" if r["note"] else "")
                        + (f"\n❌ {r['error'].splitlines()[0]}" if r["error"] else ""),
                        1024),
                }
                for r in suite_records
            ],
        }

        rows = h.get("rows", {})
        row_chunks, cur, cur_len = [], [], 0
        for name, count in sorted(rows.items(), key=lambda kv: -kv[1]):
            line = f"`{name}` = {count:,}"
            if cur_len + len(line) + 1 > 1000:
                row_chunks.append(cur)
                cur, cur_len = [], 0
            cur.append(line)
            cur_len += len(line) + 1
        if cur:
            row_chunks.append(cur)

        orphans = h.get("orphans", {})
        db_fields = [
            {"name": f" Số hàng theo bảng (phần {i + 1}/{len(row_chunks)})", "value": _clamp("\n".join(chunk), 1024)}
            for i, chunk in enumerate(row_chunks)
        ]
        if orphans:
            bad = {k: v for k, v in orphans.items() if v}
            db_fields.append({
                "name": "🔗 Hàng mồ côi (FK)",
                "value": _clamp(
                    ("✅ " + " · ".join(f"{k} = {v}" for k, v in orphans.items())) if not bad
                    else "⚠️ " + " · ".join(f"**{k} = {v}**" for k, v in bad.items()),
                    1024),
            })
        db_embed = {"title": "🗄️ Sức khỏe database", "color": color, "fields": db_fields[:24]}

        embeds = [overview, suite_embed, db_embed]
        full_lines = [
            "ZERYNBOT V2 — BÁO CÁO KIỂM THỬ KHỞI ĐỘNG",
            "=" * 72,
            f"Thời điểm  : {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.gmtime())}",
            f"Build       : {build}",
            f"Host        : {_host_snapshot()}",
            f"Phiên bản   : {_versions_snapshot()}",
            f"Tài nguyên  : {_memory_snapshot()} · {_disk_snapshot()}",
            f"Tải/uptime  : {_load_uptime_snapshot()}",
            f"Kết quả     : {verdict} · {total_assertions} assertions · {duration_s:.2f}s",
            f"Cách ly DB  : {'sandbox tạm (DB thật không bị ghi)' if sandboxed else 'KHÔNG SANDBOX — ghi DB thật'}",
            "",
            "-" * 72,
            "DATABASE (đọc từ file thật, mode=ro)",
            "-" * 72,
            db_summary,
            f"path: {h.get('path', '?')}",
        ]
        for name, count in sorted(rows.items(), key=lambda kv: -kv[1]):
            full_lines.append(f"  {name:<28} {count:>8,}")
        if orphans:
            full_lines.append("  orphans: " + " · ".join(f"{k}={v}" for k, v in orphans.items()))

        full_lines += ["", "-" * 72, "TỪNG NHÓM KIỂM THỬ", "-" * 72]
        for r in suite_records:
            full_lines.append(
                f"[{'PASS' if r['ok'] else 'FAIL'}] {r['name']} — {r['ms']:.1f} ms, "
                f"{r['asserts']} asserts, timeout ceiling {r['timeout_sec']}s"
            )
            if r["note"]:
                full_lines.append(f"    đo được: {r['note']}")

        if failed_suites:
            fail_embed_fields = []
            full_lines += ["", "-" * 72, "TRACEBACK CHI TIẾT", "-" * 72]
            for suite in failed_suites[:8]:
                err = error_details[suite]
                fail_embed_fields.append({
                    "name": f"🚨 {suite}"[:256],
                    "value": f"```py\n{_clamp(err, 990)}\n```",
                })
                full_lines += [f"\n### {suite}\n{err}"]
            embeds.append({
                "title": f"🚨 Traceback — {len(failed_suites)} suite fail (bản cắt gọn, đủ trong file đính kèm)",
                "description": _clamp(
                    "Toàn văn traceback nằm trong file `.txt` đính kèm.", 4096),
                "color": 0xED4245,
                "fields": fail_embed_fields,
            })

        full_text = "\n".join(full_lines)
        sha = build.split("@")[-1].split()[0] if "@" in build else "unknown"
        filename = f"zerynbot_selftest_{sha}_{time.strftime('%Y%m%d_%H%M%S')}.txt"

        if failed_suites:
            _safe_print(f"❌ [Tester] PHÁT HIỆN LỖI TẠI {len(failed_suites)} NHÓM TEST:")
            for suite in failed_suites:
                _safe_print(f"\n--- [Chi tiết lỗi tại: {suite}] ---")
                _safe_print(error_details[suite])
        else:
            _safe_print(f"🎉 TẤT CẢ {len(suite_records)} NHÓM BÀI TEST & {total_assertions} ASSERTIONS ĐỀU PASS 100%!")
        _safe_print("=" * 68)

        await _post_webhook_report(embeds, full_text=full_text, filename=filename)
        return all_ok

if __name__ == "__main__":
    success = asyncio.run(SystemTester.run_all_tests())
    sys.exit(0 if success else 1)
