"""
admin.py — Khu vực quản trị (bot owner): telemetry, log, AI key, hệ thống.

Mọi route ở đây được bảo vệ bởi `owner_required` (và `stepup_required` cho thao
tác nguy hiểm). Các helper `owner_required` / `stepup_required` /
`_audit_admin_action` / `get_system_hardware_stats` nằm luôn trong file này vì chỉ
khu vực admin sử dụng.
"""

import os
import sys

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import json
import secrets
import shlex
import shutil
import subprocess
import time as _time
from functools import wraps

import requests
from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import config
import database as db
from dashboard.extensions import _discord_api, limiter, logger

bp = Blueprint("admin", __name__)


def owner_required(f):
    """Decorator: chỉ Bot Owner mới được truy cập."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("public.login"))
        user_id = str(session["user"].get("id", ""))
        owner_id = str(config.BOT_OWNER_ID)
        if not owner_id or owner_id == "0" or user_id != owner_id:
            flash("⛔ Bạn không có quyền truy cập khu vực này.", "error")
            return redirect(url_for("guild.home"))
        return f(*args, **kwargs)
    return decorated

def _admin_password_ready() -> bool:
    """ADMIN_PASSWORD có tồn tại và đủ dài để mở các route nguy hiểm hay không."""
    pw = getattr(config, "ADMIN_PASSWORD", "") or ""
    return len(pw) >= getattr(config, "ADMIN_PASSWORD_MIN_LENGTH", 16)

def stepup_required(f):
    """Decorator: yêu cầu xác thực mật khẩu cấp cao (Step-Up Auth) trong vòng 15 phút.

    FAIL-CLOSED. Trước đây decorator chỉ kiểm tra khi `ADMIN_PASSWORD` đang truthy,
    nghĩa là quên cấu hình mật khẩu = Web Terminal / git-pull / restart tự động mất
    lớp bảo vệ cuối cùng và chỉ còn session owner (tuổi 7 ngày) chắn đường vào shell
    trên máy chứa token Discord + key AI.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _admin_password_ready():
            return jsonify({
                "ok": False,
                "error": "stepup_unconfigured",
                "message": (
                    "🔒 ADMIN_PASSWORD chưa được đặt hoặc ngắn hơn "
                    f"{getattr(config, 'ADMIN_PASSWORD_MIN_LENGTH', 16)} ký tự — "
                    "các thao tác quản trị cấp cao bị vô hiệu hóa."
                ),
            }), 503
        until = session.get("stepup_auth_until", 0)
        if _time.time() > until:
            return jsonify({
                "ok": False,
                "error": "stepup_required",
                "message": "🔒 Yêu cầu xác thực mật khẩu quản trị cấp cao để thực hiện thao tác này."
            }), 401
        return f(*args, **kwargs)
    return decorated

def _audit_admin_action(action: str, event_type: str = "admin_action", details: str = None) -> None:
    """Ghi mọi thao tác quản trị cấp cao vào activity_logs (audit trail).

    Trước đây Web Terminal / git-pull / restart không để lại dấu vết nào — nếu
    session owner bị lạm dụng thì không cách nào biết ai đã chạy gì.
    """
    try:
        user = session.get("user") or {}
        db.log_activity(
            action=str(action)[:250],
            event_type=event_type,
            user_id=str(user.get("id") or "") or None,
            user_name=user.get("username") or user.get("global_name") or None,
            avatar_url=session.get("avatar"),
            details=(str(details)[:500] if details else None),
        )
    except Exception as exc:  # audit log không bao giờ được làm hỏng request
        logger.warning("[Admin] lỗi ghi audit log: %s", exc)

def _get_all_bot_guilds_detailed() -> list:
    """Lấy danh sách tất cả server bot đang có mặt, kèm thông tin chi tiết."""
    try:
        resp = _discord_api("GET", "/users/@me/guilds", timeout=10)
        if resp is None or not resp.ok:
            return []
        guilds = resp.json()
    except Exception as e:
        logger.warning("[Admin] lỗi lấy danh sách guild của bot: %s", e)
        return []

    # Bổ sung thông tin icon_url
    result = []
    for g in guilds:
        g["icon_url"] = (
            f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png"
            if g.get("icon") else None
        )
        # Lấy member count từ guild_meta cache trong DB
        meta = db.get_guild_meta(g["id"]) or {}
        g["member_count"] = meta.get("member_count", 0)
        g["cached_name"]  = meta.get("guild_name") or g.get("name", "Unknown")
        result.append(g)
    return result

