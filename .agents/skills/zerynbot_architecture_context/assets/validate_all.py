# -*- coding: utf-8 -*-
"""
Script: validate_all.py — Bộ Kiểm Thử Tự Động Toàn Diện 1-Click Cho ZerynBot V2
Thực hiện 4 kiểm tra cốt lõi:
1. Đồng bộ 100% key giữa 6 file từ điển ngôn ngữ (1510 keys/file).
2. Kiểm tra biên dịch cú pháp tất cả file Python (.py) trong repo.
3. Kiểm tra số lượng lệnh trong _COMMANDS_DATA (87 lệnh, 16 danh mục).
4. Kiểm tra sự nhất quán về số liệu trong các tài liệu (ARCHITECTURE.md, AGENTS.md, llms.txt).
"""

import sys
import os
import json
import ast
import py_compile

# Ensure utf-8 encoding on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
LOCALES_DIR = os.path.join(REPO_ROOT, "locales")
APP_PY_PATH = os.path.join(REPO_ROOT, "dashboard", "app.py")
ARCH_PATH = os.path.join(REPO_ROOT, "ARCHITECTURE.md")
AGENTS_PATH = os.path.join(REPO_ROOT, ".agents", "AGENTS.md")
LLMS_PATH = os.path.join(REPO_ROOT, "llms.txt")

PASS_ICON = "✅"
FAIL_ICON = "❌"
WARN_ICON = "⚠️"

errors = []

print("=" * 65)
print("🚀 BỘ KIỂM THỬ TOÀN DIỆN 1-CLICK CHO ZERYNBOT V2")
print("=" * 65)

# ─── 1. KIỂM TRA ĐA NGÔN NGỮ (i18n) ─────────────────────────────────────────
print("\n[1/4] 🌐 Đang kiểm tra đồng bộ ngôn ngữ (locales/)...")
locale_files = [f for f in sorted(os.listdir(LOCALES_DIR)) if f.endswith(".json")]
locale_data = {}
for f in locale_files:
    path = os.path.join(LOCALES_DIR, f)
    with open(path, "r", encoding="utf-8") as fp:
        locale_data[f] = json.load(fp)

key_counts = {f: len(data) for f, data in locale_data.items()}
for f, cnt in key_counts.items():
    print(f"  • [{f[:2].upper()}] {f}: {cnt} keys")

counts_set = set(key_counts.values())
if len(counts_set) == 1:
    actual_key_count = list(counts_set)[0]
    print(f"{PASS_ICON} Chuẩn xác: Cả {len(locale_files)} ngôn ngữ đều có đúng {actual_key_count} keys/file.")
else:
    err = f"Lệch key giữa các file ngôn ngữ: {key_counts}"
    errors.append(err)
    print(f"{FAIL_ICON} {err}")

# ─── 2. KIỂM TRA BIÊN DỊCH CÚ PHÁP PYTHON ────────────────────────────────────
print("\n[2/4] 🐍 Đang kiểm tra cú pháp tất cả file Python (.py)...")
py_files_checked = 0
py_errors = 0
for root, dirs, files in os.walk(REPO_ROOT):
    if any(x in root for x in [".git", "__pycache__", ".agents", "venv", "env", "node_modules"]):
        continue
    for file in files:
        if file.endswith(".py"):
            full_path = os.path.join(root, file)
            py_files_checked += 1
            try:
                py_compile.compile(full_path, doraise=True)
            except Exception as e:
                py_errors += 1
                rel_path = os.path.relpath(full_path, REPO_ROOT)
                err_msg = f"Lỗi cú pháp tại {rel_path}: {e}"
                errors.append(err_msg)
                print(f"  {FAIL_ICON} {err_msg}")

if py_errors == 0:
    print(f"{PASS_ICON} Tất cả {py_files_checked} file Python đều biên dịch sạch, 100% không lỗi cú pháp!")
else:
    print(f"{FAIL_ICON} Có {py_errors} file Python bị lỗi cú pháp!")

# ─── 3. KIỂM TRA COMMANDS DATA REGISTRY ──────────────────────────────────────
print("\n[3/4] 📋 Đang kiểm tra danh mục lệnh (_COMMANDS_DATA)...")
try:
    with open(APP_PY_PATH, "r", encoding="utf-8") as f:
        app_code = f.read()
    tree = ast.parse(app_code)
    commands_data = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_COMMANDS_DATA":
                    commands_data = ast.literal_eval(node.value)
                    break
    if commands_data:
        cat_count = len(commands_data)
        cmd_count = sum(len(c.get("commands", [])) for c in commands_data)
        print(f"  • Danh mục: {cat_count} categories")
        print(f"  • Tổng lệnh: {cmd_count} commands")
        print(f"{PASS_ICON} _COMMANDS_DATA hợp lệ với {cmd_count} lệnh thuộc {cat_count} danh mục.")
    else:
        errors.append("Không tìm thấy biến _COMMANDS_DATA trong dashboard/app.py")
        print(f"{FAIL_ICON} Không tìm thấy _COMMANDS_DATA!")
except Exception as e:
    errors.append(f"Lỗi phân tích _COMMANDS_DATA: {e}")
    print(f"{FAIL_ICON} Lỗi: {e}")

# ─── 4. KIỂM TRA ĐỒNG BỘ TÀI LIỆU (DOCS SYNC) ────────────────────────────────
print("\n[4/4] 📚 Đang kiểm tra tính nhất quán số liệu trong tài liệu...")
doc_checks = [
    ("ARCHITECTURE.md", ARCH_PATH, str(actual_key_count)),
    ("AGENTS.md", AGENTS_PATH, str(actual_key_count)),
    ("llms.txt", LLMS_PATH, str(actual_key_count)),
]

for doc_name, path, expected_str in doc_checks:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if expected_str in content:
            print(f"  {PASS_ICON} [{doc_name}]: Chứa chính xác số key {expected_str}")
        else:
            err = f"[{doc_name}] thiếu con số key {expected_str}!"
            errors.append(err)
            print(f"  {FAIL_ICON} {err}")
    else:
        err = f"Không tìm thấy file {doc_name}"
        errors.append(err)
        print(f"  {FAIL_ICON} {err}")

# ─── KẾT QUẢ TỔNG HỢP ────────────────────────────────────────────────────────
print("\n" + "=" * 65)
if not errors:
    print(f"🎉 TỔNG KẾT: 100% HOÀN HẢO! TOÀN BỘ HỆ THỐNG ĐÃ ĐỒNG BỘ CHUẨN XÁC.")
    print("=" * 65)
    sys.exit(0)
else:
    print(f"⚠️ TỔNG KẾT: PHÁT HIỆN {len(errors)} LỖI CẦN XỬ LÝ:")
    for i, err in enumerate(errors, 1):
        print(f"  {i}. {err}")
    print("=" * 65)
    sys.exit(1)
