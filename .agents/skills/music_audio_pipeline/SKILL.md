---
name: music_audio_pipeline
description: >
  Audio pipeline, FFmpeg, yt-dlp, libopus loading, Spotify resolving,
  voice connection lifecycle, and ARM/Termux performance optimizations for ZerynBot V2.
---

# Skill: Music & Audio Pipeline Optimization (ARM / Termux)

## 🎯 1. Mục Đích & Phạm Vi

Module Music (`bot/cogs/music.py` — facade của cog, logic nằm trong package `bot/music/`: `config`, `extractor`, `player`, `views`, `embeds`, `cog_voice`) là một trong những thành phần tiêu tốn nhiều CPU và tài nguyên mạng nhất. Kỹ năng này cung cấp các nguyên tắc kiến trúc bắt buộc để hệ thống âm nhạc chạy ổn định 24/7 trên thiết bị phần cứng yếu (ARM64 Android Termux / Raspberry Pi), không gây nghẽn Gateway Discord và không bị rò rỉ RAM.

---

## ⚡ 2. Cấu Hình & Tối Ưu Hóa FFmpeg Cho ARM

### 2.1 Cờ FFmpeg Đơn Luồng Bắt Buộc
Trên chip di động ARM (Snapdragon, MediaTek, Cortex), việc chạy FFmpeg đa luồng sẽ làm quá tải CPU và gây giật lag toàn hệ thống. Bắt buộc cấu hình:
- `-threads 1`: Ép chạy đơn luồng.
- `-b:a 96k`: Giới hạn bitrate âm thanh 96kbps (vừa vặn với Discord voice channel tiêu chuẩn, tiết kiệm 50% CPU so với 320k).

### 2.2 Cờ Kết Nối Ổn Định Đa Nền Tảng (Universal FFmpeg Before Flags)
**Quy tắc P0 — không gửi cờ mà build FFmpeg đang chạy không hiểu.** `-reconnect_on_network_error` và `-reconnect_on_http_error` chỉ tồn tại từ **FFmpeg 5.0**; trên build cũ hơn FFmpeg báo `Option not found` và THOÁT NGAY khi mở source, nghĩa là mọi lệnh `/play` chết chứ không chỉ mất tính năng tự reconnect. `bot/music/config.py` tách làm 3 mảnh và gate bằng probe một lần lúc import:

```python
FFMPEG_BEFORE_HEAD = (
    "-loglevel error "
    "-reconnect 1 "
    "-reconnect_streamed 1 "
)
FFMPEG_BEFORE_HTTP_RECONNECT = (          # CHI khi major version >= 5
    "-reconnect_on_network_error 1 "
    "-reconnect_on_http_error 5xx "
)
FFMPEG_BEFORE_TAIL = (
    "-reconnect_delay_max 2 "
    "-rw_timeout 10000000 "               # 10s socket timeout chống treo vĩnh viễn khi mạng drop
    "-fflags +genpts "
    "-probesize 512K "
    "-analyzeduration 500000 "
    '-user_agent "Mozilla/5.0 ... Chrome/122.0.0.0 Safari/537.36"'
)
FFMPEG_BEFORE = build_ffmpeg_before(ffmpeg_http_reconnect_supported())  # == bản cũ khi >= 5.0
FFMPEG_OPTS_COPY = "-vn -sn -c:a copy -threads 1"
FFMPEG_OPTS_ENCODE = "-vn -sn -threads 1"
```

> [!WARNING]
> - **yt-dlp player_client**: Luôn sử dụng `["android"]`. Tuyệt đối **KHÔNG dùng client `web`** vì trên Termux (không có JS runtime/cookies) sẽ gây lỗi bot verification (*"Sign in to confirm you're not a bot"*). Tuyệt đối **KHÔNG dùng client `tv`** vì YouTube trả lỗi `The page needs to be reloaded`.
> - **FFmpeg aresample**: Tuyệt đối không dùng `-af aresample=async=1` vì `async=1` giới hạn tốc độ bù drift về 1 sample/giây, khiến âm thanh bị co dãn cao độ/tốc độ (lúc nhanh lúc chậm) suốt 1 phút đầu.

### 2.3 Cơ Chế Bộ Nhớ Đệm 2 Tầng & Thread-Safe Worker Pool
- **Thread-Safety (`threading.local`)**: Mỗi worker thread sở hữu instance `YoutubeDL` độc lập, triệt tiêu hoàn toàn race condition trong khi vẫn giữ nguyên HTTP connection pool.
- **Tầng 1 (In-Memory RAM Cache - `cache.py`)**: Lưu trữ thông tin bài hát trong RAM (TTL 10 phút).
- **Tầng 2 (SQLite Disk Cache - `music_song_cache`)**: Lưu `payload` JSON trích xuất từ yt-dlp vào CSDL SQLite (`async_get_song_cache` / `async_set_song_cache`) với **TTL 6 giờ** (hoặc timestamp `expire` thực tế trích từ URL). Khi bot khởi động lại (restart), không cần tốn 2-4 giây trích xuất lại metadata từ YouTube mà phát ngay lập tức (< 0.5s).
- **Trích xuất song song & Khả năng chịu lỗi Playlist**: Khi người dùng gõ `/play`, bot khởi chạy đồng thời tác vụ kết nối voice và trích xuất metadata. Khi chạy `/playlist play`, bot tự động tìm bài đầu tiên khả dụng để phát ngay, nạp các bài còn lại ở background task theo batch 2 bài kèm fallback qua tiêu đề bài hát nếu link hỏng.
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

