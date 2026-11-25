"""check_missing_css.py — Bắt lỗi "xoá nhầm selector class CSS vẫn còn dùng" trong diff.

Bối cảnh: commit đổi theme 9206a56 từng xoá nhầm .send-section/.empty-state/
.section-header/.section-title/.divider/.color-text-input khỏi dashboard/static/css/
style.css → khối "Gửi đến Discord" và "Embeds đã lưu" của trang Embeds mất style,
không test nào bắt được.

Cách dùng (từ repo root D:/Project/Discord Bots/v2):
    python .agents/skills/dashboard_dev_guide/assets/check_missing_css.py          # diff working tree/staged so với HEAD
    python .agents/skills/dashboard_dev_guide/assets/check_missing_css.py HEAD~1   # so với commit cụ thể

Thuật toán:
1. Lấy `git diff <base> -- dashboard/static/css/style.css`.
2. Trích selector class bị XOÁ ở các dòng '-' (regex '^-\\.Ten').
3. Class nào vẫn XUẤT HIỆN (word-boundary) trong template/JS, đồng thời hiện KHÔNG
   còn định nghĩa trong style.css → cảnh báo "xoá nhầm".
4. Exit 1 nếu có cảnh báo (dùng được trong pre-commit gate) — ngược lại exit 0.

Lưu ý: nội dung Jinja ({{ }} / {% %}) và template-literal JS (${ }) được lọc bỏ
trước khi soát usage để tránh false-positive.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # repo root (…/.agents/skills/<skill>/assets/)
CSS_REL = "dashboard/static/css/style.css"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, errors="replace"
    )
    return result.stdout


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    diff = _git("diff", base, "--", CSS_REL)

    removed = set()
    for line in diff.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            match = re.match(r"^\s*-\.([A-Za-z0-9_-]+)", line)
            if match:
                removed.add(match.group(1))

    if not removed:
        print("✅ Không có selector class nào bị xoá khỏi style.css trong diff.")
        return 0

    css_path = ROOT / CSS_REL
    current_css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    candidates = {c for c in removed if ("." + c) not in current_css}

    if not candidates:
        print(f"✅ {len(removed)} class bị xoá trong diff đều đã được thay thế/định nghĩa lại.")
        return 0

    scan_dirs = [
        (ROOT / "dashboard" / "templates", "*.html"),
        (ROOT / "dashboard" / "static" / "js", "*.js"),
    ]
    usage: dict[str, list[str]] = {}
    for folder, pattern in scan_dirs:
        for path in sorted(folder.glob(pattern)):
            src = path.read_text(encoding="utf-8", errors="replace")
            src = re.sub(r"{{.*?}}|{%.*?%}|\$\{.*?\}", " ", src, flags=re.S)
            hit = sorted(
                c for c in candidates
                if re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", src)
            )
            if hit:
                usage[path.name] = hit

    if usage:
        print("❌ Class bị xoá khỏi style.css nhưng VẪN còn dùng trong template/JS:")
        for name, items in usage.items():
            print(f"  - {name}: {items}")
        print("→ Khôi phục định nghĩa CSS (hoặc cập nhật nơi dùng) trước khi commit.")
        return 1

    print(f"✅ {len(candidates)} class bị xoá trong diff, không class nào còn được dùng.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