def get_system_hardware_stats() -> dict:
    """Đọc thông số RAM, Uptime và trạng thái hệ thống cho Termux Linux và Windows."""
    import re
    stats = {
        "ram_percent": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "uptime": "24/7 Active",
        "host_platform": "Tecno Pova 2 • Termux ARM64" if os.name != "nt" else "Windows Host",
        "status": "healthy"
    }
    
    # 1. RAM Telemetry
    try:
        if os.path.exists("/proc/meminfo"):
            meminfo = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().split()[0]
                        if v.isdigit():
                            meminfo[k] = int(v)
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0) + meminfo.get("Buffers", 0) + meminfo.get("Cached", 0))
            if total_kb > 0:
                used_kb = total_kb - avail_kb
                stats["ram_total_gb"] = round(total_kb / (1024 * 1024), 2)
                stats["ram_used_gb"] = round(used_kb / (1024 * 1024), 2)
                stats["ram_percent"] = round((used_kb / total_kb) * 100, 1)
        elif os.name == "nt":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_b = stat.ullTotalPhys
                avail_b = stat.ullAvailPhys
                used_b = total_b - avail_b
                stats["ram_total_gb"] = round(total_b / (1024**3), 2)
                stats["ram_used_gb"] = round(used_b / (1024**3), 2)
                stats["ram_percent"] = round(float(stat.dwMemoryLoad), 1)
    except Exception as e:
        logger.warning("[Telemetry] lỗi đọc RAM: %s", e)

    # 2. Uptime Telemetry
    try:
        if os.name != "nt":
            res = subprocess.run(["uptime"], capture_output=True, text=True, timeout=2)
            out = res.stdout.strip()
            if "up " in out:
                m = re.search(r"up\s+([^,]+,\s*[^,]+)", out)
                if m:
                    stats["uptime"] = m.group(1).replace("days", "ngày").replace("day", "ngày").strip()
                else:
                    part = out.split("up ")[1].split(",")[0].strip()
                    stats["uptime"] = part.replace("days", "ngày").replace("day", "ngày")
    except Exception as e:
        logger.warning("[Telemetry] lỗi đọc uptime: %s", e)

    return stats

@bp.route("/admin")
@owner_required
def admin_panel():
    guilds    = _get_all_bot_guilds_detailed()
    blacklist = db.get_blacklist()
    blacklist_ids = {b["guild_id"] for b in blacklist}
    global_ai_key = db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
    global_ai_model = db.get_global_setting("global_ai_model") or "gemini-3.6-flash"
    gemini_api_keys = db.get_global_setting("gemini_api_keys", "")
    groq_api_keys = db.get_global_setting("groq_api_keys", "")
    openrouter_api_keys = db.get_global_setting("openrouter_api_keys", "")
    global_ai_provider = db.get_global_setting("global_ai_provider", "auto")

    # Tự động nạp key cũ vào pool tương ứng nếu pool chưa được lưu
    if not gemini_api_keys and not groq_api_keys and not openrouter_api_keys and global_ai_key:
        if global_ai_key.startswith("gsk_"):
            groq_api_keys = global_ai_key
        elif global_ai_key.startswith("sk-or-"):
            openrouter_api_keys = global_ai_key
        else:
            gemini_api_keys = global_ai_key

    telemetry = get_system_hardware_stats()
    activity_logs = db.get_system_activity_logs(limit=50, days_ttl=7)
    return render_template(
        "admin.html",
        user=session["user"],
        avatar=session.get("avatar"),
        guilds=guilds,
        blacklist=blacklist,
        blacklist_ids=blacklist_ids,
        total_servers=len(guilds),
        total_blacklist=len(blacklist),
        global_ai_key=global_ai_key,
        global_ai_model=global_ai_model,
        gemini_api_keys=gemini_api_keys,
        groq_api_keys=groq_api_keys,
        openrouter_api_keys=openrouter_api_keys,
        global_ai_provider=global_ai_provider,
        telemetry=telemetry,
        activity_logs=activity_logs,
        admin_password_set=_admin_password_ready(),
    )

@bp.route("/api/admin/telemetry")
@owner_required
def api_admin_telemetry():
    """Trả về thông số % CPU, % RAM và dung lượng RAM hiện tại."""
    stats = get_system_hardware_stats()
    return jsonify({"ok": True, **stats})

