"""
music.py — Route trang nhạc & quản lý playlist của dashboard.
"""

import os
import sys

# File nằm ở dashboard/blueprints/ → cần 3 cấp dirname để tới repo root
_V2_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _V2_DIR)
sys.path.insert(0, os.path.join(_V2_DIR, "bot"))  # cho commands_data, card_generator, checks...

import sqlite3

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import database as db
from dashboard.web_helpers import _server_ctx, fetch_track_info_simple, guild_access_required

bp = Blueprint("music", __name__)


@bp.route("/dashboard/<guild_id>/music")
@guild_access_required
def server_music(guild_id: str):
    import shutil
    try:
        import davey
        has_davey = True
    except ImportError:
        has_davey = False

    has_ffmpeg = shutil.which("ffmpeg") is not None
    playlists = db.get_playlists(guild_id)
    # Top bài hát được nghe nhiều nhất (nguồn: guild_stats event_type='music_play')
    top_songs = db.get_top_played_songs(guild_id, limit=10)
    
    grouped_playlists = {}
    for pl in playlists:
        c_id = pl.get("creator_id") or "Unknown"
        c_name = pl.get("creator_name") or "Hệ thống"
        if c_id not in grouped_playlists:
            grouped_playlists[c_id] = {"name": c_name, "playlists": []}
        grouped_playlists[c_id]["playlists"].append(pl)

    return render_template("music.html", **_server_ctx(
        guild_id, "music",
        has_davey=has_davey,
        has_ffmpeg=has_ffmpeg,
        grouped_playlists=grouped_playlists,
        top_songs=top_songs,
    ))

@bp.route("/dashboard/<guild_id>/music/playlist/create", methods=["POST"])
@guild_access_required
def create_playlist_route(guild_id: str):
    name = request.form.get("playlist_name", "").strip()
    if not name:
        flash("❌ Tên playlist không được để trống!", "error")
    else:
        user = session.get("user", {})
        creator_id = user.get("id", "")
        creator_name = user.get("global_name") or user.get("username", "Unknown")
        db.create_playlist(guild_id, name, creator_id, creator_name)
        flash(f"✅ Đã tạo playlist '{name}'!", "success")
    return redirect(url_for("music.server_music", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/music/playlist/<int:playlist_id>/delete", methods=["POST"])
@guild_access_required
def delete_playlist_route(guild_id: str, playlist_id: int):
    playlist = db.get_playlist(playlist_id)
    user = session.get("user", {})
    if playlist and playlist.get("guild_id") == guild_id:
        if playlist.get("creator_id") and playlist.get("creator_id") != user.get("id"):
            flash("❌ Bạn không có quyền xóa playlist của người khác!", "error")
        else:
            db.delete_playlist(playlist_id, guild_id)
            flash(f"✅ Đã xóa playlist '{playlist.get('name')}'!", "success")
    else:
        flash("❌ Không tìm thấy playlist!", "error")
    return redirect(url_for("music.server_music", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/music/playlist/<int:playlist_id>/add", methods=["POST"])
@guild_access_required
def add_track_route(guild_id: str, playlist_id: int):
    playlist = db.get_playlist(playlist_id)
    user = session.get("user", {})
    if not playlist or playlist.get("guild_id") != guild_id:
        flash("❌ Không tìm thấy playlist!", "error")
    elif playlist.get("creator_id") and playlist.get("creator_id") != user.get("id"):
        flash("❌ Bạn không có quyền thêm bài hát vào playlist của người khác!", "error")
        return redirect(url_for("music.server_music", guild_id=guild_id))
    
    query = request.form.get("track_query", "").strip()
    if not query:
        flash("❌ Vui lòng nhập link hoặc tên bài hát!", "error")
    else:
        track_info = fetch_track_info_simple(query)
        db.add_track_to_playlist(playlist_id, track_info)
        flash(f"✅ Đã thêm '{track_info['title']}' vào playlist!", "success")
    return redirect(url_for("music.server_music", guild_id=guild_id))

@bp.route("/dashboard/<guild_id>/music/playlist/track/<int:track_id>/delete", methods=["POST"])
@guild_access_required
def delete_track_route(guild_id: str, track_id: int):
    # Kiểm ownership: track phải thuộc playlist của ĐÚNG guild này (chống xóa chéo server)
    playlist = db.get_playlist_of_track(track_id)
    user = session.get("user", {})
    if not playlist or str(playlist.get("guild_id")) != str(guild_id):
        flash("❌ Không tìm thấy bài hát trong server này!", "error")
        return redirect(url_for("music.server_music", guild_id=guild_id))
    if playlist.get("creator_id") and str(playlist.get("creator_id")) != str(user.get("id")):
        flash("❌ Bạn không có quyền xóa bài trong playlist của người khác!", "error")
        return redirect(url_for("music.server_music", guild_id=guild_id))
    db.delete_track_from_playlist(track_id)
    flash("✅ Đã xóa bài hát khỏi playlist!", "success")
    return redirect(url_for("music.server_music", guild_id=guild_id))
