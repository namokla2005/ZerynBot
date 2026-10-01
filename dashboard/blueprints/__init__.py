"""
blueprints — Các nhóm route của dashboard (Giai đoạn 3.2).

Mỗi module tạo một `Blueprint` KHÔNG có url_prefix (giữ nguyên URL tuyệt đối như
trước khi tách) để không phải sửa đường dẫn:

  public.py   trang công khai + OAuth (/, /login, /callback, /tos, /health, /docs)
  guild.py    trang quản lý server (/dashboard/<guild_id>/...)
  music.py    trang nhạc + playlist (/dashboard/<guild_id>/music/...)
  support.py  trang hỗ trợ + API support
  admin.py    khu vực bot owner (/admin, /api/admin/...)

Endpoint sau khi tách có dạng `<blueprint>.<tên_hàm>`, ví dụ `guild.home`,
`public.login`, `admin.admin_panel`.
"""