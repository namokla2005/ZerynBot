"""
termux_cleanup.py — Dọn rác & tối ưu dung lượng cho Termux (Tecno Pova 2).

An toàn theo mặc định: LUÔN chạy `--dry-run` trước để xem kế hoạch, rồi mới
chạy thật. Hai chế độ:
  - Mặc định: điều khiển Termux từ xa qua SSH (dùng scripts/termux_deploy.py).
  - `--local`: chạy ngay trên máy hiện tại (khi bạn đang ngồi ở Termux).

LƯU Ý QUAN TRỌNG — bot đã tự dọn dữ liệu (xem bot/cogs/maintenance.py):
  guild_stats 60 ngày, automod_warnings 2 ngày, fun_interactions 60 ngày,
  reminders 30 ngày, music_song_cache 7 ngày, activity_logs 7 ngày,
  ai_activity_logs 2 ngày.
Vì vậy script này chỉ tập trung vào phần bot KHÔNG đụng tới: cargo/pip cache,
backup cũ, log stdout phình to, và checkpoint WAL để trả dung lượng file.

Sử dụng:
    python scripts/termux_deploy.py cleanup --dry-run   # xem kế hoạch
    python scripts/termux_deploy.py cleanup             # dọn thật (qua SSH)
    python scripts/termux_deploy.py cleanup --local     # dọn trên máy hiện tại
"""
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Ép UTF-8 để không vỡ khi in tiếng Việt trên console Windows (cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

MAX_STDOUT_LOG_BYTES = 5 * 1024 * 1024   # khớp scripts/watchdog.sh
BACKUP_RETENTION = 5                     # giữ 5 bản backup mới nhất
STDOUT_LOGS = ("bot.stdout.log", "dashboard.stdout.log")


class _Runner:
    """Bọc 2 chế độ chạy lệnh: local (subprocess) và remote (SSH qua RemoteExecutor)."""

    def __init__(self, dry_run: bool = False, local: bool = False):
        self.dry_run = dry_run
        self.local = local
        self._remote = None
        self.mode = "local (máy hiện tại)" if local else "remote (SSH)"

    # ── kết nối / dọn dẹp ────────────────────────────────────────────────────
    def connect(self) -> tuple[bool, str]:
        if self.local:
            self.bot_dir = BASE_DIR
            return True, self.mode

        from scripts.termux_deploy import RemoteExecutor, get_config

        self._remote = RemoteExecutor(get_config())
        ok, info = self._remote.connect()
        if not ok:
            return False, info
        self.bot_dir = get_config()["bot_dir"]
        self.mode = info
        return True, info

    def close(self) -> None:
        if self._remote is not None:
            self._remote.close()

    # ── chạy lệnh ────────────────────────────────────────────────────────────
    def exec(self, cmd: str, timeout: float = 120.0, readonly: bool = False) -> tuple[str, int]:
        """Chạy `cmd`; ở chế độ dry_run chỉ in ra (trừ lệnh readonly)."""
        if self.dry_run and not readonly:
            print(f"   [dry-run] sẽ chạy: {cmd}")
            return "", 0
        if self.local:
            res = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=self.bot_dir, timeout=timeout,
            )
            return ((res.stdout or "") + (res.stderr or "")).strip(), res.returncode
        out, err, code = self._remote.exec(cmd, timeout=timeout)
        return (out or err or "").strip(), code


def _sqlite_cleanup_cmd(bot_dir: str) -> str:
    """Lệnh python dọn cache SQLite (bot không dọn: music_song_cache cũ + WAL)."""
    return (
        "python -c \""
        "import sqlite3, time, os;"
        f"p=os.path.expanduser('{bot_dir}/data/bot.db');"
        "c=sqlite3.connect(p, timeout=15.0);"
        "cur=c.cursor();"
        "cur.execute('DELETE FROM music_song_cache WHERE created_at < ?', (time.time()-7*86400,));"
        "m=cur.rowcount;"
        "c.commit();"
        "cur.execute('PRAGMA wal_checkpoint(PASSIVE);');"
        "w=cur.fetchone();"
        "c.close();"
        "print(f'cache nhac cu da xoa: {m} dong; WAL checkpoint: {w}')\""
    )


