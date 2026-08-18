import sys
import os
import datetime
import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

def send_status(status_type: str):
    webhook_url = config.STATUS_WEBHOOK_URL
    if not webhook_url:
        print("[StatusWebhook] STATUS_WEBHOOK_URL not configured.")
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
        print("[StatusWebhook] Invalid status type. Use 'start' or 'stop'.")
        return

    payload = {"embeds": [embed]}
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"[StatusWebhook] Sent '{status_type}' notification successfully!")
    except Exception as e:
        print(f"[StatusWebhook] Error sending webhook: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("[StatusWebhook] Please provide 'start' or 'stop' argument.")
        sys.exit(1)
    
    action = sys.argv[1].lower()
    send_status(action)