@bp.route("/api/admin/activity_logs")
@owner_required
def api_admin_activity_logs():
    """Trả về tối đa 50 log hoạt động gần nhất trong vòng 7 ngày (tự động xóa log > 7 ngày)."""
    logs = db.get_system_activity_logs(limit=50, days_ttl=7)
    return jsonify({"ok": True, "logs": logs})

@bp.route("/admin/support")
@bp.route("/admin/support/")
@owner_required
def admin_support_center():
    """Trang quản trị hỗ trợ khách hàng phong cách Messenger 2 cột."""
    status_filter = request.args.get("status")
    threads = db.get_all_support_threads(status_filter=status_filter)
    return render_template(
        "admin_support.html",
        threads=threads,
        current_ui_lang=session.get("ui_lang", "vi")
    )

@bp.route("/api/admin/support/thread/<thread_id>/messages")
@owner_required
def api_admin_thread_messages(thread_id: str):
    """API lấy tin nhắn của một thread cụ thể cho Admin."""
    after_id = int(request.args.get("after_id", 0) or 0)
    thread = db.get_support_thread(thread_id)
    if not thread:
        return jsonify({"ok": False, "error": "thread_not_found"}), 404

    messages = db.get_support_messages(thread_id, after_id=after_id, limit=50)
    db.mark_support_thread_read(thread_id, by_admin=True)
    return jsonify({"ok": True, "messages": messages, "status": thread.get("status")})

@bp.route("/api/admin/support/thread/<thread_id>/reply", methods=["POST"])
@owner_required
def api_admin_thread_reply(thread_id: str):
    """API gửi tin nhắn phản hồi từ Admin tới User."""
    data = request.get_json(silent=True) or request.form
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"ok": False, "error": "empty_content"}), 400

    thread = db.get_support_thread(thread_id)
    if not thread:
        return jsonify({"ok": False, "error": "thread_not_found"}), 404

    admin_name = session["user"].get("username", "Admin")
    msg = db.add_support_message(
        thread_id=thread_id,
        sender_type="admin",
        sender_id=str(session["user"].get("id")),
        sender_name=admin_name,
        content=content
    )
    return jsonify({"ok": True, "message_id": msg.get("id")})

@bp.route("/api/admin/support/thread/<thread_id>/status", methods=["POST"])
@owner_required
def api_admin_thread_status(thread_id: str):
    """API cập nhật trạng thái thread ('open', 'escalated', 'resolved')."""
    data = request.get_json(silent=True) or request.form
    status = data.get("status", "").strip()
    if status not in ("open", "escalated", "resolved"):
        return jsonify({"ok": False, "error": "invalid_status"}), 400

    updated = db.update_support_thread_status(thread_id, status)
    return jsonify({"ok": updated})

@bp.route("/admin/ai_key", methods=["POST"])
@owner_required
def admin_save_ai_key():
    gemini_keys = request.form.get("gemini_api_keys", "").strip()
    groq_keys = request.form.get("groq_api_keys", "").strip()
    openrouter_keys = request.form.get("openrouter_api_keys", "").strip()
    provider = request.form.get("global_ai_provider", "auto").strip().lower()
    model = request.form.get("global_ai_model", "").strip()
    custom_model = request.form.get("custom_ai_model", "").strip()
    if model == "custom" and custom_model:
        model = custom_model

    # Backward compatibility with single-key field if user pasted in legacy field
    legacy_key = request.form.get("global_ai_key", "").strip()
    if legacy_key and not gemini_keys and not groq_keys and not openrouter_keys:
        if legacy_key.startswith("gsk_"):
            groq_keys = legacy_key
        elif legacy_key.startswith("sk-or-"):
            openrouter_keys = legacy_key
        else:
            gemini_keys = legacy_key

    db.set_global_setting("gemini_api_keys", gemini_keys)
    db.set_global_setting("groq_api_keys", groq_keys)
    db.set_global_setting("openrouter_api_keys", openrouter_keys)
    db.set_global_setting("global_ai_provider", provider)
    if model:
        db.set_global_setting("global_ai_model", model)

    # Sync primary key to legacy setting for backwards compatibility
    from ai_manager import parse_key_pool
    p_gemini = parse_key_pool(gemini_keys)
    p_groq = parse_key_pool(groq_keys)
    p_open = parse_key_pool(openrouter_keys)
    primary_key = (p_gemini[0] if p_gemini else (p_groq[0] if p_groq else (p_open[0] if p_open else "")))
    if primary_key:
        db.set_global_setting("gemini_api_key", primary_key)

    try:
        from ai_logger import ai_logger
        ai_logger.update_model_config("model1", model=model, provider=provider)
        ai_logger.log_event(
            source="model1",
            model=model or "auto",
            provider=provider or "auto",
            latency_ms=0,
            status="OK",
            message=f"Quản trị viên đã lưu cấu hình AI Model mới: {model} ({provider})"
        )
    except Exception:
        pass

    flash("✅ Đã lưu cấu hình Multi-Provider AI API Key Pools & Model toàn cục thành công!", "success")
    return redirect(url_for("admin.admin_panel") + "#ai_settings")