def run_termux_cleanup(dry_run: bool = False, local: bool = False) -> bool:
    runner = _Runner(dry_run=dry_run, local=local)
    ok, info = runner.connect()
    if not ok:
        print(f"❌ Không thể kết nối tới Termux: {info}")
        print("💡 Gợi ý: kiểm tra sshd trên Termux, hoặc chạy với --local nếu đang ở trên máy đó.")
        return False

    print("=" * 68)
    print("🧹 DỌN DẸP & TỐI ƯU DUNG LƯỢNG TERMUX (TECNO POVA 2)")
    print("=" * 68)
    print(f"⏱️  Kênh: {info}")
    print(f"📁 Thư mục bot: {runner.bot_dir}")
    if dry_run:
        print("🟡 CHẾ ĐỘ DRY-RUN: chỉ in kế hoạch, KHÔNG xoá gì cả.")
    if local and os.name == "nt":
        print("⚠️  --local trên Windows chỉ để xem giao diện: các lệnh Termux")
        print("    (du/free/apt/sync) sẽ báo lỗi. Muốn dọn máy Termux thật, bỏ --local.")
    print()

    # ── 1. Đo trước khi dọn ─────────────────────────────────────────────────
    pre_cargo, _ = runner.exec("du -sh ~/.cargo 2>/dev/null || echo 0", readonly=True)
    pre_backups, _ = runner.exec(
        f"ls -1 {runner.bot_dir}/data/backups/*.zip 2>/dev/null | wc -l", readonly=True
    )
    pre_data, _ = runner.exec(f"du -sh {runner.bot_dir}/data 2>/dev/null || echo 0", readonly=True)
    pre_disk, _ = runner.exec("df -h /data 2>/dev/null | tail -1 || df -h . | tail -1", readonly=True)
    pre_status, _ = runner.exec(
        f"cd {runner.bot_dir} && python main.py --status", readonly=True, timeout=40.0
    )

    print("📊 TRƯỚC KHI DỌN:")
    print(f"  • ~/.cargo (cache build Rust): {pre_cargo}")
    print(f"  • data/ của bot:               {pre_data}")
    print(f"  • Số bản backup:               {pre_backups}")
    print(f"  • Dung lượng trống:            {pre_disk}")
    print(f"  • Trạng thái tiến trình:\n{pre_status}")
    print()

    # ── 2. Dọn cache build/pip/apt ──────────────────────────────────────────
    print("🗑️  [1/5] Cache build & package (cargo registry, pip, apt)...")
    runner.exec(
        'if [ -d "$HOME/.cargo/registry" ]; then '
        'du -sh "$HOME/.cargo/registry"; rm -rf "$HOME/.cargo/registry" && echo "Đã xoá cargo registry"; '
        'else echo "Không có ~/.cargo/registry"; fi'
    )
    runner.exec("pip cache purge 2>/dev/null || true")
    runner.exec("rm -rf /data/data/com.termux/cache/apt/* 2>/dev/null || true")

    # ── 3. Giữ lại N bản backup mới nhất ────────────────────────────────────
    print(f"\n📦 [2/5] Backup: giữ {BACKUP_RETENTION} bản mới nhất, xoá phần cũ hơn...")
    runner.exec(
        f"cd {runner.bot_dir}/data/backups 2>/dev/null && "
        f"ls -1t backup_*.zip 2>/dev/null | tail -n +{BACKUP_RETENTION + 1} | "
        'while read -r f; do echo "Xoá backup cũ: $f"; rm -f "$f"; done'
    )

    # ── 4. Xoay log stdout phình to (khớp cơ chế ở scripts/watchdog.sh) ─────
    print(f"\n📜 [3/5] Log stdout: xoay file > {MAX_STDOUT_LOG_BYTES // (1024 * 1024)}MB...")
    for name in STDOUT_LOGS:
        runner.exec(
            f'f="{runner.bot_dir}/data/{name}"; '
            'if [ -f "$f" ]; then '
            '  sz=$(wc -c < "$f" 2>/dev/null || echo 0); '
            f'  if [ "$sz" -gt {MAX_STDOUT_LOG_BYTES} ]; then mv -f "$f" "$f.1" && : > "$f" && echo "Đã xoay $f"; '
            '  else echo "OK: $f còn nhỏ"; fi; '
            'else echo "Không có $f"; fi'
        )

    # ── 5. SQLite: cache nhạc cũ + checkpoint WAL ───────────────────────────
    print("\n🗄️  [4/5] SQLite: xoá cache nhạc cũ hơn 7 ngày + checkpoint WAL...")
    out_db, _ = runner.exec(_sqlite_cleanup_cmd(runner.bot_dir))
    print(f"  {out_db or '(không có phản hồi)'}")
    print("  ℹ️  Các bảng activity_logs / ai_activity_logs / guild_stats... đã được"
          "\n      bot tự prune hằng ngày (bot/cogs/maintenance.py), không cần dọn tay.")

    # ── 6. Đồng bộ filesystem ───────────────────────────────────────────────
    runner.exec("sync")

    # ── 7. Đo sau khi dọn ───────────────────────────────────────────────────
    post_cargo, _ = runner.exec("du -sh ~/.cargo 2>/dev/null || echo 0", readonly=True)
    post_backups, _ = runner.exec(
        f"ls -1 {runner.bot_dir}/data/backups/*.zip 2>/dev/null | wc -l", readonly=True
    )
    post_data, _ = runner.exec(f"du -sh {runner.bot_dir}/data 2>/dev/null || echo 0", readonly=True)
    post_disk, _ = runner.exec("df -h /data 2>/dev/null | tail -1 || df -h . | tail -1", readonly=True)
    post_mem, _ = runner.exec("free -h 2>/dev/null || echo '(không có free)'", readonly=True)
    health, _ = runner.exec("curl -s -m 5 http://localhost:5000/health || echo OFFLINE", readonly=True)

    print("\n" + "=" * 68)
    print("✨ SAU KHI DỌN")
    print("=" * 68)
    print(f"  • ~/.cargo:        {pre_cargo} ➔ {post_cargo}")
    print(f"  • data/ của bot:   {pre_data} ➔ {post_data}")
    print(f"  • Số bản backup:   {pre_backups} ➔ {post_backups}")
    print(f"  • Dung lượng trống:{pre_disk} ➔ {post_disk}")
    print(f"  • Health endpoint: {health or '(không có phản hồi)'}")
    print(f"  • RAM:\n{post_mem}")

    runner.close()
    if dry_run:
        print("\n🟡 Dry-run kết thúc: chưa có gì bị xoá. Chạy lại không có --dry-run để dọn thật.")
    else:
        print(f"\n✅ Hoàn tất dọn dẹp lúc {time.strftime('%Y-%m-%d %H:%M:%S')}.")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dọn rác & tối ưu dung lượng Termux.")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in kế hoạch, không xoá")
    parser.add_argument("--local", action="store_true", help="Chạy trên máy hiện tại (không qua SSH)")
    _args = parser.parse_args()

    sys.exit(0 if run_termux_cleanup(dry_run=_args.dry_run, local=_args.local) else 1)
