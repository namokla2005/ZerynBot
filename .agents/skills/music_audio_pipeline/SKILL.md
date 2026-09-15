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
    "-reconnect_delay_max 2 "
    "-rw_timeout 10000000 "  # 10s socket timeout chống treo vĩnh viễn khi mạng drop
    "-fflags +genpts "
    "-probesize 512K "
    "-analyzeduration 500000 "
    '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"'
)
FFMPEG_OPTS_COPY = "-vn -sn -c:a copy -threads 1"
FFMPEG_OPTS_ENCODE = "-vn -sn -threads 1 -af aresample=async=1:first_pts=0"
```

> [!WARNING]
> - **yt-dlp player_client**: Luôn sử dụng `["android", "web"]`. Tuyệt đối **KHÔNG dùng client `tv`** vì YouTube trả lỗi `The page needs to be reloaded` khiến toàn bộ video & stream thất bại.
> - Tuyệt đối không dùng các cờ không tương thích trên Termux như `-reconnect_at_eof` hoặc cờ `-headers` không được escape chuỗi đúng chuẩn.

### 2.3 Cơ Chế Bộ Nhớ Đệm 2 Tầng & Thread-Safe Worker Pool
- **Thread-Safety (`threading.local`)**: Mỗi worker thread sở hữu instance `YoutubeDL` độc lập, triệt tiêu hoàn toàn race condition trong khi vẫn giữ nguyên HTTP connection pool.
- **Tầng 1 (In-Memory RAM Cache - `cache.py`)**: Lưu trữ thông tin bài hát trong RAM (TTL 10 phút).
- **Tầng 2 (SQLite Disk Cache - `music_song_cache`)**: Lưu `payload` JSON trích xuất từ yt-dlp vào CSDL SQLite (`async_get_song_cache` / `async_set_song_cache`) với **TTL 6 giờ** (hoặc timestamp `expire` thực tế trích từ URL). Khi bot khởi động lại (restart), không cần tốn 2-4 giây trích xuất lại metadata từ YouTube mà phát ngay lập tức (< 0.5s).
- **Trích xuất song song (Concurrent Extraction)**: Khi người dùng gõ `/play`, bot khởi chạy đồng thời tác vụ kết nối kênh voice (`_ensure_voice_client`) và tác vụ trích xuất metadata (`extract_info`), giúp giảm 50% tổng thời gian chờ phát bài đầu tiên. Tải playlist chạy nền theo batch 3 bài hát song song.
- **Tự cứu luồng phát 403 (Auto-Recovery)**: Khi URL stream hết hạn giữa chừng, bot tự động xóa cache stream URL, trích xuất lại URL mới và tiếp tục phát ngay tại vị trí cũ (`-ss <elapsed>`).

---

## 🧩 3. Cơ Chế Nạp Thư Viện `libopus` Động

Trên Android Termux và một số bản phân phối Linux, `discord.py` không thể tự động tìm thấy file `libopus.so`. Hàm `load_opus_library()` được gom tại `bot/bot.py` và tái sử dụng ở mọi nơi.

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
Khi danh sách bài hát hết hoặc tất cả thành viên rời khỏi phòng Voice, khởi động bộ đếm 180s. Nếu không có bài mới sau 180s, bot tự động disconnect để trả lại tài nguyên. Nếu chính bot bị ngắt kết nối (kick/disconnect khỏi voice), `on_voice_state_update` sẽ lập tức cleanup player ngay lập tức.

---

## 🎨 5. Giao Diện & Lệnh Điều Khiển Nhạc

- **Player Card**: Embed nhỏ gọn, ảnh thumbnail bên phải, thanh tiến trình `🔘▬▬▬▬▬▬▬▬ 01:23 / 03:45`, 5 nút điều khiển (`Pause/Resume`, `Skip`, `Loop`, `Shuffle`, `Stop`).
- **Lệnh tương tác nâng cao**:
  - `/seek <position>`: Tua tới mốc thời gian cụ thể (hỗ trợ `1:30` hoặc `90`).
  - `/search <query>`: Tìm kiếm tương tác với menu Select 5 kết quả hàng đầu.
  - `/remove <position>`: Xóa bài hát bất kỳ trong hàng đợi.
  - `/clearqueue` (aliases: `cq`, `qclear`): Xóa toàn bộ hàng đợi.
  - `/jump <position>`: Nhảy ngay tới vị trí chỉ định trong hàng đợi.
  - Thống kê bài hát yêu thích: Ghi nhận số lượt nghe vào CSDL qua `async_increment_stat`.
