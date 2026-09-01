---
name: music_audio_pipeline
description: >
  Audio pipeline, FFmpeg, yt-dlp, libopus loading, Spotify resolving,
  voice connection lifecycle, and ARM/Termux performance optimizations for ZerynBot V2.
---

# Skill: Music & Audio Pipeline Optimization (ARM / Termux)

## 🎯 1. Mục Đích & Phạm Vi

Module Music (`bot/cogs/music.py`) là một trong những thành phần tiêu tốn nhiều CPU và tài nguyên mạng nhất. Kỹ năng này cung cấp các nguyên tắc kiến trúc bắt buộc để hệ thống âm nhạc chạy ổn định 24/7 trên thiết bị phần cứng yếu (ARM64 Android Termux / Raspberry Pi), không gây nghẽn Gateway Discord và không bị rò rỉ RAM.

---

## ⚡ 2. Cấu Hình & Tối Ưu Hóa FFmpeg Cho ARM

### 2.1 Cờ FFmpeg Đơn Luồng Bắt Buộc
Trên chip di động ARM (Snapdragon, MediaTek, Cortex), việc chạy FFmpeg đa luồng sẽ làm quá tải CPU và gây giật lag toàn hệ thống. Bắt buộc cấu hình:
- `-threads 1`: Ép chạy đơn luồng.
- `-b:a 96k`: Giới hạn bitrate âm thanh 96kbps (vừa vặn với Discord voice channel tiêu chuẩn, tiết kiệm 50% CPU so với 320k).

### 2.2 Cờ Kết Nối Ổn Định Đa Nền Tảng (Universal FFmpeg Before Flags)
```python
FFMPEG_BEFORE = (
    "-loglevel error "
    "-reconnect 1 "
    "-reconnect_streamed 1 "
    "-reconnect_delay_max 5 "
    "-probesize 1M "
    "-analyzeduration 1000000 "
    '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"'
)
```

> [!WARNING]
> Tuyệt đối không dùng các cờ không tương thích trên Termux như `-reconnect_at_eof` hoặc cờ `-headers` không được escape chuỗi đúng chuẩn.

---

## 🧩 3. Cơ Chế Nạp Thư Viện `libopus` Động

Trên Android Termux và một số bản phân phối Linux, `discord.py` không thể tự động tìm thấy file `libopus.so`. Hàm `load_opus_library()` giải quyết vấn đề này:

```python
def load_opus_library():
    if discord.opus.is_loaded():
        return
    opus_paths = [
        "/data/data/com.termux/files/usr/lib/libopus.so",  # Termux Android
        "libopus.so.0",                                   # Linux tiêu chuẩn
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "libopus-0.x64.dll",                              # Windows 64-bit
        "libopus-0.x86.dll",                              # Windows 32-bit
        "libopus.dylib"                                   # macOS
    ]
    for path in opus_paths:
        try:
            discord.opus.load_opus(path)
            if discord.opus.is_loaded():
                return
        except Exception:
            continue
```

---

## 🛡️ 4. Xử Lý Race Condition & Chống Lỗi Crash Voice

### 4.1 Chống Lỗi `ClientException: Already playing audio`
Khi chuyển bài hát hoặc Skip, hàm `vc.stop()` cần vài mili-giây để giải phóng thread stream. Nếu gọi `vc.play()` ngay lập tức sẽ sinh crash.

**Giải pháp chuẩn:**
```python
# Chờ giải phóng thread cũ trước khi phát bài mới (tối đa 0.5s)
for _ in range(10):
    if not vc.is_playing() and not vc.is_paused():
        break
    await asyncio.sleep(0.05)

# Bọc Source trong FFmpegOpusAudio (ưu tiên) hoặc FFmpegPCMAudio
source = discord.FFmpegOpusAudio(stream_url, before_options=FFMPEG_BEFORE, options=FFMPEG_OPTS)
vc.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.next_event.set))
```

### 4.2 Giới Hạn Tải Đồng Thời (`MAX_PLAYERS = 6`)
Để tránh tràn RAM trên thiết bị 4GB RAM, hệ thống giới hạn tối đa 6 máy chủ phát nhạc cùng lúc. Nếu server thứ 7 yêu cầu, bot sẽ thông báo lịch sự máy chủ bận.

### 4.3 Tự Động Rời Kênh Khi Không Hoạt Động (3 Phút Auto-Disconnect)
Khi danh sách bài hát hết hoặc tất cả thành viên rời khỏi phòng Voice, khởi động bộ đếm 180s. Nếu không có bài mới sau 180s, bot tự động disconnect để trả lại tài nguyên.

---

## 🎨 5. Giao Diện Player Card (Music | 2 Compact Style)

- **Layout**: Embed nhỏ gọn, ảnh thumbnail bài hát nằm bên phải (`embed.set_thumbnail`).
- **Thanh tiến trình (Progress Bar)**: Render động dạng `🔘▬▬▬▬▬▬▬▬ 01:23 / 03:45`.
- **5 Nút bấm điều khiển (`MusicControlView`)**:
  - ⏯️ **Tạm dừng / Tiếp tục** (Pause / Resume)
  - ⏭️ **Bỏ qua** (Skip)
  - 🔁 **Lặp lại** (Loop: Off ➔ Single ➔ Queue)
  - 🔀 **Xáo trộn** (Shuffle)
  - ⏹️ **Dừng & Rời phòng** (Stop)