@bp.route("/api/admin/ai/activity-feed", methods=["GET"])
@limiter.limit("60/minute")
@owner_required
def api_admin_ai_activity_feed():
    """Trả về snapshot hoạt động thời gian thực của cả Model 1 và Model 2."""
    since_raw = request.args.get("since_id", 0)
    try:
        since_id = int(since_raw) if str(since_raw).isdigit() else 0
    except (ValueError, TypeError):
        since_id = 0
    try:
        from ai_logger import ai_logger
        data = ai_logger.get_snapshot(since_id=since_id)
        cur_model = db.get_global_setting("global_ai_model") or "qwen/qwen3.8-27b"
        cur_prov = db.get_global_setting("global_ai_provider") or "auto"
        if isinstance(data.get("models"), dict) and "model1" in data["models"]:
            data["models"]["model1"]["model"] = cur_model
            data["models"]["model1"]["provider"] = cur_prov
        return jsonify(data)
    except Exception as e:
        logger.error(f"Lỗi api_admin_ai_activity_feed: {e}")
        return jsonify({"ok": False, "message": "Lỗi truy vấn dữ liệu hoạt động AI", "models": {}, "logs": []})

@bp.route("/api/admin/test_ai_key", methods=["POST"])
@limiter.limit("30/minute")
@owner_required
def api_admin_test_ai_key():
    from ai_manager import ai_manager, parse_key_pool
    data = request.get_json(silent=True) or {}

    gemini_raw = data.get("gemini_keys")
    groq_raw = data.get("groq_keys")
    openrouter_raw = data.get("openrouter_keys")
    single_key = data.get("api_key", "").strip()
    target_model = data.get("model") or db.get_global_setting("global_ai_model") or "gemini-3.6-flash"

    # Single key check fallback (nếu người dùng bấm test nhanh 1 key cụ thể)
    if single_key and gemini_raw is None and groq_raw is None:
        res = ai_manager.test_single_key(single_key, target_model=target_model)
        return jsonify(res)

    # Multi-pool check: lấy từ payload hoặc DB
    if gemini_raw is None:
        gemini_raw = db.get_global_setting("gemini_api_keys", "")
    if groq_raw is None:
        groq_raw = db.get_global_setting("groq_api_keys", "")
    if openrouter_raw is None:
        openrouter_raw = db.get_global_setting("openrouter_api_keys", "")

    g_keys = parse_key_pool(gemini_raw)
    gr_keys = parse_key_pool(groq_raw)
    op_keys = parse_key_pool(openrouter_raw)

    if not g_keys and not gr_keys and not op_keys:
        legacy_k = db.get_global_setting("gemini_api_key") or config.GEMINI_API_KEY
        if legacy_k:
            res = ai_manager.test_single_key(legacy_k, target_model=target_model)
            return jsonify(res)
        return jsonify({
            "ok": False,
            "status": "no_key",
            "message": "Chưa có bất kỳ API Key nào trong các Pool! Vui lòng nhập ít nhất 1 Key."
        })

    # Kiểm tra song song an toàn qua ThreadPoolExecutor (max_workers=3)
    results = ai_manager.test_all_pools(g_keys, gr_keys, op_keys, target_model=target_model)
    total = len(results)
    passed = sum(1 for r in results if r.get("ok"))

    return jsonify({
        "ok": passed > 0,
        "total": total,
        "passed": passed,
        "results": results,
        "message": f"Kiểm tra hoàn tất: {passed}/{total} Key hoạt động bình thường!"
    })

