"""
Script kiểm tra tính toàn vẹn và độ đồng bộ 100% của 6 tệp từ điển ngôn ngữ i18n
(vi.json, en.json, zh.json, es.json, pt.json, fr.json)
"""
import os
import sys
import json
from pathlib import Path

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

    if has_error:
        print("\n❌ KẾT QUẢ: PHÁT HIỆN LỆCH KEY GIỮA CÁC NGÔN NGỮ!")
        sys.exit(1)
    else:
        first_count = total_counts["vi"]
        print(f"\n✅ KẾT QUẢ: 100% HOÀN HẢO! Cả 6 ngôn ngữ đều đồng bộ chuẩn {first_count} keys/file.")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    validate_locales()
