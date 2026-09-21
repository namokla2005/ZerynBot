# -*- coding: utf-8 -*-
"""
Central Registry for all 110 commands across 17 categories in ZerynBot V2.
Shared by Web Dashboard and Discord Bot Help Command (/help [command]).
"""

_COMMANDS_DATA = [
    {
        "category": "Tổng quát",
        "icon": "⚙️",
        "commands": [
            {
                "name": "help", "emoji": "📖",
                "desc": "Xem danh sách tất cả lệnh của bot",
                "usage": "/help", "example": "/help",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📖 Danh sách lệnh",
                    "desc": "**Tổng quát:** /help, /ping, /membercount<br>"
                            "**Info:** /serverinfo, /userinfo, /avatar<br>"
                            "**Music:** /play, /search, /stop, /loop..."
                }
            },
            {
                "name": "ping", "emoji": "🏓",
                "desc": "Kiểm tra độ trễ (latency) của bot",
                "usage": "/ping", "example": "/ping",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🏓 Pong!",
                    "desc": "**Độ trễ:** `42ms`<br>**API Discord:** `38ms`"
                }
            },
            {
                "name": "membercount", "emoji": "👥",
                "desc": "Xem tổng số thành viên trong server",
                "usage": "/membercount", "example": "/membercount",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "👥 Thành viên server",
                    "desc": "**Tổng cộng:** `142`<br>**Đang online:** `38`<br>**Bot:** `4`"
                }
            },
            {
                "name": "poll", "emoji": "📊",
                "desc": "Tạo một cuộc bình chọn nhanh",
                "usage": "/poll [câu hỏi]", "example": "/poll Tối nay ăn gì?",
                "args": [{"name": "question", "type": "Text", "required": True, "desc": "Câu hỏi bình chọn"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📊 Bình chọn",
                    "desc": "**Tối nay ăn gì?**<br><br>Thả cảm xúc bên dưới để bình chọn!"
                }
            },
            {
                "name": "roll", "emoji": "🎲",
                "desc": "Tung xúc xắc (ngẫu nhiên từ 1 đến số chỉ định)",
                "usage": "/roll [số]", "example": "/roll 100",
                "args": [{"name": "max_number", "type": "Number", "required": False, "desc": "Số lớn nhất (mặc định: 100)"}],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "🎲 Tung xúc xắc",
                    "desc": "Bạn đã tung ra số: **42** (1 - 100)"
                }
            },
            {
                "name": "choose", "emoji": "🤔",
                "desc": "Bot sẽ chọn ngẫu nhiên giúp bạn một phương án",
                "usage": "/choose [các lựa chọn]", "example": "/choose Ăn cơm, Ăn phở",
                "args": [{"name": "options", "type": "Text", "required": True, "desc": "Các phương án (cách nhau bởi dấu phẩy)"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🤔 Lựa chọn ngẫu nhiên",
                    "desc": "Giữa các phương án: `Ăn cơm, Ăn phở`<br><br>🎯 Mình chọn: **Ăn phở**"
                }
            },
            {
                "name": "embed", "emoji": "💬",
                "desc": "Gửi embed đã lưu từ Web Dashboard vào kênh hiện tại",
                "usage": "/embed [tên]", "example": "/embed thong_bao",
                "args": [{"name": "name", "type": "Text", "required": True, "desc": "Tên embed đã lưu trên Web Dashboard"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "💬 Embed Thông Báo",
                    "desc": "Nội dung thông báo embed được gửi trực tiếp từ Web Dashboard Studio!"
                }
            },
            {
                "name": "remindme", "emoji": "⏰",
                "desc": "Đặt lịch nhắc nhở bạn sau một khoảng thời gian (hỗ trợ 10m, 1h30m, 2d, 20:30)",
                "usage": "/remindme [thời gian] [nội dung]", "example": "/remindme time:10m reason:Uống nước",
                "args": [
                    {"name": "time", "type": "Text", "required": True, "desc": "Thời gian nhắc (VD: 10m, 1h, 20:30)"},
                    {"name": "reason", "type": "Text", "required": True, "desc": "Nội dung cần nhắc"},
                    {"name": "dm", "type": "Boolean", "required": False, "desc": "Gửi tin nhắn riêng qua DM"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "⏰ Đã Đặt Lịch Nhắc Nhở Thành Công!",
                    "desc": "📝 **Nội dung:** Uống nước<br>⏳ **Thời gian:** 10 phút nữa<br>📍 **Nơi nhận:** 💬 #general"
                }
            },
            {
                "name": "reminders", "emoji": "📋",
                "desc": "Xem danh sách các lời nhắc hẹn giờ đang chờ của bạn",
                "usage": "/reminders", "example": "/reminders",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "📋 Danh Sách Nhắc Nhở",
                    "desc": "**`#1`** • trong 10 phút nữa<br>└ 📝 *Uống nước*"
                }
            },
            {
                "name": "delreminder", "emoji": "🗑️",
                "desc": "Hủy một lời nhắc hẹn giờ theo ID",
                "usage": "/delreminder [id]", "example": "/delreminder reminder_id:1",
                "args": [{"name": "reminder_id", "type": "Number", "required": True, "desc": "ID của lời nhắc (xem qua /reminders)"}],
                "preview": {
                    "type": "text",
                    "desc": "✅ Đã hủy lời nhắc `#1` thành công!"
                }
            }
        ]
    },
    {
        "category": "Reaction Roles",
        "icon": "✨",
        "commands": [
            {
                "name": "reactionroles", "emoji": "✨",
                "desc": "Tính năng này không có lệnh Slash. Vui lòng sử dụng Web Dashboard để thiết lập Panel và Emoji.",
                "usage": "(Dashboard)", "example": "Dashboard",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "✨ Reaction Roles",
                    "desc": "Tính năng Reaction Roles hoàn toàn được quản lý tự động thông qua Dashboard của bot."
                }
            }
        ]
    },
    {
        "category": "Auto Roles",
        "icon": "🪪",
        "commands": [
            {
                "name": "autorole show", "emoji": "🪪",
                "desc": "Xem cấu hình Auto Roles hiện tại",
                "usage": "/autorole show", "example": "/autorole show",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "⚙️ Cấu hình Auto Roles",
                    "desc": "**Trạng thái:** ✅ Đã bật<br>**Roles cho Thành viên:** @Member<br>**Roles cho Bot:** @Bot"
                }
            }
        ]
    },
    {
        "category": "Automods",
        "icon": "🛡️",
        "commands": [
            {
                "name": "automods show", "emoji": "🛡️",
                "desc": "Xem cấu hình Automods hiện tại",
                "usage": "/automods show", "example": "/automods show",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🛡️ Automods — My Server",
                    "desc": "**Trạng thái:** 🟢 Đang Hoạt Động<br>*(Để tuỳ chỉnh chi tiết, vui lòng dùng Dashboard)*"
                }
            },
            {
                "name": "automods raidlock", "emoji": "🔒",
                "desc": "Khoá server (lockdown) khi có raid/nuke",
                "usage": "/automods raidlock", "example": "/automods raidlock",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#ED4245", "title": "🔒 Server Lockdown",
                    "desc": "Đã chặn @everyone gửi tin trên toàn server.<br>Dùng `/automods raidunlock` để mở lại."
                }
            },
            {
                "name": "automods raidunlock", "emoji": "🔓",
                "desc": "Mở khoá server sau lockdown, khôi phục overwrites",
                "usage": "/automods raidunlock", "example": "/automods raidunlock",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🔓 Server Mở Lại",
                    "desc": "Đã khôi phục quyền gửi tin cho @everyone."
                }
            }
        ]
    },
    {
        "category": "Verify Gate",
        "icon": "🔐",
        "commands": [
            {
                "name": "verify status", "emoji": "🔐",
                "desc": "Xem trạng thái Verify Gate",
                "usage": "/verify status", "example": "/verify status",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🔐 Verify Gate",
                    "desc": "**Trạng thái:** 🟢 BẬT (hard gate)<br>**Kênh xác thực:** #xac-thuc<br>**Vai trò đã xác thực:** @Member"
                }
            },
            {
                "name": "verify enable", "emoji": "✅",
                "desc": "BẬT Verify Gate (hard gate)",
                "usage": "/verify enable", "example": "/verify enable",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "✅ Verify Gate Bật",
                    "desc": "Thành viên mới sẽ chỉ thấy kênh xác thực."
                }
            },
            {
                "name": "verify disable", "emoji": "🔴",
                "desc": "TẮT Verify Gate và khôi phục overrides",
                "usage": "/verify disable", "example": "/verify disable",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#ed4245", "title": "🔴 Verify Gate Tắt",
                    "desc": "Đã khôi phục overrides cho các kênh."
                }
            },
            {
                "name": "verify channel", "emoji": "📌",
                "desc": "Đặt kênh xác thực",
                "usage": "/verify channel #kênh", "example": "/verify channel #xac-thuc",
                "args": [{"name": "channel", "type": "Channel", "required": True, "desc": "Kênh dùng làm kênh xác thực"}],
                "preview": {"type": "embed", "color": "#5865f2", "title": "📌 Kênh xác thực", "desc": "✅ Đã đặt kênh xác thực: #xac-thuc"}
            },
            {
                "name": "verify role", "emoji": "🎖️",
                "desc": "Đặt vai trò thành viên đã xác thực",
                "usage": "/verify role @Member", "example": "/verify role @Member",
                "args": [{"name": "role", "type": "Role", "required": True, "desc": "Vai trò được gán sau khi xác thực"}],
                "preview": {"type": "embed", "color": "#5865f2", "title": "🎖️ Vai trò xác thực", "desc": "✅ Đã đặt vai trò xác thực: @Member"}
            },
            {
                "name": "verify panel", "emoji": "📢",
                "desc": "Gửi bảng xác thực (nút bấm) vào kênh xác thực",
                "usage": "/verify panel", "example": "/verify panel",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🔐 Xác thực thành viên",
                    "desc": "Chào mừng! Bấm nút bên dưới để xác thực.<br>**[✅ Tôi đã đọc nội quy & Xác thực]**"
                }
            },
            {
                "name": "verify text", "emoji": "💬",
                "desc": "Đặt nội dung thông điệp xác thực",
                "usage": "/verify text (nội dung)", "example": "/verify text Chào mừng!",
                "args": [{"name": "content", "type": "String", "required": True, "desc": "Nội dung (hỗ trợ {server})"}],
                "preview": {"type": "embed", "color": "#5865f2", "title": "💬 Nội dung", "desc": "✅ Đã đặt nội dung xác thực."}
            },
            {
                "name": "verify button", "emoji": "🔘",
                "desc": "Đặt nhãn nút xác thực",
                "usage": "/verify button (nhãn)", "example": "/verify button Tôi đã đọc nội quy",
                "args": [{"name": "label", "type": "String", "required": True, "desc": "Chữ hiển thị trên nút"}],
                "preview": {"type": "embed", "color": "#5865f2", "title": "🔘 Nhãn nút", "desc": "✅ Đã đặt nhãn nút: **Tôi đã đọc nội quy**"}
            },
            {
                "name": "verify hide", "emoji": "👁️",
                "desc": "Bật/tắt chế độ ẩn kênh (hard gate)",
                "usage": "/verify hide on|off", "example": "/verify hide on",
                "args": [{"name": "state", "type": "String", "required": True, "desc": "on/off"}],
                "preview": {"type": "embed", "color": "#5865f2", "title": "👁️ Chế độ ẩn kênh", "desc": "✅ Đã bật chế độ hard gate."}
            }
        ]
    },
    {
        "category": "Leveling",
        "icon": "🌟",
        "commands": [
            {
                "name": "rank", "emoji": "🌟",
                "desc": "Xem cấp độ và hạng của bạn hoặc người khác",
                "usage": "/rank [người_dùng]", "example": "/rank @Nam",
                "args": [{"name": "member", "type": "Mention", "required": False, "desc": "Người dùng cần xem (mặc định: bạn)"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "Cấp độ của Nam",
                    "desc": "**Rank:** #1 | **Level:** 5\n**XP:** 450 / 550\n`[██████████░░░░░░░░░░]` 80%"
                }
            },
            {
                "name": "leaderboard", "emoji": "🏆",
                "desc": "Xem bảng xếp hạng cấp độ của server",
                "usage": "/leaderboard", "example": "/leaderboard",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🏆 Bảng xếp hạng",
                    "desc": "🥇 **#1** | @Nam • **Lvl 5** (450 XP)\n🥈 **#2** | @User • **Lvl 3** (200 XP)"
                }
            },
            {
                "name": "xp set", "emoji": "⚙️",
                "desc": "Thiết lập điểm kinh nghiệm cho một thành viên",
                "usage": "/xp set [người_dùng] [xp]", "example": "/xp set @Nam 1000",
                "args": [
                    {"name": "member", "type": "Mention", "required": True, "desc": "Người dùng"},
                    {"name": "amount", "type": "Number", "required": True, "desc": "Số điểm XP mới"}
                ],
                "preview": {
                    "type": "text", "content": "✅ Đã đặt XP của @Nam thành **1000** (Cấp độ: **10**)."
                }
            },
            {
                "name": "xp reset", "emoji": "🗑️",
                "desc": "Xóa toàn bộ điểm kinh nghiệm của một thành viên",
                "usage": "/xp reset [người_dùng]", "example": "/xp reset @Nam",
                "args": [
                    {"name": "member", "type": "Mention", "required": True, "desc": "Người dùng"}
                ],
                "preview": {
                    "type": "text", "content": "✅ Đã xóa toàn bộ XP của @Nam."
                }
            }
        ]
    },
    {
        "category": "Giveaways",
        "icon": "🎁",
        "commands": [
            {
                "name": "giveaway start", "emoji": "🎉",
                "desc": "Tạo một Giveaway mới",
                "usage": "/giveaway start [thời_gian] [người_thắng] [giải_thưởng]", "example": "/giveaway start 1h 2 Nitro Classic",
                "args": [
                    {"name": "duration", "type": "String", "required": True, "desc": "Thời gian (vd: 1m, 1h, 1d)"},
                    {"name": "winners", "type": "Number", "required": True, "desc": "Số người thắng"},
                    {"name": "prize", "type": "String", "required": True, "desc": "Phần thưởng"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🎉 GIVEAWAY: Nitro Classic",
                    "desc": "Bấm vào nút **🎉 Tham gia** bên dưới để nhận cơ hội trúng giải nhé!\n\n**🎁 Phần thưởng:** Nitro Classic\n**🏆 Số người thắng:** 2\n**👥 Số người tham gia:** 15 người\n**⏰ Kết thúc:** trong 1 giờ"
                }
            },
            {
                "name": "giveaway reroll", "emoji": "🎲",
                "desc": "Chọn lại người thắng mới",
                "usage": "/giveaway reroll [message_id]", "example": "/giveaway reroll 1234567890",
                "args": [
                    {"name": "message_id", "type": "String", "required": True, "desc": "ID của tin nhắn Giveaway"}
                ],
                "preview": {
                    "type": "text", "content": "🎉 **REROLL**: Chúc mừng @Nam đã trúng giải **Nitro Classic**!"
                }
            },
            {
                "name": "giveaway end", "emoji": "🛑",
                "desc": "Kết thúc sớm một Giveaway",
                "usage": "/giveaway end [message_id]", "example": "/giveaway end 1234567890",
                "args": [
                    {"name": "message_id", "type": "String", "required": True, "desc": "ID của tin nhắn Giveaway"}
                ],
                "preview": {
                    "type": "text", "content": "✅ Đang tiến hành quay số và kết thúc Giveaway..."
                }
            }
        ]
    },
    {
        "category": "Tickets",
        "icon": "🎫",
        "commands": [
            {
                "name": "tickets", "emoji": "🎫",
                "desc": "Tính năng này không có lệnh Slash. Vui lòng sử dụng Web Dashboard để tạo Panel hỗ trợ.",
                "usage": "(Dashboard)", "example": "Dashboard",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🎫 Ticket System",
                    "desc": "Hệ thống Ticket được quản lý tự động thông qua Dashboard của bot."
                }
            }
        ]
    },
    {
        "category": "Thông tin",
        "icon": "ℹ️",
        "commands": [
            {
                "name": "serverinfo", "emoji": "🏠",
                "desc": "Hiển thị thông tin chi tiết về server",
                "usage": "/serverinfo", "example": "/serverinfo",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🏠 Server Info",
                    "desc": "Thông tin về server hiện tại",
                    "fields": [
                        {"name": "📋 Tên", "value": "My Server"},
                        {"name": "👑 Chủ sở hữu", "value": "@Admin"},
                        {"name": "👥 Thành viên", "value": "142"},
                        {"name": "📅 Ngày tạo", "value": "01/01/2023"},
                    ]
                }
            },
            {
                "name": "userinfo", "emoji": "👤",
                "desc": "Xem thông tin của một thành viên",
                "usage": "/userinfo [@member]", "example": "/userinfo @Nam",
                "args": [
                    {"name": "member", "type": "Mention", "required": False,
                     "desc": "Thành viên cần xem (mặc định: bạn)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "👤 User Info",
                    "desc": "Thông tin chi tiết của thành viên",
                    "fields": [
                        {"name": "🏷️ Username", "value": "Nam#0001"},
                        {"name": "📅 Tham gia", "value": "15/06/2023"},
                        {"name": "🎭 Roles", "value": "@Admin, @Member"},
                        {"name": "🆔 ID", "value": "123456789"},
                    ]
                }
            },
            {
                "name": "avatar", "emoji": "🖼️",
                "desc": "Xem avatar của một thành viên với đường link tải về",
                "usage": "/avatar [@member]", "example": "/avatar @Nam",
                "args": [
                    {"name": "member", "type": "Mention", "required": False,
                     "desc": "Thành viên cần xem avatar (mặc định: bạn)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🖼️ Avatar của Nam",
                    "desc": "[PNG](https://...) | [JPG](https://...) | [WebP](https://...)",
                    "image": "https://cdn.discordapp.com/embed/avatars/0.png"
                }
            },
            {
                "name": "botinfo", "emoji": "🤖",
                "desc": "Hiển thị thông số kỹ thuật và trạng thái của bot",
                "usage": "/botinfo", "example": "/botinfo",
                "args": [],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🤖 Thông tin Bot",
                    "desc": "**⚙️ CPU:** `2.5%` | **🗄️ RAM:** `45.2 MB`<br>**🐍 Python:** `3.10.0` | **🏰 Servers:** `5`"
                }
            },
            {
                "name": "roleinfo", "emoji": "🎭",
                "desc": "Hiển thị thông tin về một Role",
                "usage": "/roleinfo [@role]", "example": "/roleinfo @Admin",
                "args": [{"name": "role", "type": "Mention", "required": True, "desc": "Role cần xem thông tin"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "🎭 Thông tin Role: Admin",
                    "desc": "**🪪 ID:** `123456789`<br>**👥 Số người có:** `5`<br>**📌 Có thể tag:** ✅"
                }
            },
            {
                "name": "channelinfo", "emoji": "📺",
                "desc": "Hiển thị thông tin về một Kênh",
                "usage": "/channelinfo [#channel]", "example": "/channelinfo #general",
                "args": [{"name": "channel", "type": "Mention", "required": False, "desc": "Kênh cần xem thông tin (mặc định: kênh hiện tại)"}],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📺 Thông tin Kênh: general",
                    "desc": "**🪪 ID:** `987654321`<br>**📂 Thể loại:** `text`<br>**🔞 NSFW:** ❌"
                }
            }
        ]
    },
    {
        "category": "Music 🎵",
        "icon": "🎵",
        "commands": [
            {
                "name": "play", "emoji": "▶️",
                "desc": "Phát nhạc từ YouTube. Nhập tên bài hoặc link trực tiếp",
                "usage": "/play [tên bài hoặc link]",
                "example": "/play Đen - Bố Già  |  /play https://youtu.be/...",
                "args": [
                    {"name": "query", "type": "Text", "required": True,
                     "desc": "Tên bài hát để tìm kiếm, hoặc link YouTube"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🎵 Đang phát",
                    "desc": "[Đen - Bố Già](https://youtu.be/...)",
                    "fields": [
                        {"name": "⏱ Thời lượng", "value": "4:32"},
                        {"name": "📺 Kênh", "value": "Đen Vâu"},
                    ]
                }
            },
            {
                "name": "search", "emoji": "🔍",
                "desc": "Tìm kiếm nhạc và hiển thị 5 kết quả để chọn",
                "usage": "/search [tên bài]", "example": "/search Sơn Tùng MTP",
                "args": [
                    {"name": "query", "type": "Text", "required": True,
                     "desc": "Tên bài hát cần tìm kiếm"}
                ],
                "preview": {
                    "type": "select",
                    "desc": "1️⃣ **Hãy Trao Cho Anh** — `4:12`<br>"
                            "2️⃣ **Muộn Rồi Mà Sao Còn** — `4:01`<br>"
                            "3️⃣ **Chạy Ngay Đi** — `3:48`",
                    "options": [
                        "Hãy Trao Cho Anh — 4:12 | Sơn Tùng MTP",
                        "Muộn Rồi Mà Sao Còn — 4:01 | Sơn Tùng MTP",
                        "Chạy Ngay Đi — 3:48 | Sơn Tùng MTP",
                        "Không Phải Dạng Vừa Đâu — 3:55 | Sơn Tùng MTP",
                        "Nơi Này Có Anh — 4:20 | Sơn Tùng MTP",
                    ]
                }
            },
            {
                "name": "stop", "emoji": "⏹️",
                "desc": "Dừng nhạc và xóa toàn bộ hàng chờ",
                "usage": "/stop", "example": "/stop", "args": [],
                "preview": {
                    "type": "text",
                    "text": "⏹️ Đã dừng nhạc và xóa hàng chờ!"
                }
            },
            {
                "name": "resume", "emoji": "▶️",
                "desc": "Tiếp tục phát nhạc đang bị tạm dừng",
                "usage": "/resume", "example": "/resume", "args": [],
                "preview": {"type": "text", "text": "▶️ Đã tiếp tục phát!"}
            },
            {
                "name": "loop", "emoji": "🔂",
                "desc": "Bật/tắt chế độ lặp lại bài hiện tại",
                "usage": "/loop", "example": "/loop", "args": [],
                "preview": {"type": "text", "text": "🔂 Đã **bật** chế độ lặp lại!"}
            },
            {
                "name": "autoplay", "emoji": "♾️",
                "desc": "Bật/tắt tự động phát bài tiếp theo khi hết queue",
                "usage": "/autoplay", "example": "/autoplay", "args": [],
                "preview": {"type": "text", "text": "♾️ Đã **bật** Autoplay!"}
            },
            {
                "name": "replay", "emoji": "🔁",
                "desc": "Phát lại bài hát hiện tại từ đầu",
                "usage": "/replay", "example": "/replay", "args": [],
                "preview": {"type": "text", "text": "🔁 Đang phát lại bài hiện tại..."}
            },
            {
                "name": "lofi", "emoji": "📻",
                "desc": "Phát stream Lofi Girl 24/7 — nhạc lo-fi không có quảng cáo",
                "usage": "/lofi", "example": "/lofi", "args": [],
                "preview": {"type": "text", "text": "📻 **Lofi Girl 24/7** đang bật... ☕🌙"}
            },
            {
                "name": "join", "emoji": "🔊",
                "desc": "Bot vào kênh voice đang ngồi của bạn",
                "usage": "/join", "example": "/join", "args": [],
                "preview": {"type": "text", "text": "✅ Đã vào **🎶 music**!"}
            },
            {
                "name": "leave", "emoji": "🚪",
                "desc": "Bot rời kênh voice và xóa hàng chờ",
                "usage": "/leave", "example": "/leave", "args": [],
                "preview": {"type": "text", "text": "👋 Đã rời kênh voice!"}
            },
            {
                "name": "playlist", "emoji": "📂",
                "desc": "Quản lý và phát danh sách nhạc (playlist)",
                "usage": "/playlist [name/add/play/show/remove/removesong]", "example": "/playlist play Nhạc Trẻ",
                "args": [
                    {"name": "action", "type": "Text", "required": True,
                     "desc": "Hành động (name, add, play, show, remove, removesong)"},
                    {"name": "playlist_name", "type": "Text", "required": True,
                     "desc": "Tên playlist"},
                    {"name": "query", "type": "Text", "required": False,
                     "desc": "Link nhạc hoặc tên bài hát (dành cho add)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865f2", "title": "📂 Playlist: Nhạc Trẻ",
                    "desc": "1. **Bài hát A** — `3:45`<br>2. **Bài hát B** — `4:02`<br>... và 10 bài hát khác."
                }
            },
            {
                "name": "seek", "emoji": "⏩",
                "desc": "Tua đến vị trí chỉ định trong bài hát (VD: 1:30 hoặc 90)",
                "usage": "/seek [vị_trí]", "example": "/seek 1:30",
                "args": [{"name": "position", "type": "Text", "required": True, "desc": "Vị trí thời gian cần tua (VD: 1:30 hoặc 90)"}],
                "preview": {"type": "text", "text": "⏩ Đã tua bài hát đến `01:30`."}
            },
            {
                "name": "remove", "emoji": "🗑️",
                "desc": "Xóa một bài hát khỏi hàng chờ theo vị trí",
                "usage": "/remove [vị_trí]", "example": "/remove 2",
                "args": [{"name": "position", "type": "Number", "required": True, "desc": "Số thứ tự của bài hát trong hàng chờ"}],
                "preview": {"type": "text", "text": "🗑️ Đã xóa bài hát khỏi hàng chờ."}
            },
            {
                "name": "clearqueue", "emoji": "🧹",
                "desc": "Xóa sạch toàn bộ bài hát trong hàng chờ (giữ bài đang phát)",
                "usage": "/clearqueue", "example": "/clearqueue", "args": [],
                "preview": {"type": "text", "text": "🧹 Đã xóa sạch 5 bài hát trong hàng chờ."}
            },
            {
                "name": "jump", "emoji": "⏭️",
                "desc": "Nhảy ngay tới bài hát chỉ định trong hàng chờ",
                "usage": "/jump [vị_trí]", "example": "/jump 3",
                "args": [{"name": "position", "type": "Number", "required": True, "desc": "Số thứ tự của bài hát muốn nhảy tới"}],
                "preview": {"type": "text", "text": "⏭️ Đã nhảy tới bài hát chỉ định."}
            },
            {
                "name": "topmusic", "emoji": "🏆",
                "desc": "Bảng xếp hạng các bài hát được nghe nhiều nhất trong server",
                "usage": "/topmusic", "example": "/topmusic", "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🏆 Top Bài Hát Nghe Nhiều Nhất",
                    "desc": "🥇 **Bài hát A** — **45** lần nghe<br>🥈 **Bài hát B** — **32** lần nghe<br>🥉 **Bài hát C** — **18** lần nghe"
                }
            },
            {
                "name": "lyrics", "emoji": "📜",
                "desc": "Xem lời bài hát đang phát hoặc tìm theo tên với phân trang",
                "usage": "/lyrics [tên bài]", "example": "/lyrics Đen - Nấu Ăn Cho Em",
                "args": [{"name": "query", "type": "Text", "required": False, "desc": "Tên bài hát cần xem lời (bỏ trống để lấy bài đang phát)"}],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "📜 Đen - Nấu Ăn Cho Em",
                    "desc": "Mặt trời soi rạng ngời trên nương cao...<br>Những nụ cười em thơ đón chào nắng sớm..."
                }
            },
        ]
    },
    {
        "category": "Kinh tế & Shop",
        "icon": "🪙",
        "commands": [
            {
                "name": "daily", "emoji": "📅",
                "desc": "Điểm danh hàng ngày nhận tiền thưởng và chuỗi streak",
                "usage": "/daily", "example": "/daily", "args": [],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "📅 Điểm Danh Hàng Ngày",
                    "desc": "🎉 Bạn đã nhận được **+100** 🪙!<br>🔥 Chuỗi điểm danh: **3 ngày liên tiếp**"
                }
            },
            {
                "name": "balance", "emoji": "💰",
                "desc": "Xem số dư ví tiền mặt, ngân hàng và tổng tài sản",
                "usage": "/balance [@member]", "example": "/balance @Nam",
                "args": [{"name": "member", "type": "Mention", "required": False, "desc": "Thành viên cần xem số dư"}],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "Ví Tiền & Tài Sản — Nam",
                    "desc": "💵 **Ví:** `500 🪙`<br>🏦 **Ngân hàng:** `2,500 🪙`<br>💎 **Tổng tài sản:** `3,000 🪙`"
                }
            },
            {
                "name": "deposit", "emoji": "🏦",
                "desc": "Nạp tiền từ Ví vào tài khoản Ngân hàng (Bank) để bảo vệ tài sản và mua sắm Shop",
                "usage": "/deposit <amount>", "example": "/deposit 500",
                "args": [{"name": "amount", "type": "Text", "required": True, "desc": "Số tiền cần nạp (hoặc gõ 'all' / 'max')"}],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🏦 Nạp Tiền Vào Ngân Hàng",
                    "desc": "✅ Đã nạp thành công **500** 🪙 vào Ngân hàng!<br><br>💵 **Ví (Wallet):** `0 🪙`<br>🏦 **Ngân hàng (Bank):** `3,000 🪙`"
                }
            },
            {
                "name": "withdraw", "emoji": "🏧",
                "desc": "Rút tiền từ Ngân hàng (Bank) về Ví để cá cược mini-games hoặc chuyển khoản",
                "usage": "/withdraw <amount>", "example": "/withdraw 500",
                "args": [{"name": "amount", "type": "Text", "required": True, "desc": "Số tiền cần rút (hoặc gõ 'all' / 'max')"}],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🏧 Rút Tiền Từ Ngân Hàng",
                    "desc": "✅ Đã rút thành công **500** 🪙 về Ví!<br><br>💵 **Ví (Wallet):** `500 🪙`<br>🏦 **Ngân hàng (Bank):** `2,500 🪙`"
                }
            },
            {
                "name": "pay", "emoji": "💸",
                "desc": "Chuyển tiền mặt cho thành viên khác trong server",
                "usage": "/pay <@member> <amount>", "example": "/pay @Nam 200",
                "args": [
                    {"name": "member", "type": "Mention", "required": True, "desc": "Thành viên nhận tiền"},
                    {"name": "amount", "type": "Number", "required": True, "desc": "Số tiền cần chuyển"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "💸 Chuyển Tiền Thành Công",
                    "desc": "✅ Bạn đã chuyển thành công **200 🪙** cho @Nam!"
                }
            },
            {
                "name": "rich", "emoji": "🏆",
                "desc": "Bảng xếp hạng đại gia tiền tệ trong server",
                "usage": "/rich", "example": "/rich", "args": [],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "🏆 Bảng Xếp Hạng Đại Gia",
                    "desc": "🥇 **Nam** — `15,400 🪙`<br>🥈 **Alex** — `9,850 🪙`<br>🥉 **Cú** — `5,200 🪙`"
                }
            },
            {
                "name": "coinflip", "emoji": "🪙",
                "desc": "Cược tiền trò chơi tung đồng xu (Ngửa / Sấp)",
                "usage": "/coinflip <heads/tails> <bet>", "example": "/coinflip heads 50",
                "args": [
                    {"name": "choice", "type": "Choice", "required": True, "desc": "Chọn Mặt Ngửa (heads) hoặc Mặt Sấp (tails)"},
                    {"name": "bet", "type": "Number", "required": True, "desc": "Số tiền cược"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🪙 Thắng Cược Tung Đồng Xu!",
                    "desc": "Đồng xu rơi vào mặt **Ngửa**!<br>🎉 Bạn nhận được **+100 🪙**!"
                }
            },
            {
                "name": "slots", "emoji": "🎰",
                "desc": "Quay hũ Slot Machine may mắn với nhiều mức nhân thưởng",
                "usage": "/slots <bet>", "example": "/slots 50",
                "args": [{"name": "bet", "type": "Number", "required": True, "desc": "Số tiền cược"}],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "🎰 Thắng Lớn Slot Machine!",
                    "desc": "[ 💎 | 💎 | 💎 ]<br>🎉 Bạn trúng x5 và nhận được **+250 🪙**!"
                }
            },
            {
                "name": "blackjack", "emoji": "🃏",
                "desc": "Đánh bài Xì Dách 21 điểm với Nhà Cái tương tác bằng nút bấm",
                "usage": "/blackjack <bet>", "example": "/blackjack 100",
                "args": [{"name": "bet", "type": "Number", "required": True, "desc": "Số tiền cược"}],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🃏 Đánh Bài Xì Dách (Blackjack)",
                    "desc": "**Bài của bạn:** 🂡 🂪 (21 điểm)<br>**Nhà cái:** 🂱 🂸 (19 điểm)<br>🎉 **BẠN THẮNG!** Nhận được **+200 🪙**!"
                }
            },
            {
                "name": "shop", "emoji": "🛒",
                "desc": "Xem danh sách các Role đang được bán trong shop server",
                "usage": "/shop", "example": "/shop", "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🛒 Cửa Hàng Server",
                    "desc": "• **`#1` VIP Member** — `500 🪙` (Còn 10)<br>• **`#2` Pro Gamer** — `1,000 🪙` (Vô hạn)<br><br>Dùng `/buy <ID>` để mua."
                }
            },
            {
                "name": "buy", "emoji": "🛍️",
                "desc": "Mua Role trong shop server bằng tiền ảo",
                "usage": "/buy <item_id>", "example": "/buy 1",
                "args": [{"name": "item_id", "type": "Number", "required": True, "desc": "ID vật phẩm trong shop"}],
                "preview": {
                    "type": "text", "text": "🎉 Bạn đã mua thành công **VIP Member**!"
                }
            },
            {
                "name": "work", "emoji": "💼",
                "desc": "Lao động nghề nghiệp kiếm tiền lương vào ví (Cooldown 1 giờ)",
                "usage": "/work", "example": "/work", "args": [],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "💼 Lao Động Hăng Say",
                    "desc": "@Nam đã làm công việc **Lập trình viên Fullstack 💻** và nhận được tiền lương **+180 🪙**!"
                }
            },
            {
                "name": "fish", "emoji": "🎣",
                "desc": "Câu cá thư giãn và tìm kiếm các loài thủy hải sản quý hiếm (Cooldown 15 phút)",
                "usage": "/fish", "example": "/fish", "args": [],
                "preview": {
                    "type": "embed", "color": "#3498DB", "title": "🎣 Đi Câu Cá Thư Giãn",
                    "desc": "🌊 Bạn đã quăng cần và câu được **🍣 Cá Hồi Nauy** (*Hiếm*)!<br>💰 Giá trị ước tính: **120 🪙** (đã lưu vào túi đồ)."
                }
            },
            {
                "name": "hunt", "emoji": "🏹",
                "desc": "Đi săn thú trong rừng và tìm kiếm các loài sinh vật quý hiếm (Cooldown 15 phút)",
                "usage": "/hunt", "example": "/hunt", "args": [],
                "preview": {
                    "type": "embed", "color": "#E67E22", "title": "🏹 Đi Săn Bắn Trong Rừng",
                    "desc": "🌲 Bạn đã tiến vào rừng sâu và săn được **🦌 Hươu Sao Đốm Bạc** (*Hiếm*)!<br>💰 Giá trị ước tính: **130 🪙** (đã lưu vào túi đồ)."
                }
            },
            {
                "name": "inventory", "emoji": "🎒",
                "desc": "Xem túi đồ cá nhân và quản lý các vật phẩm bạn đang sở hữu",
                "usage": "/inventory", "example": "/inventory", "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🎒 Túi Đồ Cá Nhân — Nam",
                    "desc": "🟡 **Huyền Thoại:**<br>• **🐉 Rồng Biển Leviathan** x1 (3,000 🪙/món)<br><br>🟢 **Hiếm:**<br>• **🍣 Cá Hồi Nauy** x2 (120 🪙/món)"
                }
            },
            {
                "name": "sell", "emoji": "🏷️",
                "desc": "Bán vật phẩm trong túi đồ của bạn để thu tiền mặt vào ví",
                "usage": "/sell <item_id> [quantity]", "example": "/sell ca_hoi 2",
                "args": [
                    {"name": "item_id", "type": "Choice", "required": True, "desc": "Mã hoặc tên vật phẩm cần bán (hỗ trợ autocomplete)"},
                    {"name": "quantity", "type": "Number", "required": False, "desc": "Số lượng cần bán (mặc định: 1)"}
                ],
                "preview": {
                    "type": "embed", "color": "#57F287", "title": "💰 Bán Vật Phẩm Thành Công",
                    "desc": "✅ Bạn đã bán thành công **2x 🍣 Cá Hồi Nauy** và nhận được **+240 🪙** vào ví!"
                }
            }
        ]
    },
    {
        "category": "Voice Tạm thời",
        "icon": "🎙️",
        "commands": [
            {
                "name": "voice lock", "emoji": "🔒",
                "desc": "Khóa phòng voice cá nhân (chỉ người được mời mới vào được)",
                "usage": "/voice lock", "example": "/voice lock", "args": [],
                "preview": {"type": "text", "text": "🔒 Đã KHÓA phòng voice riêng của bạn!"}
            },
            {
                "name": "voice unlock", "emoji": "🔓",
                "desc": "Mở khóa phòng voice cá nhân cho mọi người cùng vào",
                "usage": "/voice unlock", "example": "/voice unlock", "args": [],
                "preview": {"type": "text", "text": "🔓 Đã MỞ KHÓA phòng voice cho tất cả thành viên!"}
            },
            {
                "name": "voice limit", "emoji": "👥",
                "desc": "Đặt giới hạn số lượng người tối đa trong phòng voice",
                "usage": "/voice limit <number>", "example": "/voice limit 5",
                "args": [{"name": "limit", "type": "Number", "required": True, "desc": "Số người tối đa (0 = vô hạn)"}],
                "preview": {"type": "text", "text": "✅ Đã đặt giới hạn phòng thành **5 người**!"}
            },
            {
                "name": "voice rename", "emoji": "✏️",
                "desc": "Đổi tên phòng voice cá nhân của bạn",
                "usage": "/voice rename <name>", "example": "/voice rename Phòng Chơi Game",
                "args": [{"name": "name", "type": "Text", "required": True, "desc": "Tên phòng mới"}],
                "preview": {"type": "text", "text": "✅ Đã đổi tên phòng voice thành: **Phòng Chơi Game**!"}
            }
        ]
    },
    {
        "category": "Lệnh Tùy biến",
        "icon": "⚡",
        "commands": [
            {
                "name": "customcmd list", "emoji": "📋",
                "desc": "Xem danh sách các lệnh tùy biến và auto-responders trong server",
                "usage": "/customcmd list", "example": "/customcmd list", "args": [],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "⚡ Danh Sách Lệnh Tùy Biến",
                    "desc": "• **`!ip`** `[exact]` — 45 lần sử dụng<br>• **`!rules`** `[exact]` — 120 lần sử dụng"
                }
            },
            {
                "name": "customcmd add", "emoji": "➕",
                "desc": "Thêm một lệnh phản hồi tự động nhanh bằng văn bản",
                "usage": "/customcmd add <trigger> <response>", "example": "/customcmd add !ip IP server là play.example.com",
                "args": [
                    {"name": "trigger", "type": "Text", "required": True, "desc": "Từ khóa kích hoạt (VD: !ip)"},
                    {"name": "response", "type": "Text", "required": True, "desc": "Nội dung phản hồi (hỗ trợ {user}, {server})"}
                ],
                "preview": {"type": "text", "text": "✅ Đã tạo lệnh tùy biến mới: **`!ip`**!"}
            },
            {
                "name": "customcmd delete", "emoji": "🗑️",
                "desc": "Xóa một lệnh tùy biến trong server",
                "usage": "/customcmd delete <trigger>", "example": "/customcmd delete !ip",
                "args": [{"name": "trigger", "type": "Text", "required": True, "desc": "Từ khóa của lệnh cần xóa"}],
                "preview": {"type": "text", "text": "🗑️ Đã xóa lệnh tùy biến: **`!ip`**!"}
            }
        ]
    },
    {
        "category": "Trợ lý AI",
        "icon": "🤖",
        "commands": [
            {
                "name": "ask", "emoji": "💡",
                "desc": "Đặt câu hỏi thông minh cho trợ lý AI (hỗ trợ kèm ảnh & tra cứu web thời gian thực)",
                "usage": "/ask <prompt> [image] [web]", "example": "/ask Tin tức công nghệ hôm nay web:True",
                "args": [
                    {"name": "prompt", "type": "Text", "required": True, "desc": "Câu hỏi cần giải đáp"},
                    {"name": "image", "type": "Attachment", "required": False, "desc": "Hình ảnh đính kèm để phân tích"},
                    {"name": "web", "type": "Boolean", "required": False, "desc": "Bật tra cứu Internet qua DuckDuckGo (True/False)"}
                ],
                "preview": {
                    "type": "embed", "color": "#5865F2", "title": "🤖 Trợ Lý AI Zeryn",
                    "desc": "Hố đen là một vùng không gian có trường hấp dẫn mạnh đến mức không vật chất hay bức xạ nào có thể thoát ra..."
                }
            },
            {
                "name": "summarize", "emoji": "📋",
                "desc": "Đọc và tóm tắt ngắn gọn tin nhắn trong kênh hoặc nội dung bài viết từ URL",
                "usage": "/summarize [limit] [url]", "example": "/summarize url:https://vnexpress.net/...",
                "args": [
                    {"name": "limit", "type": "Number", "required": False, "desc": "Số lượng tin nhắn cần tóm tắt (10-50)"},
                    {"name": "url", "type": "Text", "required": False, "desc": "Đường link URL bài viết cần tóm tắt"}
                ],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "📋 Tóm Tắt Cuộc Trò Chuyện",
                    "desc": "• **Chủ đề chính:** Mọi người đang bàn về kế hoạch chơi game cuối tuần.<br>• **Quyết định:** Thống nhất chơi Valorant lúc 20h tối thứ 7."
                }
            }
        ]
    },
    {
        "category": "Điều hành",
        "icon": "🛡️",
        "commands": [
            {
                "name": "kick", "emoji": "🔨",
                "desc": "Đuổi thành viên khỏi server",
                "usage": "/kick [member] [reason]", "example": "/kick @User Vi phạm nội quy",
                "args": [
                    {"name": "member", "type": "User", "required": True, "desc": "Thành viên cần kick"},
                    {"name": "reason", "type": "Text", "required": False, "desc": "Lý do đuổi"}
                ],
                "preview": {"type": "text", "text": "🔨 @User đã bị đuổi khỏi server."}
            },
            {
                "name": "ban", "emoji": "⛔",
                "desc": "Cấm thành viên khỏi server",
                "usage": "/ban [member] [reason] [delete_days]", "example": "/ban @User Spam phá hoại 1",
                "args": [
                    {"name": "member", "type": "User", "required": True, "desc": "Thành viên cần cấm"},
                    {"name": "reason", "type": "Text", "required": False, "desc": "Lý do cấm"},
                    {"name": "delete_days", "type": "Number", "required": False, "desc": "Số ngày tin nhắn cần xóa (0-7)"}
                ],
                "preview": {"type": "text", "text": "⛔ @User đã bị cấm khỏi server."}
            },
            {
                "name": "unban", "emoji": "✅",
                "desc": "Hủy cấm người dùng theo ID",
                "usage": "/unban [user_id] [reason]", "example": "/unban 123456789 Hết hạn phạt",
                "args": [
                    {"name": "user_id", "type": "Text", "required": True, "desc": "ID người dùng"},
                    {"name": "reason", "type": "Text", "required": False, "desc": "Lý do hủy cấm"}
                ],
                "preview": {"type": "text", "text": "✅ Đã hủy cấm thành công cho ID 123456789."}
            },
            {
                "name": "timeout", "emoji": "🔇",
                "desc": "Khóa chat tạm thời (Mute)",
                "usage": "/timeout [member] [duration] [reason]", "example": "/timeout @User 10m Spam chat",
                "args": [
                    {"name": "member", "type": "User", "required": True, "desc": "Thành viên cần mute"},
                    {"name": "duration", "type": "Text", "required": True, "desc": "Thời lượng (10m, 2h, 1d)"},
                    {"name": "reason", "type": "Text", "required": False, "desc": "Lý do khóa chat"}
                ],
                "preview": {"type": "text", "text": "🔇 @User đã bị khóa chat 10m."}
            },
            {
                "name": "untimeout", "emoji": "🔊",
                "desc": "Gỡ khóa chat",
                "usage": "/untimeout [member] [reason]", "example": "/untimeout @User Ân xá",
                "args": [
                    {"name": "member", "type": "User", "required": True, "desc": "Thành viên cần gỡ mute"},
                    {"name": "reason", "type": "Text", "required": False, "desc": "Lý do"}
                ],
                "preview": {"type": "text", "text": "🔊 Đã gỡ khóa chat cho @User."}
            },
            {
                "name": "warn", "emoji": "⚠️",
                "desc": "Cảnh cáo thành viên (Tự động phạt: 3 lần = Mute 1h, 5 lần = Kick)",
                "usage": "/warn [member] [reason]", "example": "/warn @User Dùng từ ngữ không phù hợp",
                "args": [
                    {"name": "member", "type": "User", "required": True, "desc": "Thành viên bị cảnh cáo"},
                    {"name": "reason", "type": "Text", "required": True, "desc": "Lý do cảnh cáo"}
                ],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "⚠️ Cảnh Cáo Thành Viên",
                    "desc": "**Thành viên:** @User<br>**Lý do:** Dùng từ ngữ không phù hợp<br>**Tổng cảnh cáo:** 1"
                }
            },
            {
                "name": "warnings", "emoji": "📋",
                "desc": "Xem lịch sử cảnh cáo",
                "usage": "/warnings [member]", "example": "/warnings @User",
                "args": [{"name": "member", "type": "User", "required": False, "desc": "Thành viên cần xem (mặc định: bản thân)"}],
                "preview": {
                    "type": "embed", "color": "#FEE75C", "title": "📋 Cảnh cáo của User",
                    "desc": "`#1` — Dùng từ ngữ không phù hợp (10 phút trước)"
                }
            },
            {
                "name": "delwarn", "emoji": "🗑️",
                "desc": "Xóa cảnh cáo theo ID",
                "usage": "/delwarn [warn_id]", "example": "/delwarn 1",
                "args": [{"name": "warn_id", "type": "Number", "required": True, "desc": "ID cảnh cáo cần xóa"}],
                "preview": {"type": "text", "text": "✅ Đã xóa cảnh cáo #1."}
            },
            {
                "name": "clear", "emoji": "🧹",
                "desc": "Xóa tin nhắn hàng loạt",
                "usage": "/clear [amount] [member]", "example": "/clear 20",
                "args": [
                    {"name": "amount", "type": "Number", "required": True, "desc": "Số tin nhắn cần xóa (1-100)"},
                    {"name": "member", "type": "User", "required": False, "desc": "Chỉ xóa tin của người này"}
                ],
                "preview": {"type": "text", "text": "🗑️ Đã xóa 20 tin nhắn."}
            },
            {
                "name": "slowmode", "emoji": "🐌",
                "desc": "Đặt chế độ chat chậm",
                "usage": "/slowmode [seconds] [channel]", "example": "/slowmode 5",
                "args": [
                    {"name": "seconds", "type": "Number", "required": True, "desc": "Thời gian chờ (0 = tắt)"},
                    {"name": "channel", "type": "Channel", "required": False, "desc": "Kênh áp dụng"}
                ],
                "preview": {"type": "text", "text": "🐌 Đã bật slowmode 5s."}
            },
            {
                "name": "lock", "emoji": "🔒",
                "desc": "Khóa kênh chat",
                "usage": "/lock [channel]", "example": "/lock",
                "args": [{"name": "channel", "type": "Channel", "required": False, "desc": "Kênh cần khóa"}],
                "preview": {"type": "text", "text": "🔒 Kênh đã bị khóa."}
            },
            {
                "name": "unlock", "emoji": "🔓",
                "desc": "Mở khóa kênh chat",
                "usage": "/unlock [channel]", "example": "/unlock",
                "args": [{"name": "channel", "type": "Channel", "required": False, "desc": "Kênh cần mở khóa"}],
                "preview": {"type": "text", "text": "🔓 Kênh đã được mở khóa."}
            }
        ]
    },
    {
        "category": "Vui vẻ & Tình cảm",
        "icon": "🎭",
        "commands": [
            {
                "name": "hug", "emoji": "🤗",
                "desc": "Ôm ai đó thật ấm áp",
                "usage": "/hug [member]", "example": "/hug @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bạn muốn ôm"}],
                "preview": {"type": "text", "text": "🤗 @User ôm @Friend thật ấm áp!"}
            },
            {
                "name": "pat", "emoji": "😊",
                "desc": "Xoa đầu ai đó",
                "usage": "/pat [member]", "example": "/pat @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bạn muốn xoa đầu"}],
                "preview": {"type": "text", "text": "😊 @User xoa đầu @Friend thật dễ thương!"}
            },
            {
                "name": "kiss", "emoji": "😘",
                "desc": "Hôn ai đó",
                "usage": "/kiss [member]", "example": "/kiss @Crush",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bạn muốn hôn"}],
                "preview": {"type": "text", "text": "😘 @User hôn @Crush! 💋"}
            },
            {
                "name": "slap", "emoji": "👋",
                "desc": "Tát ai đó tinh nghịch",
                "usage": "/slap [member]", "example": "/slap @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bị tát"}],
                "preview": {"type": "text", "text": "👋 @User tát @Friend! Ouch!"}
            },
            {
                "name": "feed", "emoji": "🍙",
                "desc": "Đút cho ai đó ăn kèm GIF anime",
                "usage": "/feed [member]", "example": "/feed @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người được đút ăn"}],
                "preview": {"type": "text", "text": "🍙 @User đút cho @Friend ăn! Ngon không?"}
            },
            {
                "name": "cuddle", "emoji": "🧸",
                "desc": "Cưng nựng ôm ấp ai đó",
                "usage": "/cuddle [member]", "example": "/cuddle @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bạn muốn cưng nựng"}],
                "preview": {"type": "text", "text": "🧸 @User cưng nựng @Friend thật đáng yêu!"}
            },
            {
                "name": "poke", "emoji": "👉",
                "desc": "Chọc má ai đó",
                "usage": "/poke [member]", "example": "/poke @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bị chọc"}],
                "preview": {"type": "text", "text": "👉 @User chọc má @Friend!"}
            },
            {
                "name": "highfive", "emoji": "✋",
                "desc": "Đập tay chúc mừng",
                "usage": "/highfive [member]", "example": "/highfive @Friend",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người đập tay cùng"}],
                "preview": {"type": "text", "text": "✋ @User đập tay với @Friend! 🎉"}
            },
            {
                "name": "cry", "emoji": "😢",
                "desc": "Khóc biểu cảm",
                "usage": "/cry", "example": "/cry", "args": [],
                "preview": {"type": "text", "text": "😢 @User đang khóc... ai an ủi đi!"}
            },
            {
                "name": "dance", "emoji": "💃",
                "desc": "Nhảy múa vui vẻ",
                "usage": "/dance", "example": "/dance", "args": [],
                "preview": {"type": "text", "text": "💃 @User nhảy múa vui vẻ!"}
            },
            {
                "name": "ship", "emoji": "💘",
                "desc": "Đoán độ hợp đôi giữa hai người",
                "usage": "/ship [user1] [user2]", "example": "/ship @User1 @User2",
                "args": [
                    {"name": "user1", "type": "User", "required": True, "desc": "Người thứ nhất"},
                    {"name": "user2", "type": "User", "required": False, "desc": "Người thứ hai (mặc định: bạn)"}
                ],
                "preview": {
                    "type": "embed", "color": "#FF69B4", "title": "💘 User1 × User2",
                    "desc": "**95%** Trời sinh một cặp! 💞<br>❤️❤️❤️❤️❤️❤️❤️❤️❤️🖤"
                }
            },
            {
                "name": "marry", "emoji": "💍",
                "desc": "Cầu hôn ai đó bằng nút bấm tương tác",
                "usage": "/marry [member]", "example": "/marry @Crush",
                "args": [{"name": "member", "type": "User", "required": True, "desc": "Người bạn muốn cầu hôn"}],
                "preview": {
                    "type": "embed", "color": "#FF69B4", "title": "💍 Lời cầu hôn",
                    "desc": "💍 @User đã cầu hôn @Crush! Bạn có đồng ý không?"
                }
            },
            {
                "name": "divorce", "emoji": "💔",
                "desc": "Ly hôn và chấm dứt mối quan hệ",
                "usage": "/divorce", "example": "/divorce", "args": [],
                "preview": {"type": "text", "text": "💔 @User đã ly hôn thành công."}
            },
            {
                "name": "profile", "emoji": "💝",
                "desc": "Xem thẻ hồ sơ tình cảm cá nhân",
                "usage": "/profile [member]", "example": "/profile @User",
                "args": [{"name": "member", "type": "User", "required": False, "desc": "Thành viên cần xem"}],
                "preview": {
                    "type": "embed", "color": "#FF69B4", "title": "💝 User",
                    "desc": "💍 **Đối tượng:** @Partner<br>📅 **Ngày kết hôn:** 15 ngày<br>💖 **Điểm yêu thương:** 42"
                }
            }
        ]
    },
    {
        "category": "Sinh nhật",
        "icon": "🎂",
        "commands": [
            {
                "name": "birthday set", "emoji": "🎂",
                "desc": "Đăng ký ngày sinh của bản thân",
                "usage": "/birthday set [day] [month] [year]", "example": "/birthday set 15 8 2000",
                "args": [
                    {"name": "day", "type": "Number", "required": True, "desc": "Ngày (1-31)"},
                    {"name": "month", "type": "Number", "required": True, "desc": "Tháng (1-12)"},
                    {"name": "year", "type": "Number", "required": False, "desc": "Năm sinh (tùy chọn)"}
                ],
                "preview": {"type": "text", "text": "🎂 Đã lưu ngày sinh của bạn: **15/08/2000**"}
            },
            {
                "name": "birthday check", "emoji": "📅",
                "desc": "Xem ngày sinh và đếm ngược",
                "usage": "/birthday check [member]", "example": "/birthday check @User",
                "args": [{"name": "member", "type": "User", "required": False, "desc": "Thành viên cần xem"}],
                "preview": {
                    "type": "embed", "color": "#FF69B4", "title": "🎂 User",
                    "desc": "📅 **Ngày sinh:** 15/08/2000<br>⏳ **Đếm ngược:** 45 ngày nữa<br>🎈 **Tuổi:** 26"
                }
            },
            {
                "name": "birthday list", "emoji": "📋",
                "desc": "Xem 10 sinh nhật sắp tới trong server",
                "usage": "/birthday list", "example": "/birthday list", "args": [],
                "preview": {
                    "type": "embed", "color": "#FF69B4", "title": "🎂 Sinh nhật sắp tới",
                    "desc": "**1.** @User1 — `01/09` (12d)<br>**2.** @User2 — `15/09` (26d)"
                }
            },
            {
                "name": "birthday remove", "emoji": "🗑️",
                "desc": "Xóa ngày sinh đã đăng ký",
                "usage": "/birthday remove", "example": "/birthday remove", "args": [],
                "preview": {"type": "text", "text": "✅ Đã xóa ngày sinh của bạn."}
            }
        ]
    }
]


# Flat index by command name for fast O(1) lookup
COMMANDS_BY_NAME = {}
ALL_COMMAND_NAMES = []

for _cat in _COMMANDS_DATA:
    for _cmd in _cat.get("commands", []):
        name = _cmd["name"]
        COMMANDS_BY_NAME[name.lower()] = _cmd
        COMMANDS_BY_NAME["/" + name.lower()] = _cmd
        ALL_COMMAND_NAMES.append(name)

def get_command_data(cmd_name: str):
    """Return command dict by name (with or without leading slash)."""
    if not cmd_name:
        return None
    cleaned = cmd_name.strip().lower().lstrip("/")
    return COMMANDS_BY_NAME.get(cleaned)