@bp.route("/admin/kick/<guild_id>", methods=["POST"])
@owner_required
def admin_kick_guild(guild_id: str):
    """Buộc bot rời khỏi server và thêm vào blacklist."""
    reason = request.form.get("reason", "Bị kick bởi Owner").strip() or "Bị kick bởi Owner"

    # Lấy tên server trước khi kick
    guild_name = request.form.get("guild_name", "Unknown")

    # Gọi Discord API để bot rời server
    resp = _discord_api("DELETE", f"/users/@me/guilds/{guild_id}", timeout=10)
    if resp is None:
        flash("❌ Không thể kết nối đến Discord API (xem data/dashboard.log).", "error")
        return redirect(url_for("admin.admin_panel"))
    if resp.status_code not in (200, 204):
        flash(f"❌ Discord API trả về lỗi: {resp.status_code} — {resp.text}", "error")
        return redirect(url_for("admin.admin_panel"))

    # Thêm vào blacklist
    db.add_to_blacklist(guild_id, guild_name, reason)
    flash(f"✅ Bot đã rời khỏi **{guild_name}** và server đã được thêm vào Blacklist!", "success")
    return redirect(url_for("admin.admin_panel"))

@bp.route("/admin/unblacklist/<guild_id>", methods=["POST"])
@owner_required
def admin_unblacklist(guild_id: str):
    """Xóa server khỏi blacklist."""
    db.remove_from_blacklist(guild_id)
    flash("✅ Đã xóa server khỏi Blacklist!", "success")
    return redirect(url_for("admin.admin_panel"))

@bp.route("/admin/invite/<guild_id>", methods=["POST"])
@owner_required
def admin_invite_guild(guild_id: str):
    """Tạo instant invite link cho một server để Owner có thể gia nhập."""
    cr = _discord_api("GET", f"/guilds/{guild_id}/channels", timeout=8)
    if cr is None:
        return jsonify({"ok": False, "error": "Lỗi kết nối Discord API (xem data/dashboard.log)."}), 500
    if not cr.ok:
        return jsonify({"ok": False, "error": f"Không thể lấy danh sách kênh (HTTP {cr.status_code})"}), 400
    channels = cr.json()

    candidate_channels = [c for c in channels if c.get("type") in (0, 5, 2)]
    if not candidate_channels:
        return jsonify({"ok": False, "error": "Server không có kênh phù hợp để tạo link mời."}), 400

    # Ưu tiên text channels (type 0) trước
    candidate_channels.sort(key=lambda c: (0 if c.get("type") == 0 else 1, c.get("position", 999)))

    for ch in candidate_channels:
        ch_id = ch["id"]
        try:
            inv_resp = _discord_api(
                "POST",
                f"/channels/{ch_id}/invites",
                json={
                    "max_age": 86400,
                    "max_uses": 0,
                    "unique": False
                },
                timeout=5
            )
            if inv_resp is not None and inv_resp.status_code in (200, 201):
                inv_data = inv_resp.json()
                code = inv_data.get("code")
                if code:
                    return jsonify({
                        "ok": True,
                        "code": code,
                        "url": f"https://discord.gg/{code}",
                        "channel_name": ch.get("name", "kênh")
                    })
        except Exception:
            continue

    return jsonify({"ok": False, "error": "Bot không có quyền Create Invite (Tạo liên kết mời) ở bất kỳ kênh nào trong server này."}), 403

