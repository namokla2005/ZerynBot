import sys
import os
import datetime
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def send_status(status_type: str):
    webhook_url = config.STATUS_WEBHOOK_URL
    if not webhook_url:
        print("Không tìm thấy STATUS_WEBHOOK_URL trong cấu hình.")
        return

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    if status_type == "start":
        embed = {
            "title": "🟢 Hệ thống đã trực tuyến",
            "description": "Cả Bot và Web Dashboard đều đã khởi động thành công và đang hoạt động ổn định.",
            "color": 0x57F287,
            "timestamp": now
        }
    elif status_type == "stop":
        embed = {
            "title": "🔴 Hệ thống đã dừng",
            "description": "Bot và Web Dashboard đã nhận lệnh tắt và đang dừng hoạt động.",
            "color": 0xED4245,
            "timestamp": now
        }
    else:
        print("Loại trạng thái không hợp lệ. Chỉ chấp nhận 'start' hoặc 'stop'.")
        return

    payload = {"embeds": [embed]}
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"Đã gửi thông báo trạng thái '{status_type}' thành công!")
    except Exception as e:
        print(f"Lỗi khi gửi webhook: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Vui lòng cung cấp tham số 'start' hoặc 'stop'.")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    send_status(action)