### 4.2 Giới Hạn Tải Đồng Thời (`MAX_PLAYERS = 6` trong `bot/music/config.py`)
Để tránh tràn RAM trên thiết bị 4GB RAM, hệ thống giới hạn tối đa 6 máy chủ phát nhạc cùng lúc. Nếu server thứ 7 yêu cầu, bot sẽ thông báo lịch sự máy chủ bận.

### 4.3 Tự Động Rời Kênh Khi Không Hoạt Động (3 Phút Auto-Disconnect)
Khi danh sách bài hát hết hoặc tất cả thành viên rời khỏi phòng Voice, khởi động bộ đếm 180s. Nếu không có bài mới sau 180s, bot tự động disconnect để trả lại tài nguyên. Nếu chính bot bị ngắt kết nối (kick/disconnect khỏi voice), `on_voice_state_update` sẽ lập tức cleanup player ngay lập tức.

**Quy tắc P0 — KHÔNG tự huỷ task đang chạy.** `_inactivity_countdown()` gọi `await self.stop()`, mà `stop()` lại gọi `_reset_inactivity_timer()`. Nếu hàm đó `cancel()` chính task đang chạy, `CancelledError` bắn vào await kế tiếp giữa `stop()` → bot **không rời voice**, embed Now Playing không bị xoá, `_drop()` không chạy (zombie player ăn slot `MAX_PLAYERS`) và mọi `stop()` sau đó đều no-op vì cờ `_cleanup_done`. Luôn so với `asyncio.current_task()` trước khi cancel:

```python
task = self._inactivity_task
self._inactivity_task = None
if task and not task.done() and task is not asyncio.current_task():
    task.cancel()
```

**Quy tắc P0 — không pop khỏi `queue` trước khi phát.** `_dispatch_next_async()` phải kiểm tra `vc.is_connected()` TRƯỚC rồi mới `pop(0)`; `_play()` return ngay khi chưa có voice client, nên pop trước sẽ **mất bài hát vĩnh viễn** khi voice vừa rời. Cả hai quy tắc được test hồi quy trong `tests/test_music_behavior.py`.

**Quy tắc P0 — watchdog phải đo frame audio, KHÔNG đo `get_elapsed()`.** Toàn bộ recovery cũ phụ thuộc `after()`, mà `after()` chỉ chạy khi audio thread thoát khỏi `source.read()`. Mạng kiểu "giữ socket nhưng ngừng trả data" làm thread kẹt vĩnh viễn → không `after()`, không recovery, im lặng vô hạn, vẫn chiếm slot `MAX_PLAYERS`. `get_elapsed()` được tính từ `time.time()` nên **vẫn tăng đều khi stream chết** (đo thực tế: 100s đồng hồ tường nhưng chỉ 0.4s audio) — dùng nó làm mốc phát hiện treo là vô nghĩa. Cách làm đúng: `_bind_audio_clock()` gán `read` lên **instance** của source (không proxy hoá, để `isinstance(vc.source, PCMVolumeTransformer)`, `.volume`, `.cleanup()` còn nguyên), đếm `_audio_frames` và cập nhật `_last_data_mono`; `_stall_watchdog()` so đồng hồ đó với `STALL_TIMEOUT_SECONDS`. Pause thì discord.py gửi silence mà không đọc source → **phải re-baseline `_last_data_mono`**, không sẽ cắt bài hát đang tạm dừng. Sau khi cắt phải `asyncio.wait_for(asyncio.to_thread(source.cleanup), STALL_CLEANUP_TIMEOUT_SECONDS)` cho source cũ (thread kẹt nên `finally` của discord.py không chạy → ffmpeg mồ côi); có trần thời gian vì một ffmpeg kẹt trong D-state sẽ giữ `_recovering=True` vĩnh viễn. Cuối cùng phải **kiểm tra `_active_source` còn None không** trước khi phát lại — nếu `/play` hoặc `/skip` của user đã giao source mới trong lúc chờ dọn thì phải nhường, không cắt đè. Test: `tests/test_phase5c_music_watchdog.py`.

**Quy tắc P0 — `after()` phải được bind với source đang phát.** `_play()` truyền `functools.partial(self._after_play, source)` và `_after_play` bỏ qua callback có `bound_source is not self._active_source`. Không có guard này, EOF muộn của stream vừa bị cắt bị tính là "bài mới kết thúc" → nhảy 2 bài và đốt ngân sách recovery nhầm chỗ.

**Quy tắc P0 — sửa hàng đợi bằng slice, không gán list mới.** `/remove`, `/clearqueue`, `/jump` đi qua `MusicPlayer.remove_track_at()/clear_queue()/truncate_queue_to()` (dùng `del q[...]`). `player.queue = player.queue[k:]` sẽ mồ côi hoá mọi tham chiếu đang giữ list cũ; test tĩnh `test_no_code_rebinds_player_queue` cấm mẫu `queue =` trong `bot/`. Không bọc các thao tác này bằng `_play_lock`: list op là một lời gọi C nên đã atomic dưới GIL, còn lấy lock sẽ đẩy slash command quá cửa 3s của Discord mỗi khi `_play()` đang chờ yt-dlp.

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
