"""
Script kiểm tra tính toàn vẹn và độ đồng bộ 100% của 6 tệp từ điển ngôn ngữ i18n
(vi.json, en.json, zh.json, es.json, pt.json, fr.json)
"""
import os
import re
import sys
import json
from pathlib import Path

# Placeholder được i18n.py đưa vào str.format(**kwargs) nên có thể mang cả định dạng:
# {amount:,} {elapsed:.0f}. Regex PHẢI bỏ qua phần ":..." — bản chỉ so khớp `{ten}`
# thuần đã kết luận sai "0 lệch" đúng trên 6 key thiếu {amount}.
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^}]*)?\}")

# Đảm bảo in UTF-8 an toàn trên mọi hệ điều hành (Windows, Linux, Termux)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _flatten_dict(d: dict, prefix: str = "") -> dict:
    """Duỗi thẳng dictionary lồng nhau thành dạng key phẳng: 'a.b.c'."""
    items = {}
    for k, v in d.items():
        new_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key))
        else:
            items[new_key] = v
    return items


def validate_locales():
    # Tìm thư mục locales
    project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    locales_dir = project_root / "locales"

    if not locales_dir.exists():
        print(f"❌ Không tìm thấy thư mục locales tại: {locales_dir}")
        sys.exit(1)

    languages = ["vi", "en", "zh", "es", "pt", "fr"]
    lang_keys = {}
    lang_values = {}
    total_counts = {}

    # Đọc từng file
    for lang in languages:
        file_path = locales_dir / f"{lang}.json"
        if not file_path.exists():
            print(f"❌ Thiếu file từ điển: {file_path.name}")
            sys.exit(1)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                flat_data = _flatten_dict(data)
                lang_keys[lang] = set(flat_data.keys())
                lang_values[lang] = flat_data
                total_counts[lang] = len(flat_data)
        except Exception as e:
            print(f"❌ Lỗi cú pháp JSON trong file {file_path.name}: {e}")
            sys.exit(1)

    print("=" * 60)
    print("🌐 KIỂM TRA ĐỒNG BỘ ĐA NGÔN NGỮ (i18n Validation Report)")
    print("=" * 60)

    # Hiển thị số lượng key của từng ngôn ngữ
    for lang in languages:
        print(f"  • [{lang.upper()}] {lang}.json: {total_counts[lang]} keys")

    print("-" * 60)

    # Lấy tập hợp tất cả các key xuất hiện ở bất kỳ file nào
    all_keys = set()
    for keys in lang_keys.values():
        all_keys.update(keys)

    # Kiểm tra key thiếu ở từng ngôn ngữ
    has_error = False
    for lang in languages:
        missing = all_keys - lang_keys[lang]
        if missing:
            has_error = True
            print(f"❌ [{lang.upper()}] Thiếu {len(missing)} key sau:")
            for k in sorted(missing)[:10]:
                print(f"    - {k}")
            if len(missing) > 10:
                print(f"    ... và {len(missing) - 10} key khác.")

    # ─── PLACEHOLDER: nguồn bug "mất con số" trong câu dịch ───────────────────
    # Key thiếu `{amount}` vẫn chạy im lặng (str.format bỏ qua kwarg thừa), nên tin
    # nhắn gửi cho người dùng mất số tiền mà không có lỗi nào được ghi.
    ref_values = lang_values["vi"]
    for lang in languages:
        diffs = []
        for key, vi_text in ref_values.items():
            other = lang_values[lang].get(key)
            if other is None:
                continue
            mine = set(PLACEHOLDER_RE.findall(str(vi_text)))
            theirs = set(PLACEHOLDER_RE.findall(str(other)))
            if mine != theirs:
                diffs.append((key, sorted(mine), sorted(theirs)))
        if diffs:
            has_error = True
            print(f"❌ [{lang.upper()}] Lệch placeholder ở {len(diffs)} key:")
            for key, a, b in sorted(diffs)[:10]:
                print(f"    - {key}: vi={a} | {lang}={b}")
            if len(diffs) > 10:
                print(f"    ... và {len(diffs) - 10} key khác.")

    # ─── KÝ TỰ ĐIỀU KHIỂN: \\x07 từng làm hỏng chữ "all" ở 12 key/6 ngôn ngữ ───
    for lang in languages:
        ctrl = []
        for key, text in lang_values[lang].items():
            if isinstance(text, str):
                bad = sorted({hex(ord(ch)) for ch in text
                              if ord(ch) < 0x20 and ch not in "\n\t"})
                if bad:
                    ctrl.append((key, bad))
        if ctrl:
            has_error = True
            print(f"❌ [{lang.upper()}] {len(ctrl)} chuỗi chứa ký tự điều khiển:")
            for key, bad in sorted(ctrl)[:5]:
                print(f"    - {key}: {bad}")

    if has_error:
        print("\n❌ KẾT QUẢ: PHÁT HIỆN LỆCH GIỮA CÁC NGÔN NGỮ!")
        sys.exit(1)
    else:
        first_count = total_counts["vi"]
        print(f"\n✅ KẾT QUẢ: 100% HOÀN HẢO! Cả 6 ngôn ngữ đều đồng bộ chuẩn {first_count} keys/file.")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    validate_locales()