@bp.route("/admin/broadcast", methods=["POST"])
@limiter.limit("10/minute")
@owner_required
def admin_broadcast():
    """Gửi thông báo broadcast đến các server đã chọn."""

    title   = request.form.get("broadcast_title", "📢 Thông báo từ Bot Owner").strip()
    message = request.form.get("broadcast_message", "").strip()
    color   = request.form.get("broadcast_color", "#5865F2").strip()
    targets = request.form.getlist("target_guilds")   # danh sách guild_id được chọn
    send_all = request.form.get("send_all") == "1"

    if not message:
        flash("❌ Nội dung thông báo không được để trống!", "error")
        return redirect(url_for("admin.admin_panel"))

    # Chuyển hex color → int
    try:
        color_int = int(color.lstrip("#"), 16)
    except Exception:
        color_int = 0x5865F2

    # Lấy danh sách guild cần gửi
    all_guilds = _get_all_bot_guilds_detailed()
    blacklist_ids = {b["guild_id"] for b in db.get_blacklist()}

    if send_all:
        target_guilds = [g for g in all_guilds if g["id"] not in blacklist_ids]
    else:
        target_guilds = [g for g in all_guilds if g["id"] in targets and g["id"] not in blacklist_ids]

    if not target_guilds:
        flash("❌ Không có server nào để gửi thông báo!", "error")
        return redirect(url_for("admin.admin_panel"))

    success_count = 0
    fail_count    = 0

    for guild in target_guilds:
        guild_id = guild["id"]
        # Lấy system channel hoặc kênh text đầu tiên bot có thể gửi
        channel_id = None

        # Thử lấy guild info từ Discord API để có system_channel_id
        try:
            gr = _discord_api("GET", f"/guilds/{guild_id}", timeout=5)
            if gr is not None and gr.ok:
                gdata = gr.json()
                channel_id = gdata.get("system_channel_id")
        except Exception:
            pass

        # Nếu không có system channel, thử kênh text đầu tiên
        if not channel_id:
            try:
                cr = _discord_api("GET", f"/guilds/{guild_id}/channels", timeout=5)
                if cr is not None and cr.ok:
                    channels = cr.json()
                    text_channels = [c for c in channels if c.get("type") == 0]
                    if text_channels:
                        # Sắp xếp theo position
                        text_channels.sort(key=lambda c: c.get("position", 999))
                        channel_id = text_channels[0]["id"]
            except Exception:
                pass

        if not channel_id:
            fail_count += 1
            continue

        # Gửi embed
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": message,
                    "color": color_int,
                    "footer": {"text": "Thông báo từ Bot Owner"},
                }]
            }
            mr = _discord_api(
                "POST",
                f"/channels/{channel_id}/messages",
                json=payload,
                timeout=8,
            )
            if mr is not None and mr.status_code in (200, 201):
                success_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1

    flash(
        f"📢 Đã gửi thông báo: ✅ {success_count} server thành công"
        + (f", ❌ {fail_count} thất bại." if fail_count else "."),
        "success" if success_count else "error",
    )
    return redirect(url_for("admin.admin_panel"))

@bp.route("/admin/system/stepup", methods=["POST"])
@limiter.limit("5/minute")
@owner_required
def admin_system_stepup():
    """Xác thực mật khẩu cấp cao (Step-Up Auth), mở khóa 15 phút."""
    data = request.get_json(silent=True) or request.form or {}
    password = data.get("password", "")
    admin_pass = getattr(config, "ADMIN_PASSWORD", None)

    # Trước đây nhánh này CẤP quyền step-up khi chưa cấu hình mật khẩu — tức là chính
    # nơi dùng để xác thực lại là chỗ bỏ qua xác thực.
    if not _admin_password_ready():
        _audit_admin_action("stepup bị chặn", "admin_stepup", "ADMIN_PASSWORD chưa đặt hoặc quá ngắn")
        return jsonify({
            "ok": False,
            "error": "stepup_unconfigured",
            "message": (
                "🔒 ADMIN_PASSWORD chưa được đặt hoặc ngắn hơn "
                f"{getattr(config, 'ADMIN_PASSWORD_MIN_LENGTH', 16)} ký tự."
            ),
        }), 503

    if secrets.compare_digest(str(password), str(admin_pass)):
        session["stepup_auth_until"] = _time.time() + 900
        _audit_admin_action("stepup thành công", "admin_stepup", "session mở 15 phút")
        return jsonify({"ok": True, "message": "✅ Xác thực thành công! Quyền quản trị mở trong 15 phút."}), 200

    _audit_admin_action("stepup thất bại", "admin_stepup", "sai mật khẩu")
    return jsonify({"ok": False, "message": "❌ Mật khẩu quản trị không chính xác!"}), 403

