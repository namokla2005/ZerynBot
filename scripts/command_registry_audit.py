# -*- coding: utf-8 -*-
"""Đối chiếu registry `_COMMANDS_DATA` với lệnh thật đang khai báo trong cog.

Chạy:  python scripts/command_registry_audit.py [--json]      (exit 1 khi lệch)

Lệch registry là lỗi IM LẶNG: AI Chat được nạp đúng bản danh sách này làm system
prompt, /help tra cứu theo nó, trang /docs của Dashboard render từ nó — nên một
lệnh mới thêm mà không ghi vào đây nghĩa là bot "không biết" chính lệnh của mình.
"""
import ast
import json
import sys
from pathlib import Path

# Console Windows mac dinh cp1252: in chu co dau cua Viet Nam ra la UnicodeEncodeError,
# nen phai ep UTF-8 truoc khi bat ky print nao chay (giong dashboard/app_factory.py).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - Python < 3.7 / stream da dong
        pass

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "bot" / "cogs"
sys.path.insert(0, str(ROOT))

GROUP_DECOS = {"group", "hybrid_group"}
LEAF_DECOS = {"command", "hybrid_command"}


def parts_of(func):
    """'@commands.hybrid_command' -> ['commands', 'hybrid_command']."""
    out = []
    cur = func
    while isinstance(cur, ast.Attribute):
        out.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        out.append(cur.id)
    out.reverse()
    return out


def kw(call, key):
    """Đọc một keyword (hoặc tham số đầu) dạng literal của decorator."""
    if call is None:
        return None
    for k in call.keywords:
        if k.arg == key:
            try:
                return ast.literal_eval(k.value)
            except Exception:
                return None
    if call.args:
        try:
            return ast.literal_eval(call.args[0])
        except Exception:
            return None
    return None


def analyze(path):
    """Trả về [(tên_lệnh_đầy_đủ, kind, file, decorator)] của một file cog.

    Nhận diện cả 3 kiểu khai báo: `@commands.hybrid_command`, `@<group_func>.command`
    và `@<biến_app_commands.Group>.command`. Bản thân group cha không phải thứ user
    gõ được nên bị loại, chỉ giữ lá và lệnh con.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    parents = {}                      # tên biến/hàm cha -> tên lệnh cha thật
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(value, ast.Call):
            continue
        if parts_of(value.func)[-1:] != ["Group"]:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name):
                parents[tgt.id] = kw(value, "name") or tgt.id

    rows = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            call = d if isinstance(d, ast.Call) else None
            ps = parts_of(call.func if call else d)
            if not ps or ps[-1] not in GROUP_DECOS | LEAF_DECOS:
                continue
            leaf, owner = ps[-1], (ps[-2] if len(ps) >= 2 else None)
            name = kw(call, "name") or node.name
            if leaf in GROUP_DECOS:
                parents[node.name] = name
            elif owner in parents:
                rows.append((f"{parents[owner]} {name}", "sub", path.name, leaf))
            elif owner in (None, "commands", "app_commands"):
                rows.append((name, "leaf", path.name, leaf))
            else:
                rows.append((f"?{owner}.{name}", "unresolved", path.name, leaf))
    return rows


def actual_commands():
    """{tên_lệnh_thật: [file:decorator,...]} — gộp toàn bộ cog."""
    actual = {}
    for p in sorted(COGS.glob("*.py")):
        for name, _kind, fname, deco in analyze(p):
            actual.setdefault(name.lower(), []).append(f"{fname}:{deco}")
    return actual


def registry_raw():
    """Toàn bộ danh mục gốc (nguyên dict) để test soi từng field của entry."""
    import commands_data

    return commands_data._COMMANDS_DATA


def registry_commands():
    """{tên_lệnh_trong_registry: danh_mục}."""
    reg = {}
    for cat in registry_raw():
        for c in cat.get("commands", []):
            reg[c["name"].strip().lower()] = cat["category"]
    return reg


def drift():
    """(missing_trong_registry, stale_không_còn_trong_code)."""
    actual, reg = actual_commands(), registry_commands()
    return (
        sorted(k for k in actual if k not in reg),
        sorted(k for k in reg if k not in actual),
        actual,
        reg,
    )


if __name__ == "__main__":
    missing, stale, actual, reg = drift()
    print(f"Lệnh thật khai báo trong cog : {len(actual)}")
    print(f"Entry trong _COMMANDS_DATA   : {len(reg)}")
    print(f"\n=== CÓ TRONG CODE, THIẾU TRONG REGISTRY ({len(missing)}) ===")
    for k in missing:
        print(f"  {k:32s} <- {', '.join(actual[k])}")
    print(f"\n=== CÓ TRONG REGISTRY, KHÔNG TÌM THẤY TRONG CODE ({len(stale)}) ===")
    for k in stale:
        print(f"  {k:32s} ({reg[k]})")
    if "--json" in sys.argv:
        print(json.dumps({"missing": missing, "stale": stale}, ensure_ascii=False))
    sys.exit(1 if (missing or stale) else 0)
