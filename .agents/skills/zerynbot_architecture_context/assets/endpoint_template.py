"""
Template chuẩn tạo Route & AJAX JSON API Endpoint cho Flask Dashboard
Bao gồm:
- Xác thực @login_required & @guild_admin_required
- Kiểm tra quyền & Tham số đầu vào an toàn
- Truy cập cơ sở dữ liệu đồng bộ (sqlite3)
- Định dạng phản hồi JSON chuẩn (success, message, data, error)
"""
from flask import Blueprint, request, jsonify, render_template, session, abort
import database as db
import config
from dashboard.auth import login_required, guild_admin_required
from cache import cache

# Blueprint cho API hoặc Module
example_bp = Blueprint("example_module", __name__)


@example_bp.route("/server/<guild_id>/example", methods=["GET"])
@login_required
@guild_admin_required
def example_page(guild_id: str):
    """Trang giao diện quản lý module trên Dashboard."""
    settings = db.get_guild_settings(guild_id)
    is_enabled = db.is_module_enabled(guild_id, "example_module")
    
    return render_template(
        "server_example.html",
        guild_id=guild_id,
        settings=settings,
        is_enabled=is_enabled,
        active_tab="example"
    )


@example_bp.route("/api/server/<guild_id>/example/update", methods=["POST"])
@login_required
@guild_admin_required
def update_example_settings_api(guild_id: str):
    """API AJAX cập nhật cấu hình module."""
    data = request.get_json(silent=True) or {}
    
    field_value = data.get("field_value", "").strip()
    if len(field_value) > 200:
        return jsonify({
            "success": False,
            "error": "Giá trị nhập vào quá dài (tối đa 200 ký tự).",
            "code": "INVALID_LENGTH"
        }), 400

    try:
        # Cập nhật CSDL
        # db.update_example_setting(guild_id, field_value)
        
        # BẮT BUỘC: Xóa cache RAM để bot và web cập nhật ngay
        cache.delete(f"settings:{guild_id}")
        
        return jsonify({
            "success": True,
            "message": "Cập nhật cài đặt thành công!",
            "data": {
                "field_value": field_value
            }
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Lỗi hệ thống: {str(e)}",
            "code": "INTERNAL_ERROR"
        }), 500