@bp.route("/admin/system/terminal", methods=["POST"])
@limiter.limit("30/minute")
@owner_required
@stepup_required
def admin_system_terminal():
    """Chạy lệnh shell terminal trực tiếp trên máy chủ host (Termux / Linux / Windows)."""
    data = request.get_json(silent=True) or request.form or {}
    command = data.get("command", "").strip()

    if not command:
        return jsonify({"ok": False, "output": "⚠️ Lệnh không được để trống!", "returncode": 1}), 200

    # Audit trail: ghi lại mọi lệnh được đẩy vào shell của điện thoại/máy chủ.
    _audit_admin_action(f"$ {command}", "admin_terminal")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    current_cwd = session.get("term_cwd")
    if not current_cwd or not os.path.isdir(current_cwd):
        current_cwd = base_dir

    # Handle directory navigation (cd command)
    if command == "cd" or command.startswith("cd ") or command.startswith("cd\t"):
        target = command[2:].strip()
        if not target or target in ("~", "/"):
            new_dir = base_dir
        else:
            new_dir = os.path.abspath(os.path.join(current_cwd, target))

        if os.path.isdir(new_dir):
            session["term_cwd"] = new_dir
            return jsonify({
                "ok": True,
                "command": command,
                "output": f"📂 Đã chuyển thư mục làm việc sang: {new_dir}",
                "cwd": new_dir,
                "returncode": 0
            }), 200
        else:
            return jsonify({
                "ok": False,
                "command": command,
                "output": f"bash: cd: {target}: No such file or directory",
                "cwd": current_cwd,
                "returncode": 1
            }), 200

    # Block interactive TTY programs that hang or crash non-interactive HTTP subprocesses
    interactive_cmds = ("nano", "vim", "vi", "top", "htop", "less", "more", "gdb")
    cmd_words = command.split()
    first_cmd = cmd_words[0].lower() if cmd_words else ""
    if first_cmd in interactive_cmds or command.strip() == "python":
        target_file = cmd_words[1] if len(cmd_words) > 1 else ".env"
        return jsonify({
            "ok": False,
            "command": command,
            "output": f"⚠️ '{first_cmd}' là trình chỉnh sửa / chương trình tương tác TTY nên không thể chạy trực tiếp trong Web Console.\n💡 Gợi ý: Dùng lệnh 'cat {target_file}' để xem nội dung file trên màn hình terminal!",
            "cwd": current_cwd,
            "returncode": 1
        }), 200

    # Special background handling for long-running / restart commands from Web Console
    cmd_clean = command.strip().lower()
    if cmd_clean in ("restart", "reset", "python main.py --restart", "python3 main.py --restart", f"{sys.executable} main.py --restart".lower()):
        main_py = os.path.join(base_dir, "main.py")
        if os.name == "nt":
            subprocess.Popen([sys.executable, main_py, "--restart"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(f"sleep 1 && python main.py --restart > {os.path.join(base_dir, 'data', 'bot.log')} 2>&1 &", shell=True, cwd=base_dir)
        return jsonify({
            "ok": True,
            "command": command,
            "output": "🔄 Đã gửi lệnh khởi động lại hệ thống thành công! Bot và Dashboard đang khởi động lại...",
            "cwd": current_cwd,
            "returncode": 0
        }), 200

    if cmd_clean in ("start", "python main.py", "python3 main.py", "python main.py --start", "python3 main.py --start"):
        main_py = os.path.join(base_dir, "main.py")
        if os.name == "nt":
            subprocess.Popen([sys.executable, main_py, "--start"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(f"python main.py --start > {os.path.join(base_dir, 'data', 'bot.log')} 2>&1 &", shell=True, cwd=base_dir)
        return jsonify({
            "ok": True,
            "command": command,
            "output": "🚀 Đã khởi động hệ thống trong nền! Gõ 'python main.py --status' sau 3 giây để kiểm tra.",
            "cwd": current_cwd,
            "returncode": 0
        }), 200

    if cmd_clean in ("bot", "python main.py --bot", "python3 main.py --bot"):
        bot_log = os.path.join(base_dir, "data", "bot.log")
        watchdog_script = os.path.join(base_dir, "scripts", "watchdog.sh")
        if os.name == "nt":
            subprocess.Popen([sys.executable, os.path.join(base_dir, "main.py"), "--bot"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            if os.path.exists(watchdog_script):
                subprocess.Popen(f"nohup bash {watchdog_script} > {bot_log} 2>&1 &", shell=True, cwd=base_dir)
            else:
                subprocess.Popen(f"nohup python main.py --bot > {bot_log} 2>&1 &", shell=True, cwd=base_dir)
        return jsonify({
            "ok": True,
            "command": command,
            "output": "🤖 Đã khởi động Bot Discord trong nền! Gõ 'python main.py --status' sau 3 giây để kiểm tra.",
            "cwd": current_cwd,
            "returncode": 0
        }), 200

    # Shortcut aliases
    if command.lower() in ("status", "info"):
        command = f"{sys.executable} main.py --status"
    elif command.lower() in ("pull", "update"):
        command = "git pull"

    # Determine shell executable (Termux/Linux requires explicit bash/sh path)
    exec_shell = None
    if os.name != "nt":
        exec_shell = shutil.which("bash") or shutil.which("sh") or "/data/data/com.termux/files/usr/bin/bash" or "/bin/sh"

    try:
        res = subprocess.run(
            command,
            shell=True,
            executable=exec_shell,
            capture_output=True,
            text=True,
            cwd=current_cwd,
            timeout=30,
            encoding="utf-8",
            errors="replace"
        )
        output = (res.stdout or "").replace("\r\n", "\n")
        if res.stderr:
            output += ("\n" if output else "") + res.stderr.replace("\r\n", "\n")
        if not output.strip():
            output = "(Lệnh đã thực thi thành công, không có output trả về)"

        if res.returncode not in (0, None):
            _audit_admin_action(f"$ {command}", "admin_terminal", f"exit={res.returncode}")

        return jsonify({
            "ok": True,
            "command": command,
            "output": output,
            "cwd": current_cwd,
            "returncode": res.returncode
        }), 200
    except subprocess.TimeoutExpired:
        _audit_admin_action(f"$ {command}", "admin_terminal", "timeout 30s")
        return jsonify({
            "ok": False,
            "command": command,
            "output": "⏱️ Lệnh thực thi quá thời hạn cho phép (Timeout 30s)!",
            "cwd": current_cwd,
            "returncode": -1
        }), 200
    except Exception as e:
        err_msg = str(e)
        _audit_admin_action(f"$ {command}", "admin_terminal", f"error: {err_msg[:200]}")
        return jsonify({
            "ok": False,
            "command": command,
            "output": f"❌ Lỗi thực thi lệnh: {err_msg}",
            "cwd": current_cwd,
            "returncode": -1
        }), 200

@bp.route("/admin/system/git-pull", methods=["POST"])
@limiter.limit("5/minute")
@owner_required
@stepup_required
def admin_system_git_pull():
    """Cập nhật code mới nhất từ Git (git fetch + reset --hard).

    P0.5: trước khi `reset --hard`, cất mọi thay đổi cục bộ vào `git stash` để
    không xoá trắng chỉnh sửa trên điện thoại. Khôi phục bằng `git stash pop`.
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exec_shell = None if os.name == "nt" else (shutil.which("bash") or shutil.which("sh"))
        stash_label = f"pre-pull-{int(_time.time())}"
        pull_cmd = (
            "git fetch origin main && "
            f"git stash push -m {shlex.quote(stash_label)} ; "
            "git reset --hard origin/main && "
            "git stash list --pretty=%gd\\ %s | head -n 5"
        )
        _audit_admin_action("git pull", "admin_git_pull", stash_label)
        res = subprocess.run(
            pull_cmd,
            shell=True,
            executable=exec_shell,
            capture_output=True,
            text=True,
            cwd=base_dir,
            timeout=30,
            encoding="utf-8",
            errors="replace"
        )
        output = (res.stdout or "").replace("\r\n", "\n")
        if res.stderr:
            output += ("\n" if output else "") + res.stderr.replace("\r\n", "\n")

        note = (
            f"\n\nℹ️ Thay đổi cục bộ (nếu có) đã được cất vào stash: {stash_label}\n"
            "   Khôi phục bằng lệnh: git stash pop"
        )
        return jsonify({
            "ok": True,
            "output": (output or "Git pull thành công!") + note,
            "returncode": res.returncode
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "output": f"❌ Lỗi thực thi git pull: {e}", "returncode": -1}), 200

@bp.route("/admin/system/restart", methods=["POST"])
@limiter.limit("10/minute")
@owner_required
@stepup_required
def admin_system_restart():
    """Khởi động lại toàn bộ hệ thống Bot & Dashboard."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_py = os.path.join(base_dir, "main.py")

        if os.name == "nt":
            subprocess.Popen([sys.executable, main_py, "--restart"], cwd=base_dir, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([sys.executable, main_py, "--restart"], cwd=base_dir, start_new_session=True)

        _audit_admin_action("restart hệ thống", "admin_restart")
        return jsonify({
            "ok": True,
            "message": "🔄 Đã gửi lệnh khởi động lại hệ thống! Bot và Dashboard đang khởi động lại..."
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "message": f"❌ Lỗi khởi động lại: {e}"}), 200
